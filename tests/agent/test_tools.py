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
