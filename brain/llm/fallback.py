"""Fallback provider chain — tries providers in order until one succeeds."""

import logging
from .base import LLMProvider

log = logging.getLogger("brain")


class FallbackProvider(LLMProvider):
    """Wraps a list of LLMProviders, trying each in order on failure.

    Providers should raise exceptions on connectivity/availability failures so
    the chain can move on.  Logic-level failures (model confusion, tool loops)
    are returned as text and are not retried.
    """

    def __init__(self, providers: list):
        if not providers:
            raise ValueError("FallbackProvider requires at least one provider")
        self.providers = providers

    @property
    def provider_names(self) -> list[str]:
        return [type(p).__name__ for p in self.providers]

    def chat(self, user_message: str, system_prompt: str, tools: list, history: list = None) -> str:
        last_exc = None
        for provider in self.providers:
            name = type(provider).__name__
            try:
                result = provider.chat(user_message, system_prompt, tools, history)
                return result
            except Exception as e:
                log.warning(
                    f"{name} unavailable, trying next provider: {e}",
                    extra={"event": "provider_fallback", "provider": name, "error": str(e)}
                )
                last_exc = e

        log.error(
            f"All providers failed. Last error: {last_exc}",
            extra={"event": "all_providers_failed"}
        )
        return "Sorry, I couldn't process that request."

    def chat_stream(self, user_message: str, system_prompt: str, tools: list, history: list = None):
        last_exc = None
        for provider in self.providers:
            name = type(provider).__name__
            tokens_yielded = False
            try:
                for token in provider.chat_stream(user_message, system_prompt, tools, history):
                    tokens_yielded = True
                    yield token
                return  # Provider completed successfully
            except Exception as e:
                if tokens_yielded:
                    # Already mid-stream — can't switch, just stop
                    log.error(
                        f"{name} failed mid-stream after yielding tokens",
                        extra={"event": "provider_midstream_failure", "provider": name, "error": str(e)}
                    )
                    return
                log.warning(
                    f"{name} unavailable for streaming, trying next provider: {e}",
                    extra={"event": "provider_fallback_stream", "provider": name, "error": str(e)}
                )
                last_exc = e

        log.error(
            f"All providers failed for streaming. Last error: {last_exc}",
            extra={"event": "all_providers_failed"}
        )
        yield "Sorry, I couldn't process that request."
