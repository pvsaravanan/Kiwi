# Migrate from Cognee Cloud to Self-Hosted Cognee — Design

**Date:** 2026-07-20
**Status:** Approved, not yet implemented

## Problem

Kiwi's memory layer (`sentinel/cognee_client.py`) talks to Cognee Cloud, a paid managed service, authenticated via `X-Api-Key`/`X-Tenant-Id` headers. Cognee itself is fully open source and can be self-hosted via Docker at no cost, with file-based storage (SQLite + LanceDB + KùzuDB) requiring no additional infrastructure. This migration replaces the Cloud dependency with a local, Dockerized Cognee instance.

## Goals

- Fully replace Cognee Cloud — no dual-mode/config-switchable backend. Simpler code, no parallel test/maintenance burden for a path nobody uses once the paid service is dropped.
- Ship the Docker service as part of Kiwi's own setup (a `docker-compose.cognee.yml` in the repo), not an external manual prerequisite the user has to source themselves.
- Run with Cognee's own auth disabled — Kiwi is a local, single-user dev tool; there is no multi-tenant or remote-access need to justify the auth setup cost.
- Simplify `/login` to drop everything Cognee-credential-related, since self-hosted local Cognee needs none.
- Auto-start the Cognee container from Kiwi's existing launcher (`kiwi.ps1`), matching the launcher's existing responsibility for starting the FastAPI backend.

## Non-goals

- No Postgres/Neo4j backend — file-based storage only for this migration.
- No multi-tenancy, no auth.
- No automated migration of existing Cognee Cloud data — it's dev/test data (seeded failure records), fine to start the self-hosted instance fresh.
- No support for pointing at someone else's remote self-hosted Cognee instance beyond a plain `COGNEE_BASE_URL` override — no auth token flow for that case.

## Verified API compatibility

Checked directly against the Cognee OSS source on GitHub (`topoteretes/cognee`), not just documentation, since Cloud-only endpoint naming was a real risk:

| `CogneeClient` method | Self-hosted OSS route | Verified against |
|---|---|---|
| `remember(text, dataset, session_id)` → `POST /api/v1/remember` (multipart: `datasetName`, `session_id`) | `POST /v1/remember`, `datasetName`/`datasetId`/`session_id` as Form fields | `cognee/api/v1/remember/routers/get_remember_router.py` |
| `recall(query, dataset, top_k)` → `POST /api/v1/recall` (`{query, datasets, topK}`) | `POST /v1/recall`, `RecallPayloadDTO{query, datasets, top_k}` | `cognee/api/v1/recall/routers/get_recall_router.py` |
| `forget(dataset, data_id, memory_only, everything)` → `POST /api/v1/forget` | `POST /v1/forget`, same four fields | `cognee/api/v1/forget/routers/get_forget_router.py` |

Field names and semantics match exactly — the request/response shapes in `sentinel/cognee_client.py` require no changes, only the auth headers change. `datasets()`/`graph()` (used by `viz/graph_panel.py`) were not individually verified against source; confirm during implementation before assuming their shapes also carry over unchanged.

## Docker service

New `docker-compose.cognee.yml` at repo root, referencing the official prebuilt `cognee/cognee` Docker Hub image directly — no need to clone or vendor the Cognee source repo.

- **Port**: Cognee's container defaults to port 8000 internally, which collides with Kiwi's own backend (`uv run uvicorn app.main:app --port 8000`). Map the host side to **8010** instead (`8010:8000`); Kiwi's backend port is untouched.
- **Storage**: no `postgres`/`neo4j` compose profile — defaults to SQLite + LanceDB + KùzuDB, file-based, no extra services to run.
- **`LLM_API_KEY`**: Cognee's own internal cognify pipeline (entity/relationship extraction) needs an LLM key, resolved by the launcher from whichever of `ANTHROPIC_API_KEY` / `OPENAI_API_KEY` / `GEMINI_API_KEY` Kiwi already has configured in `.env` — reuses the existing key, no new secret to create or manage.
- **Auth**: `REQUIRE_AUTHENTICATION` left unset (off) — matches the "run auth-off locally" decision.

