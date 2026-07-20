import queue
import threading
import uuid
from typing import Optional

from sentinel.agent.loop import run_agent_loop
from sentinel.agent.providers.base import ProviderAdapter
from sentinel.agent.tools import ToolContext

_SENTINEL = object()


class AgentRun:
    """Bridges the synchronous agent loop generator to an async NDJSON stream,
    and brokers approval decisions posted from a separate HTTP request."""

    def __init__(self, provider: ProviderAdapter, ctx: ToolContext, goal: str):
        self.loop_id = uuid.uuid4().hex
        self._events: "queue.Queue" = queue.Queue()
        self._approvals: dict[str, "queue.Queue"] = {}
        self._provider = provider
        self._ctx = ctx
        self._goal = goal

    def _request_approval(self, tool_call) -> str:
        approval_queue: "queue.Queue" = queue.Queue()
        self._approvals[tool_call.id] = approval_queue
        return approval_queue.get()

    def resolve_approval(self, tool_call_id: str, decision: str) -> bool:
        approval_queue = self._approvals.get(tool_call_id)
        if approval_queue is None:
            return False
        approval_queue.put(decision)
        return True

    def _worker(self):
        try:
            for event in run_agent_loop(self._goal, self._provider, self._ctx, self._request_approval):
                self._events.put(event)
        finally:
            self._events.put(_SENTINEL)

    def start(self):
        threading.Thread(target=self._worker, daemon=True).start()

    def next_event(self, timeout: Optional[float] = None):
        item = self._events.get(timeout=timeout)
        return None if item is _SENTINEL else item


RUNS: dict[str, AgentRun] = {}
