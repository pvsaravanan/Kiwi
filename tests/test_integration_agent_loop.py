import time
from pathlib import Path

import anthropic
import pytest

from sentinel.agent.loop import run_agent_loop
from sentinel.agent.providers import build_adapter
from sentinel.agent.tools import ToolContext
from sentinel.cognee_client import CogneeClient
from sentinel.config import load_settings

pytestmark = pytest.mark.integration

DATASET = f"sentinel_smoke_{int(time.time())}"


def test_fix_loop_reads_a_deliberately_broken_file_and_edits_it(tmp_path):
    broken = tmp_path / "calc.py"
    broken.write_text("def add(a, b):\n    return a - b  # bug: should be a + b\n", encoding="utf-8")

    settings = load_settings()
    cognee_client = CogneeClient(settings)
    ctx = ToolContext(repo_root=tmp_path, cognee_client=cognee_client, dataset=DATASET)
    provider = build_adapter("anthropic", anthropic.Anthropic(), "claude-opus-4-8")

    def auto_approve(tool_call):
        return "allow"

    events = list(run_agent_loop(
        "Read calc.py, then fix the bug in add() so it returns a + b instead of a - b.",
        provider, ctx, request_approval=auto_approve, max_iterations=6,
    ))

    try:
        assert any(e.type == "loop_done" for e in events)
        updated = broken.read_text(encoding="utf-8")
        assert "a + b" in updated
    finally:
        cognee_client.forget(dataset=DATASET)
