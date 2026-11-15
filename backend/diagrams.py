"""draw_diagram: compile a small node/edge spec into a validated Archify workflow diagram (standalone HTML)."""

import json
import os
import re
import shutil
import subprocess
import uuid
from pathlib import Path

ARCHIFY = Path(os.getenv("ARCHIFY_BIN", Path.home() / ".claude/skills/archify/bin/archify.mjs"))
OUT_DIR = Path(os.getenv("COUNCIL_DIAGRAM_DIR", "data/diagrams"))
TYPES = {"external", "frontend", "backend", "database", "cloud", "security", "messagebus"}
MAX_NODES = 24

TOOL_SCHEMA = {"type": "function", "function": {
    "name": "draw_diagram",
    "description": ("Draw a flow diagram to explain an idea visually. Returns a diagram id; reference it in "
                    "your answer as ![caption](diagram:ID). Use for architectures, pipelines and step-by-step "
                    "flows with at most 24 nodes."),
    "parameters": {"type": "object", "required": ["title", "nodes", "edges"], "properties": {
        "title": {"type": "string"},
        "nodes": {"type": "array", "items": {"type": "object", "required": ["id", "label"], "properties": {
            "id": {"type": "string"}, "label": {"type": "string"}, "sublabel": {"type": "string"},
            "type": {"type": "string", "enum": sorted(TYPES)}}}},
        "edges": {"type": "array", "items": {"type": "object", "required": ["from", "to"], "properties": {
            "from": {"type": "string"}, "to": {"type": "string"}, "label": {"type": "string"}}}}}}}}


def _slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")[:40] or "n"


def compile_spec(spec: dict) -> dict:
    """Turn {title, nodes, edges} into an Archify workflow spec. Raises ValueError on a bad spec."""
    nodes, edges = spec.get("nodes") or [], spec.get("edges") or []
    if not nodes or len(nodes) > MAX_NODES:
        raise ValueError(f"need 1 to {MAX_NODES} nodes")
    ids = {}
    for n in nodes:
        if not n.get("id") or not n.get("label"):
            raise ValueError("every node needs id and label")
        if n["id"] in ids:
            raise ValueError(f"duplicate node id {n['id']}")
        ids[n["id"]] = _slug(str(n["id"])) + "-" + str(len(ids))
    for e in edges:
        if e.get("from") not in ids or e.get("to") not in ids:
            raise ValueError(f"edge {e.get('from')}->{e.get('to')} names an unknown node")

    # column = longest path from a source, with back edges (cycles) ignored via DFS order
    state, back = {}, set()

    def dfs(u):
        state[u] = 1
        for e in edges:
            if e["from"] == u:
                v = e["to"]
                if state.get(v) == 1:
                    back.add((u, v))
                elif v not in state:
                    dfs(v)
        state[u] = 2

    for n in nodes:
        if n["id"] not in state:
            dfs(n["id"])
    col = {n["id"]: 0 for n in nodes}
    for _ in range(len(nodes)):
        for e in edges:
            if (e["from"], e["to"]) not in back and e["from"] != e["to"]:
                col[e["to"]] = max(col[e["to"]], col[e["from"]] + 1)

    if max(col.values()) > 5:
        raise ValueError("diagram is too deep: at most 6 steps from start to end")
    # one lane per row: nodes that share a column stack in separate lanes
    rows = {}
    row = {}
    for n in nodes:
        row[n["id"]] = rows.get(col[n["id"]], 0)
        rows[col[n["id"]]] = row[n["id"]] + 1
    lane_count = max(rows.values())
    lane_id = {i: f"row{i + 1}" for i in range(lane_count)}

    out_nodes = []
    for n in nodes:
        t = n.get("type") if n.get("type") in TYPES else "backend"
        o = {"id": ids[n["id"]], "lane": lane_id[row[n["id"]]], "col": col[n["id"]], "type": t,
             "label": str(n["label"])[:40], "width": 148}
        if n.get("sublabel"):
            o["sublabel"] = str(n["sublabel"])[:40]
        out_nodes.append(o)
    out_edges = []
    for i, e in enumerate(edges):
        o = {"id": f"e{i}", "from": ids[e["from"]], "to": ids[e["to"]],
             "variant": "dashed" if (e["from"], e["to"]) in back else "default"}
        if e.get("label"):
            o["label"] = str(e["label"])[:28]
        out_edges.append(o)
    return {"schema_version": 2, "diagram_type": "workflow",
            "meta": {"title": str(spec.get("title") or "Diagram")[:80], "output": "diagram.html", "quality_profile": "standard"},
            "lanes": [{"id": lane_id[i], "label": f"Row {i + 1}"} for i in range(lane_count)],
            "nodes": out_nodes, "edges": out_edges}


def _reason(r) -> str:
    try:
        diags = json.loads(r.stdout).get("diagnostics") or []
        return "; ".join(f"{d.get('code')}: {d.get('message', '')[:160]}" for d in diags[:3]) or "no diagnostics"
    except ValueError:
        return (r.stderr or r.stdout or "no output")[-200:]


def draw(spec: dict) -> str:
    """Compile, validate and render a diagram; return its id. Raises ValueError with the reason on failure."""
    compiled = compile_spec(spec)
    if not ARCHIFY.is_file():
        raise ValueError(f"archify not found at {ARCHIFY}; set ARCHIFY_BIN")
    did = uuid.uuid4().hex[:12]
    folder = OUT_DIR / did  # archify locks per folder, so one folder per diagram lets draws run in parallel
    folder.mkdir(parents=True, exist_ok=True)
    src, out = folder / "spec.json", folder / "diagram.html"
    src.write_text(json.dumps(compiled), encoding="utf-8")
    try:
        r = subprocess.run(["node", str(ARCHIFY), "deliver", "workflow", str(src), str(out), "--quality", "standard", "--json"],
                           capture_output=True, text=True, timeout=60)
    except (OSError, subprocess.TimeoutExpired) as e:
        shutil.rmtree(folder, ignore_errors=True)
        raise ValueError(f"archify unavailable: {e}")
    if r.returncode != 0 or not out.exists():
        shutil.rmtree(folder, ignore_errors=True)
        raise ValueError(f"archify rejected the diagram: {_reason(r)}")
    return did


def path_for(did: str) -> Path:
    if not re.fullmatch(r"[0-9a-f]{12}", did):
        raise ValueError("bad diagram id")
    return OUT_DIR / did / "diagram.html"
