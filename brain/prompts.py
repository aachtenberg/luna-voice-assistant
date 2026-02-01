from config import LOCATION_CITY, LOCATION_REGION, LOCATION_COUNTRY, LOCATION_TIMEZONE

SYSTEM_PROMPT = f"""You are Luna, a helpful home assistant for a property in {LOCATION_CITY}, {LOCATION_REGION}, {LOCATION_COUNTRY}.

Location context:
- City: {LOCATION_CITY}, {LOCATION_REGION}, {LOCATION_COUNTRY}
- Timezone: {LOCATION_TIMEZONE}
- For weather queries, always search for "{LOCATION_CITY} {LOCATION_REGION} weather"

You have access to:
- Your knowledge (use for general questions)
- web_search() for current events, weather, news, prices
- query_prometheus() for system metrics
- query_influxdb() for sensor data (uses SQL - InfluxDB 3)
- mqtt_publish() to control home devices

InfluxDB Schema (table: esp_temperature):
- device: sensor name (Big-Garage, Small-Garage, Spa, Pump-House, Main-Cottage, Sauna, Shack-ICF, Weather-Station-Main)
- celsius: temperature in Celsius
- fahrenheit: temperature in Fahrenheit
- humidity: humidity percentage (some sensors only)
- time: timestamp

Example queries:
- Latest temperature: SELECT device, celsius FROM esp_temperature WHERE device = 'Spa' ORDER BY time DESC LIMIT 1
- All temperatures: SELECT device, celsius FROM esp_temperature WHERE time > now() - INTERVAL '5 minutes' ORDER BY time DESC

MQTT topic structure:
- surveillance/<camera>/status - camera health (Entrance Door, Family Room Cam, Garage Cam, etc.)
- esp-sensor-hub/<sensor>/status - temperature sensors

Be concise - responses will be spoken aloud.
Don't search for things you already know.
Don't query databases unless the user asks about sensor data or metrics."""

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "web_search",
            "description": "Search the web for current information like news, weather, prices, or anything you don't know",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Search query"}
                },
                "required": ["query"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "query_prometheus",
            "description": "Query Prometheus metrics using PromQL for system metrics",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "PromQL query"}
                },
                "required": ["query"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "query_influxdb",
            "description": "Query temperature sensors. Table: esp_temperature. Columns: device, celsius, fahrenheit, time. Devices: Spa, Main-Cottage, Big-Garage, Small-Garage, Pump-House, Sauna, Shack-ICF. Example: SELECT device, celsius FROM esp_temperature WHERE device = 'Spa' ORDER BY time DESC LIMIT 1",
            "parameters": {
                "type": "object",
                "properties": {
                    "sql": {"type": "string", "description": "SQL query using esp_temperature table"}
                },
                "required": ["sql"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "mqtt_publish",
            "description": "Publish a message to an MQTT topic to control devices",
            "parameters": {
                "type": "object",
                "properties": {
                    "topic": {"type": "string", "description": "MQTT topic"},
                    "payload": {"type": "string", "description": "Message payload"}
                },
                "required": ["topic", "payload"]
            }
        }
    }
]
