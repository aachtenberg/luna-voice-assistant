"""Ollama LLM provider."""

import json
import re
import time
import httpx
from .base import LLMProvider, convert_tools_to_openai
from metrics import LLM_CALLS_TOTAL, LLM_DURATION, LLM_ERRORS, TOOL_CALLS_TOTAL, TOOL_DURATION


class OllamaProvider(LLMProvider):
    """Ollama LLM provider with tool calling support."""

    # Phrases that indicate the model claimed to perform an action without calling a tool
    _ACTION_PHRASES = [
        "set a timer", "timer set", "set the timer", "i've set", "i have set",
        "started a timer", "timer started",
        "cancelled the timer", "canceled the timer", "timer cancelled", "timer canceled",
        "turned on the", "turned off the", "light is now", "lights are now",
        "i've turned", "i have turned",
    ]

    # Phrases that indicate the model doesn't know but should search
    _SHOULD_SEARCH_PHRASES = [
        "i don't have", "i do not have", "i'm not sure", "i am not sure",
        "let me check", "i can't find", "i cannot find",
        "i don't know", "i do not know", "i'm unable", "i am unable",
        "i lack", "not available to me", "beyond my knowledge",
    ]

    def __init__(self, url: str, model: str, tool_registry: dict,
                 timeout_connect: float = 10, timeout_read: float = 180,
                 max_iterations: int = 4):
        self.url = url
        self.model = model
        self.tool_registry = tool_registry
        self.timeout = httpx.Timeout(connect=timeout_connect, read=timeout_read,
                                     write=10.0, pool=10.0)
        self.max_iterations = max_iterations

    def _claims_action_without_tool(self, content: str) -> bool:
        """Check if response claims to have performed an action that requires a tool call."""
        lower = content.lower()
        return any(phrase in lower for phrase in self._ACTION_PHRASES)

    def _should_search(self, content: str) -> bool:
        """Check if response admits ignorance but didn't search the web."""
        lower = content.lower()
        return any(phrase in lower for phrase in self._SHOULD_SEARCH_PHRASES)

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

        tool_was_called = False
        for iteration in range(self.max_iterations):
            # On last iteration, drop tools to force a final answer
            use_tools = ollama_tools if iteration < self.max_iterations - 1 else []
            response = self._call_ollama(messages, use_tools)

            if not response:
                return "Sorry, I couldn't process that request."

            message = response.get("message", {})
            tool_calls = message.get("tool_calls")
            content = message.get("content", "")

            # Fallback: parse tool calls from content if model returns JSON as text
            if not tool_calls and content:
                parsed = self._parse_tool_from_content(content)
                if parsed:
                    tool_calls = [{"function": parsed}]

            if not tool_calls:
                # Safety net: if the model claims to have done something but never called a tool, force a retry
                if not tool_was_called and iteration == 0 and self._claims_action_without_tool(content):
                    print(f"[Ollama] Model claimed action without tool call, forcing retry: {content[:100]}")
                    messages.append(message)
                    messages.append({
                        "role": "user",
                        "content": "You said you performed an action, but you did NOT call any tool. "
                                   "The action was NOT actually performed. You MUST call the appropriate "
                                   "tool function (set_timer, cancel_timer, control_light, etc.) to "
                                   "actually do it. Try again now."
                    })
                    continue
                # Safety net: if the model says it doesn't know, force a web search
                if not tool_was_called and iteration == 0 and self._should_search(content):
                    print(f"[Ollama] Model punted without searching, forcing web_search: {content[:100]}")
                    messages.append(message)
                    messages.append({
                        "role": "user",
                        "content": "You said you don't have that information, but you didn't try searching. "
                                   "Use the web_search tool to look it up before responding."
                    })
                    continue
                return content

            messages.append(message)
            tool_was_called = True

            for tool_call in tool_calls:
                func_name = tool_call.get("function", {}).get("name")
                func_args = tool_call.get("function", {}).get("arguments", {})

                print(f"[Ollama] Tool call: {func_name}({func_args})")
                TOOL_CALLS_TOTAL.labels(tool_name=func_name).inc()

                tool_start = time.time()
                if func_name in self.tool_registry:
                    try:
                        result = self.tool_registry[func_name](**func_args)
                    except TypeError:
                        # Strip unexpected args the model hallucinated
                        import inspect
                        valid_params = set(inspect.signature(self.tool_registry[func_name]).parameters)
                        filtered_args = {k: v for k, v in func_args.items() if k in valid_params}
                        result = self.tool_registry[func_name](**filtered_args)
                else:
                    result = f"Unknown tool: {func_name}"
                TOOL_DURATION.labels(tool_name=func_name).observe(time.time() - tool_start)

                print(f"[Ollama] Tool result: {result[:200]}...")

                messages.append({
                    "role": "tool",
                    "content": str(result)
                })

        return "Sorry, I ran into too many steps trying to answer that."

    def _parse_tool_from_content(self, content: str) -> dict | None:
        """Parse tool call JSON from message content (fallback for models that don't use tool_calls)."""
        try:
            # Find the outermost JSON object containing name and arguments
            start = content.find('{')
            if start == -1:
                return None

            # Find matching closing brace
            depth = 0
            for i, c in enumerate(content[start:], start):
                if c == '{':
                    depth += 1
                elif c == '}':
                    depth -= 1
                    if depth == 0:
                        json_str = content[start:i+1]
                        data = json.loads(json_str)
                        if "name" in data and "arguments" in data:
                            return {"name": data["name"], "arguments": data["arguments"]}
                        break
        except (json.JSONDecodeError, KeyError):
            pass
        return None

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
                    "think": False
                },
                timeout=self.timeout
            )
            response.raise_for_status()
            result = response.json()
            LLM_CALLS_TOTAL.labels(provider="ollama", model=self.model).inc()
            LLM_DURATION.labels(provider="ollama").observe(time.time() - start_time)
            return result
        except Exception as e:
            print(f"Ollama error: {e}")
            LLM_ERRORS.labels(provider="ollama", error_type=type(e).__name__).inc()
            return {}
