# Sentinel — Design Spec (v2)

**Date:** 2026-07-03
**Supersedes:** `docs/superpowers/plans/2026-07-02-sentinel.md` (v1 plan — its `sentinel/` scaffold will be removed and rebuilt per this spec)
**Hackathon:** WeMakeDevs x Cognee, Jun 29 – Jul 5 2026 · Track: **Best Use of Cognee Cloud** · **~2 days remain**

## 1. One-liner

Sentinel is a QA reviewer with memory. CodeRabbit reviews what a diff *looks like*; Sentinel reviews what the code *actually did* — it ingests every CI test failure into Cognee Cloud, and on a failing PR posts a grounded review: *"This failure matches 2 prior incidents — same race condition in retry logic, both fixed by an idempotency key."*

## 2. Verified foundation (smoke-tested 2026-07-03 against live tenant)

All calls verified end-to-end via REST (`smoke_test.py`, 35s total):

| Capability | Endpoint | Verified latency |
|---|---|---|
| remember (permanent, add+cognify) | `POST /api/v1/remember` (multipart) | ~20s/doc sync |
| recall (semantic, GRAPH_COMPLETION default) | `POST /api/v1/recall` | ~7s |
| remember (session-scoped, background-bridged) | `POST /api/v1/remember` + `session_id` | instant |
| improve signal (QA entry → chained feedback) | `POST /api/v1/remember/entry` | instant |
| forget (dataset / per-item / memoryOnly) | `POST /api/v1/forget` | ~3s |
| graph data / rendered graph | `GET /datasets/{id}/graph`, `GET /visualize` | — |
| sessions, quotas | `GET /sessions`, `GET /quotas/usage` | — |

Auth: `X-Api-Key` + `X-Tenant-Id` headers. Env: `COGNEE_BASE_URL` (tenant URL), `COGNEE_API_KEY`, `COGNEE_TENANT_ID`, `SENTINEL_DATASET`.

**Key API facts that shape the design:**
- There is no standalone `/improve` endpoint on Cloud. Session-scoped `remember` is bridged into the permanent graph automatically in the background; the explicit improvement signal is a `FeedbackEntry` (`feedback_score`, chained to a `qa_id` from a prior QA entry). Sessions appear in the platform dashboard's **Sessions** page; the permanent graph in **Brain/Mindmap**.
- `recall` accepts `sessionId`, `topK`, `onlyContext`, `includeReferences`, and 17 search types; default `GRAPH_COMPLETION` returns a synthesized answer, `null` enables auto-routing.
- Everything the pipeline writes is visible in the Cognee dashboard (Sessions, Brain, Mindmap, Memory Schema) — the dashboard is part of the demo, free of charge.

## 3. Decisions log

| Decision | Choice |
|---|---|
| Direction | Evolution of Sentinel PRD; agentic PR review promoted from stretch to headline |
| Orchestration | Deterministic Python pipeline; LLM agent only at the review-writing/grounding step |
| Cognee access | **Thin REST client** (`httpx`/`requests`), not the `cognee` SDK — proven surface, no version risk |
| Scope in | JUnit adapter, remember/recall, seeded history, engineered flake, reviewer agent, live PR comment, graph viz (real data), lifecycle confirm/forget |
| Scope out | Browser-MCP E2E enrichment (cut), flaky-detection stats, auth/multi-tenant |
| Last-priority | promptfoo adapter — only if everything else lands |
| Assembly | Monorepo (this repo), local-first, GitHub Actions wired last |
| Tooling | **uv** for everything: `uv init`/`pyproject.toml`, `uv sync`, `uv run` (no bare pip/venv) |
| Clean slate | Existing `sentinel/`, `tests/`, `requirements.txt` from v1 are **removed** in Task 0 and rebuilt |

## 4. Architecture

