from __future__ import annotations

import json
from typing import Any

from jelly.agents.base import BaseAgent
from jelly.capability import CapabilityAssessment
from jelly.config import Config

CAPABILITY_CHECKER_SYSTEM_PROMPT = """\
You are a Capability Checker for Jelly, an automated build-and-test system.

You must decide whether the CURRENT builder setup can likely produce and verify
a working solution for the provided requirements.

Assess based on:
- deterministic preflight checks
- available tools and environment
- MCP baseline diagnostics
- recursion depth context
- repository context

Return ONLY JSON inside a code block with this schema:
```json
{
  "capable": true,
  "confidence": 0.0,
  "reasons": ["..."],
  "missing_capabilities": ["..."],
  "recommended_child_requirements": "..."
}
```

Rules:
- confidence is a float in [0, 1].
- If you are uncertain, lower confidence.
- Keep reasons and missing_capabilities concise and concrete.
- recommended_child_requirements should be empty if capable is true.
"""


class CapabilityChecker:
    def __init__(self, config: Config) -> None:
        self.config = config
        self.agent = BaseAgent(CAPABILITY_CHECKER_SYSTEM_PROMPT, config)

    def check(
        self,
        requirements: str,
        repo_context: dict[str, Any],
        available_tools: dict[str, bool],
        preflight_checks: list[dict[str, Any]],
        mcp_baseline_status: dict[str, Any],
        depth: int,
    ) -> CapabilityAssessment:
        prompt = (
            "## Requirements\n\n"
            f"{requirements}\n\n"
            "## Deterministic preflight checks\n\n"
            f"{json.dumps(preflight_checks, indent=2)}\n\n"
            "## Available tools\n\n"
            f"{json.dumps(available_tools, indent=2)}\n\n"
            "## MCP baseline status\n\n"
            f"{json.dumps(mcp_baseline_status, indent=2)}\n\n"
            "## Repository context\n\n"
            f"{json.dumps(repo_context, indent=2)}\n\n"
            "## Recursion depth\n\n"
            f"{depth}\n"
        )
        response = self.agent.call(prompt, self.config.capability_checker_max_tokens)
        return self._parse(response)

    def _parse(self, response: str) -> CapabilityAssessment:
        raw = _parse_json(response)
        if raw is None:
            return CapabilityAssessment(
                capable=False,
                confidence=0.0,
                reasons=["Could not parse capability assessment response."],
                missing_capabilities=[],
                recommended_child_requirements="",
                assessment_available=False,
            )

        capable = bool(raw.get("capable", False))
        confidence = raw.get("confidence", 0.0)
        try:
            confidence = float(confidence)
        except (TypeError, ValueError):
            confidence = 0.0
        confidence = max(0.0, min(1.0, confidence))

        reasons = raw.get("reasons", [])
        if not isinstance(reasons, list):
            reasons = []
        reasons = [str(item) for item in reasons][:8]

        missing = raw.get("missing_capabilities", [])
        if not isinstance(missing, list):
            missing = []
        missing = [str(item) for item in missing][:8]

        child_requirements = raw.get("recommended_child_requirements", "")
        if not isinstance(child_requirements, str):
            child_requirements = ""

        return CapabilityAssessment(
            capable=capable,
            confidence=confidence,
            reasons=reasons,
            missing_capabilities=missing,
            recommended_child_requirements=child_requirements.strip(),
            assessment_available=True,
        )


def _parse_json(response: str) -> Any:
    candidates = list(BaseAgent.extract_code_blocks(response)) + [response.strip()]
    for text in candidates:
        try:
            return json.loads(text.strip())
        except json.JSONDecodeError:
            pass
    return None
