import httpx
from config import BRAIN_URL


def ask(text: str) -> str:
    """Send text to brain service and get response."""
    try:
        response = httpx.post(
            f"{BRAIN_URL}/ask",
            json={"text": text},
            timeout=60.0
        )
        response.raise_for_status()
        result = response.json()
        return result.get("response", "")
    except Exception as e:
        print(f"Brain error: {e}")
        return "Sorry, I couldn't process that request."
