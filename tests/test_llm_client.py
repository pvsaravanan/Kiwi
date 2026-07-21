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
    mock_llm_client.models.get.assert_called_once()


@patch("sentinel.llm_client.get_llm_client")
def test_validate_llm_credentials_failure(mock_get_client):
    mock_llm_client = MagicMock()
    mock_llm_client.models.get.side_effect = RuntimeError("API key invalid")
    mock_get_client.return_value = ("gemini", mock_llm_client, "gemini-3.5-flash")

    from sentinel.llm_client import validate_llm_credentials
    valid, err = validate_llm_credentials("gemini", "gemini-3.5-flash")
    assert valid is False
    assert "API key invalid" in err


# Validation must never issue a *generation* request: on reasoning models a
# generation round trip costs many seconds (measured ~12s at login), while a
# models-metadata lookup validates the same credentials in well under a second.
@pytest.mark.parametrize(
    "provider,model,metadata_call,generation_attr",
    [
        ("anthropic", "claude-opus-4-8", "models.retrieve", "messages.create"),
        ("gemini", "gemini-3-flash-preview", "models.get", "models.generate_content"),
        ("openai", "gpt-5.5", "models.retrieve", "chat.completions.create"),
    ],
)
@patch("sentinel.llm_client.get_llm_client")
def test_validate_llm_credentials_uses_metadata_not_generation(
    mock_get_client, provider, model, metadata_call, generation_attr
):
    mock_llm_client = MagicMock()
    mock_get_client.return_value = (provider, mock_llm_client, model)

    valid, err = validate_llm_credentials(provider, model)

    assert valid is True
    assert err == ""

    metadata_mock = mock_llm_client
    for part in metadata_call.split("."):
        metadata_mock = getattr(metadata_mock, part)
    metadata_mock.assert_called_once()

    generation_mock = mock_llm_client
    for part in generation_attr.split("."):
        generation_mock = getattr(generation_mock, part)
    generation_mock.assert_not_called()


@patch("sentinel.llm_client.get_llm_client")
def test_validate_llm_credentials_no_client_does_not_crash_on_none_provider(mock_get_client):
    mock_get_client.return_value = (None, None, None)

    valid, err = validate_llm_credentials(None, None)

    assert valid is False
    assert err


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
def test_validate_llm_credentials_openai_checks_the_requested_model(mock_get_client):
    mock_llm_client = MagicMock()
    mock_get_client.return_value = ("openai", mock_llm_client, "gpt-5.4-mini")

    valid, err = validate_llm_credentials("openai", "gpt-5.4-mini")

    assert valid is True
    assert err == ""
    mock_llm_client.models.retrieve.assert_called_once_with("gpt-5.4-mini")
