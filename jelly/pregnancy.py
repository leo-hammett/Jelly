from __future__ import annotations

import json
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

from jelly.capability import CapabilityDecision
from jelly.config import Config
from jelly.run_logging import RunLogger
from jelly.utils import read_file


def delegate_to_child_builder(
    requirements_path: str,
    project_dir: str,
    capability_decision: CapabilityDecision,
    config: Config,
    depth: int = 0,
    seen_signatures: list[str] | None = None,
    logger: RunLogger | None = None,
) -> dict[str, Any]:
    max_depth = max(0, config.pregnancy_max_depth)
    next_depth = depth + 1
    if next_depth > max_depth:
        return _failure_result(
            error_type="PregnancyDepthExceeded",
            error_message=(
                "Capability delegation stopped: maximum depth reached "
                f"(depth={depth}, max_depth={max_depth})."
            ),
            depth=depth,
            max_depth=max_depth,
        )

    signature = _capability_signature(capability_decision)
    prior_signatures = list(seen_signatures or [])
    if _signature_seen(signature, prior_signatures):
        return _failure_result(
            error_type="RepeatedCapabilitySignature",
            error_message=(
                "Capability delegation stopped: repeated capability signature "
                f"'{signature}' detected."
            ),
            depth=depth,
            max_depth=max_depth,
        )

    repo_root = Path(__file__).resolve().parents[1]
    workspace_root = _workspace_root(repo_root, config.pregnancy_workspace_dir)
    workspace_root.mkdir(parents=True, exist_ok=True)

    child_workspace = workspace_root / f"child_d{next_depth}_{int(time.time())}"
    _copy_repo(repo_root, child_workspace, Path(config.pregnancy_workspace_dir).name)

    original_requirements = read_file(requirements_path)
    child_requirements_text = _build_child_requirements(
        original_requirements,
        capability_decision,
    )
    child_requirements_path = child_workspace / "child_requirements.md"
    child_requirements_path.write_text(child_requirements_text)

    child_project_dir = child_workspace / "output"
    next_signatures = [*prior_signatures, signature]
    cmd = [
        sys.executable,
        "-m",
        "jelly",
        "run",
        str(child_requirements_path),
        "--project-dir",
        str(child_project_dir),
        "--pregnancy-depth",
        str(next_depth),
        "--pregnancy-signatures",
        json.dumps(next_signatures),
    ]

    _log(
        logger,
        "INFO",
        "delegate.start",
        depth=depth,
        next_depth=next_depth,
        max_depth=max_depth,
        child_workspace=str(child_workspace),
        child_project_dir=str(child_project_dir),
    )
    try:
        result = subprocess.run(
            cmd,
            cwd=child_workspace,
            capture_output=True,
            text=True,
            timeout=config.pregnancy_timeout_seconds,
        )
    except subprocess.TimeoutExpired:
        _log(
            logger,
            "ERROR",
            "delegate.timeout",
            depth=depth,
            timeout_seconds=config.pregnancy_timeout_seconds,
            child_workspace=str(child_workspace),
        )
        return _failure_result(
            error_type="PregnancyTimeout",
            error_message=(
                "Child builder timed out after "
                f"{config.pregnancy_timeout_seconds}s at depth {next_depth}."
            ),
            depth=depth,
            max_depth=max_depth,
            child_workspace=str(child_workspace),
            child_project_dir=str(child_project_dir),
        )

    stdout_tail = (result.stdout or "")[-1500:]
    stderr_tail = (result.stderr or "")[-1500:]
    if result.returncode != 0:
        _log(
            logger,
            "WARNING",
            "delegate.child_failed",
            depth=depth,
            next_depth=next_depth,
            returncode=result.returncode,
            stdout_tail=stdout_tail,
            stderr_tail=stderr_tail,
        )
        return _failure_result(
            error_type="ChildBuilderFailed",
            error_message=(
                f"Child builder exited with code {result.returncode} at depth {next_depth}."
            ),
            depth=depth,
            max_depth=max_depth,
            child_workspace=str(child_workspace),
            child_project_dir=str(child_project_dir),
            child_stdout_tail=stdout_tail,
            child_stderr_tail=stderr_tail,
        )

    _log(
        logger,
        "INFO",
        "delegate.child_succeeded",
        depth=depth,
        next_depth=next_depth,
        child_workspace=str(child_workspace),
        child_project_dir=str(child_project_dir),
    )
    return {
        "all_passed": True,
        "total_tests": 0,
        "passed": 0,
        "failed": 0,
        "failure_details": [],
        "delegated_to_child": True,
        "pregnancy_depth": depth,
        "pregnancy_max_depth": max_depth,
        "child_workspace": str(child_workspace),
        "child_project_dir": str(child_project_dir),
        "child_stdout_tail": stdout_tail,
        "child_stderr_tail": stderr_tail,
    }


def _workspace_root(repo_root: Path, configured_path: str) -> Path:
    root = Path(configured_path)
    if root.is_absolute():
        return root
    return repo_root / root


def _copy_repo(repo_root: Path, child_workspace: Path, workspace_dir_name: str) -> None:
    ignore = shutil.ignore_patterns(
        ".git",
        "__pycache__",
        ".pytest_cache",
        ".mypy_cache",
        ".ruff_cache",
        ".jelly_logs",
        "output",
        workspace_dir_name,
    )
    shutil.copytree(repo_root, child_workspace, ignore=ignore)


def _build_child_requirements(
    original_requirements: str,
    decision: CapabilityDecision,
) -> str:
    if decision.recommended_child_requirements.strip():
        return decision.recommended_child_requirements.strip() + "\n"
    return original_requirements


def _capability_signature(decision: CapabilityDecision) -> str:
    if decision.missing_capabilities:
        return "|".join(sorted(decision.missing_capabilities))
    if decision.reasons:
        return "|".join(sorted(decision.reasons))[:200]
    return "unspecified_capability_gap"


def _signature_seen(signature: str, signatures: list[str]) -> bool:
    return signature in signatures


def _failure_result(
    error_type: str,
    error_message: str,
    depth: int,
    max_depth: int,
    **extra_fields: Any,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "all_passed": False,
        "total_tests": 1,
        "passed": 0,
        "failed": 1,
        "failure_details": [
            {
                "test_name": "pregnancy_delegation",
                "error_type": error_type,
                "error_message": error_message,
                "traceback": "",
            }
        ],
        "delegated_to_child": True,
        "pregnancy_depth": depth,
        "pregnancy_max_depth": max_depth,
    }
    payload.update(extra_fields)
    return payload


def _log(
    logger: RunLogger | None,
    level: str,
    operation: str,
    **fields: Any,
) -> None:
    if logger:
        logger.event(level, "pregnancy", operation, **fields)
