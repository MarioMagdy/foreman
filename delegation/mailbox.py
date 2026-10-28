"""Mailbox and progress files for one delegated job. Stdlib only.

Files live in <worktree>/_scratch/ (git-excluded by prepare_worktree.py):
  MAILBOX.md     we write, the worker's harness hook delivers new lines (cursor in .mailbox.seen = lines delivered)
  PROGRESS.md    the worker appends "- <local time> <step>" lines as it works (model-written)
  ACTIVITY.log   the harness hook appends one line per tool call (model-independent heartbeat)
  HANDOFF.md     the worker writes it on a soft stop or at the end

    python mailbox.py send <worktree> "text"          # orchestrator: queue a message
    python mailbox.py stop <worktree> [--why "..."]  # orchestrator: the soft stop message
    python mailbox.py note <worktree> "step text"     # worker: one timestamped progress line
    python mailbox.py progress <worktree> [-n 15]    # orchestrator: last progress lines + idle minutes
    python mailbox.py hang <worktree> --minutes N     # exit 1 when nothing grew for N minutes
    python mailbox.py selftest
"""
import argparse, datetime, os, sys, tempfile, time

SOFT_STOP = ("SOFT STOP: finish the step you are on (do not start a new one), commit it, write _scratch/HANDOFF.md "
             "(what is done, what is left, how to continue, test status), then end with your STATUS block.")


def stamp():
    return datetime.datetime.now().astimezone().isoformat(timespec="seconds")


def scratch(root):
    d = root if os.path.basename(os.path.normpath(root)) == "_scratch" else os.path.join(root, "_scratch")
    os.makedirs(d, exist_ok=True)
    return d


def _append(path, text):
    with open(path, "a", encoding="utf-8") as f:
        f.write(text if text.endswith("\n") else text + "\n")


def send(root, text):
    _append(os.path.join(scratch(root), "MAILBOX.md"), f"[{stamp()}] {text}")


def note(root, text):
    _append(os.path.join(scratch(root), "PROGRESS.md"), f"- {stamp()} {text}")


def activity(root, what):
    _append(os.path.join(scratch(root), "ACTIVITY.log"), f"{stamp()} {what}")


def unread(root):
    """New mailbox lines since the last call; advances the cursor. Used by every harness hook."""
    s = scratch(root)
    try:
        with open(os.path.join(s, "MAILBOX.md"), encoding="utf-8") as f:
            lines = [l.rstrip("\n") for l in f if l.strip()]
    except OSError:
        return []
    cur_f = os.path.join(s, ".mailbox.seen")
    try:
        seen = int(open(cur_f).read().strip() or 0)
    except (OSError, ValueError):
        seen = 0
    if len(lines) <= seen:
        return []
    with open(cur_f, "w") as f:
        f.write(str(len(lines)))
    return lines[seen:]


def idle_minutes(root):
    """Minutes since PROGRESS.md or ACTIVITY.log last grew (None if neither exists yet)."""
    s = scratch(root)
    times = [os.path.getmtime(os.path.join(s, n)) for n in ("PROGRESS.md", "ACTIVITY.log")
             if os.path.exists(os.path.join(s, n))]
    return round((time.time() - max(times)) / 60, 1) if times else None


def tail(path, n):
    try:
        with open(path, encoding="utf-8") as f:
            return f.read().splitlines()[-n:]
    except OSError:
        return []


def selftest():
    with tempfile.TemporaryDirectory() as d:
        assert unread(d) == [] and idle_minutes(d) is None
        send(d, "one"); send(d, "two")
        got = unread(d)
        assert len(got) == 2 and got[0].endswith("one"), got
        assert unread(d) == []                       # cursor advanced
        send(d, "three")
        assert [l.endswith("three") for l in unread(d)] == [True]
        note(d, "step 1 done"); activity(d, "tool bash")
        assert idle_minutes(d) == 0.0
        old = time.time() - 600
        for n in ("PROGRESS.md", "ACTIVITY.log"):
            os.utime(os.path.join(d, "_scratch", n), (old, old))
        assert idle_minutes(d) >= 9.9
        assert scratch(os.path.join(d, "_scratch")) == os.path.join(d, "_scratch")  # accepts the scratch dir too
    print("mailbox selftest ok")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("send", "note"):
        s = sub.add_parser(name); s.add_argument("root"); s.add_argument("text")
    s = sub.add_parser("stop"); s.add_argument("root"); s.add_argument("--why", default="")
    s = sub.add_parser("progress"); s.add_argument("root"); s.add_argument("-n", type=int, default=15)
    s = sub.add_parser("hang"); s.add_argument("root"); s.add_argument("--minutes", type=float, required=True)
    sub.add_parser("selftest")
    a = ap.parse_args()
    if a.cmd == "selftest":
        return selftest()
    if a.cmd == "send":
        return send(a.root, a.text)
    if a.cmd == "note":
        return note(a.root, a.text)
    if a.cmd == "stop":
        return send(a.root, SOFT_STOP + (f" Reason: {a.why}" if a.why else ""))
    s = scratch(a.root)
    idle = idle_minutes(a.root)
    if a.cmd == "progress":
        for l in tail(os.path.join(s, "PROGRESS.md"), a.n):
            print(l)
        last = tail(os.path.join(s, "ACTIVITY.log"), 1)
        print(f"-- last tool call: {last[0] if last else 'none'} | idle {idle} min | "
              f"handoff: {'yes' if os.path.exists(os.path.join(s, 'HANDOFF.md')) else 'no'}")
        return
    if a.cmd == "hang":
        hung = idle is not None and idle >= a.minutes
        print(f"{'HUNG' if hung else 'ok'}: idle {idle} min (limit {a.minutes})")
        sys.exit(1 if hung else 0)


if __name__ == "__main__":
    main()
