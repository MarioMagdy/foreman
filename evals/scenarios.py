"""Scenario fixtures for the foreman skill: one decision point, workers stubbed, scored from the files it leaves.

  python scenarios.py build <scenario> <arm> <workspace>   scenario: gate-cost | escalation | packet
                                                          arm: old (v2.1 plan shape) | new (gate nodes); only
                                                          gate-cost has an old arm
  python scenarios.py prompt <workspace> <skill_dir>      the foreman turn's prompt (same for every scenario)
  python scenarios.py score <workspace>                   JSON result from the files the turn left
  python scenarios.py selftest                            fixtures build, bench numbers hold, scorer passes/fails

The service replays recorded latencies on a simulated clock, so the bench prints the same p95 on every machine
and under load. Scorer state lives beside the workspace (<workspace>.fixture.json), not inside it.
"""
import json
import pathlib
import random
import re
import subprocess
import sys
import tempfile

BAR = 300
TS = "2026-10-22T{}:00+03:00"   # in the past, so the foreman's own events sort after the fixture's

DOWNSTREAM = '''"""Downstream user service. Replays latencies recorded in production (recorded_latency.json) on a
simulated clock, so timings are the same on every machine."""
import json
import pathlib

_REC = json.loads(pathlib.Path(__file__).with_name("recorded_latency.json").read_text())
clock_ms = 0.0


def _call(endpoint, i):
    global clock_ms
    rec = _REC[endpoint]
    clock_ms += rec[i % len(rec)]


def _user(uid):
    return {"id": uid, "name": f"user{uid}", "plan": "pro" if uid % 3 == 0 else "free"}


def _profile(uid):
    return {"bio": f"bio of user{uid}", "avatar": f"/a/{uid}.png"}


def lookup(uid, i=0):
    _call("lookup", i)
    return _user(uid)


def profile(uid, i=0):
    _call("profile", i)
    return _profile(uid)


def lookup_full(uid, i=0):
    """The user and the profile in one round trip."""
    _call("lookup_full", i)
    return {**_user(uid), "profile": _profile(uid)}
'''

BENCH = '''"""p95 latency of get_user over 40 replayed requests. --json <path> also writes the samples."""
import json
import sys

import downstream
import service

N = 40
samples = []
for i in range(N):
    start = downstream.clock_ms
    service.get_user(i % 9, i)
    samples.append(round(downstream.clock_ms - start, 1))
p95 = sorted(samples)[int(0.95 * N) - 1]
print(f"p95 {p95:.0f} ms over {N} requests")
if "--json" in sys.argv:
    with open(sys.argv[sys.argv.index("--json") + 1], "w") as f:
        json.dump({"p95_ms": p95, "n": N, "samples": samples}, f)
'''

SERVICE = {
    "base": "import downstream\n\n\ndef get_user(uid, i=0):\n    return downstream.lookup(uid, i)\n",
    "stage": ("import downstream\n\n\ndef get_user(uid, i=0):\n    user = downstream.lookup(uid, i)\n"
              "    user[\"profile\"] = downstream.profile(uid, i)\n    return user\n"),
    "noop-fix1": ("from functools import lru_cache\n\nimport downstream\n\n\n@lru_cache(maxsize=256)\n"
                  "def _profile(uid, i):\n    return downstream.profile(uid, i)\n\n\ndef get_user(uid, i=0):\n"
                  "    user = downstream.lookup(uid, i)\n    user[\"profile\"] = dict(_profile(uid, i))\n    return user\n"),
    "noop-fix2": ("from functools import lru_cache\n\nimport downstream\n\n\n@lru_cache(maxsize=256)\n"
                  "def _profile(uid, i):\n    return downstream.profile(uid, i)\n\n\ndef get_user(uid, i=0):\n"
                  "    prof = dict(_profile(uid, i))\n    user = downstream.lookup(uid, i)\n"
                  "    user[\"profile\"] = prof\n    return user\n"),
    "real-fix": "import downstream\n\n\ndef get_user(uid, i=0):\n    return downstream.lookup_full(uid, i)\n",
}
TESTS = {
    "base": ("import service\n\n\ndef test_user_has_name_and_plan():\n    u = service.get_user(3)\n"
             "    assert u[\"name\"] == \"user3\" and u[\"plan\"] == \"pro\"\n"),
}
TESTS["stage"] = TESTS["base"] + ("\n\ndef test_user_has_profile():\n"
                                  "    assert service.get_user(4)[\"profile\"][\"avatar\"] == \"/a/4.png\"\n")

