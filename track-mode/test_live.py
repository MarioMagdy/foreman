"""python track-mode/test_live.py — checks for live.py's stage filing and merge inference."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import live  # noqa: E402

MS = [{"id": i} for i in ("M1", "M5", "M5.8", "M10")]
for ref, want in [("M10-investigate", "M10"), ("M1-S3", "M1"), ("M5.8-F1", "M5.8"), ("M5-P7", "M5"),
                  ("M7-S0", "M7"), ("M7", "M7"), ("M12-RV-B", "M12"), ("M5.10-E3", "M5.10"), ("P1", "M10")]:
    got = live.ms_of_ref(ref, MS)
    assert got == want, (ref, got, want)

st = {"a": {"sid": "a", "status": "ready", "depends": []},
      "b": {"sid": "b", "status": "ready", "depends": ["a"]},
      "c": {"sid": "c", "status": "merged", "depends": ["b"]},
      "x": {"sid": "x", "status": "ready", "depends": []}}
live.infer_merged(st)
assert st["a"]["status"] == st["b"]["status"] == "merged" and st["a"]["mergedVia"] == "c", st
assert st["x"]["status"] == "ready" and "mergedVia" not in st["c"], st
ms = [{"id": "M1", "needs": None}]
live.add_ms(ms, {"id": "M1", "title": "restated", "needs": ["M0"]})
live.add_ms(ms, {"id": "M2", "needs": None})
assert ms == [{"id": "M1", "needs": ["M0"]}, {"id": "M2", "needs": None}], ms

# every node but the human gate done -> the milestone is in the owner's review, not running
g = lambda m, sid, st, kind="build", gate=None: {"sid": sid, "milestone": m, "status": st, "kind": kind, "gate": gate}
stg = [g("A", "A-S1", "merged"), g("A", "A-G2", "merged", "gate", "ai"), g("A", "A-G3", "planned", "gate", "human"),
       g("B", "B-S1", "running"), g("B", "B-G3", "planned", "gate", "human"),
       g("C", "C-S1", "merged"), g("C", "C-G3", "planned", "gate", "human"),
       g("D", "D-S1", "ready")]
mss = [{"id": "A"}, {"id": "B"}, {"id": "C", "gate": "accepted"}, {"id": "D"}, {"id": "E", "gate": "owner_review"}]
got = live.awaiting_owner(mss, stg)
assert got == {"A", "E"}, got   # B still running; C accepted; D has no human gate (just ready); E logged milestone_ready
# a milestone a merged one is built on is carried as merged, never "in review" (old shipped milestones)
old = [g("O", "O-S1", "merged"), g("O", "O-G3", "planned", "gate", "human")]
assert live.awaiting_owner([{"id": "O"}, {"id": "N", "needs": ["O"], "status": "merged"}], old) == set()
assert live.merged_milestones([{"id": "O"}, {"id": "N", "needs": ["O"], "status": "merged"}], old) == {"O", "N"}

# the shipped sample run passes plan_check, and serve hands out review packets but nothing outside packets/
import shutil, socket, subprocess, tempfile, time, urllib.error, urllib.request  # noqa: E402
here = os.path.dirname(os.path.abspath(__file__))
sample = os.path.join(here, "sample-run", "_coord")
r = subprocess.run([sys.executable, os.path.join(here, "..", "evals", "plan_check.py"), os.path.join(sample, "plan.yaml")],
                   capture_output=True, text=True)
assert r.returncode == 0 and "12/12 passed" in r.stdout, r.stdout
coord = os.path.join(tempfile.mkdtemp(), "_coord")
shutil.copytree(sample, coord)
os.makedirs(os.path.join(coord, "packets"))
with open(os.path.join(coord, "packets", "M1-G2.json"), "w") as f:
    f.write('{"gate": "M1-G2"}')
with socket.socket() as so:
    so.bind(("127.0.0.1", 0))
    port = so.getsockname()[1]
srv = subprocess.Popen([sys.executable, os.path.join(here, "live.py"), "serve", "--coord", coord, "--port", str(port)])
try:
    get = lambda path: urllib.request.urlopen(f"http://127.0.0.1:{port}{path}", timeout=5).read().decode()
    for _ in range(50):
        try:
            get("/run.json")
            break
        except OSError:
            time.sleep(0.2)
    assert '"gate": "M1-G2"' in get("/packets/M1-G2.json")
    assert "packets/" in get("/packet.html")
    for bad in ("/packets/missing.json", "/packets/..%2fplan.yaml", "/packets/../plan.yaml", "/packets/..%5cplan.yaml"):
        try:
            assert "Written by the orchestrator" not in get(bad), bad  # plan.yaml's first line
        except urllib.error.HTTPError as e:
            assert e.code == 404, (bad, e.code)
finally:
    srv.kill()
out = tempfile.mkdtemp()
subprocess.run([sys.executable, os.path.join(here, "live.py"), "build", "--coord", coord, "--out", out], check=True,
               capture_output=True)
assert os.path.isfile(os.path.join(out, "packet.html")) and os.path.isfile(os.path.join(out, "packets", "M1-G2.json"))
# `log` writes one event stamped with the real time, refreshes live/run.json, and rejects unknown kinds
import datetime, json  # noqa: E402
lc = os.path.join(tempfile.mkdtemp(), "_coord")
shutil.copytree(sample, lc)
live_py = os.path.join(here, "live.py")
logcmd = lambda *extra: subprocess.run([sys.executable, live_py, "log", "--coord", lc, "--actor", "foreman",
                                        "--ref", "M1-S1", "--summary", "test", *extra], capture_output=True, text=True)
shutil.rmtree(os.path.join(lc, "live"), ignore_errors=True)
r = logcmd("--kind", "brief", "--to", "builder:x", "--artifact", "briefs/nope.md")
assert r.returncode == 0, r.stderr
assert "artifact not found" in r.stderr, r.stderr  # a missing artifact only warns
ef = os.path.join(lc, "events", "foreman.jsonl")
last = json.loads(open(ef, encoding="utf-8").read().splitlines()[-1])
assert json.loads(r.stdout) == last and last["kind"] == "brief" and last["ref"] == "M1-S1" and last["to"] == "builder:x", (r.stdout, last)
age = datetime.datetime.now(datetime.timezone.utc) - datetime.datetime.strptime(last["ts"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=datetime.timezone.utc)
assert abs(age.total_seconds()) < 5, last["ts"]
rj = os.path.join(lc, "live", "run.json")
assert os.path.getmtime(rj) >= os.path.getmtime(ef) and json.load(open(rj, encoding="utf-8"))["meta"]["updated"] == last["ts"]
n = len(open(ef, encoding="utf-8").read().splitlines())
r = logcmd("--kind", "nonsense")
assert r.returncode == 2 and "handback" in r.stderr, (r.returncode, r.stderr)
assert len(open(ef, encoding="utf-8").read().splitlines()) == n  # nothing written for a bad kind
# an owner question carries its answer buttons and the recommended one
r = logcmd("--kind", "question", "--to", "owner", "--qid", "Q9", "--options", '["Keep it", "Drop it"]', "--recommended", "Keep it")
assert r.returncode == 0, r.stderr
q = json.loads(r.stdout)
assert q["options"] == ["Keep it", "Drop it"] and q["recommended"] == "Keep it", q
assert any(a.get("qid") == "Q9" and a.get("options") == ["Keep it", "Drop it"]
           for a in json.load(open(rj, encoding="utf-8"))["run"]["attention"]), "options reach the tracker"
assert logcmd("--kind", "question", "--qid", "Q8", "--options", "yes,no").returncode == 2
# a provisional start is recorded, and two events logged back to back never share a second (readers order by ts)
r1 = logcmd("--kind", "brief", "--provisional-on", "M1-S0")
r2 = logcmd("--kind", "status")
t1, t2 = json.loads(r1.stdout), json.loads(r2.stdout)
assert t1["provisional_on"] == "M1-S0" and t2["ts"] > t1["ts"], (t1, t2)
# loggers started at the same moment take turns: every event gets its own second, and no lock file is left
procs = [subprocess.Popen([sys.executable, live_py, "log", "--coord", lc, "--actor", f"mgr{i}", "--ref", "M1-S1",
                           "--kind", "status", "--summary", "same moment"], stdout=subprocess.PIPE, text=True)
         for i in range(3)]
same = [json.loads(p.communicate()[0])["ts"] for p in procs]
assert len(set(same)) == 3 and not os.path.exists(os.path.join(lc, "events", ".log.lock")), same
assert logcmd("--kind", "question", "--qid", "Q8", "--options", '["a"]', "--recommended", "b").returncode == 2
import yaml  # noqa: E402  the shipped templates stay valid YAML
for t in ("defaults.yaml", os.path.join("profiles", "default.yaml")):
    yaml.safe_load(open(os.path.join(here, "..", t), encoding="utf-8"))
print("test_live OK")
