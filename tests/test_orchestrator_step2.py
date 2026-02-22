from types import SimpleNamespace
import threading

import jelly.orchestrator as orchestrator
from jelly.capability import CapabilityDecision
from jelly.config import Config
from jelly.mcp import MCPBootstrapResult


def _decision(
    capable: bool,
    *,
    mcp_baseline_status: dict | None = None,
) -> CapabilityDecision:
    return CapabilityDecision(
        capable=capable,
        confidence=0.9 if capable else 0.2,
        reasons=["test decision"],
        missing_capabilities=[] if capable else ["missing_capability"],
        recommended_child_requirements="",
        mcp_baseline_status=mcp_baseline_status or {},
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


def test_run_task_emits_informative_progress_details(tmp_path, monkeypatch) -> None:
    req = tmp_path / "req.md"
    req.write_text("# Requirements\n\nBuild utility.\n")
    out_dir = tmp_path / "out"

    config = _config(tmp_path)
    monkeypatch.setattr(orchestrator, "Config", lambda: config)
    monkeypatch.setattr(
        orchestrator,
        "assess_capability",
        lambda **_kwargs: _decision(
            True,
            mcp_baseline_status={
                "filesystem": {"available": True},
                "browser": {"available": False},
            },
        ),
    )

    class FakeDesigner:
        def __init__(self, *_args, **_kwargs):
            pass

        def design_tests(self, *_args, **_kwargs):
            return SimpleNamespace(
                unit_test_files={"test_a.py": "def test_a():\n    assert True\n"},
                mcp_test_plan=SimpleNamespace(
                    steps=[SimpleNamespace(description="mcp step")],
                    servers=[SimpleNamespace(name="filesystem")],
                ),
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
                "mcp_summary": {
                    "plan_present": True,
                    "servers_requested": 1,
                    "servers_started": 1,
                    "steps_total": 1,
                    "steps_passed": 1,
                    "steps_failed": 0,
                    "failed_servers": [],
                },
            }

        def format_feedback(self, _results):
            return ""

    monkeypatch.setattr(orchestrator, "TestDesigner", FakeDesigner)
    monkeypatch.setattr(orchestrator, "Programmer", FakeProgrammer)
    monkeypatch.setattr(orchestrator, "TestExecutor", FakeExecutor)

    events = []
    result = orchestrator.run_task(str(req), str(out_dir), on_progress=events.append)

    assert result["all_passed"] is True
    details = [event.detail for event in events if event.detail]
    assert any("MCP baseline" in detail for detail in details)
    assert any("MCP plan is active" in detail for detail in details)
    assert any("running unit tests and MCP checks" in detail for detail in details)
    assert any("MCP results:" in detail for detail in details)
    assert any(event.meta.get("kind") == "mcp_baseline" for event in events)


def test_run_task_warns_on_bootstrap_unavailable_and_continues(tmp_path, monkeypatch) -> None:
    req = tmp_path / "req.md"
    req.write_text("# Requirements\n\nBuild utility.\n")
    out_dir = tmp_path / "out"

    config = _config(tmp_path)
    config.enable_step2_pregnancy = False
    config.mcp_unavailable_behavior = "warn_and_continue"
    monkeypatch.setattr(orchestrator, "Config", lambda: config)
    monkeypatch.setattr(
        orchestrator,
        "bootstrap_servers",
        lambda *_args, **_kwargs: MCPBootstrapResult(
            requested_servers=["filesystem", "browser"],
            available_servers=[],
            unavailable={
                "filesystem": "missing_endpoint",
                "browser": "missing_endpoint",
            },
        ),
    )

    class FakeDesigner:
        def __init__(self, *_args, **_kwargs):
            pass

        def design_tests(self, *_args, **_kwargs):
            return SimpleNamespace(
                unit_test_files={"test_a.py": "def test_a():\n    assert True\n"},
                mcp_test_plan=SimpleNamespace(steps=[], servers=[], reason=""),
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

    events = []
    result = orchestrator.run_task(str(req), str(out_dir), on_progress=events.append)

    assert result["all_passed"] is True
    assert result["mcp_bootstrap"]["unavailable_count"] == 2
    assert any(event.meta.get("kind") == "mcp_bootstrap" for event in events)


def test_run_task_stops_sidecars_on_early_delegation(tmp_path, monkeypatch) -> None:
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
        },
    )

    class FakeManager:
        instances = []

        def __init__(self, *_args, **_kwargs):
            self.stopped = False
            FakeManager.instances.append(self)

        def stop_all(self):
            self.stopped = True

    monkeypatch.setattr(orchestrator, "MCPSidecarManager", FakeManager)

    result = orchestrator.run_task(str(req), str(out_dir))

    assert result["delegated_to_child"] is True
    assert FakeManager.instances
    assert FakeManager.instances[0].stopped is True


def test_run_task_parallelizes_design_and_codegen(tmp_path, monkeypatch) -> None:
    req = tmp_path / "req.md"
    req.write_text("# Requirements\n\nBuild utility.\n")
    out_dir = tmp_path / "out"

    config = _config(tmp_path)
    config.enable_step2_pregnancy = False
    config.mcp_bootstrap_enabled = False
    monkeypatch.setattr(orchestrator, "Config", lambda: config)

    design_started = threading.Event()
    generate_started = threading.Event()
    overlap = {"design_saw_generate": False, "generate_saw_design": False}

    class FakeDesigner:
        def __init__(self, *_args, **_kwargs):
            pass

        def design_tests(self, *_args, **_kwargs):
            design_started.set()
            overlap["design_saw_generate"] = generate_started.wait(0.4)
            return SimpleNamespace(
                unit_test_files={"test_a.py": "def test_a():\n    assert True\n"},
                mcp_test_plan=SimpleNamespace(steps=[], servers=[], reason=""),
            )

        def adapt_tests(self, _code_files, test_files):
            return test_files

    class FakeProgrammer:
        def __init__(self, *_args, **_kwargs):
            pass

        def generate(self, _requirements):
            generate_started.set()
            overlap["generate_saw_design"] = design_started.wait(0.4)
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
    assert overlap["design_saw_generate"] is True
    assert overlap["generate_saw_design"] is True


