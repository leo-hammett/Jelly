# MCP Capability Testing

This folder contains a standalone FastMCP smoke test that validates Python MCP connectivity in one Python run:

1. install/check Python dependencies (`fastmcp`, `mcp`)
2. call tools in-memory via `Client(server)`
3. call tools via stdio using `Client("fs_server.py")`

## Prerequisites

- `uv` installed
- Python available on `PATH` (when run via `uv`, this is provided)
- Run from repo root: `Jelly/`

## Run

```bash
uv run python experiments/mcp_capability_testing/run_filesystem_mcp_smoke.py
```

## Expected success output

- `STEP_RESULT: dependency_check OK` (or install debug + success)
- `STEP_RESULT: load_server OK`
- `STEP_RESULT: in_memory_call OK`
- `STEP_RESULT: stdio_call OK`
- `FINAL_STATUS: PASS`

The script prints both `IN_MEMORY_RESULT` and `STDIO_RESULT`, plus startup diagnostics for the stdio path.

## Failure modes

- `FINAL_STATUS: FAIL` with dependency install error
  - `pip` could not install `fastmcp`/`mcp` in the active uv environment.
- `FINAL_STATUS: FAIL` with server load error
  - `fs_server.py` missing or does not expose `server`.
- `FINAL_STATUS: FAIL` with in-memory/stdio call error
  - tool schema mismatch, startup failure, or runtime tool exception.

The script exits with code `0` on pass and non-zero on any failure.

## Policy alignment

- `jelly/mcp.py` now blocks Node-family stdio launches (`npx`, `node`, `npm`, etc.).
- This experiment uses a Python FastMCP server (`fs_server.py`) and the FastMCP `Client` for both in-memory and stdio flows.
- For Node MCP servers, use an HTTP/SSE sidecar approach from Python rather than stdio.
