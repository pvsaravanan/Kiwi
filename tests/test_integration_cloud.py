import time

import pytest

from sentinel.cognee_client import CogneeClient

pytestmark = pytest.mark.integration

# Unique name per run: Cognee Cloud 500s when deleting a dataset whose name was
# previously deleted and re-created (verified 2026-07-03), so cleanup must
# always be the first-ever delete of the name.
DATASET = f"sentinel_smoke_{int(time.time())}"


def test_full_lifecycle_roundtrip():
    client = CogneeClient()
    try:
        client.remember(
            "Test test_roundtrip failed: race condition caused duplicate charge. "
            "Fixed by adding an idempotency key.", dataset=DATASET)
        hits = client.recall("duplicate charge after concurrent retries — seen before?",
                             dataset=DATASET)
        assert hits and "idempoten" in hits[0]["text"].lower()
        qa = client.remember_entry(
            {"type": "qa", "question": "seen before?", "answer": "yes, idempotency key"},
            session_id="smoke-integration")
        fb = client.remember_entry(
            {"type": "feedback", "qa_id": qa["entry_id"],
             "feedback_text": "correct match", "feedback_score": 1},
            session_id="smoke-integration")
        assert fb["entry_id"]
    finally:
        client.forget(dataset=DATASET)
