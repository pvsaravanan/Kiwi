from unittest.mock import MagicMock, patch
import pytest

from sentinel.config import Settings
from sentinel.kiwi_cli import run_session


@pytest.fixture
def mock_client():
    return MagicMock()


@pytest.fixture
def mock_settings():
    return Settings(
        base_url="https://test.cognee.ai",
        api_key="test-key",
        tenant_id="test-tenant",
        dataset="kiwi-test"
    )


def test_kiwi_exit(mock_client, mock_settings):
    inputs = ["/exit"]
    def mock_input(prompt):
        return inputs.pop(0)

    run_session(mock_client, mock_settings, input_func=mock_input)
    mock_client.remember.assert_not_called()


def test_kiwi_remember(mock_client, mock_settings):
    inputs = ["/remember test fact", "/exit"]
    def mock_input(prompt):
        return inputs.pop(0)

    run_session(mock_client, mock_settings, input_func=mock_input)
    mock_client.remember.assert_called_once_with("test fact", dataset="kiwi-test")


def test_kiwi_recall(mock_client, mock_settings):
    inputs = ["/recall test query", "/exit"]
    def mock_input(prompt):
        return inputs.pop(0)

    mock_client.recall.return_value = [{"text": "Found incident details"}]
    run_session(mock_client, mock_settings, input_func=mock_input)
    mock_client.recall.assert_any_call("test query", dataset="kiwi-test")


def test_kiwi_forget(mock_client, mock_settings):
    inputs = ["/forget", "/exit"]
    def mock_input(prompt):
        return inputs.pop(0)

    run_session(mock_client, mock_settings, input_func=mock_input)
    mock_client.forget.assert_called_once_with(dataset="kiwi-test")


@patch("sentinel.kiwi_cli.get_llm_client")
@patch("sentinel.kiwi_cli.ask_llm")
def test_kiwi_chat_query(mock_ask_llm, mock_get_llm, mock_client, mock_settings):
    inputs = ["Does the API charge twice?", "/exit"]
    def mock_input(prompt):
        return inputs.pop(0)

    mock_client.recall.return_value = [{"text": "observed customer billed twice"}]
    mock_get_llm.return_value = ("gemini", MagicMock(), "gemini-3.5-flash")
    mock_ask_llm.return_value = "Yes, due to retries."

    run_session(mock_client, mock_settings, input_func=mock_input)
    
    mock_client.recall.assert_any_call("Does the API charge twice?", dataset="kiwi-test")
    mock_ask_llm.assert_called_once()
    assert "observed customer billed twice" in mock_ask_llm.call_args[0][2]
    assert mock_ask_llm.call_args[1].get("model") == "gemini-3.5-flash"


@patch("sentinel.kiwi_cli.load_settings")
@patch("sentinel.kiwi_cli.run_session")
@patch("sentinel.kiwi_cli.CogneeClient")
@patch("sentinel.setup_wizard.run_setup_wizard")
def test_kiwi_cli_main_fallback_to_wizard(mock_run_setup_wizard, mock_cognee_client, mock_run_session, mock_load_settings):
    mock_load_settings.side_effect = RuntimeError("Missing env var")
    mock_run_setup_wizard.return_value = Settings(
        base_url="https://wizard.cognee.ai",
        api_key="wizard-key",
        tenant_id="wizard-tenant",
        dataset="wizard-dataset"
    )
    
    from sentinel.kiwi_cli import main
    main()
    
    mock_run_setup_wizard.assert_called_once()
    mock_cognee_client.assert_called_once()
    mock_run_session.assert_called_once()

