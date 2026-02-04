"""Groq LLM provider."""

import json
from groq import Groq
from .base import LLMProvider, convert_tools_to_openai


class GroqProvider(LLMProvider):
    """Groq LLM provider with tool calling support."""

    def __init__(self, api_key: str, model: str, tool_registry: dict):
        self.client = Groq(api_key=api_key)
        self.model = model
        self.tool_registry = tool_registry

    def chat(self, user_message: str, system_prompt: str, tools: list) -> str:
        """Send a message to Groq and handle tool calls."""
        full_prompt = system_prompt + self.get_time_context()

        messages = [
            {"role": "system", "content": full_prompt},
            {"role": "user", "content": user_message}
        ]

        groq_tools = convert_tools_to_openai(tools)

        max_iterations = 5
        for _ in range(max_iterations):
            try:
                response = self.client.chat.completions.create(
                    model=self.model,
                    messages=messages,
                    tools=groq_tools,
                    tool_choice="auto",
                    max_tokens=1024
                )
            except Exception as e:
                print(f"Groq error: {e}")
                return "Sorry, I couldn't process that request."

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

                if func_name in self.tool_registry:
                    result = self.tool_registry[func_name](**func_args)
                else:
                    result = f"Unknown tool: {func_name}"

                print(f"[Groq] Tool result: {str(result)[:200]}...")

                messages.append({
                    "role": "tool",
                    "tool_call_id": tool_call.id,
                    "content": str(result)
                })

        return "Sorry, I ran into too many steps trying to answer that."
