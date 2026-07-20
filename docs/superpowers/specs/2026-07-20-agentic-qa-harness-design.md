# Kiwi Agentic QA Harness — Design

**Date:** 2026-07-20
**Status:** Approved, not yet implemented

## Problem

Kiwi's current natural-language path (`POST /kiwi/query`) is one-shot: the LLM sees the user's query plus a Cognee recall dump, and emits either prose or a single `{"action": "...", "args": {...}}` JSON object that the UI translates into one backend call. There is no way for Kiwi to investigate a failure across multiple steps — it cannot run a test, read the failure, search the codebase for the cause, make an edit, and rerun to confirm, the way Claude Code does for a coding task.

The goal is to make Kiwi a real agentic harness for QA: given a failing test, it should autonomously loop — run → inspect → search → edit → rerun — until the test passes or it exhausts a step budget, with human approval gates on risky actions (file edits, shell commands).

## Goals

- A genuine multi-step tool-use loop (not one action per turn), reaching completion via run_tests → read_file → search_code → edit_file → run_tests cycles.
- Autonomous file edits with a rerun-to-verify step, not just diagnosis + suggested patch.
- Per-action approval by default on risky tool calls (file edits, shell commands), with an in-run "allow rest of this run" convenience.
- A curated QA toolset plus a generic shell escape hatch — not a fully open bash-only agent.
- Reachable via a dedicated `/fix [path]` command AND via natural language (e.g. "fix the failing payment test"), converging on the same loop.
- Fixed max-iteration budget; on exhaustion, stop and report what was tried rather than looping forever.
- Tool-calling support across all three configured LLM providers (Anthropic, OpenAI, Gemini) from day one, since Kiwi already supports switching providers at runtime and the loop must work regardless of which is active.

## Non-goals (v1)

- No sandboxed/containerized tool execution — tools run directly in the local backend process, same trust model as today's `/test`.
- No persisted cross-session "always allow" list — approval is per-run only (`allow_rest_of_loop` does not survive past the current `/fix` invocation).
- No token-level streaming of a single provider call's tool-call resolution — the loop streams *between* iterations (thinking/tool_call/tool_result events), not within one model response. This keeps the 3-provider adapter tractable for v1.

## Architecture

```
kiwi-ui (Ink)                    FastAPI backend                    LLM Provider
     |                                  |                                 |
     |  POST /kiwi/agent/start -------->|                                 |
     |  (NDJSON stream, long-lived)     |-- AgentLoop.run() ------------->|  converse(messages, tools)
     |<-- {type:thinking} --------------|                                 |
     |<-- {type:tool_call, needs_approval:true} |                        |
     |  POST /kiwi/agent/approve ------>|  (unblocks loop via in-proc queue)
     |<-- {type:tool_result} -----------|-- execute_tool() -------------->|  (run_tests/read_file/edit_file/shell/...)
     |<-- {type:edit_diff} -------------|                                 |
     |<-- ... repeats until done or max_iterations ... -------------------|
     |<-- {type:loop_done, success, summary} |                            |
```

The loop is driven entirely server-side. The UI is a thin renderer of the event stream plus an approval prompt — the same pattern already used for streaming thinking/text in `/kiwi/query` (see `docs/subsystems.md`).

## Components

### 1. `sentinel/agent/loop.py` — the orchestrator

Owns the iterate-until-done state machine:

1. Build the initial message list: system prompt + Cognee-recalled context for the goal + the user's goal/failing-test description.
2. Call the active provider's adapter with the current messages and the tool schema list.
3. If the response contains tool calls: execute each (gated by approval where the tool requires it), append tool results to the message list, go to step 2.
4. If the response is final text: the loop ends. On success (tests now pass), automatically `remember()` the resolution the same way `/kiwi/resolve` does today.
5. Hard cap of 10 iterations. On hitting the cap without resolution, stop and emit a summary of what was tried plus any partial diff — never loop unbounded.

### 2. `sentinel/agent/tools.py` — curated tool registry + shell escape hatch

| Tool | Approval | Notes |
|---|---|---|
| `run_tests(path?)` | auto | Wraps the existing pytest + JUnit + Cognee ingest path (`sentinel/ingest.py`); returns a structured pass/fail summary, not raw XML. |
| `read_file(path, start?, end?)` | auto | Sandboxed to repo root. |
| `search_code(pattern, glob?)` | auto | ripgrep-backed grep across the repo. |
| `edit_file(path, old_string, new_string)` | **required** | Exact-match replace, same semantics as Claude Code's Edit tool; returns a diff. |
| `shell(command)` | **required** | Generic escape hatch (e.g. `git status`, installing a dependency). Timeout + truncated output. |
| `recall(query)` / `remember(text)` | auto | Thin wrappers over `CogneeClient`, for the model's own extra memory queries mid-loop beyond the automatic recall/remember at loop boundaries. |

