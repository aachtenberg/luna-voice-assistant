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
        "checked the timer", "i've checked", "i have checked",
        "minutes remaining", "time remaining", "time left",
        "timer is still", "timer has",
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

    # Phrases that indicate the model promised to do something but didn't
    _PROMISES_ACTION = [
        "one moment", "just a moment", "hold on", "let me look",
        "i'll check", "i will check", "i'll search", "i will search",
        "i'll look", "i will look", "i'll find", "i will find",
        "let me search", "let me find", "let me get",
    ]

    def __init__(self, url: str, model: str, tool_registry: dict,
                 timeout_connect: float = 10, timeout_read: float = 180,
                 max_iterations: int = 4, auto_model: bool = True,
                 model_refresh_seconds: int = 5):
        self.url = url
        self.default_model = model
        self.model = model
        self.tool_registry = tool_registry
        self.timeout = httpx.Timeout(connect=timeout_connect, read=timeout_read,
                                     write=10.0, pool=10.0)
        self.max_iterations = max_iterations
        self.auto_model = auto_model
        self.model_refresh_seconds = max(1, int(model_refresh_seconds))
        self._last_model_refresh = 0.0

    def _resolve_active_model(self) -> str:
        """Use currently loaded Ollama model when available, else fallback to configured model."""
        if not self.auto_model:
            return self.default_model

        now = time.time()
        if now - self._last_model_refresh < self.model_refresh_seconds:
            return self.model

        self._last_model_refresh = now
        try:
            response = httpx.get(f"{self.url}/api/ps", timeout=self.timeout)
            response.raise_for_status()
            data = response.json()
            models = data.get("models") or []

            loaded_model = None
            if models:
                first = models[0] or {}
                loaded_model = first.get("name") or first.get("model")

            if loaded_model:
                loaded_model = str(loaded_model)
                if loaded_model != self.model:
                    print(f"[Ollama] Using loaded model from server: {loaded_model}")
                self.model = loaded_model
            else:
                if self.model != self.default_model:
                    print(f"[Ollama] No loaded model reported; falling back to configured model: {self.default_model}")
                self.model = self.default_model
        except Exception as e:
            # Keep requests flowing if /api/ps is unavailable.
            if self.model != self.default_model:
                print(f"[Ollama] Active-model check failed ({e}); falling back to configured model: {self.default_model}")
                self.model = self.default_model

        return self.model

    def _claims_action_without_tool(self, content: str) -> bool:
        """Check if response claims to have performed an action that requires a tool call."""
        lower = content.lower()
        return any(phrase in lower for phrase in self._ACTION_PHRASES)

    def _should_search(self, content: str) -> bool:
        """Check if response admits ignorance but didn't search the web."""
        lower = content.lower()
        return any(phrase in lower for phrase in self._SHOULD_SEARCH_PHRASES)

    def _promises_action(self, content: str) -> bool:
        """Check if response promises to take action but didn't."""
        lower = content.lower()
        return any(phrase in lower for phrase in self._PROMISES_ACTION)

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
                # Safety nets: force retry if model didn't use tools but should have
                # Allow retries up to iteration 2 (not just 0) to catch persistent hallucination
                if not tool_was_called and iteration < self.max_iterations - 1:
                    if self._claims_action_without_tool(content):
                        print(f"[Ollama] Model claimed action without tool call, forcing retry: {content[:100]}")
                        messages.append(message)
                        messages.append({
                            "role": "user",
                            "content": "You said you performed an action, but you did NOT call any tool. "
                                       "The action was NOT actually performed. You MUST call the appropriate "
                                       "tool function (set_timer, cancel_timer, list_timers, control_light, etc.) to "
                                       "actually do it. Try again now."
                        })
                        continue
                    if self._should_search(content):
                        print(f"[Ollama] Model punted without searching, forcing web_search: {content[:100]}")
                        messages.append(message)
                        messages.append({
                            "role": "user",
                            "content": "You said you don't have that information, but you didn't try searching. "
                                       "Use the web_search tool to look it up before responding."
                        })
                        continue
                    if self._promises_action(content):
                        print(f"[Ollama] Model promised action without tool call, forcing retry: {content[:100]}")
                        messages.append(message)
                        messages.append({
                            "role": "user",
                            "content": "You said you would look something up, but you didn't call any tool. "
                                       "Please use the appropriate tool (web_search, get_weather, query_influxdb, etc.) now."
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

    def chat_stream(self, user_message: str, system_prompt: str, tools: list, history: list = None):
        """Same as chat() but yields token strings for the final response."""
        full_prompt = system_prompt + self.get_time_context()
        messages = [{"role": "system", "content": full_prompt}]
        if history:
            messages.extend(history)
        messages.append({"role": "user", "content": user_message})

        ollama_tools = convert_tools_to_openai(tools)
        tool_was_called = False

        for iteration in range(self.max_iterations):
            use_tools = ollama_tools if iteration < self.max_iterations - 1 else []

            # Stream the final call when we can predict it's the last one
            can_stream = tool_was_called or iteration == self.max_iterations - 1

            if can_stream:
                # Stream this call — yield tokens as they arrive
                for token in self._call_ollama_stream(messages, use_tools):
                    yield token
                return

            # Non-streaming for early iterations where tools may be called
            response = self._call_ollama(messages, use_tools)
            if not response:
                yield "Sorry, I couldn't process that request."
                return

            message = response.get("message", {})
            tool_calls = message.get("tool_calls")
            content = message.get("content", "")

            if not tool_calls and content:
                parsed = self._parse_tool_from_content(content)
                if parsed:
                    tool_calls = [{"function": parsed}]

            if not tool_calls:
                # Safety nets: force retry if model didn't use tools but should have
                if not tool_was_called and iteration < self.max_iterations - 1:
                    if self._claims_action_without_tool(content):
                        print(f"[Ollama] Model claimed action without tool call, forcing retry: {content[:100]}")
                        messages.append(message)
                        messages.append({
                            "role": "user",
                            "content": "You said you performed an action, but you did NOT call any tool. "
                                       "The action was NOT actually performed. You MUST call the appropriate "
                                       "tool function (set_timer, cancel_timer, list_timers, control_light, etc.) to "
                                       "actually do it. Try again now."
                        })
                        continue
                    if self._should_search(content):
                        print(f"[Ollama] Model punted without searching, forcing web_search: {content[:100]}")
                        messages.append(message)
                        messages.append({
                            "role": "user",
                            "content": "You said you don't have that information, but you didn't try searching. "
                                       "Use the web_search tool to look it up before responding."
                        })
                        continue
                    if self._promises_action(content):
                        print(f"[Ollama] Model promised action without tool call, forcing retry: {content[:100]}")
                        messages.append(message)
                        messages.append({
                            "role": "user",
                            "content": "You said you would look something up, but you didn't call any tool. "
                                       "Please use the appropriate tool (web_search, get_weather, query_influxdb, etc.) now."
                        })
                        continue
                # Final response with no tools needed — yield as single chunk
                yield content
                return

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
                        import inspect
                        valid_params = set(inspect.signature(self.tool_registry[func_name]).parameters)
                        filtered_args = {k: v for k, v in func_args.items() if k in valid_params}
                        result = self.tool_registry[func_name](**filtered_args)
                else:
                    result = f"Unknown tool: {func_name}"
                TOOL_DURATION.labels(tool_name=func_name).observe(time.time() - tool_start)
                print(f"[Ollama] Tool result: {result[:200]}...")
                messages.append({"role": "tool", "content": str(result)})

        yield "Sorry, I ran into too many steps trying to answer that."

    def _call_ollama_stream(self, messages: list, tools: list):
        """Make a streaming request to Ollama, yielding content tokens."""
        start_time = time.time()
        model = self._resolve_active_model()
        try:
            with httpx.stream(
                "POST",
                f"{self.url}/api/chat",
                json={
                    "model": model,
                    "messages": messages,
                    "tools": tools,
                    "stream": True,
                    "think": False
                },
                timeout=self.timeout
            ) as response:
                response.raise_for_status()
                for line in response.iter_lines():
                    if not line:
                        continue
                    chunk = json.loads(line)
                    token = chunk.get("message", {}).get("content", "")
                    if token:
                        yield token
                    if chunk.get("done"):
                        break
            LLM_CALLS_TOTAL.labels(provider="ollama", model=model).inc()
            LLM_DURATION.labels(provider="ollama").observe(time.time() - start_time)
        except (httpx.ConnectError, httpx.ConnectTimeout, httpx.RemoteProtocolError) as e:
            LLM_ERRORS.labels(provider="ollama", error_type=type(e).__name__).inc()
            raise  # propagate to FallbackProvider
        except Exception as e:
            print(f"Ollama streaming error: {e}")
            LLM_ERRORS.labels(provider="ollama", error_type=type(e).__name__).inc()

    def _call_ollama(self, messages: list, tools: list) -> dict:
        """Make a request to Ollama's chat API."""
        start_time = time.time()
        model = self._resolve_active_model()
        try:
            response = httpx.post(
                f"{self.url}/api/chat",
                json={
                    "model": model,
                    "messages": messages,
                    "tools": tools,
                    "stream": False,
                    "think": False
                },
                timeout=self.timeout
            )
            response.raise_for_status()
            result = response.json()
            LLM_CALLS_TOTAL.labels(provider="ollama", model=model).inc()
            LLM_DURATION.labels(provider="ollama").observe(time.time() - start_time)
            return result
        except (httpx.ConnectError, httpx.ConnectTimeout, httpx.RemoteProtocolError) as e:
            LLM_ERRORS.labels(provider="ollama", error_type=type(e).__name__).inc()
            raise  # propagate to FallbackProvider
        except Exception as e:
            print(f"Ollama error: {e}")
            LLM_ERRORS.labels(provider="ollama", error_type=type(e).__name__).inc()
            return {}
