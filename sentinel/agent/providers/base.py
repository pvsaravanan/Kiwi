from typing import Protocol

from sentinel.agent.types import AgentResponse, Message, ToolSchema


class ProviderAdapter(Protocol):
    def converse(self, messages: list[Message], tools: list[ToolSchema], system: str) -> AgentResponse: ...
