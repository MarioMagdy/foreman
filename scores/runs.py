#!/usr/bin/env python3
"""Foreman's private log of checked workers, and the opt-in share of anonymous ratings.

    runs.py add --model M --job J --harness H --scores 4,5,4,4,5,4,4
    runs.py pending        one line when ratings exist for models with no or few scores, else nothing
    runs.py share          the question, the rows exactly as they would be sent, and a prefilled issue link
    runs.py mark yes|no    record the answer on every pending row (yes: only the rows the link carries)
    runs.py selftest

The log is <FOREMAN_HOME or ~/.foreman>/local-runs.csv and never leaves the machine by itself.
Sharing means printing a GitHub "new issue" link; the user reads it and clicks Submit. Stdlib only.
"""
import csv
import importlib.util
import json
import os
import re
import sys
from datetime import date
from urllib.parse import quote, urlencode

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
REPO_NEW_ISSUE = "https://github.com/MarioMagdy/foreman/issues/new?"
MAX_URL = 7000
TABLE = os.path.join(HERE, "models.yaml")


def _load(name, *parts):
    spec = importlib.util.spec_from_file_location(name, os.path.join(*parts))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


_bs = _load("foreman_build_scores", HERE, "build_scores.py")
store = _load("foreman_store", ROOT, "setup", "store.py")
DIMS, JOBS, MIN_RUNS, alias = _bs.DIMS, _bs.JOBS, _bs.MIN_RUNS, _bs.alias

LOG_COLUMNS = ["date", "foreman_version", "harness", "model", "job"] + DIMS + ["shared"]
# The only fields that ever leave the machine, in this order. Built from this list, never from a row.
SHARE_COLUMNS = ["month", "foreman_version", "harness", "model", "job"] + DIMS
QUESTION = ("Share %d anonymous ratings (model, job, grades; no project data) with the Foreman repo "
            "so others can see how these models do? (Recommended: yes)")
INTRO = "Anonymous ratings from Foreman runs: model, job, seven 0-5 grades. No project data."
LEFT = "\n%d more ratings were left for the next share.\n"
BLOCK = re.compile(r"```csv\n(.*?)\n```\n", re.S)


def log_path():
    return os.path.join(store.home(), "local-runs.csv")


def _version():
    try:
        with open(os.path.join(ROOT, "VERSION"), encoding="utf-8") as f:
            return f.read().strip() or "v0"
    except OSError:
        return "v0"


def read_log():
    try:
        with open(log_path(), newline="", encoding="utf-8-sig") as f:
            return [{c: (r.get(c) or "") for c in LOG_COLUMNS} for r in csv.DictReader(f)]
    except OSError:
        return []


