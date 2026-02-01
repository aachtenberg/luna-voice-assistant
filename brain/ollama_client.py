import httpx
from datetime import datetime
from zoneinfo import ZoneInfo
from config import OLLAMA_URL, OLLAMA_MODEL
from prompts import SYSTEM_PROMPT, TOOLS
from tools import TOOL_REGISTRY


def get_system_prompt_with_time() -> str:
    """Get system prompt with current date/time injected."""
    # Get current time in Eastern timezone
    try:
        tz = ZoneInfo("America/Toronto")
        now = datetime.now(tz)
    except:
        now = datetime.now()

    time_str = now.strftime("%I:%M %p")  # e.g., "08:15 PM"
    date_str = now.strftime("%A, %B %d, %Y")  # e.g., "Friday, January 31, 2026"

    time_context = f"""
Current date and time: {date_str}, {time_str}

IMPORTANT: For simple questions like "what time is it?" or "what's the date?", just answer directly using the time above. Do NOT use tools for basic time/date questions."""

    return SYSTEM_PROMPT + time_context


def chat(user_message: str) -> str:
    """Send a message to Ollama and handle tool calls."""
    messages = [
        {"role": "system", "content": get_system_prompt_with_time()},
        {"role": "user", "content": user_message}
    ]

    max_iterations = 5
    for _ in range(max_iterations):
        response = _call_ollama(messages)

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

            if func_name in TOOL_REGISTRY:
                result = TOOL_REGISTRY[func_name](**func_args)
            else:
                result = f"Unknown tool: {func_name}"

            messages.append({
                "role": "tool",
                "content": str(result)
            })

    return "Sorry, I ran into too many steps trying to answer that."


def _call_ollama(messages: list) -> dict:
    """Make a request to Ollama's chat API."""
    try:
        response = httpx.post(
            f"{OLLAMA_URL}/api/chat",
            json={
                "model": OLLAMA_MODEL,
                "messages": messages,
                "tools": TOOLS,
                "stream": False
            },
            timeout=60.0
        )
        response.raise_for_status()
        return response.json()
    except Exception as e:
        print(f"Ollama error: {e}")
        return {}
