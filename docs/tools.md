# Tools Reference — Kiwi

This document describes the core execution tools integrated into the Kiwi QA Harness Agent.

---

## 1. Pytest Executable Tool
**Location:** [sentinel/llm_client.py](../sentinel/llm_client.py) & [app/main.py](../app/main.py)

Runs local test suites, monitors outcomes, and captures outputs.
* **Execution**: Invokes `pytest` in a subprocess with JUnit XML serialization flags (`--junitxml=junit_report.xml`).
* **Input Parameters**: Optionally accepts a specific test target path (e.g. `tests/test_service.py`).
* **State Updates**: Increments flaky-test failure trackers on test crashes.

---

## 2. Cognee Storage Client Tool
**Location:** [sentinel/cognee_client.py](../sentinel/cognee_client.py)

Exposes memory graph creation, indexing, and vector similarity querying to the agent loop.
* **remember(text)**: Stores incident stack traces or resolution summaries.
* **recall(query)**: Searches the graph using semantic matches to retrieve historical incident records.

---

## 3. review_builder Tool
**Location:** [sentinel/reviewer.py](../sentinel/reviewer.py)

Compiles code changes, failure logs, and historical resolutions, sending them to dynamic model endpoints (Claude, GPT, or Gemini) to build anchored feedback.
* **Input**: triggers on JUnit XML generation after test crashes.
* **Grounding Validation**: Filters output using sentence n-gram verification against recalled incident logs to prevent AI hallucination.

---

## 4. Agentic Tool Registry
**Location:** [sentinel/agent/tools.py](../sentinel/agent/tools.py)

The tool set exposed to the model inside the multi-step `/fix` agentic loop (see [Agentic QA Harness design](superpowers/specs/2026-07-20-agentic-qa-harness-design.md)):
* **run_tests(path?)**: auto-approved; wraps the existing Pytest Executable Tool and Cognee ingest path, returns a structured pass/fail summary.
* **read_file / search_code**: auto-approved, read-only, sandboxed to the repo root.
* **edit_file(path, old_string, new_string)**: requires human approval; exact-match replace, returns a diff.
* **shell(command)**: requires human approval; generic escape hatch with a timeout and truncated output.
* **recall / remember**: auto-approved wrappers over the Cognee Storage Client Tool for mid-loop memory queries.
