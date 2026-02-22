#!/usr/bin/env python3
"""Python filesystem MCP server for experiment smoke tests."""

from __future__ import annotations

from pathlib import Path

from fastmcp import FastMCP

server = FastMCP("filesystem-smoke-server")
WORKSPACE_ROOT = (Path(__file__).resolve().parent / "workspace").resolve()
WORKSPACE_ROOT.mkdir(parents=True, exist_ok=True)


def _ensure_allowed(target: Path) -> Path:
    resolved = target.resolve()
    try:
        resolved.relative_to(WORKSPACE_ROOT)
    except ValueError as exc:
        raise ValueError(f"Path outside workspace: {resolved}") from exc
    return resolved


@server.tool()
def list_allowed_directories() -> dict[str, list[str]]:
    """Return allowed roots for this server."""
    return {"allowed_directories": [str(WORKSPACE_ROOT)]}


@server.tool()
def list_directory(path: str | None = None) -> list[str]:
    """List one directory under the workspace root."""
    target = WORKSPACE_ROOT if path is None else _ensure_allowed(Path(path))
    if not target.exists():
        raise ValueError(f"Path does not exist: {target}")
    if not target.is_dir():
        raise ValueError(f"Path is not a directory: {target}")
    entries: list[str] = []
    for entry in sorted(target.iterdir(), key=lambda p: p.name.lower()):
        marker = "[DIR]" if entry.is_dir() else "[FILE]"
        entries.append(f"{marker} {entry.name}")
    return entries


if __name__ == "__main__":
    server.run(transport="stdio")
