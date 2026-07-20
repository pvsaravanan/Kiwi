# Migrate to Self-Hosted Cognee Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fully replace Cognee Cloud with a self-hosted, Dockerized Cognee instance running with auth disabled, simplify `/login` from 5 steps to 2, and auto-start the container from Kiwi's launcher.

**Architecture:** A new `docker-compose.cognee.yml` runs the official `cognee/cognee` image on host port 8010 (avoiding Kiwi's own backend on 8000). `sentinel/config.py`/`sentinel/cognee_client.py` drop all Cognee auth (`api_key`/`tenant_id`/`auth_headers`) since the verified REST routes (`/api/v1/remember`, `/recall`, `/forget`) are otherwise unchanged. `app/main.py`'s `/login`/`auth-status` and `kiwi-ui/index.tsx`'s login state machine shrink to just LLM provider/model. `kiwi.ps1` resolves an `LLM_API_KEY` from whichever provider key Kiwi already has and starts the container before the backend.

**Tech Stack:** Python 3.12 (`uv`), FastAPI, React + Ink (TypeScript), Docker Compose, pytest.

## Global Constraints

- Fully replace Cognee Cloud — no dual-mode/config-switchable backend (spec: "Fully replace Cloud (Recommended)").
- Self-hosted Cognee runs with auth disabled (`REQUIRE_AUTHENTICATION` unset) — no token flow, no API key/tenant ID for Cognee itself.
- `COGNEE_BASE_URL` defaults to `http://localhost:8010` (8000 collides with Kiwi's own backend) but remains overridable via `.env`.
- Cognee's own `LLM_API_KEY` (for its internal cognify pipeline) is resolved from whichever of `ANTHROPIC_API_KEY`/`OPENAI_API_KEY`/`GEMINI_API_KEY` Kiwi already has configured — no new secret to manage.
- No Postgres/Neo4j — file-based storage only (Cognee's default).
- `/login` becomes exactly 2 steps: LLM provider → LLM model. No Cognee credential prompts.
- `docker-compose.cognee.yml`'s container is not stopped when Kiwi exits (persistent local data store, same reasoning as not tearing down a local database on client exit).
- No JS test framework exists in `kiwi-ui` — UI task steps use manual verification, not automated tests (same constraint as the prior agentic-harness plan).
- Reference spec: `docs/superpowers/specs/2026-07-20-cognee-self-hosted-migration-design.md`.

---

## Task 1: `docker-compose.cognee.yml` + manual endpoint verification

**Files:**
- Create: `docker-compose.cognee.yml`

**Interfaces:**
- Produces: a `cognee` service reachable at `http://localhost:8010`, reading `LLM_API_KEY`/`LLM_PROVIDER`/`LLM_MODEL` from the environment `docker compose` is invoked with (no `.env` file reference needed in the compose file itself — Task 5's `kiwi.ps1` sets these as process env vars before calling `docker compose up`).

This task has no automated tests — Docker/infra config isn't pytest-testable. Verify manually as described below, since Task 2 needs confirmed-correct endpoint paths before touching any Python.

- [ ] **Step 1: Write the compose file**

`docker-compose.cognee.yml`:
```yaml
services:
  cognee:
    image: cognee/cognee:main
    ports:
      - "8010:8000"
    environment:
      LLM_API_KEY: ${LLM_API_KEY}
      LLM_PROVIDER: ${LLM_PROVIDER}
      LLM_MODEL: ${LLM_MODEL}
    volumes:
      - cognee_data:/app/.data
    restart: unless-stopped

volumes:
  cognee_data:
```

- [ ] **Step 2: Start it manually with a real key**

Run (PowerShell, substituting a real Anthropic key you have):
```powershell
$env:LLM_API_KEY = "<your real ANTHROPIC_API_KEY>"
$env:LLM_PROVIDER = "anthropic"
$env:LLM_MODEL = "anthropic/claude-opus-4-8"
docker compose -f docker-compose.cognee.yml up -d
```
Expected: container starts, `docker compose -f docker-compose.cognee.yml ps` shows it `Up`.

- [ ] **Step 3: Confirm the actual data volume path**

Run: `docker compose -f docker-compose.cognee.yml exec cognee sh -c "ls -la / && find / -maxdepth 3 -iname '*.db' -o -iname '*.lance' 2>/dev/null"`

If the SQLite/LanceDB/KùzuDB files don't appear under `/app/.data`, find their actual location from this output and update the `volumes:` line in `docker-compose.cognee.yml` to match (e.g. `/app/cognee_data` or wherever they actually land), then re-run `docker compose -f docker-compose.cognee.yml up -d` to pick up the change. Record the confirmed path in this task's step so Task 5 doesn't need to re-derive it.

- [ ] **Step 4: Confirm the health check path**

Run: `curl -s -o /dev/null -w "%{http_code}\n" http://localhost:8010/health`

If that doesn't return `200`, try `curl -s http://localhost:8010/openapi.json | grep -o '"/[a-z/]*health[a-z/]*"'` to find the real path from the container's own OpenAPI schema, and use that path in Task 5's `kiwi.ps1` polling loop instead of `/health`.

- [ ] **Step 5: Smoke-test the three endpoints Kiwi actually calls**

```bash
curl -s -X POST http://localhost:8010/api/v1/remember \
  -F "datasetName=smoke_test" \
  -F "data=@-;filename=record.txt;type=text/plain" <<< "Test failed: race condition caused duplicate charge. Fixed by adding an idempotency key."

curl -s -X POST http://localhost:8010/api/v1/recall \
  -H "Content-Type: application/json" \
  -d '{"query": "duplicate charge after concurrent retries", "datasets": ["smoke_test"], "topK": 5}'

curl -s -X POST http://localhost:8010/api/v1/forget \
  -H "Content-Type: application/json" \
  -d '{"dataset": "smoke_test", "everything": false}'
```
Expected: `remember` returns a success payload (may take ~20s, same as Cloud), `recall` returns a list containing a hit whose `text` mentions "idempotency", `forget` returns a success payload. If any of these 404 or return an unexpected shape, stop and report — Task 2 assumes these three routes work exactly as tested here.

- [ ] **Step 6: Leave the container running for Task 2's testing, and commit**

```bash
git add docker-compose.cognee.yml
git commit -m "feat: add self-hosted Cognee docker-compose service"
```

---

## Task 2: `sentinel/config.py` + `sentinel/cognee_client.py` — drop Cognee auth

**Files:**
- Modify: `sentinel/config.py`
- Modify: `sentinel/cognee_client.py`
- Modify: `tests/test_config.py`
- Modify: `tests/test_cognee_client.py`

**Interfaces:**
- Produces: `Settings(base_url: str, dataset: str)` (drops `api_key`/`tenant_id`), `DEFAULT_BASE_URL = "http://localhost:8010"`, `load_settings() -> Settings` (no longer requires env vars, no longer session-state-dependent since `/login` — Task 4 — no longer collects `base_url`). `auth_headers()` and `_require()` are deleted. `CogneeClient._request` no longer sends any `headers` kwarg.

- [ ] **Step 1: Write the failing tests**

Replace the full contents of `tests/test_config.py`:
```python
import pytest

from sentinel.config import DEFAULT_BASE_URL, load_settings


@pytest.fixture
def env(monkeypatch):
    monkeypatch.delenv("COGNEE_BASE_URL", raising=False)
    monkeypatch.delenv("SENTINEL_DATASET", raising=False)


def test_load_settings_defaults_base_url_when_unset(env):
    assert load_settings().base_url == DEFAULT_BASE_URL


def test_load_settings_reads_env_and_strips_trailing_slash(env, monkeypatch):
    monkeypatch.setenv("COGNEE_BASE_URL", "http://localhost:9999/")
    assert load_settings().base_url == "http://localhost:9999"


def test_dataset_defaults_to_sentinel(env):
    assert load_settings().dataset == "sentinel"


def test_dataset_reads_env(env, monkeypatch):
    monkeypatch.setenv("SENTINEL_DATASET", "other")
    assert load_settings().dataset == "other"
```

Replace the full contents of `tests/test_cognee_client.py`:
```python
from unittest.mock import MagicMock

import pytest

from sentinel.cognee_client import CogneeClient, CogneeError
from sentinel.config import Settings

S = Settings(base_url="https://t.example", dataset="sentinel")


def make_client(status=200, payload=None):
    http = MagicMock()
    resp = MagicMock()
    resp.status_code = status
    resp.json.return_value = payload if payload is not None else {}
    resp.text = "body"
    http.request.return_value = resp
    return CogneeClient(settings=S, http=http), http


def test_remember_posts_multipart_with_dataset_and_no_auth_headers():
    client, http = make_client(payload={"status": "completed"})
    out = client.remember("failure text", dataset="sentinel")
    assert out == {"status": "completed"}
    _, kwargs = http.request.call_args
    assert http.request.call_args[0] == ("POST", "https://t.example/api/v1/remember")
    assert kwargs["data"] == {"datasetName": "sentinel"}
    assert "data" in kwargs["files"]
    assert "headers" not in kwargs


def test_remember_includes_session_id_when_given():
    client, http = make_client(payload={"status": "session_stored"})
    client.remember("confirm", dataset="sentinel", session_id="incident-1")
    assert http.request.call_args.kwargs["data"]["session_id"] == "incident-1"


def test_recall_posts_json_and_returns_list():
    client, http = make_client(payload=[{"text": "prior incident"}])
    out = client.recall("dup charge?", dataset="sentinel", top_k=5)
    assert out == [{"text": "prior incident"}]
    assert http.request.call_args[0] == ("POST", "https://t.example/api/v1/recall")
    assert http.request.call_args.kwargs["json"] == {
        "query": "dup charge?", "datasets": ["sentinel"], "topK": 5,
    }


def test_remember_entry_posts_entry_and_session():
    client, http = make_client(payload={"entry_id": "e1"})
    out = client.remember_entry({"type": "qa", "question": "q", "answer": "a"}, session_id="s1")
    assert out["entry_id"] == "e1"
    assert http.request.call_args.kwargs["json"] == {
        "entry": {"type": "qa", "question": "q", "answer": "a"}, "session_id": "s1",
    }


def test_forget_dataset():
    client, http = make_client(payload={"status": "success"})
    client.forget(dataset="sentinel_smoke")
    body = http.request.call_args.kwargs["json"]
    assert body["dataset"] == "sentinel_smoke"
    assert body["everything"] is False


def test_4xx_raises_cognee_error_with_body():
    client, _ = make_client(status=422)
    with pytest.raises(CogneeError, match="422"):
        client.recall("q", dataset="d")


def test_5xx_retries_once_then_succeeds():
    http = MagicMock()
    bad = MagicMock(status_code=500, text="boom")
    good = MagicMock(status_code=200)
    good.json.return_value = [{"text": "ok"}]
    http.request.side_effect = [bad, good]
    client = CogneeClient(settings=S, http=http)
    assert client.recall("q", dataset="d") == [{"text": "ok"}]
    assert http.request.call_count == 2
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_config.py tests/test_cognee_client.py -v`
Expected: FAIL — `test_config.py` fails with `ImportError: cannot import name 'DEFAULT_BASE_URL'`; `test_cognee_client.py` fails with `TypeError: Settings.__init__() got an unexpected keyword argument 'api_key'` (the old 4-field `Settings` doesn't match the new 2-arg construction yet).

- [ ] **Step 3: Rewrite the implementation**

Replace the full contents of `sentinel/config.py`:
```python
import os
from dataclasses import dataclass
from dotenv import load_dotenv

import glob

# Dynamically discover all .env files and load them in priority order
env_files = [f for f in glob.glob(".env*") if not f.endswith(".example")]
def get_priority(filename):
    if filename == ".env.local":
        return 0
    if filename.endswith(".local"):
        return 1
    if filename == ".env":
        return 3
    return 2

env_files.sort(key=get_priority)
for f in env_files:
    if os.path.isfile(f):
        load_dotenv(f)


# Self-hosted Cognee's default port (8000) collides with Kiwi's own backend,
# so docker-compose.cognee.yml maps it to the host at 8010 instead.
DEFAULT_BASE_URL = "http://localhost:8010"


@dataclass(frozen=True)
class Settings:
    base_url: str
    dataset: str


def load_settings() -> Settings:
    base_url = os.environ.get("COGNEE_BASE_URL", "").strip() or DEFAULT_BASE_URL
    return Settings(
        base_url=base_url.rstrip("/"),
        dataset=os.environ.get("SENTINEL_DATASET", "sentinel"),
    )
```

Replace the full contents of `sentinel/cognee_client.py`:
```python
import io

import requests

from sentinel.config import Settings, load_settings


class CogneeError(RuntimeError):
    pass


class CogneeClient:
    """Thin wrapper over a self-hosted Cognee REST API (no auth for local single-user use)."""

    def __init__(self, settings: Settings | None = None, http=None):
        self.settings = settings or load_settings()
        self.http = http or requests.Session()

    def _request(self, method: str, path: str, *, timeout: int = 180, **kwargs):
        url = f"{self.settings.base_url}{path}"
        resp = self.http.request(method, url, timeout=timeout, **kwargs)
        if resp.status_code >= 500:  # one retry on transient server errors
            resp = self.http.request(method, url, timeout=timeout, **kwargs)
        if resp.status_code >= 400:
            raise CogneeError(f"{method} {path} -> HTTP {resp.status_code}: {resp.text[:500]}")
        return resp.json()

    def remember(self, text: str, *, dataset: str, session_id: str | None = None,
                 filename: str = "record.txt") -> dict:
        form: dict = {"datasetName": dataset}
        if session_id:
            form["session_id"] = session_id
        files = {"data": (filename, io.BytesIO(text.encode("utf-8")), "text/plain")}
        # remember runs the full cognify pipeline synchronously (~20s per call)
        return self._request("POST", "/api/v1/remember", data=form, files=files, timeout=560)

    def recall(self, query: str, *, dataset: str, top_k: int = 15) -> list[dict]:
        return self._request("POST", "/api/v1/recall",
                             json={"query": query, "datasets": [dataset], "topK": top_k})

    def remember_entry(self, entry: dict, *, session_id: str) -> dict:
        return self._request("POST", "/api/v1/remember/entry",
                             json={"entry": entry, "session_id": session_id}, timeout=60)

    def forget(self, *, dataset: str | None = None, data_id: str | None = None,
               memory_only: bool = False, everything: bool = False) -> dict:
        return self._request("POST", "/api/v1/forget", json={
            "dataset": dataset, "dataId": data_id,
            "memoryOnly": memory_only, "everything": everything,
        })

    def datasets(self) -> list[dict]:
        return self._request("GET", "/api/v1/datasets/", timeout=60)

    def graph(self, dataset_id: str) -> dict:
        return self._request("GET", f"/api/v1/datasets/{dataset_id}/graph", timeout=120)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_config.py tests/test_cognee_client.py -v`
Expected: PASS (4 + 8 = 12 passed)

- [ ] **Step 5: Run the full non-integration suite to check for regressions**

Run: `uv run pytest tests/ app/tests/ -q`
Expected: some failures are EXPECTED here — `tests/test_integration_cloud.py` collection and any code still referencing the old 4-field `Settings`/`auth_headers` (Task 3's `app/main.py` changes and Task 7's integration test replacement haven't happened yet). Confirm the failures are limited to those, not something new and unrelated; do not attempt to fix `app/main.py` or the integration test in this task.

- [ ] **Step 6: Commit**

```bash
git add sentinel/config.py sentinel/cognee_client.py tests/test_config.py tests/test_cognee_client.py
git commit -m "feat: drop Cognee Cloud auth from config and client, default to self-hosted URL"
```

---

## Task 3: `app/main.py` — simplify `/login` and `/auth-status`

**Files:**
- Modify: `app/main.py`
- Create: `app/tests/test_login_endpoints.py`

**Interfaces:**
- Consumes: `sentinel.session_state.{load_state, save_state}` (existing), `sentinel.llm_client.validate_llm_credentials` (existing, imported locally inside `kiwi_login` — unchanged calling convention).
- Produces: `LoginDetails(llm_provider: str, llm_model: str)` (drops `base_url`/`api_key`/`tenant_id`). `GET /kiwi/auth-status` response shape becomes `{is_logged_in, llm_provider, llm_model}` (drops `base_url`/`api_key`/`tenant_id`/`has_env_credentials`). `POST /kiwi/login` no longer persists `base_url`/`api_key`/`tenant_id` into session state.

- [ ] **Step 1: Write the failing tests**

`app/tests/test_login_endpoints.py`:
```python
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.main import app


def test_kiwi_login_success_sets_is_logged_in_true():
    with patch("app.main.load_state", return_value={}), \
         patch("app.main.save_state") as mock_save, \
         patch("sentinel.llm_client.validate_llm_credentials", return_value=(True, "")):
        client = TestClient(app)
        resp = client.post("/kiwi/login", json={"llm_provider": "anthropic", "llm_model": "claude-opus-4-8"})

    assert resp.status_code == 200
    assert resp.json() == {"status": "success"}
    saved_state = mock_save.call_args[0][0]
    assert saved_state["is_logged_in"] is True
    assert saved_state["llm_provider"] == "anthropic"
    assert saved_state["llm_model"] == "claude-opus-4-8"
    assert "base_url" not in saved_state
    assert "api_key" not in saved_state
    assert "tenant_id" not in saved_state


def test_kiwi_login_failure_returns_400_and_clears_is_logged_in():
    with patch("app.main.load_state", return_value={}), \
         patch("app.main.save_state") as mock_save, \
         patch("sentinel.llm_client.validate_llm_credentials", return_value=(False, "bad key")):
        client = TestClient(app)
        resp = client.post("/kiwi/login", json={"llm_provider": "openai", "llm_model": "gpt-5.4-mini"})

    assert resp.status_code == 400
    assert "bad key" in resp.json()["detail"]
    last_saved_state = mock_save.call_args[0][0]
    assert last_saved_state["is_logged_in"] is False


def test_login_details_only_requires_llm_provider_and_model():
    with patch("app.main.load_state", return_value={}), \
         patch("app.main.save_state"), \
         patch("sentinel.llm_client.validate_llm_credentials", return_value=(True, "")):
        client = TestClient(app)
        resp = client.post("/kiwi/login", json={"llm_provider": "gemini", "llm_model": "gemini-3-flash-preview"})

    assert resp.status_code == 200


def test_auth_status_only_exposes_login_and_llm_fields():
    with patch("app.main.load_state", return_value={
        "is_logged_in": True, "llm_provider": "anthropic", "llm_model": "claude-opus-4-8",
    }):
        client = TestClient(app)
        resp = client.get("/kiwi/auth-status")

    assert resp.status_code == 200
    body = resp.json()
    assert body == {"is_logged_in": True, "llm_provider": "anthropic", "llm_model": "claude-opus-4-8"}
    assert "api_key" not in body
    assert "base_url" not in body
    assert "tenant_id" not in body
    assert "has_env_credentials" not in body
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest app/tests/test_login_endpoints.py -v`
Expected: FAIL — `test_kiwi_login_success_sets_is_logged_in_true` fails with a `pydantic.ValidationError` (current `LoginDetails` requires `base_url`/`api_key`/`tenant_id`); `test_auth_status_only_exposes_login_and_llm_fields` fails the `body == {...}` assertion (current response includes the extra fields).

- [ ] **Step 3: Simplify the implementation**

In `app/main.py`, replace:
```python
class LoginDetails(BaseModel):
    base_url: str
    api_key: str
    tenant_id: str
    llm_provider: str
    llm_model: str
```
with:
```python
class LoginDetails(BaseModel):
    llm_provider: str
    llm_model: str
```

Replace the `auth_status` endpoint:
```python
@app.get("/kiwi/auth-status")
def auth_status():
    state = load_state()
    env_base_url = os.environ.get("COGNEE_BASE_URL", "").strip()
    env_api_key = os.environ.get("COGNEE_API_KEY", "").strip()
    env_tenant_id = os.environ.get("COGNEE_TENANT_ID", "").strip()
    has_env = bool(env_base_url and env_api_key and env_tenant_id)
    return {
        "is_logged_in": state.get("is_logged_in", False),
        "base_url": state.get("base_url", env_base_url),
        "api_key": state.get("api_key", env_api_key),
        "tenant_id": state.get("tenant_id", env_tenant_id),
        "llm_provider": state.get("llm_provider", ""),
        "llm_model": state.get("llm_model", ""),
        "has_env_credentials": has_env
    }
```
with:
```python
@app.get("/kiwi/auth-status")
def auth_status():
    state = load_state()
    return {
        "is_logged_in": state.get("is_logged_in", False),
        "llm_provider": state.get("llm_provider", ""),
        "llm_model": state.get("llm_model", ""),
    }
```

Replace the `kiwi_login` endpoint:
```python
@app.post("/kiwi/login")
def kiwi_login(req: LoginDetails):
    try:
        state = load_state()
        state["is_logged_in"] = True
        state["base_url"] = req.base_url
        state["api_key"] = req.api_key
        state["tenant_id"] = req.tenant_id
        state["llm_provider"] = req.llm_provider
        state["llm_model"] = req.llm_model
        save_state(state)
```
with:
```python
@app.post("/kiwi/login")
def kiwi_login(req: LoginDetails):
    try:
        state = load_state()
        state["is_logged_in"] = True
        state["llm_provider"] = req.llm_provider
        state["llm_model"] = req.llm_model
        save_state(state)
```
(the rest of `kiwi_login` — the `validate_llm_credentials` call and its error handling — is unchanged).

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest app/tests/test_login_endpoints.py -v`
Expected: PASS (4 passed)

- [ ] **Step 5: Run the full non-integration suite**

Run: `uv run pytest tests/ app/tests/ -q`
Expected: the only remaining pre-existing failures should be `tests/test_integration_cloud.py` (not addressed until Task 7) — everything else, including the rest of `app/tests/`, passes.

- [ ] **Step 6: Commit**

```bash
git add app/main.py app/tests/test_login_endpoints.py
git commit -m "feat: simplify /login and /auth-status to just LLM provider/model"
```

---

## Task 4: `kiwi-ui/index.tsx` — simplify the login flow

**Files:**
- Modify: `kiwi-ui/index.tsx`

**Interfaces:**
- Consumes: `POST /kiwi/login {llm_provider, llm_model}`, `GET /kiwi/auth-status` returning `{is_logged_in, llm_provider, llm_model}` (Task 3).
- Produces: `LoginState = {step: 'idle' | 'llm_provider' | 'llm_model', llmProvider?: string, llmModel?: string}` (drops `base_url`/`api_key`/`tenant_id` steps and fields). No automated tests — no JS test framework in this repo (Global Constraints) — verify manually per Step 5.

- [ ] **Step 1: Simplify the `LoginState` type and remove `envCredentials`**

Replace:
```tsx
type LoginState = {
  step: 'idle' | 'base_url' | 'api_key' | 'tenant_id' | 'llm_provider' | 'llm_model';
  baseUrl?: string;
  apiKey?: string;
  tenantId?: string;
  llmProvider?: string;
  llmModel?: string;
}
```
with:
```tsx
type LoginState = {
  step: 'idle' | 'llm_provider' | 'llm_model';
  llmProvider?: string;
  llmModel?: string;
}
```

Replace:
```tsx
  const [loginState, setLoginState] = useState<LoginState>({ step: 'idle' })
  const [envCredentials, setEnvCredentials] = useState<{ baseUrl: string, apiKey: string, tenantId: string } | null>(null)
  const ctrlCPressedRef = React.useRef(false)
```
with:
```tsx
  const [loginState, setLoginState] = useState<LoginState>({ step: 'idle' })
  const ctrlCPressedRef = React.useRef(false)
```

Replace the `checkAuth` effect:
```tsx
  useEffect(() => {
    async function checkAuth() {
      try {
        const resp = await axios.get(`${BACKEND_URL}/kiwi/auth-status`)
        if (resp.data.has_env_credentials) {
          setEnvCredentials({
            baseUrl: resp.data.base_url,
            apiKey: resp.data.api_key,
            tenantId: resp.data.tenant_id
          })
        }
        if (resp.data.is_logged_in) {
          setIsLoggedIn(true)
          setLoginState({
            step: 'idle',
            baseUrl: resp.data.base_url,
            apiKey: resp.data.api_key,
            tenantId: resp.data.tenant_id,
            llmProvider: resp.data.llm_provider,
            llmModel: resp.data.llm_model
          })
        }
      } catch (e) {
        // ignore
      }
    }
    checkAuth()
  }, [])
```
with:
```tsx
  useEffect(() => {
    async function checkAuth() {
      try {
        const resp = await axios.get(`${BACKEND_URL}/kiwi/auth-status`)
        if (resp.data.is_logged_in) {
          setIsLoggedIn(true)
          setLoginState({
            step: 'idle',
            llmProvider: resp.data.llm_provider,
            llmModel: resp.data.llm_model
          })
        }
      } catch (e) {
        // ignore
      }
    }
    checkAuth()
  }, [])
```

- [ ] **Step 2: Remove the `base_url`/`api_key`/`tenant_id` login steps from `handleSubmit`**

Replace:
```tsx
    if (loginState.step !== 'idle') {
      try {
        if (loginState.step === 'base_url') {
          setLoginState(prev => ({ ...prev, step: 'api_key', baseUrl: text }))
          setMessages(prev => [...prev, { id: assistantMsgId, role: 'assistant', content: 'Enter Cognee API Key:' }])
        } else if (loginState.step === 'api_key') {
          setLoginState(prev => ({ ...prev, step: 'tenant_id', apiKey: text }))
          setMessages(prev => [...prev, { id: assistantMsgId, role: 'assistant', content: 'Enter Tenant ID:' }])
        } else if (loginState.step === 'tenant_id') {
          setLoginState(prev => ({ ...prev, step: 'llm_provider', tenantId: text }))
          setMessages(prev => [...prev, { id: assistantMsgId, role: 'assistant', content: 'Choose LLM Provider:\n1. Anthropic\n2. OpenAI\n3. Gemini\nEnter number (1-3):' }])
        } else if (loginState.step === 'llm_provider') {
```
with:
```tsx
    if (loginState.step !== 'idle') {
      try {
        if (loginState.step === 'llm_provider') {
```

(the `llm_provider` step's own body — the provider-parsing `if/else` chain that sets `step: 'llm_model'` — is unchanged, keep it exactly as-is directly after this line)

- [ ] **Step 3: Simplify the final `llm_model` step's login POST**

Replace:
```tsx
          } else {
            const nextState = { ...loginState, step: 'idle' as const, llmModel: model }
            setLoginState(nextState)
            
            // Post to backend to save auth status persistently
            await axios.post(`${BACKEND_URL}/kiwi/login`, {
              base_url: nextState.baseUrl || '',
              api_key: nextState.apiKey || '',
              tenant_id: nextState.tenantId || '',
              llm_provider: nextState.llmProvider || '',
              llm_model: model
            })

            setIsLoggedIn(true)
            setMessages(prev => [...prev, { id: assistantMsgId, role: 'assistant', content: `Login successful! Active session initialized with provider: ${nextState.llmProvider} (${model}).` }])
          }
        }
      } finally {
```
with:
```tsx
          } else {
            const nextState = { ...loginState, step: 'idle' as const, llmModel: model }
            setLoginState(nextState)

            // Post to backend to save auth status persistently
            await axios.post(`${BACKEND_URL}/kiwi/login`, {
              llm_provider: nextState.llmProvider || '',
              llm_model: model
            })

            setIsLoggedIn(true)
            setMessages(prev => [...prev, { id: assistantMsgId, role: 'assistant', content: `Login successful! Active session initialized with provider: ${nextState.llmProvider} (${model}).` }])
          }
        }
      } finally {
```

- [ ] **Step 4: Simplify `/config` display and the `/login` command handler**

Replace:
```tsx
      } else if (text.startsWith('/config')) {
        const configDetails = [
          'Active Configuration:',
          `  - Cognee Base URL: ${loginState.baseUrl || 'Not configured'}`,
          `  - Tenant ID:       ${loginState.tenantId || 'Not configured'}`,
          `  - LLM Provider:    ${loginState.llmProvider || 'Not configured'}`,
          `  - LLM Model:       ${loginState.llmModel || 'Not configured'}`
        ].join('\n')
        setMessages(prev => [...prev, { id: assistantMsgId, role: 'assistant', content: configDetails }])
```
with:
```tsx
      } else if (text.startsWith('/config')) {
        const configDetails = [
          'Active Configuration:',
          `  - LLM Provider:    ${loginState.llmProvider || 'Not configured'}`,
          `  - LLM Model:       ${loginState.llmModel || 'Not configured'}`
        ].join('\n')
        setMessages(prev => [...prev, { id: assistantMsgId, role: 'assistant', content: configDetails }])
```

Replace:
```tsx
      } else if (text.startsWith('/login')) {
        if (envCredentials) {
          setLoginState({
            step: 'llm_provider',
            baseUrl: envCredentials.baseUrl,
            apiKey: envCredentials.apiKey,
            tenantId: envCredentials.tenantId
          })
          setMessages(prev => [...prev, { id: assistantMsgId, role: 'assistant', content: 'Cognee credentials detected from .env file!\nChoose LLM Provider:\n1. Anthropic\n2. OpenAI\n3. Gemini\nEnter number (1-3):' }])
        } else {
          setLoginState({ step: 'base_url' })
          setMessages(prev => [...prev, { id: assistantMsgId, role: 'assistant', content: 'Enter Cognee Base URL:' }])
        }
```
with:
```tsx
      } else if (text.startsWith('/login')) {
        setLoginState({ step: 'llm_provider' })
        setMessages(prev => [...prev, { id: assistantMsgId, role: 'assistant', content: 'Choose LLM Provider:\n1. Anthropic\n2. OpenAI\n3. Gemini\nEnter number (1-3):' }])
```

- [ ] **Step 5: Manually verify**

Run the backend and CLI:
```bash
uv run uvicorn app.main:app --port 8000
```
```bash
.\kiwi
```
In the REPL: run `/login`, confirm it goes straight to `Choose LLM Provider:` (no Cognee Base URL/API Key/Tenant ID prompts), pick a provider and model, confirm `Login successful!`. Run `/config` and confirm it shows only LLM Provider/Model (no Cognee Base URL/Tenant ID lines). Exit and restart `.\kiwi`, confirm it auto-detects the prior login via `/kiwi/auth-status` without re-prompting.

Expected: 2-step login, no Cognee-credential prompts anywhere, `/config` output matches the simplified shape.

- [ ] **Step 6: Commit**

```bash
git add kiwi-ui/index.tsx
git commit -m "feat: simplify /login flow to just LLM provider/model selection"
```

---

## Task 5: `kiwi.ps1` — auto-start the Cognee container

**Files:**
- Modify: `kiwi.ps1`

**Interfaces:**
- Consumes: `docker-compose.cognee.yml` (Task 1), whichever real key is present among `ANTHROPIC_API_KEY`/`OPENAI_API_KEY`/`GEMINI_API_KEY` (read from the process environment, which already has `.env` loaded — verify this assumption in Step 2 below, since `kiwi.ps1` itself doesn't currently load `.env`; if it doesn't, `uv run uvicorn` picking up `.env` via `sentinel/config.py`'s dotenv loading is a separate, already-working mechanism inside the Python process, NOT available to the PowerShell script directly — resolve this by having the script read `.env` itself, per Step 1's code, before checking `$env:...`).

No automated tests — PowerShell script, not pytest-testable. Verify manually per Step 3.

- [ ] **Step 1: Rewrite `kiwi.ps1`**

Replace the full contents of `kiwi.ps1`:
```powershell
function Read-DotEnvValue {
    param([string]$Name)
    foreach ($candidate in @(".env.local", ".env")) {
        $path = Join-Path $PSScriptRoot $candidate
        if (Test-Path $path) {
            $line = Get-Content $path | Where-Object { $_ -match "^\s*$Name\s*=" } | Select-Object -Last 1
            if ($line) {
                return ($line -split '=', 2)[1].Trim()
            }
        }
    }
    return $null
}

$backendProcess = $null
try {
    $anthropicKey = Read-DotEnvValue "ANTHROPIC_API_KEY"
    $openaiKey = Read-DotEnvValue "OPENAI_API_KEY"
    $geminiKey = Read-DotEnvValue "GEMINI_API_KEY"

    $llmApiKey = $null
    $llmProvider = $null
    $llmModel = $null
    if ($anthropicKey -and $anthropicKey -ne "your_anthropic_key_here") {
        $llmApiKey = $anthropicKey
        $llmProvider = "anthropic"
        $llmModel = "claude-opus-4-8"
    } elseif ($openaiKey -and $openaiKey -ne "your_openai_key_here") {
        $llmApiKey = $openaiKey
        $llmProvider = "openai"
        $llmModel = "gpt-5.5"
    } elseif ($geminiKey -and $geminiKey -ne "your_gemini_key_here") {
        $llmApiKey = $geminiKey
        $llmProvider = "gemini"
        $llmModel = "gemini-3-flash-preview"
    }

    if ($llmApiKey) {
        $env:LLM_API_KEY = $llmApiKey
        $env:LLM_PROVIDER = $llmProvider
        $env:LLM_MODEL = "$llmProvider/$llmModel"
        docker compose -f (Join-Path $PSScriptRoot "docker-compose.cognee.yml") up -d | Out-Null

        $cogneeReady = $false
        for ($i = 0; $i -lt 30; $i++) {
            try {
                $resp = Invoke-WebRequest -Uri "http://localhost:8010/health" -UseBasicParsing -TimeoutSec 2 -ErrorAction Stop
                if ($resp.StatusCode -eq 200) { $cogneeReady = $true; break }
            } catch {}
            Start-Sleep -Seconds 1
        }
        if (-not $cogneeReady) {
            Write-Warning "Cognee server did not respond healthy within 30s; continuing anyway (it may still be starting up)."
        }
    } else {
        Write-Warning "No LLM API key found in .env; skipping Cognee server auto-start. Set ANTHROPIC_API_KEY, OPENAI_API_KEY, or GEMINI_API_KEY."
    }

    $outLog = Join-Path $env:TEMP "kiwi_backend_out.log"
    $errLog = Join-Path $env:TEMP "kiwi_backend_err.log"
    $backendProcess = Start-Process uv -ArgumentList "run", "uvicorn", "app.main:app", "--port", "8000" -PassThru -NoNewWindow -WorkingDirectory $PSScriptRoot -RedirectStandardOutput $outLog -RedirectStandardError $errLog
    Start-Sleep -Seconds 2
    pnpm --silent --dir kiwi-ui start
} finally {
    if ($backendProcess) {
        Stop-Process -Id $backendProcess.Id -Force -ErrorAction SilentlyContinue
    }
    Clear-Host
}
```

Note: the `/health` path used above is the design's best guess — if Task 1 Step 4 found a different actual health-check path, use that path here instead.

- [ ] **Step 2: Manually verify `.env` reading works**

Run: `powershell -NoProfile -Command ". { $ErrorActionPreference = 'Stop'; . '.\kiwi.ps1' -WhatIf }" ` is not applicable (script isn't parameterized) — instead, temporarily add a `Write-Host "Resolved provider: $llmProvider"` line after the `if ($llmApiKey)` block, run `.\kiwi`, confirm it prints the expected provider based on which key is real in your `.env`, then remove the debug line.

- [ ] **Step 3: Manually verify the full launch**

Stop any previously running Cognee container (`docker compose -f docker-compose.cognee.yml down`), then run `.\kiwi`. Expected: the script starts the Cognee container, waits for it to become healthy (or warns after 30s), starts the backend, launches the REPL. Confirm `docker compose -f docker-compose.cognee.yml ps` shows it running, and that it's still running after you `/exit` Kiwi (not stopped).

- [ ] **Step 4: Commit**

```bash
git add kiwi.ps1
git commit -m "feat: auto-start self-hosted Cognee container from the launcher"
```

---

## Task 6: `.env.example` — drop Cognee credential placeholders

**Files:**
- Modify: `.env.example`

**Interfaces:** none — plain config file edit. Does not touch the user's real `.env` (gitignored, personal, out of scope — any leftover `COGNEE_API_KEY`/`COGNEE_TENANT_ID` values there are simply unused by the code after Task 2, no harm in leaving them).

- [ ] **Step 1: Rewrite `.env.example`**

Replace the full contents of `.env.example`:
```env
# COGNEE_BASE_URL=http://localhost:8010  # optional override; defaults to this if unset
SENTINEL_DATASET=sentinel
ANTHROPIC_API_KEY=your_anthropic_key_here
GEMINI_API_KEY=your_gemini_key_here
OPENAI_API_KEY=your_openai_key_here
GITHUB_TOKEN=optional_for_pr_comments
```

- [ ] **Step 2: Commit**

```bash
git add .env.example
git commit -m "docs: drop Cognee Cloud credential placeholders from .env.example"
```

---

## Task 7: Replace the Cognee Cloud integration test

**Files:**
- Delete: `tests/test_integration_cloud.py`
- Create: `tests/test_integration_selfhosted.py`

**Interfaces:**
- Consumes: `sentinel.cognee_client.CogneeClient`, `sentinel.config.load_settings` (Task 2). Requires the `docker-compose.cognee.yml` service (Task 1) running locally at `http://localhost:8010` (or whatever `COGNEE_BASE_URL` is set to).

- [ ] **Step 1: Delete the old cloud-only integration test**

```bash
git rm tests/test_integration_cloud.py
```

- [ ] **Step 2: Write the self-hosted integration test**

`tests/test_integration_selfhosted.py`:
```python
import time

import pytest

from sentinel.cognee_client import CogneeClient
from sentinel.config import load_settings

pytestmark = pytest.mark.integration

DATASET = f"sentinel_smoke_{int(time.time())}"


def test_full_lifecycle_roundtrip():
    client = CogneeClient(load_settings())
    try:
        client.remember(
            "Test test_roundtrip failed: race condition caused duplicate charge. "
            "Fixed by adding an idempotency key.", dataset=DATASET)
        hits = client.recall("duplicate charge after concurrent retries — seen before?",
                             dataset=DATASET)
        assert hits and "idempoten" in hits[0]["text"].lower()
        qa = client.remember_entry(
            {"type": "qa", "question": "seen before?", "answer": "yes, idempotency key"},
            session_id="smoke-integration")
        fb = client.remember_entry(
            {"type": "feedback", "qa_id": qa["entry_id"],
             "feedback_text": "correct match", "feedback_score": 1},
            session_id="smoke-integration")
        assert fb["entry_id"]
    finally:
        client.forget(dataset=DATASET)
```

- [ ] **Step 3: Run it against the local container**

Ensure the Cognee container is running (`docker compose -f docker-compose.cognee.yml up -d`), then:
Run: `uv run pytest tests/test_integration_selfhosted.py -v -m integration`
Expected: PASS. If it fails, check the container is actually up (`docker compose -f docker-compose.cognee.yml ps`) and that `COGNEE_BASE_URL` (or the default `http://localhost:8010`) is reachable.

- [ ] **Step 4: Run the default suite to confirm exclusion still works**

Run: `uv run pytest tests/ app/tests/ -q`
Expected: passes, with the integration test deselected (per `pyproject.toml`'s `addopts = "-m 'not integration'"`), same as before.

- [ ] **Step 5: Commit**

```bash
git add tests/test_integration_selfhosted.py
git commit -m "test: replace Cognee Cloud integration test with self-hosted equivalent"
```

---

## Task 8: Flip docs from planned to shipped

**Files:**
- Modify: `README.md`
- Modify: `docs/commands.md`
- Modify: `docs/subsystems.md`
- Modify: `docs/exploration_guide.md`

**Interfaces:** none — doc-only changes, matching the markers added when the design was approved (`docs/superpowers/specs/2026-07-20-cognee-self-hosted-migration-design.md`).

- [ ] **Step 1: Update `README.md`**

Replace the "Roadmap: Self-Hosted Cognee *(planned)*" section:
```markdown
## Roadmap: Self-Hosted Cognee *(planned)*

Kiwi currently depends on Cognee Cloud (paid, `X-Api-Key`/`X-Tenant-Id` auth). Cognee itself is open source and self-hostable via Docker at no cost, with file-based storage (no Postgres/Neo4j required) and no auth needed for a local single-user setup like Kiwi's. This migration will fully replace Cloud, shrink `/login` from 5 steps to 2 (no more Cognee credentials to collect — just LLM provider and model), and add a `docker-compose.cognee.yml` that Kiwi's launcher starts automatically alongside the backend. See the design at [docs/superpowers/specs/2026-07-20-cognee-self-hosted-migration-design.md](docs/superpowers/specs/2026-07-20-cognee-self-hosted-migration-design.md).
```
with:
```markdown
## Self-Hosted Cognee

Kiwi runs entirely on a self-hosted, Dockerized Cognee instance (`docker-compose.cognee.yml`) instead of the paid Cognee Cloud — `kiwi.ps1` starts it automatically alongside the backend. No Cognee auth is required for this local single-user setup, so `/login` only asks for your LLM provider and model. See the design at [docs/superpowers/specs/2026-07-20-cognee-self-hosted-migration-design.md](docs/superpowers/specs/2026-07-20-cognee-self-hosted-migration-design.md).
```

Update the Commands Registry table row:
```markdown
| `/login` | Starts the step-by-step interactive credentials gate. |
```
with:
```markdown
| `/login` | Picks your LLM provider and model (Cognee itself needs no login — self-hosted, no auth). |
```

Update the Prerequisites list to add Docker:
```markdown
### 1. Prerequisites
* Python 3.12+
* Node.js & pnpm
* uv (Fast Python package manager)
```
with:
```markdown
### 1. Prerequisites
* Python 3.12+
* Node.js & pnpm
* uv (Fast Python package manager)
* Docker (for the self-hosted Cognee server)
```

Update the Configuration Setup `.env` block to match the new `.env.example`:
```markdown
### 2. Configuration Setup
Copy `.env.example` to `.env` (or `.env.local`) and fill in real values:
```env
COGNEE_BASE_URL=https://tenant-<your-tenant-id>.aws.cognee.ai
COGNEE_API_KEY=your_api_key_here
COGNEE_TENANT_ID=your-tenant-id
SENTINEL_DATASET=sentinel

# LLM Keys
ANTHROPIC_API_KEY=your_anthropic_key_here
GEMINI_API_KEY=your_gemini_key_here
OPENAI_API_KEY=your_openai_key_here
GITHUB_TOKEN=optional_for_pr_comments
```
```
with:
```markdown
### 2. Configuration Setup
Copy `.env.example` to `.env` (or `.env.local`) and fill in at least one LLM key. `kiwi.ps1` auto-starts a local self-hosted Cognee server (via `docker-compose.cognee.yml`) using whichever key you provide — no Cognee account or API key needed.
```env
# COGNEE_BASE_URL=http://localhost:8010  # optional override; defaults to this if unset
SENTINEL_DATASET=sentinel
ANTHROPIC_API_KEY=your_anthropic_key_here
GEMINI_API_KEY=your_gemini_key_here
OPENAI_API_KEY=your_openai_key_here
GITHUB_TOKEN=optional_for_pr_comments
```
```

- [ ] **Step 2: Update `docs/commands.md`**

Replace the `/login` detailed section:
```markdown
### `/login`
* **Purpose**: Authenticates the Kiwi session by configuring backend connections.
* **Function**: Initializes the credentials pipeline. If credentials exist in the root `.env` or `.env.local` file, it automatically imports them (displaying `"Cognee credentials detected from .env file!"`) and prompts you to select the LLM Provider. Otherwise, it launches an interactive walkthrough asking you to specify the Cognee Base URL, API Key, and Tenant ID.
* **Example**:
  ```text
  /login
  ```
* **Planned change**: once Kiwi migrates to self-hosted Cognee (Docker, no auth), this flow shrinks to just LLM Provider → LLM Model — there will be no Cognee credentials left to collect. See [Self-Hosted Cognee design](superpowers/specs/2026-07-20-cognee-self-hosted-migration-design.md).
```
with:
```markdown
### `/login`
* **Purpose**: Selects the active LLM provider and model for the session.
* **Function**: Prompts you to choose an LLM Provider, then a model for that provider. Cognee itself runs self-hosted with no auth, so there are no Cognee credentials to collect.
* **Example**:
  ```text
  /login
  ```
```

- [ ] **Step 3: Update `docs/subsystems.md`**

Replace the Memory Subsystem section:
```markdown
## 3. Memory Subsystem
**Location:** [sentinel/cognee_client.py](../sentinel/cognee_client.py)

Connects the agent to a Cognee graph database. Currently backed by Cognee Cloud (`X-Api-Key`/`X-Tenant-Id` auth); a migration to a self-hosted Docker instance (no auth, no cloud dependency) is planned — see [Self-Hosted Cognee design](superpowers/specs/2026-07-20-cognee-self-hosted-migration-design.md). The verified REST routes (`remember`/`recall`/`forget`) are identical between Cloud and self-hosted, so this subsystem's request logic is expected to change minimally; only the auth headers and base URL default go away.
* **Remember pipeline**: Serializes test traces, stack traces, and resolution summaries, writing them into graph databases.
* **Recall pipeline**: Uses vector search and semantic matching to find similar failure context based on test signatures.
```
with:
```markdown
## 3. Memory Subsystem
**Location:** [sentinel/cognee_client.py](../sentinel/cognee_client.py)

Connects the agent to a self-hosted Cognee graph database (`docker-compose.cognee.yml`, no auth, no cloud dependency). See [Self-Hosted Cognee design](superpowers/specs/2026-07-20-cognee-self-hosted-migration-design.md) for the migration rationale.
* **Remember pipeline**: Serializes test traces, stack traces, and resolution summaries, writing them into graph databases.
* **Recall pipeline**: Uses vector search and semantic matching to find similar failure context based on test signatures.
```

- [ ] **Step 4: Update `docs/exploration_guide.md`**

Replace the orientation-map row:
```markdown
| **Memory Client** | Client wrapper around Cognee graph database (`remember`, `recall`) — currently Cognee Cloud, migration to self-hosted Docker *(planned)* | [sentinel/cognee_client.py](../sentinel/cognee_client.py) — see [design](superpowers/specs/2026-07-20-cognee-self-hosted-migration-design.md) |
```
with:
```markdown
| **Memory Client** | Client wrapper around a self-hosted Cognee graph database (`remember`, `recall`), no auth | [sentinel/cognee_client.py](../sentinel/cognee_client.py) |
```

- [ ] **Step 5: Run the full suite once more to confirm no regressions**

Run: `uv run pytest tests/ app/tests/ -q`
Expected: all tests pass (integration test excluded by default).

- [ ] **Step 6: Commit**

```bash
git add README.md docs/commands.md docs/subsystems.md docs/exploration_guide.md
git commit -m "docs: mark the self-hosted Cognee migration as shipped"
```
