"""Find the agent CLIs and companion skills on this machine. Prints JSON.

    python setup/detect.py tools         # {"claude": "2.1.3 (Claude Code)", "codex": null, ...}
    python setup/detect.py companions    # each companion in companions.yaml, found or not
    python setup/detect.py selftest

Stdlib only. companions.yaml is JSON-compatible YAML; PyYAML is used only if the file is not plain JSON.
"""
import json, os, shutil, subprocess, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
REGISTRY = os.path.join(os.path.dirname(HERE), "companions.yaml")
HOME = os.path.expanduser("~")
SKILL_DIRS = [os.path.join(HOME, ".claude", "skills"), os.path.join(HOME, ".agents", "skills")]
CLIS = ("claude", "codex", "opencode", "agy")

def _version(cli):
    """First line of `<cli> --version`, or None when the CLI is missing or fails."""
    exe = shutil.which(cli)  # resolves .cmd shims on Windows
    if not exe:
        return None
    try:
        r = subprocess.run([exe, "--version"], capture_output=True, text=True, timeout=10,
                           stdin=subprocess.DEVNULL)
    except (OSError, subprocess.SubprocessError):
        return None
    if r.returncode != 0:
        return None
    lines = (r.stdout or r.stderr or "").strip().splitlines()
    return lines[0].strip() if lines else None


def tools():
    return {cli: _version(cli) for cli in CLIS}


def _read(path):
    try:
        text = open(path, encoding="utf-8").read()
    except OSError:
        return []
    try:
        data = json.loads(text)
    except ValueError:
        try:
            import yaml
            data = yaml.safe_load(text)
        except Exception:
            return []
    return data if isinstance(data, list) else []


def companions(registry, skill_dirs):
    out = []
    for row in _read(registry):
        if not isinstance(row, dict) or not row.get("name"):
            continue
        found = any(os.path.isfile(os.path.join(d, row["name"], "SKILL.md")) for d in skill_dirs)
        out.append({"name": row["name"], "used_for": row.get("used_for", ""),
                    "source": row.get("source", ""), "fallback": row.get("fallback", ""), "found": found})
    return out


def selftest():
    t = tools()
    assert set(t) == set(CLIS), t
    assert all(v is None or isinstance(v, str) for v in t.values()), t
    assert _version("definitely-not-a-real-cli-xyz") is None
    d = tempfile.mkdtemp()
    os.makedirs(os.path.join(d, "skills", "council-judge"))
    open(os.path.join(d, "skills", "council-judge", "SKILL.md"), "w").write("x")
    os.makedirs(os.path.join(d, "skills", "keys"))  # folder without SKILL.md does not count
    reg = os.path.join(d, "companions.yaml")
    rows = [{"name": n, "used_for": "u", "source": "not public yet", "fallback": "references/x.md"}
            for n in ("council-judge", "keys")]
    json.dump(rows, open(reg, "w"))
    got = {c["name"]: c for c in companions(reg, [os.path.join(d, "skills"), os.path.join(d, "nope")])}
    assert got["council-judge"]["found"] is True, got
    assert got["keys"]["found"] is False, got
    assert set(got["keys"]) == {"name", "used_for", "source", "fallback", "found"}, got
    assert companions(os.path.join(d, "missing.yaml"), []) == []
    real = companions(REGISTRY, [os.path.join(d, "skills")])  # the shipped registry parses
    assert {"delegation", "keys", "council-judge"} <= {c["name"] for c in real}, real
    print("selftest: OK")


def main(argv):
    cmd = argv[1] if len(argv) > 1 else "tools"
    if cmd == "selftest":
        return selftest()
    if cmd == "tools":
        print(json.dumps(tools(), indent=2))
    elif cmd == "companions":
        print(json.dumps(companions(REGISTRY, SKILL_DIRS), indent=2))
    else:
        print(__doc__)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
