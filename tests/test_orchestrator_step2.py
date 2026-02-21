from types import SimpleNamespace

import jelly.orchestrator as orchestrator
from jelly.capability import CapabilityDecision
from jelly.config import Config


def _decision(capable: bool) -> CapabilityDecision:
    return CapabilityDecision(
        capable=capable,
        confidence=0.9 if capable else 0.2,
        reasons=["test decision"],
        missing_capabilities=[] if capable else ["missing_capability"],
        recommended_child_requirements="",
        mcp_baseline_status={},
        preflight_checks=[],
        depth=0,
    )


def _config(tmp_path) -> Config:
    config = Config()
    config.enable_step2_pregnancy = True
    config.log_dir = str(tmp_path / "logs")
    config.max_fix_iterations = 1
    return config


def test_run_task_capable_path_keeps_pipeline(tmp_path, monkeypatch) -> None:
    req = tmp_path / "req.md"
    req.write_text("# Requirements\n\nBuild utility.\n")
    out_dir = tmp_path / "out"

    config = _config(tmp_path)
    monkeypatch.setattr(orchestrator, "Config", lambda: config)
    monkeypatch.setattr(orchestrator, "assess_capability", lambda **_kwargs: _decision(True))

    class FakeDesigner:
        def __init__(self, *_args, **_kwargs):
            pass

        def design_tests(self, *_args, **_kwargs):
            return SimpleNamespace(
                unit_test_files={"test_a.py": "def test_a():\n    assert True\n"},
                mcp_test_plan=SimpleNamespace(steps=[], servers=[]),
            )

        def adapt_tests(self, _code_files, test_files):
            return test_files

    class FakeProgrammer:
        def __init__(self, *_args, **_kwargs):
            pass

        def generate(self, _requirements):
            return {"a.py": "def x() -> int:\n    return 1\n"}

        def refine(self, *_args, **_kwargs):
            return {"a.py": "def x() -> int:\n    return 1\n"}

    class FakeExecutor:
        def __init__(self, *_args, **_kwargs):
            pass

        def run_all(self, *_args, **_kwargs):
            return {
                "all_passed": True,
                "total_tests": 1,
                "passed": 1,
                "failed": 0,
                "failure_details": [],
            }

        def format_feedback(self, _results):
            return ""

    monkeypatch.setattr(orchestrator, "TestDesigner", FakeDesigner)
    monkeypatch.setattr(orchestrator, "Programmer", FakeProgrammer)
    monkeypatch.setattr(orchestrator, "TestExecutor", FakeExecutor)

    result = orchestrator.run_task(str(req), str(out_dir))

    assert result["all_passed"] is True
    assert (out_dir / "src" / "a.py").exists()
    assert (out_dir / "tests" / "test_a.py").exists()


def test_run_task_incapable_delegates_to_child(tmp_path, monkeypatch) -> None:
    req = tmp_path / "req.md"
    req.write_text("# Requirements\n\nBuild utility.\n")
    out_dir = tmp_path / "out"

    config = _config(tmp_path)
    monkeypatch.setattr(orchestrator, "Config", lambda: config)
    monkeypatch.setattr(orchestrator, "assess_capability", lambda **_kwargs: _decision(False))
    monkeypatch.setattr(
        orchestrator,
        "delegate_to_child_builder",
        lambda **_kwargs: {
            "all_passed": True,
            "total_tests": 0,
            "passed": 0,
            "failed": 0,
            "failure_details": [],
            "delegated_to_child": True,
            "child_workspace": "/tmp/child",
            "child_project_dir": "/tmp/child/output",
        },
    )

    class ShouldNotBeCalled:
        def __init__(self, *_args, **_kwargs):
            raise AssertionError("Main pipeline should not run when delegating to child")

    monkeypatch.setattr(orchestrator, "TestDesigner", ShouldNotBeCalled)

    result = orchestrator.run_task(str(req), str(out_dir))

    assert result["all_passed"] is True
    assert result["delegated_to_child"] is True
    assert "capability_decision" in result


def test_run_task_incapable_depth_exhaustion(tmp_path, monkeypatch) -> None:
    req = tmp_path / "req.md"
    req.write_text("# Requirements\n\nBuild utility.\n")
    out_dir = tmp_path / "out"

    config = _config(tmp_path)
    monkeypatch.setattr(orchestrator, "Config", lambda: config)
    monkeypatch.setattr(orchestrator, "assess_capability", lambda **_kwargs: _decision(False))
    monkeypatch.setattr(
        orchestrator,
        "delegate_to_child_builder",
        lambda **_kwargs: {
            "all_passed": False,
            "total_tests": 1,
            "passed": 0,
            "failed": 1,
            "failure_details": [
                {
                    "test_name": "pregnancy_delegation",
                    "error_type": "PregnancyDepthExceeded",
                    "error_message": "depth exceeded",
                    "traceback": "",
                }
            ],
            "delegated_to_child": True,
        },
    )

    result = orchestrator.run_task(str(req), str(out_dir))

    assert result["all_passed"] is False
    assert result["failure_details"][0]["error_type"] == "PregnancyDepthExceeded"
