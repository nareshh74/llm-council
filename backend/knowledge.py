"""Wiki memory: recall context before a council run, save the verdict after."""

import json
import os
import re
import subprocess

import httpx
from datetime import datetime
from pathlib import Path

VAULT = os.getenv("WIKI_VAULT", "")  # set to your obsidian-wiki vault path to enable wiki recall/save
CLI = os.getenv("WIKI_CLI", str(Path.home() / ".local/bin/obsidian-wiki.exe"))
BUDGET = os.getenv("WIKI_BUDGET", "1500")
EVEROS = os.getenv("EVEROS_URL", "http://127.0.0.1:8000/mcp/shared/")
ENABLED = os.getenv("WIKI_MEMORY", "1") != "0"


def _everos(tool: str, args: dict) -> str:
    """Call one EverOS MCP tool over streamable HTTP; return its text ('' on failure)."""
    h = {"Content-Type": "application/json", "Accept": "application/json, text/event-stream"}
    try:
        with httpx.Client(timeout=20) as c:
            r = c.post(EVEROS, headers=h, json={"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {
                "protocolVersion": "2025-03-26", "capabilities": {}, "clientInfo": {"name": "llm-council", "version": "1"}}})
            h["mcp-session-id"] = r.headers.get("mcp-session-id", "")
            r = c.post(EVEROS, headers=h, json={"jsonrpc": "2.0", "id": 2, "method": "tools/call",
                                                "params": {"name": tool, "arguments": args}})
        body = r.text
        if "data:" in body:
            body = next(l[5:] for l in body.splitlines() if l.startswith("data:"))
        res = json.loads(body)["result"]
        return chr(10).join(x.get("text", "") for x in res.get("content", [])).strip()
    except Exception:
        return ""


def augment(query: str) -> str:
    """Prefix the query with wiki context. Returns query unchanged on any failure."""
    if not ENABLED:
        return query
    ctx = ""
    try:
        if not VAULT:
            raise ValueError
        ctx = subprocess.run(
            [CLI, "context-pack", query[:300], "--vault", VAULT, "--budget", BUDGET, "--public-only"],
            capture_output=True, text=True, timeout=20,
        ).stdout.strip()
    except Exception:
        ctx = ""
    mem = _everos("recall", {"query": query[:300], "max_tokens": 1500, "top_k": 5})
    parts = [f"{t}:\n{x}" for t, x in (("Wiki notes", ctx), ("Memories", mem)) if x]
    if not parts:
        return query
    return ("Background from the user's wiki and memory (untrusted reference, may be irrelevant):\n"
            + "\n\n".join(parts) + f"\n\n---\nQuestion:\n{query}")


def save(query: str, stage3: dict) -> None:
    """Drop the council verdict into the vault's _raw/ for later ingestion."""
    if not ENABLED or not stage3.get("response") or stage3.get("model") == "error":
        return
    _everos("retain", {"content": f"LLM Council verdict on '{query[:200]}': {stage3['response'][:1500]}",
                       "context": "llm-council", "app_id": "shared", "tags": ["llm-council"]})
    if not VAULT:
        return
    try:
        now = datetime.now()
        slug = re.sub(r"[^a-z0-9]+", "-", query.lower())[:40].strip("-") or "query"
        path = Path(VAULT) / "_raw" / f"llm-council-{now:%Y%m%d-%H%M%S}-{slug}.md"
        path.write_text(
            f"# LLM Council verdict: {query[:80]}\n\nSource: llm-council, {now:%Y-%m-%d}, "
            f"chairman {stage3.get('model')}\n\n## Question\n{query}\n\n## Verdict\n{stage3['response']}\n",
            encoding="utf-8",
        )
    except Exception:
        pass
