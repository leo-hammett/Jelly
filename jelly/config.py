from dataclasses import dataclass


@dataclass
class Config:
    model: str = "claude-sonnet-4-6"
    programmer_max_tokens: int = 16000
    test_designer_max_tokens: int = 16000
    max_fix_iterations: int = 3
    test_timeout_seconds: int = 30
    use_extended_thinking: bool = True
    thinking_budget_tokens: int = 10000
    mcp_test_timeout: int = 60
    log_level: str = "INFO"
    log_dir: str = ".jelly_logs"
    keep_sandbox_on_failure: bool = False
    clean_output_before_write: bool = True
    # Step 2 rollout guard. Keep disabled by default for teammate safety.
    enable_step2_pregnancy: bool = False
    capability_threshold: float = 0.7
    capability_checker_max_tokens: int = 4096
    # Recursion controls for child builders.
    pregnancy_max_depth: int = 3
    pregnancy_timeout_seconds: int = 600
    pregnancy_workspace_dir: str = ".jelly_children"
    # MCP baseline is diagnostic-first (recommended, not hard-required).
    require_mcp_baseline: bool = False
