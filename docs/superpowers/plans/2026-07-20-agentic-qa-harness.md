# Agentic QA Harness Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace Kiwi's one-shot NL-to-single-action path with a real multi-step agentic tool-use loop (run test → inspect → search code → edit → rerun → repeat) reachable via a `/fix` command and natural language, with per-action approval on risky tools, across all three configured LLM providers.

**Architecture:** A provider-agnostic loop core (`sentinel/agent/loop.py`) calls one of three provider adapters (`sentinel/agent/providers/`) that normalize Anthropic/OpenAI/Gemini native tool-calling into a shared `AgentResponse` type, executes calls against a curated tool registry (`sentinel/agent/tools.py`), and streams events out through a thread-bridged FastAPI endpoint (`app/agent_bridge.py`, `app/main.py`) to the Ink UI (`kiwi-ui/index.tsx`), which renders tool calls/diffs and posts approval decisions back.

**Tech Stack:** Python 3.12, FastAPI, `anthropic`, `google-genai`, `openai` SDKs, pytest, React + Ink (TypeScript), Cognee Cloud.

## Global Constraints

- Max 10 tool-call iterations per `/fix` invocation (spec: "Fixed max iterations + report back").
- `edit_file` and `shell` always require per-action human approval by default; no persisted cross-session allowlist. `allow_rest_of_loop` only auto-approves for the remainder of the current run.
- All file-touching tools are sandboxed to the repo root — reject `..` traversal and absolute paths outside cwd.
- Tool-calling must work across Anthropic, OpenAI, and Gemini from day one (spec: "All three providers from day one").
- No sandboxed/containerized tool execution — tools run in the local backend process, same trust model as today's `/test`.
- Follow existing test style: plain `pytest` + `unittest.mock.MagicMock`, no new test framework (see `tests/test_cognee_client.py`, `tests/test_ingest.py`).
- No JS test framework exists in `kiwi-ui` today (see `kiwi-ui/package.json`) — UI task steps use manual verification, not automated tests, consistent with the rest of `kiwi-ui/index.tsx` being untested today.
- Reference spec: `docs/superpowers/specs/2026-07-20-agentic-qa-harness-design.md`.

---

## Task 1: Agent core types

**Files:**
- Create: `sentinel/agent/__init__.py`
- Create: `sentinel/agent/types.py`
- Test: `tests/agent/__init__.py`
- Test: `tests/agent/test_types.py`

**Interfaces:**
- Produces: `ToolCall(id: str, name: str, args: dict)`, `ToolSchema(name: str, description: str, parameters: dict)`, `Message(role: str, content: str = "", tool_calls: list[ToolCall] = [], tool_call_id: str | None = None, tool_name: str | None = None)`, `AgentResponse(tool_calls: list[ToolCall] = [], text: str = "")` with `.is_final` property (`True` when `tool_calls` is empty).

- [ ] **Step 1: Create package directories**

```bash
mkdir -p sentinel/agent tests/agent
```

- [ ] **Step 2: Write empty package markers**

`sentinel/agent/__init__.py`:
```python
```

`tests/agent/__init__.py`:
```python
```

- [ ] **Step 3: Write the failing test**

`tests/agent/test_types.py`:
```python
from sentinel.agent.types import AgentResponse, Message, ToolCall, ToolSchema


def test_tool_call_holds_id_name_args():
    call = ToolCall(id="c1", name="read_file", args={"path": "a.py"})
    assert call.id == "c1"
    assert call.name == "read_file"
    assert call.args == {"path": "a.py"}


def test_message_defaults_to_empty_tool_calls_and_no_ids():
    msg = Message(role="user", content="hello")
    assert msg.tool_calls == []
    assert msg.tool_call_id is None
    assert msg.tool_name is None


def test_agent_response_is_final_when_no_tool_calls():
    assert AgentResponse(text="done").is_final is True


def test_agent_response_is_not_final_with_tool_calls():
    call = ToolCall(id="c1", name="read_file", args={})
    assert AgentResponse(tool_calls=[call]).is_final is False


def test_tool_schema_holds_json_schema_parameters():
    schema = ToolSchema(
        name="read_file",
        description="Read a file.",
        parameters={"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]},
    )
    assert schema.parameters["required"] == ["path"]
```

- [ ] **Step 4: Run test to verify it fails**

Run: `uv run pytest tests/agent/test_types.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'sentinel.agent.types'`

- [ ] **Step 5: Write the implementation**

`sentinel/agent/types.py`:
```python
from dataclasses import dataclass, field


@dataclass
class ToolCall:
    id: str
    name: str
    args: dict


@dataclass
class ToolSchema:
    name: str
    description: str
    parameters: dict


@dataclass
class Message:
    role: str  # "user" | "assistant" | "tool"
    content: str = ""
    tool_calls: list[ToolCall] = field(default_factory=list)
    tool_call_id: str | None = None
    tool_name: str | None = None


@dataclass
class AgentResponse:
    tool_calls: list[ToolCall] = field(default_factory=list)
    text: str = ""

    @property
    def is_final(self) -> bool:
        return not self.tool_calls
```

- [ ] **Step 6: Run test to verify it passes**

Run: `uv run pytest tests/agent/test_types.py -v`
Expected: PASS (5 passed)

- [ ] **Step 7: Commit**

```bash
git add sentinel/agent/__init__.py sentinel/agent/types.py tests/agent/__init__.py tests/agent/test_types.py
git commit -m "feat: add shared agent message/tool types"
```

---

## Task 2: Tool sandboxing + read_file/search_code

**Files:**
- Create: `sentinel/agent/tools.py`
- Test: `tests/agent/test_tools.py`

**Interfaces:**
- Consumes: `sentinel.agent.types.ToolSchema` (Task 1); `sentinel.cognee_client.CogneeClient` (existing).
- Produces: `ToolError(RuntimeError)`, `ToolContext(repo_root: Path, cognee_client: CogneeClient, dataset: str)`, `ToolSpec(schema: ToolSchema, requires_approval: bool, run: Callable[[ToolContext, dict], str])`, `TOOL_REGISTRY: dict[str, ToolSpec]` (initially containing `read_file`, `search_code`; grows in Tasks 3-4).

- [ ] **Step 1: Write the failing tests**

`tests/agent/test_tools.py`:
```python
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from sentinel.agent.tools import TOOL_REGISTRY, ToolContext, ToolError


def make_ctx(tmp_path: Path) -> ToolContext:
    return ToolContext(repo_root=tmp_path, cognee_client=MagicMock(), dataset="sentinel")


def test_read_file_returns_numbered_lines(tmp_path):
    (tmp_path / "a.py").write_text("line1\nline2\nline3\n", encoding="utf-8")
    ctx = make_ctx(tmp_path)
    out = TOOL_REGISTRY["read_file"].run(ctx, {"path": "a.py"})
    assert out == "1\tline1\n2\tline2\n3\tline3"


def test_read_file_respects_start_and_end(tmp_path):
    (tmp_path / "a.py").write_text("line1\nline2\nline3\n", encoding="utf-8")
    ctx = make_ctx(tmp_path)
    out = TOOL_REGISTRY["read_file"].run(ctx, {"path": "a.py", "start": 2, "end": 2})
    assert out == "2\tline2"


def test_read_file_missing_file_raises_tool_error(tmp_path):
    ctx = make_ctx(tmp_path)
    with pytest.raises(ToolError, match="No such file"):
        TOOL_REGISTRY["read_file"].run(ctx, {"path": "missing.py"})


def test_read_file_rejects_path_escaping_repo_root(tmp_path):
    ctx = make_ctx(tmp_path)
    with pytest.raises(ToolError, match="escapes repo root"):
        TOOL_REGISTRY["read_file"].run(ctx, {"path": "../outside.py"})


def test_search_code_finds_matches_with_line_numbers(tmp_path):
    (tmp_path / "a.py").write_text("def foo():\n    return 1\n", encoding="utf-8")
    (tmp_path / "b.py").write_text("def bar():\n    return 2\n", encoding="utf-8")
    ctx = make_ctx(tmp_path)
    out = TOOL_REGISTRY["search_code"].run(ctx, {"pattern": "def foo"})
    assert "a.py:1: def foo():" in out
    assert "b.py" not in out


def test_search_code_no_matches_returns_message(tmp_path):
    (tmp_path / "a.py").write_text("nothing here\n", encoding="utf-8")
    ctx = make_ctx(tmp_path)
    out = TOOL_REGISTRY["search_code"].run(ctx, {"pattern": "notfound"})
    assert out == "No matches found."


def test_search_code_invalid_regex_raises_tool_error(tmp_path):
    ctx = make_ctx(tmp_path)
    with pytest.raises(ToolError, match="Invalid regex"):
        TOOL_REGISTRY["search_code"].run(ctx, {"pattern": "("})


def test_read_file_and_search_code_are_not_approval_gated():
    assert TOOL_REGISTRY["read_file"].requires_approval is False
    assert TOOL_REGISTRY["search_code"].requires_approval is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/agent/test_tools.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'sentinel.agent.tools'`

- [ ] **Step 3: Write the implementation**

