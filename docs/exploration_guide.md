# Exploration Guide — Kiwi

This guide helps you navigate and study the Kiwi codebase, showing how the UI, CLI, memory client, and backend API interact.

---

## Orientation Map

| Component | Responsibility | Path |
|---|---|---|
| **CLI & REPL Surface** | Interactive terminal rendering and command parser (React + Ink) | [kiwi-ui/index.tsx](../kiwi-ui/index.tsx) |
| **Backend API** | FastAPI server hosting endpoints for queries, tests, and configuration | [app/main.py](../app/main.py) |
| **Memory Client** | Client wrapper around Cognee graph database (`remember`, `recall`) | [sentinel/cognee_client.py](../sentinel/cognee_client.py) |
| **Review Engine** | Prompt generator that builds and lints grounding reviews using LLMs | [sentinel/reviewer.py](../sentinel/reviewer.py) |
| **Dynamic Configuration**| Priority-based env loader (.env.local -> .env) and state files | [sentinel/config.py](../sentinel/config.py) |
| **Agentic QA Harness** *(planned)* | Multi-step tool-use loop (run → inspect → search → edit → rerun) for autonomously fixing failing tests | `sentinel/agent/` — see [design doc](superpowers/specs/2026-07-20-agentic-qa-harness-design.md) |

---

## Data Flow Pipeline

Trace how a user action (e.g. running a test or query) flows through Kiwi:

```
[kiwi-ui/index.tsx] (User input / command execution)
       ↓
[app/main.py] (FastAPI Endpoint Handler)
       ↓
[sentinel/cognee_client.py] (Recall historical matches / remember failures)
       ↓
[sentinel/reviewer.py] (LLM prompt synthesis & n-gram grounding validation)
       ↓
[kiwi-ui/index.tsx] (Renders final review response in Ink UI)
```

---

## Key Patterns to Recognize

### 1. Dynamic LLM Instantiation
Kiwi dynamically resolves the active provider (Anthropic, OpenAI, or Gemini) and model directly from the persistent config or `.env` files:
```python
# sentinel/llm_client.py
provider, client, model = get_llm_client()
```

### 2. Environment Priority Matching
Dot-env files are loaded in override-priority order so that local config files take precedence:
```python
# sentinel/config.py
env_files = glob.glob(".env*")
env_files.sort(key=get_priority)
for f in env_files:
    load_dotenv(f)
```

### 3. Multi-Step Agentic Loop *(planned)*
`/kiwi/query` today is one-shot: one LLM call in, one action or text reply out. The planned `/fix` agentic harness replaces that with an iterate-until-done loop — call the model with tools, execute any tool calls (with approval gates on risky ones), feed results back, repeat up to a fixed step budget. See [Agentic QA Harness design](superpowers/specs/2026-07-20-agentic-qa-harness-design.md) for the full architecture.