def _write_log(rows):
    os.makedirs(store.home(), exist_ok=True)
    with open(log_path(), "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=LOG_COLUMNS, lineterminator="\n", extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)


def add(model, job, harness, scores, today=None):
    """Append one checked worker to the private log and return the row."""
    if job not in JOBS:
        raise ValueError("job must be one of: " + ", ".join(JOBS))
    if (not isinstance(scores, (list, tuple)) or len(scores) != len(DIMS)
            or any(type(x) is not int or not 0 <= x <= 5 for x in scores)):
        raise ValueError("give exactly %d whole-number grades from 0 to 5, in this order: %s"
                         % (len(DIMS), ", ".join(DIMS)))
    name = alias(model)[0]
    if not name:
        raise ValueError("name the model with its version, e.g. claude-sonnet-5-5")
    harness = (harness or "").strip()
    if not re.fullmatch(r"[\w.\-]{1,32}", harness):
        raise ValueError("harness is one short word such as claude, codex or opencode")
    row = {"date": today or date.today().isoformat(), "foreman_version": _version(), "harness": harness,
           "model": name, "job": job, "shared": ""}
    row.update({d: str(x) for d, x in zip(DIMS, scores)})
    # Append one line rather than rewrite the file, so two workers logged at the same moment both land.
    os.makedirs(store.home(), exist_ok=True)
    with open(log_path(), "a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=LOG_COLUMNS, lineterminator="\n", extrasaction="ignore")
        if f.tell() == 0:
            w.writeheader()
        w.writerow(row)
    return row


def pending(table, rows):
    """Unanswered rows whose model/job has no cell in the table, or a cell with fewer than MIN_RUNS runs."""
    models = (table or {}).get("models") or {}
    out = []
    for r in rows:
        if (r.get("shared") or "") != "":
            continue
        cell = (models.get(r.get("model")) or {}).get(r.get("job"))
        if not cell or (cell.get("n") or 0) < MIN_RUNS:
            out.append(r)
    return out


def _safe(v):
    """One CSV field: letters, digits and . _ - / : only, so nothing can break the block or carry prose."""
    return re.sub(r"[^\w.\-/:]", "", str(v if v is not None else ""))


def _lines(rows):
    """CSV lines for the share block, header first, from SHARE_COLUMNS only."""
    out = [",".join(SHARE_COLUMNS)]
    for r in rows:
        vals = dict(r, month=str(r.get("date", ""))[:7])
        out.append(",".join(_safe(vals.get(c, "")) for c in SHARE_COLUMNS))
    return out


def _title(k, rows):
    models = []
    for r in rows:
        m = _safe(r.get("model", ""))
        if m not in models:
            models.append(m)
    shown = models[:3] + (["+%d" % (len(models) - 3)] if len(models) > 3 else [])
    return "Model ratings: %d runs (%s)" % (k, ", ".join(shown))


def payload(rows):
    """(title, body) of the issue. Only SHARE_COLUMNS are ever read from a row."""
    body = INTRO + "\n\n```csv\n" + "\n".join(_lines(rows)) + "\n```\n"
    return _title(len(rows), rows), body


def _url(title, body):
    return REPO_NEW_ISSUE + urlencode({"title": title, "body": body, "labels": "rating"}, quote_via=quote)


def _cut(title, body):
    """(title, body, kept): the payload cut to the CSV lines that fit in MAX_URL characters, with a note."""
    m = BLOCK.search(body)
    if len(_url(title, body)) <= MAX_URL or not m:
        return title, body, None
    lines = m.group(1).split("\n")
    head, data = lines[0], lines[1:]

    def make(n):
        t = re.sub(r"\d+ runs", "%d runs" % n, title, count=1)
        note = LEFT % (len(data) - n) if n < len(data) else ""
        return t, body[:m.start()] + "```csv\n" + "\n".join([head] + data[:n]) + "\n```\n" + note + body[m.end():]
    lo, hi = 1, len(data)           # always keep one row; a single row is far below the limit
    while lo < hi:
        mid = (lo + hi + 1) // 2
        if len(_url(*make(mid))) <= MAX_URL:
            lo = mid
        else:
            hi = mid - 1
    return make(lo) + (lo,)


def issue_url(title, body):
    """The prefilled new-issue link. Over MAX_URL characters, only as many CSV lines as fit are kept."""
    t, b, _ = _cut(title, body)
    return _url(t, b)


def share_plan(rows):
    """(kept, title, body, url): how many of these rows the link carries, and the link itself."""
    title, body = payload(rows)
    t, b, kept = _cut(title, body)
    return (len(rows) if kept is None else kept), t, b, _url(t, b)


def load_table():
    try:
        with open(TABLE, encoding="utf-8") as f:
            text = f.read()
    except OSError:
        return {}
    try:
        d = json.loads(text)
    except ValueError:
        try:
            import yaml
            d = yaml.safe_load(text)
        except Exception:
            return {}
    return d if isinstance(d, dict) else {}


def main(argv):
    cmd = argv[0] if argv else ""
    if cmd == "selftest":
        return selftest()
    if cmd == "add":
        a = dict(zip(argv[1::2], argv[2::2]))
        try:
            scores = [int(x) for x in a.get("--scores", "").split(",")]
            row = add(a.get("--model", ""), a.get("--job", ""), a.get("--harness", ""), scores)
        except ValueError as e:
            print("not logged: %s" % e, file=sys.stderr)
            return 2
        print("logged %s %s" % (row["model"], row["job"]))
        return 0
    if cmd == "pending":
        rows = pending(load_table(), read_log())
        if rows:
            print("%d ratings for models with no or few scores: %s"
                  % (len(rows), ", ".join(sorted({r["model"] for r in rows}))))
        return 0
    if cmd == "share":
        rows = pending(load_table(), read_log())
        if rows:
            kept, title, body, url = share_plan(rows)
            print(QUESTION % kept)
            print("\nTitle: " + title + "\n")
            print(body)
            print(url)
        return 0
    if cmd == "mark" and argv[1:2] in (["yes"], ["no"]):
        rows = read_log()
        todo = pending(load_table(), rows)          # the same row objects, so marking them marks `rows`
        for r in (todo[:share_plan(todo)[0]] if argv[1] == "yes" and todo else todo):
            r["shared"] = argv[1]
        _write_log(rows)
        return 0
    print(__doc__, file=sys.stderr)
    return 2


def selftest():
    import contextlib
    import io
    import tempfile
    from urllib.parse import parse_qs, urlsplit
    global TABLE
    old_home, old_table = os.environ.get("FOREMAN_HOME"), TABLE
    tmp = tempfile.mkdtemp()
    os.environ["FOREMAN_HOME"] = os.path.join(tmp, "fh")
    try:
        assert not os.path.exists(log_path()), "fresh temp home has no log"
        assert log_path() == os.path.join(tmp, "fh", "local-runs.csv")
        good = [4, 5, 4, 4, 5, 4, 4]
        r = add("Claude Sonnet 5.5", "build", "claude", good, today="2026-11-04")
        assert r["model"] == "claude-sonnet-5-5" and r["job"] == "build" and r["shared"] == "", r
        assert r["date"] == "2026-11-04" and r["harness"] == "claude" and r["foreman_version"], r
        assert [r[d] for d in DIMS] == [str(x) for x in good], r
        with open(log_path(), newline="", encoding="utf-8") as f:
            header = next(csv.reader(f))
        assert header == ["date", "foreman_version", "harness", "model", "job"] + DIMS + ["shared"], header
        add("gpt-5.6", "review", "codex", good, today="2026-11-05")
        add("gpt-5.6", "review", "codex", good, today="2026-11-06")
        add("rare-model", "fix", "opencode", good, today="2026-11-06")

        def bad(*a):
            try:
                add(*a)
            except ValueError as e:
                assert str(e), "message must be plain text"
                return str(e)
            raise AssertionError("expected ValueError for %r" % (a,))
        bad("m", "cook", "claude", good)
        bad("m", "build", "claude", good + [3])
        bad("m", "build", "claude", [4, 5, 4, 4, 5, 4, 6])
        bad("m", "build", "claude", [4, 5, 4, 4, 5, 4, -1])
        bad("m", "build", "claude", [4, 5, 4, 4, 5, 4, 2.5])
        assert "claude-sonnet-5-5" in bad("sonnet", "build", "claude", good), "unversioned name hint"
        assert len(read_log()) == 4, "failed adds must not write"

        table = {"models": {"claude-sonnet-5-5": {"build": {"score": 9.0, "n": 8, "latest": "2026-10"}},
                            "gpt-5.6": {"review": {"score": 8.0, "n": 3, "latest": "2026-10"}}}}
        p = pending(table, read_log())
        assert [(x["model"], x["job"]) for x in p] == [("gpt-5.6", "review"), ("gpt-5.6", "review"),
                                                       ("rare-model", "fix")], p
        assert pending(table, [dict(read_log()[1], shared="no")]) == [], "answered rows are not pending"

        rows = [dict(x) for x in p]
        rows[0]["notes"] = "SECRET-PROJECT"
        rows[0]["cwd"] = "C:/secret/path"
        title, body = payload(rows)
        assert title == "Model ratings: 3 runs (gpt-5.6, rare-model)", title
        for d in DIMS:
            assert d in body, d
        assert "SECRET-PROJECT" not in body and "notes" not in body and "secret" not in body.lower()
        assert INTRO in body
        assert "\n2026-11," in body and "2026-11-05" not in body, "month only, no day"
        assert body.count("```") == 2
        many = [dict(rows[1], model="m%d" % i) for i in range(5)]
        assert payload(many)[0] == "Model ratings: 5 runs (m0, m1, m2, +2)", payload(many)[0]

        url = issue_url(title, body)
        assert url.startswith(REPO_NEW_ISSUE) and "labels=rating" in url and len(url) <= 7000
        assert "left for the next share" not in url
        big = [dict(rows[1]) for _ in range(500)]
        t2, b2 = payload(big)
        u2 = issue_url(t2, b2)
        assert len(u2) <= 7000 and u2.startswith(REPO_NEW_ISSUE), len(u2)
        got = parse_qs(urlsplit(u2).query)
        assert got["labels"] == ["rating"]
        sent = got["body"][0].count("\n2026-11,")
        assert 0 < sent < 500, sent
        assert "%d more ratings were left for the next share" % (500 - sent) in got["body"][0]
        assert share_plan(big)[0] == sent, "mark yes must cover exactly the rows the link carries"
        assert got["title"][0].startswith("Model ratings: %d runs" % sent), (got["title"][0], sent)

        # CLI round trip on the temp log with a temp table
        tp = os.path.join(tmp, "models.yaml")
        with open(tp, "w", encoding="utf-8") as f:
            json.dump(table, f)
        TABLE = tp

        def run(*argv):
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                assert main(list(argv)) == 0
            return out.getvalue()
        assert run("pending") == ("3 ratings for models with no or few scores: gpt-5.6, rare-model\n")
        o = run("share")
        assert o.startswith(QUESTION % 3), o[:200]
        assert "Share 3 anonymous ratings (model, job, grades; no project data) with the Foreman repo " \
               "so others can see how these models do? (Recommended: yes)" in o
        assert "gpt-5.6,review" in o and "https://github.com/MarioMagdy/foreman/issues/new?" in o
        run("mark", "yes")
        assert pending(load_table(), read_log()) == []
        assert run("pending") == "" and run("share") == ""
        assert [x["shared"] for x in read_log()] == ["", "yes", "yes", "yes"], "rated rows stay unmarked"
        run("add", "--model", "gpt-5.6", "--job", "review", "--harness", "codex", "--scores", "1,2,3,4,5,4,3")
        run("mark", "no")
        assert read_log()[-1]["shared"] == "no" and run("pending") == ""
        # workers logged at the same moment all land
        import threading
        n = len(read_log())
        ts = [threading.Thread(target=add, args=("gpt-5.6", "build", "codex", good)) for _ in range(8)]
        [t.start() for t in ts]
        [t.join() for t in ts]
        assert len(read_log()) == n + 8, len(read_log())
    finally:
        TABLE = old_table
        if old_home is None:
            os.environ.pop("FOREMAN_HOME", None)
        else:
            os.environ["FOREMAN_HOME"] = old_home
    print("selftest: OK")


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
