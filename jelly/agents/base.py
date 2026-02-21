import re
import time

import anthropic

from jelly.config import Config


class BaseAgent:
    """Base agent wrapping the Anthropic SDK.

    Stateless — no conversation history. The orchestrator manages all state.
    """

    def __init__(self, system_prompt: str, config: Config) -> None:
        """Initialize with a system prompt and config.

        Creates an anthropic.Anthropic() client (reads ANTHROPIC_API_KEY from env).
        """
        self.system_prompt = system_prompt
        self.config = config
        self.client = anthropic.Anthropic()

    def call(self, user_message: str, max_tokens: int) -> str:
        """Make a single API call to Claude.

        Handles retries (3 attempts, exponential backoff: 1s, 2s, 4s).
        For extended thinking: temperature=1, thinking={"type": "enabled", "budget_tokens": N}.

        Args:
            user_message: The user-role message content.
            max_tokens: Maximum tokens for the response.

        Returns:
            The text content of Claude's response.

        Raises:
            anthropic.APIError: If all retry attempts fail.
        """
        backoff_delays = [1, 2, 4]

        for attempt in range(3):
            try:
                if self.config.use_extended_thinking:
                    budget = self.config.thinking_budget_tokens
                    effective_max = max(max_tokens, budget + 1024)
                else:
                    effective_max = max_tokens
                    budget = 0

                kwargs: dict = {
                    "model": self.config.model,
                    "max_tokens": effective_max,
                    "system": self.system_prompt,
                    "messages": [{"role": "user", "content": user_message}],
                }

                if budget:
                    kwargs["temperature"] = 1
                    kwargs["thinking"] = {
                        "type": "enabled",
                        "budget_tokens": budget,
                    }

                # Stream to avoid 10-minute timeout on long requests
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

        return ""  # unreachable, but satisfies type checker

    @staticmethod
    def extract_code_blocks(response: str) -> list[str]:
        """Extract content from ```python ... ``` fences in a response.

        Args:
            response: Raw text response from Claude.

        Returns:
            List of code strings found inside python fences.
        """
        return re.findall(r"```python\s*\n(.*?)```", response, re.DOTALL)
