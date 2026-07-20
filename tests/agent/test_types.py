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
