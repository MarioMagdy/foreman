#!/usr/bin/env python3
"""Foreman SessionStart reminder: after a compaction, resume or restart, put the active run back in front of the model.

    session_context.py claude|codex     hook entry: reads the hook JSON (cwd, session_id) on stdin, prints
                                        {"hookSpecificOutput": {...additionalContext...}} only when there is text,
                                        always exits 0
    session_context.py selftest         temp folders only; prints "selftest: OK"

Looks for `_runs/ACTIVE` in the working folder or any folder above it. One line per run:
`<run folder relative to the repo root> <orchestrator session id>` (`-` = id unknown on this harness).
Lines starting with `#` and malformed lines are ignored. Workers and managers (FOREMAN_ROLE set) get nothing.
The text is at most 1500 bytes. Stdlib only.
"""
import datetime
import glob
import importlib.util
import json
import os
import re
import sys
import tempfile

LIMIT = 1500
STALE_H = 24
STAGE_RE = re.compile(r"^M\d+(-S[\d.]+)?$")
HERE = os.path.dirname(os.path.abspath(__file__))


def _minutes():
    """Check-in interval from the machine settings store; 60 when it cannot be read."""
    try:
        spec = importlib.util.spec_from_file_location("foreman_store", os.path.join(HERE, "..", "setup", "store.py"))
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        n = int(mod.get("checkin.minutes", 60))
        return n if n > 0 else 60
    except Exception:
        return 60


def _ts(s):
    """ISO-8601 (Z, offset or none = UTC) to epoch seconds, or None."""
    try:
        d = datetime.datetime.fromisoformat(str(s).strip().replace("Z", "+00:00"))
        if d.tzinfo is None:
            d = d.replace(tzinfo=datetime.timezone.utc)
        return d.timestamp()
    except Exception:
        return None


def _hhmm(t):
    return "--:--" if t is None else datetime.datetime.fromtimestamp(t, datetime.timezone.utc).strftime("%H:%M")


def _find_active(cwd):
    d = os.path.abspath(cwd)
    while True:
        p = os.path.join(d, "_runs", "ACTIVE")
        if os.path.isfile(p):
            return d, p
        parent = os.path.dirname(d)
        if parent == d:
            return None, None
        d = parent


def _read_lines(p):
    """[(folder, session id)] from an ACTIVE file; comments and malformed lines are dropped."""
    out = []
    with open(p, encoding="utf-8", errors="replace") as f:
        for raw in f:
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            parts = line.rsplit(None, 1)
            if len(parts) != 2:
                continue
            folder, sid = parts[0].strip().strip('"'), parts[1]
            norm = folder.replace("\\", "/")
            if not folder or os.path.isabs(folder) or norm.startswith("/") or ".." in norm.split("/") or re.match(r"^[A-Za-z]:", norm):
                continue
            if any(ord(c) < 32 or c == "�" for c in line):
                continue  # binary junk
            out.append((folder, sid))
    return out


def _events(run_dir):
    """All parsable event dicts, in file order; broken lines are skipped."""
    out = []
    for f in sorted(glob.glob(os.path.join(run_dir, "_coord", "events", "*.jsonl"))):
        try:
            with open(f, encoding="utf-8", errors="replace") as fh:
                for raw in fh:
                    try:
                        e = json.loads(raw)
                    except Exception:
                        continue
                    if isinstance(e, dict):
                        out.append(e)
        except Exception:
            continue
    return out


def _tracker_url(run_dir):
    """First `url:` value after a `dashboard:` line in run-sheet.md."""
    try:
        with open(os.path.join(run_dir, "run-sheet.md"), encoding="utf-8", errors="replace") as f:
            in_block = False
            for line in f:
                if re.match(r"^\s*dashboard\s*:", line):
                    in_block = True
                    m = re.search(r"url\s*:\s*[\"']?(\S+?)[\"']?\s*$", line)  # inline form
                    if m:
                        return m.group(1)
                    continue
                if in_block:
                    m = re.match(r"^\s*(?:-\s*)?url\s*:\s*[\"']?(\S+?)[\"']?\s*$", line)
                    if m:
                        return m.group(1)
    except Exception:
        pass
    return None


def _one(s, n=200):
    s = " ".join(str(s).split())
    return s if len(s) <= n else s[: n - 1] + "…"


