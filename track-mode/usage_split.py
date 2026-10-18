"""Which Claude Code sessions used the weekly limit in a time window, and how much of it.

    python usage_split.py --since 2026-10-10T23:40:00Z [--until <iso Z>] [--usage-log <_coord/usage-log.jsonl>]

Scans every transcript under ~/.claude/projects (sessions and their subagents), dedupes usage by message id,
and weights tokens by public API price ratios. Anthropic does not publish the subscription meter, so the
weights are relative. With --usage-log, the weekly-percent rise over the window is split in proportion to
those weights. Not counted: claude.ai web or desktop chats, other machines, Codex and opencode.
"""
import argparse, datetime, glob, json, os
from collections import defaultdict

# (input, output) per M tokens; cache read = 0.1x input, cache write = 1.25x (5 min) or 2x (1 h) input
PRICE = {"opus": (5, 25), "sonnet": (3, 15), "haiku": (1, 5), "fable": (5, 25)}


def weight(model, u):
    i, o = next((v for k, v in PRICE.items() if k in (model or "")), PRICE["sonnet"])
    cc = u.get("cache_creation") or {}
    w1h = cc.get("ephemeral_1h_input_tokens", 0)
    w5m = u.get("cache_creation_input_tokens", 0) - w1h
    return (u.get("input_tokens", 0) * i + w5m * i * 1.25 + w1h * i * 2
            + u.get("cache_read_input_tokens", 0) * i * 0.1 + u.get("output_tokens", 0) * o) / 1e6


def scan(since, until):
    root = os.path.expanduser("~/.claude/projects")
    since_epoch = datetime.datetime.fromisoformat(since.replace("Z", "+00:00")).timestamp()
    seen = {}
    for f in glob.glob(os.path.join(root, "*", "*.jsonl")) + glob.glob(os.path.join(root, "*", "*", "subagents", "*.jsonl")):
        parts = os.path.relpath(f, root).split(os.sep)
        project, session = parts[0], (parts[1] if len(parts) > 2 else parts[1][:-6])
        who = "main" if len(parts) == 2 else agent_name(f)
        if os.path.getmtime(f) < since_epoch:  # untouched since the window opened
            continue
        with open(f, encoding="utf-8", errors="replace") as h:
            for line in h:
                if '"usage"' not in line:
                    continue
                try:
                    r = json.loads(line)
                except ValueError:
                    continue
                m, ts = r.get("message") or {}, r.get("timestamp", "")
                if not m.get("usage") or not (since <= ts < until) or (who == "main" and r.get("isSidechain")):
                    continue
                seen[m.get("id") or r.get("uuid")] = (project, session, who, m.get("model"), m["usage"])
    return seen


def agent_name(f):
    try:
        d = json.load(open(f[:-6] + ".meta.json", encoding="utf-8"))
        return d.get("name") or d.get("description") or "subagent"
    except (OSError, ValueError):
        return "subagent"


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--since", required=True)
    ap.add_argument("--until", default="9999")
    ap.add_argument("--usage-log")
    ap.add_argument("--top", type=int, default=25)
    a = ap.parse_args()
    rows = defaultdict(lambda: [0.0, 0, None])
    for project, session, who, model, u in scan(a.since, a.until).values():
        r = rows[(project, session[:8], who)]
        r[0] += weight(model, u); r[1] += 1; r[2] = model
    total = sum(r[0] for r in rows.values()) or 1
    rise = None
    if a.usage_log:
        pts = [json.loads(l) for l in open(a.usage_log, encoding="utf-8") if l.strip()]
        pts = [p for p in pts if a.since <= p["ts"] < a.until]
        if len(pts) > 1:
            rise = pts[-1]["seven_day"] - pts[0]["seven_day"]
            print(f"weekly limit {pts[0]['seven_day']}% -> {pts[-1]['seven_day']}% ({rise} points, whole percents)")
    print(f"{'project':48} {'session':8} {'who':30} {'model':18} {'calls':>6} {'weight':>7} {'share':>6}" + ("  points" if rise else ""))
    for (p, s, w), (c, n, m) in sorted(rows.items(), key=lambda kv: -kv[1][0])[:a.top]:
        print(f"{p[-48:]:48} {s:8} {str(w)[:30]:30} {str(m)[:18]:18} {n:6} {c:7.1f} {c / total:6.1%}" + (f"  {rise * c / total:5.1f}" if rise else ""))
    print(f"total weight {total:.1f} across {len(rows)} session/agent rows")


if __name__ == "__main__":
    main()
