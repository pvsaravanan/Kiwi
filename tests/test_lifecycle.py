from unittest.mock import MagicMock

from sentinel.lifecycle import confirm, forget_dataset


def test_confirm_chains_qa_then_feedback_then_session_remember():
    client = MagicMock()
    client.remember_entry.side_effect = [{"entry_id": "qa-1"}, {"entry_id": "qa-1"}]
    session = confirm(client, test_name="test_x", resolution="added idempotency key",
                      run_id="run-9", dataset="sentinel")
    assert session == "incident-run-9"
    first, second = client.remember_entry.call_args_list
    assert first.args[0]["type"] == "qa"
    assert first.kwargs["session_id"] == "incident-run-9"
    assert second.args[0] == {
        "type": "feedback", "qa_id": "qa-1",
        "feedback_text": "Engineer confirmed: same root cause as recalled incident.",
        "feedback_score": 1,
    }
    client.remember.assert_called_once()
    assert client.remember.call_args.kwargs["session_id"] == "incident-run-9"
    assert "added idempotency key" in client.remember.call_args[0][0]


def test_forget_dataset_delegates():
    client = MagicMock()
    forget_dataset(client, dataset="sentinel_smoke", memory_only=True)
    client.forget.assert_called_once_with(dataset="sentinel_smoke", memory_only=True)