`sentinel/agent/tools.py`:
```python
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from sentinel.agent.types import ToolSchema
from sentinel.cognee_client import CogneeClient


class ToolError(RuntimeError):
    pass


@dataclass
class ToolContext:
    repo_root: Path
    cognee_client: CogneeClient
    dataset: str


@dataclass
class ToolSpec:
    schema: ToolSchema
    requires_approval: bool
    run: Callable[["ToolContext", dict], str]


def _safe_path(repo_root: Path, path: str) -> Path:
    candidate = (repo_root / path).resolve()
    try:
        candidate.relative_to(repo_root.resolve())
    except ValueError:
        raise ToolError(f"Path escapes repo root: {path}")
    return candidate


def _read_file(ctx: ToolContext, args: dict) -> str:
    target = _safe_path(ctx.repo_root, args["path"])
    if not target.is_file():
        raise ToolError(f"No such file: {args['path']}")
    lines = target.read_text(encoding="utf-8").splitlines()
    start = args.get("start") or 1
    end = min(args.get("end") or len(lines), len(lines))
    numbered = [f"{i}\t{lines[i - 1]}" for i in range(start, end + 1)]
    return "\n".join(numbered)


def _search_code(ctx: ToolContext, args: dict) -> str:
    try:
        regex = re.compile(args["pattern"])
    except re.error as exc:
        raise ToolError(f"Invalid regex: {exc}")
    glob_pattern = args.get("glob") or "**/*.py"
    matches: list[str] = []
    for file_path in sorted(ctx.repo_root.glob(glob_pattern)):
        if not file_path.is_file() or file_path.stat().st_size > 1_000_000:
            continue
        try:
            text = file_path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        rel = file_path.relative_to(ctx.repo_root)
        for lineno, line in enumerate(text.splitlines(), start=1):
            if regex.search(line):
                matches.append(f"{rel}:{lineno}: {line.strip()}")
                if len(matches) >= 200:
                    return "\n".join(matches)
    return "\n".join(matches) if matches else "No matches found."


TOOL_REGISTRY: dict[str, ToolSpec] = {
    "read_file": ToolSpec(
        schema=ToolSchema(
            name="read_file",
            description="Read a file from the repository, optionally a line range.",
            parameters={
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Repo-relative file path."},
                    "start": {"type": "integer", "description": "First line to include (1-indexed)."},
                    "end": {"type": "integer", "description": "Last line to include."},
                },
                "required": ["path"],
            },
        ),
        requires_approval=False,
        run=_read_file,
    ),
    "search_code": ToolSpec(
        schema=ToolSchema(
            name="search_code",
            description="Search the repository for a regex pattern, optionally scoped by glob.",
            parameters={
                "type": "object",
                "properties": {
                    "pattern": {"type": "string", "description": "Regular expression to search for."},
                    "glob": {"type": "string", "description": "Glob to scope the search, e.g. '**/*.py'."},
                },
                "required": ["pattern"],
            },
        ),
        requires_approval=False,
        run=_search_code,
    ),
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/agent/test_tools.py -v`
Expected: PASS (8 passed)

- [ ] **Step 5: Commit**

```bash
git add sentinel/agent/tools.py tests/agent/test_tools.py
git commit -m "feat: add tool sandboxing, read_file, and search_code tools"
```

---

## Task 3: edit_file and shell tools

**Files:**
- Modify: `sentinel/agent/tools.py`
- Modify: `tests/agent/test_tools.py`

**Interfaces:**
- Consumes: `ToolContext`, `ToolError`, `ToolSpec`, `TOOL_REGISTRY`, `_safe_path` (Task 2).
- Produces: `TOOL_REGISTRY["edit_file"]`, `TOOL_REGISTRY["shell"]`, both `requires_approval=True`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/agent/test_tools.py`:
```python
def test_edit_file_replaces_unique_match_and_returns_diff(tmp_path):
    (tmp_path / "a.py").write_text("def foo():\n    return 1\n", encoding="utf-8")
    ctx = make_ctx(tmp_path)
    diff = TOOL_REGISTRY["edit_file"].run(ctx, {
        "path": "a.py", "old_string": "return 1", "new_string": "return 2",
    })
    assert (tmp_path / "a.py").read_text(encoding="utf-8") == "def foo():\n    return 2\n"
    assert "-    return 1" in diff
    assert "+    return 2" in diff


def test_edit_file_raises_when_old_string_missing(tmp_path):
    (tmp_path / "a.py").write_text("def foo():\n    return 1\n", encoding="utf-8")
    ctx = make_ctx(tmp_path)
    with pytest.raises(ToolError, match="not found"):
        TOOL_REGISTRY["edit_file"].run(ctx, {
            "path": "a.py", "old_string": "return 99", "new_string": "return 2",
        })


def test_edit_file_raises_when_old_string_not_unique(tmp_path):
    (tmp_path / "a.py").write_text("x = 1\nx = 1\n", encoding="utf-8")
    ctx = make_ctx(tmp_path)
    with pytest.raises(ToolError, match="not unique"):
        TOOL_REGISTRY["edit_file"].run(ctx, {
            "path": "a.py", "old_string": "x = 1", "new_string": "x = 2",
        })


def test_shell_returns_exit_code_and_output(tmp_path):
    ctx = make_ctx(tmp_path)
    out = TOOL_REGISTRY["shell"].run(ctx, {"command": "echo hello"})
    assert "exit code 0" in out
    assert "hello" in out


def test_shell_times_out_gracefully(tmp_path, monkeypatch):
    import subprocess as sp

    def fake_run(*args, **kwargs):
        raise sp.TimeoutExpired(cmd="sleep 999", timeout=60)

    monkeypatch.setattr("sentinel.agent.tools.subprocess.run", fake_run)
    ctx = make_ctx(tmp_path)
    out = TOOL_REGISTRY["shell"].run(ctx, {"command": "sleep 999"})
    assert "timed out" in out.lower()


def test_edit_file_and_shell_require_approval():
    assert TOOL_REGISTRY["edit_file"].requires_approval is True
    assert TOOL_REGISTRY["shell"].requires_approval is True
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/agent/test_tools.py -v`
Expected: FAIL with `KeyError: 'edit_file'`

- [ ] **Step 3: Write the implementation**

Add near the top of `sentinel/agent/tools.py` (with the other imports):
```python
import difflib
import subprocess
```

Add after `_search_code` and before the `TOOL_REGISTRY` dict in `sentinel/agent/tools.py`:
```python
def _edit_file(ctx: ToolContext, args: dict) -> str:
    path = args["path"]
    old_string = args["old_string"]
    new_string = args["new_string"]
    target = _safe_path(ctx.repo_root, path)
    if not target.is_file():
        raise ToolError(f"No such file: {path}")
    original = target.read_text(encoding="utf-8")
    count = original.count(old_string)
    if count == 0:
        raise ToolError(f"old_string not found in {path}")
    if count > 1:
        raise ToolError(f"old_string is not unique in {path} ({count} occurrences); include more context")
    updated = original.replace(old_string, new_string, 1)
    target.write_text(updated, encoding="utf-8")
    diff = "\n".join(difflib.unified_diff(
        original.splitlines(), updated.splitlines(),
        fromfile=f"a/{path}", tofile=f"b/{path}", lineterm="",
    ))
    return diff


def _shell(ctx: ToolContext, args: dict) -> str:
    try:
        result = subprocess.run(
            args["command"], shell=True, cwd=ctx.repo_root,
            capture_output=True, text=True, timeout=60,
        )
    except subprocess.TimeoutExpired:
        return "Command timed out after 60s."
    output = (result.stdout + result.stderr)[-4000:]
    return f"exit code {result.returncode}\n{output}"
```

Replace the `TOOL_REGISTRY: dict[str, ToolSpec] = { ... }` block in `sentinel/agent/tools.py` with:
```python
TOOL_REGISTRY: dict[str, ToolSpec] = {
    "read_file": ToolSpec(
        schema=ToolSchema(
            name="read_file",
            description="Read a file from the repository, optionally a line range.",
            parameters={
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Repo-relative file path."},
                    "start": {"type": "integer", "description": "First line to include (1-indexed)."},
                    "end": {"type": "integer", "description": "Last line to include."},
                },
                "required": ["path"],
            },
        ),
        requires_approval=False,
        run=_read_file,
    ),
    "search_code": ToolSpec(
        schema=ToolSchema(
            name="search_code",
            description="Search the repository for a regex pattern, optionally scoped by glob.",
            parameters={
                "type": "object",
                "properties": {
                    "pattern": {"type": "string", "description": "Regular expression to search for."},
                    "glob": {"type": "string", "description": "Glob to scope the search, e.g. '**/*.py'."},
                },
                "required": ["pattern"],
            },
        ),
        requires_approval=False,
        run=_search_code,
    ),
    "edit_file": ToolSpec(
        schema=ToolSchema(
            name="edit_file",
            description="Replace an exact, unique string in a file. Fails if old_string is missing or ambiguous.",
            parameters={
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Repo-relative file path."},
                    "old_string": {"type": "string", "description": "Exact text to replace; must be unique in the file."},
                    "new_string": {"type": "string", "description": "Replacement text."},
                },
                "required": ["path", "old_string", "new_string"],
            },
        ),
        requires_approval=True,
        run=_edit_file,
    ),
    "shell": ToolSpec(
        schema=ToolSchema(
            name="shell",
            description="Run a shell command in the repository root. Use for one-offs like checking git status or installing a dependency.",
            parameters={
                "type": "object",
                "properties": {
                    "command": {"type": "string", "description": "Shell command to run."},
                },
                "required": ["command"],
            },
        ),
        requires_approval=True,
        run=_shell,
    ),
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/agent/test_tools.py -v`
Expected: PASS (14 passed)

- [ ] **Step 5: Commit**

```bash
git add sentinel/agent/tools.py tests/agent/test_tools.py
git commit -m "feat: add edit_file and shell tools with approval gating"
```

---

## Task 4: run_tests, recall, and remember tools

**Files:**
- Modify: `sentinel/agent/tools.py`
- Modify: `tests/agent/test_tools.py`

**Interfaces:**
- Consumes: `sentinel.ingest.process_report` (existing, `sentinel/ingest.py:37`), `ToolContext.cognee_client` / `.dataset` (Task 2).
- Produces: `TOOL_REGISTRY["run_tests"]`, `TOOL_REGISTRY["recall"]`, `TOOL_REGISTRY["remember"]`, all `requires_approval=False`. `TOOL_REGISTRY` is now complete (7 tools).

- [ ] **Step 1: Write the failing tests**

Append to `tests/agent/test_tools.py`:
```python
def test_run_tests_reports_all_passed_when_no_junit_report(tmp_path, monkeypatch):
    import subprocess as sp

    def fake_run(*args, **kwargs):
        return sp.CompletedProcess(args=args, returncode=0, stdout="", stderr="")

    monkeypatch.setattr("sentinel.agent.tools.subprocess.run", fake_run)
    ctx = make_ctx(tmp_path)
    out = TOOL_REGISTRY["run_tests"].run(ctx, {})
    assert "no JUnit report" in out or "All tests passed" in out