## Config & client changes

- `sentinel/config.py`: `Settings` drops the `api_key` and `tenant_id` fields entirely. `COGNEE_BASE_URL` gets a default of `http://localhost:8010` (still overridable via `.env`). `auth_headers()` is deleted — nothing calls it anymore.
- `sentinel/cognee_client.py`: `_request` no longer sends `X-Api-Key`/`X-Tenant-Id` headers. Method bodies (`remember`, `recall`, `forget`, `datasets`, `graph`) are otherwise unchanged — verified paths/payloads above carry over.
- `.env` / `.env.example`: remove `COGNEE_API_KEY`, `COGNEE_TENANT_ID`. `COGNEE_BASE_URL` becomes optional (commented out, defaulted in code) rather than a required-looking placeholder line.

## Login flow simplification

With no Cognee credential left to collect, `/login` shrinks from a 5-step flow (base URL → API key → tenant ID → LLM provider → LLM model) to 2 steps (LLM provider → LLM model):

- `app/main.py`: `LoginDetails` Pydantic model drops `base_url`/`api_key`/`tenant_id`, keeping only `llm_provider`/`llm_model`. `auth_status`'s response drops the same three fields from its payload — this also closes a pre-existing issue where that endpoint echoed the raw Cognee API key back in its JSON response body, since there's no longer a secret to echo.
- `sentinel/session_state.py`: the persisted session-state shape drops `base_url`/`api_key`/`tenant_id`, keeping `is_logged_in`/`llm_provider`/`llm_model`.
- `kiwi-ui/index.tsx`: the `LoginState` type and its step machine (`base_url` → `api_key` → `tenant_id` → `llm_provider` → `llm_model`) shrink to just `llm_provider` → `llm_model`. The `envCredentials`/"Cognee credentials detected from .env file!" auto-detection branch is removed, since there is nothing Cognee-related left to auto-detect from env.

## Launcher integration

`kiwi.ps1` runs `docker compose -f docker-compose.cognee.yml up -d` before starting the FastAPI backend (in addition to its existing uvicorn auto-start), polling a health endpoint until the container is ready rather than a fixed sleep. The container is **not** stopped when Kiwi exits — it's a persistent local data store, the same way you wouldn't tear down a local database every time you close a client that uses it. `docker compose -f docker-compose.cognee.yml down` is a manual, documented step for anyone who wants to fully reset or reclaim resources.

## Docs

Update to reflect self-hosted Cognee instead of Cloud: `README.md` (Configuration Setup, Getting Started, System Architecture diagrams), `docs/commands.md` (`/login`'s shortened flow), `docs/exploration_guide.md`, `docs/subsystems.md`. `prd.md` (the original hackathon PRD, which explicitly locked in "Best Use of Cognee Cloud" as a prize-track decision) is left untouched — it documents a past decision point, not current architecture.

## Testing

- `tests/test_config.py`: remove the tests asserting `COGNEE_API_KEY`/`COGNEE_TENANT_ID` are required (they raise `RuntimeError` today via `_require`); add a test that `load_settings()` defaults `base_url` to `http://localhost:8010` when `COGNEE_BASE_URL` is unset.
- `tests/test_cognee_client.py`: remove assertions on `X-Api-Key`/`X-Tenant-Id` request headers.
- `tests/test_integration_cloud.py` is replaced by a self-hosted equivalent (same lifecycle-roundtrip shape: remember → recall → remember_entry → forget in a `finally`), requiring a running local Cognee container instead of cloud credentials — consistent with fully replacing Cloud rather than keeping the cloud-only integration test around unused.

## Rollout

1. `docker-compose.cognee.yml` + launcher integration, verified manually against a running container (curl smoke test of `/api/v1/remember`/`/recall`/`/forget` before touching any Python).
2. `sentinel/config.py` + `sentinel/cognee_client.py` changes, unit-tested in isolation.
3. `/login` simplification: `app/main.py` + `sentinel/session_state.py` + `kiwi-ui/index.tsx`.
4. Docs updates.
5. Integration test replacement, run manually against the local container (not part of the default `-m 'not integration'` suite).
