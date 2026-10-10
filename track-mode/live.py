"""Foreman live view: writes the run.json that dashboard/tracker.html renders, from a run's _coord/ folder.

    python live.py build --coord <_coord dir> [--out <dir>]   # writes <dir>/run.json (default <coord>/live/)
    python live.py serve --coord <_coord dir> [--port 8765]   # local page; run.json is rebuilt on every read

The page never changes: put tracker.html and run.json side by side (publish tracker.html as the
Artifact page with `files: {"run.json": ...}`), and the page re-reads run.json every 10 s. To update
the claude.ai copy, republish with the new run.json. run.json is plain data and may be edited by hand.

Reads plan.yaml (milestones and stages, written in the architect pass), events/*.jsonl, launcher/,
staffing.yaml, tracks/*.md and questions.md. Nothing secret goes in: no server password (the launcher
never writes one), no worktree paths, and artifact paths are made relative to the run.
"""
import argparse, datetime, glob, http.server, json, os, re, sys

import yaml  # PyYAML: plan.yaml and staffing.yaml

HERE = os.path.dirname(os.path.abspath(__file__))
TRACKER = os.path.join(HERE, "..", "dashboard", "tracker.html")
KEEP = ("ts", "actor", "to", "kind", "ref", "summary", "artifact", "job", "worker_status", "cost", "tokens", "secs",
        "verdict", "state", "provisional_on", "qid", "reason")
STATES = {"planned", "briefed", "running", "verifying", "review", "fixing", "ready", "merged", "blocked"}
ALIAS = {"in review": "review", "queued": "briefed", "done": "ready", "stuck": "blocked"}


def read(path, default=""):
    try:
        with open(path, encoding="utf-8", errors="replace") as f:  # a file saved in ANSI must not take the page down
            return f.read()
    except OSError:
        return default


def load_yaml(path, default):
    try:
        return yaml.safe_load(read(path)) or default
    except yaml.YAMLError as e:
        return {"_error": f"{os.path.basename(path)} unreadable: {e}"} if isinstance(default, dict) else default


def rel(path, coord):
    if not path or not os.path.isabs(path):
        return path
    run = os.path.dirname(coord)
    return os.path.relpath(path, run) if os.path.abspath(path).startswith(run) else os.path.basename(path)


def short(actor):
    """'builder:opencode/step-5-preview-free' -> 'step-5-preview-free'; 'manager:A' -> 'manager A'."""
    if not actor:
        return ""
    role, _, rest = actor.partition(":")
    return f"manager {rest}" if role == "manager" else (rest or role).split("/")[-1]


def is_go(v):
    v = str(v or "").upper()
    return bool(re.match(r"^(GO|PASS|APPROVED?)\b", v)) and not v.startswith("GO WITH")


