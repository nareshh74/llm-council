"""E2E: drive the real UI in a browser against the real backend and real models.

Needs: Vite on :5173 (started here if absent), a model gateway (LLM_API/OPENROUTER_API_KEY),
Playwright and Edge or Chromium. Run: python -m pytest tests/e2e -s
"""

import os
import re
import socket
import subprocess
import sys
import time
from pathlib import Path

import httpx
import pytest

sync_api = pytest.importorskip("playwright.sync_api")
expect = sync_api.expect

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
    style = base / "startup_skills" / "e2e-style"
    style.mkdir(parents=True)
    (style / "SKILL.md").write_text(
        "---\nname: e2e-style\ndescription: test style\n---\n"
        "Always end every reply you write with the exact token ZEBRA-STYLE-OK on its own final line.\n")
    folders = {}
    for name, code in (("alpha", "PELICAN-77"), ("beta", "WALRUS-42")):
        d = base / name
        d.mkdir()
        (d / "AGENTS.md").write_text(f"The codeword for this project is in secret.txt. Project name: {name}.")
        (d / "secret.txt").write_text(f"codeword: {code}")
        folders[name] = d
    outside = base / "outside"
    outside.mkdir()
    (outside / "notes.txt").write_text("codeword: OSTRICH-91")
    (outside / ".env").write_text("TOKEN=hunter2-never-leak")
    folders["outside"] = outside
    archify = Path.home() / ".claude/skills/archify/bin/archify.mjs"
    env = {**os.environ, "COUNCIL_DATA_DIR": str(base / "data"), "HOME": str(base), "USERPROFILE": str(base),
           "WIKI_MEMORY": "0", "THINKING_SKILLS": "0", "ARCHIFY_BIN": str(archify),
           "STARTUP_SKILLS_DIR": str(base / "startup_skills"), "STARTUP_SKILLS": "e2e-style",
           "COUNCIL_DIAGRAM_DIR": str(base / "diagrams")}
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


def _pick(page, name):
    page.get_by_role("button", name="Choose folder").click()
    page.locator(".folder-item", has_text=re.compile(f"^{name}$")).click()
    page.get_by_role("button", name="Use this folder").click()
    page.locator(".folder-current", has_text=name).wait_for()


def _ask(page, name, question):
    page.goto(UI)
    page.get_by_role("button", name="+ New Conversation").click()
    _pick(page, name)
    page.locator(".message-input").fill(question)
    page.get_by_role("button", name="Send").click()
    page.locator(".stage3 .final-text").wait_for(timeout=280_000)
    return page.locator(".stage3 .final-text").inner_text()


Q = "Use your tools to read secret.txt. What is the codeword? Answer with just the codeword."


def test_conversation_runs_in_its_own_folder(page, stack):
    answer = _ask(page, "alpha", Q)
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
    answer = _ask(page, "beta", Q)
    assert "WALRUS-42" in answer
    assert "PELICAN-77" not in answer


def test_picker_navigates_down_and_up(page, stack):
    page.goto(UI)
    page.get_by_role("button", name="+ New Conversation").click()
    page.get_by_role("button", name="Choose folder").click()
    items = page.locator(".folder-item")
    alpha = items.filter(has_text=re.compile("^alpha$"))
    beta = items.filter(has_text=re.compile("^beta$"))
    expect(alpha).to_have_count(1)
    expect(beta).to_have_count(1)
    alpha.click()
    expect(beta).to_have_count(0)
    expect(page.locator(".folder-path")).to_contain_text("alpha")
    page.get_by_role("button", name="Up").click()
    expect(beta).to_have_count(1)
    page.get_by_role("button", name="Cancel").click()
    expect(page.locator(".folder-current", has_text="plain chat")).to_have_count(1)


def test_folder_field_is_gone_from_the_sidebar(page, stack):
    page.goto(UI)
    assert page.get_by_placeholder("Folder (optional)").count() == 0


