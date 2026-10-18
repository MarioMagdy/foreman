"""Foreman worker launcher: one `opencode serve` per run, a slot pool, and hand-off events.

Contract: track-mode/LAUNCHER.md. Stdlib only, Windows-first.

    python launcher.py --coord <_coord dir> start [--port 4300] [--slots 3] [--db <opencode db>]
    python launcher.py --coord D submit --stage M2a --role builder --model opencode/step-5-preview-free \
                                        --brief briefs/M2a-a.md --workdir <worktree> --actor A [--expect 15] [--critical]
    python launcher.py --coord D status|wait|cancel <job>
    python launcher.py --coord D soft <job> [--why "..."]      # soft stop through the job's _scratch/MAILBOX.md
    python launcher.py --coord D jobs [--actor A]
    python launcher.py --coord D health
    python launcher.py --coord D stop

`--coord` defaults to $FOREMAN_COORD. One writer per file: `submit` writes queue/<job>.json once,
`cancel` drops cancel/<job>; everything else (jobs/, events/launcher.jsonl, reports/) is the daemon's.
"""
import argparse, base64, ctypes, datetime, json, os, re, secrets, shutil, subprocess, sys, time, urllib.request

def find_opencode():
    """$FOREMAN_OPENCODE, else opencode on PATH; an npm shim (.cmd) resolves to the real binary beside it."""
    if os.environ.get("FOREMAN_OPENCODE"):
        return os.environ["FOREMAN_OPENCODE"]
    found = shutil.which("opencode")
    if found and found.lower().endswith((".cmd", ".ps1")):
        exe = os.path.join(os.path.dirname(found), "node_modules", "opencode-ai", "bin", "opencode.exe")
        if os.path.exists(exe):
            return exe
    return found or "opencode"


EXE = find_opencode()
NOWIN, DETACHED, NEWGROUP, BREAKAWAY = 0x08000000, 0x00000008, 0x00000200, 0x01000000
QUOTA = re.compile(r"usage limit", re.I)
STATUS = re.compile(r"^\s*STATUS:\s*(DONE|UNSURE|TOO_HARD|BLOCKED)\b.*$", re.M)
MSG = "Your brief is the attached file. Follow it exactly, and end with the STATUS block it asks for."
FINAL = ("done", "failed", "hung", "quota", "cancelled")
SOFT_STOP = ("SOFT STOP: finish the step you are on (do not start a new one), commit it, write _scratch/HANDOFF.md "
             "(what is done, what is left, how to continue, test status), then end with your STATUS block.")  # = delegation/mailbox.py


def now():
    return datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def cmd(*args):
    return ([sys.executable, EXE] if EXE.endswith(".py") else [EXE]) + list(args)


def rjson(path, default=None):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


def wjson(path, data):
    tmp = f"{path}.{os.getpid()}.tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=1)
    for _ in range(20):  # a reader holding the file open blocks os.replace on Windows
        try:
            return os.replace(tmp, path)
        except PermissionError:
            time.sleep(0.05)
    os.replace(tmp, path)


def alive(pid):
    if not pid:
        return False
    h = ctypes.windll.kernel32.OpenProcess(0x1000, False, int(pid))  # PROCESS_QUERY_LIMITED_INFORMATION
    if not h:
        return False
    code = ctypes.c_ulong()
    ctypes.windll.kernel32.GetExitCodeProcess(h, ctypes.byref(code))
    ctypes.windll.kernel32.CloseHandle(h)
    return code.value == 259  # STILL_ACTIVE


def kill(pid):
    if alive(pid):
        subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], capture_output=True)