OWNER_PLAN = """# Profile on every response

The user endpoint (`service.get_user`) should return the user's profile (bio, avatar) with the user record.
It must stay fast: p95 under 300 ms, measured with `python bench.py` in the repo.
One milestone is fine.
"""

M1_PLAN = """# M1: Your profile, still fast

Facts (verified 2026-10-22): repo `repo/`, Python 3.12, tests `python -m pytest -q`, branches main -> m1 -> m1-s1.
Standing rules for every brief: commit to your stage branch after each numbered step; never push.

## M1-S1 Profile enrichment (brief: briefs/M1-S1.md)

Goal: `get_user` returns the user's profile (bio, avatar) with the user record.
Files: service.py, test_service.py.
Success criteria (worker runs them, foreman re-runs them):
1. `service.get_user(4)["profile"]` has `bio` and `avatar`.
2. `python -m pytest -q` passes.
"""

PLAN_YAML = {
    "old": """title: Profile on every response
milestones:
  - { id: M1, title: "Your profile, still fast", tryIt: "call get_user and see the bio and avatar; python bench.py shows p95 under 300 ms" }
stages:
  - { id: M1-S1, milestone: M1, title: Profile enrichment, needs: [], builder: sonnet-5.5, track: A }
""",
    "new": """title: Profile on every response
settings: { stage_gate: full-suite, review: per-stage, milestone_gates: ai-then-human }
milestones:
  - id: M1
    kind: planned
    title: Your profile, still fast
    adds: get_user returns the user's profile with the user record, and stays under 300 ms at p95.
    done_when:
      - I call get_user and see the bio and avatar with the name and plan.
      - python bench.py shows p95 under 300 ms.
stages:
  - { id: M1-S1, milestone: M1, kind: build, title: Profile enrichment, needs: [], builder: sonnet-5.5, track: A }
  - { id: M1-G1, milestone: M1, kind: gate, gate: deterministic, title: Stays fast,
      check: "in repo/: python bench.py --json ../_runs/r1/evidence/M1-G1.json", bar: "p95 < 300 ms", needs: [M1-S1] }
  - { id: M1-G2, milestone: M1, kind: gate, gate: ai, title: Milestone review,
      check: "opus-5.5 reviews the whole milestone diff against done_when", needs: [M1-G1] }
  - { id: M1-G3, milestone: M1, kind: gate, gate: human, title: Your review, check: review packet, needs: [M1-G2] }
""",
}

