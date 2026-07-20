import os
from unittest.mock import MagicMock, patch
import pytest

from sentinel.llm_client import ask_llm, get_llm_client, stream_llm, validate_llm_credentials

@patch("sentinel.session_state.load_state")
def test_get_llm_client_no_state_and_no_env(mock_load_state):
    mock_load_state.return_value = {}
    with patch.dict(os.environ, {}, clear=True):
        provider, client, model = get_llm_client()
        assert provider is None
        assert client is None
        assert model is None

@patch("sentinel.session_state.load_state")
def test_get_llm_client_with_state(mock_load_state):
    mock_load_state.return_value = {
        "is_logged_in": True,
        "llm_provider": "gemini",
        "llm_model": "gemini-3.5-flash"
    }
    with patch.dict(os.environ, {"GEMINI_API_KEY": "valid-key"}):
        with patch("google.genai.Client") as mock_client_init:
            provider, client, model = get_llm_client()
            assert provider == "gemini"
            assert model == "gemini-3.5-flash"


@patch("sentinel.llm_client.get_llm_client")
def test_validate_llm_credentials_success(mock_get_client):
    mock_llm_client = MagicMock()
    mock_get_client.return_value = ("gemini", mock_llm_client, "gemini-3.5-flash")
    
    from sentinel.llm_client import validate_llm_credentials
    valid, err = validate_llm_credentials("gemini", "gemini-3.5-flash")
    assert valid is True
    assert err == ""
    mock_llm_client.models.generate_content.assert_called_once()


@patch("sentinel.llm_client.get_llm_client")
def test_validate_llm_credentials_failure(mock_get_client):
    mock_llm_client = MagicMock()
    mock_llm_client.models.generate_content.side_effect = RuntimeError("API key invalid")
    mock_get_client.return_value = ("gemini", mock_llm_client, "gemini-3.5-flash")
    
    from sentinel.llm_client import validate_llm_credentials
    valid, err = validate_llm_credentials("gemini", "gemini-3.5-flash")
    assert valid is False
    assert "API key invalid" in err


def test_ask_llm_openai_uses_max_completion_tokens_not_max_tokens():
    client = MagicMock()
    client.chat.completions.create.return_value.choices = [
        MagicMock(message=MagicMock(content="hi"))
    ]

    ask_llm("openai", client, "hello", model="gpt-5.4-mini")

    kwargs = client.chat.completions.create.call_args.kwargs
    assert "max_tokens" not in kwargs
    assert kwargs["max_completion_tokens"] == 1024


def test_stream_llm_openai_uses_max_completion_tokens_not_max_tokens():
    client = MagicMock()
    client.chat.completions.create.return_value = []

    list(stream_llm("openai", client, "hello", model="gpt-5.4-mini"))

    kwargs = client.chat.completions.create.call_args.kwargs
    assert "max_tokens" not in kwargs
    assert kwargs["max_completion_tokens"] == 1024


@patch("sentinel.llm_client.get_llm_client")
def test_validate_llm_credentials_openai_uses_max_completion_tokens(mock_get_client):
    mock_llm_client = MagicMock()
    mock_get_client.return_value = ("openai", mock_llm_client, "gpt-5.4-mini")

    valid, err = validate_llm_credentials("openai", "gpt-5.4-mini")

    assert valid is True
    assert err == ""
    kwargs = mock_llm_client.chat.completions.create.call_args.kwargs
    assert "max_tokens" not in kwargs
    assert kwargs["max_completion_tokens"] == 5