def test_run_tests_summarizes_failures_from_junit_report(tmp_path, monkeypatch):
    import subprocess as sp

    junit_xml = (
        '<testsuite><testcase name="test_x" classname="tests.test_x">'
        '<failure message="boom">trace</failure></testcase></testsuite>'
    )
    (tmp_path / "junit_report.xml").write_text(junit_xml, encoding="utf-8")

    def fake_run(*args, **kwargs):
        return sp.CompletedProcess(args=args, returncode=1, stdout="", stderr="")

    monkeypatch.setattr("sentinel.agent.tools.subprocess.run", fake_run)
    ctx = make_ctx(tmp_path)
    ctx.cognee_client.recall.return_value = []
    out = TOOL_REGISTRY["run_tests"].run(ctx, {"path": "tests/test_x.py"})
    assert "test_x" in out
    assert "boom" in out
    ctx.cognee_client.remember.assert_called_once()


def test_recall_formats_hits(tmp_path):
    ctx = make_ctx(tmp_path)
    ctx.cognee_client.recall.return_value = [{"text": "prior incident"}]
    out = TOOL_REGISTRY["recall"].run(ctx, {"query": "flaky login"})
    assert out == "- prior incident"
    ctx.cognee_client.recall.assert_called_once_with("flaky login", dataset="sentinel")


def test_recall_no_hits_returns_message(tmp_path):
    ctx = make_ctx(tmp_path)
    ctx.cognee_client.recall.return_value = []
    out = TOOL_REGISTRY["recall"].run(ctx, {"query": "flaky login"})
    assert out == "No matching memories found."


def test_remember_delegates_to_client(tmp_path):
    ctx = make_ctx(tmp_path)
    out = TOOL_REGISTRY["remember"].run(ctx, {"text": "fixed by adding retry"})
    ctx.cognee_client.remember.assert_called_once_with("fixed by adding retry", dataset="sentinel")
    assert out == "Stored in memory."


def test_run_tests_recall_remember_are_not_approval_gated():
    assert TOOL_REGISTRY["run_tests"].requires_approval is False
    assert TOOL_REGISTRY["recall"].requires_approval is False
    assert TOOL_REGISTRY["remember"].requires_approval is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/agent/test_tools.py -v`
Expected: FAIL with `KeyError: 'run_tests'`

- [ ] **Step 3: Write the implementation**

Add near the top of `sentinel/agent/tools.py`:
```python
from sentinel.ingest import process_report
```

Add after `_shell` and before `TOOL_REGISTRY` in `sentinel/agent/tools.py`:
```python
def _run_tests(ctx: ToolContext, args: dict) -> str:
    path = (args.get("path") or "").strip()
    cmd = ["uv", "run", "pytest", "--junitxml=junit_report.xml"]
    if path:
        cmd.append(path)
    result = subprocess.run(cmd, cwd=ctx.repo_root, capture_output=True, text=True, timeout=300)
    junit_path = ctx.repo_root / "junit_report.xml"
    if not junit_path.exists():
        return f"pytest exited {result.returncode} but produced no JUnit report:\n{result.stdout[-2000:]}"
    ingest_results = process_report(str(junit_path), client=ctx.cognee_client, dataset=ctx.dataset)
    if not ingest_results:
        return "All tests passed."
    lines = [f"{len(ingest_results)} test(s) failed:"]
    for r in ingest_results:
        lines.append(f"- {r.failure.test_name}: {r.failure.error_message}")
        if r.matched and r.history:
            lines.append(f"  prior history: {r.history}")
    return "\n".join(lines)


def _recall(ctx: ToolContext, args: dict) -> str:
    hits = ctx.cognee_client.recall(args["query"], dataset=ctx.dataset)
    if not hits:
        return "No matching memories found."
    return "\n".join(f"- {h.get('text')}" for h in hits)


def _remember(ctx: ToolContext, args: dict) -> str:
    ctx.cognee_client.remember(args["text"], dataset=ctx.dataset)
    return "Stored in memory."
```

Add these three entries to the `TOOL_REGISTRY` dict in `sentinel/agent/tools.py` (after `"shell": ...,` and before the closing `}`):
```python
    "run_tests": ToolSpec(
        schema=ToolSchema(
            name="run_tests",
            description="Run pytest (optionally scoped to a path) and get a structured pass/fail summary with recalled history for any failures.",
            parameters={
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Repo-relative test path, or empty to run the full suite."},
                },
                "required": [],
            },
        ),
        requires_approval=False,
        run=_run_tests,
    ),
    "recall": ToolSpec(
        schema=ToolSchema(
            name="recall",
            description="Query Cognee memory for prior incidents similar to a description.",
            parameters={
                "type": "object",
                "properties": {"query": {"type": "string", "description": "Description of the failure to search for."}},
                "required": ["query"],
            },
        ),
        requires_approval=False,
        run=_recall,
    ),
    "remember": ToolSpec(
        schema=ToolSchema(
            name="remember",
            description="Store a fact or resolution summary in Cognee memory.",
            parameters={
                "type": "object",
                "properties": {"text": {"type": "string", "description": "Fact or resolution to store."}},
                "required": ["text"],
            },
        ),
        requires_approval=False,
        run=_remember,
    ),
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/agent/test_tools.py -v`
Expected: PASS (20 passed)

- [ ] **Step 5: Commit**

```bash
git add sentinel/agent/tools.py tests/agent/test_tools.py
git commit -m "feat: add run_tests, recall, and remember tools to complete the registry"
```

---

## Task 5: Provider adapter base + Anthropic adapter

**Files:**
- Create: `sentinel/agent/providers/__init__.py`
- Create: `sentinel/agent/providers/base.py`
- Create: `sentinel/agent/providers/anthropic_provider.py`
- Test: `tests/agent/test_provider_anthropic.py`

**Interfaces:**
- Consumes: `sentinel.agent.types.{AgentResponse, Message, ToolCall, ToolSchema}` (Task 1).
- Produces: `ProviderAdapter` protocol (`converse(messages, tools, system) -> AgentResponse`), `AnthropicAdapter(client, model).converse(...)`.

- [ ] **Step 1: Write the failing tests**

`tests/agent/test_provider_anthropic.py`:
```python
from types import SimpleNamespace
from unittest.mock import MagicMock

from sentinel.agent.providers.anthropic_provider import AnthropicAdapter
from sentinel.agent.types import Message, ToolCall, ToolSchema

TOOLS = [ToolSchema(name="read_file", description="Read a file.", parameters={
    "type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"],
})]


def make_text_response(text: str):
    block = SimpleNamespace(type="text", text=text)
    return SimpleNamespace(content=[block])


def make_tool_use_response(call_id: str, name: str, tool_input: dict):
    block = SimpleNamespace(type="tool_use", id=call_id, name=name, input=tool_input)
    return SimpleNamespace(content=[block])


def test_converse_returns_text_when_no_tool_use():
    client = MagicMock()
    client.messages.create.return_value = make_text_response("All good.")
    adapter = AnthropicAdapter(client, model="claude-opus-4-8")

    response = adapter.converse([Message(role="user", content="hi")], tools=TOOLS, system="sys")

    assert response.is_final is True
    assert response.text == "All good."


def test_converse_returns_tool_calls_when_tool_use_present():
    client = MagicMock()
    client.messages.create.return_value = make_tool_use_response("call_1", "read_file", {"path": "a.py"})
    adapter = AnthropicAdapter(client, model="claude-opus-4-8")

    response = adapter.converse([Message(role="user", content="read a.py")], tools=TOOLS, system="sys")

    assert response.is_final is False
    assert response.tool_calls == [ToolCall(id="call_1", name="read_file", args={"path": "a.py"})]


def test_converse_sends_tools_in_anthropic_input_schema_shape():
    client = MagicMock()
    client.messages.create.return_value = make_text_response("ok")
    adapter = AnthropicAdapter(client, model="claude-opus-4-8")

    adapter.converse([Message(role="user", content="hi")], tools=TOOLS, system="sys")

    sent_tools = client.messages.create.call_args.kwargs["tools"]
    assert sent_tools == [{
        "name": "read_file", "description": "Read a file.",
        "input_schema": TOOLS[0].parameters,
    }]
    assert client.messages.create.call_args.kwargs["system"] == "sys"


def test_converse_translates_tool_result_message_to_user_tool_result_block():
    client = MagicMock()
    client.messages.create.return_value = make_text_response("ok")
    adapter = AnthropicAdapter(client, model="claude-opus-4-8")
    messages = [
        Message(role="user", content="read a.py"),
        Message(role="assistant", tool_calls=[ToolCall(id="call_1", name="read_file", args={"path": "a.py"})]),
        Message(role="tool", tool_call_id="call_1", tool_name="read_file", content="1\tprint(1)"),
    ]

    adapter.converse(messages, tools=TOOLS, system="sys")

    sent_messages = client.messages.create.call_args.kwargs["messages"]
    assert sent_messages[2] == {
        "role": "user",
        "content": [{"type": "tool_result", "tool_use_id": "call_1", "content": "1\tprint(1)"}],
    }
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/agent/test_provider_anthropic.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'sentinel.agent.providers'`

- [ ] **Step 3: Write the implementation**

`sentinel/agent/providers/__init__.py`:
```python
```

`sentinel/agent/providers/base.py`:
```python
from typing import Protocol

from sentinel.agent.types import AgentResponse, Message, ToolSchema


class ProviderAdapter(Protocol):
    def converse(self, messages: list[Message], tools: list[ToolSchema], system: str) -> AgentResponse: ...
```

`sentinel/agent/providers/anthropic_provider.py`:
```python
from sentinel.agent.types import AgentResponse, Message, ToolCall, ToolSchema


