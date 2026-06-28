import os
import re
import json
import time
import threading
from typing import Optional
from fastapi import FastAPI, Response, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from llm import get_provider
from tools import TOOL_REGISTRY
from prompts import SYSTEM_PROMPT, TOOLS
from config import (
    LLM_PROVIDER,
    OLLAMA_URL, OLLAMA_MODEL, OLLAMA_AUTO_MODEL, OLLAMA_MODEL_REFRESH_SECONDS,
    ANTHROPIC_API_KEY, ANTHROPIC_MODEL,
    GROQ_API_KEY, GROQ_MODEL
)
from runtime_config import load_override, save_override, clear_override
from metrics import (
    REQUESTS_TOTAL, REQUEST_DURATION, CURRENT_PROVIDER,
    get_metrics, get_content_type
)
from logging_config import setup_logging

# Setup structured logging (JSON for Loki, plain text if LOG_FORMAT=text)
log = setup_logging(json_output=os.getenv("LOG_FORMAT", "text") != "text")

app = FastAPI(title="Voice Assistant Brain")

# Conversation memory - stores recent exchanges
conversation_history = []
MAX_HISTORY = 12  # Keep last 12 messages (6 exchanges)

# ---------------------------------------------------------------------------
# LLM provider — built at startup from env defaults, overlaid with any persisted
# runtime override, and rebuildable live via the /admin/provider endpoints.
# ---------------------------------------------------------------------------

# Routing fields that may be changed at runtime. API keys are NEVER overridable
# here — they always come from the environment / k8s Secret.
_OVERRIDABLE = (
    "provider", "ollama_url", "ollama_model", "ollama_auto_model",
    "anthropic_model", "groq_model",
)

# Env-var defaults — the config the pod reverts to when no override is set.
_BASE_CONFIG = {
    "provider": LLM_PROVIDER,
    "ollama_url": OLLAMA_URL,
    "ollama_model": OLLAMA_MODEL,
    "ollama_auto_model": OLLAMA_AUTO_MODEL,
    "ollama_model_refresh_seconds": OLLAMA_MODEL_REFRESH_SECONDS,
    "anthropic_model": ANTHROPIC_MODEL,
    "groq_model": GROQ_MODEL,
}

_provider_lock = threading.Lock()


def _build_llm(cfg: dict):
    """Construct a provider (single or fallback chain) from an effective config."""
    return get_provider(
        provider_name=cfg["provider"],
        tool_registry=TOOL_REGISTRY,
        ollama_url=cfg["ollama_url"],
        ollama_model=cfg["ollama_model"],
        ollama_auto_model=cfg["ollama_auto_model"],
        ollama_model_refresh_seconds=cfg["ollama_model_refresh_seconds"],
        anthropic_api_key=ANTHROPIC_API_KEY,
        anthropic_model=cfg["anthropic_model"],
        groq_api_key=GROQ_API_KEY,
        groq_model=cfg["groq_model"],
    )


def _set_provider_metric(label: str):
    """Reset the gauge so only the active chain label reads 1."""
    CURRENT_PROVIDER.clear()
    CURRENT_PROVIDER.labels(provider=label).set(1)


# Effective config = env defaults overlaid with persisted override (if any).
current_config = dict(_BASE_CONFIG)
_persisted = load_override()
if _persisted:
    current_config.update({k: v for k, v in _persisted.items() if k in _OVERRIDABLE})
    log.info(
        f"Applied persisted LLM override: {current_config['provider']}",
        extra={"event": "startup_override", "override": _persisted},
    )

log.info(
    f"Initializing LLM provider: {current_config['provider']}",
    extra={"event": "startup", "provider": current_config["provider"]},
)
llm = _build_llm(current_config)
_set_provider_metric(current_config["provider"])


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


