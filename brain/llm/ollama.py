"""Ollama LLM provider."""

import time
import httpx
from .base import LLMProvider, convert_tools_to_openai
from metrics import LLM_CALLS_TOTAL, LLM_DURATION, LLM_ERRORS, TOOL_CALLS_TOTAL, TOOL_DURATION


class OllamaProvider(LLMProvider):
    """Ollama LLM provider with tool calling support."""

    def __init__(self, url: str, model: str, tool_registry: dict):
        self.url = url
        self.model = model
        self.tool_registry = tool_registry

    def chat(self, user_message: str, system_prompt: str, tools: list, history: list = None) -> str:
        """Send a message to Ollama and handle tool calls."""
        full_prompt = system_prompt + self.get_time_context()

        messages = [
            {"role": "system", "content": full_prompt},
        ]

        # Add conversation history for context
        if history:
            messages.extend(history)

        messages.append({"role": "user", "content": user_message})

        ollama_tools = convert_tools_to_openai(tools)

        max_iterations = 5
        for _ in range(max_iterations):
            response = self._call_ollama(messages, ollama_tools)

            if not response:
                return "Sorry, I couldn't process that request."

            message = response.get("message", {})
            tool_calls = message.get("tool_calls")

            if not tool_calls:
                return message.get("content", "")

            messages.append(message)

            for tool_call in tool_calls:
                func_name = tool_call.get("function", {}).get("name")
                func_args = tool_call.get("function", {}).get("arguments", {})

                print(f"[Ollama] Tool call: {func_name}({func_args})")
                TOOL_CALLS_TOTAL.labels(tool_name=func_name).inc()

                tool_start = time.time()
                if func_name in self.tool_registry:
                    result = self.tool_registry[func_name](**func_args)
                else:
                    result = f"Unknown tool: {func_name}"
                TOOL_DURATION.labels(tool_name=func_name).observe(time.time() - tool_start)

                print(f"[Ollama] Tool result: {result[:200]}...")

                messages.append({
                    "role": "tool",
                    "content": str(result)
                })

        return "Sorry, I ran into too many steps trying to answer that."

    def _call_ollama(self, messages: list, tools: list) -> dict:
        """Make a request to Ollama's chat API."""
        start_time = time.time()
        try:
            response = httpx.post(
                f"{self.url}/api/chat",
                json={
                    "model": self.model,
                    "messages": messages,
                    "tools": tools,
                    "stream": False,
                    "keep_alive": -1  # Keep model loaded in memory
                },
                timeout=60.0
            )
            response.raise_for_status()
            LLM_CALLS_TOTAL.labels(provider="ollama", model=self.model).inc()
            LLM_DURATION.labels(provider="ollama").observe(time.time() - start_time)
            return response.json()
        except Exception as e:
            print(f"Ollama error: {e}")
            LLM_ERRORS.labels(provider="ollama", error_type=type(e).__name__).inc()
            return {}