def test_folder_api_accepts_directories_and_rejects_the_rest(stack):
    conv = httpx.post(API + "/api/conversations", json={}).json()
    url = f"{API}/api/conversations/{conv['id']}/folder"
    r = httpx.put(url, json={"folder": str(stack["alpha"])})
    assert r.status_code == 200 and r.json()["folder"].endswith("alpha")
    r = httpx.put(url, json={"folder": str(stack["alpha"] / ".." / "beta")})
    assert r.status_code == 200 and r.json()["folder"].endswith("beta")
    for bad in (stack["alpha"] / "secret.txt", stack["alpha"] / "missing"):
        assert httpx.put(url, json={"folder": str(bad)}).status_code == 400, bad
        assert httpx.post(API + "/api/conversations", json={"folder": str(bad)}).status_code == 400, bad
    assert httpx.put(url, json={"folder": None}).json()["folder"] is None


def test_follow_up_uses_the_earlier_turn(page, stack):
    _ask(page, "alpha", Q)
    page.locator(".message-input").fill("Without using tools, repeat the codeword from your previous answer in lower case.")
    page.get_by_role("button", name="Send").click()
    expect(page.locator(".stage3 .final-text")).to_have_count(2, timeout=280_000)
    assert "pelican-77" in page.locator(".stage3 .final-text").nth(1).inner_text().lower()
    assert page.locator(".user-message").count() == 2


def test_markdown_renders_in_the_ui(page, stack):
    page.goto(UI)
    page.get_by_role("button", name="+ New Conversation").click()
    page.locator(".message-input").fill(
        "Reply with exactly this markdown and nothing else:\n\n"
        "| Name | Role |\n|---|---|\n| Ada | Engineer |\n\n"
        "- **bold item**\n- second item\n\n```python\nprint('hi')\n```"
    )
    page.get_by_role("button", name="Send").click()
    final = page.locator(".stage3 .final-text")
    expect(final).to_have_count(1, timeout=280_000)
    expect(final.locator("table")).to_have_count(1)
    expect(final.locator("th")).to_have_text(["Name", "Role"])
    expect(final.locator("li strong")).to_have_count(1)
    expect(final.locator("pre code")).to_have_count(1)


def test_chairman_draws_a_diagram_that_renders(page, stack):
    page.goto(UI)
    page.get_by_role("button", name="+ New Conversation").click()
    page.locator(".message-input").fill(
        "Explain visually how a web request flows from a browser through a CDN and a load balancer "
        "to an API server and a database. You must call draw_diagram and show the diagram."
    )
    page.get_by_role("button", name="Send").click()
    frame = page.locator(".stage3 .diagram-frame")
    expect(frame).to_have_count(1, timeout=280_000)
    src = frame.get_attribute("src")
    assert "/api/diagrams/" in src
    body = httpx.get(src)
    assert body.status_code == 200 and "<svg" in body.text
    inner = page.frame_locator(".stage3 .diagram-frame")
    expect(inner.locator("svg").first).to_be_visible()


def test_diagram_route_rejects_bad_ids(stack):
    assert httpx.get(API + "/api/diagrams/..%2f..%2fsecret").status_code == 404
    assert httpx.get(API + "/api/diagrams/000000000000").status_code == 404


def _send(page, text, nth):
    page.locator(".message-input").fill(text)
    page.get_by_role("button", name="Send").click()
    expect(page.locator(".stage3 .final-text")).to_have_count(nth, timeout=280_000)


