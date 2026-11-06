#!/usr/bin/env python3
"""Install or remove Foreman's SessionStart reminder hook.

    install_hook.py install   claude|codex     add the hook to ~/.claude/settings.json or ~/.codex/hooks.json
    install_hook.py uninstall claude|codex     remove only Foreman's entry
    install_hook.py selftest                   temp files only; prints "selftest: OK"

The existing file is merged, never replaced: other hooks stay. A backup `<file>.bak-<YYYYmmdd-HHMMSS>` is written
first. Invalid JSON: nothing is changed and the command stops with the reason. Installing twice leaves one entry.
Stdlib only.
"""
import datetime
import json
import os
import re
import shutil
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPT = os.path.join(HERE, "session_context.py")
MATCHER = "startup|resume|compact"
MARK = "session_context.py"


def default_path(harness):
    if harness == "claude":
        return os.path.join(os.path.expanduser("~"), ".claude", "settings.json")
    if harness == "codex":
        return os.path.join(os.path.expanduser("~"), ".codex", "hooks.json")
    raise SystemExit(f"unknown harness {harness!r}: use claude or codex")


def _load(path):
    """(data, existed). Invalid JSON or a non-object file stops the run with the file untouched."""
    if not os.path.exists(path):
        return {}, False
    try:
        with open(path, encoding="utf-8") as f:
            text = f.read()
        data = json.loads(text) if text.strip() else {}
    except Exception as e:
        raise SystemExit(f"{path} is not valid JSON ({e}); not touching it. Fix or move it, then run this again.")
    if not isinstance(data, dict):
        raise SystemExit(f"{path} is not a JSON object; not touching it.")
    return data, True


def _entries(data, create=False):
    hooks = data.get("hooks")
    if not isinstance(hooks, dict):
        if not create:
            return None
        hooks = data["hooks"] = {}
    ss = hooks.get("SessionStart")
    if not isinstance(ss, list):
        if not create:
            return None
        ss = hooks["SessionStart"] = []
    return ss


def _is_foreman(cmd):
    # Foreman's own script: <a folder named foreman...>/hooks/session_context.py. Another tool's session_context.py
    # (any other path) is left alone.
    return re.search(r"foreman[^\\/\"']*[\\/]+hooks[\\/]+" + re.escape(MARK), cmd, re.I) is not None or SCRIPT in cmd


def _mine(h):
    return isinstance(h, dict) and _is_foreman(str(h.get("command", "")))


def _ours(entry):
    return isinstance(entry, dict) and any(_mine(h) for h in (entry.get("hooks") or []))


def _command(harness):
    return f'"{sys.executable}" "{SCRIPT}" {harness}'


def _write(path, data):
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
        f.write("\n")
    os.replace(tmp, path)


def _backup(path):
    b = f"{path}.bak-{datetime.datetime.now().strftime('%Y%m%d-%H%M%S')}"
    n = 1
    while os.path.exists(b):
        n += 1
        b = f"{path}.bak-{datetime.datetime.now().strftime('%Y%m%d-%H%M%S')}-{n}"
    shutil.copy2(path, b)
    return b


def install(harness, settings=None):
    """Add our SessionStart entry. Returns the backup path (None when the file did not exist)."""
    path = settings or default_path(harness)
    data, existed = _load(path)
    backup = _backup(path) if existed else None
    cmd = _command(harness)
    ss = _entries(data, create=True)
    # Take our command out of any entry (another tool's hooks and matcher in a shared entry stay as they were),
    # then add one entry of our own.
    for entry in list(ss):
        if _ours(entry):
            entry["hooks"] = [h for h in entry["hooks"] if not _mine(h)]
            if not entry["hooks"]:
                ss.remove(entry)
    ss.append({"matcher": MATCHER, "hooks": [{"type": "command", "command": cmd}]})
    _write(path, data)
    return backup


def uninstall(harness, settings=None):
    """Remove only our entry (and our command inside a shared entry). Returns True when something was removed."""
    path = settings or default_path(harness)
    data, existed = _load(path)
    ss = _entries(data) if existed else None
    if not ss:
        return False
    keep, removed = [], False
    for entry in ss:
        if _ours(entry):
            rest = [h for h in entry["hooks"] if not _mine(h)]
            removed = True
            if rest:
                entry["hooks"] = rest
                keep.append(entry)
        else:
            keep.append(entry)
    if not removed:
        return False
    _backup(path)
    data["hooks"]["SessionStart"] = keep
    if not keep:
        del data["hooks"]["SessionStart"]
        if not data["hooks"]:
            del data["hooks"]
    _write(path, data)
    return True


