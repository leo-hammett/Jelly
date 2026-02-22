from __future__ import annotations

import os
import shutil
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from jelly.config import Config
from jelly.run_logging import RunLogger


@dataclass
class PreflightCheck:
    name: str
    ok: bool
    severity: str  # "hard" | "soft"
    message: str


@dataclass
class CapabilityAssessment:
    capable: bool
    confidence: float
    reasons: list[str] = field(default_factory=list)
    missing_capabilities: list[str] = field(default_factory=list)
    recommended_child_requirements: str = ""
    assessment_available: bool = True


@dataclass
class CapabilityDecision:
    capable: bool
    confidence: float
    reasons: list[str] = field(default_factory=list)
    missing_capabilities: list[str] = field(default_factory=list)
    recommended_child_requirements: str = ""
    mcp_baseline_status: dict[str, Any] = field(default_factory=dict)
    preflight_checks: list[PreflightCheck] = field(default_factory=list)
    depth: int = 0

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["preflight_checks"] = [asdict(c) for c in self.preflight_checks]
        return payload


def assess_capability(
    requirements: str,
    requirements_path: str,
    project_dir: str,
    config: Config,
    depth: int = 0,
    logger: RunLogger | None = None,
) -> CapabilityDecision:
    checks = _run_preflight_checks(requirements_path, project_dir)
    mcp_baseline = _mcp_baseline_status()

    if config.require_mcp_baseline:
        for key, status in mcp_baseline.items():
            if not status.get("available", False):
                checks.append(
                    PreflightCheck(
                        name=f"mcp_{key}",
                        ok=False,
                        severity="hard",
                        message=f"{key} MCP baseline unavailable: {status.get('detail', '')}",
                    )
                )

    hard_failures = [c for c in checks if not c.ok and c.severity == "hard"]
    if hard_failures:
        reasons = [c.message for c in hard_failures]
        missing = [c.name for c in hard_failures]
        decision = CapabilityDecision(
            capable=False,
            confidence=0.0,
            reasons=reasons,
            missing_capabilities=missing,
            recommended_child_requirements=_default_child_requirements(
                requirements,
                reasons,
            ),
            mcp_baseline_status=mcp_baseline,
            preflight_checks=checks,
            depth=depth,
        )
        _log_capability(logger, decision, "hard_preflight_failure")
        return decision

    from jelly.agents.capability_checker import CapabilityChecker

    checker = CapabilityChecker(config)
    llm_assessment = checker.check(
        requirements=requirements,
        repo_context=_repo_context(),
        available_tools=_available_tools_snapshot(),
        preflight_checks=[asdict(c) for c in checks],
        mcp_baseline_status=mcp_baseline,
        depth=depth,
    )

    capable: bool
    confidence = llm_assessment.confidence
    reasons = list(llm_assessment.reasons)
    missing = list(llm_assessment.missing_capabilities)
    recommended = llm_assessment.recommended_child_requirements

    if llm_assessment.assessment_available:
        capable = (
            llm_assessment.capable
            and llm_assessment.confidence >= config.capability_threshold
        )
        if not capable and llm_assessment.confidence < config.capability_threshold:
            reasons.append(
                "Capability confidence below threshold "
                f"({llm_assessment.confidence:.2f} < {config.capability_threshold:.2f})."
            )
    else:
        capable = True
        reasons.append(
            "LLM capability assessment unavailable; falling back to deterministic preflight."
        )

    if not recommended and not capable:
        recommended = _default_child_requirements(requirements, missing or reasons)

    decision = CapabilityDecision(
        capable=capable,
        confidence=confidence,
        reasons=reasons,
        missing_capabilities=missing,
        recommended_child_requirements=recommended,
        mcp_baseline_status=mcp_baseline,
        preflight_checks=checks,
        depth=depth,
    )
    _log_capability(logger, decision, "llm_hybrid_decision")
    return decision