def test_time_title_and_search(page, stack):
    page.goto(UI)
    page.get_by_role("button", name="+ New Conversation").click()
    _send(page, "Explain how a zebra crossing keeps pedestrians safe. One short paragraph.", 1)
    _send(page, "Now explain the same for a pelican crossing. One short paragraph.", 2)

    times = page.locator(".message-time")
    expect(times).to_have_count(4)
    for t in times.all_inner_texts():
        assert re.search(r"\d{1,2}:\d{2}", t), t

    page.reload()
    item = page.locator(".conversation-item", has_text=re.compile("crossing", re.I)).first
    expect(item).to_be_visible(timeout=60_000)
    title = item.locator(".conversation-title").inner_text()
    assert title and title != "New Conversation" and len(title) <= 50

    other = page.get_by_role("button", name="+ New Conversation")
    other.click()
    _send(page, "Reply with the single word banana.", 1)
    page.reload()

    box = page.get_by_placeholder("Search conversations")
    box.fill("crossing")
    expect(page.locator(".conversation-item")).to_have_count(1)
    box.fill("no-such-title-xyz")
    expect(page.locator(".conversation-item")).to_have_count(0)
    expect(page.locator(".no-conversations")).to_contain_text("No matching")
    box.fill("")
    assert page.locator(".conversation-item").count() >= 2

    page.locator(".conversation-item", has_text=re.compile("crossing", re.I)).first.click()
    expect(page.locator(".message-group")).to_have_count(4)
    inbox = page.get_by_placeholder("Search in this conversation")
    inbox.fill("pelican")
    expect(page.locator(".message-group.search-hit").first).to_be_visible()
    assert page.locator(".message-search-count").inner_text().endswith("of " + str(page.locator(".message-group.search-hit").count()))
    inbox.fill("zzz-not-here")
    expect(page.locator(".message-search-count")).to_have_text("No matches")
    expect(page.locator(".message-group.search-hit")).to_have_count(0)
    inbox.fill("")
    expect(page.locator(".message-search-count")).to_have_count(0)


def test_startup_skills_apply_on_every_turn(page, stack):
    page.goto(UI)
    page.get_by_role("button", name="+ New Conversation").click()
    _send(page, "What is 2+2? Answer in one short sentence.", 1)
    _send(page, "What is 3+3? Answer in one short sentence.", 2)
    finals = page.locator(".stage3 .final-text")
    for i in range(2):
        assert "ZEBRA-STYLE-OK" in finals.nth(i).inner_text(), f"turn {i + 1} missed the startup skill"


def test_activity_streams_live_into_the_conversation(page, stack):
    page.goto(UI)
    page.get_by_role("button", name="+ New Conversation").click()
    _pick(page, "alpha")
    page.locator(".message-input").fill(Q)
    page.get_by_role("button", name="Send").click()

    activity = page.locator(".activity")
    expect(activity).to_have_count(1, timeout=60_000)
    expect(activity.locator(".activity-row.llm").first).to_be_visible(timeout=60_000)
    expect(page.locator(".stage3 .final-text")).to_have_count(0)
    assert page.locator(".loading-indicator").count() == 1, "the run should still be in progress"

    expect(activity.locator(".activity-row.tool").first).to_be_visible(timeout=120_000)
    expect(activity.locator(".activity-row.tool").filter(has_text="read_file").first).to_be_visible()

    expect(page.locator(".stage3 .final-text")).to_have_count(1, timeout=280_000)
    assert "PELICAN-77" in page.locator(".stage3 .final-text").inner_text()
    expect(activity.locator(".activity-row.running")).to_have_count(0, timeout=30_000)
    expect(activity).not_to_have_attribute("open", "")
    activity.locator("summary").first.click()
    expect(activity).to_have_attribute("open", "")
    for stage in ("Stage 1", "Stage 2", "Stage 3"):
        expect(activity.get_by_text(stage, exact=False).first).to_be_visible()

    page.reload()
    page.locator(".conversation-item", has_text="alpha").first.click()
    expect(page.locator(".activity")).to_have_count(1)
    expect(page.locator(".activity .activity-row.llm").first).to_be_attached()


def test_council_reads_outside_the_folder_but_not_secrets(page, stack):
    outside = stack["outside"]
    page.goto(UI)
    page.get_by_role("button", name="+ New Conversation").click()
    _pick(page, "alpha")
    page.locator(".message-input").fill(
        f"Use your tools. Read the file {outside / 'notes.txt'} and tell me its codeword. "
        f"Then try to read {outside / '.env'} and tell me what happened to that second read, without repeating any secret."
    )
    page.get_by_role("button", name="Send").click()
    final = page.locator(".stage3 .final-text")
    expect(final).to_have_count(1, timeout=280_000)
    text = final.inner_text()
    assert "OSTRICH-91" in text
    assert "hunter2-never-leak" not in text
    page.locator(".activity summary").first.click()
    tools = page.locator(".activity .activity-row.tool")
    expect(tools.filter(has_text="notes.txt").first).to_be_visible()
    blocked = tools.filter(has_text=".env")
    assert blocked.count() >= 1
    assert "hunter2-never-leak" not in page.locator(".activity").inner_text()
