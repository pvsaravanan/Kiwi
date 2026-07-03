from sentinel.cognee_client import CogneeClient


def confirm(client: CogneeClient, *, test_name: str, resolution: str,
            run_id: str, dataset: str) -> str:
    """Engineer confirms 'same issue' — Cloud's improve mechanism:
    QA entry + chained feedback in an incident session, then a session-scoped
    remember that Cognee bridges into the permanent graph in the background."""
    session = f"incident-{run_id}"
    qa = client.remember_entry({
        "type": "qa",
        "question": f"Failure in {test_name}: have we seen this before, and what fixed it?",
        "answer": resolution,
    }, session_id=session)
    client.remember_entry({
        "type": "feedback",
        "qa_id": qa["entry_id"],
        "feedback_text": "Engineer confirmed: same root cause as recalled incident.",
        "feedback_score": 1,
    }, session_id=session)
    client.remember(
        f"Confirmed resolution for {test_name}: {resolution}\nStatus: CONFIRMED_RESOLVED",
        dataset=dataset, session_id=session, filename=f"confirm_{test_name}.txt",
    )
    print(f"[IMPROVE] Confirmation recorded in session '{session}' (bridging to permanent graph)")
    return session


def forget_dataset(client: CogneeClient, *, dataset: str, memory_only: bool = False) -> dict:
    out = client.forget(dataset=dataset, memory_only=memory_only)
    print(f"[FORGET] dataset='{dataset}' memory_only={memory_only}")
    return out
