from .web_search import web_search
from .prometheus import query_prometheus
from .influxdb import query_influxdb
from .mqtt import mqtt_publish
from .timers import set_timer, cancel_timer, list_timers
from .kasa import control_light, list_lights

TOOL_REGISTRY = {
    "web_search": web_search,
    "query_prometheus": query_prometheus,
    "query_influxdb": query_influxdb,
    "mqtt_publish": mqtt_publish,
    "set_timer": set_timer,
    "cancel_timer": cancel_timer,
    "list_timers": list_timers,
    "control_light": control_light,
    "list_lights": list_lights,
}
