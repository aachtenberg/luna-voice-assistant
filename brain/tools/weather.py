import httpx
from config import LOCATION_LAT, LOCATION_LON, LOCATION_CITY

# WMO weather codes to descriptions
WMO_CODES = {
    0: "clear sky",
    1: "mainly clear", 2: "partly cloudy", 3: "overcast",
    45: "foggy", 48: "depositing rime fog",
    51: "light drizzle", 53: "moderate drizzle", 55: "dense drizzle",
    56: "light freezing drizzle", 57: "dense freezing drizzle",
    61: "slight rain", 63: "moderate rain", 65: "heavy rain",
    66: "light freezing rain", 67: "heavy freezing rain",
    71: "slight snow", 73: "moderate snow", 75: "heavy snow",
    77: "snow grains",
    80: "slight rain showers", 81: "moderate rain showers", 82: "violent rain showers",
    85: "slight snow showers", 86: "heavy snow showers",
    95: "thunderstorm", 96: "thunderstorm with slight hail", 99: "thunderstorm with heavy hail",
}


def get_weather() -> str:
    """Get current weather and forecast for the configured location using Open-Meteo API."""
    try:
        response = httpx.get(
            "https://api.open-meteo.com/v1/forecast",
            params={
                "latitude": LOCATION_LAT,
                "longitude": LOCATION_LON,
                "current": "temperature_2m,relative_humidity_2m,apparent_temperature,precipitation,weather_code,wind_speed_10m,wind_gusts_10m",
                "daily": "weather_code,temperature_2m_max,temperature_2m_min,precipitation_sum,precipitation_probability_max,wind_speed_10m_max",
                "temperature_unit": "celsius",
                "wind_speed_unit": "kmh",
                "precipitation_unit": "mm",
                "timezone": "America/Toronto",
                "forecast_days": 3
            },
            timeout=10.0
        )
        response.raise_for_status()
        data = response.json()

        current = data.get("current", {})
        daily = data.get("daily", {})

        # Current conditions
        temp_c = current.get("temperature_2m")
        feels_c = current.get("apparent_temperature")
        humidity = current.get("relative_humidity_2m")
        weather_code = current.get("weather_code", 0)
        conditions = WMO_CODES.get(weather_code, "unknown")
        wind_kmh = current.get("wind_speed_10m")
        gusts_kmh = current.get("wind_gusts_10m")
        precip_mm = current.get("precipitation", 0)

        result = f"Current weather in {LOCATION_CITY}:\n"
        result += f"- Conditions: {conditions}\n"
        result += f"- Temperature: {temp_c:.0f} degrees (feels like {feels_c:.0f} degrees)\n"
        result += f"- Humidity: {humidity}%\n"
        result += f"- Wind: {wind_kmh:.0f} km/h"
        if gusts_kmh and gusts_kmh > wind_kmh + 8:
            result += f" (gusts to {gusts_kmh:.0f} km/h)"
        result += "\n"
        if precip_mm > 0:
            result += f"- Precipitation: {precip_mm:.1f} mm\n"

        # Daily forecast
        if daily.get("time"):
            result += "\nForecast:\n"
            for i, date in enumerate(daily["time"][:3]):
                day_name = "Today" if i == 0 else ("Tomorrow" if i == 1 else date)
                high_c = daily["temperature_2m_max"][i]
                low_c = daily["temperature_2m_min"][i]
                code = daily["weather_code"][i]
                day_conditions = WMO_CODES.get(code, "unknown")
                precip_prob = daily.get("precipitation_probability_max", [0]*3)[i]

                result += f"- {day_name}: {day_conditions}, high {high_c:.0f} degrees, low {low_c:.0f} degrees"
                if precip_prob and precip_prob > 20:
                    result += f", {precip_prob}% chance of precipitation"
                result += "\n"

        return result

    except Exception as e:
        return f"Weather error: {e}"
