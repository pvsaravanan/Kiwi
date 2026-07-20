from sentinel.agent.types import AgentResponse, Message, ToolCall, ToolSchema


class AnthropicAdapter:
    def __init__(self, client, model: str):
        self.client = client
        self.model = model

    def converse(self, messages: list[Message], tools: list[ToolSchema], system: str) -> AgentResponse:
        anthropic_tools = [
            {"name": t.name, "description": t.description, "input_schema": t.parameters}
            for t in tools
        ]
        anthropic_messages = [self._to_anthropic_message(m) for m in messages]
        response = self.client.messages.create(
            model=self.model, max_tokens=2048, system=system,
            tools=anthropic_tools, messages=anthropic_messages,
        )
        tool_calls = [
            ToolCall(id=block.id, name=block.name, args=block.input)
            for block in response.content if block.type == "tool_use"
        ]
        if tool_calls:
            return AgentResponse(tool_calls=tool_calls)
        text = "".join(block.text for block in response.content if block.type == "text")
        return AgentResponse(text=text)

    @staticmethod
    def _to_anthropic_message(m: Message) -> dict:
        if m.role == "tool":
            return {"role": "user", "content": [
                {"type": "tool_result", "tool_use_id": m.tool_call_id, "content": m.content},
            ]}
        if m.role == "assistant" and m.tool_calls:
            return {"role": "assistant", "content": [
                {"type": "tool_use", "id": c.id, "name": c.name, "input": c.args}
                for c in m.tool_calls
            ]}
        return {"role": m.role, "content": m.content}
