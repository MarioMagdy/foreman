"""Self-check for launcher.py against a fake opencode (this same file). Run: python test_launcher.py

Covers: slot cap, critical-path-first queueing, answers -> reports, STATUS parsing, hang, quota (from the
server log, matched by session id), cancel, server death -> restart, password on every call, stop.
"""
import base64, json, os, random, shutil, subprocess, sys, tempfile, threading, time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
FAKE = os.environ.get("FAKE_DIR")


def put(sid, **kw):
    path = os.path.join(FAKE, sid + ".json")
    s = json.load(open(path)) if os.path.exists(path) else {"messages": []}
    s.update(kw, updated=int(time.time() * 1000))
    json.dump(s, open(path, "w"))


def fake_serve(port):
    want = "Basic " + base64.b64encode(f"opencode:{os.environ['OPENCODE_SERVER_PASSWORD']}".encode()).decode()

    class H(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def reply(self, obj, code=200):
            body = json.dumps(obj).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            if self.headers.get("Authorization") != want:
                return self.reply({"error": "auth"}, 401)
            parts = self.path.strip("/").split("/")
            if self.path == "/global/health":
                return self.reply({"healthy": True})
            s = json.load(open(os.path.join(FAKE, parts[1] + ".json")))
            if len(parts) == 2:
                return self.reply({"time": {"updated": s["updated"]}, "cost": 0, "tokens": {"total": 42}})
            return self.reply(s["messages"])

        def do_POST(self):
            if self.headers.get("Authorization") != want:
                return self.reply({"error": "auth"}, 401)
            open(os.path.join(FAKE, self.path.strip("/").split("/")[1] + ".aborted"), "w").close()
            self.reply(True)

    def quota_lines():  # what real opencode prints with --print-logs on a usage limit
        while True:
            for n in os.listdir(FAKE):
                if n.endswith(".quota") and not os.path.exists(os.path.join(FAKE, n + "_logged")):
                    sid = n[:-6]
                    print(f'timestamp=2026-10-11T10:00:00Z level=ERROR message="stream error" providerID=opencode-go '
                          f'session.id={sid} error.error="AI_APICallError: Weekly usage limit reached. Resets in 5hr. '
                          f'https://opencode.ai/workspace/wrk_SECRET"', flush=True)
                    open(os.path.join(FAKE, n + "_logged"), "w").close()
            time.sleep(0.3)

    threading.Thread(target=quota_lines, daemon=True).start()
    print(f"opencode server listening on http://127.0.0.1:{port}", flush=True)
    ThreadingHTTPServer(("127.0.0.1", port), H).serve_forever()


def fake_run(args):
    brief = open(args[args.index("-f") + 1]).read()
    sid = "ses_%08x" % random.getrandbits(32)
    put(sid)
    print(json.dumps({"type": "step_start", "sessionID": sid}), flush=True)
    user = {"info": {"role": "user"}, "parts": [{"type": "file"}, {"type": "text", "text": args[1]}]}
    if brief.startswith("HANG"):
        time.sleep(600)
    if brief.startswith("QUOTA"):
        open(os.path.join(FAKE, sid + ".quota"), "w").close()
        time.sleep(600)
    for _ in range(int(brief.split()[1])):  # "SLEEP n <status>": stay active n seconds
        time.sleep(1)
        put(sid)
    status = brief.split()[2]
    text = f"worked\nSTATUS: UNSURE  question: early\nmore work\nSTATUS: {status}      criteria: 1/1 self-checked"
    put(sid, messages=[user, {"info": {"role": "assistant", "tokens": {"total": 42}}, "parts": [{"type": "text", "text": text}]}])


# ------------------------------------------------------------------------------------------- the test
def L(coord, *args):
    r = subprocess.run([sys.executable, os.path.join(HERE, "launcher.py"), "--coord", coord] + list(args),
                       capture_output=True, text=True, timeout=200)
    assert r.returncode == 0 or args[0] == "health", (args, r.stdout, r.stderr)
    return r.stdout.strip()


def job(coord, jid):
    return json.load(open(os.path.join(coord, "launcher", "jobs", jid + ".json")))


def until(pred, secs=60):
    t = time.time()
    while time.time() - t < secs:
        v = pred()
        if v:
            return v
        time.sleep(0.25)
    raise AssertionError("timed out")


def main():
    root = tempfile.mkdtemp(prefix="launcher-test-")
    coord, work = os.path.join(root, "_coord"), os.path.join(root, "wt")
    os.makedirs(work)
    os.makedirs(os.path.join(root, "fake"))
    os.environ.update(FOREMAN_OPENCODE=os.path.abspath(__file__), FAKE_DIR=os.path.join(root, "fake"))
    briefs = {}
    for name, body in {"a": "SLEEP 4 DONE", "b": "SLEEP 4 DONE", "c": "SLEEP 2 DONE", "d": "SLEEP 1 TOO_HARD",
                       "hang": "HANG", "quota": "QUOTA", "long": "SLEEP 60 DONE"}.items():
        briefs[name] = os.path.join(root, f"{name}.md")
        open(briefs[name], "w").write(body)
    sub = lambda st, b, *x: L(coord, "submit", "--stage", st, "--role", "builder", "--model", "opencode/fake",
                              "--brief", briefs[b], "--workdir", work, "--actor", "A", "--expect", "0", *x)
    try:
        print(L(coord, "start", "--port", str(random.randint(43000, 43900)), "--slots", "2", "--hang-min", "0.05",
                "--tick", "0.5"))
        ids = [sub("M1", "a"), sub("M2", "b"), sub("M3", "c"), sub("M4", "d", "--critical")]
        assert ids[0] == "M1-builder-1" and sub("M1", "c") == "M1-builder-2"  # ids never collide
        peak = [0]

        def all_done():
            st = [job(coord, j)["status"] if os.path.exists(os.path.join(coord, "launcher", "jobs", j + ".json"))
                  else "queued" for j in ids + ["M1-builder-2"]]
            peak[0] = max(peak[0], st.count("running"))
            return all(s == "done" for s in st)
        until(all_done, 90)
        assert peak[0] == 2, f"slot cap: peak {peak[0]} running, want 2"
        assert job(coord, "M4-builder-1")["started"] <= job(coord, "M3-builder-1")["started"], "critical goes first"
        report = open(os.path.join(coord, job(coord, "M1-builder-1")["report"])).read()
        assert "STATUS: DONE" in report and "tokens 42" in report

        h, q, lg = sub("M5", "hang"), sub("M6", "quota", "--expect", "1"), sub("M7", "long", "--expect", "1")
        until(lambda: job(coord, h)["status"] == "hung")
        until(lambda: job(coord, q)["status"] == "quota")
        until(lambda: job(coord, lg)["status"] == "running")
        L(coord, "cancel", lg)
        until(lambda: job(coord, lg)["status"] == "cancelled")
        for sid in (job(coord, h)["session"], job(coord, q)["session"]):
            assert os.path.exists(os.path.join(root, "fake", sid + ".aborted")), "dead jobs are aborted on the server"
        assert L(coord, "status", q) == "quota" and L(coord, "wait", "M4-builder-1").startswith("done")

        d = json.load(open(os.path.join(coord, "launcher", "daemon.json")))  # kill the server: the pool restarts it
        subprocess.run(["taskkill", "/PID", str(d["server_pid"]), "/T", "/F"], capture_output=True)
        until(lambda: json.load(open(os.path.join(coord, "launcher", "daemon.json"))).get("server_pid") not in (None, d["server_pid"]), 30)
        until(lambda: L(coord, "health").startswith("ok"), 30)

        ev = [json.loads(x) for x in open(os.path.join(coord, "events", "launcher.jsonl"))]
        kinds = [e["kind"] for e in ev]
        assert kinds.count("brief") == 8 and kinds.count("handback") == 5, kinds
        assert kinds.count("hang") == 1 and kinds.count("quota") == 1, kinds
        hb = {e["job"]: e for e in ev if e["kind"] == "handback"}
        assert hb["M4-builder-1"]["worker_status"] == "TOO_HARD", "last STATUS block wins"
        assert hb["M4-builder-1"]["actor"] == "builder:opencode/fake" and hb["M4-builder-1"]["to"] == "manager:A"
        quota = next(e for e in ev if e["kind"] == "quota")
        assert "wrk_SECRET" not in quota["summary"] and "usage limit" in quota["summary"]
        assert all(e["ts"].endswith("Z") for e in ev)
        print(L(coord, "jobs"))
    except BaseException:
        print(L(coord, "jobs"))
        for f in ("server.log", "daemon.log"):
            p = os.path.join(coord, "launcher", f)
            print(f"--- {f}\n" + (open(p, errors="replace").read()[-1500:] if os.path.exists(p) else "(none)"))
        raise
    finally:
        print(L(coord, "stop"))
        time.sleep(1)
        shutil.rmtree(root, ignore_errors=True)
    print("launcher self-check: OK")


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "serve":
        fake_serve(int(sys.argv[sys.argv.index("--port") + 1]))
    elif len(sys.argv) > 1 and sys.argv[1] == "run":
        fake_run(sys.argv[1:])
    else:
        main()
