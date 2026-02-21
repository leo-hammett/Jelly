from jelly.agents.test_designer import TestDesigner as DesignerAgent
from jelly.config import Config


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


def test_normalize_server_entry_for_filesystem() -> None:
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

    assert server is not None
    assert server.command == "npx"
    assert server.args[0] == "-y"
    assert server.args[-1] == "/project/.mcp/filesystem"
    assert server.install_cmd is None
