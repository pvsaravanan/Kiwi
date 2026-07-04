import os
from unittest.mock import MagicMock, patch
import pytest

from sentinel.llm_client import get_llm_client, ask_llm

@patch("os.path.exists")
def test_get_llm_client_no_state_and_no_env(mock_exists):
    mock_exists.return_value = False
    with patch.dict(os.environ, {}, clear=True):
        provider, client, model = get_llm_client()
        assert provider is None
        assert client is None
        assert model is None

@patch("os.path.exists")
def test_get_llm_client_with_state(mock_exists):
    mock_exists.return_value = True
    
    with patch("builtins.open", MagicMock()):
        with patch("json.load") as mock_json_load:
            mock_json_load.return_value = {
                "is_logged_in": True,
                "llm_provider": "gemini",
                "llm_model": "gemini-3.5-flash"
            }
            with patch.dict(os.environ, {"GEMINI_API_KEY": "valid-key"}):
                with patch("google.genai.Client") as mock_client_init:
                    provider, client, model = get_llm_client()
                    assert provider == "gemini"
                    assert model == "gemini-3.5-flash"