@app.post("/ask/stream")
def ask_stream(request: AskRequest):
    """Stream the LLM response as SSE tokens for real-time TTS."""
    global conversation_history
    start_time = time.time()

    log.info(f"Stream request received: {request.text}", extra={
        "event": "stream_request",
        "query": request.text,
        "history_length": len(conversation_history)
    })

    def generate():
        full_text_parts = []
        try:
            for token in llm.chat_stream(request.text, SYSTEM_PROMPT, TOOLS, conversation_history):
                full_text_parts.append(token)
                yield f"data: {json.dumps({'token': token})}\n\n"

            full_response = clean_for_tts("".join(full_text_parts))
            yield f"data: {json.dumps({'done': True})}\n\n"

            # Update conversation history (mutate in-place to avoid reassignment)
            conversation_history.append({"role": "user", "content": request.text})
            conversation_history.append({"role": "assistant", "content": full_response})
            if len(conversation_history) > MAX_HISTORY:
                del conversation_history[:-MAX_HISTORY]

            duration_ms = int((time.time() - start_time) * 1000)
            REQUESTS_TOTAL.labels(status="success").inc()
            log.info(f"Stream response sent: {full_response[:100]}...", extra={
                "event": "stream_response",
                "duration_ms": duration_ms,
                "response_length": len(full_response)
            })
        except Exception as e:
            REQUESTS_TOTAL.labels(status="error").inc()
            log.error(f"Stream request failed: {e}", exc_info=True, extra={
                "event": "stream_error",
                "query": request.text
            })
            yield f"data: {json.dumps({'error': str(e)})}\n\n"
        finally:
            REQUEST_DURATION.observe(time.time() - start_time)

    return StreamingResponse(generate(), media_type="text/event-stream")


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


# ---------------------------------------------------------------------------
# Admin: switch the LLM provider/model at runtime (no redeploy).
# ---------------------------------------------------------------------------

class ProviderUpdate(BaseModel):
    """Partial update — only the supplied routing fields change."""
    provider: Optional[str] = None          # e.g. "ollama" or "ollama,groq,anthropic"
    ollama_url: Optional[str] = None
    ollama_model: Optional[str] = None
    ollama_auto_model: Optional[bool] = None
    anthropic_model: Optional[str] = None
    groq_model: Optional[str] = None


def _public_config() -> dict:
    """Current effective routing config (no secrets) + the live active chain."""
    active_chain = getattr(llm, "provider_names", [type(llm).__name__])
    return {
        "provider": current_config["provider"],
        "ollama_url": current_config["ollama_url"],
        "ollama_model": current_config["ollama_model"],
        "ollama_auto_model": current_config["ollama_auto_model"],
        "anthropic_model": current_config["anthropic_model"],
        "groq_model": current_config["groq_model"],
        "active_chain": active_chain,
        "override_active": load_override() is not None,
    }


@app.get("/admin/provider")
def get_provider_config():
    """Show the current LLM routing config and live provider chain."""
    return _public_config()


@app.post("/admin/provider")
def set_provider_config(update: ProviderUpdate):
    """Switch provider/model live. Persists the override to the data volume so
    it survives pod restarts. Rejects the change (keeping the running provider)
    if the new config can't be built."""
    global llm, current_config

    fields = update.model_dump(exclude_none=True) if hasattr(update, "model_dump") else update.dict(exclude_none=True)
    requested = {k: v for k, v in fields.items() if k in _OVERRIDABLE}
    if not requested:
        raise HTTPException(status_code=400, detail="No overridable fields supplied")

    with _provider_lock:
        new_cfg = dict(current_config)
        new_cfg.update(requested)
        try:
            new_llm = _build_llm(new_cfg)
        except Exception as e:
            log.warning(
                f"Rejected LLM switch ({requested}): {e}",
                extra={"event": "llm_switch_rejected", "requested": requested, "error": str(e)},
            )
            raise HTTPException(status_code=400, detail=f"Failed to build provider: {e}")

        llm = new_llm
        current_config = new_cfg
        # Persist only the fields that differ from env defaults.
        override = {k: current_config[k] for k in _OVERRIDABLE if current_config[k] != _BASE_CONFIG[k]}
        if override:
            save_override(override)
        else:
            clear_override()
        _set_provider_metric(current_config["provider"])
        log.info(
            f"Switched LLM provider to: {current_config['provider']}",
            extra={"event": "llm_switched", "config": _public_config()},
        )

    return _public_config()


@app.delete("/admin/provider")
def reset_provider_config():
    """Drop any runtime override and rebuild from env-var defaults."""
    global llm, current_config
    with _provider_lock:
        current_config = dict(_BASE_CONFIG)
        clear_override()
        llm = _build_llm(current_config)
        _set_provider_metric(current_config["provider"])
        log.info(
            f"Reset LLM provider to env defaults: {current_config['provider']}",
            extra={"event": "llm_reset", "config": _public_config()},
        )
    return _public_config()