```
app/ (demo target: FastAPI mini-app + pytest, engineered reproducible flake)
        │  pytest --junitxml
        ▼
sentinel/adapters/junit.py ──► FailureRecord (normalized dataclass)
        │                      [promptfoo.py: same interface, last priority]
        ▼
sentinel/ingest.py
   ├─ cognee_client.remember(text, dataset)          # permanent failure record
   └─ cognee_client.recall(query, dataset)           # semantic match vs history
        │
        ▼
sentinel/reviewer.py  [AGENT — the only LLM-judgment step]
   assemble(diff + failure + recall results)
   → grounding pass: every claim must cite recalled data; ungrounded claims dropped
   → markdown review  ──► CLI output │ --post → GitHub PR comment
        │
        ▼  engineer runs: sentinel confirm <test_name> "<resolution>"
sentinel/lifecycle.py
   ├─ QA entry (question=failure query, answer=recall result) → qa_id   [session]
   ├─ FeedbackEntry(qa_id, feedback_score=1)                            [session]
   │    └─ background bridge → permanent graph (visible: Sessions → Brain)
   └─ forget: per-item / memoryOnly / dataset prune of resolved issues
        │
        ▼
viz: GET /datasets/{id}/graph → Streamlit panel (real nodes/edges)
     + platform dashboard Mindmap/Sessions/Brain shown live in demo
```

Every stage is a typed function, runnable standalone via CLI (`uv run sentinel ingest report.xml`), which is also how it's tested.

## 5. Components

### 5.1 `sentinel/cognee_client.py`
Thin REST wrapper (evolved from `smoke_test.py`): `remember(text, *, dataset, session_id=None)`, `recall(query, *, dataset, top_k=15)`, `remember_entry(entry, session_id)`, `forget(...)`, `get_graph(dataset_id)`, `quota()`. Reads env via `config.py`. Retries once on 5xx; raises `CogneeError` with response body otherwise.

### 5.2 `sentinel/config.py`
Loads `.env` (`COGNEE_BASE_URL`, `COGNEE_API_KEY`, `COGNEE_TENANT_ID`, `SENTINEL_DATASET` default `sentinel`, `GITHUB_TOKEN` optional). Single source of headers.

### 5.3 `sentinel/adapters/`
- `junit.py`: JUnit XML → `list[FailureRecord]` (test_name, class_name, error_message, stack_trace, failure_type, file_hint, run_id, timestamp). Stdlib only, no Cognee dependency. Handles `<failure>` and `<error>`, multi-suite files, malformed XML (raises `AdapterError`).
- `promptfoo.py` (last priority): promptfoo JSON results → same `FailureRecord` shape — proves the adapter interface.

### 5.4 `sentinel/ingest.py`
Per-CI-run entry point. For each failure: `recall()` first (query = raw error text + file hint, no preprocessing — Cognee does the semantic work), then `remember()` the new failure. Prints match/no-match to CLI, returns structured results for the reviewer. `--run-id` from CI.

### 5.5 `sentinel/reviewer.py` — the agent
Input: recall results + failing test info + `git diff` of the triggering change. Uses the Claude API (single call, not an agent loop): system prompt enforces the grounding contract — *every factual claim about history must quote/cite a recalled record; if nothing grounds, output the honest "new failure, no history" review*. Output: markdown review. `--post` posts to the PR via GitHub REST (`GITHUB_TOKEN`); otherwise prints. A `verify` step lints the draft: any sentence referencing prior incidents must contain a fragment from the recall payload, else it's dropped (deterministic check, not LLM self-grading alone).

### 5.6 `sentinel/lifecycle.py`
- `confirm <test_name> "<resolution>"`: writes QA entry + positive FeedbackEntry into an incident session (`incident-<run_id>`), then `remember(resolution_text, session_id=...)` so the fix bridges to the permanent graph. Demo shows the session appear in the dashboard Sessions page, then the knowledge land in Brain.
- `forget --test <name> | --stale`: real deletion via `/forget` (per-item where data_id known, `memoryOnly` for re-cognify demos, dataset prune for cleanup).

