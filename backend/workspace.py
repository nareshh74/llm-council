"""Folder context for the council: instructions, skills, read-only file tools, MCP tools."""

import json
import os
import re
from contextlib import AsyncExitStack, asynccontextmanager
from contextvars import ContextVar
from pathlib import Path

from .readguard import resolve, denied
FOLDER = os.getenv("COUNCIL_FOLDER", "")
MAX_OUT = 20000
MAX_SCAN = 5000
current: ContextVar = ContextVar("workspace", default=None)


def _fn(name, desc, props, req):
    return {"type": "function", "function": {"name": name, "description": desc, "parameters": {
        "type": "object", "properties": {k: {"type": "string"} for k in props}, "required": req}}}


BUILTIN = [
    _fn("list_dir", "List a folder. The path is relative to the workspace root, or absolute to reach anywhere on the machine.", ["path"], []),
    _fn("read_file", "Read a text file. The path is relative to the workspace root, or absolute to reach anywhere on the machine.", ["path"], ["path"]),
    _fn("search", "Regex search across text files under a folder (default: the workspace root); returns file:line:text.", ["pattern", "path"], ["pattern"]),
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
        return resolve(self.root, p)

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
                        "Use list_dir, read_file and search (read-only) to inspect it when relevant. "
                        "Relative paths start there. Use an absolute path to read anywhere else on the machine; "
                        "files that look like secrets (keys, .env, credentials) are blocked.")
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
                with open(self._safe(args["path"]), encoding="utf-8", errors="replace") as fh:
                    out = fh.read(MAX_OUT)
            elif name == "search":
                rx, hits, scanned = re.compile(args["pattern"]), [], 0
                base = self._safe(args.get("path", ""))
                skip = (".git", "node_modules", ".venv", "__pycache__")
                files = [base] if base.is_file() else base.rglob("*")
                for f in files:
                    rel = f.relative_to(base) if f != base else Path(f.name)
                    if f.is_file() and not any(p in skip for p in rel.parts) and f.stat().st_size < 500_000 and not denied(f.resolve()):
                        scanned += 1
                        for i, line in enumerate(f.read_text(encoding="utf-8", errors="ignore").splitlines(), 1):
                            if rx.search(line):
                                hits.append(f"{rel}:{i}:{line[:200]}")
                    if len(hits) > 200 or scanned >= MAX_SCAN:
                        break
                out = "\n".join(hits[:200])
                if scanned >= MAX_SCAN:
                    out += f"\n[stopped after scanning {MAX_SCAN} files; search a narrower folder]"
            elif name == "read_skill":
                out = self.skills[args["name"]].read_text(encoding="utf-8", errors="replace")
            else:
                out = f"unknown tool {name}"
        except Exception as e:
            out = f"error: {e}"
        return out[:MAX_OUT]


def resolve_folder(folder: str) -> str:
    """Return the resolved folder if it is an existing directory."""
    p = Path(folder).resolve()
    if not p.is_dir():
        raise ValueError("folder must be an existing directory")
    return str(p)


def browse(path: str = "") -> dict:
    """List the subfolders of path for the folder picker. Empty path starts at COUNCIL_FOLDER or the home folder."""
    p = Path(resolve_folder(path or FOLDER or str(Path.home())))
    skip = {"node_modules", "__pycache__"}
    dirs = []
    for c in sorted(p.iterdir(), key=lambda x: x.name.lower()):
        try:
            if c.is_dir() and not c.name.startswith(".") and c.name not in skip:
                dirs.append({"name": c.name, "path": str(c)})
        except OSError:
            continue
    return {"path": str(p), "parent": str(p.parent) if p.parent != p else None, "dirs": dirs[:500]}


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