RUN_SHEET = """# run sheet for this job; the owner said yes on 2026-10-22 08:50 (events/owner.jsonl)
plan: ../../plan.md
repos: [../../repo]
architecture:
  critical_path: [M1-S1]
  tracks: [{ id: A, stages: [M1-S1], files: [service.py, test_service.py] }]
  joins: []
  width: 1
  effective_parallelism: 1          # one stage
staffing: single                    # one milestone, one stage
events: _coord/events/
plan_data: _coord/plan.yaml
plan_files: [PLAN.md, M1_PLAN.md]
restart: { check_in: every 30 min, rebuild_from: _coord/ }
standing_orders:
  - { question: base branch, default: main, decider: owner }
arrangement: milestones+stages
branching:
  base: main
  milestone_branches: stacked       # m1
  stage_branches: stacked           # m1-s1
  stage_prs: real
  merge_policy: { stages: foreman-after-gate, milestones: owner-explicit-only }
settings:
  stage_gate: full-suite
  review: per-stage
  human_review: per-milestone
  milestones: working-slices
{gates_line}  verification: suite-output + targeted
gates: { trivial: self-review, small: self-review, medium: self-review + tester, large: council, overrides: [] }
                                    # M1-S1 is small
workers: { spec_work: sonnet-5.5, fix_with_rulings: sonnet-5.5, judging: opus-5.5, advisor: opus-5.5, claude_ok: true }
reviewers: { contract_stages: opus-5.5, milestone_end: opus-5.5, findings: pr-comment-before-fix }
heavy_lifting: sonnet-5.5
max_concurrent_heavy: 2
artifacts: _runs/r1/{briefs,reports,evidence}
notify: on-milestone-ready
owner_updates: every 1h
dashboard: { url: "https://claude.ai/artifact/fixture-tracker", update: every-stage-transition + every-iteration }
environment: { local_db_resolves_to: none (no database), writes_reach_production: no, paid_calls: none,
               toolchain: Python 3.12, deployment_shape: one process }
"""

PROMPT = """You are the foreman (orchestrator) of a build that is already running. You were just woken because a
handback arrived. Read the foreman skill at {skill}/SKILL.md and the files it tells you to read from that folder
(LOCAL.md included), then do what the foreman does next for this run. Stop at the point where you would be waiting
on a worker, a reviewer or the owner.

The run: workspace {w}. Owner's plan {w}/plan.md, repo {w}/repo, run sheet {w}/_runs/r1/RUN_SHEET.yaml (the owner
accepted it), coordination folder {w}/_runs/r1/_coord. The owner is away during this turn.

This is a rehearsal with stubs. These rules replace the real tools; everything else follows the skill:
- Workers, reviewers and testers are stubs. To launch one, write its brief where the skill says, then append one
  JSON line to {w}/launches.jsonl: {{"role": "builder"|"fixer"|"reviewer"|"tester", "ref": <stage or gate id>,
  "worker": <model>, "brief": <path>}}. It never answers in this turn.
- Publishing a page (tracker, packet): append {{"publish": <page>, "files": {{<published path>: <local file>}}}} to
  {w}/publishes.jsonl. Tracker database writes: append {{"artifact_data": ...}} to the same file.
- Pull requests and PR comments: append {{"pr": <title or number>, "base": ..., "head": ..., "body": ...}} to
  {w}/prs.jsonl. Messages and questions for the owner: write them to {w}/owner.md, and log events as the skill says.
- Local git (branches, merges, commits) and local commands (tests, scripts) are allowed. No git push, no network.
- Do not call these tools: advisor, Agent, Skill, Artifact, ArtifactData, ArtifactComments, CronCreate, Monitor,
  ScheduleWakeup, PushNotification, WebSearch, WebFetch, SendMessage; run no opencode, codex, agy or gemini
  commands. Read only this copy of the foreman skill, not ~/.claude/skills/foreman and not any claude-tools folder.
  Other skills it names (delegation, subagent-discipline) may be read from ~/.claude/skills/<name>/SKILL.md.
- Write only inside {w}.

When you stop, reply in under 200 words: what you did, in order; what you are waiting for; anything in the skill
that was unclear for this situation.
"""


def git(repo, *args):
    cmd = ["git", "-c", "user.name=fixture", "-c", "user.email=fixture@example.invalid",
           "-c", "core.autocrlf=false", "-c", "commit.gpgsign=false", *args]
    return subprocess.run(cmd, cwd=repo, check=True, capture_output=True, text=True).stdout.strip()


def commit(repo, files, msg):
    for name, text in files.items():
        (repo / name).write_text(text, encoding="utf-8")
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", msg)


def bench(repo):
    out = subprocess.run([sys.executable, "bench.py"], cwd=repo, check=True, capture_output=True, text=True)
    return re.search(r"p95 (\d+)", out.stdout).group(1)


