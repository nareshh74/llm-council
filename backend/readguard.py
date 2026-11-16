"""Read-anywhere guard: the council may read any path, except places that usually hold secrets."""

import fnmatch
import os
from pathlib import Path

DENY_DIRS = {".ssh", ".aws", ".azure", ".gnupg", ".kube", ".docker", ".gcloud", ".config/gcloud", ".config/gh",
             ".npm", ".password-store", ".terraform.d"}
DENY_PATH_PARTS = ("appdata/local/google/chrome/user data", "appdata/local/microsoft/edge/user data",
                   "appdata/roaming/mozilla/firefox", "appdata/roaming/microsoft/credentials",
                   "appdata/roaming/microsoft/protect", "appdata/local/microsoft/credentials",
                   ".claude/.credentials", ".claude/projects", ".copilot/config")
DENY_NAMES = (".env", ".env.*", "*.pem", "*.key", "*.pfx", "*.p12", "*.kdbx", "id_rsa*", "id_ed25519*", "id_ecdsa*",
              "*.ppk", "credentials", "credentials.json", "secrets.json", "secrets.yaml", "secrets.yml", ".netrc", ".npmrc",
              ".pypirc", "auth.json", "token", "tokens.json", "*.secret", "*.secrets", "*apikey*", "*api_key*",
              "*api-key*", "*password*", "*passwd*", "known_hosts", "cookies", "cookies.sqlite", "login data",
              "web data", "local state", "*.tfstate", "terraform.tfvars")
ALLOW_NAMES = (".env.example", ".env.sample", ".env.template")


def denied(path: Path) -> str:
    """Return why a fully resolved path is off limits, or an empty string when it may be read."""
    posix = path.as_posix().lower()
    name = path.name.lower()
    if name in ALLOW_NAMES:
        return ""
    parts = [p.lower() for p in path.parts]
    for d in DENY_DIRS:
        if "/" in d:
            if f"/{d}/" in f"{posix}/":
                return f"inside a protected folder ({d})"
        elif d in parts:
            return f"inside a protected folder ({d})"
    for frag in DENY_PATH_PARTS:
        if frag in posix:
            return "inside a protected application folder"
    for pat in DENY_NAMES:
        if fnmatch.fnmatch(name, pat):
            return f"file name looks like a secret ({pat})"
    return ""


def resolve(root: Path, p: str) -> Path:
    """Resolve a model-supplied path: relative paths start at root, absolute paths and .. may leave it.
    Raises ValueError when the real path (after symlinks) is protected."""
    full = Path(os.path.expanduser(p or "."))
    full = (full if full.is_absolute() else root / full).resolve()
    why = denied(full)
    if why:
        raise ValueError(f"access blocked: {why}")
    return full
