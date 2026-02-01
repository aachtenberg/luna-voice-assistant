import httpx
from config import SEARXNG_URL


def web_search(query: str) -> str:
    """Search the web using SearXNG."""
    try:
        response = httpx.get(
            f"{SEARXNG_URL}/search",
            params={"q": query, "format": "json"},
            timeout=10.0
        )
        response.raise_for_status()
        data = response.json()

        results = data.get("results", [])[:5]
        if not results:
            return "No results found."

        summaries = []
        for r in results:
            title = r.get("title", "")
            content = r.get("content", "")
            summaries.append(f"- {title}: {content}")

        return "\n".join(summaries)
    except Exception as e:
        return f"Search error: {e}"