CODEX_TRUST = ("Codex does not run a new hook until you trust it: start `codex` once interactively, approve the new "
               "SessionStart hook when it asks, and until then the reminder silently does not run.")


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if argv[:1] == ["selftest"]:
        return selftest()
    if len(argv) != 2 or argv[0] not in ("install", "uninstall") or argv[1] not in ("claude", "codex"):
        print(__doc__)
        return 2
    cmd, harness = argv
    path = default_path(harness)
    if cmd == "install":
        b = install(harness)
        print(f"installed in {path}" + (f" (backup: {b})" if b else " (new file)"))
        if harness == "codex":
            print(CODEX_TRUST)
    else:
        print(("removed from " if uninstall(harness) else "nothing of ours in ") + path)
    return 0


def selftest():
    tmp = tempfile.mkdtemp()
    f = os.path.join(tmp, "my dir", "settings.json")  # a space on purpose
    os.makedirs(os.path.dirname(f))
    assert not _is_foreman("python /other-plugin/hooks/session_context.py") and not _is_foreman("python x/session_context.py")
    assert _is_foreman('"py" "C:\\Users\\u\\.claude\\skills\\foreman\\hooks\\session_context.py" claude')
    assert _is_foreman("python /home/u/foreman-v2.4/hooks/session_context.py codex")
    other = {"matcher": "startup", "hooks": [{"type": "command", "command": "echo hi"}]}
    pre = {"theme": "dark", "hooks": {"SessionStart": [other], "Stop": [{"hooks": [{"type": "command", "command": "x"}]}]}}
    with open(f, "w", encoding="utf-8") as fh:
        json.dump(pre, fh)
    b = install("claude", f)
    assert b and os.path.exists(b), b
    d = json.load(open(f, encoding="utf-8"))
    ss = d["hooks"]["SessionStart"]
    assert other in ss and len(ss) == 2 and d["theme"] == "dark" and "Stop" in d["hooks"], d
    ours = [e for e in ss if _ours(e)]
    assert len(ours) == 1 and ours[0]["matcher"] == MATCHER, ours
    c = ours[0]["hooks"][0]["command"]
    assert c.startswith('"') and SCRIPT in c and c.endswith(" claude"), c
    install("claude", f)
    d = json.load(open(f, encoding="utf-8"))
    assert len([e for e in d["hooks"]["SessionStart"] if _ours(e)]) == 1 and len(d["hooks"]["SessionStart"]) == 2
    assert uninstall("claude", f) is True
    d = json.load(open(f, encoding="utf-8"))
    assert d["hooks"]["SessionStart"] == [other] and "Stop" in d["hooks"], d
    assert uninstall("claude", f) is False
    # a shared entry holding our hook and another tool's session_context.py: theirs and their matcher stay
    theirs = {"type": "command", "command": "python /other-plugin/hooks/session_context.py"}
    shared = {"matcher": "startup", "hooks": [{"type": "command", "command": "python /x/foreman/hooks/session_context.py claude"}, theirs]}
    with open(f, "w", encoding="utf-8") as fh:
        json.dump({"hooks": {"SessionStart": [shared]}}, fh)
    install("claude", f)
    ss = json.load(open(f, encoding="utf-8"))["hooks"]["SessionStart"]
    assert ss[0] == {"matcher": "startup", "hooks": [theirs]} and len(ss) == 2 and ss[1]["matcher"] == MATCHER, ss
    assert uninstall("claude", f) is True
    assert json.load(open(f, encoding="utf-8"))["hooks"]["SessionStart"] == [{"matcher": "startup", "hooks": [theirs]}]
    # a new file: no backup
    g = os.path.join(tmp, "new", "hooks.json")
    assert install("codex", g) is None and _ours(json.load(open(g))["hooks"]["SessionStart"][0])
    assert uninstall("codex", g) is True and json.load(open(g)) == {}
    # invalid JSON: refuse, file byte-identical, no backup written
    bad = os.path.join(tmp, "bad.json")
    raw = b'{"hooks": {oops'
    with open(bad, "wb") as fh:
        fh.write(raw)
    for fn in (install, uninstall):
        try:
            fn("claude", bad)
            raise AssertionError("should refuse")
        except SystemExit as e:
            assert "not valid JSON" in str(e), e
    assert open(bad, "rb").read() == raw
    assert [x for x in os.listdir(tmp) if x.startswith("bad.json.bak")] == []
    print("selftest: OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
