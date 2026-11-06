"""Ask whether a newer Foreman release exists, and install it on the owner's yes.

    python setup/update.py check [--force]   # prints the question when a newer release is out, else nothing
    python setup/update.py install <tag>     # download the tag's archive, verify SHA256SUMS, run its install.py
    python setup/update.py selftest

Never installs unasked. The archive must match its line in the release's SHA256SUMS or nothing is copied.
~/.foreman/ and LOCAL.md are never touched. Stdlib only.
"""
import hashlib, io, json, os, re, subprocess, sys, tarfile, tempfile, time, urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)  # the skill root: <skill>/setup/update.py
sys.path.insert(0, HERE)
import store  # noqa: E402

REPO = "MarioMagdy/foreman"
API = f"https://api.github.com/repos/{REPO}/releases/latest"
DOWNLOAD = f"https://github.com/{REPO}/releases/download"
DAY = 24 * 3600

def _open(url):
    req = urllib.request.Request(url, headers={"User-Agent": "foreman-update"})
    with urllib.request.urlopen(req, timeout=10) as r:
        return r.read()


def fetch_bytes(url):
    return _open(url)


def fetch_json(url):
    return json.loads(_open(url).decode("utf-8"))


def _nums(v):
    m = re.fullmatch(r"v?(\d+(?:\.\d+)*)", str(v).strip())
    return tuple(int(x) for x in m.group(1).split(".")) if m else None


def newer(a, b):
    """True when version a is newer than b ("v2.10" > "v2.9", "2.4.1" > "v2.4"). Unparseable: False."""
    x, y = _nums(a), _nums(b)
    if x is None or y is None:
        return False
    n = max(len(x), len(y))
    return x + (0,) * (n - len(x)) > y + (0,) * (n - len(y))


def installed():
    try:
        with open(os.path.join(ROOT, "VERSION"), encoding="utf-8") as f:
            return f.read().strip() or "v0"
    except OSError:
        return "v0"


def check(force=False, fetch=fetch_json):
    """{"tag", "notes"} when a newer release exists, else None. At most once per 24 h unless force."""
    try:
        # The time of the last check lives in its own file: writing it into setup.yaml would make a machine that never
        # finished `foreman setup` look set up.
        stamp = os.path.join(store.home(), "last-update-check")
        try:
            last = float(open(stamp, encoding="utf-8").read())
        except (OSError, ValueError):
            last = 0.0
        if not force and time.time() - last < DAY:
            return None
        rel = fetch(API)
        tag = rel["tag_name"]
        os.makedirs(store.home(), exist_ok=True)
        with open(stamp, "w", encoding="utf-8") as f:
            f.write(str(time.time()))
        if not newer(tag, installed()):
            return None
        lines = [x.strip() for x in str(rel.get("body") or "").splitlines() if x.strip()]
        return {"tag": tag, "notes": "\n".join(lines[:3])}
    except Exception:
        return None


def question(rel):
    return f"Foreman {rel['tag']} is out:\n{rel['notes']}\nInstall it now? (Recommended: yes)"


def _safe(name):
    parts = re.split(r"[\\/]", name)
    return not (name.startswith(("/", "\\")) or re.match(r"[A-Za-z]:", name) or ".." in parts)


def _sum_for(sums, name):
    for line in sums.decode("utf-8", "replace").splitlines():
        bits = line.split(None, 1)
        if len(bits) == 2 and bits[1].strip().lstrip("*") == name:
            return bits[0].lower()
    return None


def _differs(new_root):
    out = []
    for dp, _, fs in os.walk(new_root):
        for f in fs:
            p = os.path.join(dp, f)
            rel = os.path.relpath(p, new_root)
            old = os.path.join(ROOT, rel)
            if not os.path.isfile(old) or open(old, "rb").read() != open(p, "rb").read():
                out.append(rel.replace(os.sep, "/"))
    return sorted(out)


