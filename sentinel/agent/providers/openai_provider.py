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
        kwargs = {"model": self.model, "messages": openai_messages}
        if openai_tools:
            kwargs["tools"] = openai_tools
        response = self.client.chat.completions.create(**kwargs)
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
