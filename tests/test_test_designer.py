from jelly.agents.test_designer import TestDesigner as DesignerAgent
from jelly.config import Config
from jelly.mcp import MCPServer, MCPTestPlan


def test_parse_response_normalizes_tests_prefix() -> None:
    designer = DesignerAgent(Config())
    response = (
        "```python\n"
        "# tests/test_alpha.py\n"
        "def test_alpha() -> None:\n"
        "    assert True\n"
        "```\n\n"
        "```python:tests/sub/test_beta.py\n"
        "def test_beta() -> None:\n"
        "    assert True\n"
        "```\n"
    )

    files = designer._parse_test_response(response)

    assert set(files.keys()) == {"test_alpha.py", "sub/test_beta.py"}


def test_normalize_server_entry_rejects_node_family_commands() -> None:
    designer = DesignerAgent(Config())
    server = designer._normalize_server_entry(
        {
            "name": "filesystem",
            "command": "npx",
            "args": ["@modelcontextprotocol/server-filesystem", "/tmp/old"],
            "install_cmd": 123,
        },
        "/project/.mcp/filesystem",
    )

    assert server is None


def test_normalize_server_entry_for_python_filesystem_server() -> None:
    designer = DesignerAgent(Config())
    server = designer._normalize_server_entry(
        {
            "name": "filesystem",
            "command": "python",
            "args": ["tools/fs_server.py"],
            "install_cmd": 123,
        },
        "/project/.mcp/filesystem",
    )

    assert server is not None
    assert server.command == "python"
    assert server.args[-1] == "/project/.mcp/filesystem"
    assert server.install_cmd is None


def test_select_preinstalled_servers_requires_non_unit_needs() -> None:
    servers = [MCPServer(name="filesystem", transport="http_sse", endpoint="http://x")]

    selected = DesignerAgent._select_preinstalled_servers(
        {"testing_needs": [{"category": "unit", "description": "unit tests"}]},
        servers,
    )
    assert selected == []

    selected = DesignerAgent._select_preinstalled_servers(
        {"testing_needs": [{"category": "browser", "description": "user flow"}]},
        servers,
    )
    assert [s.name for s in selected] == ["filesystem"]


def test_design_tests_uses_bootstrap_registry_without_install(monkeypatch) -> None:
    config = Config()
    config.mcp_dynamic_sidecars_enabled = False
    designer = DesignerAgent(config)

    monkeypatch.setattr(
        designer,
        "_analyze_requirements",
        lambda _requirements: {
            "testing_needs": [{"category": "browser", "description": "ui flow"}]
        },
    )
    monkeypatch.setattr(
        designer,
        "_install_tools",
        lambda _servers: (_ for _ in ()).throw(
            AssertionError("install_tools should not run with bootstrap registry")
        ),
    )
    monkeypatch.setattr(
        designer,
        "_generate_test_plan",
        lambda _requirements, _signatures, servers: (
            {"test_a.py": "def test_a():\n    assert True\n"},
            MCPTestPlan(servers=list(servers), steps=[], reason="no_valid_steps"),
        ),
    )

    bootstrap_servers = [
        MCPServer(name="filesystem", transport="http_sse", endpoint="http://fs"),
        MCPServer(name="browser", transport="http_sse", endpoint="http://browser"),
    ]
    result = designer.design_tests(
        requirements="# req",
        function_signatures=["def x() -> int"],
        project_dir=".",
        preinstalled_servers=bootstrap_servers,
    )

    assert set(result.unit_test_files.keys()) == {"test_a.py"}
    assert [s.name for s in result.installed_servers] == ["filesystem", "browser"]


def test_normalize_dynamic_sidecar_entry_infers_install_and_filesystem_workspace() -> None:
    config = Config()
    config.mcp_dynamic_sidecars_enabled = True
    designer = DesignerAgent(config)

    server = designer._normalize_dynamic_sidecar_entry(
        {
            "name": "filesystem_dynamic",
            "transport": "http_sse",
            "package": "@modelcontextprotocol/server-filesystem",
            "sidecar_cmd": ["npx", "-y", "@modelcontextprotocol/server-filesystem"],
            "install_cmd": None,
        },
        "/project/.mcp/filesystem",
    )

    assert server is not None
    assert server.dynamic_sidecar is True
    assert server.transport == "http_sse"
    assert server.sidecar_package == "@modelcontextprotocol/server-filesystem"
    assert server.sidecar_command[-1] == "/project/.mcp/filesystem"
    assert server.install_cmd == [
        "npm",
        "install",
        "-g",
        "@modelcontextprotocol/server-filesystem",
    ]


