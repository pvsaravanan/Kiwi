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
