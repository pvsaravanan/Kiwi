# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

**Python backend (uv-managed, Python 3.12+):**
```bash
uv sync                                   # install/sync dependencies
uv run pytest tests/ app/tests/ -q        # full non-integration suite (default: -m 'not integration')
uv run pytest tests/agent/test_loop.py::test_loop_ends_immediately_on_final_text_response -v  # single test
uv run pytest -m integration              # integration tests (hit the local self-hosted Cognee server / real LLM APIs; excluded by default)
uv run uvicorn app.main:app --port 8000   # run the FastAPI backend alone
```

**Frontend (kiwi-ui, pnpm):**
```bash
pnpm install --prefix kiwi-ui             # install UI deps
```

**Run the full app** (backend + Ink terminal REPL together):
```bash
.\kiwi        # PowerShell
kiwi          # CMD
pnpm kiwi     # via root package.json
```
`kiwi.ps1` starts the FastAPI backend as a background process, then launches the Ink REPL in the foreground; on exit it kills the backend process.

**CI ingestion runner** (parses a JUnit XML report, ingests into Cognee, optionally posts a PR review comment):
```bash
uv run python scripts/ci_runner.py <path/to/junit.xml> --review --post --repo owner/repo --pr 123
```

There is no configured linter for either the Python or TypeScript side (no ruff/flake8/eslint config present). `kiwi-ui/tsconfig.json` has `strict: true` if you want an ad hoc `pnpm exec tsc --noEmit` type check.

## Architecture

Kiwi is a terminal-native QA assistant. Its architecture has three layers plus a Cognee-backed memory store:

```
kiwi-ui/index.tsx (React + Ink REPL)
        |  axios / fetch (NDJSON streaming for agentic + chat endpoints)
app/main.py (FastAPI backend, single-file router)
        |
sentinel/  (config, memory client, LLM client, ingest/review, agent loop)
        |
Cognee (self-hosted via docker-compose.cognee.yml, no auth — kiwi.ps1 starts it automatically)
```

### Config resolution

`sentinel/config.py` loads `.env*` files in priority order (`.env.local` > `.env.<mode>.local` > `.env.<mode>` > `.env`) at import time via `python-dotenv`. `COGNEE_BASE_URL` comes straight from env, defaulting to `http://localhost:8010` (self-hosted Cognee needs no credentials). Once a user has run `/login`, `kiwi_session_state.json` (gitignored, **Fernet-encrypted** via `sentinel/session_state.py`, key in gitignored `kiwi_secret.key`) takes priority over env vars for the active LLM provider/model only. `sentinel/session_state.py` is the single shared `load_state()`/`save_state()` used by `app/main.py`, `sentinel/config.py`, and `sentinel/llm_client.py` — don't read/write `kiwi_session_state.json` directly from a new call site.

### Self-hosted Cognee server

`docker-compose.cognee.yml` runs the official `cognee/cognee:main` image, bound to `127.0.0.1:8010` only (8000 collides with Kiwi's own backend), no auth, file-based storage. `kiwi.ps1` starts it automatically before the backend, resolving a real `LLM_API_KEY` for Cognee's own internal cognify pipeline from whichever of `ANTHROPIC_API_KEY`/`OPENAI_API_KEY`/`GEMINI_API_KEY` is real in `.env` — separate from (but often the same underlying key as) whichever provider Kiwi's own chat/agent loop is using. It writes that key to a transient `.cognee_compose.env` file (gitignored, `-Encoding ascii` — not `utf8`, which emits a BOM that corrupts `docker compose --env-file`'s first key) and cleans it up in a `finally` block; inherited `$env:` vars did not reliably substitute into the compose file's `${VAR}` references on Windows/Docker Desktop, hence the file. The container is never stopped on `/exit` — it's a persistent local data store.

### Two separate LLM code paths — don't conflate them

- **`sentinel/llm_client.py`** — plain prompt-in/text-out calls (`ask_llm`, `stream_llm`, `validate_llm_credentials`) used by the one-shot NL chat path (`/kiwi/query`) and `sentinel/reviewer.py`. Each provider branch is hand-rolled per function.
- **`sentinel/agent/providers/`** — native tool-calling adapters (`AnthropicAdapter`, `OpenAIAdapter`, `GeminiAdapter`) behind a shared `ProviderAdapter.converse(messages, tools, system) -> AgentResponse` protocol, used only by the agentic `/fix` loop (`sentinel/agent/loop.py`). `sentinel/agent/providers/build_adapter(provider, client, model)` is the factory. These two paths intentionally don't share code — the message/tool-call shapes are fundamentally different (plain text vs. structured tool calls).

Known cross-provider gotchas already fixed once, worth remembering before "fixing" them again:
- OpenAI's `gpt-5.x` model family rejects the legacy `max_tokens` param — use `max_completion_tokens` (all three call sites in `llm_client.py`, plus anywhere new that calls `chat.completions.create`).
- Gemini requires echoing back a response's `thought_signature` field on any later turn that replays a prior function call, or the API 400s. `sentinel/agent/types.py`'s `ToolCall.provider_data` exists specifically to carry this (and future provider-specific metadata) through the loop without polluting the shared type for Anthropic/OpenAI.

### Agentic `/fix` loop

`sentinel/agent/loop.py:run_agent_loop()` is a synchronous generator: call the active provider, execute any returned tool calls against `sentinel/agent/tools.py:TOOL_REGISTRY` (7 tools: `read_file`, `search_code`, `edit_file`, `shell`, `run_tests`, `recall`, `remember` — `edit_file`/`shell` require approval), feed results back, repeat up to `MAX_ITERATIONS` (10). It stops **deterministically** the instant `run_tests` returns its exact `ALL_TESTS_PASSED` string (`sentinel/agent/tools.py`) — don't rely on the system prompt alone to make the model stop, the loop enforces it in code.

`app/agent_bridge.py`'s `AgentRun` bridges this synchronous generator to an async NDJSON stream: it runs the loop in a background thread, pipes `LoopEvent`s through a `queue.Queue` to `POST /kiwi/agent/start`'s streaming response, and blocks on a second `queue.Queue` per pending approval until `POST /kiwi/agent/approve` resolves it. All file-touching tools sandbox to `ctx.repo_root` (`_is_contained`/`_safe_path` in `tools.py`) — when the live `/kiwi/agent/start` endpoint runs, `repo_root` is the actual Kiwi checkout (`Path.cwd()`), so tool calls from a live run can touch real repository files.

`/fix [path]` is reachable both as a direct slash command and via natural language — `/kiwi/query`'s system prompt lists `fix` as an action in its taxonomy, and the UI routes that action to the same `/kiwi/agent/start` flow instead of replaying it as a one-shot command like other actions.

### Testing conventions

Plain `pytest` + `unittest.mock.MagicMock`/`monkeypatch` throughout — no other test framework, no fixtures-heavy setup beyond a shared `tests/fixtures/` dir for JUnit XML samples. Tests marked `@pytest.mark.integration` hit live external services (the local self-hosted Cognee server, real LLM APIs) and are excluded by the default `addopts` in `pyproject.toml`; run them explicitly and expect them to need the Cognee container running (`docker compose -f docker-compose.cognee.yml up -d`) and real LLM credentials in `.env`.

### Design docs for larger changes

Non-trivial features get a design spec under `docs/superpowers/specs/YYYY-MM-DD-<topic>-design.md` and, once approved, an implementation plan under `docs/superpowers/plans/`. Check there before assuming a "planned" feature referenced in README/docs is already implemented — docs consistently mark unshipped work as *(planned)* with a link to its spec.
