"""Folder context for the council: instructions, skills, read-only file tools, MCP tools."""

import json
import os
import re
from contextlib import AsyncExitStack, asynccontextmanager
from contextvars import ContextVar
from pathlib import Path

FOLDER = os.getenv("COUNCIL_FOLDER", "")
ROOTS = [r for r in os.getenv("COUNCIL_FOLDER_ROOTS", "").split(os.pathsep) if r]
MAX_OUT = 20000
current: ContextVar = ContextVar("workspace", default=None)


def _fn(name, desc, props, req):
    return {"type": "function", "function": {"name": name, "description": desc, "parameters": {
        "type": "object", "properties": {k: {"type": "string"} for k in props}, "required": req}}}


BUILTIN = [
    _fn("list_dir", "List files in a folder (relative to the workspace root).", ["path"], []),
    _fn("read_file", "Read a text file (relative to the workspace root).", ["path"], ["path"]),
    _fn("search", "Regex search across workspace text files; returns file:line:text.", ["pattern"], ["pattern"]),
    _fn("read_skill", "Load the full instructions of a named skill.", ["name"], ["name"]),
]


class Workspace:
    def __init__(self, root: Path):
        self.root = root.resolve()
        self.schemas = list(BUILTIN)
        self.mcp = {}  # exposed tool name -> (session, mcp tool name)
        self.skills = {}  # name -> SKILL.md path
        self.context = ""

    def _safe(self, p: str) -> Path:
        full = (self.root / (p or ".")).resolve()
        if not full.is_relative_to(self.root):
            raise ValueError("path outside workspace")
        return full

    async def load(self, stack: AsyncExitStack) -> None:
        parts = []
        for name in ("AGENTS.md", "CLAUDE.md"):
            f = self.root / name
            if f.is_file():
                text = f.read_text(encoding="utf-8", errors="replace")[:MAX_OUT]
                parts.append(f"Workspace instructions ({name}):\n{text}")
                break
        lines = []
        for base in (".claude/skills", "skills"):
            for f in sorted((self.root / base).glob("*/SKILL.md")):
                m = re.search(r"^description:\s*(.+)$", f.read_text(encoding="utf-8", errors="replace"), re.M)
                self.skills[f.parent.name] = f
                lines.append(f"- {f.parent.name}: {m.group(1).strip() if m else ''}")
        if lines:
            parts.append("Workspace skills (call read_skill to load one when relevant):\n" + "\n".join(lines))
        parts.insert(0, f"You are working in the folder '{self.root.name}'. "
                        "Use list_dir, read_file and search (read-only) to inspect it when relevant.")
        self.context = "\n\n".join(parts)
        await self._load_mcp(stack)

    async def _load_mcp(self, stack: AsyncExitStack) -> None:
        cfg = self.root / ".mcp.json"
        if not cfg.is_file():
            return
        from mcp import ClientSession, StdioServerParameters
        from mcp.client.stdio import stdio_client
        from mcp.client.streamable_http import streamablehttp_client

        for server, c in json.loads(cfg.read_text(encoding="utf-8")).get("mcpServers", {}).items():
            try:
                if c.get("url"):
                    r, w, _ = await stack.enter_async_context(streamablehttp_client(c["url"], headers=c.get("headers")))
                else:
                    params = StdioServerParameters(command=c["command"], args=c.get("args", []),
                                                   env={**os.environ, **c.get("env", {})}, cwd=str(self.root))
                    r, w = await stack.enter_async_context(stdio_client(params))
                s = await stack.enter_async_context(ClientSession(r, w))
                await s.initialize()
                for t in (await s.list_tools()).tools:
                    name = re.sub(r"[^a-zA-Z0-9_-]", "_", f"{server}__{t.name}")[:64]
                    self.mcp[name] = (s, t.name)
                    self.schemas.append({"type": "function", "function": {
                        "name": name, "description": t.description or "", "parameters": t.inputSchema}})
            except Exception as e:
                print(f"MCP server {server} failed: {e}")

    async def call(self, name: str, args: dict) -> str:
        try:
            if name in self.mcp:
                s, tool = self.mcp[name]
                res = await s.call_tool(tool, args)
                out = "\n".join(getattr(x, "text", "") for x in res.content)
            elif name == "list_dir":
                items = sorted(self._safe(args.get("path", "")).iterdir())
                out = "\n".join(p.name + ("/" if p.is_dir() else "") for p in items)
            elif name == "read_file":
                out = self._safe(args["path"]).read_text(encoding="utf-8", errors="replace")
            elif name == "search":
                rx, hits = re.compile(args["pattern"]), []
                skip = (".git", "node_modules", ".venv", "__pycache__")
                for f in self.root.rglob("*"):
                    if f.is_file() and not any(p in skip for p in f.parts) and f.stat().st_size < 500_000:
                        for i, line in enumerate(f.read_text(encoding="utf-8", errors="ignore").splitlines(), 1):
                            if rx.search(line):
                                hits.append(f"{f.relative_to(self.root)}:{i}:{line[:200]}")
                    if len(hits) > 200:
                        break
                out = "\n".join(hits[:200])
            elif name == "read_skill":
                out = self.skills[args["name"]].read_text(encoding="utf-8", errors="replace")
            else:
                out = f"unknown tool {name}"
        except Exception as e:
            out = f"error: {e}"
        return out[:MAX_OUT]


def allowed_roots() -> list:
    return [Path(r).resolve() for r in ROOTS + ([FOLDER] if FOLDER else []) if Path(r).is_dir()]


def resolve_folder(folder: str) -> str:
    """Return the resolved folder if it is a directory under COUNCIL_FOLDER or a COUNCIL_FOLDER_ROOTS entry."""
    p = Path(folder).resolve()
    if not p.is_dir() or not any(p.is_relative_to(a) for a in allowed_roots()):
        raise ValueError("folder must be an existing directory under COUNCIL_FOLDER_ROOTS")
    return str(p)


def browse(path: str = "") -> dict:
    """List the subfolders of path for the folder picker. Empty path lists the allowed roots."""
    roots = allowed_roots()
    if not path:
        return {"path": None, "parent": None,
                "dirs": [{"name": r.name or str(r), "path": str(r)} for r in roots]}
    p = Path(resolve_folder(path))
    skip = {"node_modules", "__pycache__"}
    dirs = []
    for c in sorted(p.iterdir(), key=lambda x: x.name.lower()):
        try:
            if c.is_dir() and not c.name.startswith(".") and c.name not in skip:
                dirs.append({"name": c.name, "path": str(c)})
        except OSError:
            continue
    parent = p.parent if any(p != r and p.is_relative_to(r) for r in roots) else None
    return {"path": str(p), "parent": str(parent) if parent else None, "dirs": dirs[:500]}


@asynccontextmanager
async def open_workspace(folder: str = ""):
    """Load a conversation's folder (default COUNCIL_FOLDER) for one request; yields None when there is none."""
    folder = folder or FOLDER
    if not folder or not Path(folder).is_dir():
        yield None
        return
    async with AsyncExitStack() as stack:
        ws = Workspace(Path(folder))
        await ws.load(stack)
        token = current.set(ws)
        try:
            yield ws
        finally:
            current.reset(token)
