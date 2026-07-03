from dataclasses import dataclass

from sentinel.adapters.junit import FailureRecord, parse_junit_xml
from sentinel.cognee_client import CogneeClient, CogneeError
from sentinel.config import load_settings


@dataclass
class IngestResult:
    failure: FailureRecord
    matched: bool
    history: str | None


def build_query(f: FailureRecord) -> str:
    # raw error text, no normalization — Cognee's hybrid search does the semantic work
    return (
        f"A test failed with: {f.error_message}\n"
        f"Test: {f.test_name} in {f.file_hint}\n"
        "Have we seen a similar failure before, and what fixed it?"
    )


def format_failure(f: FailureRecord) -> str:
    return (
        "Test Failure:\n"
        f"Test: {f.test_name}\n"
        f"Class: {f.class_name}\n"
        f"File: {f.file_hint}\n"
        f"Error Type: {f.failure_type}\n"
        f"Error Message: {f.error_message}\n"
        f"Stack Trace:\n{f.stack_trace}\n"
        f"Run ID: {f.run_id or 'unknown'}\n"
    )


def process_report(xml_path: str, *, run_id: str | None = None,
                   client: CogneeClient | None = None,
                   dataset: str | None = None) -> list[IngestResult]:
    client = client or CogneeClient()
    dataset = dataset or load_settings().dataset
    results = []
    for failure in parse_junit_xml(xml_path):
        failure.run_id = run_id
        print(f"\n[SENTINEL] {failure.test_name}")
        matched, history = False, None
        try:
            hits = client.recall(build_query(failure), dataset=dataset)
            if hits:
                matched, history = True, hits[0].get("text")
                print(f"[RECALL] Prior history found:\n{history}")
            else:
                print("[RECALL] New failure — no history found.")
            client.remember(format_failure(failure), dataset=dataset,
                            filename=f"{failure.test_name}.txt")
            print(f"[REMEMBER] Stored in '{dataset}'")
        except CogneeError as exc:
            print(f"[WARNING] Cognee unavailable, continuing without memory: {exc}")
        results.append(IngestResult(failure=failure, matched=matched, history=history))
    return results
