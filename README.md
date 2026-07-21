# Kiwi - QA Harness Agent

Kiwi is a terminal-native, intelligent QA assistant designed to integrate graph-based memory retrieval (powered by Cognee) with local test executions (via pytest).

---

## Key Features

* **Terminal-Native REPL**: A reactive CLI surface built with React + Ink, offering autocomplete suggestions and instant command execution.
* **Graph-Based Memory**: Uses Cognee to index incident logs, stack traces, and resolution summaries, dynamically recalling them during test failures.
* **Dynamic Credentials Gate**: Keeps API credentials secure and overrides them step-by-step or automatically using .env priority lookups (.env.local -> .env).
* **Multi-Provider LLM Integration**: Dynamically switches LLM providers (Anthropic, Gemini, OpenAI) and active model configurations at runtime.
* **Factual Reviews**: Generates test reviews grounded in historical failure records, validated via sentence n-gram verification to eliminate hallucinations.

---

## System Architecture

Kiwi uses a layered architecture separating entry surfaces, agent reasoning, memory matching, and subprocess environments.

### Component Architecture

```mermaid
graph TD
    UI[Ink UI Surface] <--> API[FastAPI Backend]
    API <--> Memory[Cognee Graph Memory]
    API <--> Reviewer[Reviewer Engine]
    Reviewer <--> LLM[LLM API Gateways]
```

### Turn Execution Sequence Diagram

```mermaid
sequenceDiagram
    actor User
    participant CLI as Ink CLI REPL
    participant Srv as FastAPI Backend
    participant DB as Cognee Graph Memory
    participant AI as Reviewer Engine

    User->>CLI: run /test
    CLI->>Srv: POST /kiwi/test
    Srv->>Srv: Run pytest command
    alt Test Crashes
        Srv->>DB: recall(test_name)
        DB-->>Srv: Return matching historical incident traces
        Srv->>AI: build_review(failure, history)
        AI-->>Srv: Return n-gram validated review
        Srv->>DB: remember(new_failure)
    end
    Srv-->>CLI: Return test output & reviews
    CLI-->>User: Render review in terminal
```

### Configuration Priority Resolution

```mermaid
graph LR
    Local[1. .env.local] --> Combine[Environment Pool]
    ModeLocal[2. .env.mode.local] --> Combine
    Mode[3. .env.mode] --> Combine
    Root[4. .env] --> Combine
    Combine --> Config[Kiwi Config Loader]
    State[kiwi_session_state.json] -- Bypasses env if logged in --> Config
```

1. **Surface Layer**: Built with React and Ink, providing terminal components, state management, and autocomplete command suggestions.
2. **Backend API Layer**: Built with FastAPI, acting as a middleware server coordinating pytest runs, memory writes, and status checks.
3. **Memory Layer**: Built on the Cognee graph database platform to store and query failure logs contextually.
4. **Reviewer Engine**: Runs LLM queries and validates output using sentence n-gram verification against recalled context.

---

## Subsystems

### CLI REPL Subsystem
Located in `kiwi-ui/index.tsx`, this subsystem handles stdin/stdout rendering, command routing, autocomplete dropdowns, welcome menus, and credentials gating.

### API Backend Subsystem
Located in `app/main.py`, this coordinates API requests, runs subprocesses, and manages configurations in `kiwi_session_state.json`.

### Memory Subsystem
Located in `sentinel/cognee_client.py`, this wraps Cognee API commands (`remember` and `recall`) and indexes incident traces into vector databases.

---

## Execution Tools

### Pytest Executable Tool
Invokes pytest in a local subprocess with JUnit XML serialization flags (`--junitxml=junit_report.xml`) and tracks local failure metrics.

### Cognee Storage Client Tool
Performs vector similarity queries (`recall`) and updates graph memory nodes (`remember`).

### Review Builder Tool
Translates JUnit XML outputs and git changes into grounded developer reviews via Dynamic LLM calls.

---

## Commands Registry

