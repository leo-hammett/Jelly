from __future__ import annotations

import json
from typing import Any

from jelly.agents.base import BaseAgent
from jelly.config import Config

JUDGE_SYSTEM_PROMPT = """\
You are a Requirements Judge. You evaluate software requirements documents \
for clarity, completeness, and readiness for automated code generation.

Score the requirements on five dimensions (each 0-20, totalling 0-100):

1. **Specificity** (0-20): Are inputs, outputs, types, and behaviors \
precisely described? Vague language like "should handle errors" scores low; \
explicit error types and messages score high.

2. **Edge Cases** (0-20): Are boundary conditions, empty inputs, nulls, \
large inputs, and error scenarios explicitly listed?

3. **API Surface** (0-20): Are function signatures, parameter types, return \
types, and module organization clearly defined? Is there a concrete API spec?

4. **Testability** (0-20): Can an engineer write automated tests from the \
spec alone? Are expected outputs for given inputs provided? Are examples included?

5. **Completeness** (0-20): Does the spec cover all features needed for a \
working product? Are there obvious gaps or missing requirements?

Respond ONLY with JSON inside a code block. No other text.\
"""


class Judge:
    """Scores requirements documents on readiness for code generation."""

    def __init__(self, config: Config) -> None:
        self.config = config
        self.agent = BaseAgent(JUDGE_SYSTEM_PROMPT, config)

    def score(self, requirements: str) -> dict[str, Any]:
        """Score a requirements document on a 0-100 scale.

        Returns a dict with overall score, per-dimension breakdown,
        actionable suggestions, and a boolean ready flag (score >= 70).
        """
        prompt = (
            f"## Requirements Document\n\n{requirements}\n\n"
            "Score this requirements document. For each dimension, provide:\n"
            "- score (integer 0-20)\n"
            "- feedback (one sentence explaining the score)\n\n"
            "Also provide 3-5 specific, actionable suggestions to improve "
            "the weakest areas.\n\n"
            "Respond with JSON in a code block:\n"
            "```json\n"
            "{\n"
            '  "dimensions": {\n'
            '    "specificity": {"score": 0, "feedback": "..."},\n'
            '    "edge_cases": {"score": 0, "feedback": "..."},\n'
            '    "api_surface": {"score": 0, "feedback": "..."},\n'
            '    "testability": {"score": 0, "feedback": "..."},\n'
            '    "completeness": {"score": 0, "feedback": "..."}\n'
            "  },\n"
            '  "suggestions": ["...", "...", "..."]\n'
            "}\n"
            "```"
        )

        response = self.agent.call(prompt, 4096)
        return self._parse_response(response)

    def _parse_response(self, response: str) -> dict[str, Any]:
        raw = _parse_json(response)
        if raw is None:
            return _default_result()

        dimensions = raw.get("dimensions", {})
        total = 0
        for dim in ("specificity", "edge_cases", "api_surface",
                     "testability", "completeness"):
            entry = dimensions.get(dim, {})
            s = entry.get("score", 0)
            s = max(0, min(20, int(s)))
            entry["score"] = s
            entry["max"] = 20
            entry.setdefault("feedback", "")
            dimensions[dim] = entry
            total += s

        suggestions = raw.get("suggestions", [])
        if not isinstance(suggestions, list):
            suggestions = []

        return {
            "score": total,
            "dimensions": dimensions,
            "suggestions": suggestions[:5],
            "ready": total >= 70,
        }


def _parse_json(response: str) -> Any:
    """Extract JSON from an LLM response, handling code fences."""
    candidates = list(BaseAgent.extract_code_blocks(response)) + [response.strip()]
    for text in candidates:
        text = text.strip()
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass
    return None


def _default_result() -> dict[str, Any]:
    dims = {}
    for dim in ("specificity", "edge_cases", "api_surface",
                 "testability", "completeness"):
        dims[dim] = {"score": 0, "max": 20, "feedback": "Could not evaluate"}
    return {
        "score": 0,
        "dimensions": dims,
        "suggestions": ["Unable to parse scoring response"],
        "ready": False,
    }