def state(coord):
    coord = os.path.abspath(coord)
    events = []
    for f in sorted(glob.glob(os.path.join(coord, "events", "*.jsonl"))):
        for line in read(f).splitlines():
            try:
                e = json.loads(line)
            except ValueError:
                continue  # a half-written last line while its actor is appending
            e = {k: e[k] for k in KEEP if e.get(k) is not None}
            e["artifact"] = rel(e.get("artifact"), coord)
            e["file"] = os.path.basename(f)
            events.append(e)
    events.sort(key=lambda e: e.get("ts", ""))
    jobs = []
    for f in sorted(glob.glob(os.path.join(coord, "launcher", "jobs", "*.json"))):
        j = json.loads(read(f, "{}") or "{}")
        jobs.append({k: j.get(k) for k in ("id", "stage", "role", "model", "actor", "status", "submitted", "started",
                                            "ended", "critical") if j.get(k) is not None})
    pool = json.loads(read(os.path.join(coord, "launcher", "daemon.json"), "{}") or "{}")
    plan = load_yaml(os.path.join(coord, "plan.yaml"), {})
    staffing = load_yaml(os.path.join(coord, "staffing.yaml"), [])
    staffing = staffing if isinstance(staffing, list) else []

    milestones = [{"id": str(m["id"]), "title": m.get("title", ""), "tryIt": m.get("tryIt"), "order": i + 1}
                  for i, m in enumerate(plan.get("milestones") or [])]
    stages, order = {}, {}
    for s in plan.get("stages") or []:
        sid, ms = str(s["id"]), str(s.get("milestone", ""))
        order[ms] = order.get(ms, 0) + 1
        stages[sid] = {"sid": sid, "milestone": ms, "order": order[ms], "title": s.get("title", sid),
                       "depends": [str(d) for d in s.get("needs") or []], "worker": s.get("builder"),
                       "track": s.get("track"), "status": "planned"}
    by_ref = {}
    for e in events:
        by_ref.setdefault(e.get("ref"), []).append(e)

    # stages that appear in events but not in the plan were added mid-run
    stage_kinds = {"brief", "fix_brief", "handback", "verify", "verdict", "clarification", "fallback", "hang", "quota", "failed"}
    for ref, evs in by_ref.items():
        if ref and ref not in stages and any(e["kind"] in stage_kinds for e in evs):
            ms = next((m["id"] for m in milestones if ref.startswith(m["id"])), milestones[-1]["id"] if milestones else "?")
            order[ms] = order.get(ms, 0) + 1
            stages[ref] = {"sid": ref, "milestone": ms, "order": order[ms] + 100, "title": ref, "depends": [],
                           "status": "planned", "origin": "added", "addedAt": evs[0]["ts"],
                           "addedReason": "not in plan.yaml; first seen in the event log"}
            if not any(m["id"] == ms for m in milestones):
                milestones.append({"id": ms, "title": "", "order": len(milestones) + 1})

    answered = {e.get("qid") or e.get("ref") for e in events if e["kind"] == "answer"}
    approved = {e.get("ref") for e in events if e["kind"] == "staff_approved"}
    open_q = [e for e in events if (e["kind"] == "question" and (e.get("qid") or e.get("ref")) not in answered)
              or (e["kind"] == "staff_request" and e.get("ref") not in approved)]

    log, attention = [], []
    for sid, s in stages.items():
        st, it, cur, why = "planned", 0, None, None
        for e in by_ref.get(sid, []):
            k, to, actor = e["kind"], e.get("to") or "", e.get("actor") or ""
            if actor.startswith("manager:") or to.startswith("manager:"):
                s["manager"] = (actor if actor.startswith("manager:") else to).split(":", 1)[1]
            if e.get("provisional_on"):
                s["provisional_on"] = e["provisional_on"]
            if k in ("brief", "fix_brief") and not to.startswith("reviewer:"):
                it += 1
                st, why = ("fixing" if k == "fix_brief" else "briefed"), None
                s["worker"] = short(to)
                cur = {"at": e["ts"], "ref": sid, "kind": "fix" if k == "fix_brief" else "build", "round": it,
                       "actor": short(to), "text": f"{e.get('summary', '')} (in progress)"}
                log.append(cur)
            elif k == "brief":  # to a reviewer
                st = "review"
                cur = {"at": e["ts"], "ref": sid, "kind": "review", "round": max(it, 1), "actor": short(to),
                       "text": "review in progress"}
                log.append(cur)
            elif k == "handback":
                spent = " · ".join(x for x in (f"{round(e['secs'] / 60)} min" if e.get("secs") else "",
                                               f"{e['tokens']:,} tokens" if e.get("tokens") else "") if x)
                if cur:
                    cur["text"] = e.get("summary", "") + (f" ({spent})" if spent else "")
                    cur["actor"] = short(actor)
                st = "review" if actor.startswith("reviewer:") else "verifying"
                if e.get("worker_status") in ("UNSURE", "TOO_HARD", "BLOCKED"):
                    st, why = "blocked", e.get("summary")
            elif k == "verdict":
                if cur and cur["kind"] == "review":
                    cur.update(verdict=e.get("verdict"), text=e.get("summary", ""), actor=short(actor))
                else:
                    log.append({"at": e["ts"], "ref": sid, "kind": "review", "round": max(it, 1), "verdict": e.get("verdict"),
                                "actor": short(actor), "text": e.get("summary", "")})
                st = "ready" if is_go(e.get("verdict")) else "fixing"
                cur = None
            else:
                if k in ("hang", "quota", "failed"):
                    st, why = "blocked", f"{k}: {e.get('summary', '')}"
                    if cur and cur["text"].endswith("(in progress)"):
                        cur["text"] = cur["text"][:-len("(in progress)")] + f"(stopped: {k})"
                elif k == "question":
                    st, why = "blocked", f"waiting on {e.get('qid') or 'an answer'}"
                elif k in ("answer", "fallback", "clarification") and st == "blocked":
                    st, why = ("fixing" if k == "clarification" else "briefed"), None
                elif k == "verify":
                    st = "verifying"
                log.append({"at": e["ts"], "ref": sid, "kind": k, "actor": short(actor),
                            "text": e.get("summary", "") + (f" → {short(to)}" if k == "fallback" and to else "")})
            want = ALIAS.get(e.get("state"), e.get("state"))
            if want in STATES:
                st = want
        live = [j for j in jobs if j.get("stage") == sid and j.get("status") in ("running", "queued")]
        if live:
            j = max(live, key=lambda j: j.get("submitted", ""))
            s["job"] = {k: j.get(k) for k in ("status", "role", "model", "started", "submitted")}
            if st != "blocked":
                st = "review" if j.get("role") == "reviewer" else ("running" if j["status"] == "running" else "briefed")
        s["status"], s["why"] = st, why
        if st == "blocked" and not (why or "").startswith("waiting on "):  # a question is listed once, as the question
            attention.append({"type": "blocked", "ref": sid, "text": why or "blocked", "at": by_ref[sid][-1]["ts"]})
    for e in open_q:
        attention.append({"type": "question" if e["kind"] == "question" else "staffing", "ref": e.get("ref"),
                          "qid": e.get("qid"), "from": short(e.get("actor")), "to": short(e.get("to")),
                          "text": e.get("summary", ""), "at": e["ts"]})
    # events about the run rather than one stage: plan, charters, staffing, milestones, shared notes
    for e in events:
        if e.get("ref") not in stages:
            log.append({"at": e["ts"], "ref": e.get("ref"), "kind": e["kind"], "actor": short(e.get("actor")),
                        "text": e.get("summary", "") + (f" → {short(e.get('to'))}" if e.get("to") else "")})

    running = [s for s in stages.values() if s.get("job", {}).get("status") == "running"]
    ready = [s for s in stages.values() if s["status"] == "ready"]
    waits = [f"{a['qid'] or a['ref']} ({a['from']} → {a['to'] or 'orchestrator'})" for a in attention if a["type"] != "blocked"]
    if ready:
        waits.append(f"Owner: merge decision on {', '.join(s['sid'] for s in ready)}")
    run_name = os.path.basename(os.path.dirname(coord))
    return {
        "meta": {
            "project": plan.get("title") or run_name,
            "subtitle": f"Run {run_name}",
            "focus": ("Running " + "; ".join(f"{s['sid']} ({short(s['job']['model'])}, manager {s.get('manager', '?')})"
                                              for s in running)) if running else "Nothing running.",
            "waitingOn": "; ".join(waits) or "nothing",
            "updated": events[-1]["ts"] if events else None,
        },
        "milestones": milestones,
        "stages": list(stages.values()),
        "log": log,
        "run": {
            "built": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
            "attention": sorted(attention, key=lambda a: a["at"]),
            "staffing": staffing,
            "jobs": jobs,
            "pool": {"slots": pool.get("slots"), "stopped": pool.get("stopped")},
            "handoffs": {ref: [{k: e.get(k) for k in ("ts", "actor", "to", "kind", "summary", "artifact", "job",
                                                      "worker_status", "verdict", "cost", "tokens", "secs", "file")
                                if e.get(k) is not None} for e in evs] for ref, evs in by_ref.items() if ref},
            "files": {**{f"tracks/{os.path.basename(f)}": read(f) for f in sorted(glob.glob(os.path.join(coord, "tracks", "*.md")))},
                      **({"questions.md": read(os.path.join(coord, "questions.md"))}
                         if os.path.exists(os.path.join(coord, "questions.md")) else {})},
            "warnings": [plan["_error"]] if plan.get("_error") else [],
        },
    }


def page():
    # a published Artifact gets its document skeleton from claude.ai; a page served locally needs its own
    return ('<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" '
            'content="width=device-width, initial-scale=1, viewport-fit=cover"></head><body>' + read(TRACKER) + "</body></html>")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cmd", choices=("build", "serve"))
    ap.add_argument("--coord", default=os.environ.get("FOREMAN_COORD"), required="FOREMAN_COORD" not in os.environ)
    ap.add_argument("--out")
    ap.add_argument("--port", type=int, default=8765)
    a = ap.parse_args()
    if a.cmd == "build":
        out = os.path.join(a.out or os.path.join(a.coord, "live"), "run.json")
        os.makedirs(os.path.dirname(out), exist_ok=True)
        with open(out, "w", encoding="utf-8") as f:
            json.dump(state(a.coord), f, indent=1)
        return print(out)

    class H(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            js = self.path.split("?")[0].endswith("/run.json")
            body = (json.dumps(state(a.coord)) if js else page()).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json" if js else "text/html; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            pass

    print(f"live view: http://127.0.0.1:{a.port}/  (Ctrl+C to stop)")
    http.server.ThreadingHTTPServer(("127.0.0.1", a.port), H).serve_forever()


if __name__ == "__main__":
    sys.exit(main())
