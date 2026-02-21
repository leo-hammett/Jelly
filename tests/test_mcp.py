import io

import jelly.mcp as mcp


def test_install_server_uses_non_shell_command(monkeypatch) -> None:
    captured = {}

    class _Result:
        returncode = 0
        stdout = "ok"
        stderr = ""

    def fake_run(cmd, shell, capture_output, text, timeout):
        captured["cmd"] = cmd
        captured["shell"] = shell
        captured["capture_output"] = capture_output
        captured["text"] = text
        captured["timeout"] = timeout
        return _Result()

    monkeypatch.setattr(mcp.subprocess, "run", fake_run)

    server = mcp.MCPServer(
        name="playwright",
        command="npx",
        args=["-y", "@playwright/mcp@latest"],
        install_cmd="npm install -g @playwright/mcp",
    )

    assert mcp.install_server(server) is True
    assert captured["shell"] is False
    assert captured["cmd"] == ["npm", "install", "-g", "@playwright/mcp"]


def test_start_server_includes_stderr_on_boot_failure(monkeypatch) -> None:
    class _FakeProc:
        def __init__(self) -> None:
            self.stdin = io.BytesIO()
            self.stdout = io.BytesIO()
            self.stderr = io.BytesIO(b"boom stderr")
            self.returncode = 23

        def poll(self):
            return self.returncode

        def terminate(self):
            return None

        def wait(self, timeout=None):
            return self.returncode

        def kill(self):
            return None

    monkeypatch.setattr(mcp.subprocess, "Popen", lambda *args, **kwargs: _FakeProc())

    server = mcp.MCPServer(name="broken", command="npx", args=["-y", "broken-server"])
    try:
        mcp.start_server(server, startup_wait=0.2)
    except RuntimeError as exc:
        assert "boom stderr" in str(exc)
    else:
        raise AssertionError("Expected RuntimeError from startup failure")