def install(tag, fetch=fetch_bytes, harnesses=None, runner=subprocess.call):
    """Install release `tag`. Returns 0, or 1 with the reason printed (nothing installed)."""
    if not re.fullmatch(r"v?\d+(\.\d+)*", tag):
        print(f"refusing: '{tag}' is not a release tag")
        return 1
    name = f"foreman-{tag}.tar.gz"
    tmp = tempfile.mkdtemp()
    try:
        try:
            archive = fetch(f"{DOWNLOAD}/{tag}/{name}")
            sums = fetch(f"{DOWNLOAD}/{tag}/SHA256SUMS")
        except Exception as e:
            print(f"download failed: {e}")
            return 1
        want = _sum_for(sums, name)
        if not want:
            print(f"stopping: SHA256SUMS has no line for {name}")
            return 1
        if hashlib.sha256(archive).hexdigest() != want:
            print("stopping: the archive does not match SHA256SUMS")
            return 1
        try:
            with tarfile.open(fileobj=io.BytesIO(archive), mode="r:gz") as t:
                for m in t.getmembers():
                    if not _safe(m.name) or not (m.isfile() or m.isdir()):
                        print(f"stopping: unsafe archive member '{m.name}'")
                        return 1
                if hasattr(tarfile, "data_filter"):
                    t.extractall(tmp, filter="data")
                else:
                    t.extractall(tmp)
        except (tarfile.TarError, OSError, EOFError) as e:
            print(f"stopping: cannot read the archive: {e}")
            return 1
        root = tmp
        if not os.path.isfile(os.path.join(root, "install.py")):
            subs = [d for d in os.listdir(tmp) if os.path.isdir(os.path.join(tmp, d))]
            root = os.path.join(tmp, subs[0]) if len(subs) == 1 else tmp
        script = os.path.join(root, "install.py")
        if not os.path.isfile(script):
            print("stopping: the archive has no install.py")
            return 1
        changed = _differs(root)
        print(f"{len(changed)} files differ from the installed copy:")
        for f in changed:
            print(f"  {f}")
        # setup.yaml names harnesses (claude, codex, opencode); install.py takes the folder they read skills from
        folder = {"claude": "claude", "claude-code": "claude", "codex": "agents", "opencode": "agents",
                  "agents": "agents", "all": "all"}
        hs = []
        for h in harnesses or store.get("harnesses", None) or ["claude"]:
            f = folder.get(str(h).strip().lower())
            if not f:
                print(f"skipping harness {h!r}: install it by hand with install.py --dest <its skills folder>")
            elif f not in hs:
                hs.append(f)
        if not hs:
            print("nothing installed: no harness this installer knows (claude, codex, opencode)")
            return 1
        bad = 0
        for h in hs:
            bad += 1 if (runner([sys.executable, script, "--harness", h]) or 0) else 0
        if bad:
            print("install.py failed for at least one harness")
            return 1
        print(f"Foreman {tag} installed. It loads at the next session start.")
        return 0
    finally:
        import shutil
        shutil.rmtree(tmp, ignore_errors=True)


def _make_release(tag, members, extra=()):
    """An in-memory .tar.gz laid out like `git archive --prefix=foreman-<tag>/`."""
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as t:
        for name, data in list(members.items()) + list(extra):
            ti = tarfile.TarInfo(name)
            ti.size = len(data)
            t.addfile(ti, io.BytesIO(data))
    return buf.getvalue()


