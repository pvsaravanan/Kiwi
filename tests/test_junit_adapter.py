from pathlib import Path

import pytest

from sentinel.adapters.junit import AdapterError, FailureRecord, parse_junit_xml

FIXTURES = Path(__file__).parent / "fixtures"


def test_parses_single_failure():
    records = parse_junit_xml(str(FIXTURES / "simple_failure.xml"))
    assert len(records) == 1
    r = records[0]
    assert r.test_name == "test_concurrent_retry_creates_single_charge"
    assert r.failure_type == "AssertionError"
    assert "duplicate charge" in r.error_message
    assert "assert len(charges) == 1" in r.stack_trace
    assert r.file_hint == "app/tests/test_webhook"


def test_skips_passing_tests():
    names = [r.test_name for r in parse_junit_xml(str(FIXTURES / "simple_failure.xml"))]
    assert "test_webhook_endpoint_returns_charge_count" not in names


def test_parses_multi_suite_including_error_element():
    records = parse_junit_xml(str(FIXTURES / "multi_suite.xml"))
    assert len(records) == 2
    err = next(r for r in records if r.test_name == "test_order_create")
    assert "ConnectionError" in err.error_message


def test_optional_fields_default_none():
    r = parse_junit_xml(str(FIXTURES / "simple_failure.xml"))[0]
    assert r.run_id is None and r.timestamp is None


def test_malformed_xml_raises_adapter_error(tmp_path):
    bad = tmp_path / "bad.xml"
    bad.write_text("<not-closed>")
    with pytest.raises(AdapterError):
        parse_junit_xml(str(bad))
