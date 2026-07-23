import io

import requests

from sentinel.config import Settings, load_settings


class CogneeError(RuntimeError):
    pass


# Cognee preflights its own LLM credentials before running cognify, and retries
# *any* failure - auth, quota, rate limit - with backoff until a 30s budget runs
# out, then reports the lot as a connection timeout. Its suggested remedies are
# actively misleading: the endpoint is usually reachable and answering in well
# under a second, and skipping the check only moves the failure a few seconds
# later into cognify, which still needs real LLM calls.
_LLM_PREFLIGHT_MARKER = "LLM connection test timed out"

_LLM_PREFLIGHT_HELP = (
    "Cognee's own LLM provider did not answer within its 30s preflight budget.\n"
    "Despite the wording, this usually is NOT a network problem: Cognee retries "
    "quota and rate-limit errors with backoff until the budget expires, so an "
    "exhausted quota surfaces here as a timeout. (A plainly invalid key reports "
    "'LLM authentication failed' instead, so that is likely not the cause.)\n"
    "This is the key Cognee uses for its internal cognify pipeline "
    "(.cognee_compose.env, written by kiwi.ps1 from your .env) - not whichever "
    "provider you logged in to Kiwi with.\n"
    "Container logs only repeat this same message; to see what the provider really "
    "said, run:  uv run python scripts/diagnose_cognee_llm.py\n"
    "After fixing the key or its billing, fully restart .\\kiwi - the container "
    "bakes the key in at creation time."
)


def _explain(method: str, path: str, status: int, body: str) -> str:
    """Turn a Cognee error body into something actionable, where we can recognise it."""
    prefix = f"{method} {path} -> HTTP {status}: "
    if _LLM_PREFLIGHT_MARKER in body:
        return prefix + _LLM_PREFLIGHT_HELP
    return prefix + body[:500]


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
            raise CogneeError(_explain(method, path, resp.status_code, resp.text))
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
