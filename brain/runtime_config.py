"""Runtime LLM override persistence.

The brain builds its LLM provider once at startup from environment variables.
To allow switching provider/model live (without a redeploy/restart), the admin
endpoints in main.py write the chosen overrides here. The file lives on the
mounted data volume (hostPath) so a chosen config survives pod restarts.

Only non-secret routing fields are persisted (provider chain + model names +
ollama url). API keys always come from the environment / k8s Secret.
"""

import json
import logging
import os
from pathlib import Path

log = logging.getLogger("brain")

OVERRIDE_PATH = Path(os.getenv("LLM_OVERRIDE_PATH", "/app/data/llm_override.json"))


def load_override() -> dict | None:
    """Return the persisted override dict, or None if absent/unreadable."""
    try:
        if not OVERRIDE_PATH.exists():
            return None
        data = json.loads(OVERRIDE_PATH.read_text())
        if isinstance(data, dict) and data:
            return data
        return None
    except Exception as e:
        log.warning(
            f"Ignoring unreadable LLM override at {OVERRIDE_PATH}: {e}",
            extra={"event": "llm_override_read_failed", "error": str(e)},
        )
        return None


def save_override(override: dict) -> None:
    """Persist the override dict atomically to the data volume."""
    OVERRIDE_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = OVERRIDE_PATH.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(override, indent=2))
    tmp.replace(OVERRIDE_PATH)
    log.info(
        f"Persisted LLM override to {OVERRIDE_PATH}",
        extra={"event": "llm_override_saved", "override": override},
    )


def clear_override() -> None:
    """Remove any persisted override (revert to env-var defaults on restart)."""
    try:
        OVERRIDE_PATH.unlink()
        log.info("Cleared LLM override", extra={"event": "llm_override_cleared"})
    except FileNotFoundError:
        pass
