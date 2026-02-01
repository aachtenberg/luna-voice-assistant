from .web_search import web_search
from .prometheus import query_prometheus
from .influxdb import query_influxdb
from .mqtt import mqtt_publish

TOOL_REGISTRY = {
    "web_search": web_search,
    "query_prometheus": query_prometheus,
    "query_influxdb": query_influxdb,
    "mqtt_publish": mqtt_publish,
}
