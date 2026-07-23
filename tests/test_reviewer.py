from unittest.mock import MagicMock, patch

import anthropic

from sentinel.adapters.junit import FailureRecord
from sentinel.ingest import IngestResult
from sentinel.reviewer import build_review, fallback_review, ground_review, post_pr_comment

FAILURE = FailureRecord(
    test_name="test_x", class_name="c", error_message="AssertionError: expected 1 charge, found 2",
    stack_trace="tb", failure_type="AssertionError", file_hint="app/tests/test_webhook",
)
HISTORY = ("The test_payment_processed_once failure was previously observed: customer "
           "billed twice after gateway retry. Fixed by adding an idempotency key on charge creation.")


def test_ground_review_keeps_grounded_history_sentence():
    draft = ("This matches a prior incident: customer billed twice after gateway retry. "
             "Recommend applying the same fix.")
    assert "billed twice after gateway retry" in ground_review(draft, HISTORY)


def test_ground_review_drops_ungrounded_history_claims():
    draft = ("A previous incident on March 3rd was caused by DNS failures in the ingress layer. "
             "The failing assertion is in the webhook test.")
    out = ground_review(draft, HISTORY)
    assert "DNS failures" not in out
    assert "failing assertion" in out  # non-history sentence kept


def test_ground_review_passthrough_when_no_history():
    assert ground_review("Anything at all.", None) == "Anything at all."


def test_fallback_review_no_match_is_honest():
    r = IngestResult(failure=FAILURE, matched=False, history=None)
    out = fallback_review(r)
    assert "no prior" in out.lower()
    assert "test_x" in out


def test_fallback_review_with_match_quotes_history():
    r = IngestResult(failure=FAILURE, matched=True, history=HISTORY)
    assert "idempotency key" in fallback_review(r)


def test_build_review_uses_fallback_without_api_key(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    r = IngestResult(failure=FAILURE, matched=True, history=HISTORY)
    assert "idempotency key" in build_review(r)


def test_build_review_calls_claude_and_grounds(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    block = MagicMock(type="text", text="Matches prior incident: customer billed twice after gateway retry.")
    msg = MagicMock(content=[block])
    with patch("sentinel.reviewer.anthropic") as mock_anthropic:
        mock_anthropic.Anthropic.return_value.messages.create.return_value = msg
        r = IngestResult(failure=FAILURE, matched=True, history=HISTORY)
        out = build_review(r, diff="diff --git a/x b/x")
        kwargs = mock_anthropic.Anthropic.return_value.messages.create.call_args.kwargs
        assert kwargs["model"] == "claude-opus-4-8"
        assert "billed twice" in out


def test_post_pr_comment_hits_github_api():
    http = MagicMock()
    http.post.return_value = MagicMock(status_code=201)
    post_pr_comment("hello", repo="o/r", pr_number=7, token="t", http=http)
    url = http.post.call_args[0][0]
    assert url == "https://api.github.com/repos/o/r/issues/7/comments"
    assert http.post.call_args.kwargs["json"] == {"body": "hello"}
    assert "Bearer t" in http.post.call_args.kwargs["headers"]["Authorization"]


def test_build_review_calls_gemini_and_grounds(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setenv("GEMINI_API_KEY", "test-gemini-key")
    response_mock = MagicMock()
    response_mock.text = "Matches prior incident: customer billed twice after gateway retry."
    
    with patch("sentinel.reviewer.genai") as mock_genai:
        mock_genai.Client.return_value.models.generate_content.return_value = response_mock
        r = IngestResult(failure=FAILURE, matched=True, history=HISTORY)
        out = build_review(r, diff="diff --git a/x b/x")
        
        mock_genai.Client.assert_called_once()
        generate_kwargs = mock_genai.Client.return_value.models.generate_content.call_args.kwargs
        assert generate_kwargs["model"] == "gemini-3.6-flash"
        assert "billed twice" in out


def test_build_review_does_not_fallback_to_gemini_when_claude_fails(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-claude-key")
    monkeypatch.setenv("GEMINI_API_KEY", "test-gemini-key")
    
    with patch("sentinel.reviewer.anthropic.Anthropic") as mock_anthropic_class, patch("sentinel.reviewer.genai") as mock_genai:
        mock_anthropic_class.return_value.messages.create.side_effect = anthropic.APIError("Claude failed", request=MagicMock(), body={})
        
        r = IngestResult(failure=FAILURE, matched=True, history=HISTORY)
        out = build_review(r, diff="diff --git a/x b/x")
        
        mock_anthropic_class.return_value.messages.create.assert_called_once()
        mock_genai.Client.assert_not_called()
        assert "idempotency key" in out  # falls back to fallback_review


