"""Version studies: keep every run's files and numbers so foreman versions can be compared over time.

Usage:
  python evals/study.py save <run dir> <study>/runs/<case>/<arm>-<n>   # copy a run, redacting paths, emails, key names
  python evals/study.py measure <study>                               # fill runs[].measured in <study>/data.json
  python evals/study.py --selftest

<study>/data.json holds what a person or a tool result recorded (tokens, minutes, questions, criteria);
`measure` adds what can be computed from the saved files, so those numbers are never typed by hand.
"""
import json
import re
import shutil
import sys
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).parent))
from plan_check import check  # noqa: E402

REDACT = [
    (re.compile(r"[A-Za-z]:[\\/](?:[^\s`'\"<>|;,)]| (?=[^\s`'\"<>|;,)]*[\\/]))*"), "<local path>"),
    (re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+"), "<account email>"),
    (re.compile(r"\b[A-Z][A-Z0-9]*_[A-Z0-9_]*(?:KEY|TOKEN|SECRET|PASSWORD)[A-Z0-9_]*\b"), "<KEY_NAME>"),
]


def redact(text):
    for pat, sub in REDACT:
        text = pat.sub(sub, text)
    return text


def save(src, dst):
    src, dst = Path(src), Path(dst)
    for f in src.rglob("*"):
        if f.is_file():
            out = dst / f.relative_to(src)
            out.parent.mkdir(parents=True, exist_ok=True)
            try:
                out.write_text(redact(f.read_text(encoding="utf-8")), encoding="utf-8", newline="\n")
            except UnicodeDecodeError:
                shutil.copy2(f, out)


def measure_plan(plan):
    ms, st = plan.get("milestones") or [], plan.get("stages") or []
    gates = [s for s in st if s.get("kind") == "gate"]
    by_gate = {t: sum(1 for g in gates if g.get("gate") == t) for t in ("deterministic", "ai", "human")}
    n_explore = sum(1 for m in ms if m.get("kind") == "explore")
    # A check with nothing to look at passes without proving anything; mark it so the report can say so.
    subject = {"gate has a known type and a check": len(gates), "deterministic gate has a bar": by_gate["deterministic"],
               "explore milestone stays off the stack": n_explore}
    checks = [{"name": n, "passed": p, "vacuous": subject.get(n, len(ms)) == 0, "detail": d} for n, p, d in check(plan)]
    return {
        "milestones": len(ms), "explore_milestones": n_explore, "stages": len(st),
        "build": sum(1 for s in st if s.get("kind", "build") == "build"),
        "spike": sum(1 for s in st if s.get("kind") == "spike"),
        "gates": by_gate, "checks": checks,
        "passed": sum(c["passed"] for c in checks),
        "passed_with_evidence": sum(c["passed"] and not c["vacuous"] for c in checks),
        "of": len(checks),
    }


def measure(study):
    study = Path(study)
    data = json.loads((study / "data.json").read_text(encoding="utf-8"))
    for run in data["runs"]:
        d = study / run["dir"]
        plan = yaml.safe_load((d / "_coord" / "plan.yaml").read_text(encoding="utf-8")) or {}
        m = measure_plan(plan)
        sheet = d / "run-sheet.md"
        m["run_sheet_words"] = len(sheet.read_text(encoding="utf-8").split()) if sheet.exists() else None
        m["extra_plan_files"] = sorted(p.name for p in d.glob("*PLAN*.md"))
        run["measured"] = m
    (study / "data.json").write_text(json.dumps(data, indent=1, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")
    for r in data["runs"]:
        m = r["measured"]
        print(f"{r['dir']}: {m['passed']}/{m['of']} ({m['passed_with_evidence']} with evidence), gates {m['gates']}, "
              f"build {m['build']} spike {m['spike']}, explore {m['explore_milestones']}")


def selftest():
    s = redact(r"see C:\Users\someone\skills\ and D:\work dir\notes\a.md; mail a.b@example.com; `SOME_SERVICE_API_KEY`")
    assert s == "see <local path> and <local path>; mail <account email>; `<KEY_NAME>`", s
    m = measure_plan({"milestones": [{"id": "M1", "title": "t", "adds": "a", "done_when": ["x", "y"]}],
                      "stages": [{"id": "M1-S1", "milestone": "M1"}]})
    vac = {c["name"] for c in m["checks"] if c["vacuous"]}
    assert vac == {"gate has a known type and a check", "deterministic gate has a bar",
                   "explore milestone stays off the stack"}, vac
    assert m["passed_with_evidence"] == m["passed"] - 3, m
    print("selftest ok")


if __name__ == "__main__":
    a = sys.argv[1:]
    if a == ["--selftest"]:
        selftest()
    elif a[:1] == ["save"] and len(a) == 3:
        save(a[1], a[2])
    elif a[:1] == ["measure"] and len(a) == 2:
        measure(a[1])
    else:
        sys.exit(__doc__)
