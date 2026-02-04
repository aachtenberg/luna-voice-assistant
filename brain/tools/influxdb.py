import httpx
from config import INFLUXDB_URL, INFLUXDB_TOKEN, INFLUXDB_DATABASE


def query_influxdb(sql: str) -> str:
    """Query InfluxDB 3 using SQL."""
    print(f"[InfluxDB] Query: {sql}")
    try:
        response = httpx.post(
            f"{INFLUXDB_URL}/api/v3/query_sql",
            headers={
                "Authorization": f"Bearer {INFLUXDB_TOKEN}",
                "Content-Type": "application/json"
            },
            json={
                "db": INFLUXDB_DATABASE,
                "q": sql
            },
            timeout=10.0
        )
        if response.status_code != 200:
            print(f"[InfluxDB] Error {response.status_code}: {response.text}")
        response.raise_for_status()
        data = response.json()

        if not data:
            return "No data found."

        if isinstance(data, list):
            if len(data) > 10:
                data = data[:10]
            return "\n".join(str(row) for row in data)

        return str(data)
    except Exception as e:
        return f"InfluxDB error: {e}"
