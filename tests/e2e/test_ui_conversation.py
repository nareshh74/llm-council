"""E2E: drive the real UI in a browser against the real backend and real models.

Needs: Vite on :5173 (started here if absent), a model gateway (LLM_API/OPENROUTER_API_KEY),
Playwright and Edge or Chromium. Run: python -m pytest tests/e2e -s
"""

import os
import socket
import subprocess
import sys
import time
from pathlib import Path

import httpx
import pytest

sync_api = pytest.importorskip("playwright.sync_api")

ROOT = Path(__file__).resolve().parents[2]
API = "http://localhost:8001"
UI = "http://localhost:5173"


def _up(port):
    with socket.socket() as s:
        s.settimeout(0.5)
        return s.connect_ex(("127.0.0.1", port)) == 0


def _wait(url, secs=60):
    end = time.time() + secs
    while time.time() < end:
        try:
            httpx.get(url, timeout=2)
            return
        except Exception:
            time.sleep(0.5)
    raise RuntimeError(f"{url} did not come up")


@pytest.fixture(scope="module")
def stack(tmp_path_factory):
    if _up(8001):
        pytest.skip("port 8001 busy; stop the running backend first")
    base = tmp_path_factory.mktemp("e2e")
    folders = {}
    for name, code in (("alpha", "PELICAN-77"), ("beta", "WALRUS-42")):
        d = base / name
        d.mkdir()
        (d / "AGENTS.md").write_text(f"The codeword for this project is in secret.txt. Project name: {name}.")
        (d / "secret.txt").write_text(f"codeword: {code}")
        folders[name] = d
    env = {**os.environ, "COUNCIL_DATA_DIR": str(base / "data"), "COUNCIL_FOLDER_ROOTS": str(base),
           "WIKI_MEMORY": "0", "THINKING_SKILLS": "0"}
    env.pop("COUNCIL_FOLDER", None)
    procs = [subprocess.Popen([sys.executable, "-m", "backend.main"], cwd=ROOT, env=env,
                              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)]
    if not _up(5173):
        npx = "npx.cmd" if os.name == "nt" else "npx"
        procs.append(subprocess.Popen([npx, "vite", "--port", "5173", "--strictPort"], cwd=ROOT / "frontend",
                                      stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL))
    try:
        _wait(API + "/")
        _wait(UI)
        yield folders
    finally:
        for p in procs:
            p.terminate()


@pytest.fixture
def page(stack):
    with sync_api.sync_playwright() as pw:
        try:
            browser = pw.chromium.launch(channel="msedge")
        except Exception:
            browser = pw.chromium.launch()
        pg = browser.new_page()
        yield pg
        browser.close()


def _ask(page, folder, question):
    page.goto(UI)
    page.get_by_placeholder("Folder (optional)").fill(str(folder))
    page.get_by_role("button", name="+ New Conversation").click()
    page.locator(".folder-banner").wait_for()
    page.locator(".message-input").fill(question)
    page.get_by_role("button", name="Send").click()
    page.locator(".stage3 .final-text").wait_for(timeout=280_000)
    return page.locator(".stage3 .final-text").inner_text()


Q = "Use your tools to read secret.txt. What is the codeword? Answer with just the codeword."


def test_conversation_runs_in_its_own_folder(page, stack):
    answer = _ask(page, stack["alpha"], Q)
    assert "PELICAN-77" in answer
    assert "WALRUS-42" not in answer
    assert page.locator(".stage1 .tab").count() >= 2, "expected several council members in stage 1"
    assert page.locator(".stage2").count() == 1
    assert page.locator(".folder-banner").inner_text().endswith("alpha")

    # sidebar lists it with the folder name, and it survives a reload
    page.reload()
    page.locator(".conversation-item", has_text="alpha").first.click()
    page.locator(".stage3 .final-text").wait_for()
    assert "PELICAN-77" in page.locator(".stage3 .final-text").inner_text()


def test_second_conversation_uses_a_different_folder(page, stack):
    answer = _ask(page, stack["beta"], Q)
    assert "WALRUS-42" in answer
    assert "PELICAN-77" not in answer


def test_folder_outside_allowed_roots_is_rejected(page, stack):
    page.goto(UI)
    page.get_by_placeholder("Folder (optional)").fill(str(ROOT))
    page.get_by_role("button", name="+ New Conversation").click()
    page.locator(".folder-error").wait_for()
    assert "existing directory under" in page.locator(".folder-error").inner_text()
    assert page.locator(".folder-banner").count() == 0


def test_api_rejects_escape_attempt(stack):
    for bad in (stack["alpha"] / ".." / "..", ROOT, Path(ROOT.anchor), stack["alpha"] / "secret.txt", stack["alpha"] / "missing"):
        r = httpx.post(API + "/api/conversations", json={"folder": str(bad)})
        assert r.status_code == 400, bad
    r = httpx.post(API + "/api/conversations", json={"folder": str(stack["alpha"] / ".." / "beta")})
    assert r.status_code == 200 and r.json()["folder"].endswith("beta")
