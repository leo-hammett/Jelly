from __future__ import annotations

import anthropic

from jelly.config import Config

PLANNER_SYSTEM_PROMPT = """\
You are a Requirements Planner for an automated code-generation system called \
Jelly. Your job is to help users define clear, complete software requirements \
through iterative conversation.

## Your approach

1. Start by understanding what the user wants to build at a high level.
2. Ask ONE focused follow-up question at a time to clarify ambiguities.
3. Cover these areas progressively:
   - Purpose and target users
   - Core functional requirements (inputs, outputs, behavior)
   - API surface (function signatures, types, module organization)
   - Edge cases and error handling
   - Non-functional requirements (performance, dependencies, constraints)
4. After gathering enough detail, proactively suggest implementation \
approaches, technology choices, or architecture patterns.
5. Keep responses concise — no more than 2-3 short paragraphs per message.

## When suggesting implementations

When you have enough context, offer concrete recommendations:
- Recommended language and libraries
- File/module organization
- Algorithm or data-structure choices
- Tradeoffs worth considering

Label suggestions clearly so the user can accept, modify, or skip them.

## Tone

Be direct and practical. Avoid filler. Ask questions that meaningfully \
reduce ambiguity — never ask something the user already answered.\
"""

GENERATE_SYSTEM_PROMPT = """\
You generate structured requirements documents in markdown. Follow this \
exact format:

# Project: <Name>

## Overview
<One paragraph summary>

## Functional Requirements

### FR-1: <Title>
<Description with inputs, outputs, constraints, examples>

### FR-2: <Title>
...

## API Specification
```<language>
<function/method signatures with docstrings>
```

## Edge Cases
- <case 1>
- <case 2>
...

Use precise types. Include concrete examples. Every requirement must be \
testable. Do NOT include implementation code — only signatures and specs.\
"""


class Planner:
    """Stateful multi-turn agent for building requirements interactively."""

    def __init__(self, config: Config) -> None:
        self.config = config
        self.client = anthropic.Anthropic()
        self.messages: list[dict[str, str]] = []

    def start(self, initial_description: str | None = None) -> str:
        """Begin the planning conversation.

        If initial_description is provided, treat it as the user's first
        message. Otherwise, the planner asks what they want to build.
        """
        if initial_description:
            self.messages.append({"role": "user", "content": initial_description})
            return self._call()

        opening = (
            "What would you like to build? Give me a brief description "
            "and I'll help you turn it into a clear requirements spec."
        )
        return opening

    def respond(self, user_input: str) -> str:
        """Continue the conversation with the user's latest input."""
        self.messages.append({"role": "user", "content": user_input})
        return self._call()

    def generate_requirements(self) -> str:
        """Produce a structured requirements markdown from the conversation."""
        conversation_summary = "\n\n".join(
            f"{'User' if m['role'] == 'user' else 'Planner'}: {m['content']}"
            for m in self.messages
        )

        gen_messages = [
            {
                "role": "user",
                "content": (
                    "Based on the following planning conversation, generate "
                    "a complete requirements document.\n\n"
                    f"## Conversation\n\n{conversation_summary}\n\n"
                    "Generate the full requirements document in markdown. "
                    "Include all functional requirements, API specification "
                    "with typed signatures, and edge cases discussed."
                ),
            }
        ]

        return self._raw_call(GENERATE_SYSTEM_PROMPT, gen_messages)

    def suggest_implementation(self) -> str:
        """Suggest technologies and architecture based on conversation so far."""
        self.messages.append({
            "role": "user",
            "content": (
                "Based on everything we've discussed, what implementation "
                "approach do you recommend? Suggest specific technologies, "
                "libraries, file organization, and any important tradeoffs."
            ),
        })
        return self._call()

    def _call(self) -> str:
        """Make an API call with the full conversation history."""
        response_text = self._raw_call(PLANNER_SYSTEM_PROMPT, self.messages)
        self.messages.append({"role": "assistant", "content": response_text})
        return response_text

    def _raw_call(self, system: str, messages: list[dict]) -> str:
        """Send messages to the API with retry logic."""
        import time

        backoff_delays = [1, 2, 4]

        for attempt in range(3):
            try:
                kwargs: dict = {
                    "model": self.config.model,
                    "max_tokens": 4096,
                    "system": system,
                    "messages": messages,
                }

                if self.config.use_extended_thinking:
                    budget = self.config.thinking_budget_tokens
                    kwargs["max_tokens"] = max(4096, budget + 1024)
                    kwargs["temperature"] = 1
                    kwargs["thinking"] = {
                        "type": "enabled",
                        "budget_tokens": budget,
                    }

                text_parts: list[str] = []
                with self.client.messages.stream(**kwargs) as stream:
                    for event in stream:
                        if event.type == "content_block_delta":
                            if event.delta.type == "text_delta":
                                text_parts.append(event.delta.text)

                return "".join(text_parts)

            except anthropic.APIError:
                if attempt == 2:
                    raise
                time.sleep(backoff_delays[attempt])

        return ""
