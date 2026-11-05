#!/usr/bin/env python3
"""Build scores/models.yaml (JSON-compatible YAML) from a run log CSV.

    build_scores.py <runs.csv> [more.csv ...] [--out scores/models.yaml]
    build_scores.py selftest

Only the columns in COLUMNS are read; every other column is ignored and never
reaches the output. Score = mean of the filled 0-5 dimensions x 2 (one row),
cell = mean of row scores, one decimal, only cells with n >= MIN_RUNS.
Several CSVs are merged. A CSV may say `job` instead of `role` and `month` (YYYY-MM)
instead of `date` (the community share format).
"""
import csv
import json
import re
import statistics
import sys
import tempfile
from datetime import date
from pathlib import Path

# Column names in the run log. Adjust here if the real header differs slightly.
COL_MODEL, COL_ROLE, COL_DATE = "model", "role", "date"
DIMS = ["rule_following_0to5", "task_understanding_0to5", "unknowns_recovery_0to5",
        "output_quality_0to5", "honesty_0to5", "autonomy_0to5", "verification_rigor_0to5"]
COLUMNS = [COL_MODEL, COL_ROLE, COL_DATE] + DIMS
COL_JOB, COL_MONTH = "job", "month"          # accepted in place of role / date

MIN_RUNS = 5
JOBS = ["build", "fix", "review", "plan", "investigate"]
ROLE_TO_JOB = {
    "builder": "build", "build": "build",
    "fixer": "fix", "fix": "fix",
    "reviewer": "review", "review": "review", "judge": "review", "judge-r1": "review", "judge-r2": "review",
    "milestone-reviewer": "review", "verifier": "review", "research": "investigate",
    "plan": "plan", "planner": "plan",
    "investigator": "investigate", "researcher": "investigate",
    "investigate": "investigate",
}
BARE_FAMILIES = ("sonnet", "opus", "haiku", "fable")
# Families we recognise; a model outside these is kept as written (lowercased)
# but reported as unaliased so a human can decide.
KNOWN_PREFIXES = ("claude-", "gpt-", "gemini-")
# Open-model families run through opencode and similar; kept as written, not reported.
OPEN_FAMILIES = ("glm-", "kimi-", "deepseek-", "qwen", "minimax-", "mimo-")
DROP = {"", "unknown"}


def alias(raw):
    """Return (normalised name, was_unaliased); name "" means drop the row."""
    name = (raw or "").strip().lower().replace(" ", "-").replace("_", "-")
    if name in DROP or "unverified" in name:
        return "", False
    for p in ("anthropic/", "openai/", "codex-"):
        if name.startswith(p):
            name = name[len(p):]
    name = re.sub(r"-(low|medium|high|xhigh)$", "", name)   # reasoning effort is a setting, not a model
    if name in BARE_FAMILIES:
        return "", True                        # no version: nobody can tell which model it was; drop and flag
    if name.startswith(BARE_FAMILIES):         # sonnet-5.5 -> claude-sonnet-5-5
        name = "claude-" + name
    if name.startswith("claude-"):
        name = re.sub(r"(?<=\d)\.(?=\d)", "-", name)   # 5.5 -> 5-5
        return name, False
    return name, not name.startswith(KNOWN_PREFIXES + OPEN_FAMILIES)


def _num(v):
    try:
        x = float(str(v).strip())
    except (TypeError, ValueError):
        return None
    return x if 0 <= x <= 5 else None          # blank/garbage/out of range = not filled


def _day(v):
    m = re.match(r"\d{4}-\d{2}(-\d{2})?", (v or "").strip())
    return m.group(0) if m else ""


def _clean(rows):
    """Yield (model, job, row_score, day) for every usable row."""
    for r in rows:
        word = (r.get(COL_ROLE) or "").strip().lower()
        job = ROLE_TO_JOB.get(word) or (word if word in JOBS else None)
        model = alias(r.get(COL_MODEL))[0]
        if not job or not model:
            continue
        vals = [x for x in (_num(r.get(d)) for d in DIMS) if x is not None]
        if not vals:
            continue
        yield model, job, statistics.mean(vals) * 2, _day(r.get(COL_DATE))


def build(rows, today=None):
    cells = {}
    for model, job, score, day in _clean(rows):
        cells.setdefault(model, {}).setdefault(job, []).append((score, day))
    models = {}
    for model in sorted(cells):
        out = {}
        for job in JOBS:
            items = cells[model].get(job, [])
            if len(items) >= MIN_RUNS:
                out[job] = {"score": round(statistics.mean(s for s, _ in items), 1),
                            "n": len(items),
                            "latest": max((d for _, d in items), default="")}
        if out:
            models[model] = out
    return {"generated": today or date.today().isoformat(), "models": models}


def find_unaliased(rows):
    """Distinct raw model spellings we could not map with confidence."""
    return sorted({(r.get(COL_MODEL) or "").strip() for r in rows
                   if (r.get(COL_MODEL) or "").strip() and alias(r.get(COL_MODEL))[1]})


