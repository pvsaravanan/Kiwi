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


def test_converse_omits_tools_when_empty():
    client = MagicMock()
    client.chat.completions.create.return_value = make_text_response("ok")
    adapter = OpenAIAdapter(client, model="gpt-5.5")

    adapter.converse([Message(role="user", content="hi")], tools=[], system="sys")

    call_kwargs = client.chat.completions.create.call_args.kwargs
    assert "tools" not in call_kwargs
