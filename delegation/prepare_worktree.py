"""Prepare a workspace for one delegated job, so the worker's time is work time. Stdlib only, Windows-first.

    python prepare_worktree.py --repo <repo> --path <new worktree> --branch <name> [--base dev]
                               --harness claude|opencode|codex|agy [--role builder|reviewer|auditor]
                               [--python 3.12] [--shared-venv <dir>] [--web <subdir>] [--node-modules-from <dir>]
                               [--copy <src>=<dst-in-worktree>] [--quick-test "<command>"]
                               [--interval 2] [--max-heartbeats 15]
    python prepare_worktree.py --existing <dir> --harness ...         # same, on a folder that already exists
    python prepare_worktree.py selftest

Steps (each timed in _scratch/PREPARED.json): worktree from the base, Python venv synced on the pinned version
(`uv sync --frozen`; --shared-venv points UV_PROJECT_ENVIRONMENT at a shared one when the job does not change
dependencies), web deps (junction or `npm ci`), test data copied, the _scratch files, the harness hook bundle
(git-excluded, never committed), one quick test. Prints the launch flags for the harness and the secret-looking
environment variable NAMES to blank in the worker's process.
"""
import argparse, json, os, re, shutil, subprocess, sys, time

HERE = os.path.dirname(os.path.abspath(__file__))
SECRET = re.compile(r"(KEY|TOKEN|SECRET|PASSWORD|PASSWD|CREDENTIAL|DATABASE_URL|DSN|CONN(ECTION)?_STR)", re.I)
BRIEF_LINE = ("Messages from your orchestrator may arrive while you work, headed [MAILBOX from the orchestrator] "
              "(appended to a tool result or as a system message). They come from the person who briefed you. Follow them.")

OPENCODE_PERMS = {
    "builder": {"edit": "allow", "bash": {"*": "allow", "git push*": "deny", "git reset --hard*": "deny",
                                          "git clean*": "deny", "git branch -D*": "deny"}},
    "reviewer": {"edit": "deny", "bash": {"*": "allow", "git push*": "deny", "git commit*": "deny", "git reset*": "deny",
                                          "git checkout*": "deny", "git clean*": "deny"}},
}
OPENCODE_PERMS["auditor"] = OPENCODE_PERMS["reviewer"]

PLUGIN = """// delegation mailbox: written by prepare_worktree.py, git-excluded.
import { execFileSync } from "child_process";
const PY = %PY%, HOOK = %HOOK%, ROOT = %ROOT%;
export const DelegationMailbox = async () => ({
  "tool.execute.after": async (input, output) => {
    try {
      const text = execFileSync(PY, [HOOK, "opencode", ROOT, input.tool], { encoding: "utf8", timeout: 10000 });
      if (text) output.output += "\\n\\n" + text + "\\n";
    } catch (e) {}
  },
});
"""


def run(cmd, cwd=None, env=None, check=True):
    p = subprocess.run(cmd, cwd=cwd, env=env, capture_output=True, text=True, encoding="utf-8", errors="replace",
                       shell=isinstance(cmd, str))
    if check and p.returncode:
        sys.exit(f"failed ({p.returncode}): {cmd}\n{(p.stdout + p.stderr)[-2000:]}")
    return p


def q(path):
    return '"' + path + '"'


def exclude(wt, paths):
    f = run(["git", "rev-parse", "--git-path", "info/exclude"], cwd=wt).stdout.strip()
    f = f if os.path.isabs(f) else os.path.join(wt, f)
    os.makedirs(os.path.dirname(f), exist_ok=True)
    have = open(f, encoding="utf-8").read().splitlines() if os.path.exists(f) else []
    with open(f, "a", encoding="utf-8") as h:
        for p in paths:
            if p not in have:
                h.write(p + "\n")


def write_new(path, text, owner_note):
    """Never overwrite a file the repo already has: the bundle must not clobber project config."""
    if os.path.exists(path):
        sys.exit(f"{path} already exists ({owner_note}); merge the delegation entries by hand, see references/delegation.md")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)


