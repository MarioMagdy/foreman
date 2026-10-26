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
print("test_live OK")
