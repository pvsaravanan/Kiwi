from dataclasses import dataclass
from typing import Callable, Iterator

from sentinel.agent.providers.base import ProviderAdapter
from sentinel.agent.tools import TOOL_REGISTRY, ToolContext, ToolError
from sentinel.agent.types import Message, ToolCall

MAX_ITERATIONS = 10

SYSTEM_PROMPT = (
    "You are Kiwi's QA agent. You diagnose and fix a failing test by calling tools: "
    "run_tests, read_file, search_code, edit_file, shell, recall, remember. "
    "Investigate before editing. When you believe the issue is fixed, call run_tests "
    "to verify, then respond with plain text summarizing what you found and changed. "
    "Only call edit_file when you are confident in the fix."
)


@dataclass
class LoopEvent:
    type: str
    data: dict


def run_agent_loop(
    goal: str,
    provider: ProviderAdapter,
    ctx: ToolContext,
    request_approval: Callable[[ToolCall], str],
    max_iterations: int = MAX_ITERATIONS,
) -> Iterator[LoopEvent]:
    messages: list[Message] = [Message(role="user", content=goal)]
    tool_schemas = [spec.schema for spec in TOOL_REGISTRY.values()]
    auto_approve = False

    for iteration in range(1, max_iterations + 1):
        yield LoopEvent("thinking", {"text": f"Step {iteration}: reasoning..."})
        response = provider.converse(messages, tools=tool_schemas, system=SYSTEM_PROMPT)

        if response.is_final:
            yield LoopEvent("loop_done", {"success": True, "summary": response.text})
            return

        messages.append(Message(role="assistant", tool_calls=response.tool_calls))

        for call in response.tool_calls:
            spec = TOOL_REGISTRY[call.name]
            needs_approval = spec.requires_approval and not auto_approve
            yield LoopEvent("tool_call", {
                "id": call.id, "name": call.name, "args": call.args, "needs_approval": needs_approval,
            })

            if needs_approval:
                decision = request_approval(call)
                if decision == "allow_rest_of_loop":
                    auto_approve = True
                elif decision != "allow":
                    # Fail closed: only an explicit "allow" (or a prior
                    # allow_rest_of_loop) proceeds to execution. Any other
                    # value -- "deny", a typo, garbage input -- is treated
                    # as a denial, since this is the human-approval safety
                    # boundary for risky tools like edit_file and shell.
                    result_text = "User denied this action."
                    messages.append(Message(role="tool", tool_call_id=call.id, tool_name=call.name, content=result_text))
                    yield LoopEvent("tool_result", {"id": call.id, "output": result_text})
                    continue

            try:
                result_text = spec.run(ctx, call.args)
            except ToolError as exc:
                result_text = f"Error: {exc}"

            messages.append(Message(role="tool", tool_call_id=call.id, tool_name=call.name, content=result_text))
            yield LoopEvent("tool_result", {"id": call.id, "output": result_text})

            if call.name == "edit_file" and not result_text.startswith("Error"):
                yield LoopEvent("edit_diff", {"id": call.id, "file": call.args.get("path"), "diff": result_text})

    yield LoopEvent("loop_done", {
        "success": False,
        "summary": f"Stopped after {max_iterations} iterations without resolving. Review the tool history above.",
    })
