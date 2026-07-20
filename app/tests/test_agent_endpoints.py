import json
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient

from app.main import app
from sentinel.agent.types import AgentResponse


def test_agent_start_streams_thinking_and_loop_done_for_a_trivial_goal():
    fake_settings = MagicMock(dataset="sentinel", base_url="https://t", api_key="k", tenant_id="tid")
    with patch("app.main.load_settings", return_value=fake_settings), \
         patch("app.main.CogneeClient"), \
         patch("app.main.get_llm_client", return_value=("anthropic", MagicMock(), "claude-opus-4-8")), \
         patch("app.main.build_adapter") as mock_build_adapter:
        mock_build_adapter.return_value.converse.return_value = AgentResponse(text="Nothing to fix.")

        client = TestClient(app)
        with client.stream("POST", "/kiwi/agent/start", json={"goal": "check the repo"}) as resp:
            lines = [json.loads(line) for line in resp.iter_lines() if line]

    types_seen = [line["type"] for line in lines]
    assert "loop_start" in types_seen
    assert "thinking" in types_seen
    assert types_seen[-1] == "loop_done"
    assert lines[-1]["success"] is True


def test_agent_start_streams_error_event_when_worker_raises():
    fake_settings = MagicMock(dataset="sentinel", base_url="https://t", api_key="k", tenant_id="tid")
    with patch("app.main.load_settings", return_value=fake_settings), \
         patch("app.main.CogneeClient"), \
         patch("app.main.get_llm_client", return_value=("anthropic", MagicMock(), "claude-opus-4-8")), \
         patch("app.main.build_adapter") as mock_build_adapter:
        mock_build_adapter.return_value.converse.side_effect = RuntimeError("provider blew up")

        client = TestClient(app)
        with client.stream("POST", "/kiwi/agent/start", json={"goal": "check the repo"}) as resp:
            lines = [json.loads(line) for line in resp.iter_lines() if line]

    types_seen = [line["type"] for line in lines]
    assert "error" in types_seen
    error_line = next(line for line in lines if line["type"] == "error")
    assert "provider blew up" in error_line["message"]
    # The stream must end (no hang) after the error is reported -- no loop_done follows.
    assert types_seen[-1] == "error"


def test_agent_start_returns_400_when_no_llm_configured():
    fake_settings = MagicMock(dataset="sentinel")
    with patch("app.main.load_settings", return_value=fake_settings), \
         patch("app.main.CogneeClient"), \
         patch("app.main.get_llm_client", return_value=(None, None, None)):
        client = TestClient(app)
        resp = client.post("/kiwi/agent/start", json={"goal": "check the repo"})

    assert resp.status_code == 400


def test_agent_approve_returns_404_for_unknown_loop():
    client = TestClient(app)
    resp = client.post("/kiwi/agent/approve", json={"loop_id": "nope", "tool_call_id": "c1", "decision": "allow"})
    assert resp.status_code == 404