class AnthropicAdapter:
    def __init__(self, client, model: str):
        self.client = client
        self.model = model

    def converse(self, messages: list[Message], tools: list[ToolSchema], system: str) -> AgentResponse:
        anthropic_tools = [
            {"name": t.name, "description": t.description, "input_schema": t.parameters}
            for t in tools
        ]
        anthropic_messages = [self._to_anthropic_message(m) for m in messages]
        response = self.client.messages.create(
            model=self.model, max_tokens=2048, system=system,
            tools=anthropic_tools, messages=anthropic_messages,
        )
        tool_calls = [
            ToolCall(id=block.id, name=block.name, args=block.input)
            for block in response.content if block.type == "tool_use"
        ]
        if tool_calls:
            return AgentResponse(tool_calls=tool_calls)
        text = "".join(block.text for block in response.content if block.type == "text")
        return AgentResponse(text=text)

    @staticmethod
    def _to_anthropic_message(m: Message) -> dict:
        if m.role == "tool":
            return {"role": "user", "content": [
                {"type": "tool_result", "tool_use_id": m.tool_call_id, "content": m.content},
            ]}
        if m.role == "assistant" and m.tool_calls:
            return {"role": "assistant", "content": [
                {"type": "tool_use", "id": c.id, "name": c.name, "input": c.args}
                for c in m.tool_calls
            ]}
        return {"role": m.role, "content": m.content}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/agent/test_provider_anthropic.py -v`
Expected: PASS (4 passed)

- [ ] **Step 5: Commit**

```bash
git add sentinel/agent/providers/ tests/agent/test_provider_anthropic.py
git commit -m "feat: add provider adapter protocol and Anthropic tool-calling adapter"
```

---

## Task 6: OpenAI adapter

**Files:**
- Modify: `pyproject.toml`
- Create: `sentinel/agent/providers/openai_provider.py`
- Test: `tests/agent/test_provider_openai.py`

**Interfaces:**
- Consumes: `sentinel.agent.types.{AgentResponse, Message, ToolCall, ToolSchema}` (Task 1).
- Produces: `OpenAIAdapter(client, model).converse(...)`.

- [ ] **Step 1: Add openai as an explicit dependency**

In `pyproject.toml`, in the `dependencies` list (it currently has `anthropic>=0.40` and `google-genai>=0.1.1` — `openai` is used lazily today in `sentinel/llm_client.py` but isn't declared; the agent loop needs it testable/installed like the other two providers):
```toml
dependencies = [
    "requests>=2.32",
    "python-dotenv>=1.0",
    "fastapi>=0.115",
    "uvicorn>=0.30",
    "anthropic>=0.40",
    "streamlit>=1.40",
    "pyvis>=0.3.2",
    "google-genai>=0.1.1",
    "openai>=1.50",
    "rich>=13.7.0",
    "cryptography>=42.0",
]
```

Run: `uv sync`
Expected: `openai` installed, `uv.lock` updated.

- [ ] **Step 2: Write the failing tests**

`tests/agent/test_provider_openai.py`:
```python
import json
from types import SimpleNamespace
from unittest.mock import MagicMock

from sentinel.agent.providers.openai_provider import OpenAIAdapter
from sentinel.agent.types import Message, ToolCall, ToolSchema

TOOLS = [ToolSchema(name="read_file", description="Read a file.", parameters={
    "type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"],
})]


def make_text_response(text: str):
    message = SimpleNamespace(content=text, tool_calls=None)
    return SimpleNamespace(choices=[SimpleNamespace(message=message)])


def make_tool_call_response(call_id: str, name: str, arguments: dict):
    function = SimpleNamespace(name=name, arguments=json.dumps(arguments))
    tool_call = SimpleNamespace(id=call_id, function=function)
    message = SimpleNamespace(content=None, tool_calls=[tool_call])
    return SimpleNamespace(choices=[SimpleNamespace(message=message)])


def test_converse_returns_text_when_no_tool_calls():
    client = MagicMock()
    client.chat.completions.create.return_value = make_text_response("All good.")
    adapter = OpenAIAdapter(client, model="gpt-5.5")

    response = adapter.converse([Message(role="user", content="hi")], tools=TOOLS, system="sys")

    assert response.is_final is True
    assert response.text == "All good."


def test_converse_returns_tool_calls_and_parses_json_arguments():
    client = MagicMock()
    client.chat.completions.create.return_value = make_tool_call_response("call_1", "read_file", {"path": "a.py"})
    adapter = OpenAIAdapter(client, model="gpt-5.5")

    response = adapter.converse([Message(role="user", content="read a.py")], tools=TOOLS, system="sys")

    assert response.is_final is False
    assert response.tool_calls == [ToolCall(id="call_1", name="read_file", args={"path": "a.py"})]


def test_converse_sends_tools_in_openai_function_shape_and_system_message():
    client = MagicMock()
    client.chat.completions.create.return_value = make_text_response("ok")
    adapter = OpenAIAdapter(client, model="gpt-5.5")

    adapter.converse([Message(role="user", content="hi")], tools=TOOLS, system="sys")

    call_kwargs = client.chat.completions.create.call_args.kwargs
    assert call_kwargs["tools"] == [{
        "type": "function",
        "function": {"name": "read_file", "description": "Read a file.", "parameters": TOOLS[0].parameters},
    }]
    assert call_kwargs["messages"][0] == {"role": "system", "content": "sys"}


def test_converse_translates_tool_result_message_to_tool_role():
    client = MagicMock()
    client.chat.completions.create.return_value = make_text_response("ok")
    adapter = OpenAIAdapter(client, model="gpt-5.5")
    messages = [
        Message(role="user", content="read a.py"),
        Message(role="assistant", tool_calls=[ToolCall(id="call_1", name="read_file", args={"path": "a.py"})]),
        Message(role="tool", tool_call_id="call_1", tool_name="read_file", content="1\tprint(1)"),
    ]

    adapter.converse(messages, tools=TOOLS, system="sys")

    sent_messages = client.chat.completions.create.call_args.kwargs["messages"]
    assert sent_messages[3] == {"role": "tool", "tool_call_id": "call_1", "content": "1\tprint(1)"}
```

- [ ] **Step 3: Run test to verify it fails**

Run: `uv run pytest tests/agent/test_provider_openai.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'sentinel.agent.providers.openai_provider'`

- [ ] **Step 4: Write the implementation**

`sentinel/agent/providers/openai_provider.py`:
```python
import json

from sentinel.agent.types import AgentResponse, Message, ToolCall, ToolSchema


class OpenAIAdapter:
    def __init__(self, client, model: str):
        self.client = client
        self.model = model

    def converse(self, messages: list[Message], tools: list[ToolSchema], system: str) -> AgentResponse:
        openai_tools = [
            {"type": "function", "function": {
                "name": t.name, "description": t.description, "parameters": t.parameters,
            }} for t in tools
        ]
        openai_messages = [{"role": "system", "content": system}]
        openai_messages += [self._to_openai_message(m) for m in messages]
        response = self.client.chat.completions.create(
            model=self.model, messages=openai_messages, tools=openai_tools,
        )
        message = response.choices[0].message
        raw_tool_calls = message.tool_calls or []
        if raw_tool_calls:
            tool_calls = [
                ToolCall(id=c.id, name=c.function.name, args=json.loads(c.function.arguments))
                for c in raw_tool_calls
            ]
            return AgentResponse(tool_calls=tool_calls)
        return AgentResponse(text=message.content or "")

    @staticmethod
    def _to_openai_message(m: Message) -> dict:
        if m.role == "tool":
            return {"role": "tool", "tool_call_id": m.tool_call_id, "content": m.content}
        if m.role == "assistant" and m.tool_calls:
            return {"role": "assistant", "content": None, "tool_calls": [
                {"id": c.id, "type": "function",
                 "function": {"name": c.name, "arguments": json.dumps(c.args)}}
                for c in m.tool_calls
            ]}
        return {"role": m.role, "content": m.content}
```

- [ ] **Step 5: Run test to verify it passes**

Run: `uv run pytest tests/agent/test_provider_openai.py -v`
Expected: PASS (4 passed)

- [ ] **Step 6: Commit**

```bash
git add pyproject.toml uv.lock sentinel/agent/providers/openai_provider.py tests/agent/test_provider_openai.py
git commit -m "feat: add OpenAI tool-calling adapter and declare openai dependency"
```

---

## Task 7: Gemini adapter + build_adapter factory

**Files:**
- Create: `sentinel/agent/providers/gemini_provider.py`
- Modify: `sentinel/agent/providers/__init__.py`
- Test: `tests/agent/test_provider_gemini.py`
- Test: `tests/agent/test_providers_init.py`

**Interfaces:**
- Consumes: `sentinel.agent.types.{AgentResponse, Message, ToolCall, ToolSchema}` (Task 1); `AnthropicAdapter`, `OpenAIAdapter` (Tasks 5-6).
- Produces: `GeminiAdapter(client, model).converse(...)`; `build_adapter(provider: str, client, model: str) -> ProviderAdapter` in `sentinel/agent/providers/__init__.py`.

- [ ] **Step 1: Write the failing Gemini adapter tests**

`tests/agent/test_provider_gemini.py`:
```python
from types import SimpleNamespace
from unittest.mock import MagicMock

from sentinel.agent.providers.gemini_provider import GeminiAdapter
from sentinel.agent.types import Message, ToolCall, ToolSchema

TOOLS = [ToolSchema(name="read_file", description="Read a file.", parameters={
    "type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"],
})]


def make_text_response(text: str):
    part = SimpleNamespace(text=text, function_call=None)
    content = SimpleNamespace(parts=[part])
    return SimpleNamespace(candidates=[SimpleNamespace(content=content)])


def make_function_call_response(name: str, args: dict):
    function_call = SimpleNamespace(name=name, args=args)
    part = SimpleNamespace(text=None, function_call=function_call)
    content = SimpleNamespace(parts=[part])
    return SimpleNamespace(candidates=[SimpleNamespace(content=content)])


