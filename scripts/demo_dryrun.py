"""Rehearse the full demo sequence end-to-end. Run: uv run python scripts/demo_dryrun.py"""
import os
import subprocess
import sys

def _already_seeded() -> bool:
    from sentinel.cognee_client import CogneeClient
    client = CogneeClient()
    return any(d.get("name") == client.settings.dataset for d in client.datasets())


STEPS = [
    ("Seed history (skip if already seeded)", ["uv", "run", "sentinel", "seed"]),
    ("Trigger the engineered flake", None),  # handled inline below (needs env var)
    ("Ingest + review", ["uv", "run", "sentinel", "ingest", "test-results.xml",
                         "--run-id", "demo-1", "--review"]),
    ("Confirm same issue (improve)", ["uv", "run", "sentinel", "confirm",
        "test_concurrent_retry_creates_single_charge",
        "Added idempotency key on charge creation", "--run-id", "demo-1"]),
]

for title, cmd in STEPS:
    print(f"\n{'=' * 60}\n{title}\n{'=' * 60}")
    if title.startswith("Seed") and _already_seeded():
        print("Dataset already exists — skipping seed.")
        continue
    if cmd is None:
        env = os.environ | {"FLAKY_MODE": "1"}
        subprocess.run(["uv", "run", "pytest", "app/tests", "-v",
                        "--junitxml=test-results.xml"], env=env)
        continue
    result = subprocess.run(cmd)
    if result.returncode != 0:
        sys.exit(f"Step failed: {title}")

print("\nDry run complete. Check the Cognee dashboard: Sessions -> incident-demo-1, "
      "Brain/Mindmap for the graph. Cleanup: uv run sentinel forget --dataset sentinel --memory-only")
