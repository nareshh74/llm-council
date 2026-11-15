"""Startup skills: injected as a system message on every answer-writing model call, so they apply to every turn."""

import os
import re
from pathlib import Path

SKILLS = Path(os.getenv("STARTUP_SKILLS_DIR", Path.home() / ".claude/skills"))
NAMES = [n.strip() for n in os.getenv(
    "STARTUP_SKILLS",
    "i-have-adhd,humanizer,andrej-karpathy-skill,autonomous-delivery,codeburn,repo-context,leanrea,trail,floorplan,worktrunk,archify",
).split(",") if n.strip()]
FULL_MAX = int(os.getenv("STARTUP_SKILLS_FULL_MAX", "4000"))


def _build() -> str:
    full, index = [], []
    for name in NAMES:
        f = SKILLS / name / "SKILL.md"
        if not f.is_file():
            continue
        text = f.read_text(encoding="utf-8", errors="replace").strip()
        body = re.sub(r"\A---\n.*?\n---\n", "", text, count=1, flags=re.S).strip()
        if len(body) <= FULL_MAX:
            full.append(f'<startup_skill name="{name}">\n{body}\n</startup_skill>')
        else:
            m = re.search(r"^description:\s*(.+)$", text, re.M)
            index.append(f"- {name}: {m.group(1).strip().strip(chr(39) + chr(34)) if m else ''}")
    if not full and not index:
        return ""
    head = ("These startup skills are active for every reply in this conversation, on every turn. "
            "Follow the style and behavior rules they define.")
    parts = [head] + full
    if index:
        parts.append("Also available, by description only:\n" + "\n".join(index))
    return "\n\n".join(parts)


try:
    PROMPT = _build()
except Exception:
    PROMPT = ""
