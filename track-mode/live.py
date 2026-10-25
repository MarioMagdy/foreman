"""Foreman live view: writes the run.json that dashboard/tracker.html renders, from a run's _coord/ folder.

    python live.py build --coord <_coord dir> [--out <dir>]   # writes <dir>/run.json + tracker.html (default <coord>/live/)
    python live.py serve --coord <_coord dir> [--port 8765]   # local page; run.json is rebuilt on every read

The page never changes: put tracker.html and run.json side by side (publish the built tracker.html, titled
"<project> Foreman", as the Artifact page with `files: {"run.json": ...}`), and the page re-reads run.json every 10 s. To update
the claude.ai copy, republish with the new run.json. run.json is plain data and may be edited by hand.

Reads plan.yaml (milestones and stages, written in the architect pass), events/*.jsonl, launcher/,
staffing.yaml, tracks/*.md and questions.md. Nothing secret goes in: no server password (the launcher
never writes one), no worktree paths, and artifact paths are made relative to the run.
"""
import argparse, datetime, glob, html, http.server, json, os, re, sys

import yaml  # PyYAML: plan.yaml and staffing.yaml

HERE = os.path.dirname(os.path.abspath(__file__))
TRACKER = os.path.join(HERE, "..", "dashboard", "tracker.html")
KEEP = ("ts", "actor", "to", "kind", "ref", "summary", "artifact", "job", "worker_status", "cost", "tokens", "secs",
        "verdict", "state", "provisional_on", "qid", "reason", "options", "recommended")
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