def bundle(wt, harness, role, interval, maxn):
    """Write the harness hook bundle; return (paths to git-exclude, launch hint)."""
    py, hook = sys.executable, os.path.join(HERE, "hook.py")
    s = os.path.join(wt, "_scratch")
    if harness == "claude":
        cfg = {"hooks": {"PostToolUse": [{"matcher": "*", "hooks": [
            {"type": "command", "command": f"{q(py)} {q(hook)} claude {q(wt)}", "timeout": 10}]}]},
               "permissions": {"deny": ["Bash(git push:*)", "Bash(git reset --hard:*)", "Bash(git clean:*)"]}}
        path = os.path.join(s, "claude-settings.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(cfg, f, indent=1)
        mode = "--permission-mode acceptEdits" if role == "builder" else "--allowedTools Read,Grep,Glob,Bash(git diff:*),Bash(git log:*)"
        return [], f'claude -p --settings "{path}" {mode} "<brief>"'
    if harness == "codex":
        cfg = {"hooks": {"PostToolUse": [{"matcher": "*", "hooks": [
            {"type": "command", "command": f"{q(py)} {q(hook)} codex {q(wt)}", "timeout": 10}]}]}}
        write_new(os.path.join(wt, ".codex", "hooks.json"), json.dumps(cfg, indent=1), "project codex hooks")
        sandbox = "workspace-write" if role == "builder" else "read-only"
        return [".codex/hooks.json"], (f"codex exec -m <model> -s {sandbox} -c 'approval_policy=\"never\"' -c 'mcp_servers={{}}' "
                                       f"-C \"{wt}\" -   (hooks run only once trusted; until then the brief's "
                                       f"read-the-mailbox rule is the channel, see references/delegation.md)")
    if harness == "opencode":
        js = PLUGIN.replace("%PY%", json.dumps(py)).replace("%HOOK%", json.dumps(hook)).replace("%ROOT%", json.dumps(wt))
        write_new(os.path.join(wt, ".opencode", "plugins", "delegation-mailbox.js"), js, "opencode plugin")
        paths = [".opencode/plugins/delegation-mailbox.js"]
        cfg_path = os.path.join(wt, "opencode.json")
        if os.path.exists(cfg_path):
            print(f"note: {cfg_path} exists; role permissions NOT written, add this block by hand: "
                  f"{json.dumps({'permission': OPENCODE_PERMS[role]})}")
        else:
            write_new(cfg_path, json.dumps({"$schema": "https://opencode.ai/config.json",
                                            "permission": OPENCODE_PERMS[role]}, indent=1), "opencode config")
            paths.append("opencode.json")
        return paths, f'opencode run "<message>" --dir "{wt}" -m <model> -f <brief>   (or launcher.py submit --workdir "{wt}")'
    if harness == "agy":
        # agy hands the command to `cmd /c` and mangles any quotes in it, so the hook command is
        # a bare shim name (cwd = the .agents folder) and the quoted paths live inside the shim.
        write_new(os.path.join(wt, ".agents", "delegation-hook.cmd"),
                  f"@{q(py)} {q(hook)} agy {q(wt)} %*\r\n", "agy hook shim")
        ev = lambda e, t=10: {"type": "command", "command": f".\\delegation-hook.cmd {e} --role {role} --interval {interval} --max {maxn}", "timeout": t}
        cfg = {"delegation": {"PreInvocation": [ev("PreInvocation")],
                              "PreToolUse": [{"matcher": "*", "hooks": [ev("PreToolUse")]}],
                              "PostToolUse": [{"matcher": "*", "hooks": [ev("PostToolUse")]}],
                              "Stop": [ev("Stop", int(interval * 60) + 60)]}}
        write_new(os.path.join(wt, ".agents", "hooks.json"), json.dumps(cfg, indent=1), "agy workspace hooks")
        skip = " --dangerously-skip-permissions" if role == "builder" else ""
        return [".agents/hooks.json", ".agents/delegation-hook.cmd"], (f'cd "{wt}"; agy --model "<label>" --print-timeout <sec>s{skip} -p "<brief>"   '
                                        f"(cwd MUST be the worktree, or the hooks do not load)")
    sys.exit(f"unknown harness {harness}")


def prepare(a):
    times, mark = {}, [time.time()]

    def tick(name):
        times[name], mark[0] = round(time.time() - mark[0], 1), time.time()
    if a.existing:
        wt = os.path.abspath(a.existing)
    else:
        wt = os.path.abspath(a.path)
        exists = run(["git", "rev-parse", "--verify", "--quiet", a.branch], cwd=a.repo, check=False).returncode == 0
        run(["git", "worktree", "add", wt, a.branch] if exists else ["git", "worktree", "add", "-b", a.branch, wt, a.base],
            cwd=a.repo)
    tick("worktree")
    env = dict(os.environ)
    if os.path.exists(os.path.join(wt, "pyproject.toml")) and shutil.which("uv"):
        if a.shared_venv:
            env["UV_PROJECT_ENVIRONMENT"] = os.path.abspath(a.shared_venv)
        cmd = ["uv", "sync"] + (["--frozen"] if os.path.exists(os.path.join(wt, "uv.lock")) else [])
        cmd += ["--python", a.python] if a.python else []
        run(cmd, cwd=wt, env=env)
    tick("python")
    if a.web:
        web = os.path.join(wt, a.web)
        if a.node_modules_from:
            if not os.path.exists(os.path.join(web, "node_modules")):
                run(["cmd", "/c", "mklink", "/J", os.path.join(web, "node_modules"), os.path.abspath(a.node_modules_from)])
        elif os.path.exists(os.path.join(web, "package-lock.json")):
            run("npm ci", cwd=web)
        elif os.path.exists(os.path.join(web, "pnpm-lock.yaml")):
            run("pnpm install --frozen-lockfile", cwd=web)
    tick("web")
    for pair in a.copy:
        src, dst = pair.split("=", 1)
        dst = os.path.join(wt, dst)
        (shutil.copytree if os.path.isdir(src) else shutil.copy2)(src, dst, **({"dirs_exist_ok": True} if os.path.isdir(src) else {}))
    tick("copy")
    s = os.path.join(wt, "_scratch")
    os.makedirs(s, exist_ok=True)
    for name in ("MAILBOX.md", "PROGRESS.md"):
        open(os.path.join(s, name), "a").close()
    paths, launch = bundle(wt, a.harness, a.role, a.interval, a.max_heartbeats)
    exclude(wt, ["_scratch/"] + paths)
    tick("bundle")
    quick = None
    if a.quick_test:
        p = run(a.quick_test, cwd=wt, env=dict(env, PYTHONDONTWRITEBYTECODE="1"), check=False)
        quick = {"cmd": a.quick_test, "rc": p.returncode, "tail": (p.stdout + p.stderr)[-600:]}
    tick("quick_test")
    out = {"worktree": wt, "harness": a.harness, "role": a.role, "seconds": times, "quick_test": quick,
           "launch": launch, "brief_line": BRIEF_LINE,
           "blank_these_env_vars": sorted(k for k in os.environ if SECRET.search(k)),
           "uv_project_environment": env.get("UV_PROJECT_ENVIRONMENT")}
    with open(os.path.join(s, "PREPARED.json"), "w", encoding="utf-8") as f:
        json.dump(out, f, indent=1)
    print(json.dumps(out, indent=1))
    if quick and quick["rc"]:
        sys.exit("quick test FAILED: fix the environment before starting the worker")


def selftest():
    import tempfile
    with tempfile.TemporaryDirectory() as d:
        repo = os.path.join(d, "repo")
        os.makedirs(repo)
        for c in (["git", "init", "-q", "-b", "main"], ["git", "commit", "-q", "--allow-empty", "-m", "init"]):
            run(c, cwd=repo, env=dict(os.environ, GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@t", GIT_COMMITTER_NAME="t",
                                      GIT_COMMITTER_EMAIL="t@t"))
        for i, h in enumerate(("claude", "opencode", "codex", "agy")):
            wt = os.path.join(d, f"wt-{h}")
            ns = argparse.Namespace(existing=None, path=wt, repo=repo, branch=f"job-{h}", base="main", harness=h,
                                    role="builder", python=None, shared_venv=None, web=None, node_modules_from=None,
                                    copy=[], quick_test="git status --short", interval=2, max_heartbeats=15)
            prepare(ns)
            status = run(["git", "status", "--porcelain"], cwd=wt).stdout
            assert status == "", f"{h}: bundle not git-excluded: {status!r}"
            prep = json.load(open(os.path.join(wt, "_scratch", "PREPARED.json")))
            assert prep["quick_test"]["rc"] == 0 and prep["harness"] == h
        js = open(os.path.join(d, "wt-opencode", ".opencode", "plugins", "delegation-mailbox.js")).read()
        assert "%PY%" not in js and "hook.py" in js
        hooks = json.load(open(os.path.join(d, "wt-agy", ".agents", "hooks.json")))["delegation"]
        assert hooks["Stop"][0]["timeout"] == 180 and "--interval 2" in hooks["Stop"][0]["command"]
        assert '"' not in hooks["Stop"][0]["command"], "agy mangles quotes in hook commands"
        shim = os.path.join(d, "wt-agy", ".agents", "delegation-hook.cmd")
        if os.name == "nt":  # the .cmd shim only runs on Windows
            p = subprocess.run('cmd /c .\\delegation-hook.cmd PreInvocation', cwd=os.path.dirname(shim), input="{}",
                               capture_output=True, text=True)
            assert '"injectSteps"' in p.stdout, p.stdout + p.stderr  # the shim really runs the hook
        try:  # a second bundle into the same tree must refuse, not clobber
            bundle(os.path.join(d, "wt-agy"), "agy", "builder", 2, 15)
            raise AssertionError("overwrote an existing hooks.json")
        except SystemExit:
            pass
    print("prepare_worktree selftest ok")


def main():
    if sys.argv[1:] == ["selftest"]:
        return selftest()
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--existing")
    ap.add_argument("--repo"); ap.add_argument("--path"); ap.add_argument("--branch"); ap.add_argument("--base", default="main")
    ap.add_argument("--harness", required=True, choices=["claude", "opencode", "codex", "agy"])
    ap.add_argument("--role", default="builder", choices=["builder", "reviewer", "auditor"])
    ap.add_argument("--python"); ap.add_argument("--shared-venv"); ap.add_argument("--web"); ap.add_argument("--node-modules-from")
    ap.add_argument("--copy", action="append", default=[]); ap.add_argument("--quick-test")
    ap.add_argument("--interval", type=float, default=2, help="agy idle heartbeat, minutes (run sheet mailbox_interval_min)")
    ap.add_argument("--max-heartbeats", type=int, default=15)
    a = ap.parse_args()
    if not a.existing and not (a.repo and a.path and a.branch):
        ap.error("give --existing, or --repo --path --branch")
    prepare(a)


if __name__ == "__main__":
    main()
