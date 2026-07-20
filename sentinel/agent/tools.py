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
