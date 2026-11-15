"""OpenRouter API client for making LLM requests."""

import asyncio
import json
import httpx
from typing import List, Dict, Any, Optional
from .thinking import PROMPT as THINKING
from .workspace import current as workspace
from . import diagrams
from .config import OPENROUTER_API_KEY, OPENROUTER_API_URL

MAX_TOOL_ROUNDS = 8


async def query_model(
    model: str,
    messages: List[Dict[str, str]],
    timeout: float = 120.0,
    use_tools: bool = False,
    draw: bool = False
) -> Optional[Dict[str, Any]]:
    """
    Query a single model via OpenRouter API.

    Args:
        model: OpenRouter model identifier (e.g., "openai/gpt-4o")
        messages: List of message dicts with 'role' and 'content'
        timeout: Request timeout in seconds
        use_tools: Give the model the workspace folder context and tools (if a folder is set)
        draw: Give the model the draw_diagram tool

    Returns:
        Response dict with 'content' and optional 'reasoning_details', or None if failed
    """
    headers = {
        "Authorization": f"Bearer {OPENROUTER_API_KEY}",
        "Content-Type": "application/json",
    }

    ws = workspace.get() if use_tools else None
    drawn = []
    system = "\n\n".join(x for x in (THINKING, ws and ws.context) if x)
    if system:
        messages = [{"role": "system", "content": system}] + messages

    payload = {"model": model, "messages": messages}
    tools = (ws.schemas if ws else []) + ([diagrams.TOOL_SCHEMA] if draw else [])
    if tools:
        payload["tools"] = tools

    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            for i in range(MAX_TOOL_ROUNDS + 1):
                if i == MAX_TOOL_ROUNDS:
                    payload.pop("tools", None)  # out of rounds: force a text answer
                response = await client.post(OPENROUTER_API_URL, headers=headers, json=payload)
                response.raise_for_status()
                message = response.json()['choices'][0]['message']
                calls = message.get('tool_calls')
                if not (calls and "tools" in payload):
                    return {
                        'content': message.get('content'),
                        'reasoning_details': message.get('reasoning_details'),
                        'diagrams': drawn
                    }
                results = []
                for c in calls:
                    try:
                        args = json.loads(c['function'].get('arguments') or '{}')
                    except ValueError:
                        args = {}
                    name = c['function']['name']
                    if name == "draw_diagram":
                        try:
                            did = await asyncio.to_thread(diagrams.draw, args)
                            drawn.append(did)
                            out = f"Diagram created. Reference it in your answer as ![caption](diagram:{did})"
                        except ValueError as e:
                            print(f"draw_diagram failed: {e} | args={json.dumps(args)[:600]}")
                            out = f"error: {e}"
                    else:
                        out = await ws.call(name, args) if ws else f"unknown tool {name}"
                    results.append({"role": "tool", "tool_call_id": c['id'], "content": out})
                payload["messages"] = payload["messages"] + [
                    {"role": "assistant", "content": message.get('content'), "tool_calls": calls}
                ] + results

    except Exception as e:
        print(f"Error querying model {model}: {e}")
        return None


async def query_models_parallel(
    models: List[str],
    messages: List[Dict[str, str]],
    use_tools: bool = False
) -> Dict[str, Optional[Dict[str, Any]]]:
    """
    Query multiple models in parallel.

    Args:
        models: List of OpenRouter model identifiers
        messages: List of message dicts to send to each model
        use_tools: Pass through to query_model

    Returns:
        Dict mapping model identifier to response dict (or None if failed)
    """
    tasks = [query_model(model, messages, use_tools=use_tools) for model in models]
    responses = await asyncio.gather(*tasks)
    return {model: response for model, response in zip(models, responses)}
