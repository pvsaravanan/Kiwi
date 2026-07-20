from unittest.mock import MagicMock

import pytest

from sentinel.agent.providers import build_adapter
from sentinel.agent.providers.anthropic_provider import AnthropicAdapter
from sentinel.agent.providers.gemini_provider import GeminiAdapter
from sentinel.agent.providers.openai_provider import OpenAIAdapter


def test_build_adapter_returns_anthropic_adapter():
    adapter = build_adapter("anthropic", MagicMock(), "claude-opus-4-8")
    assert isinstance(adapter, AnthropicAdapter)


def test_build_adapter_returns_openai_adapter():
    adapter = build_adapter("openai", MagicMock(), "gpt-5.5")
    assert isinstance(adapter, OpenAIAdapter)


def test_build_adapter_returns_gemini_adapter():
    adapter = build_adapter("gemini", MagicMock(), "gemini-3-flash-preview")
    assert isinstance(adapter, GeminiAdapter)


def test_build_adapter_raises_for_unknown_provider():
    with pytest.raises(ValueError, match="Unsupported provider"):
        build_adapter("mystery", MagicMock(), "some-model")
