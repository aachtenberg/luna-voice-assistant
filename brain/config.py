import os
from dotenv import load_dotenv

load_dotenv()

OLLAMA_URL = os.getenv("OLLAMA_URL", "http://192.168.0.198:11434")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "llama3.1:8b")

MQTT_BROKER = os.getenv("MQTT_BROKER", "192.168.0.167")
MQTT_PORT = int(os.getenv("MQTT_PORT", "1883"))

INFLUXDB_URL = os.getenv("INFLUXDB_URL", "http://192.168.0.167:8181")
INFLUXDB_TOKEN = os.getenv("INFLUXDB_TOKEN", "")
INFLUXDB_DATABASE = os.getenv("INFLUXDB_DATABASE", "temperature_data")

PROMETHEUS_URL = os.getenv("PROMETHEUS_URL", "http://192.168.0.167:9090")
SEARXNG_URL = os.getenv("SEARXNG_URL", "http://192.168.0.198:8089")

# Location for weather and local context
LOCATION_CITY = os.getenv("LOCATION_CITY", "Pembroke")
LOCATION_REGION = os.getenv("LOCATION_REGION", "Ontario")
LOCATION_COUNTRY = os.getenv("LOCATION_COUNTRY", "Canada")
LOCATION_TIMEZONE = os.getenv("LOCATION_TIMEZONE", "Eastern Time")
