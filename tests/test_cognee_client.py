from unittest.mock import MagicMock

import pytest

from sentinel.cognee_client import CogneeClient, CogneeError
from sentinel.config import Settings

S = Settings(base_url="https://t.example", api_key="k", tenant_id="tid", dataset="sentinel")


def make_client(status=200, payload=None):
    http = MagicMock()
    resp = MagicMock()
    resp.status_code = status
    resp.json.return_value = payload if payload is not None else {}
    resp.text = "body"
    http.request.return_value = resp
    return CogneeClient(settings=S, http=http), http


def test_remember_posts_multipart_with_dataset():
    client, http = make_client(payload={"status": "completed"})
    out = client.remember("failure text", dataset="sentinel")
    assert out == {"status": "completed"}
    _, kwargs = http.request.call_args
    assert http.request.call_args[0] == ("POST", "https://t.example/api/v1/remember")
    assert kwargs["data"] == {"datasetName": "sentinel"}
    assert "data" in kwargs["files"]
    assert kwargs["headers"] == {"X-Api-Key": "k", "X-Tenant-Id": "tid"}


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
