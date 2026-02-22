from .web_search import web_search
from .prometheus import query_prometheus
from .timescaledb import query_timescaledb
from .mqtt import mqtt_publish
from .timers import set_timer, cancel_timer, list_timers
from .kasa import control_light, list_lights
from .weather import get_weather

TOOL_REGISTRY = {
    "web_search": web_search,
    "query_prometheus": query_prometheus,
    "query_timescaledb": query_timescaledb,
    "mqtt_publish": mqtt_publish,
    "set_timer": set_timer,
    "cancel_timer": cancel_timer,
    "list_timers": list_timers,
    "control_light": control_light,
    "list_lights": list_lights,
    "get_weather": get_weather,
}
