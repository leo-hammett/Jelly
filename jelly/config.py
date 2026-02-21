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
