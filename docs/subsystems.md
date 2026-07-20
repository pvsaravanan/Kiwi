# Subsystems Guide — Kiwi

This document details the major subsystems of the Kiwi QA Harness Agent.

---

## 1. CLI Surface & REPL Subsystem
**Location:** [kiwi-ui/index.tsx](../kiwi-ui/index.tsx)

An interactive React + Ink shell that runs in the terminal.
* **REPL Component**: Manages terminal output streaming, autocomplete suggestions, and history buffers.
* **Credentials Gate**: Restricts execution until settings are loaded or interactive `/login` config is completed.
* **State Store**: Uses React state hooks to coordinate login states, loader overlays, and chat history.

---

## 2. API Backend Subsystem
**Location:** [app/main.py](../app/main.py)

A FastAPI web service coordinating executions and client interactions.
* **Endpoints**:
  - `/kiwi/query`: Coordinates memory recall and system prompts.
  - `/kiwi/test`: Spawns pytest commands and captures output logs.
  - `/kiwi/login` & `/kiwi/auth-status`: Serializes dynamic session configurations.
  - `/webhook`: Connects Kiwi to external event hooks (such as GitHub Actions or pull request updates).

---

## 3. Memory Subsystem
**Location:** [sentinel/cognee_client.py](../sentinel/cognee_client.py)

Connects the agent to a Cognee graph database.
* **Remember pipeline**: Serializes test traces, stack traces, and resolution summaries, writing them into graph databases.
* **Recall pipeline**: Uses vector search and semantic matching to find similar failure context based on test signatures.

---

## 4. Review & Grounding Subsystem
**Location:** [sentinel/reviewer.py](../sentinel/reviewer.py)

Ensures generated reviews are factual and grounded.
* **get_diff()**: Queries git history for local repository code modifications.
* **ground_review()**: Validates model output using n-gram grounding checks against recalled history to prevent hallucinations.

---

## 5. Agentic QA Harness Subsystem
**Location:** [sentinel/agent/](../sentinel/agent/)

Turns Kiwi from a one-shot NL-to-single-action translator into a real multi-step tool-use loop — run a test, inspect the failure, search the codebase, edit, rerun, repeat — the way Claude Code works for coding tasks, but scoped to QA. Full design: [Agentic QA Harness design](superpowers/specs/2026-07-20-agentic-qa-harness-design.md).
* **Loop orchestrator** (`sentinel/agent/loop.py`): iterates provider tool calls until the model returns final text or a fixed iteration budget (10) is hit.
* **Tool registry** (`sentinel/agent/tools.py`): curated tools (`run_tests`, `read_file`, `search_code`, `edit_file`, `shell`, `recall`, `remember`); `edit_file` and `shell` require per-action human approval.
* **Provider adapters** (`sentinel/agent/providers/`): normalize Anthropic/OpenAI/Gemini native tool-calling into one shared interface.
* **Entry points**: dedicated `/fix [path]` command, and a new `fix` action in the `/kiwi/query` NL router so plain-English requests reach the same loop.
