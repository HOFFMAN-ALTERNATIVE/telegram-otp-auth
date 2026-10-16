"""Local LLM + web search via tool calling.

The model (served by Ollama) decides when to call `web_search`; results come from a
self-hosted SearXNG instance. Nothing leaves your infrastructure except the search queries.

    python agent.py "What is the latest stable Python release?"
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
from dataclasses import dataclass
from typing import Any

import httpx

OLLAMA_URL = os.getenv("OLLAMA_URL", "http://127.0.0.1:11434")
SEARXNG_URL = os.getenv("SEARXNG_URL", "http://127.0.0.1:8888")
MODEL = os.getenv("MODEL", "qwen2.5:7b")  # any Ollama model with tool-calling support
MAX_STEPS = 4

SYSTEM = (
    "You are a research assistant. When a question needs current or factual information, "
    "call the web_search tool, then answer concisely and cite sources as [n] with URLs."
)

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "web_search",
            "description": "Search the web and return the top results (title, url, snippet).",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Search query"},
                    "max_results": {"type": "integer", "minimum": 1, "maximum": 10},
                },
                "required": ["query"],
            },
        },
    }
]


@dataclass
class SearchResult:
    title: str
    url: str
    snippet: str


async def web_search(http: httpx.AsyncClient, query: str, max_results: int = 5) -> list[SearchResult]:
    r = await http.get(
        f"{SEARXNG_URL}/search",
        params={"q": query, "format": "json", "safesearch": 1},
        timeout=20,
    )
    r.raise_for_status()
    results = r.json().get("results", [])[: max(1, min(max_results, 10))]
    return [
        SearchResult(x.get("title", ""), x.get("url", ""), (x.get("content") or "")[:300])
        for x in results
    ]


async def run(question: str, http: httpx.AsyncClient, verbose: bool = False) -> str:
    messages: list[dict[str, Any]] = [
        {"role": "system", "content": SYSTEM},
        {"role": "user", "content": question},
    ]
    for _ in range(MAX_STEPS):
        r = await http.post(
            f"{OLLAMA_URL}/api/chat",
            json={"model": MODEL, "messages": messages, "tools": TOOLS, "stream": False},
            timeout=300,
        )
        r.raise_for_status()
        msg = r.json()["message"]
        messages.append(msg)
        calls = msg.get("tool_calls") or []
        if not calls:
            return str(msg.get("content", "")).strip()
        for call in calls:
            fn = call["function"]
            args = fn.get("arguments") or {}
            if isinstance(args, str):
                args = json.loads(args)
            if fn["name"] != "web_search":
                content = json.dumps({"error": f"unknown tool {fn['name']}"})
            else:
                if verbose:
                    print(f"🔎 searching: {args.get('query')}")
                hits = await web_search(http, str(args["query"]), int(args.get("max_results", 5)))
                content = json.dumps([h.__dict__ for h in hits], ensure_ascii=False)
            messages.append({"role": "tool", "content": content, "name": fn["name"]})
    return "Stopped: too many tool calls."


async def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("question")
    p.add_argument("-v", "--verbose", action="store_true")
    a = p.parse_args()
    async with httpx.AsyncClient() as http:
        print(await run(a.question, http, a.verbose))


if __name__ == "__main__":
    asyncio.run(main())
