import os

from jelly.capability import CapabilityDecision
from jelly.config import Config
from jelly.pregnancy import delegate_to_child_builder


def _decision(capable: bool = False) -> CapabilityDecision:
    return CapabilityDecision(
        capable=capable,
        confidence=0.2,
        reasons=["missing capability"],
        missing_capabilities=["missing_capability"],
        recommended_child_requirements="# child reqs\n",
        mcp_baseline_status={},
        preflight_checks=[],
        depth=0,
    )


def test_delegate_to_child_stops_at_max_depth(tmp_path) -> None:
    req = tmp_path / "req.md"
    req.write_text("# Requirements\n\nDo thing.\n")

    config = Config()
    config.pregnancy_max_depth = 0
    config.pregnancy_workspace_dir = str(tmp_path / "children")

    result = delegate_to_child_builder(
        requirements_path=str(req),
        project_dir=str(tmp_path / "out"),
        capability_decision=_decision(),
        config=config,
        depth=0,
    )

    assert result["all_passed"] is False
    assert result["failure_details"][0]["error_type"] == "PregnancyDepthExceeded"


def test_delegate_to_child_stops_on_repeated_signature(tmp_path) -> None:
    req = tmp_path / "req.md"
    req.write_text("# Requirements\n\nDo thing.\n")

    config = Config()
    config.pregnancy_max_depth = 3
    config.pregnancy_workspace_dir = str(tmp_path / "children")

    result = delegate_to_child_builder(
        requirements_path=str(req),
        project_dir=str(tmp_path / "out"),
        capability_decision=_decision(),
        config=config,
        depth=0,
        seen_signatures=["missing_capability"],
    )

    assert result["all_passed"] is False
    assert result["failure_details"][0]["error_type"] == "RepeatedCapabilitySignature"


def test_delegate_to_child_success_returns_child_paths(tmp_path, monkeypatch) -> None:
    req = tmp_path / "req.md"
    req.write_text("# Requirements\n\nDo thing.\n")

    config = Config()
    config.pregnancy_max_depth = 3
    config.pregnancy_workspace_dir = str(tmp_path / "children")
    config.pregnancy_timeout_seconds = 5

    def fake_copy_repo(_repo_root, child_workspace, _workspace_dir_name):
        child_workspace.mkdir(parents=True, exist_ok=True)

    captured = {}

    class _Result:
        returncode = 0
        stdout = "child success"
        stderr = ""

    def fake_run(cmd, cwd, capture_output, text, timeout):
        captured["cmd"] = cmd
        captured["cwd"] = cwd
        captured["capture_output"] = capture_output
        captured["text"] = text
        captured["timeout"] = timeout
        return _Result()

    monkeypatch.setattr("jelly.pregnancy._copy_repo", fake_copy_repo)
    monkeypatch.setattr("jelly.pregnancy.subprocess.run", fake_run)

    result = delegate_to_child_builder(
        requirements_path=str(req),
        project_dir=str(tmp_path / "out"),
        capability_decision=_decision(),
        config=config,
        depth=0,
    )

    assert result["all_passed"] is True
    assert result["delegated_to_child"] is True
    assert os.path.isdir(result["child_workspace"])
    assert os.path.isdir(result["child_project_dir"]) is False
    assert "--pregnancy-depth" in captured["cmd"]
    assert "--pregnancy-signatures" in captured["cmd"]