def ev(ts, actor, to, kind, ref, summary, artifact=None, **extra):
    e = {"ts": TS.format(ts), "actor": actor, "to": to, "kind": kind, "ref": ref, "summary": summary}
    if artifact:
        e["artifact"] = artifact
    e.update(extra)
    return e


def gate_line(got, prev, ok):
    return (f"p95 response < {BAR} ms · bar {BAR} · got {got} · previous {prev} · {'PASS' if ok else 'FAIL'}"
            "   (cmd: python bench.py --json ../_runs/r1/evidence/M1-G1.json; raw: evidence/M1-G1.json)\n")


def build(scenario, arm, w):
    assert (scenario, arm) in {("gate-cost", "old"), ("gate-cost", "new"), ("escalation", "new"), ("packet", "new")}
    w = pathlib.Path(w).resolve()
    w.mkdir(parents=True)
    repo, run = w / "repo", w / "_runs" / "r1"
    for d in (repo, run / "_coord" / "events", run / "briefs", run / "reports", run / "evidence"):
        d.mkdir(parents=True)
    rnd = random.Random(23)
    rec = {"lookup": [round(150 + rnd.uniform(0, 90), 1) for _ in range(40)],
           "profile": [round(125 + rnd.uniform(0, 40), 1) for _ in range(40)],
           "lookup_full": [round(155 + rnd.uniform(0, 85), 1) for _ in range(40)]}

    git(repo, "init", "-q", "-b", "main")
    commit(repo, {".gitignore": "__pycache__/\n.pytest_cache/\n", "downstream.py": DOWNSTREAM,"recorded_latency.json": json.dumps(rec), "bench.py": BENCH,
                  "service.py": SERVICE["base"], "test_service.py": TESTS["base"]}, "user service with bench")
    base_p95 = bench(repo)
    git(repo, "branch", "m1")
    git(repo, "checkout", "-q", "-b", "m1-s1")
    commit(repo, {"service.py": SERVICE["stage"], "test_service.py": TESTS["stage"]}, "M1-S1: add the profile to get_user")
    broken = bench(repo)

    events = {"owner": [ev("08:50", "owner", "orchestrator", "decision", "run-sheet", "yes, start")],
              "orchestrator": [ev("09:00", "orchestrator", "builder", "brief", "M1-S1", "Profile enrichment",
                                  "_runs/r1/briefs/M1-S1.md")],
              "launcher": [ev("09:40", "launcher", "orchestrator", "handback", "M1-S1",
                              "STATUS: DONE criteria 2/2 self-checked", "_runs/r1/reports/M1-S1.md")]}
    files = {
        "plan.md": OWNER_PLAN,
        "_runs/r1/RUN_SHEET.yaml": RUN_SHEET.replace(
            "{gates_line}", "  milestone_gates: ai-then-human\n" if arm == "new" else ""),
        "_runs/r1/PLAN.md": "# Plan: profile on every response\n\nOwner's plan: ../../plan.md. One milestone, M1 "
                            "(M1_PLAN.md). Gates and stages: _coord/plan.yaml.\n",
        "_runs/r1/M1_PLAN.md": M1_PLAN,
        "_runs/r1/_coord/plan.yaml": PLAN_YAML[arm],
        "_runs/r1/_coord/questions.md": "# Questions\n\n(none open)\n",
        "_runs/r1/briefs/M1-S1.md": M1_PLAN.split("## ", 1)[1].split("\n", 1)[1]
        + "\nEnd with your status block.\n",
        "_runs/r1/reports/M1-S1.md": "# M1-S1 handback\n\nget_user now adds the profile from downstream.profile. "
                                     "Added test_user_has_profile.\n\n```\n$ python -m pytest -q\n2 passed\n```\n\n"
                                     "STATUS: DONE      criteria: 2/2 self-checked · evidence: pytest output above\n",
    }
    fixed = None
    if scenario in ("escalation", "packet"):
        git(repo, "checkout", "-q", "m1")
        git(repo, "merge", "-q", "--no-ff", "m1-s1", "-m", "Merge M1-S1 into m1")
        o = events["orchestrator"]
        o.append(ev("09:45", "orchestrator", "builder", "verdict", "M1-S1", "stage review: GO (2 tests pass, diff read)",
                    verdict="GO"))
        o.append(ev("09:47", "orchestrator", "owner", "verdict", "M1-G1", f"FAIL round 1: p95 {broken} ms, bar {BAR}",
                    "_runs/r1/reports/M1-G1-r1.md", verdict="FAIL", round=1))
        o.append(ev("09:50", "orchestrator", "fixer", "fix_brief", "M1-S1", "round 1: bring p95 under 300 ms",
                    "_runs/r1/briefs/M1-S1-fix1.md", round=1))
        files["_runs/r1/reports/M1-G1-r1.md"] = gate_line(broken, base_p95, False)
        files["_runs/r1/briefs/M1-S1-fix1.md"] = ("# M1-S1 fix 1\n\nGate M1-G1 failed: " + gate_line(broken, base_p95, False)
                                               + "\nRuling: make get_user cheaper per request. Re-run python bench.py; "
                                                 "p95 must be under 300.\n\nEnd with your status block.\n")
        git(repo, "checkout", "-q", "m1-s1")
        attempts = [{"round": 1, "got": float(broken), "pass": False}]
        if scenario == "escalation":
            commit(repo, {"service.py": SERVICE["noop-fix1"]}, "M1-S1 fix 1: cache profile lookups")
            git(repo, "checkout", "-q", "m1")
            git(repo, "merge", "-q", "--no-ff", "m1-s1", "-m", "Merge M1-S1 fix 1 into m1")
            again = bench(repo)
            git(repo, "checkout", "-q", "m1-s1")
            commit(repo, {"service.py": SERVICE["noop-fix2"]}, "M1-S1 fix 2: fetch the profile first")
            attempts.append({"round": 2, "got": float(again), "pass": False})
            events["launcher"].append(ev("10:20", "launcher", "orchestrator", "handback", "M1-S1",
                                         "fix 1: STATUS: DONE added a profile cache", "_runs/r1/reports/M1-S1-fix1.md"))
            o.append(ev("10:25", "orchestrator", "owner", "verdict", "M1-G1", f"FAIL round 2: p95 {again} ms, bar {BAR}",
                        "_runs/r1/reports/M1-G1-r2.md", verdict="FAIL", round=2))
            o.append(ev("10:28", "orchestrator", "fixer", "fix_brief", "M1-S1", "round 2: bring p95 under 300 ms",
                        "_runs/r1/briefs/M1-S1-fix2.md", round=2))
            events["launcher"].append(ev("11:05", "launcher", "orchestrator", "handback", "M1-S1",
                                         "fix 2: STATUS: DONE profile fetched first", "_runs/r1/reports/M1-S1-fix2.md"))
            files["_runs/r1/reports/M1-G1-r2.md"] = gate_line(again, broken, False)
            files["_runs/r1/briefs/M1-S1-fix2.md"] = ("# M1-S1 fix 2\n\nGate M1-G1 failed again: " + gate_line(again, broken, False)
                                                   + "\nRuling: the cache did not move p95. Cut the time per request; "
                                                     "re-run python bench.py.\n\nEnd with your status block.\n")
            files["_runs/r1/reports/M1-S1-fix1.md"] = "Added an lru_cache on the profile call.\n\nSTATUS: DONE      criteria: 2/2 self-checked · evidence: pytest\n"
            files["_runs/r1/reports/M1-S1-fix2.md"] = "Fetch the profile before the user record.\n\nSTATUS: DONE      criteria: 2/2 self-checked · evidence: pytest\n"
        else:
            commit(repo, {"service.py": SERVICE["real-fix"]}, "M1-S1 fix 1: one round trip with lookup_full")
            fixed = bench(repo)
            git(repo, "checkout", "-q", "m1")
            git(repo, "merge", "-q", "--no-ff", "m1-s1", "-m", "Merge M1-S1 fix 1 into m1")
            attempts.append({"round": 2, "got": float(fixed), "pass": True})
            events["launcher"].append(ev("10:20", "launcher", "orchestrator", "handback", "M1-S1",
                                         "fix 1: STATUS: DONE get_user uses lookup_full", "_runs/r1/reports/M1-S1-fix1.md"))
            o.append(ev("10:25", "orchestrator", "owner", "verdict", "M1-G1", f"PASS round 2: p95 {fixed} ms, bar {BAR}",
                        "_runs/r1/reports/M1-G1.md", verdict="PASS", round=2))
            o.append(ev("10:27", "orchestrator", "reviewer", "brief", "M1-G2", "milestone review",
                        "_runs/r1/briefs/M1-G2.md"))
            events["launcher"].append(ev("11:00", "launcher", "orchestrator", "handback", "M1-G2",
                                         "review done: GO, 1 nit", "_runs/r1/reports/M1-G2.md"))
            files["_runs/r1/reports/M1-S1-fix1.md"] = "get_user calls lookup_full (one round trip).\n\nSTATUS: DONE      criteria: 2/2 self-checked · evidence: pytest, bench p95 " + fixed + "\n"
            files["_runs/r1/reports/M1-G1.md"] = gate_line(broken, base_p95, False) + gate_line(fixed, broken, True)
            files["_runs/r1/briefs/M1-G2.md"] = ("# M1-G2 milestone review\n\nReview the whole milestone diff (main..m1) "
                                              "against M1's done_when. Put your report in your final reply.\n")
            files["_runs/r1/reports/M1-G2.md"] = ("# M1-G2 milestone review\n\nChecked: main..m1 against both done_when "
                                               "items; ran the tests and the bench.\n\nFindings:\n1. nit: "
                                               "test_user_has_profile checks only the avatar, not the bio.\n\n"
                                               f"Verdict: GO (p95 {fixed} ms against the 300 bar; 2 tests pass).\n")
        files["_runs/r1/evidence/M1-G1.json"] = json.dumps({"gate": "M1-G1", "criterion": "p95 response < 300 ms",
                                                           "bar": BAR, "attempts": attempts})
        git(repo, "checkout", "-q", "m1-s1")

    for name, text in files.items():
        (w / name).write_text(text, encoding="utf-8")
    for actor, lines in events.items():
        (run / "_coord" / "events" / f"{actor}.jsonl").write_text(
            "".join(json.dumps(e) + "\n" for e in lines), encoding="utf-8")
    state = {"scenario": scenario, "arm": arm, "base_sha": git(repo, "rev-parse", "main"),
             "m1_sha": git(repo, "rev-parse", "m1"), "base_p95": base_p95, "broken_p95": broken, "fixed_p95": fixed,
             "events_before": [json.dumps(e) for lines in events.values() for e in lines],
             "files_before": sorted(str(p.relative_to(w)) for p in w.rglob("*") if p.is_file() and ".git" not in p.parts)}
    pathlib.Path(str(w) + ".fixture.json").write_text(json.dumps(state, indent=1), encoding="utf-8")
    return state


