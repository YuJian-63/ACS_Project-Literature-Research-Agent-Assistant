"""Tavily search, usable by both the CLI and the research workflow."""

import argparse
import asyncio
import json
import os

from langchain_tavily import TavilySearch

from config import load_env


def search_web(
    query: str,
    max_results: int = 5,
    include_domains: list[str] | None = None,
    *,
    timeout: float = 60,
) -> dict:
    """Return Tavily's response, including ranked source URLs and snippets."""
    if not query.strip():
        raise ValueError("Search query must not be empty")
    if not 1 <= max_results <= 20:
        raise ValueError("max_results must be between 1 and 20")
    if timeout <= 0:
        raise ValueError("timeout must be positive")
    load_env()
    if not os.environ.get("TAVILY_API_KEY"):
        raise ValueError("Set TAVILY_API_KEY in agent/.env")
    tool = TavilySearch(
        max_results=max_results,
        topic="general",
        search_depth="basic",
        include_answer=False,
        include_raw_content=False,
        include_domains=include_domains,
    )

    # The sync integration has no HTTP timeout; cancelling its aiohttp path
    # closes the request and bounds the complete search operation.
    async def invoke() -> dict:
        return await asyncio.wait_for(tool.ainvoke({"query": query.strip()}), timeout=timeout)

    result = asyncio.run(invoke())
    if isinstance(result, str):
        result = json.loads(result)
    if not isinstance(result, dict) or "results" not in result:
        detail = str(result.get("error", result) if isinstance(result, dict) else result)
        detail = detail.replace(os.environ["TAVILY_API_KEY"], "[redacted]")
        raise RuntimeError(f"Tavily search failed: {detail[:500]}")
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("query")
    parser.add_argument("--max-results", type=int, default=5)
    parser.add_argument("--domains", nargs="+")
    parser.add_argument("--timeout", type=float, default=60)
    args = parser.parse_args()
    print(
        json.dumps(
            search_web(args.query, args.max_results, args.domains, timeout=args.timeout),
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
