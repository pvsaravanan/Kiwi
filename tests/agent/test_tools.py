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


def test_search_code_glob_cannot_escape_repo_root(tmp_path):
    outside = tmp_path.parent / f"outside_{tmp_path.name}.txt"
    outside.write_text("TOTALLY_SECRET_MARKER\n", encoding="utf-8")
    try:
        (tmp_path / "a.py").write_text("nothing interesting\n", encoding="utf-8")
        ctx = make_ctx(tmp_path)
        out = TOOL_REGISTRY["search_code"].run(
            ctx, {"pattern": "TOTALLY_SECRET_MARKER", "glob": "../*.txt"}
        )
        assert "TOTALLY_SECRET_MARKER" not in out
        assert out == "No matches found."
    finally:
        outside.unlink(missing_ok=True)


def test_read_file_and_search_code_are_not_approval_gated():
    assert TOOL_REGISTRY["read_file"].requires_approval is False
    assert TOOL_REGISTRY["search_code"].requires_approval is False


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