All file-touching tools resolve and validate paths stay within the repo root (reject `..` traversal and absolute paths outside cwd).

### 3. `sentinel/agent/providers/{anthropic,openai,gemini}.py` — provider adapters

Each wraps its native tool-calling API behind one shared interface:

```python
def converse(messages: list[Message], tools: list[ToolSchema], system: str) -> AgentResponse: ...
```

`AgentResponse` is either `tool_calls: list[ToolCall]` or `text: str`. This replaces the ad-hoc "parse JSON out of prose" action detection in `sentinel/llm_client.py` for anything going through the agent loop. The existing one-shot chat path (plain questions with no tool need) keeps using today's `ask_llm`/`stream_llm` — the agent loop is a separate, additive code path, not a replacement for simple Q&A.

### 4. Approval flow

Risky tool calls emit `{"type": "tool_call", "id": ..., "name": ..., "args": {...}, "needs_approval": true}` and the loop blocks on an in-memory `asyncio.Queue` keyed by `(loop_id, tool_call_id)`. `POST /kiwi/agent/approve {loop_id, tool_call_id, decision: allow|deny|allow_rest_of_loop}` resolves it:

- `allow` — run this one call.
- `deny` — the tool result fed back to the model is "User denied this action."; the loop continues so the model can adapt.
- `allow_rest_of_loop` — auto-approves remaining risky calls for *this* `/fix` invocation only; does not persist.

This assumes a single backend process (matches the existing `kiwi_session_state.json`-on-disk, single-user local dev model — no multi-worker deployment assumed).

### 5. Backend endpoints

- `POST /kiwi/agent/start {goal, path?}` — NDJSON stream, same framing style as `/kiwi/query` (one JSON object per line: `thinking`, `tool_call`, `tool_result`, `edit_diff`, `loop_done`, `error`).
- `POST /kiwi/agent/approve {loop_id, tool_call_id, decision}` — resolves a pending approval.
- `/fix [path]` in the UI calls `/kiwi/agent/start` directly.
- The NL router's action taxonomy in `/kiwi/query`'s system prompt gains a `fix` action (`args: {path}`). When the UI receives `{"type": "action", "action": "fix", "args": {"path": ...}}` it invokes the agent-loop endpoint instead of silently replaying a one-shot command (as it does today for actions like `test`/`remember`) — both entry points converge on the same loop.

### 6. UI (`kiwi-ui/index.tsx`)

New message content-block types alongside the existing `thinking`/`text`:

- `tool_call` — tool name + args, collapsible like today's thinking block.
- `edit_diff` — colored +/- diff.
- An inline approval prompt block for `needs_approval` tool calls, capturing `allow` / `deny` / `allow_rest_of_loop`, posting to `/kiwi/agent/approve`, and blocking further input until resolved.

## Safety & limits

- Max 10 tool-call iterations per `/fix` invocation.
- `edit_file` and `shell` always require approval by default; no persisted allowlist.
- File tools sandboxed to the repo root.
- `shell` has a timeout and truncates output.

## Testing approach

- Unit tests per tool implementation (`read_file`, `search_code`, `edit_file`, `shell`) covering the sandboxing/traversal guards independently of the loop.
- Unit tests per provider adapter, mocking each SDK's tool-calling response shape, asserting normalization into `AgentResponse`.
- Loop tests using a fake provider adapter (deterministic scripted tool-call sequence) to verify: iteration budget enforcement, approval blocking/resolution, deny-and-continue behavior, and the success → auto-remember path — without hitting a real LLM or Cognee.
- One integration-marked test (`@pytest.mark.integration`, consistent with the existing `test_integration_cloud.py` pattern) exercising a real `/fix` run against a deliberately broken sample test, gated the same way current Cognee-Cloud integration tests are.

## Rollout

1. Provider adapters + tool registry + loop core, unit-tested in isolation (no UI/endpoint wiring yet).
2. `/kiwi/agent/start` + `/kiwi/agent/approve` endpoints, exercised via `httpx` test client with a fake provider.
3. UI wiring: `/fix` command, streaming event rendering, approval prompt.
4. NL router `fix` action wiring, so plain-English requests reach the same loop.
