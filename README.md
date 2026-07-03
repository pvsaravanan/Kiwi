# 🥝 Kiwi — QA Harness Agent

Kiwi is a terminal-native, intelligent QA assistant designed to integrate graph-based memory retrieval (powered by **Cognee**) with local test executions (via **pytest**).

---

## 🚀 Key Features

* **Terminal-Native REPL**: A reactive CLI surface built with **React + Ink**, offering autocomplete suggestions and instant command execution.
* **Graph-Based Memory**: Uses **Cognee** to index incident logs, stack traces, and resolution summaries, dynamically recalling them during test failures.
* **Dynamic Credentials Gate**: Keeps API credentials secure and overrides them step-by-step or automatically using `.env` priority lookups (`.env.local` -> `.env`).
* **Multi-Provider LLM Integration**: Dynamically switches LLM providers (Anthropic, Gemini, OpenAI) and active model configurations at runtime.
* **Factual Reviews**: Generates test reviews grounded in historical failure records, validated via sentence n-gram verification to eliminate hallucinations.

---

## 🛠️ Getting Started

### 1. Prerequisites
Ensure you have the following installed:
* Python 3.10+
* Node.js & `pnpm`
* `uv` (Fast Python package manager)

### 2. Configuration Setup
Create a `.env.local` or `.env` in the root directory:
```env
COGNEE_BASE_URL=https://<your-tenant>.cognee.ai
COGNEE_API_KEY=<your-api-key>
COGNEE_TENANT_ID=<your-tenant-id>

# LLM Keys
ANTHROPIC_API_KEY=<key>
GEMINI_API_KEY=<key>
OPENAI_API_KEY=<key>
```

### 3. Run the Backend API
```bash
uv run uvicorn app.main:app --port 8000
```

### 4. Run the CLI REPL
```bash
pnpm kiwi
# Or use the silent launchers:
# CMD: kiwi
# PowerShell: .\kiwi
```

---

## 🥝 Commands Registry

| Command | Description |
|---|---|
| `/login` | Starts the step-by-step interactive credentials gate. |
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

---

## 📖 Codebase Documentation

For in-depth developer orientation, refer to:
* 🗺️ [Exploration Guide](docs/exploration_guide.md): Code orientation map and data pipeline flow.
* 📦 [Subsystems Guide](docs/subsystems.md): Structural details of CLI, Backend, Memory, and Review engines.
* 🔧 [Tools Reference](docs/tools.md): Specs for Kiwi's execution modules.
