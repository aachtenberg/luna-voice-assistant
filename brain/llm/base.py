"""Abstract LLM provider interface with tool format converters."""

from abc import ABC, abstractmethod
from datetime import datetime
from zoneinfo import ZoneInfo


class LLMProvider(ABC):
    """Abstract base class for LLM providers."""

    @abstractmethod
    def chat(self, user_message: str, system_prompt: str, tools: list, history: list = None) -> str:
        """
        Send a message to the LLM and handle tool calls.

        Args:
            user_message: The user's input text
            system_prompt: System prompt for the LLM
            tools: List of tool definitions in OpenAI format
            history: Optional conversation history

        Returns:
            The final response text from the LLM
        """
        pass

    def get_time_context(self) -> str:
        """Get current date/time context to append to system prompt."""
        try:
            tz = ZoneInfo("America/Toronto")
            now = datetime.now(tz)
        except Exception:
            now = datetime.now()

        time_str = now.strftime("%I:%M %p")
        date_str = now.strftime("%A, %B %d, %Y")

        return f"""
Current date and time: {date_str}, {time_str}

IMPORTANT: For simple questions like "what time is it?" or "what's the date?", just answer directly using the time above. Do NOT use tools for basic time/date questions."""


def convert_tools_to_anthropic(tools: list) -> list:
    """
    Convert OpenAI-style tool definitions to Anthropic format.

    OpenAI format:
    {
        "type": "function",
        "function": {
            "name": "...",
            "description": "...",
            "parameters": {...}
        }
    }

    Anthropic format:
    {
        "name": "...",
        "description": "...",
        "input_schema": {...}
    }
    """
    anthropic_tools = []
    for tool in tools:
        if tool.get("type") == "function":
            func = tool["function"]
            anthropic_tools.append({
                "name": func["name"],
                "description": func.get("description", ""),
                "input_schema": func.get("parameters", {"type": "object", "properties": {}})
            })
    return anthropic_tools


def convert_tools_to_openai(tools: list) -> list:
    """
    Ensure tools are in OpenAI format (used by Ollama and Groq).
    This is a pass-through since our tools are already in this format.
    """
    return tools