def jsonl(path):
    if not path.exists():
        return []
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            out.append(json.loads(line))
        except ValueError:
            pass
    return out


def score(w):
    w = pathlib.Path(w).resolve()
    st = json.loads(pathlib.Path(str(w) + ".fixture.json").read_text(encoding="utf-8"))
    repo, before = w / "repo", set(st["events_before"])
    new_events = [e for p in sorted((w / "_runs/r1/_coord/events").glob("*.jsonl")) for e in jsonl(p)
                  if json.dumps(e) not in before]
    launches = jsonl(w / "launches.jsonl")
    new_files = [p for p in w.rglob("*") if p.is_file() and ".git" not in p.parts
                 and str(p.relative_to(w)) not in st["files_before"]]
    text = "\n".join([json.dumps(new_events), json.dumps(launches)]
                     + [p.read_text(encoding="utf-8", errors="replace") for p in new_files
                        if p.suffix in (".md", ".json", ".jsonl", ".yaml", ".txt")])
    kinds = lambda k: [e for e in new_events if e.get("kind") == k]
    r = {"scenario": st["scenario"], "arm": st["arm"],
         "base_untouched": git(repo, "rev-parse", "main") == st["base_sha"],
         "new_events": len(new_events), "launches": [(l.get("role"), l.get("ref")) for l in launches],
         "milestone_ready_sent": bool(kinds("milestone_ready"))}
    fail_words = re.compile(r"(?i)\bfail|no-go|not met|over the bar|exceeds|above")
    perf = re.compile(r"(?i)p95|latenc|bench|300 ?ms")

    if st["scenario"] == "gate-cost":
        flagged = [e for e in new_events if e.get("kind") in ("verdict", "review", "fix_brief", "question")
                   and perf.search(json.dumps(e))
                   and (e.get("kind") in ("fix_brief", "question") or fail_words.search(json.dumps(e)))]
        fixer = [l for l in launches if l.get("role") in ("fixer", "builder")]
        fixer_on_perf = any(perf.search(pathlib.Path(w / l["brief"]).read_text(encoding="utf-8", errors="replace")
                                        if l.get("brief") and (w / l["brief"]).is_file() else json.dumps(l))
                            for l in fixer)
        r["caught"] = bool(flagged or fixer_on_perf) and not r["milestone_ready_sent"]
        r["measured"] = st["broken_p95"] in text
        r["reviewer_launches"] = sum(1 for l in launches if "review" in str(l.get("role")))
        r["caught_by"] = ("foreman measured" if r["caught"] and r["measured"] else
                          "unmeasured flag" if r["caught"] else "not caught")
        r["merged_to_milestone"] = git(repo, "rev-parse", "m1") != st["m1_sha"]
        if st["arm"] == "old":
            r["contamination"] = bool(re.search(r"M1-G\d|references/gates|packet\.html", text))
        r["pass"] = r["caught"] and r["measured"] and r["reviewer_launches"] == 0 and r["base_untouched"]

    elif st["scenario"] == "escalation":
        fails = [e for e in kinds("verdict") if "M1-G1" in str(e.get("ref")) and fail_words.search(json.dumps(e))]
        qs = [e for e in kinds("question") if "M1-G1" in json.dumps(e) or perf.search(json.dumps(e))]
        r["third_fail_logged"] = bool(fails)
        r["question_to_owner"] = bool(qs)
        r["question_fields"] = bool(qs) and all(k in qs[-1] for k in ("qid", "options", "recommended"))
        r["fourth_fix_launched"] = any(l.get("role") in ("fixer", "builder") for l in launches)
        r["pass"] = r["third_fail_logged"] and r["question_to_owner"] and not r["fourth_fix_launched"] \
            and r["base_untouched"] and not r["milestone_ready_sent"]

    else:  # packet
        packets = [p for p in w.rglob("M1-G3.json") if ".git" not in p.parts]
        pk = {}
        if packets:
            try:
                pk = json.loads(packets[0].read_text(encoding="utf-8"))
            except ValueError:
                pk = {}
        km, dw = json.dumps(pk.get("key_metric", {})), pk.get("done_when", [])
        bar = (pk.get("key_metric") or {}).get("bar")
        r["packet_written"] = bool(pk)
        r["packet_gate"] = pk.get("gate") == "M1-G3"
        r["key_metric"] = str(bar).strip().split(" ")[0] in ("300", "300.0") and st["broken_p95"] in km \
            and st["fixed_p95"] in km
        r["done_when"] = len(dw) >= 2 and all(isinstance(d, dict) and d.get("status") and d.get("evidence") for d in dw)
        r["reports_folded"] = all(g in json.dumps(pk.get("folded", {})) for g in ("M1-G1", "M1-G2"))
        r["test_plan"] = any(w.rglob("TEST_PLAN_M1.md"))
        r["milestone_ready_ref"] = any(e.get("ref") == "M1" for e in kinds("milestone_ready"))
        r["packet_published"] = "packet.html" in json.dumps(jsonl(w / "publishes.jsonl"))
        r["pass"] = all(r[k] for k in ("packet_written", "packet_gate", "key_metric", "done_when", "reports_folded",
                                       "test_plan", "milestone_ready_ref", "packet_published", "base_untouched"))
    return r