def test_run_task_skips_refine_adapt_for_mcp_runtime_only_failures(tmp_path, monkeypatch) -> None:
    req = tmp_path / "req.md"
    req.write_text("# Requirements\n\nBuild utility.\n")
    out_dir = tmp_path / "out"

    config = _config(tmp_path)
    config.enable_step2_pregnancy = False
    config.mcp_bootstrap_enabled = False
    config.max_fix_iterations = 2
    monkeypatch.setattr(orchestrator, "Config", lambda: config)

    class FakeDesigner:
        adapt_calls = 0

        def __init__(self, *_args, **_kwargs):
            pass

        def design_tests(self, *_args, **_kwargs):
            return SimpleNamespace(
                unit_test_files={"test_a.py": "def test_a():\n    assert True\n"},
                mcp_test_plan=SimpleNamespace(steps=[], servers=[], reason=""),
            )

        def adapt_tests(self, _code_files, test_files):
            FakeDesigner.adapt_calls += 1
            return test_files

    class FakeProgrammer:
        refine_calls = 0

        def __init__(self, *_args, **_kwargs):
            pass

        def generate(self, _requirements):
            return {"a.py": "def x() -> int:\n    return 1\n"}

        def refine(self, *_args, **_kwargs):
            FakeProgrammer.refine_calls += 1
            return {"a.py": "def x() -> int:\n    return 1\n"}

    class FakeExecutor:
        calls = 0

        def __init__(self, *_args, **_kwargs):
            pass

        def run_all(self, *_args, **_kwargs):
            FakeExecutor.calls += 1
            if FakeExecutor.calls == 1:
                return {
                    "all_passed": False,
                    "total_tests": 1,
                    "passed": 0,
                    "failed": 1,
                    "failure_details": [
                        {
                            "test_name": "mcp step",
                            "error_type": "RuntimeError",
                            "error_message": "Timed out waiting for MCP header line",
                            "traceback": "",
                        }
                    ],
                    "mcp_summary": {
                        "plan_present": True,
                        "steps_total": 1,
                        "steps_passed": 0,
                    },
                }
            return {
                "all_passed": True,
                "total_tests": 1,
                "passed": 1,
                "failed": 0,
                "failure_details": [],
            }

        def format_feedback(self, _results):
            return "feedback"

    monkeypatch.setattr(orchestrator, "TestDesigner", FakeDesigner)
    monkeypatch.setattr(orchestrator, "Programmer", FakeProgrammer)
    monkeypatch.setattr(orchestrator, "TestExecutor", FakeExecutor)

    result = orchestrator.run_task(str(req), str(out_dir))

    assert result["all_passed"] is True
    assert FakeProgrammer.refine_calls == 1
    assert FakeDesigner.adapt_calls == 1


def test_run_task_reruns_refine_adapt_for_import_failures(tmp_path, monkeypatch) -> None:
    req = tmp_path / "req.md"
    req.write_text("# Requirements\n\nBuild utility.\n")
    out_dir = tmp_path / "out"

    config = _config(tmp_path)
    config.enable_step2_pregnancy = False
    config.mcp_bootstrap_enabled = False
    config.max_fix_iterations = 2
    monkeypatch.setattr(orchestrator, "Config", lambda: config)

    class FakeDesigner:
        adapt_calls = 0

        def __init__(self, *_args, **_kwargs):
            pass

        def design_tests(self, *_args, **_kwargs):
            return SimpleNamespace(
                unit_test_files={"test_a.py": "def test_a():\n    assert True\n"},
                mcp_test_plan=SimpleNamespace(steps=[], servers=[], reason=""),
            )

        def adapt_tests(self, _code_files, test_files):
            FakeDesigner.adapt_calls += 1
            return test_files

    class FakeProgrammer:
        def __init__(self, *_args, **_kwargs):
            pass

        def generate(self, _requirements):
            return {"a.py": "def x() -> int:\n    return 1\n"}

        def refine(self, *_args, **_kwargs):
            return {"a.py": "def x() -> int:\n    return 1\n"}

    class FakeExecutor:
        calls = 0

        def __init__(self, *_args, **_kwargs):
            pass

        def run_all(self, *_args, **_kwargs):
            FakeExecutor.calls += 1
            if FakeExecutor.calls == 1:
                return {
                    "all_passed": False,
                    "total_tests": 1,
                    "passed": 0,
                    "failed": 1,
                    "failure_details": [
                        {
                            "test_name": "test_imports",
                            "error_type": "ModuleNotFoundError",
                            "error_message": "No module named 'missing_module'",
                            "traceback": "",
                        }
                    ],
                }
            return {
                "all_passed": True,
                "total_tests": 1,
                "passed": 1,
                "failed": 0,
                "failure_details": [],
            }

        def format_feedback(self, _results):
            return "feedback"

    monkeypatch.setattr(orchestrator, "TestDesigner", FakeDesigner)
    monkeypatch.setattr(orchestrator, "Programmer", FakeProgrammer)
    monkeypatch.setattr(orchestrator, "TestExecutor", FakeExecutor)

    result = orchestrator.run_task(str(req), str(out_dir))

    assert result["all_passed"] is True
    assert FakeDesigner.adapt_calls == 2
