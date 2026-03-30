"""LLM provider factory."""

from .base import LLMProvider
from .ollama import OllamaProvider
from .anthropic import AnthropicProvider
from .groq import GroqProvider
from .fallback import FallbackProvider


def _build_single_provider(
    provider_name: str,
    tool_registry: dict,
    ollama_url: str = "",
    ollama_model: str = "",
    ollama_auto_model: bool = True,
    ollama_model_refresh_seconds: int = 5,
    anthropic_api_key: str = "",
    anthropic_model: str = "",
    groq_api_key: str = "",
    groq_model: str = "",
) -> LLMProvider:
    """Build a single named provider. Raises ValueError if misconfigured."""
    name = provider_name.strip().lower()

    if name == "ollama":
        if not ollama_url:
            raise ValueError("ollama_url is required for Ollama provider")
        return OllamaProvider(
            url=ollama_url,
            model=ollama_model or "qwen2.5:14b",
            tool_registry=tool_registry,
            auto_model=ollama_auto_model,
            model_refresh_seconds=ollama_model_refresh_seconds,
        )

    if name == "anthropic":
        if not anthropic_api_key:
            raise ValueError("anthropic_api_key is required for Anthropic provider")
        return AnthropicProvider(
            api_key=anthropic_api_key,
            model=anthropic_model or "claude-3-haiku-20240307",
            tool_registry=tool_registry,
        )

    if name == "groq":
        if not groq_api_key:
            raise ValueError("groq_api_key is required for Groq provider")
        return GroqProvider(
            api_key=groq_api_key,
            model=groq_model or "llama-3.1-70b-versatile",
            tool_registry=tool_registry,
        )

    raise ValueError(f"Unknown LLM provider: '{name}'. Valid options: ollama, anthropic, groq")


def get_provider(
    provider_name: str,
    tool_registry: dict,
    # Ollama settings
    ollama_url: str = "",
    ollama_model: str = "",
    ollama_auto_model: bool = True,
    ollama_model_refresh_seconds: int = 5,
    # Anthropic settings
    anthropic_api_key: str = "",
    anthropic_model: str = "",
    # Groq settings
    groq_api_key: str = "",
    groq_model: str = "",
) -> LLMProvider:
    """Factory: build one provider or a FallbackProvider chain.

    provider_name can be a single name ("ollama") or a comma-separated
    priority list ("ollama,groq,anthropic").  Providers that are missing
    required credentials are skipped with a warning.
    """
    import logging
    log = logging.getLogger("brain")

    names = [n.strip() for n in provider_name.split(",") if n.strip()]
    if not names:
        raise ValueError("LLM_PROVIDER is empty")

    kwargs = dict(
        tool_registry=tool_registry,
        ollama_url=ollama_url,
        ollama_model=ollama_model,
        ollama_auto_model=ollama_auto_model,
        ollama_model_refresh_seconds=ollama_model_refresh_seconds,
        anthropic_api_key=anthropic_api_key,
        anthropic_model=anthropic_model,
        groq_api_key=groq_api_key,
        groq_model=groq_model,
    )

    providers = []
    for name in names:
        try:
            providers.append(_build_single_provider(name, **kwargs))
            log.info(f"Registered LLM provider: {name}", extra={"event": "provider_registered", "provider": name})
        except ValueError as e:
            log.warning(f"Skipping provider '{name}': {e}", extra={"event": "provider_skipped", "provider": name})

    if not providers:
        raise ValueError(f"No usable LLM providers from: {provider_name}")

    if len(providers) == 1:
        return providers[0]

    log.info(
        f"Using fallback chain: {' → '.join(names)}",
        extra={"event": "provider_chain", "chain": names}
    )
    return FallbackProvider(providers)


__all__ = [
    "get_provider",
    "LLMProvider",
    "OllamaProvider",
    "AnthropicProvider",
    "GroqProvider",
    "FallbackProvider",
]

