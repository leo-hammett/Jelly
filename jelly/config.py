from dataclasses import dataclass


@dataclass
class Config:
    model: str = "claude-sonnet-4-6"
    programmer_max_tokens: int = 16000
    test_designer_max_tokens: int = 16000
    max_fix_iterations: int = 9999
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
    # MCP bootstrap policy: preconfigure known servers at startup.
    mcp_bootstrap_enabled: bool = True
    # Preset name for deterministic startup servers.
    mcp_bootstrap_preset: str = "filesystem_browser"
    # Transport strategy used by bootstrap and execution path.
    # Allowed values:
    # - "python_stdio_only"
    # - "python_plus_node_sidecar"
    # - "allow_node_stdio"
    mcp_transport_mode: str = "python_plus_node_sidecar"
    # Behavior when configured MCP targets are unavailable.
    # Allowed values:
    # - "fail_closed"
    # - "warn_and_continue"
    # - "unit_only_fallback"
    mcp_unavailable_behavior: str = "warn_and_continue"
    # If enabled, bootstrap attempts package install commands for preset servers.
    mcp_bootstrap_install: bool = False
    # Endpoint env var names for sidecar transports.
    mcp_filesystem_endpoint_env: str = "JELLY_MCP_FILESYSTEM_URL"
    mcp_browser_endpoint_env: str = "JELLY_MCP_BROWSER_URL"
    # Dynamic sidecar provisioning policy (for model-selected extra servers).
    mcp_dynamic_sidecars_enabled: bool = True
    mcp_dynamic_install_timeout_seconds: int = 120
    mcp_dynamic_startup_timeout_seconds: int = 30
    mcp_dynamic_max_sidecars_per_run: int = 6
    mcp_dynamic_sidecar_host: str = "127.0.0.1"
    mcp_dynamic_sidecar_base_port: int = 7700
    mcp_dynamic_sidecar_port_span: int = 100
