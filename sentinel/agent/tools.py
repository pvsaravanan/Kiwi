import difflib
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from sentinel.agent.types import ToolSchema
from sentinel.cognee_client import CogneeClient
from sentinel.ingest import process_report


class ToolError(RuntimeError):
    pass


# Exact string _run_tests returns on a clean pass. The loop orchestrator
# matches on this verbatim to deterministically stop once tests are green,
# rather than relying on the model to notice and stop on its own.
ALL_TESTS_PASSED = "All tests passed."


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


def _is_contained(repo_root: Path, candidate: Path) -> bool:
    try:
        candidate.resolve().relative_to(repo_root.resolve())
    except ValueError:
        return False
    return True


def _safe_path(repo_root: Path, path: str) -> Path:
    candidate = (repo_root / path).resolve()
    if not _is_contained(repo_root, candidate):
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
        if not _is_contained(ctx.repo_root, file_path):
            continue
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
        return ALL_TESTS_PASSED
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
}
