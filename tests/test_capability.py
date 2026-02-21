from jelly.capability import CapabilityAssessment, assess_capability
from jelly.config import Config


def test_assess_capability_fails_on_missing_api_key(tmp_path, monkeypatch) -> None:
    req = tmp_path / "req.md"
    req.write_text("# Requirements\n\nBuild a tiny utility.\n")
    out_dir = tmp_path / "out"

    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

    decision = assess_capability(
        requirements=req.read_text(),
        requirements_path=str(req),
        project_dir=str(out_dir),
        config=Config(),
        depth=0,
    )

    assert decision.capable is False
    assert "anthropic_api_key" in decision.missing_capabilities


def test_assess_capability_honors_confidence_threshold(tmp_path, monkeypatch) -> None:
    req = tmp_path / "req.md"
    req.write_text("# Requirements\n\nBuild a tiny utility.\n")
    out_dir = tmp_path / "out"

    monkeypatch.setenv("ANTHROPIC_API_KEY", "dummy")

    def fake_check(*_args, **_kwargs):
        return CapabilityAssessment(
            capable=True,
            confidence=0.55,
            reasons=["Tooling likely sufficient but uncertain."],
            missing_capabilities=[],
            recommended_child_requirements="",
            assessment_available=True,
        )

    monkeypatch.setattr(
        "jelly.agents.capability_checker.CapabilityChecker.check",
        fake_check,
    )

    config = Config()
    config.capability_threshold = 0.75
    decision = assess_capability(
        requirements=req.read_text(),
        requirements_path=str(req),
        project_dir=str(out_dir),
        config=config,
        depth=0,
    )

    assert decision.capable is False
    assert any("below threshold" in reason for reason in decision.reasons)


def test_mcp_baseline_is_reported_but_not_required_by_default(tmp_path, monkeypatch) -> None:
    req = tmp_path / "req.md"
    req.write_text("# Requirements\n\nBuild a tiny utility.\n")
    out_dir = tmp_path / "out"

    monkeypatch.setenv("ANTHROPIC_API_KEY", "dummy")

    def fake_which(command: str):
        if command in {"python", "python3", "pytest"}:
            return f"/usr/bin/{command}"
        return None

    monkeypatch.setattr("jelly.capability.shutil.which", fake_which)

    def fake_check(*_args, **_kwargs):
        return CapabilityAssessment(
            capable=True,
            confidence=0.99,
            reasons=["Core build/test loop is feasible."],
            missing_capabilities=[],
            recommended_child_requirements="",
            assessment_available=True,
        )

    monkeypatch.setattr(
        "jelly.agents.capability_checker.CapabilityChecker.check",
        fake_check,
    )

    config = Config()
    config.require_mcp_baseline = False
    decision = assess_capability(
        requirements=req.read_text(),
        requirements_path=str(req),
        project_dir=str(out_dir),
        config=config,
        depth=0,
    )

    assert decision.capable is True
    assert decision.mcp_baseline_status["filesystem"]["available"] is False
    assert decision.mcp_baseline_status["browser"]["available"] is False