def _full(folder, run_dir, minutes, now, budget):
    evs = _events(run_dir)
    stamped = [(t, i, e) for i, e in enumerate(evs) for t in [_ts(e.get("ts"))]]
    newest = max(stamped, key=lambda x: (x[0] is not None, x[0] or 0, x[1]), default=None)
    head = f"Foreman run: {folder}"
    if newest and newest[0] is not None and now - newest[0] > STALE_H * 3600:
        h = int((now - newest[0]) // 3600)
        head += f" (STALE: no events for {h} h; ask the owner whether to resume or close it)"
    lines = [head, f"Tracker: {_tracker_url(run_dir) or 'none published'}"]

    stages = {}
    for t, i, e in sorted(stamped, key=lambda x: (x[0] if x[0] is not None else -1, x[1])):
        ref = str(e.get("ref", ""))
        if STAGE_RE.match(ref):
            stages[ref] = (e.get("kind", "?"), t)
    answered = {e.get("qid") or e.get("ref") for e in evs if e.get("kind") == "answer"}
    qids = []
    for e in evs:
        if e.get("kind") == "question" and e.get("to") == "owner":
            q = e.get("qid") or e.get("ref")
            if q and q not in answered and str(q) not in qids:
                qids.append(str(q))
    tail = []
    if qids:
        tail.append("Open questions for you: " + ", ".join(qids[:10]) + (f" … {len(qids) - 10} more" if len(qids) > 10 else ""))
    if newest:
        tail.append("Last logged: " + _one(newest[2].get("summary", "")))
    tail.append(f"Check-in: every {minutes} min. If the scheduled check-in is gone (it dies with the session), "
                "re-create it now, and re-arm the handback Monitor.")
    tail.append("Re-read run-sheet.md and the newest events before acting; never trust memory for paths or URLs.")

    entries = [f"  {r} {k} {_hhmm(t)}" for r, (k, t) in sorted(stages.items(), key=lambda kv: (kv[1][1] or 0), reverse=True)]

    def build(n):
        parts = list(lines)
        if entries:
            parts.append("Stages:")
            parts += entries[:n]
            if n < len(entries):
                parts.append(f"  … {len(entries) - n} more")
        return "\n".join(parts + tail)

    n = len(entries)
    while n > 0 and len(build(n).encode("utf-8")) > budget:
        n -= 1
    return build(n)


def context(cwd, session_id, env, now):
    """The reminder text for this session, or "" when there is nothing to say. Never raises."""
    try:
        if (env or {}).get("FOREMAN_ROLE"):
            return ""
        root, path = _find_active(cwd or ".")
        if not root:
            return ""
        runs = _read_lines(path)
        if not runs:
            return ""
        sid = session_id or ""
        mine = [f for f, s in runs if s == "-" or (sid and s == sid)]
        other = [f for f, s in runs if not (s == "-" or (sid and s == sid))]
        if not sid:
            other = []  # no session id: cannot tell whose run it is, stay quiet unless the line says "unknown"
        notes = [f"A Foreman run is active in {f}. If you are taking it over, say so (and rewrite its line in "
                 f"_runs/ACTIVE with your session id); otherwise ignore this." for f in other]
        minutes = _minutes()
        fixed = sum(len(n.encode("utf-8")) + 2 for n in notes)
        blocks = []
        for f in mine:
            blocks.append(_full(f, os.path.join(root, f), minutes, now, max(300, (LIMIT - fixed) // max(1, len(mine)))))
        text = "\n\n".join(blocks + notes)
        b = text.encode("utf-8")
        if len(b) > LIMIT:
            text = b[:LIMIT].decode("utf-8", "ignore")
        return text
    except Exception:
        return ""


def main(argv=None, stdin=None, out=None):
    argv = sys.argv[1:] if argv is None else argv
    out = out or sys.stdout
    if argv[:1] == ["selftest"]:
        return selftest()
    try:
        raw = (stdin or sys.stdin).read()
        data = json.loads(raw)
        text = context(data.get("cwd") or os.getcwd(), data.get("session_id"), os.environ, datetime.datetime.now().timestamp())
        if text:
            out.write(json.dumps({"hookSpecificOutput": {"hookEventName": "SessionStart", "additionalContext": text}}) + "\n")
    except SystemExit:
        raise
    except BaseException:
        pass
    return 0


def selftest():
    import io
    old = os.environ.get("FOREMAN_HOME")
    tmp = tempfile.mkdtemp()
    os.environ["FOREMAN_HOME"] = os.path.join(tmp, "nohome")  # keep the real settings out of the test
    try:
        repo = os.path.join(tmp, "my repo")  # a space on purpose
        run = os.path.join(repo, "_runs", "2026-11-04-x")
        ev = os.path.join(run, "_coord", "events")
        os.makedirs(ev)
        os.makedirs(os.path.join(repo, "sub"))
        with open(os.path.join(repo, "_runs", "ACTIVE"), "w") as f:
            f.write("# comment\nbroken-line-without-id\n/abs/path sid-9\n../up sid-9\n_runs/2026-11-04-x sid-1\n")
        with open(os.path.join(run, "run-sheet.md"), "w") as f:
            f.write("goal: x\ndashboard:\n  url: https://example.test/tracker\n")
        t0 = datetime.datetime(2026, 11, 4, 10, 0, tzinfo=datetime.timezone.utc).timestamp()

        def line(ts, kind, ref, summary, **kw):
            return json.dumps(dict({"ts": ts, "actor": "a", "to": "foreman", "kind": kind, "ref": ref, "summary": summary}, **kw))
        with open(os.path.join(ev, "a.jsonl"), "w") as f:
            f.write(line("2026-11-04T10:00:00Z", "brief", "M1-S1", "brief out") + "\n")
            f.write("{this is broken\n")
            f.write(line("2026-11-04T10:30:00", "verdict", "M1-S1", "approved with nits") + "\n")  # no timezone
            f.write(line("2026-11-04T10:40:00+00:00", "question", "M1", "which db?", to="owner", qid="q1") + "\n")
            f.write(line("2026-11-04T10:41:00Z", "question", "M1", "old one", to="owner", qid="q0") + "\n")
            f.write(line("2026-11-04T10:42:00Z", "answer", "M1", "use sqlite", qid="q0") + "\n")
        now = t0 + 3600
        sub = os.path.join(repo, "sub")
        t = context(sub, "sid-1", {}, now)
        for need in ("_runs/2026-11-04-x", "M1-S1 verdict", "q1", "re-create it now", "https://example.test/tracker",
                     "Last logged: use sqlite", "every 60 min"):
            assert need in t, (need, t)
        assert "q0" not in t.replace("Last logged", ""), t
        assert len(t.encode("utf-8")) <= LIMIT, len(t)
        assert "STALE" not in t
        o = context(sub, "other", {}, now)
        assert "If you are taking it over" in o and "Stages:" not in o, o
        assert context(sub, None, {}, now) == ""  # no session id: stay quiet
        assert context(sub, "sid-1", {"FOREMAN_ROLE": "worker"}, now) == ""
        assert context(tmp, "sid-1", {}, now) == ""  # no ACTIVE above this folder
        assert context(os.path.join(tmp, "missing", "dir"), "sid-1", {}, now) == ""
        assert "STALE" in context(sub, "sid-1", {}, t0 + 42 * 60 + 25 * 3600), "stale"
        with open(os.path.join(repo, "_runs", "ACTIVE"), "a") as f:
            f.write("_runs/unknown-run -\n")  # id unknown: full text for any session
        assert "Foreman run: _runs/unknown-run" in context(sub, "whatever", {}, now)
        assert "Foreman run: _runs/unknown-run" in context(sub, None, {}, now)
        with open(os.path.join(repo, "_runs", "ACTIVE"), "w") as f:
            f.write("_runs/2026-11-04-x sid-1\n")
        with open(os.path.join(ev, "b.jsonl"), "w") as f:
            for i in range(200):
                f.write(line(f"2026-11-04T10:{i % 60:02d}:00Z", "build", f"M2-S{i}", "s") + "\n")
        big = context(sub, "sid-1", {}, now)
        assert len(big.encode("utf-8")) <= LIMIT and "more" in big and "re-create it now" in big, big
        # a corrupt ACTIVE prints nothing
        with open(os.path.join(repo, "_runs", "ACTIVE"), "wb") as f:
            f.write(b"\xff\xfe\x00 garbage\n\n   \n")
        assert context(sub, "sid-1", {}, now) == ""
        # CLI: bad stdin, good stdin
        buf = io.StringIO()
        assert main(["claude"], io.StringIO("not json"), buf) == 0 and buf.getvalue() == ""
        with open(os.path.join(repo, "_runs", "ACTIVE"), "w") as f:
            f.write("_runs/2026-11-04-x sid-1\n")
        buf = io.StringIO()
        main(["codex"], io.StringIO(json.dumps({"cwd": sub, "session_id": "sid-1"})), buf)
        o = json.loads(buf.getvalue())["hookSpecificOutput"]
        assert o["hookEventName"] == "SessionStart" and "Foreman run:" in o["additionalContext"]
        buf = io.StringIO()
        main(["claude"], io.StringIO(json.dumps({"cwd": tmp})), buf)
        assert buf.getvalue() == ""
    finally:
        if old is None:
            os.environ.pop("FOREMAN_HOME", None)
        else:
            os.environ["FOREMAN_HOME"] = old
    print("selftest: OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
