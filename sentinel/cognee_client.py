import io

import requests

from sentinel.config import Settings, auth_headers, load_settings


class CogneeError(RuntimeError):
    pass


class CogneeClient:
    """Thin wrapper over the Cognee Cloud REST API (verified against the live tenant)."""

    def __init__(self, settings: Settings | None = None, http=None):
        self.settings = settings or load_settings()
        self.http = http or requests.Session()

    def _request(self, method: str, path: str, *, timeout: int = 180, **kwargs):
        url = f"{self.settings.base_url}{path}"
        headers = auth_headers(self.settings)
        resp = self.http.request(method, url, headers=headers, timeout=timeout, **kwargs)
        if resp.status_code >= 500:  # one retry on transient server errors
            resp = self.http.request(method, url, headers=headers, timeout=timeout, **kwargs)
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
