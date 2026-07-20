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
