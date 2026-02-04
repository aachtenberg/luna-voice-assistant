import os
import re
import time
import threading
from fastapi import FastAPI, Response
from pydantic import BaseModel
from llm import get_provider
from tools import TOOL_REGISTRY
from prompts import SYSTEM_PROMPT, TOOLS
from config import (
    LLM_PROVIDER,
    OLLAMA_URL, OLLAMA_MODEL,
    ANTHROPIC_API_KEY, ANTHROPIC_MODEL,
    GROQ_API_KEY, GROQ_MODEL
)
from metrics import (
    REQUESTS_TOTAL, REQUEST_DURATION, CURRENT_PROVIDER,
    get_metrics, get_content_type
)
from logging_config import setup_logging

# Setup structured logging (JSON for Loki, plain text if LOG_FORMAT=text)
log = setup_logging(json_output=os.getenv("LOG_FORMAT", "text") != "text")

# Keepalive interval in seconds (3 minutes)
KEEPALIVE_INTERVAL = 180

app = FastAPI(title="Voice Assistant Brain")

# Conversation memory - stores recent exchanges
conversation_history = []
MAX_HISTORY = 12  # Keep last 12 messages (6 exchanges)

# Initialize the LLM provider
log.info(f"Initializing LLM provider: {LLM_PROVIDER}", extra={"event": "startup", "provider": LLM_PROVIDER})
llm = get_provider(
    provider_name=LLM_PROVIDER,
    tool_registry=TOOL_REGISTRY,
    ollama_url=OLLAMA_URL,
    ollama_model=OLLAMA_MODEL,
    anthropic_api_key=ANTHROPIC_API_KEY,
    anthropic_model=ANTHROPIC_MODEL,
    groq_api_key=GROQ_API_KEY,
    groq_model=GROQ_MODEL
)


class AskRequest(BaseModel):
    text: str


class AskResponse(BaseModel):
    response: str


def clean_for_tts(text: str) -> str:
    """Remove markdown formatting that TTS would read literally."""
    # Remove bold/italic markers
    text = re.sub(r'\*+', '', text)
    # Remove underscores used for emphasis
    text = re.sub(r'_+', '', text)
    # Remove markdown headers
    text = re.sub(r'^#+\s*', '', text, flags=re.MULTILINE)
    # Remove markdown links [text](url) -> text
    text = re.sub(r'\[([^\]]+)\]\([^)]+\)', r'\1', text)
    # Remove backticks
    text = re.sub(r'`+', '', text)
    # Clean up extra whitespace
    text = re.sub(r'\s+', ' ', text).strip()
    return text


@app.post("/ask", response_model=AskResponse)
def ask(request: AskRequest):
    """Process a voice query and return a response."""
    global conversation_history
    start_time = time.time()

    log.info(f"Request received: {request.text}", extra={
        "event": "request",
        "query": request.text,
        "history_length": len(conversation_history)
    })

    try:
        response_text = llm.chat(request.text, SYSTEM_PROMPT, TOOLS, conversation_history)
        response_text = clean_for_tts(response_text)

        # Update conversation history
        conversation_history.append({"role": "user", "content": request.text})
        conversation_history.append({"role": "assistant", "content": response_text})

        # Trim to keep only recent messages
        if len(conversation_history) > MAX_HISTORY:
            conversation_history = conversation_history[-MAX_HISTORY:]

        duration_ms = int((time.time() - start_time) * 1000)
        REQUESTS_TOTAL.labels(status="success").inc()

        log.info(f"Response sent: {response_text[:100]}...", extra={
            "event": "response",
            "duration_ms": duration_ms,
            "response_length": len(response_text)
        })

        return AskResponse(response=response_text)
    except Exception as e:
        duration_ms = int((time.time() - start_time) * 1000)
        REQUESTS_TOTAL.labels(status="error").inc()

        log.error(f"Request failed: {e}", exc_info=True, extra={
            "event": "error",
            "duration_ms": duration_ms,
            "query": request.text
        })

        raise e
    finally:
        REQUEST_DURATION.observe(time.time() - start_time)


@app.post("/clear-history")
def clear_history():
    """Clear conversation history."""
    global conversation_history
    conversation_history = []
    log.info("Conversation history cleared", extra={"event": "history_cleared"})
    return {"status": "cleared"}


@app.get("/health")
def health():
    """Health check endpoint."""
    return {"status": "ok"}


@app.get("/metrics")
def metrics():
    """Prometheus metrics endpoint."""
    return Response(content=get_metrics(), media_type=get_content_type())


# Set current provider gauge
CURRENT_PROVIDER.labels(provider=LLM_PROVIDER).set(1)


def _keepalive_loop():
    """Background thread to keep LLM model loaded in memory."""
    import httpx

    while True:
        time.sleep(KEEPALIVE_INTERVAL)
        try:
            if LLM_PROVIDER == "anthropic" and hasattr(llm, 'client') and hasattr(llm.client, 'messages'):
                # Anthropic: count tokens on a minimal message
                llm.client.messages.count_tokens(
                    model=llm.model,
                    messages=[{"role": "user", "content": "ping"}]
                )
            elif LLM_PROVIDER == "ollama" and hasattr(llm, 'url'):
                # Ollama: do a tiny inference to keep model loaded in GPU memory
                httpx.post(
                    f"{llm.url}/api/generate",
                    json={
                        "model": llm.model,
                        "prompt": "hi",
                        "stream": False,
                        "options": {"num_predict": 1},  # Generate just 1 token
                        "keep_alive": -1  # Keep model loaded indefinitely
                    },
                    timeout=30.0
                )
            elif LLM_PROVIDER == "groq" and hasattr(llm, 'client'):
                # Groq: list models
                llm.client.models.list()

            log.debug("Keepalive ping sent", extra={"event": "keepalive", "provider": LLM_PROVIDER})
        except Exception as e:
            log.warning(f"Keepalive ping failed: {e}", extra={"event": "keepalive_error", "provider": LLM_PROVIDER})


# Start keepalive thread
keepalive_thread = threading.Thread(target=_keepalive_loop, daemon=True)
keepalive_thread.start()
log.info(f"Keepalive thread started (interval: {KEEPALIVE_INTERVAL}s)", extra={"event": "keepalive_started", "provider": LLM_PROVIDER})
