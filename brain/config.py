import os
from pathlib import Path
import yaml
from dotenv import load_dotenv

load_dotenv()

# Load YAML config
_config_path = Path(__file__).parent / "config.yaml"
if _config_path.exists():
    with open(_config_path) as f:
        _yaml = yaml.safe_load(f) or {}
else:
    _yaml = {}

def _cfg(*keys, default=None):
    """Walk nested YAML keys, return default if missing."""
    node = _yaml
    for k in keys:
        if isinstance(node, dict):
            node = node.get(k)
        else:
            return default
        if node is None:
            return default
    return node

# LLM Provider: "ollama", "anthropic", or "groq"
LLM_PROVIDER = os.getenv("LLM_PROVIDER", "ollama")

# Ollama settings
OLLAMA_URL = os.getenv("OLLAMA_URL", "http://192.168.0.198:11434")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "qwen2.5:14b")

# Anthropic (Claude) settings
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
ANTHROPIC_MODEL = os.getenv("ANTHROPIC_MODEL", "claude-3-haiku-20240307")

# Groq settings
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
GROQ_MODEL = os.getenv("GROQ_MODEL", "llama-3.1-70b-versatile")

MQTT_BROKER = os.getenv("MQTT_BROKER", "192.168.0.167")
MQTT_PORT = int(os.getenv("MQTT_PORT", "1883"))

TIMESCALEDB_HOST = os.getenv("TIMESCALEDB_HOST", "192.168.0.146")
TIMESCALEDB_PORT = int(os.getenv("TIMESCALEDB_PORT", "5433"))
TIMESCALEDB_DATABASE = os.getenv("TIMESCALEDB_DATABASE", "sensors")
TIMESCALEDB_USER = os.getenv("TIMESCALEDB_USER", "telegraf")
TIMESCALEDB_PASSWORD = os.getenv("TIMESCALEDB_PASSWORD", "7OMyGmIG/5Ech8PYfvg1vykYffuaHNol")

PROMETHEUS_URL = os.getenv("PROMETHEUS_URL", "http://192.168.0.167:9090")
SEARXNG_URL = os.getenv("SEARXNG_URL", "http://192.168.0.198:8089")

# Location for weather and local context
LOCATION_CITY = os.getenv("LOCATION_CITY", "Pembroke")
LOCATION_REGION = os.getenv("LOCATION_REGION", "Ontario")
LOCATION_COUNTRY = os.getenv("LOCATION_COUNTRY", "Canada")
LOCATION_TIMEZONE = os.getenv("LOCATION_TIMEZONE", "Eastern Time")
LOCATION_LAT = float(os.getenv("LOCATION_LAT", "45.8167"))
LOCATION_LON = float(os.getenv("LOCATION_LON", "-77.1167"))

# Ollama tuning
OLLAMA_TIMEOUT_CONNECT = _cfg("ollama", "timeout_connect", default=10)
OLLAMA_TIMEOUT_READ = _cfg("ollama", "timeout_read", default=180)
OLLAMA_MAX_ITERATIONS = _cfg("ollama", "max_iterations", default=4)

# Anthropic tuning
ANTHROPIC_MAX_TOKENS = _cfg("anthropic", "max_tokens", default=1024)
ANTHROPIC_MAX_ITERATIONS = _cfg("anthropic", "max_iterations", default=5)

# Groq tuning
GROQ_MAX_TOKENS = _cfg("groq", "max_tokens", default=1024)
GROQ_MAX_ITERATIONS = _cfg("groq", "max_iterations", default=5)

# Conversation
MAX_HISTORY = _cfg("conversation", "max_history", default=12)

# Keepalive
KEEPALIVE_INTERVAL = _cfg("keepalive", "interval", default=180)
KEEPALIVE_NUM_PREDICT = _cfg("keepalive", "num_predict", default=1)
