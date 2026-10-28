"""Install foreman into an agent harness's skills folder.

    python install.py                      # Claude Code: ~/.claude/skills/foreman
    python install.py --harness agents     # codex, opencode: ~/.agents/skills/foreman
    python install.py --harness all        # both
    python install.py --dest <dir>         # any other harness: the folder that will hold SKILL.md
    python install.py selftest

Copies the run-time files only (not tests, the sample run or dev notes). Re-run to update. Never touches LOCAL.md.
Stdlib only.
"""
import argparse, os, shutil, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
FILES = [
    "SKILL.md", "defaults.yaml", "LOCAL.md.example", "LICENSE",
    "harness/claude-code.md", "harness/generic.md",
    "profiles/default.yaml",
    "references/gates.md", "references/explore.md", "references/packet.md", "references/delegation.md",
    "delegation/prepare_worktree.py", "delegation/mailbox.py", "delegation/hook.py",
    "dashboard/tracker.html", "dashboard/packet.html", "dashboard/SCHEMA.md", "dashboard/seed-example.json",
    "track-mode/CHARTER.md", "track-mode/LAUNCHER.md", "track-mode/launcher.py", "track-mode/live.py",
    "track-mode/usage_split.py",
    "evals/plan_check.py",
]
HOME = os.path.expanduser("~")
TARGETS = {"claude": os.path.join(HOME, ".claude", "skills", "foreman"),
           "agents": os.path.join(HOME, ".agents", "skills", "foreman")}


def install(dest):
    # Overwrites in place; a file dropped from FILES in a later version stays behind until removed by hand
    for f in FILES:
        out = os.path.join(dest, *f.split("/"))
        os.makedirs(os.path.dirname(out), exist_ok=True)
        shutil.copy2(os.path.join(HERE, *f.split("/")), out)
    print(f"installed {len(FILES)} files -> {dest}")


def selftest():
    d = os.path.join(tempfile.mkdtemp(), "foreman")
    os.makedirs(d)
    with open(os.path.join(d, "LOCAL.md"), "w") as f:
        f.write("mine")
    install(d)
    for f in FILES:
        assert os.path.isfile(os.path.join(d, *f.split("/"))), f
    assert open(os.path.join(d, "LOCAL.md")).read() == "mine", "LOCAL.md was touched"
    assert not os.path.exists(os.path.join(d, "track-mode", "sample-run")), "sample run was copied"
    print("install selftest: OK")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cmd", nargs="?", choices=("selftest",))
    ap.add_argument("--harness", choices=("claude", "agents", "all"), default="claude")
    ap.add_argument("--dest", help="install here instead (the folder that will hold SKILL.md)")
    a = ap.parse_args()
    if a.cmd == "selftest":
        return selftest()
    for d in [a.dest] if a.dest else ([TARGETS["claude"], TARGETS["agents"]] if a.harness == "all" else [TARGETS[a.harness]]):
        install(os.path.abspath(os.path.expanduser(d)))
    try:
        import yaml  # noqa: F401
    except ImportError:
        print(f"note: live.py and plan_check.py need PyYAML: {sys.executable} -m pip install pyyaml")
    print("Start a new session to load it. Optional: copy LOCAL.md.example to LOCAL.md there and fill it in.")


if __name__ == "__main__":
    sys.exit(main())