def test_converse_returns_text_when_no_function_call():
    client = MagicMock()
    client.models.generate_content.return_value = make_text_response("All good.")
    adapter = GeminiAdapter(client, model="gemini-3-flash-preview")

    response = adapter.converse([Message(role="user", content="hi")], tools=TOOLS, system="sys")

    assert response.is_final is True
    assert response.text == "All good."


def test_converse_returns_tool_call_when_function_call_present():
    client = MagicMock()
    client.models.generate_content.return_value = make_function_call_response("read_file", {"path": "a.py"})
    adapter = GeminiAdapter(client, model="gemini-3-flash-preview")

    response = adapter.converse([Message(role="user", content="read a.py")], tools=TOOLS, system="sys")

    assert response.is_final is False
    assert len(response.tool_calls) == 1
    assert response.tool_calls[0].name == "read_file"
    assert response.tool_calls[0].args == {"path": "a.py"}


def test_converse_maps_assistant_role_to_model():
    client = MagicMock()
    client.models.generate_content.return_value = make_text_response("ok")
    adapter = GeminiAdapter(client, model="gemini-3-flash-preview")
    messages = [
        Message(role="user", content="read a.py"),
        Message(role="assistant", tool_calls=[ToolCall(id="0", name="read_file", args={"path": "a.py"})]),
        Message(role="tool", tool_call_id="0", tool_name="read_file", content="1\tprint(1)"),
    ]

    adapter.converse(messages, tools=TOOLS, system="sys")

    contents = client.models.generate_content.call_args.kwargs["contents"]
    assert contents[1]["role"] == "model"
    assert contents[2]["role"] == "user"
    assert contents[2]["parts"][0]["function_response"]["name"] == "read_file"
    assert contents[2]["parts"][0]["function_response"]["response"] == {"result": "1\tprint(1)"}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/agent/test_provider_gemini.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'sentinel.agent.providers.gemini_provider'`

- [ ] **Step 3: Write the Gemini adapter implementation**

`sentinel/agent/providers/gemini_provider.py`:
```python
from google.genai import types

from sentinel.agent.types import AgentResponse, Message, ToolCall, ToolSchema


class GeminiAdapter:
    def __init__(self, client, model: str):
        self.client = client
        self.model = model

    def converse(self, messages: list[Message], tools: list[ToolSchema], system: str) -> AgentResponse:
        function_declarations = [
            types.FunctionDeclaration(name=t.name, description=t.description, parameters=t.parameters)
            for t in tools
        ]
        contents = [self._to_gemini_content(m) for m in messages]
        response = self.client.models.generate_content(
            model=self.model, contents=contents,
            config=types.GenerateContentConfig(
                system_instruction=system,
                tools=[types.Tool(function_declarations=function_declarations)],
            ),
        )
        parts = response.candidates[0].content.parts
        tool_calls = [
            ToolCall(id=str(i), name=p.function_call.name, args=dict(p.function_call.args))
            for i, p in enumerate(parts) if getattr(p, "function_call", None)
        ]
        if tool_calls:
            return AgentResponse(tool_calls=tool_calls)
        text = "".join(p.text for p in parts if getattr(p, "text", None))
        return AgentResponse(text=text)

    @staticmethod
    def _to_gemini_content(m: Message) -> dict:
        if m.role == "tool":
            return {"role": "user", "parts": [
                {"function_response": {"name": m.tool_name, "response": {"result": m.content}}},
            ]}
        if m.role == "assistant" and m.tool_calls:
            return {"role": "model", "parts": [
                {"function_call": {"name": c.name, "args": c.args}} for c in m.tool_calls
            ]}
        role = "model" if m.role == "assistant" else "user"
        return {"role": role, "parts": [{"text": m.content}]}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/agent/test_provider_gemini.py -v`
Expected: PASS (3 passed)

- [ ] **Step 5: Write the failing build_adapter test**

`tests/agent/test_providers_init.py`:
```python
from unittest.mock import MagicMock

import pytest

from sentinel.agent.providers import build_adapter
from sentinel.agent.providers.anthropic_provider import AnthropicAdapter
from sentinel.agent.providers.gemini_provider import GeminiAdapter
from sentinel.agent.providers.openai_provider import OpenAIAdapter


def test_build_adapter_returns_anthropic_adapter():
    adapter = build_adapter("anthropic", MagicMock(), "claude-opus-4-8")
    assert isinstance(adapter, AnthropicAdapter)


def test_build_adapter_returns_openai_adapter():
    adapter = build_adapter("openai", MagicMock(), "gpt-5.5")
    assert isinstance(adapter, OpenAIAdapter)


def test_build_adapter_returns_gemini_adapter():
    adapter = build_adapter("gemini", MagicMock(), "gemini-3-flash-preview")
    assert isinstance(adapter, GeminiAdapter)


def test_build_adapter_raises_for_unknown_provider():
    with pytest.raises(ValueError, match="Unsupported provider"):
        build_adapter("mystery", MagicMock(), "some-model")
```

- [ ] **Step 6: Run test to verify it fails**

Run: `uv run pytest tests/agent/test_providers_init.py -v`
Expected: FAIL with `ImportError: cannot import name 'build_adapter'`

- [ ] **Step 7: Write the build_adapter implementation**

`sentinel/agent/providers/__init__.py`:
```python
from sentinel.agent.providers.anthropic_provider import AnthropicAdapter
from sentinel.agent.providers.base import ProviderAdapter
from sentinel.agent.providers.gemini_provider import GeminiAdapter
from sentinel.agent.providers.openai_provider import OpenAIAdapter


def build_adapter(provider: str, client, model: str) -> ProviderAdapter:
    if provider == "anthropic":
        return AnthropicAdapter(client, model)
    if provider == "openai":
        return OpenAIAdapter(client, model)
    if provider == "gemini":
        return GeminiAdapter(client, model)
    raise ValueError(f"Unsupported provider: {provider}")
```

- [ ] **Step 8: Run both test files to verify they pass**

Run: `uv run pytest tests/agent/test_provider_gemini.py tests/agent/test_providers_init.py -v`
Expected: PASS (7 passed)

- [ ] **Step 9: Commit**

```bash
git add sentinel/agent/providers/gemini_provider.py sentinel/agent/providers/__init__.py tests/agent/test_provider_gemini.py tests/agent/test_providers_init.py
git commit -m "feat: add Gemini tool-calling adapter and build_adapter factory"
```

---

## Task 8: Loop orchestrator

**Files:**
- Create: `sentinel/agent/loop.py`
- Test: `tests/agent/test_loop.py`

**Interfaces:**
- Consumes: `sentinel.agent.types.{AgentResponse, Message, ToolCall}` (Task 1); `sentinel.agent.tools.{TOOL_REGISTRY, ToolContext, ToolError}` (Tasks 2-4); `sentinel.agent.providers.base.ProviderAdapter` (Task 5).
- Produces: `LoopEvent(type: str, data: dict)`, `run_agent_loop(goal: str, provider: ProviderAdapter, ctx: ToolContext, request_approval: Callable[[ToolCall], str], max_iterations: int = 10) -> Iterator[LoopEvent]`. Event types: `"thinking"`, `"tool_call"`, `"tool_result"`, `"edit_diff"`, `"loop_done"`.

- [ ] **Step 1: Write the failing tests**

`tests/agent/test_loop.py`:
```python
from pathlib import Path
from unittest.mock import MagicMock

from sentinel.agent.loop import run_agent_loop
from sentinel.agent.tools import ToolContext
from sentinel.agent.types import AgentResponse, ToolCall


class FakeProvider:
    """Scripted provider: returns each response in `responses` in order,
    one per converse() call, ignoring the actual messages passed in."""

    def __init__(self, responses: list[AgentResponse]):
        self._responses = list(responses)
        self.calls = 0

    def converse(self, messages, tools, system):
        self.calls += 1
        return self._responses[self.calls - 1]


def make_ctx(tmp_path: Path) -> ToolContext:
    return ToolContext(repo_root=tmp_path, cognee_client=MagicMock(), dataset="sentinel")


def test_loop_ends_immediately_on_final_text_response():
    provider = FakeProvider([AgentResponse(text="Nothing to fix.")])
    events = list(run_agent_loop("check the repo", provider, make_ctx(Path(".")), request_approval=lambda c: "allow"))

    assert events[-1].type == "loop_done"
    assert events[-1].data == {"success": True, "summary": "Nothing to fix."}
    assert provider.calls == 1


def test_loop_executes_auto_approved_tool_and_continues(tmp_path):
    (tmp_path / "a.py").write_text("x = 1\n", encoding="utf-8")
    call = ToolCall(id="c1", name="read_file", args={"path": "a.py"})
    provider = FakeProvider([
        AgentResponse(tool_calls=[call]),
        AgentResponse(text="Done reading."),
    ])
    events = list(run_agent_loop("read a.py", provider, make_ctx(tmp_path), request_approval=lambda c: "allow"))

    tool_call_events = [e for e in events if e.type == "tool_call"]
    tool_result_events = [e for e in events if e.type == "tool_result"]
    assert tool_call_events[0].data == {"id": "c1", "name": "read_file", "args": {"path": "a.py"}, "needs_approval": False}
    assert "1\tx = 1" in tool_result_events[0].data["output"]
    assert events[-1].data["success"] is True


def test_loop_blocks_edit_file_on_approval_and_reports_needs_approval_true(tmp_path):
    (tmp_path / "a.py").write_text("x = 1\n", encoding="utf-8")
    call = ToolCall(id="c1", name="edit_file", args={"path": "a.py", "old_string": "x = 1", "new_string": "x = 2"})
    provider = FakeProvider([
        AgentResponse(tool_calls=[call]),
        AgentResponse(text="Fixed."),
    ])
    approvals_requested = []

    def approve(tool_call):
        approvals_requested.append(tool_call.id)
        return "allow"

    events = list(run_agent_loop("fix a.py", provider, make_ctx(tmp_path), request_approval=approve))

    assert approvals_requested == ["c1"]
    tool_call_event = next(e for e in events if e.type == "tool_call")
    assert tool_call_event.data["needs_approval"] is True
    assert (tmp_path / "a.py").read_text(encoding="utf-8") == "x = 2\n"
    edit_diff_events = [e for e in events if e.type == "edit_diff"]
    assert edit_diff_events[0].data["file"] == "a.py"


