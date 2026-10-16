import json

import httpx

import agent


def transport() -> httpx.MockTransport:
    state = {"calls": 0}

    def handler(req: httpx.Request) -> httpx.Response:
        if req.url.path == "/search":
            assert req.url.params["format"] == "json"
            return httpx.Response(200, json={"results": [
                {"title": "Python 9.9 released", "url": "https://example.org/py", "content": "Release notes"}]})
        if req.url.path == "/api/chat":
            body = json.loads(req.content)
            assert body["tools"][0]["function"]["name"] == "web_search"
            state["calls"] += 1
            if state["calls"] == 1:
                return httpx.Response(200, json={"message": {"role": "assistant", "content": "", "tool_calls": [
                    {"function": {"name": "web_search", "arguments": {"query": "latest python"}}}]}})
            tool_msg = body["messages"][-1]
            assert tool_msg["role"] == "tool"
            assert "example.org/py" in tool_msg["content"]
            return httpx.Response(200, json={"message": {"role": "assistant",
                                                          "content": "Python 9.9 [1] https://example.org/py"}})
        return httpx.Response(404)

    return httpx.MockTransport(handler)


async def test_tool_calling_loop() -> None:
    async with httpx.AsyncClient(transport=transport()) as http:
        answer = await agent.run("latest python?", http)
    assert "example.org/py" in answer


async def test_answers_without_tools() -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"message": {"role": "assistant", "content": "4"}})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        assert await agent.run("2+2?", http) == "4"