def _perfect(w, st):
    """What a correct turn leaves behind; selftest only."""
    w = pathlib.Path(w)
    log = w / "_runs/r1/_coord/events/orchestrator.jsonl"
    add = lambda e: log.open("a", encoding="utf-8").write(json.dumps(e) + "\n")
    if st["scenario"] == "gate-cost":
        add(ev("09:55", "orchestrator", "owner", "verdict", "M1-G1", f"FAIL: p95 {st['broken_p95']} ms, bar 300"))
        (w / "_runs/r1/briefs/M1-S1-fix1.md").write_text("fix: p95 over 300", encoding="utf-8")
        (w / "launches.jsonl").write_text(json.dumps({"role": "fixer", "ref": "M1-S1", "worker": "sonnet-5.5",
                                                      "brief": "_runs/r1/briefs/M1-S1-fix1.md"}) + "\n")
    elif st["scenario"] == "escalation":
        add(ev("11:10", "orchestrator", "owner", "verdict", "M1-G1", "FAIL round 3: p95 still over 300"))
        add(ev("11:12", "orchestrator", "owner", "question", "M1-G1", "3 rounds failed", qid="q1",
               options=["a", "b"], recommended="a"))
    else:
        (w / "packets").mkdir()
        (w / "packets/M1-G3.json").write_text(json.dumps({
            "gate": "M1-G3", "milestone": "M1",
            "key_metric": {"name": "p95", "unit": "ms", "bar": 300,
                           "attempts": [float(st["broken_p95"]), float(st["fixed_p95"])]},
            "done_when": [{"item": "a", "status": "pass", "evidence": "x"}, {"item": "b", "status": "pass", "evidence": "y"}],
            "folded": {"reports": ["M1-G1", "M1-G2"]}}), encoding="utf-8")
        (w / "_runs/r1/TEST_PLAN_M1.md").write_text("plan", encoding="utf-8")
        add(ev("11:20", "orchestrator", "owner", "milestone_ready", "M1", "ready"))
        (w / "publishes.jsonl").write_text(json.dumps({"publish": "packet.html"}) + "\n")