def test_loop_denied_tool_feeds_denial_back_and_continues(tmp_path):
    (tmp_path / "a.py").write_text("x = 1\n", encoding="utf-8")
    call = ToolCall(id="c1", name="edit_file", args={"path": "a.py", "old_string": "x = 1", "new_string": "x = 2"})
    provider = FakeProvider([
        AgentResponse(tool_calls=[call]),
        AgentResponse(text="Stopped, edit was denied."),
    ])
    events = list(run_agent_loop("fix a.py", provider, make_ctx(tmp_path), request_approval=lambda c: "deny"))

    result_event = next(e for e in events if e.type == "tool_result")
    assert result_event.data["output"] == "User denied this action."
    assert (tmp_path / "a.py").read_text(encoding="utf-8") == "x = 1\n"
    assert events[-1].data["success"] is True


def test_loop_allow_rest_of_loop_skips_further_approval_prompts(tmp_path):
    (tmp_path / "a.py").write_text("x = 1\n", encoding="utf-8")
    (tmp_path / "b.py").write_text("y = 1\n", encoding="utf-8")
    call1 = ToolCall(id="c1", name="edit_file", args={"path": "a.py", "old_string": "x = 1", "new_string": "x = 2"})
    call2 = ToolCall(id="c2", name="edit_file", args={"path": "b.py", "old_string": "y = 1", "new_string": "y = 2"})
    provider = FakeProvider([
        AgentResponse(tool_calls=[call1]),
        AgentResponse(tool_calls=[call2]),
        AgentResponse(text="Both fixed."),
    ])
    approval_calls = []

    def approve(tool_call):
        approval_calls.append(tool_call.id)
        return "allow_rest_of_loop"

    events = list(run_agent_loop("fix both", provider, make_ctx(tmp_path), request_approval=approve))

    assert approval_calls == ["c1"]  # only asked once
    tool_call_events = [e for e in events if e.type == "tool_call"]
    assert tool_call_events[1].data["needs_approval"] is False
    assert (tmp_path / "b.py").read_text(encoding="utf-8") == "y = 2\n"


def test_loop_stops_after_max_iterations_without_resolution(tmp_path):
    call = ToolCall(id="c1", name="read_file", args={"path": "a.py"})
    (tmp_path / "a.py").write_text("x = 1\n", encoding="utf-8")
    provider = FakeProvider([AgentResponse(tool_calls=[call])] * 3)

    events = list(run_agent_loop(
        "loop forever", provider, make_ctx(tmp_path), request_approval=lambda c: "allow", max_iterations=3,
    ))

    assert provider.calls == 3
    assert events[-1].type == "loop_done"
    assert events[-1].data["success"] is False
    assert "3 iterations" in events[-1].data["summary"]


