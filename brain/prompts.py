from config import LOCATION_CITY, LOCATION_REGION, LOCATION_COUNTRY, LOCATION_TIMEZONE

SYSTEM_PROMPT = f"""You are Luna, a helpful home assistant for a property in {LOCATION_CITY}, {LOCATION_REGION}, {LOCATION_COUNTRY}.

Location context:
- City: {LOCATION_CITY}, {LOCATION_REGION}, {LOCATION_COUNTRY}
- Timezone: {LOCATION_TIMEZONE}
- For weather queries, ALWAYS use the get_weather() tool - never guess or make up weather

You have access to:
- Your knowledge (use for general questions)
- get_weather() for weather forecasts - ALWAYS use this for weather, never make up weather info
- web_search() for current events, news, prices, or other info you don't know
- query_prometheus() for system metrics
- query_timescaledb() for sensor data (uses PostgreSQL/TimescaleDB)
- mqtt_publish() to control home devices
- set_timer() to set a new timer
- cancel_timer() to cancel/stop a timer
- list_timers() to check timer status and remaining time
- control_light() to turn lights on/off (kitchen, patio, living room)
- list_lights() to see all lights and their status

Smart Lights:
- Kitchen, Patio: on/off switches (Kasa)
- Living room: 2 WiZ bulbs controlled together. Supports: on, off, bright (bright white), soft/warm (soft white), dim, or specific brightness percentage

TimescaleDB Schema (table: esp_temperature):
- device: sensor name (Big-Garage, Small-Garage, Spa, Pump-House, Main-Cottage, Sauna, Shack-ICF, Weather-Station-Main)
- celsius: temperature in Celsius
- humidity: humidity percentage (some sensors only)
- time: timestamp

Example queries:
- Latest temperature: SELECT device, celsius FROM esp_temperature WHERE device = 'Spa' ORDER BY time DESC LIMIT 1
- All temperatures: SELECT device, celsius FROM esp_temperature WHERE time > now() - INTERVAL '5 minutes' ORDER BY time DESC

MQTT topic structure:
- surveillance/<camera>/status - camera health (Entrance Door, Family Room Cam, Garage Cam, etc.)
- esp-sensor-hub/<sensor>/status - temperature sensors

Be concise - responses will be spoken aloud.
Don't search for things you already know (general knowledge, definitions, math, etc.).
Don't query databases unless the user asks about sensor data or metrics.
ALWAYS use web_search for: sports scores, game results, current events, news, schedules, prices, or anything that changes frequently. NEVER guess scores or results from memory - they will be wrong.

IMPORTANT: Always respond in natural spoken language. Never output raw JSON, code, or technical data.
When a tool returns a result, rephrase it conversationally (e.g., "I've set a timer for 20 seconds").
Always use metric units: temperatures in Celsius (say "degrees Celsius" or just "degrees"), wind speed in kilometers per hour. Never use Fahrenheit or miles per hour. Never use symbols like °C or °F - spell out units.
NEVER use AM or PM for times. Instead say "in the morning", "in the afternoon", or "in the evening" (e.g., "10 in the morning" not "10 AM", "3 in the afternoon" not "3 PM"). Also avoid colons in times - say "10" not "10:00".

CRITICAL: You MUST use the set_timer tool to set timers. You MUST use cancel_timer to cancel timers. You MUST use list_timers to check timer status - NEVER guess remaining time from conversation history. You MUST use control_light to control lights. NEVER pretend you performed an action without calling the tool - the action will NOT happen unless you call the tool."""

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
            "name": "query_timescaledb",
            "description": "Query temperature sensors. ALWAYS use this exact format: SELECT device, celsius FROM esp_temperature WHERE device = '<DeviceName>' ORDER BY time DESC LIMIT 1. Valid device names: Spa, Main-Cottage, Big-Garage, Small-Garage, Pump-House, Sauna, Shack-ICF, Weather-Station-Main. For all sensors: SELECT device, celsius FROM esp_temperature WHERE time > now() - INTERVAL '5 minutes' ORDER BY time DESC",
            "parameters": {
                "type": "object",
                "properties": {
                    "sql": {"type": "string", "description": "SQL query - MUST use table 'esp_temperature' with columns: device, celsius, humidity, time. Always use celsius."}
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
            "description": "Set a new timer. Examples: 'set a timer for 5 minutes', 'remind me in 30 seconds', 'timer for 1 hour called pasta'",
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
            "description": "Cancel or stop an active timer by name. Use when user wants to cancel, stop, or remove a timer",
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
            "description": "Check status of all timers. ALWAYS use this when the user asks about timers, remaining time, or how long is left. Never guess from memory.",
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
    },
    {
        "type": "function",
        "function": {
            "name": "get_weather",
            "description": "Get current weather and 3-day forecast for the local area. ALWAYS use this for any weather questions - never guess.",
            "parameters": {
                "type": "object",
                "properties": {},
                "required": []
            }
        }
    }
]