def test_design_tests_merges_dynamic_sidecars_with_bootstrap(monkeypatch) -> None:
    config = Config()
    config.mcp_dynamic_sidecars_enabled = True
    designer = DesignerAgent(config)

    monkeypatch.setattr(
        designer,
        "_analyze_requirements",
        lambda _requirements: {
            "testing_needs": [{"category": "browser", "description": "ui flow"}]
        },
    )
    monkeypatch.setattr(
        designer,
        "_select_dynamic_sidecars",
        lambda _analysis, _project_dir: [
            MCPServer(
                name="github",
                transport="http_sse",
                dynamic_sidecar=True,
                sidecar_package="@modelcontextprotocol/server-github",
                sidecar_command=["npx", "-y", "@modelcontextprotocol/server-github"],
            )
        ],
    )
    monkeypatch.setattr(
        designer,
        "_generate_test_plan",
        lambda _requirements, _signatures, servers: (
            {"test_a.py": "def test_a():\n    assert True\n"},
            MCPTestPlan(servers=list(servers), steps=[], reason="no_valid_steps"),
        ),
    )

    bootstrap_servers = [
        MCPServer(name="filesystem", transport="http_sse", endpoint="http://fs"),
    ]
    result = designer.design_tests(
        requirements="# req",
        function_signatures=["def x() -> int"],
        project_dir=".",
        preinstalled_servers=bootstrap_servers,
    )

    assert {s.name for s in result.installed_servers} == {"filesystem", "github"}


def test_design_tests_skips_dynamic_selection_when_disabled(monkeypatch) -> None:
    config = Config()
    config.mcp_dynamic_sidecars_enabled = False
    designer = DesignerAgent(config)

    monkeypatch.setattr(
        designer,
        "_analyze_requirements",
        lambda _requirements: {
            "testing_needs": [{"category": "browser", "description": "ui flow"}]
        },
    )
    monkeypatch.setattr(
        designer,
        "_select_dynamic_sidecars",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("dynamic selection should not run when disabled")
        ),
    )
    monkeypatch.setattr(designer, "_select_tools", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(designer, "_install_tools", lambda _servers: [])
    monkeypatch.setattr(
        designer,
        "_generate_test_plan",
        lambda _requirements, _signatures, _servers: (
            {"test_a.py": "def test_a():\n    assert True\n"},
            MCPTestPlan(servers=[], steps=[], reason="no_available_servers"),
        ),
    )

    result = designer.design_tests(
        requirements="# req",
        function_signatures=["def x() -> int"],
        project_dir=".",
    )
    assert set(result.unit_test_files.keys()) == {"test_a.py"}


def test_select_dynamic_sidecars_dedupes_and_filters(monkeypatch) -> None:
    config = Config()
    config.mcp_dynamic_sidecars_enabled = True
    config.mcp_dynamic_max_sidecars_per_run = 4
    designer = DesignerAgent(config)

    monkeypatch.setattr(
        "jelly.agents.test_designer.BaseAgent.call",
        lambda *_args, **_kwargs: "```json\n[]\n```",
    )
    monkeypatch.setattr(
        designer,
        "_parse_json_response",
        lambda _response: [
            {
                "name": "github",
                "transport": "http_sse",
                "package": "@modelcontextprotocol/server-github",
                "sidecar_cmd": ["npx", "-y", "@modelcontextprotocol/server-github"],
            },
            {
                "name": "github",
                "transport": "http_sse",
                "package": "@modelcontextprotocol/server-github-duplicate",
                "sidecar_cmd": [
                    "npx",
                    "-y",
                    "@modelcontextprotocol/server-github-duplicate",
                ],
            },
            {
                "name": "github_alt",
                "transport": "http_sse",
                "package": "@modelcontextprotocol/server-github",
                "sidecar_cmd": ["npx", "-y", "@modelcontextprotocol/server-github"],
            },
            {
                "name": "bad_transport",
                "transport": "stdio",
                "package": "@modelcontextprotocol/server-github",
                "sidecar_cmd": ["npx", "-y", "@modelcontextprotocol/server-github"],
            },
            {
                "name": "missing_cmd",
                "transport": "http_sse",
            },
            {
                "name": "playwright",
                "transport": "http_sse",
                "package": "@playwright/mcp",
                "sidecar_cmd": ["npx", "-y", "@playwright/mcp"],
            },
        ],
    )

    servers = designer._select_dynamic_sidecars(
        {"testing_needs": [{"category": "browser", "description": "ui"}]},
        ".",
    )
    assert [s.name for s in servers] == ["github", "playwright"]
