---
name: MCP startup triage hardening
overview: Harden MCP failure handling so startup/infrastructure errors are classified immediately as test-side issues, repaired via MCP/test edits (not code refinement), and fail closed with actionable diagnostics when repair budgets are exhausted.
todos:
  - id: mcp-preflight-diagnostics
    content: Add MCP startup stderr propagation and filesystem preflight path handling in jelly/mcp.py
    status: pending
  - id: mcp-aware-classifier
    content: Update classify_failures to detect MCP infra errors and avoid code_bug misclassification
    status: pending
  - id: mcp-plan-repair
    content: Add deterministic repair_mcp_plan flow for MCP server args/step validity in TestDesigner
    status: pending
  - id: orchestrator-routing
    content: Update orchestrator triage loop to route MCP/test repairs without code fallback and enforce fail-closed behavior
    status: pending
  - id: mcp-accounting
    content: Fix MCP failure counting and partial execution behavior in TestExecutor.run_mcp_tests
    status: pending
  - id: reporting-traceability
    content: Add iteration-level classification/action metadata to test_results.md reporting
    status: pending
  - id: regression-tests
    content: Add regression tests for repeated filesystem startup failure classification and routing
    status: pending
isProject: false
---

# MCP Startup Triage Hardening

## Confirmed Bugs (Exhaustive Findings)

### Critical

- In `[jelly/agents/test_executor.py](jelly/agents/test_executor.py)`, `classify_failures()` misclassifies MCP startup failures like `(start filesystem)` as `code_bug` because unhandled `RuntimeError` paths fall into the default `code_signals` branch.
- In `[jelly/orchestrator.py](jelly/orchestrator.py)`, a `test_bug` can still trigger code refinement when test budget is exhausted (`test_bug` + no test budget -> code fix fallback), violating the requirement to avoid code edits for test-side failures.
- In `[jelly/agents/test_designer.py](jelly/agents/test_designer.py)`, the filesystem MCP example is hardcoded to `/tmp/jelly_test`, while no preflight guarantees that path exists.
- In `[jelly/mcp.py](jelly/mcp.py)`, startup failures discard `stderr`, so the system cannot identify root cause and cannot auto-repair based on concrete diagnostics.

### High

- In `[jelly/agents/test_executor.py](jelly/agents/test_executor.py)`, `run_mcp_tests()` returns early on first startup failure and marks all MCP steps failed (`len(plan.steps)`), which inflates failure counts and prevents partial execution.
- In `[jelly/agents/test_executor.py](jelly/agents/test_executor.py)`, `project_dir` is unused in MCP startup flow, so no stable writable MCP workspace is derived.
- In `[jelly/agents/test_designer.py](jelly/agents/test_designer.py)`, MCP plan steps are not validated against installed/available servers (can create `ServerNotFound` cascades).
- In `[jelly/config.py](jelly/config.py)` and `[jelly/mcp.py](jelly/mcp.py)`, `mcp_test_timeout` is currently unused by JSON-RPC calls/startup waits.

### Medium

- `classify_failures()` fallback defaults to `code_bug` unless `test_bug` substring appears, despite prompt guidance to bias ambiguous cases toward test-side.
- There is no explicit MCP infra repair path (editing server args/step routing); current `fix_tests()` only edits unit tests in `[jelly/agents/test_designer.py](jelly/agents/test_designer.py)`.
- Reporting in `[jelly/orchestrator.py](jelly/orchestrator.py)` / `test_results.md` lacks triage action context (what was classified and what repair was attempted each iteration).

## Implementation Plan

1. **Add MCP infra diagnostics and preflight in `[jelly/mcp.py](jelly/mcp.py)`**

- Capture and propagate startup `stderr` in raised errors.
- Add safe startup preflight helper for filesystem servers:
  - derive/normalize path
  - ensure directory exists
  - include command/args in error context
- Wire startup and JSON-RPC waits to config-driven values.

1. **Introduce MCP-aware classification in `[jelly/agents/test_executor.py](jelly/agents/test_executor.py)`**

- Extend `classify_failures()` heuristics to immediately classify these as test-side/infrastructure:
  - `test_name.startswith("(start ")`
  - `error_type` in `ServerNotFound`
  - messages containing `MCP server`, `exited during startup`, handshake/timeout keywords
- Add repeated-failure signature detection across iterations to avoid reclassifying identical infra failures as code bugs.
- Fix ambiguous fallback to prefer test-side classification.

1. **Add MCP plan repair path in `[jelly/agents/test_designer.py](jelly/agents/test_designer.py)`**

- Add `repair_mcp_plan(mcp_plan, results, project_dir)` that can:
  - rewrite filesystem server path to a guaranteed writable directory under `project_dir` (e.g. `.mcp/filesystem`)
  - drop or quarantine invalid server steps when server name mismatches occur
  - return updated `MCPTestPlan`
- Keep this deterministic where possible; use LLM only for non-deterministic mapping if needed.

1. **Rewrite triage control flow in `[jelly/orchestrator.py](jelly/orchestrator.py)`**

- On classification as test-side issue:
  - attempt MCP-plan repair first (if MCP infra signature)
  - otherwise run test-file repair
  - retest without code refinement
- Remove cross-track fallbacks that convert test-side failures into code refinement.
- Respect your selected policy: **fail closed** when repair budgets are exhausted, with `needs_user_help` and detailed `help_summary`.

1. **Improve MCP execution accounting in `[jelly/agents/test_executor.py](jelly/agents/test_executor.py)`**

- Avoid counting all MCP steps as failed when startup fails before execution.
- Preserve explicit infra failure detail entries while keeping totals accurate and explainable.
- Continue starting/executing independent servers where safe.

1. **Improve run report fidelity in `[jelly/orchestrator.py](jelly/orchestrator.py)`**

- Record per-iteration metadata in `all_iterations`:
  - classification (`test_bug`/`code_bug` + infra subtype)
  - action taken (`repair_mcp_plan` / `fix_tests` / `refine_code`)
  - budgets consumed
- Emit these details into `test_results.md` for post-run traceability.

1. **Add regression tests for this area**

- Add focused tests for classification and loop routing (mocking MCP failures) under repo tests.
- Include case: repeated `(start filesystem)` failure should never trigger `programmer.refine()` and should fail closed after test/MCP budget exhaustion.

## Key Files To Change

- `[jelly/mcp.py](jelly/mcp.py)`
- `[jelly/agents/test_executor.py](jelly/agents/test_executor.py)`
- `[jelly/agents/test_designer.py](jelly/agents/test_designer.py)`
- `[jelly/orchestrator.py](jelly/orchestrator.py)`
- `[jelly/config.py](jelly/config.py)`

## Expected Outcome

- `(start filesystem)`-style failures are immediately treated as test-side infra failures.
- System attempts MCP/test repair first, with no phantom code-fix loops.
- If repairs cannot recover within budget, run stops and asks user with actionable diagnostics (fail-closed policy).