def test_loop_tool_error_is_fed_back_as_error_result(tmp_path):
    call = ToolCall(id="c1", name="read_file", args={"path": "missing.py"})
    provider = FakeProvider([
        AgentResponse(tool_calls=[call]),
        AgentResponse(text="Could not find the file."),
    ])
    events = list(run_agent_loop("read missing.py", provider, make_ctx(tmp_path), request_approval=lambda c: "allow"))

    result_event = next(e for e in events if e.type == "tool_result")
    assert "Error" in result_event.data["output"]
    assert "No such file" in result_event.data["output"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/agent/test_loop.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'sentinel.agent.loop'`

- [ ] **Step 3: Write the implementation**

`sentinel/agent/loop.py`:
```python
from dataclasses import dataclass
from typing import Callable, Iterator

from sentinel.agent.providers.base import ProviderAdapter
from sentinel.agent.tools import TOOL_REGISTRY, ToolContext, ToolError
from sentinel.agent.types import Message, ToolCall

MAX_ITERATIONS = 10

SYSTEM_PROMPT = (
    "You are Kiwi's QA agent. You diagnose and fix a failing test by calling tools: "
    "run_tests, read_file, search_code, edit_file, shell, recall, remember. "
    "Investigate before editing. When you believe the issue is fixed, call run_tests "
    "to verify, then respond with plain text summarizing what you found and changed. "
    "Only call edit_file when you are confident in the fix."
)


@dataclass
class LoopEvent:
    type: str
    data: dict


def run_agent_loop(
    goal: str,
    provider: ProviderAdapter,
    ctx: ToolContext,
    request_approval: Callable[[ToolCall], str],
    max_iterations: int = MAX_ITERATIONS,
) -> Iterator[LoopEvent]:
    messages: list[Message] = [Message(role="user", content=goal)]
    tool_schemas = [spec.schema for spec in TOOL_REGISTRY.values()]
    auto_approve = False

    for iteration in range(1, max_iterations + 1):
        yield LoopEvent("thinking", {"text": f"Step {iteration}: reasoning..."})
        response = provider.converse(messages, tools=tool_schemas, system=SYSTEM_PROMPT)

        if response.is_final:
            yield LoopEvent("loop_done", {"success": True, "summary": response.text})
            return

        messages.append(Message(role="assistant", tool_calls=response.tool_calls))

        for call in response.tool_calls:
            spec = TOOL_REGISTRY[call.name]
            needs_approval = spec.requires_approval and not auto_approve
            yield LoopEvent("tool_call", {
                "id": call.id, "name": call.name, "args": call.args, "needs_approval": needs_approval,
            })

            if needs_approval:
                decision = request_approval(call)
                if decision == "allow_rest_of_loop":
                    auto_approve = True
                elif decision == "deny":
                    result_text = "User denied this action."
                    messages.append(Message(role="tool", tool_call_id=call.id, tool_name=call.name, content=result_text))
                    yield LoopEvent("tool_result", {"id": call.id, "output": result_text})
                    continue

            try:
                result_text = spec.run(ctx, call.args)
            except ToolError as exc:
                result_text = f"Error: {exc}"

            messages.append(Message(role="tool", tool_call_id=call.id, tool_name=call.name, content=result_text))
            yield LoopEvent("tool_result", {"id": call.id, "output": result_text})

            if call.name == "edit_file" and not result_text.startswith("Error"):
                yield LoopEvent("edit_diff", {"id": call.id, "file": call.args.get("path"), "diff": result_text})

    yield LoopEvent("loop_done", {
        "success": False,
        "summary": f"Stopped after {max_iterations} iterations without resolving. Review the tool history above.",
    })
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/agent/test_loop.py -v`
Expected: PASS (7 passed)

- [ ] **Step 5: Commit**

```bash
git add sentinel/agent/loop.py tests/agent/test_loop.py
git commit -m "feat: add agent loop orchestrator with approval gating and iteration budget"
```

---

## Task 9: FastAPI streaming bridge and endpoints

**Files:**
- Create: `app/agent_bridge.py`
- Modify: `app/main.py`
- Test: `app/tests/test_agent_endpoints.py`

**Interfaces:**
- Consumes: `sentinel.agent.loop.{run_agent_loop, LoopEvent}` (Task 8); `sentinel.agent.tools.ToolContext` (Task 2); `sentinel.agent.providers.build_adapter` (Task 7); `sentinel.config.load_settings`, `sentinel.cognee_client.CogneeClient`, `sentinel.llm_client.get_llm_client` (existing).
- Produces: `AgentRun(provider, ctx, goal)` with `.loop_id`, `.start()`, `.next_event(timeout)`, `.resolve_approval(tool_call_id, decision) -> bool`; module-level `RUNS: dict[str, AgentRun]`; endpoints `POST /kiwi/agent/start`, `POST /kiwi/agent/approve`.

- [ ] **Step 1: Write the failing endpoint tests**

`app/tests/test_agent_endpoints.py`:
```python
import json
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient

from app.main import app
from sentinel.agent.types import AgentResponse


def test_agent_start_streams_thinking_and_loop_done_for_a_trivial_goal():
    fake_settings = MagicMock(dataset="sentinel", base_url="https://t", api_key="k", tenant_id="tid")
    with patch("app.main.load_settings", return_value=fake_settings), \
         patch("app.main.CogneeClient"), \
         patch("app.main.get_llm_client", return_value=("anthropic", MagicMock(), "claude-opus-4-8")), \
         patch("app.main.build_adapter") as mock_build_adapter:
        mock_build_adapter.return_value.converse.return_value = AgentResponse(text="Nothing to fix.")

        client = TestClient(app)
        with client.stream("POST", "/kiwi/agent/start", json={"goal": "check the repo"}) as resp:
            lines = [json.loads(line) for line in resp.iter_lines() if line]

    types_seen = [line["type"] for line in lines]
    assert "loop_start" in types_seen
    assert "thinking" in types_seen
    assert types_seen[-1] == "loop_done"
    assert lines[-1]["success"] is True


def test_agent_start_returns_400_when_no_llm_configured():
    fake_settings = MagicMock(dataset="sentinel")
    with patch("app.main.load_settings", return_value=fake_settings), \
         patch("app.main.CogneeClient"), \
         patch("app.main.get_llm_client", return_value=(None, None, None)):
        client = TestClient(app)
        resp = client.post("/kiwi/agent/start", json={"goal": "check the repo"})

    assert resp.status_code == 400


def test_agent_approve_returns_404_for_unknown_loop():
    client = TestClient(app)
    resp = client.post("/kiwi/agent/approve", json={"loop_id": "nope", "tool_call_id": "c1", "decision": "allow"})
    assert resp.status_code == 404
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest app/tests/test_agent_endpoints.py -v`
Expected: FAIL with `404 Not Found` for `/kiwi/agent/start` (route doesn't exist yet).

- [ ] **Step 3: Write the bridge implementation**

`app/agent_bridge.py`:
```python
import queue
import threading
import uuid
from typing import Optional

from sentinel.agent.loop import run_agent_loop
from sentinel.agent.providers.base import ProviderAdapter
from sentinel.agent.tools import ToolContext

_SENTINEL = object()


class AgentRun:
    """Bridges the synchronous agent loop generator to an async NDJSON stream,
    and brokers approval decisions posted from a separate HTTP request."""

    def __init__(self, provider: ProviderAdapter, ctx: ToolContext, goal: str):
        self.loop_id = uuid.uuid4().hex
        self._events: "queue.Queue" = queue.Queue()
        self._approvals: dict[str, "queue.Queue"] = {}
        self._provider = provider
        self._ctx = ctx
        self._goal = goal

    def _request_approval(self, tool_call) -> str:
        approval_queue: "queue.Queue" = queue.Queue()
        self._approvals[tool_call.id] = approval_queue
        return approval_queue.get()

    def resolve_approval(self, tool_call_id: str, decision: str) -> bool:
        approval_queue = self._approvals.get(tool_call_id)
        if approval_queue is None:
            return False
        approval_queue.put(decision)
        return True

    def _worker(self):
        try:
            for event in run_agent_loop(self._goal, self._provider, self._ctx, self._request_approval):
                self._events.put(event)
        finally:
            self._events.put(_SENTINEL)

    def start(self):
        threading.Thread(target=self._worker, daemon=True).start()

    def next_event(self, timeout: Optional[float] = None):
        item = self._events.get(timeout=timeout)
        return None if item is _SENTINEL else item


RUNS: dict[str, AgentRun] = {}
```

- [ ] **Step 4: Wire the endpoints into app/main.py**

Add these imports near the top of `app/main.py`, alongside the existing `from sentinel...` imports:
```python
from pathlib import Path

from app.agent_bridge import RUNS, AgentRun
from sentinel.agent.providers import build_adapter
from sentinel.agent.tools import ToolContext
```

Add these request models near the other `BaseModel` classes in `app/main.py` (after `class FlakyReq(BaseModel): ...`):
```python
class AgentStartReq(BaseModel):
    goal: str = ""
    path: str = ""


class AgentApproveReq(BaseModel):
    loop_id: str
    tool_call_id: str
    decision: str
```

Add these endpoints near the end of `app/main.py`, after the `kiwi_login` endpoint:
```python
@app.post("/kiwi/agent/start")
def agent_start(req: AgentStartReq):
    settings = load_settings()
    client = CogneeClient(settings)
    provider_name, llm, model = get_llm_client()
    if not llm:
        raise HTTPException(status_code=400, detail="No LLM configured. Run /login first.")

    adapter = build_adapter(provider_name, llm, model)
    ctx = ToolContext(repo_root=Path.cwd(), cognee_client=client, dataset=settings.dataset)
    goal = f"Fix the failing test at {req.path}" if req.path else req.goal
    run = AgentRun(adapter, ctx, goal)
    RUNS[run.loop_id] = run
    run.start()

    def generator():
        yield json.dumps({"type": "loop_start", "loop_id": run.loop_id}) + "\n"
        try:
            while True:
                event = run.next_event(timeout=120)
                if event is None:
                    break
                yield json.dumps({"type": event.type, **event.data}) + "\n"
                if event.type == "loop_done":
                    break
        finally:
            RUNS.pop(run.loop_id, None)

    return StreamingResponse(generator(), media_type="text/event-stream")


@app.post("/kiwi/agent/approve")
def agent_approve(req: AgentApproveReq):
    run = RUNS.get(req.loop_id)
    if not run or not run.resolve_approval(req.tool_call_id, req.decision):
        raise HTTPException(status_code=404, detail="No pending approval for that tool_call_id.")
    return {"status": "ok"}
```

- [ ] **Step 5: Run test to verify it passes**

Run: `uv run pytest app/tests/test_agent_endpoints.py -v`
Expected: PASS (3 passed)

- [ ] **Step 6: Run the full backend test suite to check for regressions**

Run: `uv run pytest tests/ app/tests/ -q`
Expected: all tests pass (no regressions in existing suites)

- [ ] **Step 7: Commit**

```bash
git add app/agent_bridge.py app/main.py app/tests/test_agent_endpoints.py
git commit -m "feat: add /kiwi/agent/start and /kiwi/agent/approve streaming endpoints"
```

---

## Task 10: NL router `fix` action + UI wiring

**Files:**
- Modify: `app/main.py`
- Modify: `kiwi-ui/index.tsx`

**Interfaces:**
- Consumes: `/kiwi/agent/start`, `/kiwi/agent/approve` (Task 9).
- Produces: `fix` action in the `/kiwi/query` system prompt's action taxonomy; `/fix [path]` REPL command; `tool_call`/`edit_diff`/approval-prompt rendering in the Ink UI.

- [ ] **Step 1: Add the `fix` action to the NL router's system prompt**

In `app/main.py`, inside `kiwi_query`'s `generator()`, the `system_instruction` string currently lists actions 1-11 ending with `"11. 'help': ..."`. Change the numbered action list to add a 12th entry and renumber `help` is unaffected since it's already last — insert directly after action `7. 'flaky'` is not required; simplest is to append after item 11:

Find this block in `app/main.py`:
```python
                "10. 'session': Show active session logs.\n"
                "11. 'help': Show the list of available commands.\n"
                "\n"
```

Replace it with:
```python
                "10. 'session': Show active session logs.\n"
                "11. 'help': Show the list of available commands.\n"
                "12. 'fix': Autonomously diagnose and fix a failing test via a multi-step agent loop. Args: 'path' (string, path to the failing test, optional).\n"
                "\n"
```

- [ ] **Step 2: Manually verify the prompt change**

Run: `uv run python -c "import app.main"`
Expected: no import errors (syntax check only — the string is only exercised at request time).

- [ ] **Step 3: Add `/fix` handling and streaming renderer state to the UI**

In `kiwi-ui/index.tsx`, add a new branch to `handleSubmit`'s command dispatch, alongside the existing `else if (text.startsWith('/resolve'))` branch (before the final natural-language `else` branch):
```tsx
      } else if (text.startsWith('/fix')) {
        const testPath = text.substring(4).trim()
        await runAgentLoop(testPath ? { path: testPath } : { goal: 'Fix the currently failing tests.' }, assistantMsgId)
```

Add a new `runAgentLoop` function inside the `App` component, above `handleSubmit`:
```tsx
  const runAgentLoop = useCallback(async (
    payload: { path?: string, goal?: string },
    assistantMsgId: string
  ) => {
    const assistantMsg: Message = {
      id: assistantMsgId,
      role: 'assistant',
      content: [{ type: 'thinking', text: 'Starting agent loop...', collapsed: false }]
    }
    setMessages(prev => [...prev, assistantMsg])

    let loopId = ''
    const response = await fetch(`${BACKEND_URL}/kiwi/agent/start`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload)
    })
    if (!response.ok) {
      const detail = await response.json().catch(() => ({ detail: response.statusText }))
      setMessages(prev => [...prev, { id: assistantMsgId, role: 'assistant', content: `Agent error: ${detail.detail}` }])
      return
    }

    const reader = response.body?.getReader()
    const decoder = new TextDecoder()
    if (!reader) return
    let buffer = ''
    while (true) {
      const { done, value } = await reader.read()
      if (done) break
      buffer += decoder.decode(value, { stream: true })
      const lines = buffer.split('\n')
      buffer = lines.pop() || ''
      for (const line of lines) {
        if (!line.trim()) continue
        const event = JSON.parse(line)
        if (event.type === 'loop_start') {
          loopId = event.loop_id
        } else if (event.type === 'thinking') {
          appendBlock(assistantMsgId, { type: 'thinking', text: event.text, collapsed: false })
        } else if (event.type === 'tool_call') {
          appendBlock(assistantMsgId, {
            type: 'tool_call', id: event.id, name: event.name, args: event.args,
            needsApproval: event.needs_approval, collapsed: false
          })
          if (event.needs_approval) {
            const decision = await promptApproval(event.name, event.args)
            await axios.post(`${BACKEND_URL}/kiwi/agent/approve`, {
              loop_id: loopId, tool_call_id: event.id, decision
            })
          }
        } else if (event.type === 'tool_result') {
          appendBlock(assistantMsgId, { type: 'tool_result', id: event.id, output: event.output })
        } else if (event.type === 'edit_diff') {
          appendBlock(assistantMsgId, { type: 'edit_diff', id: event.id, file: event.file, diff: event.diff })
        } else if (event.type === 'loop_done') {
          appendBlock(assistantMsgId, { type: 'text', text: event.summary })
        }
      }
    }
  }, [])
```

Add the `appendBlock` helper above `runAgentLoop`:
```tsx
  const appendBlock = useCallback((assistantMsgId: string, block: any) => {
    setMessages(prev => prev.map(m => {
      if (m.id === assistantMsgId && Array.isArray(m.content)) {
        return { ...m, content: [...m.content, block] }
      }
      return m
    }))
  }, [])
```

Add the `promptApproval` helper (uses the existing `useInput` pattern for a blocking y/n/a prompt — matches the ESC/Ctrl+C handling already in the component) above `appendBlock`:
```tsx
  const promptApproval = useCallback((name: string, args: any): Promise<string> => {
    return new Promise(resolve => {
      setMessages(prev => [...prev, {
        id: Math.random().toString(36).substring(7),
        role: 'assistant',
        content: `Approve ${name}(${JSON.stringify(args)})? [y]es / [n]o / [a]llow rest of run`
      }])
      pendingApprovalRef.current = (input: string) => {
        const v = input.trim().toLowerCase()
        if (v === 'y' || v === 'yes') resolve('allow')
        else if (v === 'a' || v === 'allow') resolve('allow_rest_of_loop')
        else resolve('deny')
        pendingApprovalRef.current = null
      }
    })
  }, [])
```

Add the ref near the other `useRef` in the component:
```tsx
  const pendingApprovalRef = React.useRef<((input: string) => void) | null>(null)
