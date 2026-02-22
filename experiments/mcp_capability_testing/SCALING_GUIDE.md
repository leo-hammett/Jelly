# Scaling Guide: MCP Transport Policy

This guide scales the current MCP experiment into production rules for Jelly while avoiding known Node stdio failures.

## Core policy

- Python MCP servers may run over stdio.
- Node-family MCP servers (`npx`, `node`, `npm`, `pnpm`, `yarn`, `bun`) must not run over stdio in `jelly/mcp.py`.
- Node MCP integrations should use Python-managed HTTP/SSE sidecars.

## Reference implementation

- `experiments/mcp_capability_testing/run_filesystem_mcp_smoke.py`
- `experiments/mcp_capability_testing/fs_server.py`

These demonstrate a policy-compliant Python stdio MCP lifecycle (`install/start/call/stop`) and focused startup diagnostics.

## Rollout steps for Jelly

1. Keep `jelly/mcp.py` as Python-stdio-only transport utilities.
2. Reject Node-family stdio commands early with explicit error messages.
3. In `jelly/agents/test_designer.py`, reject Node-family MCP server entries for this stdio pipeline.
4. Introduce a separate sidecar utility for Node servers (HTTP/SSE) in a dedicated module (for example `jelly/mcp_sidecar.py`).
5. Route Node MCP scenarios through the sidecar utility instead of `jelly/mcp.py`.

## Sidecar rollout blueprint (Node MCP)

1. Install package (`npm`/`pnpm`) into controlled runtime environment.
2. Spawn process with explicit host/port args.
3. Poll health/ready endpoint with timeout.
4. Connect from Python client to `http://localhost:<port>/mcp`.
5. Ensure process cleanup on success/failure.

## Operational rules

- Keep startup diagnostics focused where failures occur (boot/handshake).
- Emit command, timeout, and stdout/stderr tail for sidecar startup failures.
- Use deterministic exit codes for smoke scripts.
- Prefer pinned dependency versions in production paths.

## Success criteria before full adoption

- Python stdio MCP smoke tests pass reliably.
- Node MCP use cases no longer depend on stdio transport.
- Startup failures are actionable from logs without additional reproduction steps.
