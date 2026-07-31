"""Anthropic (Claude) LLM provider."""

import inspect

import anthropic
from .base import LLMProvider, convert_tools_to_anthropic


class AnthropicProvider(LLMProvider):
    """Anthropic Claude LLM provider with tool calling support."""

    def __init__(self, api_key: str, model: str, tool_registry: dict):
        self.client = anthropic.Anthropic(api_key=api_key)
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
        """Send a message to Claude and handle tool calls."""
        full_prompt = system_prompt + self.get_time_context()

        messages = []
        # Add conversation history
        if history:
            messages.extend(history)
        messages.append({"role": "user", "content": user_message})

        anthropic_tools = convert_tools_to_anthropic(tools)

        print(f"[Claude] Model: {self.model}")
        print(f"[Claude] Tools: {anthropic_tools}")

        max_iterations = 5
        for iteration in range(max_iterations):
            # Last turn: drop tools so the model must answer from what it already has
            kwargs = {
                "model": self.model,
                "max_tokens": 1024,
                "system": full_prompt,
                "messages": messages,
            }
            if iteration < max_iterations - 1 and anthropic_tools:
                kwargs["tools"] = anthropic_tools
                kwargs["tool_choice"] = {"type": "auto"}

            try:
                response = self.client.messages.create(**kwargs)
                print(f"[Claude] Stop reason: {response.stop_reason}")
                print(f"[Claude] Content: {response.content}")
            except Exception as e:
                print(f"Anthropic error: {e}")
                raise  # propagate to FallbackProvider

            # Check if we need to handle tool use
            if response.stop_reason == "tool_use":
                # Add assistant's response to messages
                messages.append({
                    "role": "assistant",
                    "content": response.content
                })

                # Process tool calls
                tool_results = []
                for block in response.content:
                    if block.type == "tool_use":
                        func_name = block.name
                        func_args = block.input

                        print(f"[Claude] Tool call: {func_name}({func_args})")
                        result = self._invoke_tool(func_name, func_args)
                        print(f"[Claude] Tool result: {str(result)[:200]}...")

                        tool_results.append({
                            "type": "tool_result",
                            "tool_use_id": block.id,
                            "content": str(result)
                        })

                # Add tool results to messages
                messages.append({
                    "role": "user",
                    "content": tool_results
                })
            else:
                # No more tool calls, extract text response
                for block in response.content:
                    if hasattr(block, "text"):
                        return block.text
                return ""

        return "Sorry, I ran into too many steps trying to answer that."
