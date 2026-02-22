#!/usr/bin/env python3
"""FastMCP smoke test for Python MCP server (in-memory + stdio file)."""

from __future__ import annotations

import asyncio
import importlib
import importlib.util
import subprocess
import sys
import time
from pathlib import Path
from typing import Any


def _has_module(name: str) -> bool:
    return importlib.util.find_spec(name) is not None


def _ensure_dependencies() -> bool:
    missing = [pkg for pkg in ("fastmcp", "mcp") if not _has_module(pkg)]
    if not missing:
        print("STEP_RESULT: dependency_check OK")
        return True

    print(f"INSTALL_DEBUG: missing_packages={missing}")
    cmd = [sys.executable, "-m", "pip", "install", *missing]
    started = time.perf_counter()
    result = subprocess.run(cmd, shell=False, capture_output=True, text=True)
    elapsed = round(time.perf_counter() - started, 3)
    print(
        "INSTALL_DEBUG:"
        f" pip_elapsed_seconds={elapsed}"
        f" returncode={result.returncode}"
        f" stdout_tail={result.stdout[-400:]!r}"
        f" stderr_tail={result.stderr[-400:]!r}"
    )
    if result.returncode == 0:
        return True

    # uv-managed environments sometimes omit pip. Fallback to uv pip.
    if "No module named pip" in result.stderr:
        uv_cmd = ["uv", "pip", "install", *missing]
        uv_started = time.perf_counter()
        uv_result = subprocess.run(uv_cmd, shell=False, capture_output=True, text=True)
        uv_elapsed = round(time.perf_counter() - uv_started, 3)
        print(
            "INSTALL_DEBUG:"
            f" uv_pip_elapsed_seconds={uv_elapsed}"
            f" returncode={uv_result.returncode}"
            f" stdout_tail={uv_result.stdout[-400:]!r}"
            f" stderr_tail={uv_result.stderr[-400:]!r}"
        )
        return uv_result.returncode == 0
    return False


def _load_fs_server(server_file: Path):
    spec = importlib.util.spec_from_file_location("fs_server", server_file)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load module from {server_file}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    if not hasattr(module, "server"):
        raise RuntimeError(f"{server_file} must define `server`")
    return module.server


async def _run_in_memory(server_obj) -> None:
    Client = getattr(importlib.import_module("fastmcp"), "Client")

    async with Client(server_obj) as client:
        tools = await client.list_tools()
        tool_names = [tool.name for tool in tools]
        if "list_allowed_directories" not in tool_names:
            raise RuntimeError(f"Expected tool missing. got={tool_names}")
        result = await client.call_tool("list_allowed_directories", {})
        print(f"IN_MEMORY_RESULT: {result}")


async def _run_stdio(server_file: Path, workspace: Path) -> None:
    Client = getattr(importlib.import_module("fastmcp"), "Client")

    started = time.perf_counter()
    async with Client(str(server_file)) as client:
        print(
            "STARTUP_DEBUG:"
            f" launcher_mode=fastmcp_client_stdio_pyfile"
            f" server_file={server_file}"
        )
        tools = await client.list_tools()
        tool_names = [tool.name for tool in tools]
        if "list_directory" not in tool_names:
            raise RuntimeError(f"Expected tool missing. got={tool_names}")
        result = await client.call_tool("list_directory", {"path": str(workspace)})
        elapsed = round(time.perf_counter() - started, 3)
        print(f"STARTUP_DEBUG: stdio_connect_elapsed_seconds={elapsed}")
        print(f"STDIO_RESULT: {result}")


async def _async_main() -> int:
    experiment_root = Path(__file__).resolve().parent
    workspace = (experiment_root / "workspace").resolve()
    workspace.mkdir(parents=True, exist_ok=True)
    server_file = (experiment_root / "fs_server.py").resolve()

    if not server_file.exists():
        print("FINAL_STATUS: FAIL")
        print(f"REASON: expected server file missing: {server_file}")
        return 1

    print("STEP 1/4 dependency install/check")
    if not _ensure_dependencies():
        print("FINAL_STATUS: FAIL")
        print("REASON: could not install required python packages (fastmcp, mcp)")
        return 1

    print("STEP 2/4 load server")
    server_obj = _load_fs_server(server_file)
    print("STEP_RESULT: load_server OK")

    try:
        print("STEP 3/4 in-memory call")
        await _run_in_memory(server_obj)
        print("STEP_RESULT: in_memory_call OK")

        print("STEP 4/4 stdio call")
        await _run_stdio(server_file, workspace)
        print("STEP_RESULT: stdio_call OK")

        print("FINAL_STATUS: PASS")
        return 0
    except Exception as exc:  # noqa: BLE001 - smoke script should expose all failures
        print("FINAL_STATUS: FAIL")
        print(f"REASON: {type(exc).__name__}: {exc}")
        return 1


def main() -> int:
    return asyncio.run(_async_main())


if __name__ == "__main__":
    raise SystemExit(main())
