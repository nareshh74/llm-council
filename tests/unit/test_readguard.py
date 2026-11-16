"""The read tools may leave the conversation folder, but never reach secrets."""

import asyncio
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from backend.workspace import Workspace  # noqa: E402
from backend.readguard import denied  # noqa: E402


@pytest.fixture
def ws(tmp_path):
    (tmp_path / "proj").mkdir()
    (tmp_path / "proj" / "a.txt").write_text("inside")
    out = tmp_path / "outside"
    out.mkdir()
    (out / "notes.txt").write_text("codeword: WALRUS-42")
    (out / ".env").write_text("API_KEY=hunter2-should-never-leak")
    (out / ".env.example").write_text("API_KEY=changeme")
    (out / "server.pem").write_text("-----BEGIN PRIVATE KEY-----")
    (out / "prod_password.txt").write_text("hunter2-should-never-leak")
    ssh = out / ".ssh"
    ssh.mkdir()
    (ssh / "config").write_text("Host x")
    return Workspace(tmp_path / "proj"), tmp_path


def call(w, name, **args):
    return asyncio.run(w.call(name, args))


def test_reads_inside_relative_and_outside_absolute_and_dotdot(ws):
    w, base = ws
    assert call(w, "read_file", path="a.txt") == "inside"
    assert "WALRUS-42" in call(w, "read_file", path=str(base / "outside" / "notes.txt"))
    assert "WALRUS-42" in call(w, "read_file", path="../outside/notes.txt")
    assert "notes.txt" in call(w, "list_dir", path=str(base / "outside"))
    assert "WALRUS-42" in call(w, "search", pattern="WALRUS", path=str(base / "outside"))


def test_secrets_are_blocked_everywhere(ws):
    w, base = ws
    out = base / "outside"
    for name in (".env", "server.pem", "prod_password.txt", ".ssh/config"):
        for how in (str(out / name), "../outside/" + name):
            r = call(w, "read_file", path=how)
            assert r.startswith("error: access blocked"), (name, how, r)
            assert "hunter2" not in r
    assert call(w, "list_dir", path=str(out / ".ssh")).startswith("error: access blocked")


def test_search_never_returns_secret_lines(ws):
    w, base = ws
    r = call(w, "search", pattern="hunter2|BEGIN PRIVATE|Host x|API_KEY", path=str(base / "outside"))
    assert "hunter2" not in r and "BEGIN PRIVATE" not in r and "Host x" not in r
    assert "API_KEY=changeme" in r, "template env files stay readable"


def test_symlink_into_a_protected_folder_is_blocked(ws):
    w, base = ws
    link = base / "proj" / "innocent"
    try:
        link.symlink_to(base / "outside" / ".ssh", target_is_directory=True)
    except OSError:
        pytest.skip("symlinks need privileges on this machine")
    assert call(w, "read_file", path="innocent/config").startswith("error: access blocked")


def test_home_expansion_cannot_reach_ssh(ws):
    w, _ = ws
    assert call(w, "list_dir", path="~/.ssh").startswith("error: access blocked")
    assert call(w, "read_file", path="~/.aws/credentials").startswith("error: access blocked")


def test_denied_rules():
    for bad in ("/home/u/.ssh/id_rsa", "C:/Users/u/.aws/credentials", "/x/.env", "/x/.env.production", "/x/a.pfx",
                "C:/Users/u/AppData/Local/Google/Chrome/User Data/Default/Cookies", "/x/my_api_key.txt"):
        assert denied(Path(bad)), bad
    for ok in ("/x/readme.md", "/x/src/main.py", "/x/.env.example", "/x/environment.md", "/x/token_utils.py"):
        assert not denied(Path(ok)), ok