def pid_alive(pid):
    """True if a process with this pid exists. Never sends a signal (os.kill on Windows would terminate it)."""
    try:
        pid = int(pid)
    except (TypeError, ValueError):
        return False
    if os.name == "nt":
        import ctypes
        k = ctypes.windll.kernel32
        h = k.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
        if not h:
            return False
        code = ctypes.c_ulong()
        ok = k.GetExitCodeProcess(h, ctypes.byref(code))
        k.CloseHandle(h)
        return bool(ok) and code.value == 259  # STILL_ACTIVE
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def iso(ts):
    return datetime.datetime.fromtimestamp(ts, datetime.timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def load_coord(coord, seen=()):
    """One _coord folder: events, jobs, plan milestones and stages. plan.yaml `include:` (a list of other _coord
    paths) is loaded first, so an earlier cycle's milestones, stages, events and jobs come before this run's."""
    coord = os.path.abspath(coord)
    plan = load_yaml(os.path.join(coord, "plan.yaml"), {})
    out = {"plan": plan, "events": [], "jobs": [], "milestones": [], "stages": [], "warnings": []}
    for inc in plan.get("include") or []:
        inc = os.path.abspath(str(inc))
        if inc in seen or inc == coord or not os.path.isdir(inc):
            out["warnings"].append(f"include skipped: {inc}")
            continue
        sub = load_coord(inc, seen + (coord,))
        for k in ("events", "jobs", "warnings"):
            out[k] += sub[k]
        for m in sub["milestones"]:
            if not any(x["id"] == m["id"] for x in out["milestones"]):
                out["milestones"].append(m)
        out["stages"] += [x for x in sub["stages"] if not any(str(y["id"]) == str(x["id"]) for y in out["stages"])]
    for f in sorted(glob.glob(os.path.join(coord, "events", "*.jsonl"))):
        for line in read(f).splitlines():
            try:
                e = json.loads(line)
            except ValueError:
                continue  # a half-written last line while its actor is appending
            e = {k: e[k] for k in KEEP if e.get(k) is not None}
            e["artifact"] = rel(e.get("artifact"), coord)
            e["file"] = os.path.basename(f)
            out["events"].append(e)
    for f in sorted(glob.glob(os.path.join(coord, "launcher", "jobs", "*.json"))):
        j = json.loads(read(f, "{}") or "{}")
        out["jobs"].append({k: j.get(k) for k in ("id", "stage", "role", "model", "actor", "status", "submitted", "started",
                                                   "ended", "critical", "expect") if j.get(k) is not None})
    for m in plan.get("milestones") or []:
        if not any(x["id"] == str(m["id"]) for x in out["milestones"]):
            out["milestones"].append({"id": str(m["id"]), "title": m.get("title", ""), "tryIt": m.get("tryIt"),
                                      "kind": m.get("kind", "planned"), "adds": m.get("adds"), "done_when": m.get("done_when"),
                                      # optional milestone-to-milestone dependencies the page draws on its overview map
                                      "needs": [str(x) for x in (m.get("needs") or [])] or None})
    out["stages"] += plan.get("stages") or []
    return out


def now_panel(coord, jobs, lab):
    """What is running at build time, from the CURRENT coord: managers (wake state), jobs, launcher pool."""
    wake = json.loads(read(os.path.join(coord, "launcher", "wake", "state.json"), "{}") or "{}")
    daemon = json.loads(read(os.path.join(coord, "launcher", "daemon.json"), "{}") or "{}")
    now = datetime.datetime.now(datetime.timezone.utc)
    mgrs = []
    for mid in sorted(set(wake.get("procs") or {}) | set(wake.get("flight") or {}) | set(wake.get("pending") or {})):
        fl = (wake.get("flight") or {}).get(mid) or {}
        pid = (wake.get("procs") or {}).get(mid)
        awake = bool(fl) and (pid_alive(pid) if pid else True)
        since = None
        if awake and fl.get("log"):
            try:
                since = iso(os.path.getctime(fl["log"]))
            except OSError:
                since = None
        mgrs.append({"id": mid, "state": "awake" if awake else "asleep", "pid": pid if awake else None, "since": since,
                     "items": len((wake.get("pending") or {}).get(mid) or []) + (len(fl.get("items") or []) if awake else 0)})
    rows = []
    for j in jobs:
        if j.get("status") not in ("running", "queued"):
            continue
        t0 = j.get("started") or j.get("submitted")
        mins = None
        try:
            mins = round((now - datetime.datetime.fromisoformat(t0.replace("Z", "+00:00"))).total_seconds() / 60, 1)
        except (AttributeError, ValueError):
            pass
        exp = j.get("expect")
        rows.append({"id": j.get("id"), "stage": lab(j.get("stage")), "role": j.get("role"), "model": short(j.get("model") or ""),
                     "actor": j.get("actor"), "status": j["status"], "since": t0, "minutes": mins, "expect": exp,
                     "over": bool(exp and mins is not None and j["status"] == "running" and mins > 1.5 * exp)})
    used = sum(1 for r in rows if r["status"] == "running")
    return {"asOf": iso(now.timestamp()), "managers": mgrs, "jobs": rows,
            "pool": {"slots": daemon.get("slots"), "used": used, "up": pid_alive(daemon.get("pid")), "url": daemon.get("url")}}


def state(coord):
    coord = os.path.abspath(coord)
    L = load_coord(coord)
    events, jobs, plan = L["events"], L["jobs"], L["plan"]
    events.sort(key=lambda e: e.get("ts", ""))
    pool = json.loads(read(os.path.join(coord, "launcher", "daemon.json"), "{}") or "{}")
    staffing = load_yaml(os.path.join(coord, "staffing.yaml"), [])
    staffing = staffing if isinstance(staffing, list) else []

    milestones = [dict(m, order=i + 1) for i, m in enumerate(L["milestones"])]
    stages, order, labels = {}, {}, {}
    for s in L["stages"]:
        sid, ms = str(s["id"]), str(s.get("milestone", ""))
        order[ms] = order.get(ms, 0) + 1
        if s.get("label"):
            labels[sid] = str(s["label"])
        stages[sid] = {"sid": sid, "milestone": ms, "order": order[ms], "title": s.get("title", sid),
                       "depends": [str(d) for d in s.get("needs") or []], "worker": s.get("builder"),
                       "track": s.get("track"), "status": "planned", "kind": s.get("kind", "build"),
                       "gate": s.get("gate"), "check": s.get("check"), "bar": s.get("bar")}
    lab = lambda x: labels.get(x, x)

    def parent(ref):
        """A ref that is not a plan stage id (worktree 'M2a-b', split part 'M2b.1') -> its plan stage, else the ref."""
        if not ref or ref in stages:
            return ref
        for cand in (re.sub(r"\.\d+$", "", ref), re.sub(r"-[ab]$", "", re.sub(r"\.\d+$", "", ref))):
            if cand in stages:
                return cand
        return ref

    for e in events:
        r = parent(e.get("ref"))
        if r != e.get("ref"):
            e["sub"], e["ref"] = e["ref"], r
            e["summary"] = f"[{e['sub']}] {e.get('summary', '')}"
    for j in jobs:
        if j.get("stage"):
            j["stage"] = parent(j["stage"])
    by_ref = {}
    for e in events:
        by_ref.setdefault(e.get("ref"), []).append(e)

    # stages that appear in events but not in the plan were added mid-run
    stage_kinds = {"brief", "fix_brief", "handback", "verify", "verdict", "clarification", "fallback", "hang", "quota", "failed"}
    for ref, evs in by_ref.items():
        if ref and ref not in stages and not (ref.startswith("track-") or ref == "wake" or any(m["id"] == ref for m in milestones))                 and any(e["kind"] in stage_kinds for e in evs):
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
            if e.get("sub") and st == "ready":  # a split part reporting after the parent's GO: logged, status stays GO
                log.append({"at": e["ts"], "ref": sid, "kind": k, "actor": short(actor), "text": e.get("summary", "")})
                continue
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
    # one entry per question id: who raised it, every hop it took (a manager asks, the orchestrator passes it
    # on to the owner under the same qid), and the options for whoever holds it now
    asks = {}
    for e in open_q:
        key = (e.get("qid") or e.get("ref")) if e["kind"] == "question" else "staff:" + str(e.get("ref"))
        hop = {"from": short(e.get("actor")), "to": short(e.get("to")), "at": e["ts"], "text": e.get("summary", "")}
        a = asks.setdefault(key, {"type": "question" if e["kind"] == "question" else "staffing", "ref": e.get("ref"),
                                  "qid": e.get("qid"), "from": hop["from"], "text": hop["text"], "chain": []})
        a["chain"].append(hop)
        a.update(to=hop["to"], at=e["ts"])
        a.update({k: e[k] for k in ("options", "recommended") if e.get(k)})
    attention.extend(asks.values())
    # events about the run rather than one stage: plan, charters, staffing, milestones, shared notes
    for e in events:
        if e.get("ref") not in stages:
            log.append({"at": e["ts"], "ref": e.get("ref"), "kind": e["kind"], "actor": short(e.get("actor")),
                        "text": e.get("summary", "") + (f" → {short(e.get('to'))}" if e.get("to") else "")})

    # the owner's gate per milestone: ready -> owner review; owner accepts -> its PRs may merge; rejected -> back to stages
    gate_of = {"milestone_ready": "owner_review", "milestone_accepted": "accepted", "milestone_rejected": None}
    for m in milestones:
        for e in by_ref.get(m["id"], []):
            if e["kind"] in gate_of:
                m["gate"] = gate_of[e["kind"]]
    open_ms = {s["milestone"] for s in stages.values() if s["status"] not in ("ready", "merged")}
    in_review = {m["id"] for m in milestones if m.get("gate") == "owner_review" and m["id"] not in open_ms}

    running = [s for s in stages.values() if s.get("job", {}).get("status") == "running"]
    waits = [f"{a['qid'] or a['ref']} ({a['from']} → {a['to'] or 'orchestrator'})" for a in attention if a["type"] != "blocked"]
    if in_review:
        waits.append(f"Owner: review {', '.join(m['id'] for m in milestones if m['id'] in in_review)} (test plans)")
    # ready stages are not listed: a gated stage merges into its milestone without the owner (default 2026-10-21)
    run_name = os.path.basename(os.path.dirname(coord))
    project, _, rest = str(plan.get("title") or "").partition(":")
    project = str(plan.get("project") or "").strip() or project.strip() or run_name   # page shows "<project> foreman"
    rest = rest.strip() if not plan.get("project") else str(plan.get("title") or "")
    included = [os.path.basename(os.path.dirname(os.path.abspath(str(i)))) for i in plan.get("include") or []]
    out = {
        "meta": {
            "project": project,
            "subtitle": (rest + " · " if rest and rest != project else "")
                        + ("Runs " + ", ".join(included + [run_name]) if included else f"Run {run_name}"),
            "focus": ("Running " + "; ".join(f"{s['sid']} ({short(s['job']['model'])}" + (f", manager {s['manager']})" if s.get('manager') else ")")
                                              for s in running)) if running else "Nothing running.",
            "waitingOn": "; ".join(waits) or "nothing",
            # run settings (run sheet `settings:` block, copied into plan.yaml), one line on the page header
            "settings": " · ".join(f"{k} {v}" for k, v in (plan.get("settings") or {}).items()) or None,
            "updated": events[-1]["ts"] if events else None,
        },
        "milestones": milestones,
        "stages": list(stages.values()),
        "log": log,
        "run": {
            "built": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
            "attention": sorted(attention, key=lambda a: a["at"]),
            "staffing": staffing,
            "jobs": [dict(j, stage=lab(j.get("stage"))) for j in jobs],
            "now": now_panel(coord, jobs, lab),
            "pool": {"slots": pool.get("slots"), "stopped": pool.get("stopped")},
            "handoffs": {ref: [{k: e.get(k) for k in ("ts", "actor", "to", "kind", "summary", "artifact", "job",
                                                      "worker_status", "verdict", "cost", "tokens", "secs", "file")
                                if e.get(k) is not None} for e in evs] for ref, evs in by_ref.items() if ref},
            "files": {**{f"tracks/{os.path.basename(f)}": read(f) for f in sorted(glob.glob(os.path.join(coord, "tracks", "*.md")))},
                      **({"questions.md": read(os.path.join(coord, "questions.md"))}
                         if os.path.exists(os.path.join(coord, "questions.md")) else {})},
            "warnings": ([plan["_error"]] if plan.get("_error") else []) + L["warnings"],
        },
    }
    return relabel(out, labels) if labels else out


def relabel(out, labels):
    """Show each stage by its plan `label` (M2-S2) instead of its internal id (M2a), everywhere in run.json."""
    lab = lambda x: labels.get(x, x) if isinstance(x, str) else x
    sub = lambda t: re.sub(r"\b[\w-]+\b", lambda m: labels.get(m.group(0), m.group(0)), t) if isinstance(t, str) else t
    for s in out["stages"]:
        s["key"] = s["sid"]
        s["sid"], s["depends"] = lab(s["sid"]), [lab(d) for d in s["depends"]]
        s["title"] = s["title"] if s["title"] != s["key"] else lab(s["key"])
    for e in out["log"]:
        e["ref"] = lab(e.get("ref"))
    run = out["run"]
    for a in run["attention"]:
        a["ref"] = lab(a.get("ref"))
    run["handoffs"] = {lab(k): v for k, v in run["handoffs"].items()}
    m = out["meta"]
    m["focus"], m["waitingOn"] = sub(m["focus"]), sub(m["waitingOn"])
    return out


def titled(project):
    """The tracker with its <title> set to "<project> Foreman": an artifact is named after the <title> it was published with."""
    return read(TRACKER).replace("<title>Foreman</title>", f"<title>{html.escape(project)} Foreman</title>", 1)


def page(project):
    # a published Artifact gets its document skeleton from claude.ai; a page served locally needs its own
    return ('<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" '
            'content="width=device-width, initial-scale=1, viewport-fit=cover"></head><body>' + titled(project) + "</body></html>")


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
        st = state(a.coord)
        with open(out, "w", encoding="utf-8") as f:
            json.dump(st, f, indent=1)
        with open(os.path.join(os.path.dirname(out), "tracker.html"), "w", encoding="utf-8") as f:
            f.write(titled(st["meta"]["project"]))  # publish this copy, with run.json beside it
        return print(out)

    class H(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            js = self.path.split("?")[0].endswith("/run.json")
            st = state(a.coord)
            body = (json.dumps(st) if js else page(st["meta"]["project"])).encode()
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
