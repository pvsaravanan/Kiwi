from pathlib import Path
from unittest.mock import MagicMock

from sentinel.adapters.junit import FailureRecord
from sentinel.cognee_client import CogneeError
from sentinel.ingest import IngestResult, build_query, format_failure, process_report

FIXTURES = Path(__file__).parent / "fixtures"

SAMPLE = FailureRecord(
    test_name="test_concurrent_retry_creates_single_charge",
    class_name="app.tests.test_webhook",
    error_message="AssertionError: expected 1 charge, found 2",
    stack_trace="trace",
    failure_type="AssertionError",
    file_hint="app/tests/test_webhook",
)


def test_build_query_uses_raw_error_text_and_file():
    q = build_query(SAMPLE)
    assert "expected 1 charge, found 2" in q
    assert "app/tests/test_webhook" in q


def test_format_failure_includes_core_fields():
    text = format_failure(SAMPLE)
    for needle in ("test_concurrent_retry_creates_single_charge", "AssertionError", "trace"):
        assert needle in text


def test_process_report_recalls_before_remember():
    client = MagicMock()
    client.recall.return_value = [{"text": "matched prior incident: idempotency key"}]
    results = process_report(str(FIXTURES / "simple_failure.xml"),
                             run_id="run-1", client=client, dataset="sentinel")
    assert len(results) == 1
    assert results[0].matched is True
    assert "idempotency" in results[0].history
    assert results[0].failure.run_id == "run-1"
    # recall must be called before remember
    call_order = [c[0] for c in client.method_calls]
    assert call_order.index("recall") < call_order.index("remember")


def test_process_report_no_match():
    client = MagicMock()
    client.recall.return_value = []
    results = process_report(str(FIXTURES / "simple_failure.xml"),
                             client=client, dataset="sentinel")
    assert results[0].matched is False and results[0].history is None


def test_cognee_error_fails_soft(capsys):
    client = MagicMock()
    client.recall.side_effect = CogneeError("boom")
    results = process_report(str(FIXTURES / "simple_failure.xml"),
                             client=client, dataset="sentinel")
    assert results[0].matched is False
    assert "warning" in capsys.readouterr().out.lower()
