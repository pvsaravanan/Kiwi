import json
from pathlib import Path

from sentinel.cognee_client import CogneeClient


def format_record(r: dict) -> str:
    return (
        "Historical Test Failure:\n"
        f"Test: {r['test_name']}\n"
        f"File: {r['file']}\n"
        f"Error Type: {r.get('error_type', 'Unknown')}\n"
        f"Error: {r['error']}\n"
        f"Stack Trace:\n{r.get('stack_trace', 'N/A')}\n"
        f"Date: {r['timestamp']}\n"
        f"Resolution: {r['resolution']}\n"
    )


def load_seed_data(client: CogneeClient, *, dataset: str,
                   path: str = "sentinel/seed_data.jsonl") -> int:
    records = [json.loads(line) for line in Path(path).read_text(encoding="utf-8").splitlines()
               if line.strip()]
    combined = "\n\n---\n\n".join(format_record(r) for r in records)
    # single batched call — per PRD 13a, don't cognify row-by-row
    client.remember(combined, dataset=dataset, filename="seed_history.txt")
    print(f"[SEED] Loaded {len(records)} historical failures into '{dataset}'")
    return len(records)