### 5.7 `sentinel/seed_loader.py` + `sentinel/seed_data.jsonl`
20 synthetic historical failures across 5 error clusters, each with a resolution. Batched into a few `remember()` calls (not per-row cognify) with `run_in_background=false` so completion is deterministic. At least two records are deliberate *semantic* (not string) matches for the engineered flake.

### 5.8 `app/` — demo target
Minimal FastAPI service (webhook-processing feature) + pytest suite emitting JUnit XML. Contains one **deliberately engineered, reproducible race condition** in retry logic, toggled by env flag (`FLAKY_MODE=1` guarantees failure; unset, tests pass) so the demo fires on cue.

### 5.9 `viz/graph_panel.py`
Streamlit page: fetches `GET /datasets/{id}/graph`, renders real nodes/edges (pyvis), plus recall query box. Secondary to the platform dashboard's own Mindmap — the demo uses both.

### 5.10 `.github/workflows/sentinel.yml`
Written last. Runs `uv sync`, pytest with `--junitxml`, then `always()`: `uv run sentinel ingest … && uv run sentinel review --post`. Secrets: `COGNEE_*`, `ANTHROPIC_API_KEY`, `GITHUB_TOKEN`.

## 6. Cognee data design

- Single dedicated dataset `sentinel` (context-pollution guard per PRD §12b/13b). Smoke/dev use `sentinel_smoke`, deleted via `forget` after.
- Permanent graph: failure records + resolutions (seed + live failures). Relational richness (test ↔ error signature ↔ file ↔ fix) comes from cognify's extraction over well-formatted records.
- Sessions: one per incident (`incident-<run_id>`) holding QA + feedback entries; bridged in the background; visible in dashboard.

## 7. Error handling

- No recall match → explicit "new failure — no history" path (demo's *before* case).
- Cognee/Claude/GitHub API failures → fail soft with a message; the CI step never fails the build (`continue-on-error` semantics in the workflow; try/except at CLI top level).
- Reviewer grounding failure → honest fallback review, never invented history.
- Adapter gets malformed XML → `AdapterError` with the offending path; exit code 0 in CI (soft), non-zero locally.

## 8. Testing

- Unit tests (uv-run pytest): adapters against fixture XMLs (pass/fail/error/multi-suite/malformed), cognee_client against a mocked `requests` transport, reviewer grounding lint against canned recall payloads, lifecycle entry construction. No live calls.
- Integration: `@pytest.mark.integration`, skipped by default, hits `sentinel_smoke` dataset and cleans up with `forget`.
- `scripts/demo_dryrun.py`: full demo sequence end-to-end for rehearsal.

## 9. Build order (2 days)

**Task 0 — clean slate + uv (first):** delete v1 `sentinel/`, `tests/`, `requirements.txt`; `uv init` with `pyproject.toml` (deps: requests, python-dotenv, fastapi, uvicorn, streamlit, pyvis, anthropic, pytest + plugins as dev group); everything thereafter via `uv run` / `uv sync`.

**Day 1 (today):** Task 0 → cognee_client (from smoke_test.py) → junit adapter → ingest (recall→remember) → seed data loaded → `app/` with engineered flake → verified semantic match on the flake. *Complete honest demo exists here.*

**Day 2:** reviewer agent + grounding + PR posting → lifecycle confirm/forget → viz panel → CI workflow → demo rehearsal (dry-run script) → promptfoo adapter only if idle time remains.

## 10. Demo script (~90s)

1. Dashboard Mindmap open: memory graph of 20 seeded incidents.
2. `FLAKY_MODE=1 uv run pytest app/` → failure → `sentinel ingest` → recall finds 2 semantically-similar prior incidents (different wording, same root cause).
3. `sentinel review --post` → grounded PR comment appears on a real PR — the "better than CodeRabbit" moment.
4. `sentinel confirm` → session appears in dashboard Sessions → bridged into Brain (improve, live).
5. `sentinel forget --test <old>` → node gone from graph (forget, live).