def _run_preflight_checks(requirements_path: str, project_dir: str) -> list[PreflightCheck]:
    checks: list[PreflightCheck] = []

    req_path = Path(requirements_path)
    checks.append(
        PreflightCheck(
            name="requirements_file_exists",
            ok=req_path.exists(),
            severity="hard",
            message=f"Requirements file exists: {req_path}",
        )
    )
    checks.append(
        PreflightCheck(
            name="requirements_non_empty",
            ok=req_path.exists() and bool(req_path.read_text().strip()),
            severity="hard",
            message="Requirements file is non-empty.",
        )
    )

    api_key_present = bool(os.getenv("ANTHROPIC_API_KEY"))
    checks.append(
        PreflightCheck(
            name="anthropic_api_key",
            ok=api_key_present,
            severity="hard",
            message="ANTHROPIC_API_KEY is configured.",
        )
    )

    project_dir_ok = _is_project_dir_writable(project_dir)
    checks.append(
        PreflightCheck(
            name="project_dir_writable",
            ok=project_dir_ok,
            severity="hard",
            message=f"Project output directory is writable: {project_dir}",
        )
    )

    checks.append(
        PreflightCheck(
            name="python_available",
            ok=shutil.which("python") is not None or shutil.which("python3") is not None,
            severity="hard",
            message="Python interpreter is available on PATH.",
        )
    )
    checks.append(
        PreflightCheck(
            name="pytest_available",
            ok=shutil.which("pytest") is not None,
            severity="soft",
            message="pytest executable is available on PATH.",
        )
    )
    checks.append(
        PreflightCheck(
            name="node_available",
            ok=shutil.which("node") is not None,
            severity="soft",
            message="node is available for MCP sidecar workflows.",
        )
    )
    checks.append(
        PreflightCheck(
            name="npm_available",
            ok=shutil.which("npm") is not None,
            severity="soft",
            message="npm is available to install MCP sidecar packages.",
        )
    )
    return checks


def _is_project_dir_writable(project_dir: str) -> bool:
    path = Path(project_dir).resolve()
    try:
        path.mkdir(parents=True, exist_ok=True)
        probe = path / ".jelly_write_probe"
        probe.write_text("ok")
        probe.unlink(missing_ok=True)
        return True
    except OSError:
        return False


def _mcp_baseline_status() -> dict[str, dict[str, Any]]:
    has_node = shutil.which("node") is not None
    has_npm = shutil.which("npm") is not None
    filesystem_ok = has_node and has_npm
    browser_ok = has_node and has_npm
    return {
        "filesystem": {
            "available": filesystem_ok,
            "detail": (
                "Requires `node` and `npm`; Node-family MCP servers should run as "
                "HTTP/SSE sidecars instead of stdio."
            ),
            "required_commands": ["node", "npm"],
        },
        "browser": {
            "available": browser_ok,
            "detail": (
                "Requires `node` and `npm`; browser MCP servers should run via "
                "HTTP/SSE sidecar transport."
            ),
            "required_commands": ["node", "npm"],
        },
    }


def _available_tools_snapshot() -> dict[str, bool]:
    commands = ("python", "python3", "pytest", "node", "npm", "git")
    return {name: shutil.which(name) is not None for name in commands}


def _repo_context() -> dict[str, Any]:
    repo_root = Path(__file__).resolve().parents[1]
    top_level = sorted(p.name for p in repo_root.iterdir())[:50]
    return {
        "repo_root": str(repo_root),
        "top_level_entries": top_level,
    }


def _default_child_requirements(requirements: str, reasons: list[str]) -> str:
    reasons_text = "\n".join(f"- {reason}" for reason in reasons[:8]) if reasons else "- Unknown capability gap."
    return (
        "# Child Capability Bootstrap\n\n"
        "## Objective\n"
        "Produce a working solution for the original requirements after addressing the "
        "capability gaps identified by the parent builder.\n\n"
        "## Capability Gaps\n"
        f"{reasons_text}\n\n"
        "## Original Requirements\n"
        f"{requirements.strip()}\n"
    )


def _log_capability(
    logger: RunLogger | None,
    decision: CapabilityDecision,
    operation: str,
) -> None:
    if logger is None:
        return
    logger.event(
        "INFO",
        "capability",
        operation,
        capable=decision.capable,
        confidence=decision.confidence,
        depth=decision.depth,
        missing_capabilities=decision.missing_capabilities,
        mcp_baseline_status=decision.mcp_baseline_status,
    )
