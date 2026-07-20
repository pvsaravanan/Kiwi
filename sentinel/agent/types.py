from dataclasses import dataclass, field


@dataclass
class ToolCall:
    id: str
    name: str
    args: dict


@dataclass
class ToolSchema:
    name: str
    description: str
    parameters: dict


@dataclass
class Message:
    role: str  # "user" | "assistant" | "tool"
    content: str = ""
    tool_calls: list[ToolCall] = field(default_factory=list)
    tool_call_id: str | None = None
    tool_name: str | None = None


@dataclass
class AgentResponse:
    tool_calls: list[ToolCall] = field(default_factory=list)
    text: str = ""

    @property
    def is_final(self) -> bool:
        return not self.tool_calls
