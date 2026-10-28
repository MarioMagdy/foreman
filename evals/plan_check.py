"""Score a foreman plan.yaml against the milestone / gate shape.

Usage:
  python evals/plan_check.py <plan.yaml>     # prints one line per check, exit 1 if any fail
  python evals/plan_check.py --selftest

Shape checked (see references/gates.md):
  milestones: id, title, adds, done_when (2-4 items), kind planned|explore (default planned); a milestone with a
              `status` (shipped history backfilled for the tracker) is skipped
  stages:     id, milestone, title, needs, kind build|spike|gate (default build)
  gate stages also carry gate: deterministic|ai|human and check; deterministic ones carry bar.
"""
import re
import sys

import yaml

GATE_TYPES = {"deterministic", "ai", "human"}


def ancestors(sid, by_id):
    seen, todo = set(), list(by_id[sid].get("needs") or [])
    while todo:
        n = todo.pop()
        if n in by_id and n not in seen:
            seen.add(n)
            todo.extend(by_id[n].get("needs") or [])
    return seen


def check(plan):
    """Return a list of (name, passed, detail)."""
    # A milestone with a `status` (merged history backfilled for the tracker) is not new work: skip it
    ms = [m for m in plan.get("milestones") or [] if not m.get("status")]
    st = plan.get("stages") or []
    by_id = {s["id"]: s for s in st}
    out = []

    def add(name, bad):
        out.append((name, not bad, "; ".join(bad) if bad else "ok"))

    add("milestone has adds", [m["id"] for m in ms if not str(m.get("adds") or "").strip()])
    add("milestone has 2-4 done_when", [m["id"] for m in ms
        if not isinstance(m.get("done_when"), list) or not 2 <= len(m["done_when"]) <= 4])
    add("title has no [gate]/layer prefix", [m["id"] for m in ms
        if re.match(r"\s*(\[|gate\b|layer\b|backend\b|frontend\b|service\b|engine\b|schema\b)", m.get("title", ""), re.I)])

    gates = [s for s in st if s.get("kind") == "gate"]
    add("gate has a known type and a check", [s["id"] for s in gates
        if s.get("gate") not in GATE_TYPES or not str(s.get("check") or "").strip()])
    add("deterministic gate has a bar", [s["id"] for s in gates
        if s.get("gate") == "deterministic" and not str(s.get("bar") or "").strip()])

    # Planned milestone ends: AI gate, then human gate that every other node of the milestone leads into.
    bad = []
    for m in ms:
        if m.get("kind", "planned") != "planned":
            continue
        mine = [s for s in st if s.get("milestone") == m["id"]]
        human = [s for s in mine if s.get("kind") == "gate" and s.get("gate") == "human"]
        if len(human) != 1:
            bad.append(f"{m['id']}: {len(human)} human gates")
            continue
        up = ancestors(human[0]["id"], by_id)
        if not any(by_id[a].get("gate") == "ai" and by_id[a].get("milestone") == m["id"] for a in up):
            bad.append(f"{m['id']}: no AI gate before the human gate")
        loose = [s["id"] for s in mine if s is not human[0] and s["id"] not in up]
        if loose:
            bad.append(f"{m['id']}: not behind the human gate: {','.join(loose)}")
    add("planned milestone ends AI gate -> human gate", bad)

    # Nothing outside an explore milestone may need a stage inside it.
    explore = {m["id"] for m in ms if m.get("kind") == "explore"}
    add("explore milestone stays off the stack", [f"{s['id']} needs {n}" for s in st
        if s.get("milestone") not in explore
        for n in (s.get("needs") or []) if by_id.get(n, {}).get("milestone") in explore])

    add("needs point at real stages", [f"{s['id']}->{n}" for s in st for n in (s.get("needs") or []) if n not in by_id])

    add("plan has milestones and stages", [k for k in ("milestones", "stages") if not plan.get(k)])
    new = {m["id"] for m in ms}
    ids = [x.get("id") for x in ms] + [s.get("id") for s in st if s.get("milestone") in new]
    add("ids are unique", sorted({str(i) for i in ids if ids.count(i) > 1}))
    add("new nodes have a title and a known kind",
        [m["id"] for m in ms if not str(m.get("title") or "").strip() or m.get("kind", "planned") not in ("planned", "explore")]
        + [s.get("id", "?") for s in st if s.get("milestone") in new
           and (not str(s.get("title") or "").strip() or s.get("kind", "build") not in ("build", "spike", "gate"))])

    state = {}  # 1 = on the current path, 2 = done

    def loops(sid):
        if state.get(sid):
            return state[sid] == 1
        state[sid] = 1
        hit = [n for n in by_id[sid].get("needs") or [] if n in by_id and loops(n)]
        state[sid] = 2
        return bool(hit)
    add("needs have no loop", [s["id"] for s in st if s["id"] not in state and loops(s["id"])])
    return out


