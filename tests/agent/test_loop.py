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


def test_loop_unrecognized_decision_is_treated_as_denial(tmp_path):
    (tmp_path / "a.py").write_text("x = 1\n", encoding="utf-8")
    call = ToolCall(id="c1", name="edit_file", args={"path": "a.py", "old_string": "x = 1", "new_string": "x = 2"})
    provider = FakeProvider([
        AgentResponse(tool_calls=[call]),
        AgentResponse(text="Stopped, edit was denied."),
    ])
    events = list(run_agent_loop("fix a.py", provider, make_ctx(tmp_path), request_approval=lambda c: "maybe"))

    result_event = next(e for e in events if e.type == "tool_result")
    assert result_event.data["output"] == "User denied this action."
    assert (tmp_path / "a.py").read_text(encoding="utf-8") == "x = 1\n"
    assert events[-1].data["success"] is True


def test_loop_stops_immediately_after_run_tests_reports_all_passed(tmp_path, monkeypatch):
    import subprocess as sp

    (tmp_path / "junit_report.xml").write_text("<testsuite></testsuite>", encoding="utf-8")

    def fake_run(*args, **kwargs):
        return sp.CompletedProcess(args=args, returncode=0, stdout="", stderr="")

    monkeypatch.setattr("sentinel.agent.tools.subprocess.run", fake_run)

    call = ToolCall(id="c1", name="run_tests", args={})
    # A second scripted response the loop must never reach if it stops deterministically.
    provider = FakeProvider([
        AgentResponse(tool_calls=[call]),
        AgentResponse(tool_calls=[ToolCall(id="c2", name="shell", args={"command": "ls"})]),
    ])

    events = list(run_agent_loop(
        "fix and verify", provider, make_ctx(tmp_path), request_approval=lambda c: "allow",
    ))

    assert provider.calls == 1
    assert events[-1].type == "loop_done"
    assert events[-1].data["success"] is True
    assert not any(e.type == "tool_call" and e.data["name"] == "shell" for e in events)


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
