"""Browser check that the tracker keeps the owner's answers: a note survives picking an option, picks and notes
survive a reload, and the 10 s refresh does not steal focus from a box being typed in.

    python track-mode/test_tracker_drafts.py        # needs playwright (pip install playwright; a Chrome install)

Uses a temporary copy of the bundled sample run with one extra owner question (Q3); the repo's sample is not changed.
"""
import json, os, re, shutil, subprocess, sys, tempfile, time

HERE = os.path.dirname(os.path.abspath(__file__))
PORT = "8799"


def main():
    from playwright.sync_api import sync_playwright
    tmp = tempfile.mkdtemp(prefix="foreman-drafts-")
    try:
        run = os.path.join(tmp, "run")
        shutil.copytree(os.path.join(HERE, "sample-run"), run)
        extra = {"ts": "2026-10-14T11:35:00Z", "actor": "orchestrator", "to": "owner", "kind": "question", "ref": "M1-S4",
                 "qid": "Q3", "summary": "Q3 needs you: keep the log window at 10 minutes or widen it?",
                 "options": ["Keep 10 minutes", "Widen it"], "recommended": "Keep 10 minutes"}
        site = os.path.join(tmp, "site")

        def build(folder):
            subprocess.run([sys.executable, os.path.join(HERE, "live.py"), "build", "--coord",
                            os.path.join(folder, "_coord"), "--out", site], check=True, stdout=subprocess.DEVNULL)

        def event(e):
            with open(os.path.join(run, "_coord", "events", "orchestrator.jsonl"), "a", encoding="utf-8") as f:
                f.write(json.dumps(e) + "\n")
            build(run)

        event(extra)
        srv = subprocess.Popen([sys.executable, "-m", "http.server", PORT, "-d", site],
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        time.sleep(1.5)
        ok = True

        def check(name, cond):
            nonlocal ok
            print(("ok   " if cond else "FAIL ") + name)
            ok = ok and bool(cond)

        try:
            with sync_playwright() as p:
                try:
                    b = p.chromium.launch(channel="chrome")
                except Exception:
                    b = p.chromium.launch()
                pg = b.new_page()
                pg.goto(f"http://127.0.0.1:{PORT}/tracker.html")
                pg.wait_for_selector('.other[data-q="Q2"]', timeout=15000)
                note = "Only for C1, nothing else"
                box = pg.locator('.other[data-q="Q2"]')
                box.fill(note)
                pg.locator('.opt[data-q="Q2"][data-v="Skip C1 in report v1"]').click()
                check("note kept after picking an option", box.input_value() == note)
                pg.reload()
                pg.wait_for_selector('.other[data-q="Q2"]', timeout=15000)
                check("note kept after reload", pg.locator('.other[data-q="Q2"]').input_value() == note)
                check("pick kept after reload", pg.locator('.opt[data-q="Q2"][data-v="Skip C1 in report v1"]')
                      .get_attribute("aria-pressed") == "true")
                b3 = pg.locator('.other[data-q="Q3"]')
                b3.click()
                pg.keyboard.type("typing during refresh")
                pg.evaluate("document.activeElement.setSelectionRange(6, 6)")   # caret mid-text, not at the end
                # change the run while typing, so the refresh really redraws the question list (a new Q4 appears)
                event({"ts": "2026-10-14T11:36:00Z", "actor": "orchestrator", "to": "owner", "kind": "question",
                       "ref": "M1-S4", "qid": "Q4", "summary": "Q4 needs you: name the export file?"})
                pg.wait_for_selector('.other[data-q="Q4"]', timeout=15000)
                check("focus stays in the box through a redraw",
                      pg.evaluate("document.activeElement && document.activeElement.dataset.q") == "Q3")
                check("caret stays where it was", pg.evaluate(
                    "[document.activeElement.selectionStart, document.activeElement.selectionEnd]") == [6, 6])
                pg.keyboard.press("End")
                pg.keyboard.type(" ...still here")
                check("text survives the redraw",
                      pg.locator('.other[data-q="Q3"]').input_value() == "typing during refresh ...still here")
                # an answered question's draft is dropped from storage
                event({"ts": "2026-10-14T11:37:00Z", "actor": "orchestrator", "kind": "answer", "ref": "M1-S4",
                       "qid": "Q3", "summary": "Owner: keep 10 minutes"})
                pg.wait_for_selector('.other[data-q="Q3"]', state="detached", timeout=15000)
                stored = pg.evaluate("Object.keys(localStorage).filter(k => k.startsWith('foreman-drafts'))"
                                     ".map(k => localStorage.getItem(k)).join('')")
                check("answered question's draft is dropped", "typing during refresh" not in stored and note in stored)
                # renaming the run keeps its drafts (they follow the run folder, not the title)
                plan = os.path.join(run, "_coord", "plan.yaml")
                text = open(plan, encoding="utf-8").read()
                assert re.search(r"(?m)^title:", text), "sample plan has a title line"
                open(plan, "w", encoding="utf-8").write(re.sub(r"(?m)^title:.*$", 'title: "Renamed: same run"', text, 1))
                build(run)
                pg.reload()
                pg.wait_for_selector('.other[data-q="Q2"]', timeout=15000)
                check("drafts survive renaming the run", pg.locator('.other[data-q="Q2"]').input_value() == note)
                # another run with the same folder name, served on the same port, does not inherit this run's Q2 draft
                other = os.path.join(tmp, "elsewhere", "run")
                shutil.copytree(run, other)
                build(other)
                pg.reload()
                pg.wait_for_selector('.other[data-q="Q2"]', timeout=15000)
                check("another run starts with no drafts",
                      pg.locator('.other[data-q="Q2"]').input_value() == ""
                      and pg.locator('.opt[data-q="Q2"][data-v="Skip C1 in report v1"]').get_attribute("aria-pressed") != "true")
                # unreadable storage does not break the page
                pg.evaluate("Object.keys(localStorage).forEach(k => localStorage.setItem(k, '{\"Q2\": {\"other\": 42}}'))")
                pg.reload()
                pg.wait_for_selector('.other[data-q="Q2"]', timeout=15000)
                check("bad stored drafts are ignored", pg.locator('.other[data-q="Q2"]').input_value() == "")
                b.close()
        finally:
            srv.terminate()
        print("test_tracker_drafts OK" if ok else "test_tracker_drafts FAILED")
        return 0 if ok else 1
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
