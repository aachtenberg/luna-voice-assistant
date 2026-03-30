import json
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


def ask_stream(text: str):
    """Yield text tokens from the brain streaming endpoint."""
    try:
        with httpx.stream(
            "POST",
            f"{BRAIN_URL}/ask/stream",
            json={"text": text},
            timeout=httpx.Timeout(connect=10.0, read=120.0, write=10.0, pool=10.0)
        ) as response:
            response.raise_for_status()
            for line in response.iter_lines():
                if line.startswith("data: "):
                    data = json.loads(line[6:])
                    if data.get("done") or data.get("error"):
                        return
                    token = data.get("token", "")
                    if token:
                        yield token
    except Exception as e:
        print(f"Brain stream error: {e}")
        # Fallback to non-streaming
        result = ask(text)
        if result:
            yield result