```

At the top of `handleSubmit`, before the existing login-state check, intercept input when an approval is pending:
```tsx
    if (pendingApprovalRef.current) {
      pendingApprovalRef.current(text)
      return
    }
```

Register the `/fix` command in the `commands` prop passed to `<REPL>`, alongside the existing `test` entry:
```tsx
        { name: 'fix', description: 'Autonomously diagnose and fix a failing test', onExecute: () => handleSubmit('/fix') },
```

Add rendering for the new block types in `customRenderMessage`'s `renderContent`, alongside the existing `thinking`/`text` cases:
```tsx
            if (c.type === 'tool_call') {
              return (
                <Box key={i} marginY={1}>
                  <Text dimColor>{`→ ${c.name}(${JSON.stringify(c.args)})${c.needsApproval ? ' [awaiting approval]' : ''}`}</Text>
                </Box>
              );
            }
            if (c.type === 'tool_result') {
              return (
                <Box key={i} marginLeft={2}>
                  <Text dimColor italic>{c.output}</Text>
                </Box>
              );
            }
            if (c.type === 'edit_diff') {
              return (
                <Box key={i} flexDirection="column" marginY={1} borderStyle="round" borderColor="gray">
                  <Text dimColor>{c.file}</Text>
                  {c.diff.split('\n').map((line: string, j: number) => (
                    <Text key={j} color={line.startsWith('+') ? 'green' : line.startsWith('-') ? 'red' : undefined}>
                      {line}
                    </Text>
                  ))}
                </Box>
              );
            }
```

Add `/fix` to the `/help` output list in `app/main.py`... *(N/A — help text lives client-side)*. Add it to the client-side help list in `kiwi-ui/index.tsx` instead, in the `helpText` array next to `/resolve`:
```tsx
          '  /fix [path]             Autonomously diagnose and fix a failing test',
```

- [ ] **Step 4: Manually verify the UI end-to-end**

Run the backend: `uv run uvicorn app.main:app --port 8000` (background/separate terminal).
Run the CLI: `pnpm kiwi` (or `.\kiwi` per README).
In the REPL:
1. `/login` with valid Cognee + LLM credentials.
2. Introduce a deliberately failing test (e.g. temporarily break an assertion in `app/tests/test_webhook.py`).
3. Run `/fix app/tests/test_webhook.py` and confirm: thinking blocks stream, a `tool_call` block appears for `run_tests`/`read_file`/`search_code` without prompting, an `edit_file` or `shell` call prompts `Approve ...? [y]es / [n]o / [a]llow rest of run`, typing `y` applies the edit and the diff renders, and the loop eventually emits a final summary.
4. Revert the deliberately-broken test change.

Expected: the full run→inspect→edit→rerun cycle is visible in the terminal and the approval prompt blocks correctly until answered.

- [ ] **Step 5: Commit**

```bash
git add app/main.py kiwi-ui/index.tsx
git commit -m "feat: wire /fix command and NL fix action through to the agent loop UI"
```

---

## Task 11: Flip docs from planned to shipped

**Files:**
- Modify: `README.md`
- Modify: `docs/commands.md`
- Modify: `docs/subsystems.md`
- Modify: `docs/tools.md`
- Modify: `docs/exploration_guide.md`

**Interfaces:**
- Consumes: nothing new — this task only edits prose/markers left by the design-phase doc updates (`docs/superpowers/specs/2026-07-20-agentic-qa-harness-design.md` §"Roadmap: Agentic QA Harness" additions from that commit).

- [ ] **Step 1: Update README.md**

In `README.md`, change:
```markdown
| `/fix [path]` *(planned)* | Runs a multi-step agentic loop to autonomously diagnose and fix a failing test. |
```
to:
```markdown
| `/fix [path]` | Runs a multi-step agentic loop to autonomously diagnose and fix a failing test. |
```

Change the "Roadmap: Agentic QA Harness" section heading and body from future tense to a short shipped-feature note:
```markdown
## Agentic QA Harness

Kiwi's `/fix [path]` command (and natural-language requests like "fix the failing payment test") run a multi-step agentic loop — run test → inspect → search code → edit → rerun → repeat — instead of a one-shot suggestion. File edits and shell commands require per-action approval, and the loop stops after 10 iterations if unresolved. See the design at [docs/superpowers/specs/2026-07-20-agentic-qa-harness-design.md](docs/superpowers/specs/2026-07-20-agentic-qa-harness-design.md).
```

- [ ] **Step 2: Update docs/commands.md**

Change the summary table row:
```markdown
| `/fix [path]` *(planned)* | Runs the multi-step agentic loop to autonomously diagnose and fix a failing test | `/fix tests/test_login.py` |
```
to:
```markdown
| [`/fix [path]`](#/fix-path) | Runs the multi-step agentic loop to autonomously diagnose and fix a failing test | `/fix tests/test_login.py` |
```

Change the detailed section heading:
```markdown
### `/fix [path]` *(planned — not yet implemented)*
```
to:
```markdown
### `/fix [path]`
```

- [ ] **Step 3: Update docs/subsystems.md**

Change the section heading:
```markdown
## 5. Agentic QA Harness Subsystem *(planned — not yet implemented)*
**Location (planned):** `sentinel/agent/`
```
to:
```markdown
## 5. Agentic QA Harness Subsystem
**Location:** [sentinel/agent/](../sentinel/agent/)
```

- [ ] **Step 4: Update docs/tools.md**

Change the section heading:
```markdown
## 4. Agentic Tool Registry *(planned — not yet implemented)*
**Location (planned):** [sentinel/agent/tools.py](superpowers/specs/2026-07-20-agentic-qa-harness-design.md)
```
to:
```markdown
## 4. Agentic Tool Registry
**Location:** [sentinel/agent/tools.py](../sentinel/agent/tools.py)
```

- [ ] **Step 5: Update docs/exploration_guide.md**

Change the orientation-map row:
```markdown
| **Agentic QA Harness** *(planned)* | Multi-step tool-use loop (run → inspect → search → edit → rerun) for autonomously fixing failing tests | `sentinel/agent/` — see [design doc](superpowers/specs/2026-07-20-agentic-qa-harness-design.md) |
```
to:
```markdown
| **Agentic QA Harness** | Multi-step tool-use loop (run → inspect → search → edit → rerun) for autonomously fixing failing tests | [sentinel/agent/](../sentinel/agent/) |
```

Change the "Multi-Step Agentic Loop *(planned)*" heading:
```markdown
### 3. Multi-Step Agentic Loop *(planned)*
`/kiwi/query` today is one-shot: one LLM call in, one action or text reply out. The planned `/fix` agentic harness replaces that with an iterate-until-done loop
```
to:
```markdown
### 3. Multi-Step Agentic Loop
The `/fix` agentic harness runs an iterate-until-done loop
```

- [ ] **Step 6: Run the full test suite one more time**

Run: `uv run pytest tests/ app/tests/ -q`
Expected: all tests pass.

- [ ] **Step 7: Commit**

```bash
git add README.md docs/commands.md docs/subsystems.md docs/tools.md docs/exploration_guide.md
git commit -m "docs: mark the agentic QA harness as shipped"
```

---

## Task 12: Integration test for a live `/fix` run

**Files:**
- Create: `tests/test_integration_agent_loop.py`

**Interfaces:**
- Consumes: `sentinel.agent.loop.run_agent_loop` (Task 8); `sentinel.agent.providers.build_adapter` (Task 7); `sentinel.agent.tools.ToolContext` (Task 2); `sentinel.cognee_client.CogneeClient` (existing).

Matches the existing live-service integration pattern in `tests/test_integration_cloud.py` — marked `@pytest.mark.integration`, excluded by default (`addopts = "-m 'not integration'"` in `pyproject.toml`), run explicitly. Requires real `COGNEE_BASE_URL`/`COGNEE_API_KEY`/`COGNEE_TENANT_ID` and `ANTHROPIC_API_KEY` in the environment.

- [ ] **Step 1: Write the integration test**

`tests/test_integration_agent_loop.py`:
```python
import time
from pathlib import Path

import anthropic
import pytest

from sentinel.agent.loop import run_agent_loop
from sentinel.agent.providers import build_adapter
from sentinel.agent.tools import ToolContext
from sentinel.cognee_client import CogneeClient
from sentinel.config import load_settings

pytestmark = pytest.mark.integration

DATASET = f"sentinel_smoke_{int(time.time())}"


def test_fix_loop_reads_a_deliberately_broken_file_and_edits_it(tmp_path):
    broken = tmp_path / "calc.py"
    broken.write_text("def add(a, b):\n    return a - b  # bug: should be a + b\n", encoding="utf-8")

    settings = load_settings()
    cognee_client = CogneeClient(settings)
    ctx = ToolContext(repo_root=tmp_path, cognee_client=cognee_client, dataset=DATASET)
    provider = build_adapter("anthropic", anthropic.Anthropic(), "claude-opus-4-8")

    def auto_approve(tool_call):
        return "allow"

    events = list(run_agent_loop(
        "Read calc.py, then fix the bug in add() so it returns a + b instead of a - b.",
        provider, ctx, request_approval=auto_approve, max_iterations=6,
    ))

    try:
        assert any(e.type == "loop_done" for e in events)
        updated = broken.read_text(encoding="utf-8")
        assert "a + b" in updated
    finally:
        cognee_client.forget(dataset=DATASET)
```

- [ ] **Step 2: Run the integration test explicitly**

Run: `uv run pytest tests/test_integration_agent_loop.py -v -m integration`
Expected: PASS — `calc.py` is edited so `add()` returns `a + b`. If it fails, inspect which tool call the model made (add a temporary `print(event)` in the loop) rather than assuming the adapter is broken — model behavior on a live call is not fully deterministic.

- [ ] **Step 3: Run the full non-integration suite once more to confirm no regressions**

Run: `uv run pytest tests/ app/tests/ -q`
Expected: all tests pass (integration test excluded by default `addopts`).

- [ ] **Step 4: Commit**

```bash
git add tests/test_integration_agent_loop.py
git commit -m "test: add live integration test for the /fix agent loop"
```
