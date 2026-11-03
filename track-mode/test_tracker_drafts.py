"""Browser check that the tracker keeps the owner's answers: a note survives picking an option, picks and notes
survive a reload, and the 10 s refresh does not steal focus from a box being typed in.

    python track-mode/test_tracker_drafts.py        # needs playwright (pip install playwright; a Chrome install)

Uses a temporary copy of the bundled sample run with one extra owner question (Q3); the repo's sample is not changed.
"""
import json, os, shutil, subprocess, sys, tempfile, time

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
        with open(os.path.join(run, "_coord", "events", "orchestrator.jsonl"), "a", encoding="utf-8") as f:
            f.write(json.dumps(extra) + "\n")
        site = os.path.join(tmp, "site")
        subprocess.run([sys.executable, os.path.join(HERE, "live.py"), "build", "--coord", os.path.join(run, "_coord"),
                        "--out", site], check=True, stdout=subprocess.DEVNULL)
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
                b3.type("typing during refresh")
                pg.wait_for_timeout(11500)
                b3.type(" ...still here")
                check("focus and text survive the 10 s refresh",
                      pg.locator('.other[data-q="Q3"]').input_value() == "typing during refresh ...still here")
                b.close()
        finally:
            srv.terminate()
        print("test_tracker_drafts OK" if ok else "test_tracker_drafts FAILED")
        return 0 if ok else 1
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
