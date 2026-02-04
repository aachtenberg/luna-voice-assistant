"""LLM provider factory."""

from .base import LLMProvider
from .ollama import OllamaProvider
from .anthropic import AnthropicProvider
from .groq import GroqProvider


def get_provider(
    provider_name: str,
    tool_registry: dict,
    # Ollama settings
    ollama_url: str = "",
    ollama_model: str = "",
    # Anthropic settings
    anthropic_api_key: str = "",
    anthropic_model: str = "",
    # Groq settings
    groq_api_key: str = "",
    groq_model: str = ""
) -> LLMProvider:
    """
    Factory function to create an LLM provider.

    Args:
        provider_name: One of "ollama", "anthropic", or "groq"
        tool_registry: Dict mapping tool names to callable functions
        *_url, *_api_key, *_model: Provider-specific settings

    Returns:
        An LLMProvider instance
    """
    provider_name = provider_name.lower()

    if provider_name == "ollama":
        if not ollama_url:
            raise ValueError("ollama_url is required for Ollama provider")
        return OllamaProvider(
            url=ollama_url,
            model=ollama_model or "qwen2.5:14b",
            tool_registry=tool_registry
        )

    elif provider_name == "anthropic":
        if not anthropic_api_key:
            raise ValueError("anthropic_api_key is required for Anthropic provider")
        return AnthropicProvider(
            api_key=anthropic_api_key,
            model=anthropic_model or "claude-3-haiku-20240307",
            tool_registry=tool_registry
        )

    elif provider_name == "groq":
        if not groq_api_key:
            raise ValueError("groq_api_key is required for Groq provider")
        return GroqProvider(
            api_key=groq_api_key,
            model=groq_model or "llama-3.1-70b-versatile",
            tool_registry=tool_registry
        )

    else:
        raise ValueError(f"Unknown LLM provider: {provider_name}. Use 'ollama', 'anthropic', or 'groq'")


__all__ = ["get_provider", "LLMProvider", "OllamaProvider", "AnthropicProvider", "GroqProvider"]