class Coord:
    def __init__(self, root):
        self.root = os.path.abspath(root)
        self.dir = os.path.join(self.root, "launcher")
        for d in ("queue", "jobs", "cancel", "logs"):
            os.makedirs(os.path.join(self.dir, d), exist_ok=True)
        os.makedirs(os.path.join(self.root, "events"), exist_ok=True)
        os.makedirs(os.path.join(self.root, "reports"), exist_ok=True)

    def p(self, *parts):
        return os.path.join(self.dir, *parts)

    def daemon(self):
        return rjson(self.p("daemon.json"), {})

    def job(self, jid):
        return rjson(self.p("jobs", jid + ".json")) or rjson(self.p("queue", jid + ".json"))


# ---------------------------------------------------------------- the daemon (sole writer of state)
class Daemon:
    def __init__(self, c, port, slots, db, hang_min, tick):
        self.c, self.port, self.slots, self.db, self.hang_min, self.tick = c, port, slots, db, hang_min, tick
        self.url = f"http://127.0.0.1:{port}"
        self.pw = secrets.token_urlsafe(18)
        self.server = None
        self.log_off = 0
        self.procs = {}  # job id -> Popen (children of this daemon only)
        self.bad_health = 0

    # -- plumbing
    def env(self):
        # one skill folder for workers: without this opencode loads ~/.claude/skills AND ~/.agents/skills (duplicates,
        # and the owner's orchestration skills); see delegation/skills.json
        e = dict(os.environ, OPENCODE_SERVER_PASSWORD=self.pw, OPENCODE_DISABLE_CLAUDE_CODE_SKILLS="1")
        if self.db:
            e["OPENCODE_DB"] = self.db
        return e

    def http(self, method, path, timeout=10):
        req = urllib.request.Request(self.url + path, method=method, data=b"" if method == "POST" else None)
        req.add_header("Authorization", "Basic " + base64.b64encode(f"opencode:{self.pw}".encode()).decode())
        with urllib.request.urlopen(req, timeout=timeout) as r:
            raw = r.read()
            return json.loads(raw) if raw.strip() else None

    def event(self, kind, job, summary, actor="launcher", to=None, artifact=None, **extra):
        e = {"ts": now(), "actor": actor, "to": to or f"manager:{job['actor']}", "kind": kind, "ref": job["stage"],
             "summary": summary, "artifact": artifact, "job": job["id"], "via": "launcher"}
        e.update({k: v for k, v in extra.items() if v is not None})
        with open(os.path.join(self.c.root, "events", "launcher.jsonl"), "a", encoding="utf-8") as f:
            f.write(json.dumps(e) + "\n")

    def save(self, job):
        wjson(self.c.p("jobs", job["id"] + ".json"), job)

    def state(self):
        wjson(self.c.p("daemon.json"), {"pid": os.getpid(), "port": self.port, "url": self.url, "slots": self.slots,
                                        "server_pid": self.server.pid if self.server else None, "db": self.db,
                                        "updated": now()})

    # -- server
    def start_server(self):
        log = open(self.c.p("server.log"), "ab")
        self.server = subprocess.Popen(cmd("serve", "--port", str(self.port), "--print-logs", "--log-level", "INFO"),
                                       cwd=self.c.dir, stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT,
                                       creationflags=NOWIN, env=self.env())
        for _ in range(240):
            if self.healthy():
                self.state()
                return
            time.sleep(0.5)
        raise RuntimeError("opencode serve did not become healthy in 120 s; see launcher/server.log")

    def healthy(self):
        try:
            return bool(self.http("GET", "/global/health", timeout=3).get("healthy"))
        except Exception:
            return False

    # -- one pass
    def jobs(self):
        out = []
        for name in os.listdir(self.c.p("queue")):
            jid = name[:-5]
            job = rjson(self.c.p("jobs", name))
            if job is None:  # new submission: take it over and log the hand-off
                job = rjson(self.c.p("queue", name))
                if job is None:
                    continue
                job.update(status="queued", retries=0)
                self.save(job)
                brief = os.path.relpath(job["brief"], self.c.root) if job["brief"].startswith(self.c.root) else job["brief"]
                self.event("fix_brief" if job.get("fix") else "brief", job, f"{job['role']} {job['model']} queued{' (critical path)' if job.get('critical') else ''}",
                           actor=f"manager:{job['actor']}", to=f"{job['role']}:{job['model']}", artifact=brief)
            out.append(job)
        return out

    def finish(self, job, status, summary, kind, reason=None, **extra):
        job.update(status=status, ended=now(), reason=reason)
        self.save(job)
        self.procs.pop(job["id"], None)
        actor = f"{job['role']}:{job['model']}" if kind == "handback" else "launcher"
        self.event(kind, job, summary, actor=actor, artifact=job.get("report"), **extra)

    def stop_job(self, job):
        if job.get("session"):
            try:
                self.http("POST", f"/session/{job['session']}/abort")
            except Exception:
                pass
        kill(job.get("pid"))

    def session_id(self, job):
        try:
            with open(self.c.p("logs", job["id"] + ".out"), encoding="utf-8", errors="replace") as f:
                return json.loads(f.readline()).get("sessionID")
        except (OSError, ValueError):
            return None

    def collect(self, job, rc):
        """Client exited: fetch the answer from the server, write the report."""
        try:
            msgs = self.http("GET", f"/session/{job['session']}/message", timeout=30) if job.get("session") else []
            info = self.http("GET", f"/session/{job['session']}") if job.get("session") else {}
        except Exception as e:
            return self.finish(job, "failed", f"answer not readable: {e}", "failed", reason="no-answer")
        texts = [m for m in msgs if m["info"]["role"] == "assistant" and any(p.get("type") == "text" for p in m["parts"])]
        errors = [str(m["info"].get("error")) for m in msgs if m["info"]["role"] == "assistant" and m["info"].get("error")]
        answer = "".join(p.get("text", "") for p in texts[-1]["parts"] if p.get("type") == "text") if texts else ""
        cost = info.get("cost")
        tokens = sum((m["info"].get("tokens") or {}).get("total") or 0 for m in msgs if m["info"]["role"] == "assistant") or None
        secs = round(time.time() - job["started_epoch"])
        report = os.path.join(self.c.root, "reports", job["id"] + ".md")
        with open(report, "w", encoding="utf-8") as f:
            f.write(f"<!-- job {job['id']} | {job['role']} {job['model']} | session {job.get('session')} | rc {rc} | "
                    f"{secs}s | cost {cost} | tokens {tokens} -->\n\n{answer}\n")
            if errors:
                f.write("\n## Errors\n\n" + "\n".join(errors) + "\n")
        job["report"] = os.path.relpath(report, self.c.root)
        if errors and any(QUOTA.search(e) for e in errors):
            return self.finish(job, "quota", strip(errors[-1]), "quota", reason="usage limit", secs=secs)
        st = list(STATUS.finditer(answer))  # the last block is the worker's final word
        if rc == 0 and answer:
            return self.finish(job, "done", st[-1].group(0).strip() if st else "no STATUS block", "handback",
                               worker_status=st[-1].group(1) if st else None, cost=cost, tokens=tokens, secs=secs)
        why = strip(errors[-1]) if errors else f"client exit {rc}, {'no answer' if not answer else 'answer present'}"
        self.finish(job, "failed", why, "failed", reason=f"exit:{rc}", cost=cost, tokens=tokens, secs=secs)

    def scan_quota(self, running):
        try:
            with open(self.c.p("server.log"), "rb") as f:
                f.seek(self.log_off)
                chunk = f.read()
                self.log_off = f.tell()
        except OSError:
            return
        by_session = {j.get("session"): j for j in running if j.get("session")}
        for line in chunk.decode("utf-8", "replace").splitlines():
            if "level=ERROR" in line and QUOTA.search(line):
                m = re.search(r"session\.id=(\S+)", line)
                job = by_session.get(m.group(1)) if m else None
                if job and job["status"] == "running":
                    self.stop_job(job)
                    msg = re.search(r'error\.error="([^"]*)', line)
                    self.finish(job, "quota", strip(msg.group(1) if msg else line), "quota", reason="usage limit")

    def spawn(self, job):
        out = open(self.c.p("logs", job["id"] + ".out"), "wb")
        p = subprocess.Popen(cmd("run", MSG, "--attach", self.url, "--dir", job["workdir"], "--auto", "-m", job["model"],
                                 "--format", "json", "--title", job["id"], "-f", job["brief"]),
                             cwd=job["workdir"], stdin=subprocess.DEVNULL, stdout=out, stderr=subprocess.STDOUT,
                             creationflags=NOWIN, env=self.env())
        self.procs[job["id"]] = p
        job.update(status="running", pid=p.pid, started=now(), started_epoch=time.time(), session=None)
        self.save(job)
        time.sleep(2)  # stagger client starts (Windows 0xC0000142 under burst process creation)

    def once(self):
        if self.healthy():
            self.bad_health = 0
        else:
            self.bad_health += 1
            if self.bad_health >= 3:  # server gone: every attached job died with it
                kill(self.server.pid if self.server else None)
                for job in [j for j in self.jobs() if j["status"] == "running"]:
                    kill(job.get("pid"))
                    if job.get("retries", 0) < 1:
                        job.update(status="queued", retries=job.get("retries", 0) + 1, pid=None, session=None)
                        self.save(job)
                        self.event("failed", job, "opencode server died; job re-queued once", reason="server")
                    else:
                        self.finish(job, "failed", "opencode server died again", "failed", reason="server")
                self.start_server()
                self.bad_health = 0
        jobs = self.jobs()
        for name in os.listdir(self.c.p("cancel")):
            job = next((j for j in jobs if j["id"] == name), None)
            if job and job["status"] in ("queued", "running"):
                self.stop_job(job)
                self.finish(job, "cancelled", "cancelled by its manager", "failed", reason="cancelled")
            os.remove(self.c.p("cancel", name))
        running = [j for j in jobs if j["status"] == "running"]
        for job in running:
            if not job.get("session"):
                job["session"] = self.session_id(job)
                if job["session"]:
                    self.save(job)
        self.scan_quota(running)  # before the hang check: a quota-stuck job looks hung too
        for job in [j for j in running if j["status"] == "running"]:
            p = self.procs.get(job["id"])
            rc = p.poll() if p else (None if alive(job.get("pid")) else 0)
            if rc is not None:
                self.collect(job, rc)
                continue
            last = job["started_epoch"]
            for name in ("PROGRESS.md", "ACTIVITY.log"):  # delegation progress files: model and hook heartbeats
                try:
                    last = max(last, os.path.getmtime(os.path.join(job["workdir"], "_scratch", name)))
                except OSError:
                    pass
            if job.get("session"):
                try:
                    last = max(last, self.http("GET", f"/session/{job['session']}")["time"]["updated"] / 1000)
                except Exception:
                    pass
            limit = max(2 * job.get("expect", 15), self.hang_min) * 60
            if time.time() - last > limit:
                self.stop_job(job)
                self.finish(job, "hung", f"no session activity for {round((time.time() - last) / 60, 1)} min", "hang",
                            reason="hang")
        free =self.slots - sum(1 for j in self.jobs() if j["status"] == "running")
        waiting = sorted((j for j in self.jobs() if j["status"] == "queued"),
                         key=lambda j: (not j.get("critical"), j["submitted"]))
        for job in waiting[:max(free, 0)]:
            self.spawn(job)
        self.state()

    def run(self):
        d = self.c.daemon()
        if d.get("server_pid") and alive(d["server_pid"]):  # previous daemon died; its server holds the port
            kill(d["server_pid"])
        for job in self.jobs():  # restart: clients of a dead daemon are orphans, re-queue them once
            if job["status"] == "running":
                kill(job.get("pid"))
                job.update(status="queued", retries=job.get("retries", 0) + 1, pid=None, session=None)
                self.save(job)
                self.event("failed", job, "launcher restarted; job re-queued", reason="launcher")
        try:
            self.log_off = os.path.getsize(self.c.p("server.log"))
        except OSError:
            pass
        self.start_server()
        while not os.path.exists(self.c.p("stop")):
            try:
                self.once()
            except Exception as e:  # keep the pool alive; the error is in daemon.log
                with open(self.c.p("daemon.log"), "a", encoding="utf-8") as f:
                    f.write(f"{now()} {type(e).__name__}: {e}\n")
            time.sleep(self.tick)
        for job in self.jobs():
            if job["status"] == "running":
                self.stop_job(job)
                self.finish(job, "failed", "launcher stopped", "failed", reason="stopped")
        kill(self.server.pid if self.server else None)
        os.remove(self.c.p("stop"))
        wjson(self.c.p("daemon.json"), {"stopped": now()})


