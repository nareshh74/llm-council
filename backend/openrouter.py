"""OpenRouter API client for making LLM requests."""

import asyncio
import json
import time
import httpx
from typing import List, Dict, Any, Optional
from .thinking import PROMPT as THINKING
from .startup import PROMPT as STARTUP
from .workspace import current as workspace
from . import diagrams
from .activity import emit, new_id, clip
from .config import OPENROUTER_API_KEY, OPENROUTER_API_URL

MAX_TOOL_ROUNDS = 8


async def query_model(
    model: str,
    messages: List[Dict[str, str]],
    timeout: float = 120.0,
    use_tools: bool = False,
    draw: bool = False,
    style: bool = False
) -> Optional[Dict[str, Any]]:
    """
    Query a single model via OpenRouter API.

    Args:
        model: OpenRouter model identifier (e.g., "openai/gpt-4o")
        messages: List of message dicts with 'role' and 'content'
        timeout: Request timeout in seconds
        use_tools: Give the model the workspace folder context and tools (if a folder is set)
        draw: Give the model the draw_diagram tool
        style: Add the startup skills (used for the calls that write the answer the user reads)

    Returns:
        Response dict with 'content' and optional 'reasoning_details', or None if failed
    """
    headers = {
        "Authorization": f"Bearer {OPENROUTER_API_KEY}",
        "Content-Type": "application/json",
    }

    ws = workspace.get() if use_tools else None
    drawn = []
    system = "\n\n".join(x for x in (THINKING, STARTUP if style else "", ws and ws.context) if x)
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
                call_id, t0 = new_id(), time.perf_counter()
                emit("llm", id=call_id, model=model, round=i + 1, status="running")
                try:
                    response = await client.post(OPENROUTER_API_URL, headers=headers, json=payload)
                    response.raise_for_status()
                except Exception as e:
                    emit("llm", id=call_id, model=model, round=i + 1, status="error",
                         error=clip(e, 160), ms=int((time.perf_counter() - t0) * 1000))
                    raise
                message = response.json()['choices'][0]['message']
                calls = message.get('tool_calls')
                emit("llm", id=call_id, model=model, round=i + 1, status="done",
                     ms=int((time.perf_counter() - t0) * 1000),
                     chars=len(message.get('content') or ''), tool_calls=len(calls or []))
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
                    tool_id, t1 = new_id(), time.perf_counter()
                    shown = clip(json.dumps(args, ensure_ascii=False), 200)
                    emit("tool", id=tool_id, model=model, name=name, args=shown, status="running")
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
                    emit("tool", id=tool_id, model=model, name=name, args=shown,
                         status="error" if out.startswith("error") else "done",
                         ms=int((time.perf_counter() - t1) * 1000), chars=len(out), preview=clip(out, 400))
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
    use_tools: bool = False,
    style: bool = False
) -> Dict[str, Optional[Dict[str, Any]]]:
    """
    Query multiple models in parallel.

    Args:
        models: List of OpenRouter model identifiers
        messages: List of message dicts to send to each model
        use_tools: Pass through to query_model
        style: Pass through to query_model

    Returns:
        Dict mapping model identifier to response dict (or None if failed)
    """
    tasks = [query_model(model, messages, use_tools=use_tools, style=style) for model in models]
    responses = await asyncio.gather(*tasks)
    return {model: response for model, response in zip(models, responses)}
