"""Groq LLM provider."""

import inspect
import json
from groq import Groq
from .base import LLMProvider, convert_tools_to_openai


class GroqProvider(LLMProvider):
    """Groq LLM provider with tool calling support."""

    def __init__(self, api_key: str, model: str, tool_registry: dict):
        self.client = Groq(api_key=api_key)
        self.model = model
        self.tool_registry = tool_registry

    def _invoke_tool(self, func_name: str, func_args: dict):
        """Call a tool, stripping hallucinated kwargs the model may add."""
        if func_name not in self.tool_registry:
            return f"Unknown tool: {func_name}"
        fn = self.tool_registry[func_name]
        try:
            return fn(**func_args)
        except TypeError:
            valid_params = set(inspect.signature(fn).parameters)
            filtered = {k: v for k, v in func_args.items() if k in valid_params}
            return fn(**filtered)

    def chat(self, user_message: str, system_prompt: str, tools: list, history: list = None) -> str:
        """Send a message to Groq and handle tool calls."""
        full_prompt = system_prompt + self.get_time_context()

        messages = [{"role": "system", "content": full_prompt}]
        # Add conversation history (OpenAI-style roles, as stored by main.py)
        if history:
            messages.extend(history)
        messages.append({"role": "user", "content": user_message})

        groq_tools = convert_tools_to_openai(tools)

        max_iterations = 5
        for iteration in range(max_iterations):
            # Last turn: drop tools so the model must answer from what it already has
            kwargs = {
                "model": self.model,
                "messages": messages,
                "max_tokens": 1024,
            }
            last_turn = iteration == max_iterations - 1 or not groq_tools
            if not last_turn:
                kwargs["tools"] = groq_tools
                kwargs["tool_choice"] = "auto"
            else:
                kwargs["messages"] = messages + [{
                    "role": "system",
                    "content": "No more tool calls are available. Answer the user now "
                               "in one or two spoken sentences from what you have, or "
                               "say you couldn't find it."
                }]

            try:
                response = self.client.chat.completions.create(**kwargs)
            except Exception as e:
                print(f"Groq error: {e}")
                # gpt-oss sometimes still emits a tool call with tools removed; Groq
                # rejects it (tool_use_failed). That's an answer failure, not an
                # outage — don't fall through to the next provider.
                if last_turn and "tool_use_failed" in str(e):
                    return "Sorry, I couldn't find an answer to that."
                raise  # propagate to FallbackProvider

            message = response.choices[0].message
            tool_calls = message.tool_calls

            if not tool_calls:
                return message.content or ""

            # Add assistant message with tool calls
            messages.append({
                "role": "assistant",
                "content": message.content,
                "tool_calls": [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {
                            "name": tc.function.name,
                            "arguments": tc.function.arguments
                        }
                    }
                    for tc in tool_calls
                ]
            })

            # Process each tool call
            for tool_call in tool_calls:
                func_name = tool_call.function.name
                try:
                    func_args = json.loads(tool_call.function.arguments)
                except json.JSONDecodeError:
                    func_args = {}

                print(f"[Groq] Tool call: {func_name}({func_args})")
                result = self._invoke_tool(func_name, func_args)
                print(f"[Groq] Tool result: {str(result)[:200]}...")

                messages.append({
                    "role": "tool",
                    "tool_call_id": tool_call.id,
                    "content": str(result)
                })

        return "Sorry, I ran into too many steps trying to answer that."
