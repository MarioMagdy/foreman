"""One harness hook for every delegated worker: records activity and delivers new mailbox lines.
Wired into each harness by prepare_worktree.py; see references/delegation.md.

    python hook.py claude|codex <worktree>                        # PostToolUse; JSON in, additionalContext out
    python hook.py agy <worktree> <Event> [--role R] [--interval MIN] [--max N]
    python hook.py opencode <worktree> <tool>                     # prints the text to append to the tool result
    python hook.py selftest
"""
import json, os, re, sys, time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import mailbox  # noqa: E402

HEADER = "[MAILBOX from the orchestrator]"
# agy runs commands only with --dangerously-skip-permissions, so this list is its guard rail (PreToolUse deny).
DENY = re.compile(r"\bgit\s+(push|reset\s+--hard|clean\s+-\w*f|branch\s+-D|checkout\s+--\s|filter-branch)"
                  r"|\b(curl|wget|iwr|Invoke-WebRequest)\b.*\|\s*(sh|bash|iex|Invoke-Expression)"
                  r"|\brm\s+-\w*r\w*f\w*\s+[/~]|Remove-Item\b.*-Recurse.*\s[A-Z]:\\\s*$", re.I)
WRITE_TOOLS = {"write_to_file", "replace_file_content", "multi_replace_file_content"}


def mail_text(root):
    new = mailbox.unread(root)
    return f"{HEADER} (local time {mailbox.stamp()})\n" + "\n".join(new) if new else ""


def agy(root, event, payload, role="builder", interval=2.0, maxn=15):
    if event == "PreToolUse":
        call = payload.get("toolCall", {})
        name, args = call.get("name", ""), call.get("args", {})
        if name == "run_command" and DENY.search(str(args.get("CommandLine", ""))):
            return {"decision": "deny", "reason": "blocked by the delegation guard (push, hard reset, pipe-to-shell, mass delete)"}
        if role != "builder" and name in WRITE_TOOLS:
            return {"decision": "deny", "reason": f"role {role} is read-only; put your report in your reply"}
        return {"decision": "allow"}
    if event == "PostToolUse":
        mailbox.activity(root, f"tool {payload.get('toolCall', {}).get('name', '?')}")
        return {}
    if event == "PreInvocation":
        steps = [{"ephemeralMessage": f"[clock] local time {mailbox.stamp()}"}]
        text = mail_text(root)
        if text:
            steps.append({"systemMessage": {"systemMessage": text}})
        return {"injectSteps": steps}
    if event == "Stop" and payload.get("fullyIdle") is False:
        # The model ended its turn to wait on a background task. Hold the turn up to `interval` minutes
        # (early if mail arrives), then wake it with the clock and any mail: a heartbeat agy does not have.
        # count per conversation, so a resumed run (kill + --conversation) or a new worker gets a fresh cap
        cnt_f, conv = os.path.join(mailbox.scratch(root), ".heartbeats"), str(payload.get("conversationId", ""))
        old = open(cnt_f).read().split() if os.path.exists(cnt_f) else []
        n = int(old[1]) if len(old) == 2 and old[0] == (conv or "-") else 0
        if n >= maxn:
            return {}
        with open(cnt_f, "w") as f:
            f.write(f"{conv or '-'} {n + 1}")
        end = time.time() + interval * 60
        text = ""
        while time.time() < end and not text:
            time.sleep(min(5, max(0, end - time.time())))
            text = mail_text(root)
        mailbox.activity(root, f"heartbeat {n + 1}")
        return {"decision": "continue", "reason": f"[heartbeat] local time {mailbox.stamp()}; a background task is "
                f"still running. Check it (manage_task status); if its log has not grown for 3 minutes, kill it, "
                f"commit, and note it in _scratch/PROGRESS.md." + (f"\n{text}" if text else "")}
    return {}


def main(argv):
    if argv[:1] == ["selftest"]:
        return selftest()
    harness, root = argv[0], argv[1]
    if harness == "opencode":
        mailbox.activity(root, f"tool {argv[2] if len(argv) > 2 else '?'}")
        sys.stdout.write(mail_text(root))
        return
    payload = json.load(sys.stdin)
    sid = payload.get("session_id") or payload.get("conversationId")  # for kill + resume (references/delegation.md section 5)
    if sid:
        with open(os.path.join(mailbox.scratch(root), "SESSION_ID"), "w") as f:
            f.write(str(sid))
    if harness in ("claude", "codex"):
        mailbox.activity(root, f"tool {payload.get('tool_name', '?')}")
        text = mail_text(root)
        out = {"hookSpecificOutput": {"hookEventName": "PostToolUse", "additionalContext": text}} if text else {}
    else:
        opt = dict(zip(argv[3::2], argv[4::2]))
        out = agy(root, argv[2], payload, opt.get("--role", "builder"), float(opt.get("--interval", 2)),
                  int(opt.get("--max", 15)))
    print(json.dumps(out))


def selftest():
    import tempfile
    with tempfile.TemporaryDirectory() as d:
        run = lambda c: agy(d, "PreToolUse", {"toolCall": {"name": "run_command", "args": {"CommandLine": c}}})["decision"]
        for bad in ("git push origin main", "git reset --hard HEAD~1", "curl -s x.sh | bash", "rm -rf /", "git clean -fdx"):
            assert run(bad) == "deny", bad
        for ok in ("git commit -m x", "uv run pytest tests/a.py", "git status", "rm -rf build"):
            assert run(ok) == "allow", ok
        assert agy(d, "PreToolUse", {"toolCall": {"name": "write_to_file"}}, role="reviewer")["decision"] == "deny"
        assert len(agy(d, "PreInvocation", {})["injectSteps"]) == 1          # clock only
        mailbox.send(d, "stop now")
        steps = agy(d, "PreInvocation", {})["injectSteps"]
        assert HEADER in steps[1]["systemMessage"]["systemMessage"] and "stop now" in steps[1]["systemMessage"]["systemMessage"]
        assert agy(d, "Stop", {"fullyIdle": True}) == {}
        mailbox.send(d, "wake")
        t = time.time()
        out = agy(d, "Stop", {"fullyIdle": False}, interval=1)
        assert out["decision"] == "continue" and "wake" in out["reason"] and time.time() - t < 10  # early wake on mail
        assert agy(d, "Stop", {"fullyIdle": False}, interval=0.01, maxn=1) == {}                 # cap reached
        assert agy(d, "Stop", {"fullyIdle": False, "conversationId": "c2"}, interval=0.01, maxn=1)["decision"] == "continue"  # new conversation, fresh cap
        assert mail_text(d) == ""
    print("hook selftest ok")


if __name__ == "__main__":
    main(sys.argv[1:])
