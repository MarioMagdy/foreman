"""Foreman's machine-level settings (one file per machine, shared by every harness install).

    python setup/store.py show        # print the saved settings
    python setup/store.py selftest

Lives in $FOREMAN_HOME or ~/.foreman/setup.yaml (written as indented JSON, which is valid YAML).
install.py never touches it. Stdlib only; PyYAML is used to read a hand-edited file when present.
"""
import json, os, sys, tempfile

def home():
    return os.environ.get("FOREMAN_HOME") or os.path.join(os.path.expanduser("~"), ".foreman")


def _path():
    return os.path.join(home(), "setup.yaml")


def load():
    """The saved settings, or {} when the file is missing or unreadable."""
    try:
        with open(_path(), encoding="utf-8") as f:
            text = f.read()
    except OSError:
        return {}
    try:
        d = json.loads(text)
    except ValueError:
        try:
            import yaml
            d = yaml.safe_load(text)
        except Exception:
            return {}
    return d if isinstance(d, dict) else {}


def save(d):
    os.makedirs(home(), exist_ok=True)
    with open(_path(), "w", encoding="utf-8") as f:
        json.dump(d, f, indent=2)
        f.write("\n")


def get(key, default=None):
    """Dotted lookup: get("checkin.minutes", 60)."""
    cur = load()
    for part in key.split("."):
        if not isinstance(cur, dict) or part not in cur:
            return default
        cur = cur[part]
    return cur


def selftest():
    old = os.environ.get("FOREMAN_HOME")
    os.environ["FOREMAN_HOME"] = os.path.join(tempfile.mkdtemp(), "fh")
    try:
        assert home() == os.environ["FOREMAN_HOME"]
        assert load() == {}, "missing file must load as {}"
        save({"checkin": {"minutes": 30}})
        assert load() == {"checkin": {"minutes": 30}}
        assert get("checkin.minutes", 60) == 30
        assert get("nope.x", 7) == 7
        assert get("checkin.minutes.deeper", 5) == 5
        with open(os.path.join(home(), "setup.yaml"), "w") as f:
            f.write("{ this is: [not valid")
        assert load() == {}, "garbage must load as {}"
        with open(os.path.join(home(), "setup.yaml"), "w") as f:
            f.write("[1, 2]")
        assert load() == {}, "a non-mapping must load as {}"
        del os.environ["FOREMAN_HOME"]
        assert home() == os.path.join(os.path.expanduser("~"), ".foreman")
    finally:
        if old is None:
            os.environ.pop("FOREMAN_HOME", None)
        else:
            os.environ["FOREMAN_HOME"] = old
    print("selftest: OK")


def main(argv):
    cmd = argv[1] if len(argv) > 1 else "show"
    if cmd == "selftest":
        return selftest()
    if cmd == "show":
        print(json.dumps(load(), indent=2))
        return 0
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))
