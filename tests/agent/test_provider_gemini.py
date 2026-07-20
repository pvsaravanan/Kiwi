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