def selftest():
    assert newer("v2.4", "v2.3") and newer("v2.10", "v2.9") and newer("2.4.1", "v2.4")
    assert not newer("v2.4", "v2.4") and not newer("v2.3", "v2.4") and not newer("junk", "v2.4")
    assert re.fullmatch(r"v\d+(\.\d+)+", installed()), installed()

    sandbox = tempfile.mkdtemp()
    old = {k: os.environ.get(k) for k in ("FOREMAN_HOME",)}
    old_tmp = tempfile.tempdir
    os.environ["FOREMAN_HOME"] = os.path.join(sandbox, "fh")
    try:
        calls = []

        def fetch(url):
            calls.append(url)
            return {"tag_name": "v9.9", "body": "\n\nfirst\n  \nsecond\nthird\nfourth\n"}

        r = check(fetch=fetch)
        assert r == {"tag": "v9.9", "notes": "first\nsecond\nthird"}, r
        assert check(fetch=fetch) is None and len(calls) == 1, "second call must be throttled"
        assert store.load() == {}, "a release check must not create setup.yaml (it marks the machine as set up)"
        assert check(force=True, fetch=fetch)["tag"] == "v9.9"

        def older(url):
            return {"tag_name": "v2.4", "body": "x"}
        assert check(force=True, fetch=older) is None

        def boom(url):
            raise OSError("offline")
        assert check(force=True, fetch=boom) is None
        assert check(force=True, fetch=lambda u: ["not", "a", "dict"]) is None
        assert "Install it now? (Recommended: yes)" in question(r)

        # install: good archive, bad sums, evil member
        tag = "v9.9"
        name = f"foreman-{tag}.tar.gz"
        good = _make_release(tag, {f"foreman-{tag}/install.py": b"print(1)", f"foreman-{tag}/VERSION": b"v9.9\n"})
        sums = f"{hashlib.sha256(good).hexdigest()}  {name}\n".encode()

        def serve(archive, sumfile):
            def f(url):
                if url.endswith("SHA256SUMS"):
                    return sumfile
                assert url == f"{DOWNLOAD}/{tag}/{name}", url
                return archive
            return f

        tempfile.tempdir = os.path.join(sandbox, "tmp")
        os.makedirs(tempfile.tempdir)
        ran = []
        rc = install(tag, fetch=serve(good, sums), harnesses=["claude", "agents"], runner=lambda c: ran.append(c) or 0)
        assert rc == 0 and len(ran) == 2, (rc, ran)
        assert ran[0][1].endswith("install.py") and ran[0][-2:] == ["--harness", "claude"], ran[0]
        assert ran[1][-1] == "agents", ran[1]
        assert os.listdir(tempfile.tempdir) == [], "temp dir must be cleaned up"

        ran.clear()
        assert install(tag, fetch=serve(good, b"0" * 64 + b"  " + name.encode() + b"\n"), runner=ran.append) == 1
        assert install(tag, fetch=serve(good, b"abc  other.tar.gz\n"), runner=ran.append) == 1
        assert install(tag, fetch=serve(good, b""), runner=ran.append) == 1
        assert install("../x", fetch=serve(good, sums), runner=ran.append) == 1
        assert not ran, "nothing may run after a failed check"

        for bad in ("../evil", "/abs/evil", "foreman-v9.9/../../evil", "C:/evil"):
            evil = _make_release(tag, {f"foreman-{tag}/install.py": b"x"}, extra=[(bad, b"pwned")])
            esums = f"{hashlib.sha256(evil).hexdigest()}  {name}\n".encode()
            assert install(tag, fetch=serve(evil, esums), runner=ran.append) == 1, bad
        assert not ran
        assert not os.path.exists(os.path.join(sandbox, "evil")) and not os.path.exists(os.path.join(sandbox, "tmp", "evil"))
        assert os.listdir(tempfile.tempdir) == []

        def offline(url):
            raise OSError("offline")
        assert install(tag, fetch=offline, runner=ran.append) == 1

        store.save({"harnesses": ["agents"]})
        ran.clear()
        assert install(tag, fetch=serve(good, sums), runner=lambda c: ran.append(c) or 0) == 0
        assert [c[-1] for c in ran] == ["agents"], ran
        # harness names from setup map to install.py's folders: codex and opencode share ~/.agents, once
        store.save({"harnesses": ["claude", "codex", "opencode", "gemini"]})
        ran.clear()
        assert install(tag, fetch=serve(good, sums), runner=lambda c: ran.append(c) or 0) == 0
        assert [c[-1] for c in ran] == ["claude", "agents"], ran
        store.save({"harnesses": ["agy"]})
        ran.clear()
        assert install(tag, fetch=serve(good, sums), runner=lambda c: ran.append(c) or 0) == 1 and not ran, \
            "no known harness: report failure, not success"
    finally:
        tempfile.tempdir = old_tmp
        for k, v in old.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
    print("selftest: OK")


def main(argv):
    cmd = argv[1] if len(argv) > 1 else ""
    if cmd == "selftest":
        return selftest()
    if cmd == "check":
        r = check(force="--force" in argv)
        if r:
            print(question(r))
        return 0
    if cmd == "install" and len(argv) > 2:
        return install(argv[2])
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))
