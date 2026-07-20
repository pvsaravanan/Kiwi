from google.genai import types

from sentinel.agent.types import AgentResponse, Message, ToolCall, ToolSchema


class GeminiAdapter:
    def __init__(self, client, model: str):
        self.client = client
        self.model = model

    def converse(self, messages: list[Message], tools: list[ToolSchema], system: str) -> AgentResponse:
        function_declarations = [
            types.FunctionDeclaration(name=t.name, description=t.description, parameters=t.parameters)
            for t in tools
        ]
        contents = [self._to_gemini_content(m) for m in messages]
        response = self.client.models.generate_content(
            model=self.model, contents=contents,
            config=types.GenerateContentConfig(
                system_instruction=system,
                tools=[types.Tool(function_declarations=function_declarations)],
            ),
        )
        parts = response.candidates[0].content.parts
        tool_calls = []
        for i, p in enumerate(parts):
            if not getattr(p, "function_call", None):
                continue
            sig = getattr(p, "thought_signature", None)
            tool_calls.append(ToolCall(
                id=str(i), name=p.function_call.name, args=dict(p.function_call.args),
                provider_data={"thought_signature": sig} if sig is not None else None,
            ))
        if tool_calls:
            return AgentResponse(tool_calls=tool_calls)
        text = "".join(p.text for p in parts if getattr(p, "text", None))
        return AgentResponse(text=text)

    @staticmethod
    def _to_gemini_content(m: Message) -> dict:
        if m.role == "tool":
            return {"role": "user", "parts": [
                {"function_response": {"name": m.tool_name, "response": {"result": m.content}}},
            ]}
        if m.role == "assistant" and m.tool_calls:
            gemini_parts = []
            for c in m.tool_calls:
                part = {"function_call": {"name": c.name, "args": c.args}}
                sig = (c.provider_data or {}).get("thought_signature")
                if sig is not None:
                    part["thought_signature"] = sig
                gemini_parts.append(part)
            return {"role": "model", "parts": gemini_parts}
        role = "model" if m.role == "assistant" else "user"
        return {"role": role, "parts": [{"text": m.content}]}
