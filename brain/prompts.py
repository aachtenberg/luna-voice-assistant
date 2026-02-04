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
- set_timer() to set timers/reminders
- cancel_timer() to cancel a timer
- list_timers() to show active timers
- control_light() to turn lights on/off (kitchen, patio, living room)
- list_lights() to see all lights and their status

Smart Lights:
- Kitchen, Patio: on/off switches (Kasa)
- Living room: 2 WiZ bulbs controlled together. Supports: on, off, bright (bright white), soft/warm (soft white), dim, or specific brightness percentage

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
Don't query databases unless the user asks about sensor data or metrics.

IMPORTANT: Always respond in natural spoken language. Never output raw JSON, code, or technical data.
When a tool returns a result, rephrase it conversationally (e.g., "I've set a timer for 20 seconds")."""

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
            "description": "Query temperature sensors. ALWAYS use this exact format: SELECT device, celsius FROM esp_temperature WHERE device = '<DeviceName>' ORDER BY time DESC LIMIT 1. Valid device names: Spa, Main-Cottage, Big-Garage, Small-Garage, Pump-House, Sauna, Shack-ICF, Weather-Station-Main. For all sensors: SELECT device, celsius FROM esp_temperature WHERE time > now() - INTERVAL '5 minutes' ORDER BY time DESC",
            "parameters": {
                "type": "object",
                "properties": {
                    "sql": {"type": "string", "description": "SQL query - MUST use table 'esp_temperature' with columns: device, celsius, fahrenheit, time"}
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
    },
    {
        "type": "function",
        "function": {
            "name": "set_timer",
            "description": "Set a timer or reminder. Examples: 'set a timer for 5 minutes', 'remind me in 30 seconds', 'timer for 1 hour called pasta'",
            "parameters": {
                "type": "object",
                "properties": {
                    "duration": {"type": "string", "description": "Duration like '5 minutes', '30 seconds', '1 hour'"},
                    "name": {"type": "string", "description": "Optional name for the timer (e.g., 'pasta', 'laundry')"}
                },
                "required": ["duration"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "cancel_timer",
            "description": "Cancel an active timer by name",
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "Name of timer to cancel, or empty for most recent"}
                },
                "required": []
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "list_timers",
            "description": "List all active timers and their remaining time",
            "parameters": {
                "type": "object",
                "properties": {},
                "required": []
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "control_light",
            "description": "Control smart lights. Available: kitchen, patio (on/off switches), living room (WiZ bulbs with brightness/color control)",
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "Light name: kitchen, patio, living room"},
                    "action": {"type": "string", "description": "Action: on, off, toggle, status. For living room also: bright (bright white), soft/warm (soft white), dim"},
                    "brightness": {"type": "integer", "description": "Optional brightness percentage 1-100 for living room"}
                },
                "required": ["name", "action"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "list_lights",
            "description": "List all smart lights and their current on/off status",
            "parameters": {
                "type": "object",
                "properties": {},
                "required": []
            }
        }
    }
]
