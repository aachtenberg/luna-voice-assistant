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
            # Every engine suspended/CAPTCHA'd: say so, or the model keeps
            # rephrasing the query until it runs out of tool turns.
            down = [e[0] for e in data.get("unresponsive_engines", []) if e]
            if down:
                return ("Web search is unavailable right now (search engines are "
                        f"blocking requests: {', '.join(down)}). Do not search again; "
                        "tell the user you can't look that up at the moment.")
            return "No results found."

        summaries = []
        for r in results:
            title = r.get("title", "")
            content = r.get("content", "")
            summaries.append(f"- {title}: {content}")

        return "\n".join(summaries)
    except Exception as e:
        return f"Search error: {e}"