def strip(text):
    return re.sub(r"https?://\S+", "<url>", text)[:300]  # quota messages carry the account's workspace URL


# ---------------------------------------------------------------- the CLI (never writes daemon-owned files)
def cli():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--coord", default=os.environ.get("FOREMAN_COORD"))
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("start", "daemon"):
        s = sub.add_parser(name)
        s.add_argument("--port", type=int, default=4300)
        s.add_argument("--slots", type=int, default=3)
        s.add_argument("--db", help="separate opencode database for this run (OPENCODE_DB)")
        s.add_argument("--hang-min", type=float, default=20)
        s.add_argument("--tick", type=float, default=3)
    s = sub.add_parser("submit")
    for a in ("--stage", "--role", "--model", "--brief", "--workdir", "--actor"):
        s.add_argument(a, required=True)
    s.add_argument("--expect", type=float, default=15, help="expected minutes; hang = max(2x this, --hang-min)")
    s.add_argument("--critical", action="store_true", help="critical-path stage: jumps the queue")
    s.add_argument("--fix", action="store_true", help="a fix round (logged as fix_brief)")
    for name in ("status", "wait", "cancel"):
        sub.add_parser(name).add_argument("job")
    s = sub.add_parser("soft")
    s.add_argument("job")
    s.add_argument("--why", default="")
    sub.add_parser("jobs").add_argument("--actor")
    sub.add_parser("health")
    sub.add_parser("stop")
    a = ap.parse_args()
    if not a.coord:
        ap.error("--coord or FOREMAN_COORD is required")
    c = Coord(a.coord)

    if a.cmd == "daemon":
        return Daemon(c, a.port, a.slots, a.db and os.path.abspath(a.db), a.hang_min, a.tick).run()
    if a.cmd == "start":
        d = c.daemon()
        if alive(d.get("pid")):
            return print(f"already running: pid {d['pid']}, {d.get('url')}")
        args = [sys.executable, os.path.abspath(__file__), "--coord", c.root, "daemon", "--port", str(a.port),
                "--slots", str(a.slots), "--hang-min", str(a.hang_min), "--tick", str(a.tick)] + (["--db", a.db] if a.db else [])
        log = open(c.p("daemon.log"), "ab")
        kw = dict(stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT, close_fds=True, cwd=c.dir)
        try:  # break away from the calling shell's job object so the pool outlives the tool call
            p = subprocess.Popen(args, creationflags=DETACHED | NEWGROUP | BREAKAWAY | NOWIN, **kw)
        except OSError:
            p = subprocess.Popen(args, creationflags=DETACHED | NEWGROUP | NOWIN, **kw)
        for _ in range(300):
            d = c.daemon()
            if d.get("pid") == p.pid and d.get("server_pid"):
                return print(f"started: pid {p.pid}, server {d['url']}, {a.slots} slots")
            if p.poll() is not None:
                sys.exit(f"daemon exited ({p.returncode}); see {c.p('daemon.log')}")
            time.sleep(0.5)
        sys.exit("daemon did not report a healthy server in 150 s")
    if a.cmd == "submit":
        brief = a.brief if os.path.isabs(a.brief) else next(
            (p for p in (os.path.join(c.root, a.brief), os.path.abspath(a.brief)) if os.path.exists(p)), None)
        if not brief or not os.path.exists(brief):
            sys.exit(f"brief not found: {a.brief}")
        if not os.path.isdir(a.workdir):
            sys.exit(f"workdir not found: {a.workdir}")
        job = {"stage": a.stage, "role": a.role, "model": a.model, "brief": os.path.abspath(brief),
               "workdir": os.path.abspath(a.workdir), "actor": a.actor, "expect": a.expect, "critical": a.critical, "fix": a.fix,
               "submitted": now()}
        for n in range(1, 1000):  # O_EXCL: two managers submitting at once never get the same id
            jid = f"{a.stage}-{a.role}-{n}"
            try:
                fd = os.open(c.p("queue", jid + ".json"), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            except FileExistsError:
                continue
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(dict(job, id=jid), f, indent=1)
            return print(jid)
    if a.cmd in ("status", "wait"):
        while True:
            job = c.job(a.job)
            if not job:
                sys.exit(f"no such job: {a.job}")
            st = job.get("status", "queued")
            st = f"failed:{job['reason']}" if st == "failed" and job.get("reason") else st
            if a.cmd == "status" or job.get("status") in FINAL:
                return print(st + (f"  report: {job['report']}" if job.get("report") else ""))
            time.sleep(5)
    if a.cmd == "cancel":
        open(c.p("cancel", a.job), "w").close()
        return print(f"cancel requested: {a.job}")
    if a.cmd == "soft":  # delegation soft stop: the worker's mailbox hook delivers it at its next tool call
        job = c.job(a.job) or sys.exit(f"no such job: {a.job}")
        os.makedirs(os.path.join(job["workdir"], "_scratch"), exist_ok=True)
        with open(os.path.join(job["workdir"], "_scratch", "MAILBOX.md"), "a", encoding="utf-8") as f:
            f.write(f"[{now()}] {SOFT_STOP}{' Reason: ' + a.why if a.why else ''}\n")
        return print(f"soft stop queued for {a.job}; `cancel` it after the grace period if no handback")
    if a.cmd == "jobs":
        for name in sorted(os.listdir(c.p("queue"))):
            job = c.job(name[:-5])
            if job and (not a.actor or job["actor"] == a.actor):
                print(f"{job['id']:<28} {job.get('status', 'queued'):<10} {job['actor']:<6} {job['model']:<36} {job.get('report') or ''}")
        return
    if a.cmd == "health":
        d = c.daemon()
        ok = alive(d.get("pid")) and alive(d.get("server_pid"))
        running = sum(1 for n in os.listdir(c.p("queue")) if (c.job(n[:-5]) or {}).get("status") == "running")
        queued = sum(1 for n in os.listdir(c.p("queue")) if (c.job(n[:-5]) or {}).get("status", "queued") == "queued")
        print(f"{'ok' if ok else 'DOWN'}: daemon {d.get('pid')}, server {d.get('server_pid')} {d.get('url', '')}, "
              f"{running}/{d.get('slots', '?')} running, {queued} queued, updated {d.get('updated')}")
        sys.exit(0 if ok else 1)
    if a.cmd == "stop":
        d = c.daemon()
        if not alive(d.get("pid")):
            return print("not running")
        open(c.p("stop"), "w").close()
        for _ in range(60):
            if not alive(d["pid"]):
                return print("stopped")
            time.sleep(0.5)
        kill(d["pid"])
        kill(d.get("server_pid"))
        print("stopped (forced)")


if __name__ == "__main__":
    cli()
