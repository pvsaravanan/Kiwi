import os
import threading
import time


class ChargeStore:
    """In-memory charge ledger keyed by webhook event id."""

    def __init__(self) -> None:
        self._charges: list[dict] = []
        self._lock = threading.Lock()

    def add_charge(self, event_id: str, amount_cents: int) -> None:
        with self._lock:
            self._charges.append({"event_id": event_id, "amount_cents": amount_cents})

    def add_charge_idempotent(self, event_id: str, amount_cents: int) -> None:
        # the fix: check-and-insert under one lock, keyed by event id
        with self._lock:
            if any(c["event_id"] == event_id for c in self._charges):
                return
            self._charges.append({"event_id": event_id, "amount_cents": amount_cents})

    def charges_for(self, event_id: str) -> list[dict]:
        with self._lock:
            return [c for c in self._charges if c["event_id"] == event_id]


def _charge(store: ChargeStore, event_id: str, amount_cents: int) -> None:
    time.sleep(0.02)  # simulated gateway latency
    if os.getenv("FLAKY_MODE") == "1":
        store.add_charge(event_id, amount_cents)  # pre-fix path: no idempotency key
    else:
        store.add_charge_idempotent(event_id, amount_cents)


def process_webhook(store: ChargeStore, event: dict) -> None:
    """Charge for a webhook event.

    A gateway timeout makes the provider redeliver, so a retry worker races the
    original attempt. FLAKY_MODE=1 reinstates the pre-fix code path (no
    idempotency key) so the race reproducibly double-charges.
    """
    attempt = threading.Thread(target=_charge, args=(store, event["id"], event["amount_cents"]))
    retry = threading.Thread(target=_charge, args=(store, event["id"], event["amount_cents"]))
    attempt.start()
    retry.start()
    attempt.join()
    retry.join()
