from fastapi import FastAPI

from app.webhook_service import ChargeStore, process_webhook

app = FastAPI(title="Demo payments service")
store = ChargeStore()


@app.post("/webhook")
def receive_webhook(event: dict):
    process_webhook(store, event)
    return {"event_id": event["id"], "charges": len(store.charges_for(event["id"]))}
