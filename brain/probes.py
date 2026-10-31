"""Health probes: can Luna still do her job, checked at no cost.

/health only says the process is up. Web search can return nothing for days and
a fallback provider can die unnoticed with /health saying ok throughout. These
ask each thing a turn depends on whether it still answers.

Nothing here spends credits or touches conversation_history. A plain "hello"
through /ask would do both: every request shares one history, and each one
carries the whole system prompt and tool list.

- groq lists models, which uses no tokens, and looks for the configured one. A
  bad key, an outage or a retired model fails it. A spent quota does not.
- ollama lists installed models, which loads nothing. PROBE_OLLAMA_HELLO adds a
  real chat a few tokens long, for once a local model does all the inference.
  It stays off on a GPU shared with other work, where it would load a model and
  could evict theirs.
- search makes one SearXNG query. PROBE_SEARCH_INTERVAL_SECONDS spaces these out
  because each one spends search engine quota.
- Anthropic is not checked: it isn't funded, so it would only ever fail.

Off by default, and off means absent: no thread, no calls, no metrics. POST
/admin/probe runs the checks once. PROBE_INTERVAL_SECONDS starts the timer; leave
it at 0 until a local model does all the inference.
"""

import logging
import threading
import time

import httpx

from config import PROBE_INTERVAL_SECONDS, PROBE_SEARCH_INTERVAL_SECONDS, PROBE_OLLAMA_HELLO
from llm import GroqProvider, OllamaProvider
from metrics import PROBE_SUCCESS, PROBE_DURATION, PROBE_LAST_RUN
from tools.web_search import search

log = logging.getLogger("brain")

TIMEOUT = 10.0
HELLO_TIMEOUT = 180.0  # A cold model takes as long to load as it takes
SEARCH_QUERY = "weather"

_reported = set()  # Provider checks with live gauges, to drop when the chain changes
_failing = set()


class ProbeFailed(Exception):
    """The dependency answered, and the answer was wrong."""


def _check_groq(provider) -> str:
    models = provider.client.with_options(timeout=TIMEOUT, max_retries=0).models.list()
    if not any(m.id == provider.model for m in models.data):
        raise ProbeFailed(f"model {provider.model} not listed")
    return f"model {provider.model} listed"


def _check_ollama(provider) -> str:
    model = provider.default_model
    response = httpx.get(f"{provider.url}/api/tags", timeout=TIMEOUT)
    response.raise_for_status()
    installed = {m["name"] for m in response.json().get("models", [])}
    if model not in installed and f"{model}:latest" not in installed:
        raise ProbeFailed(f"model {model} not installed")
    if not PROBE_OLLAMA_HELLO:
        return f"model {model} installed"

    response = httpx.post(
        f"{provider.url}/api/chat",
        json={
            "model": model,
            "messages": [{"role": "user", "content": "Say hello."}],
            "stream": False,
            "think": False,
            "options": {"num_predict": 8},
        },
        timeout=httpx.Timeout(HELLO_TIMEOUT, connect=TIMEOUT),
    )
    response.raise_for_status()
    if not response.json().get("eval_count"):
        raise ProbeFailed(f"model {model} generated nothing")
    return f"model {model} answered"


def _check_search() -> str:
    data = search(SEARCH_QUERY)
    results = data.get("results", [])
    if not results:
        down = [e[0] for e in data.get("unresponsive_engines", []) if e]
        raise ProbeFailed(f"no results, engines down: {', '.join(down) or 'none'}")
    return f"{len(results)} results"


_PROVIDER_CHECKS = {GroqProvider: ("groq", _check_groq), OllamaProvider: ("ollama", _check_ollama)}


def _why(e: Exception) -> str:
    """A status or a class name, never a message, which could quote a URL or a key."""
    status = getattr(e, "status_code", None) or getattr(getattr(e, "response", None), "status_code", None)
    return f"HTTP {status}" if status else type(e).__name__


def _run(name: str, check, *args) -> dict:
    """Run one check, record it, and never let it raise."""
    start = time.time()
    try:
        ok, detail = True, check(*args)
    except ProbeFailed as e:
        ok, detail = False, str(e)
    except Exception as e:
        ok, detail = False, _why(e)
    seconds = round(time.time() - start, 3)

    PROBE_SUCCESS.labels(check=name).set(1 if ok else 0)
    PROBE_DURATION.labels(check=name).set(seconds)
    PROBE_LAST_RUN.labels(check=name).set(time.time())
    if not ok:
        _failing.add(name)
        log.warning(f"Probe {name} failed: {detail}",
                    extra={"event": "probe_failed", "check": name, "detail": detail})
    elif name in _failing:
        _failing.discard(name)
        log.info(f"Probe {name} recovered: {detail}", extra={"event": "probe_recovered", "check": name})
    return {"check": name, "ok": ok, "detail": detail, "seconds": seconds}


def run(llm, include_search: bool = True) -> list:
    """Run the checks once, for the chain that is live now. Returns each result."""
    checks = [_PROVIDER_CHECKS[type(p)] + (p,) for p in getattr(llm, "providers", [llm])
              if type(p) in _PROVIDER_CHECKS]

    # A provider switched out of the chain must not leave a gauge stuck at its last value.
    active = {name for name, _, _ in checks}
    for name in _reported - active:
        for gauge in (PROBE_SUCCESS, PROBE_DURATION, PROBE_LAST_RUN):
            gauge.remove(name)
        _failing.discard(name)
    _reported.clear()
    _reported.update(active)

    results = [_run(name, check, provider) for name, check, provider in checks]
    if include_search:
        results.append(_run("search", _check_search))
    return results


def start(get_llm):
    """Run the checks on a timer if PROBE_INTERVAL_SECONDS is set. get_llm is
    called each time, so a live /admin/provider switch is followed."""
    if PROBE_INTERVAL_SECONDS <= 0:
        return

    def loop():
        last_search = None
        while True:
            search_due = (last_search is None
                          or time.monotonic() - last_search >= PROBE_SEARCH_INTERVAL_SECONDS)
            try:
                run(get_llm(), include_search=search_due)
                if search_due:
                    last_search = time.monotonic()
            except Exception as e:
                log.warning(f"Probe run failed: {type(e).__name__}", extra={"event": "probe_run_failed"})
            time.sleep(PROBE_INTERVAL_SECONDS)

    threading.Thread(target=loop, name="probes", daemon=True).start()
    log.info(f"Probes every {PROBE_INTERVAL_SECONDS}s, search every {PROBE_SEARCH_INTERVAL_SECONDS}s",
             extra={"event": "probes_started"})