def read_rows(*paths):
    """Read the CSVs keeping only COLUMNS (job counts as role, month as date). Exits 2 if a required column is missing."""
    out = []
    for path in paths:
        with open(path, newline="", encoding="utf-8-sig") as f:
            reader = csv.reader(f)
            header = next(reader, [])
            index = {h.strip().lower(): i for i, h in enumerate(header)}
            pick = {COL_MODEL: [COL_MODEL], COL_ROLE: [COL_ROLE, COL_JOB], COL_DATE: [COL_DATE, COL_MONTH]}
            pick.update({d: [d] for d in DIMS})
            missing = [c for c in COLUMNS if not any(n in index for n in pick[c])]
            if missing:
                print("missing columns in %s: %s" % (path, ", ".join(missing)), file=sys.stderr)
                print("file has: " + ", ".join(h.strip() for h in header), file=sys.stderr)
                sys.exit(2)

            def cell(row, names):
                for n in names:                       # first spelling that has a value in this row
                    if n in index and index[n] < len(row) and row[index[n]].strip():
                        return row[index[n]]
                return ""
            out += [{c: cell(row, pick[c]) for c in COLUMNS} for row in reader if any(x.strip() for x in row)]
    return out


def render(table):
    return json.dumps(table, indent=2, sort_keys=True) + "\n"


def selftest():
    dims = {d: "4" for d in DIMS}
    rows = [{"model": "m1", "role": "builder", "date": "2026-10-0%d" % i, "notes": "SECRET-PROJECT", **dims}
            for i in range(1, 6)]
    rows += [{"model": "m1", "role": "reviewer", "date": "2026-10-01", "notes": "SECRET-PROJECT", **dims}
             for _ in range(4)]
    # two dims only: mean(2, 4) * 2 = 6.0, five of them
    rows += [{"model": "m2", "role": "judge", "date": "2026-09-01", "notes": "SECRET-PROJECT",
              DIMS[4]: "2", DIMS[5]: "4"} for _ in range(5)]
    # one model under two spellings, plus a bare alias and an unknown name
    rows += [{"model": "claude-sonnet-5-5", "role": "fixer", "date": "2026-10-02", **dims} for _ in range(3)]
    rows += [{"model": "Claude Sonnet 5.5", "role": "fix", "date": "2026-10-03", **dims} for _ in range(2)]
    rows += [{"model": "sonnet", "role": "plan", "date": "2026-10-04", **dims}]
    rows += [{"model": "weird-model", "role": "builder", "date": "2026-10-04", **dims}]
    rows += [{"model": "m1", "role": "cook", "date": "2026-10-04", **dims}]      # dropped role

    t = build(rows, today="2026-11-04")
    assert t["generated"] == "2026-11-04"
    assert t["models"]["m1"]["build"] == {"score": 8.0, "n": 5, "latest": "2026-10-05"}, t
    assert "review" not in t["models"]["m1"], "4 reviewer rows must not make a cell"
    assert t["models"]["m2"]["review"]["score"] == 6.0, t["models"]["m2"]
    assert list(t["models"]["claude-sonnet-5-5"]) == ["fix"] and \
        t["models"]["claude-sonnet-5-5"]["fix"]["n"] == 5, "two spellings must become one row"
    assert "weird-model" not in t["models"] and "claude-sonnet" not in t["models"]
    un = find_unaliased(rows)
    assert un == ["m1", "m2", "sonnet", "weird-model"], un   # bare alias + names outside known families

    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "runs.csv"
        cols = ["model", "role", "date", "notes"] + DIMS
        with open(p, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=cols, restval="")
            w.writeheader()
            w.writerows(rows)
        got = read_rows(p)
        text = render(build(got, today="2026-11-04"))
        assert "SECRET-PROJECT" not in text and "notes" not in text
        assert json.loads(text) == build(got, today="2026-11-04")
        assert all(set(r) == set(COLUMNS) for r in got)
        bad = Path(d) / "bad.csv"
        bad.write_text("model,role,when\nm,builder,x\n", encoding="utf-8")
        try:
            read_rows(bad)
            raise AssertionError("missing columns must exit 2")
        except SystemExit as e:
            assert e.code == 2
        # community-style CSV (month, job, extra share columns) merges with a role/date CSV into one cell
        a, b = Path(d) / "a.csv", Path(d) / "b.csv"
        a.write_text("model,role,date," + ",".join(DIMS) + "\n" +
                     "".join("m3,builder,2026-10-0%d,%s\n" % (i, ",".join(["4"] * 7)) for i in (1, 2, 3)),
                     encoding="utf-8")
        b.write_text("month,foreman_version,harness,model,job," + ",".join(DIMS) + "\n" +
                     "".join("2026-11,v2.4.2,claude,m3,build,%s\n" % ",".join(["4"] * 7) for _ in range(2)),
                     encoding="utf-8")
        merged = build(read_rows(a, b), today="2026-11-04")
        assert merged["models"]["m3"]["build"] == {"score": 8.0, "n": 5, "latest": "2026-11"}, merged
        assert "m3" not in build(read_rows(a), today="x")["models"], "3 rows alone make no cell"
        assert all(set(r) == set(COLUMNS) for r in read_rows(a, b))
    print("selftest: OK")


def main(argv):
    if argv[:1] == ["selftest"]:
        return selftest()
    out = None
    if "--out" in argv:
        i = argv.index("--out")
        out = argv[i + 1] if i + 1 < len(argv) else None
        argv = argv[:i] + argv[i + 2:]
    if not argv or any(a.startswith("-") for a in argv):
        print(__doc__, file=sys.stderr)
        sys.exit(2)
    rows = read_rows(*argv)
    un = find_unaliased(rows)
    if un:
        print("unaliased models (kept as written, check them): " + ", ".join(un), file=sys.stderr)
    text = render(build(rows))
    if out:
        Path(out).parent.mkdir(parents=True, exist_ok=True)
        Path(out).write_text(text, encoding="utf-8")
    else:
        sys.stdout.write(text)


if __name__ == "__main__":
    main(sys.argv[1:])
