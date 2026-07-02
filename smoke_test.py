"""One-shot verification that all Cognee Cloud verbs Sentinel needs work end-to-end.

Run: python smoke_test.py
Throwaway script — safe to delete after verification.
"""
import io
import json
import os
import time

import requests
from dotenv import load_dotenv

load_dotenv()

BASE = os.environ["COGNEE_BASE_URL"].rstrip("/")
HEADERS = {
    "X-Api-Key": os.environ["COGNEE_API_KEY"],
    "X-Tenant-Id": os.environ["COGNEE_TENANT_ID"],
}
DATASET = "sentinel_smoke"
SESSION = "smoke-incident-001"

FAILURE_A = (
    "Test test_webhook_retry failed in payments/webhook.py: "
    "AssertionError: expected 1 charge, found 2. Root cause: race condition in "
    "retry logic - two workers processed the same webhook concurrently. "
    "Fixed by adding an idempotency key on charge creation."
)
QUERY = "A test failed with a duplicate charge after concurrent webhook retries. Have we seen this before and what fixed it?"


def step(name, resp):
    print(f"\n=== {name}: HTTP {resp.status_code} ({resp.elapsed.total_seconds():.1f}s)")
    try:
        body = resp.json()
        print(json.dumps(body, indent=2, default=str)[:1200])
        return body
    except ValueError:
        print(resp.text[:500])
        return None


t0 = time.time()

# 1. remember() — permanent: multipart file upload, sync cognify
resp = requests.post(
    f"{BASE}/api/v1/remember",
    headers=HEADERS,
    files={"data": ("failure_a.txt", io.BytesIO(FAILURE_A.encode()), "text/plain")},
    data={"datasetName": DATASET},
    timeout=560,
)
step("remember (permanent)", resp)

# 2. recall() — semantic query, default GRAPH_COMPLETION
resp = requests.post(
    f"{BASE}/api/v1/recall",
    headers=HEADERS,
    json={"query": QUERY, "datasets": [DATASET]},
    timeout=180,
)
step("recall", resp)

# 3. remember() with session_id — session cache, background-bridged
resp = requests.post(
    f"{BASE}/api/v1/remember",
    headers=HEADERS,
    files={"data": ("confirm.txt", io.BytesIO(
        b"Engineer confirmed: this incident is the same root cause as the "
        b"March webhook race condition. Fix: idempotency key."), "text/plain")},
    data={"datasetName": DATASET, "session_id": SESSION},
    timeout=560,
)
step("remember (session)", resp)

# 4. feedback entry — the improve() signal on Cloud
resp = requests.post(
    f"{BASE}/api/v1/remember/entry",
    headers=HEADERS,
    json={
        "entry": {
            "type": "feedback",
            "feedback_text": "Recall matched the correct prior incident.",
            "feedback_score": 1,
        },
        "session_id": SESSION,
    },
    timeout=60,
)
step("remember/entry (feedback)", resp)

# 5. sessions dashboard sees the session?
resp = requests.get(f"{BASE}/api/v1/sessions", headers=HEADERS, timeout=60)
step("sessions list", resp)

# 6. quota burn for the whole exercise
resp = requests.get(f"{BASE}/api/v1/quotas/usage", headers=HEADERS, timeout=60)
step("quota usage", resp)

# 7. forget() — clean up the smoke dataset
resp = requests.post(
    f"{BASE}/api/v1/forget",
    headers=HEADERS,
    json={"dataset": DATASET},
    timeout=180,
)
step("forget", resp)

print(f"\nTotal: {time.time() - t0:.0f}s")
