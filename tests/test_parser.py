import pytest
from pathlib import Path
from sentinel.parser import parse_junit_xml, FailureRecord

FIXTURES = Path(__file__).parent / "fixtures"

def test_parses_single_failure():
    records = parse_junit_xml(str(FIXTURES / "simple_failure.xml"))
    assert len(records) == 1
    r = records[0]
    assert r.test_name == "test_webhook_retry"
    assert r.class_name == "tests.payments.test_webhook"
    assert "AssertionError" in r.error_message
    assert r.failure_type == "AssertionError"
    assert "assert response.status_code == 200" in r.stack_trace
    assert r.file_hint == "tests/payments/test_webhook"

def test_skips_passing_tests():
    records = parse_junit_xml(str(FIXTURES / "simple_failure.xml"))
    names = [r.test_name for r in records]
    assert "test_webhook_success" not in names

def test_parses_multi_suite():
    records = parse_junit_xml(str(FIXTURES / "multi_suite.xml"))
    assert len(records) == 2

def test_handles_error_element():
    records = parse_junit_xml(str(FIXTURES / "multi_suite.xml"))
    err_record = next(r for r in records if r.test_name == "test_order_create")
    assert "ConnectionError" in err_record.error_message

def test_file_hint_derived_from_classname():
    records = parse_junit_xml(str(FIXTURES / "multi_suite.xml"))
    login = next(r for r in records if r.test_name == "test_login_timeout")
    assert login.file_hint == "tests/auth/test_login"

def test_failure_record_optional_fields_default_none():
    records = parse_junit_xml(str(FIXTURES / "simple_failure.xml"))
    r = records[0]
    assert r.run_id is None
    assert r.timestamp is None
