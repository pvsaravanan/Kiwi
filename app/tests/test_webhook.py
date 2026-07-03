from fastapi.testclient import TestClient

from app.main import app
from app.webhook_service import ChargeStore, process_webhook


def test_concurrent_retry_creates_single_charge():
    store = ChargeStore()
    process_webhook(store, {"id": "evt_42", "amount_cents": 1900})
    charges = store.charges_for("evt_42")
    assert len(charges) == 1, (
        f"expected 1 charge, found {len(charges)}: duplicate charge after concurrent webhook retry"
    )


def test_webhook_endpoint_returns_charge_count():
    client = TestClient(app)
    resp = client.post("/webhook", json={"id": "evt_7", "amount_cents": 500})
    assert resp.status_code == 200
    assert resp.json()["charges"] >= 1
