"""cc-thinking-skills: compact index injected as a system message on every model call."""

import os
import re
from pathlib import Path

SKILLS = Path(os.getenv("THINKING_SKILLS_DIR", Path.home() / "AppData/Local/hermes/skills"))
ENABLED = os.getenv("THINKING_SKILLS", "1") != "0"


def _build() -> str:
    lines = []
    for f in sorted(SKILLS.glob("thinking-*/SKILL.md")):
        m = re.search(r"^description:\s*(.+)$", f.read_text(encoding="utf-8"), re.M)
        if m:
            lines.append(f"- {f.parent.name[9:]}: {m.group(1).strip()}")
    if not lines:
        return ""
    return ("You have these structured thinking skills. Silently pick the one or two that fit the "
            "question and apply them in your reasoning; do not list them.\n" + "\n".join(lines))


try:
    PROMPT = _build() if ENABLED else ""
except Exception:
    PROMPT = ""
