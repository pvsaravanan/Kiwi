from sentinel.agent.providers.anthropic_provider import AnthropicAdapter
from sentinel.agent.providers.base import ProviderAdapter
from sentinel.agent.providers.gemini_provider import GeminiAdapter
from sentinel.agent.providers.openai_provider import OpenAIAdapter


def build_adapter(provider: str, client, model: str) -> ProviderAdapter:
    if provider == "anthropic":
        return AnthropicAdapter(client, model)
    if provider == "openai":
        return OpenAIAdapter(client, model)
    if provider == "gemini":
        return GeminiAdapter(client, model)
    raise ValueError(f"Unsupported provider: {provider}")