| Command | Description |
|---|---|
| `/login` | Picks your LLM provider and model (Cognee itself needs no login — self-hosted, no auth). |
| `/provider` | Allows switching active LLM Provider (Anthropic, OpenAI, Gemini). |
| `/model` | Allows selecting provider-specific models. |
| `/config` | Prints active configuration and settings. |
| `/clear` | Instantly clears the screen's message logs. |
| `/test [path]` | Spawns pytest and auto-ingests failures. |
| `/remember <text>` | Manually saves a custom fact/incident comment to graph memory. |
| `/recall <query>` | Contextually queries the Cognee memory graph. |
| `/resolve <summary>`| Records a resolution/fix summary for the last failing test. |
| `/flaky [test]` | Lists flaky-test failure counts. |
| `/history <test>` | Lists all historical failures of a target test. |
| `/session` | Outputs logs for the active CLI session. |
| `/forget` | Explicitly clears datasets from Cognee memory. |
| `/exit` | Safely quits the Kiwi CLI. |
| `/fix [path]` | Runs a multi-step agentic loop to autonomously diagnose and fix a failing test. |

---

## Agentic QA Harness

Kiwi's `/fix [path]` command (and natural-language requests like "fix the failing payment test") run a multi-step agentic loop — run test → inspect → search code → edit → rerun → repeat — instead of a one-shot suggestion. File edits and shell commands require per-action approval, and the loop stops after 10 iterations if unresolved. See the design at [docs/superpowers/specs/2026-07-20-agentic-qa-harness-design.md](docs/superpowers/specs/2026-07-20-agentic-qa-harness-design.md).

---

## Self-Hosted Cognee

Kiwi runs entirely on a self-hosted, Dockerized Cognee instance (`docker-compose.cognee.yml`) instead of the paid Cognee Cloud — `kiwi.ps1` starts it automatically alongside the backend. No Cognee auth is required for this local single-user setup, so `/login` only asks for your LLM provider and model. See the design at [docs/superpowers/specs/2026-07-20-cognee-self-hosted-migration-design.md](docs/superpowers/specs/2026-07-20-cognee-self-hosted-migration-design.md).

To stop the Cognee server (data persists, restarts fresh on next `.\kiwi` launch):
```bash
docker compose -f docker-compose.cognee.yml down
```
Add `-v` to also wipe its stored memory data: `docker compose -f docker-compose.cognee.yml down -v`

**Upgrading from before this migration?** If your `.env` still has `COGNEE_BASE_URL` pointed at a `*.aws.cognee.ai` Cloud URL (plus `COGNEE_API_KEY`/`COGNEE_TENANT_ID`), remove those three lines — otherwise Kiwi keeps silently talking to Cloud, which now rejects every request since credentials are no longer sent.

---

## Getting Started

### 1. Prerequisites
* Python 3.12+
* Node.js & pnpm
* uv (Fast Python package manager)
* Docker (for the self-hosted Cognee server)

### 2. Configuration Setup
Copy `.env.example` to `.env` (or `.env.local`) and fill in at least one LLM key. `kiwi.ps1` auto-starts a local self-hosted Cognee server (via `docker-compose.cognee.yml`) using whichever key you provide — no Cognee account or API key needed.
```env
# COGNEE_BASE_URL=http://localhost:8010  # optional override; defaults to this if unset
SENTINEL_DATASET=sentinel
ANTHROPIC_API_KEY=your_anthropic_key_here
GEMINI_API_KEY=your_gemini_key_here
OPENAI_API_KEY=your_openai_key_here
GITHUB_TOKEN=optional_for_pr_comments
```

### 3. Install Frontend Dependencies
Since the CLI's UI dependencies are located in the `kiwi-ui` directory, install them with:
```bash
pnpm install --prefix kiwi-ui
```
Or navigate into the directory and install:
```bash
cd kiwi-ui
pnpm install
```

### 4. Run the Backend API
```bash
uv run uvicorn app.main:app --port 8000
```

### 5. Run the CLI REPL
Use the silent launcher command for your shell:
* **CMD**: `kiwi`
* **PowerShell**: `.\kiwi`

*(Alternatively, you can launch via `pnpm kiwi`)*

---

## Codebase Documentation

For in-depth developer orientation, refer to:
* [CLAUDE.md](CLAUDE.md): Commands and architecture notes for AI coding agents working in this repo.
* [Exploration Guide](docs/exploration_guide.md): Code orientation map and data pipeline flow.
* [Subsystems Guide](docs/subsystems.md): Structural details of CLI, Backend, Memory, and Review engines.
* [Tools Reference](docs/tools.md): Specs for Kiwi's execution modules.
* [Command Reference](docs/commands.md): Details, functions, and examples for all REPL slash commands.