def selftest():
    good = {
        "milestones": [
            {"id": "M1", "title": "Get a key only when I allow it", "adds": "x", "done_when": ["a", "b"]},
            {"id": "M2", "kind": "explore", "title": "Try vaults", "adds": "y", "done_when": ["a", "b"]},
        ],
        "stages": [
            {"id": "M1-S1", "milestone": "M1", "title": "b", "needs": []},
            {"id": "M1-G1", "milestone": "M1", "kind": "gate", "gate": "deterministic", "title": "t", "check": "c", "bar": "0 leaks", "needs": ["M1-S1"]},
            {"id": "M1-G2", "milestone": "M1", "kind": "gate", "gate": "ai", "title": "t", "check": "c", "needs": ["M1-G1"]},
            {"id": "M1-G3", "milestone": "M1", "kind": "gate", "gate": "human", "title": "t", "check": "c", "needs": ["M1-G2"]},
            {"id": "M2-S1", "milestone": "M2", "kind": "spike", "title": "s", "needs": []},
        ],
    }
    assert all(p for _, p, _ in check(good)), check(good)
    bad = yaml.safe_load(yaml.safe_dump(good))
    bad["milestones"][0]["done_when"] = ["only one"]
    bad["milestones"][0]["title"] = "[gate 1] Backend"
    bad["stages"][2]["gate"] = "human"          # two human gates, no AI gate
    bad["stages"][0]["needs"] = ["M2-S1"]       # stack depends on explore
    del bad["stages"][1]["bar"]
    failed = {n for n, p, _ in check(bad) if not p}
    assert failed == {"milestone has 2-4 done_when", "title has no [gate]/layer prefix",
                      "deterministic gate has a bar", "planned milestone ends AI gate -> human gate",
                      "explore milestone stays off the stack"}, failed
    loop = yaml.safe_load(yaml.safe_dump(good))
    loop["stages"][0]["needs"] = ["M1-G3"]       # S1 -> G3 -> G2 -> G1 -> S1
    loop["stages"][4]["kind"] = "task"
    loop["stages"].append(dict(loop["stages"][3]))
    failed = {n for n, p, _ in check(loop) if not p}
    assert {"needs have no loop", "new nodes have a title and a known kind", "ids are unique"} <= failed, failed
    assert {n for n, p, _ in check({}) if not p} == {"plan has milestones and stages"}, check({})
    print("selftest ok")


if __name__ == "__main__":
    if sys.argv[1:] == ["--selftest"]:
        selftest()
        sys.exit(0)
    with open(sys.argv[1], encoding="utf-8") as f:
        results = check(yaml.safe_load(f) or {})
    for name, passed, detail in results:
        print(f"{'PASS' if passed else 'FAIL'}  {name}: {detail}")
    print(f"{sum(p for _, p, _ in results)}/{len(results)} passed")
    sys.exit(0 if all(p for _, p, _ in results) else 1)
