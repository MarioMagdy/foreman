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

# owner 2026-10-27: every node but the human gate done -> the milestone is in the owner's review, not running
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
print("test_live OK")
