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
assert r.returncode == 0 and "8/8 passed" in r.stdout, r.stdout
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
import yaml  # noqa: E402  the shipped templates stay valid YAML
for t in ("defaults.yaml", os.path.join("profiles", "default.yaml")):
    yaml.safe_load(open(os.path.join(here, "..", t), encoding="utf-8"))
print("test_live OK")