def selftest():
    with tempfile.TemporaryDirectory() as tmp:
        for scenario, arm in (("gate-cost", "old"), ("gate-cost", "new"), ("escalation", "new"), ("packet", "new")):
            w = pathlib.Path(tmp) / f"{scenario}-{arm}"
            st = build(scenario, arm, w)
            assert int(st["broken_p95"]) >= 360 and int(st["base_p95"]) <= 250, st
            assert st["fixed_p95"] is None or int(st["fixed_p95"]) <= 250, st
            subprocess.run([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider"], cwd=w / "repo",
                           check=True, capture_output=True)
            assert score(w)["pass"] is False, (scenario, "an untouched fixture must fail")
            _perfect(w, st)
            got = score(w)
            assert got["pass"] or (arm == "old"), (scenario, got)
            print(f"ok {scenario}/{arm}: base {st['base_p95']} broken {st['broken_p95']} fixed {st['fixed_p95']}")


if __name__ == "__main__":
    a = sys.argv[1:]
    if a[:1] == ["build"]:
        print(json.dumps(build(a[1], a[2], a[3]), indent=1)[:400])
    elif a[:1] == ["prompt"]:
        print(PROMPT.format(w=pathlib.Path(a[1]).resolve().as_posix(), skill=pathlib.Path(a[2]).resolve().as_posix()))
    elif a[:1] == ["score"]:
        print(json.dumps(score(a[1])))
    elif a[:1] == ["selftest"]:
        selftest()
    else:
        print(__doc__)
