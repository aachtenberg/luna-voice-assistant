import httpx
from config import PROMETHEUS_URL


def query_prometheus(query: str) -> str:
    """Query Prometheus using PromQL."""
    try:
        response = httpx.get(
            f"{PROMETHEUS_URL}/api/v1/query",
            params={"query": query},
            timeout=10.0
        )
        response.raise_for_status()
        data = response.json()

        if data.get("status") != "success":
            return f"Query failed: {data.get('error', 'Unknown error')}"

        results = data.get("data", {}).get("result", [])
        if not results:
            return "No data found."

        formatted = []
        for r in results:
            metric = r.get("metric", {})
            value = r.get("value", [None, None])[1]
            label = metric.get("__name__", str(metric))
            formatted.append(f"{label}: {value}")

        return "\n".join(formatted)
    except Exception as e:
        return f"Prometheus error: {e}"
