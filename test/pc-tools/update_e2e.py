"""The update from inside the tools, end to end (pc-tools-self-update), on
the PC tools as the one-line installer put them: a running configurator
updates to a newer wheel and comes back on the same port with the same
session, through `canworks-config --update --yes`.

A local web server plays the release page: releases/latest redirects to a
made-up newer release (99.0.0, built from this checkout with only the
version changed), and releases/download serves its wheel, but not the
version under test's (an old release is often deleted: nothing may need
it). On Windows a process held open in the tools' environment first makes
the update stop cleanly with the old install still working. Then an update
whose wheel uv refuses puts the old environment back, before the real
update. On macOS and Linux a configurator still running the version under
test after 99.0.0 was installed beside it restarts into 99.0.0 without
installing anything.

    python test/pc-tools/update_e2e.py VERSION DIST_WHEEL [PYTHON]

Run it last in a job, or reinstall afterwards: it leaves the original
version installed again at the end.
"""

import http.client
import http.server
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
NEW = "99.0.0"
WIN = os.name == "nt"


def say(text):
    print("update-e2e: %s" % text, flush=True)


DUMP = {"cfg": None}


def dump():
    """What the configurator and the updater wrote, for a failed run."""
    cfg = DUMP["cfg"]
    if not cfg or not os.path.isdir(cfg):
        return
    for name in sorted(os.listdir(cfg)):
        path = os.path.join(cfg, name)
        if not os.path.isfile(path) or not name.endswith((".log", ".json", ".1")):
            continue
        print("----- %s" % name, flush=True)
        with open(path, encoding="utf-8", errors="replace") as f:
            print(f.read()[-6000:], flush=True)
    cmd = ["tasklist", "/v"] if WIN else ["ps", "-ef"]
    try:
        out = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, universal_newlines=True).stdout
        print("----- processes\n" + "\n".join(l for l in out.splitlines() if "python" in l.lower() or "canworks" in l.lower()),
              flush=True)
    except OSError:
        pass


def fail(text):
    print("update-e2e: FAILED: %s" % text, flush=True)
    dump()
    raise SystemExit("update-e2e: FAILED: %s" % text)


def uv(*args, **kw):
    return subprocess.run(["uv"] + list(args), check=True, universal_newlines=True, **kw)


def build_new_wheel(work):
    src = os.path.join(work, "deploy")
    shutil.copytree(os.path.join(ROOT, "tools", "deploy"), src,
                    ignore=shutil.ignore_patterns("tests", "__pycache__", "build", "*.egg-info", "dist"))
    pyproject = os.path.join(src, "pyproject.toml")
    with open(pyproject, encoding="utf-8") as f:
        text = f.read()
    with open(pyproject, "w", encoding="utf-8") as f:
        f.write(re.sub(r'^version = ".*"$', 'version = "%s"' % NEW, text, count=1, flags=re.M))
    init = os.path.join(src, "canworks", "__init__.py")
    with open(init, encoding="utf-8") as f:
        text = f.read()
    with open(init, "w", encoding="utf-8") as f:
        f.write(re.sub(r'^__version__ = ".*"$', '__version__ = "%s"' % NEW, text, count=1, flags=re.M))
    out = os.path.join(work, "dist-new")
    uv("build", "-q", "--wheel", "--out-dir", out, src)
    return os.path.join(out, "canworks-%s-py3-none-any.whl" % NEW)


class Release(http.server.BaseHTTPRequestHandler):
    wheels = {}
    corrupt = False  # serve a wheel uv refuses, for the step whose install fails
    # The made-up release's locked dependency versions (the exported uv.lock,
    # CANWORKS_E2E_CONSTRAINTS); the version under test has none, so the
    # updater's rollback path meets a release without them.
    constraints = {}

    def log_message(self, *args):
        pass

    def do_HEAD(self):
        self.do_GET(head=True)

    def do_GET(self, head=False):
        if self.path == "/releases/latest":
            self.send_response(302)
            self.send_header("Location", "/releases/tag/deploy-v%s" % NEW)
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        m = re.match(r"^/releases/download/deploy-v([0-9.]+)/(canworks-[0-9.]+-(?:py3-none-any\.whl|constraints\.txt))$",
                     self.path)
        files = dict(self.wheels, **self.constraints)
        if m and m.group(2) in files:
            with open(files[m.group(2)], "rb") as f:
                data = f.read()
            if self.corrupt and m.group(2).endswith(".whl"):
                data = b"not a wheel"
            self.send_response(200)
            self.send_header("Content-Type", "application/octet-stream")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            if not head:
                self.wfile.write(data)
            return
        self.send_response(404)
        self.send_header("Content-Length", "0")
        self.end_headers()


def bin_dir():
    return subprocess.run(["uv", "tool", "dir", "--bin"], check=True, stdout=subprocess.PIPE,
                          universal_newlines=True).stdout.strip()


def tool(name):
    return os.path.join(bin_dir(), name + (".exe" if WIN else ""))


def installed():
    try:
        out = subprocess.run([tool("canworks-deploy"), "--version"], stdout=subprocess.PIPE,
                             universal_newlines=True).stdout.split()
    except OSError:
        return None  # uv is replacing it
    return out[-1] if out else None


def tool_dir():
    return subprocess.run(["uv", "tool", "dir"], check=True, stdout=subprocess.PIPE,
                          universal_newlines=True).stdout.strip()


def instance(cfg):
    try:
        with open(os.path.join(cfg, "instance.json"), encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def request(port, method, path, body=None, headers=None):
    c = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
    h = {"Host": "127.0.0.1:%d" % port, "Content-Type": "application/json"}
    h.update(headers or {})
    c.request(method, path, json.dumps(body) if body is not None else None, h)
    r = c.getresponse()
    data = r.read()
    out = (r.status, dict(r.getheaders()), data)
    c.close()
    return out


def ask(inst, path, body):
    status, _, data = request(inst["port"], "POST", path, body, {"X-Canworks-Instance": inst["secret"]})
    return status, json.loads(data.decode() or "{}")


def wait_for(what, fn, timeout=300):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        v = fn()
        if v:
            return v
        time.sleep(0.5)
    fail("timed out waiting for %s" % what)


def start_configurator(env):
    p = subprocess.Popen([tool("canworks-config"), "--keep-running", "--no-browser"], env=env,
                         stdout=subprocess.PIPE, stderr=subprocess.STDOUT, universal_newlines=True)
    line = p.stdout.readline()
    m = re.search(r"http://127\.0\.0\.1:(\d+)/\?code=(\S+)", line)
    if not m:
        fail("no start address from canworks-config: %r" % line)
    # Its output is read and the process waited for, so it ends cleanly (no zombie keeps its pid).
    threading.Thread(target=lambda: ([None for _ in p.stdout], p.wait()), daemon=True).start()
    port = int(m.group(1))
    status, headers, _ = request(port, "GET", "/?code=" + m.group(2))
    cookie = headers.get("Set-Cookie", "").split(";", 1)[0]
    if status != 303 or "=" not in cookie:
        fail("the start address gave no session (%d)" % status)
    return p, port, cookie


def update_and_wait(env, cfg, old_pid):
    r = subprocess.run([tool("canworks-config"), "--update", "--yes"], env=env, stdout=subprocess.PIPE,
                       stderr=subprocess.STDOUT, universal_newlines=True)
    say("canworks-config --update: %s" % r.stdout.strip().replace("\n", " / "))
    if r.returncode != 0:
        fail("canworks-config --update exited with %d" % r.returncode)

    def back():
        inst = instance(cfg)
        if not inst or inst["pid"] == old_pid:
            return None
        try:
            status, view = ask(inst, "/api/instance/update", {})
        except OSError:
            return None
        return (inst, view) if status == 200 else None

    return wait_for("the configurator to come back", back, 150)


def main(version, dist_wheel):
    work = tempfile.mkdtemp(prefix="canworks-update-e2e-")
    cfg = os.path.join(work, "cfg")
    DUMP["cfg"] = cfg
    new_wheel = build_new_wheel(work)
    Release.wheels = {os.path.basename(new_wheel): new_wheel}  # not the version under test's: a rollback must not need it
    if os.environ.get("CANWORKS_E2E_CONSTRAINTS"):
        Release.constraints = {"canworks-%s-constraints.txt" % NEW: os.environ["CANWORKS_E2E_CONSTRAINTS"]}
    httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Release)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    env = dict(os.environ, CANWORKS_REPO="http://127.0.0.1:%d" % httpd.server_port, CANWORKS_CONFIG_DIR=cfg,
               CANWORKS_NO_UPDATE_CHECK="1")
    if installed() != version:
        fail("the installed tools are %s, not %s" % (installed(), version))

    p, port, cookie = start_configurator(env)
    inst = wait_for("instance.json", lambda: instance(cfg), 30)
    say("configurator %s runs on port %d (pid %d)" % (version, port, inst["pid"]))

    holder = None
    if WIN:
        env_dir = os.path.join(subprocess.run(["uv", "tool", "dir"], check=True, stdout=subprocess.PIPE,
                                              universal_newlines=True).stdout.strip(), "canworks")
        holder = subprocess.Popen([os.path.join(env_dir, "Scripts", "python.exe"), "-c", "import time; time.sleep(900)"])
        time.sleep(2)
        inst, view = update_and_wait(env, cfg, inst["pid"])
        result = view.get("result") or {}
        say("with a tools process held open: %s" % result)
        if result.get("state") != "locked":
            fail("expected the update to stop because a file is in use, got %r" % result)
        if installed() != version or view.get("version") != version:
            fail("the old install should be unchanged")
        if inst["port"] != port:
            fail("the old configurator came back on port %d, not %d" % (inst["port"], port))
        holder.kill()
        holder.wait()
        time.sleep(1)

    # A wheel uv refuses: the environment moved aside comes back, the old configurator starts again.
    Release.corrupt = True
    inst, view = update_and_wait(env, cfg, inst["pid"])
    Release.corrupt = False
    result = view.get("result") or {}
    say("with a wheel uv refuses: %s" % result)
    if result.get("state") != "failed" or "Still on %s" % version not in result.get("message", ""):
        fail("expected the failed update to keep %s, got %r" % (version, result))
    if installed() != version or view.get("version") != version:
        fail("the old install should be back: installed %s, running %s" % (installed(), view.get("version")))
    leftover = os.path.join(tool_dir(), ".canworks-update-backup")
    if os.path.exists(leftover):
        fail("the backup was left behind: %s" % leftover)
    with open(os.path.join(cfg, "update.log"), encoding="utf-8") as f:
        text = f.read()
    if "put the backup back" not in text:
        fail("the failed update did not put the moved environment back (update.log)")

    inst, view = update_and_wait(env, cfg, inst["pid"])
    result = view.get("result") or {}
    say("update: %s" % result)
    if result.get("state") != "ok" or view.get("version") != NEW or installed() != NEW:
        fail("expected %s to be installed and running, got %r, installed %s" % (NEW, view, installed()))
    if inst["port"] != port:
        fail("the new configurator listens on %d, not on the old port %d" % (inst["port"], port))
    status, _, _ = request(port, "GET", "/", headers={"Cookie": cookie})
    if status != 200:
        fail("the open tab's session does not work on the new configurator (%d)" % status)
    token = cookie.split("=", 1)[1]
    status, _, data = request(port, "GET", "/api/update", headers={"X-CANopen-Token": token})
    if status != 200 or json.loads(data.decode()).get("version") != NEW:
        fail("GET /api/update on the new configurator: %d %r" % (status, data[:200]))
    request(port, "POST", "/api/quit", {}, {"X-CANopen-Token": token})
    wait_for("the configurator to stop", lambda: instance(cfg) is None, 30)
    p.wait(timeout=30)
    log = os.path.join(cfg, "update.log")
    with open(log, encoding="utf-8") as f:
        text = f.read()
    say("update.log has %d lines" % len(text.splitlines()))
    if Release.constraints and "--constraints" not in text:
        fail("the update did not install the release's locked dependency versions (no --constraints in update.log)")

    # Back to the version under test, then canworks-config --update with no
    # configurator running: in the terminal (macOS, Linux) or in the
    # background (Windows); then back again for the steps after this one.
    overrides = os.path.join(work, "overrides.txt")
    with open(overrides, "w", encoding="ascii") as f:
        f.write("pytest; sys_platform == 'never'\n")
    python = sys.argv[3] if len(sys.argv) > 3 else "3.14"

    def reinstall():
        uv("tool", "install", "--force", "--compile-bytecode", "--python", python, "--overrides", overrides, dist_wheel)

    reinstall()
    r = subprocess.run([tool("canworks-config"), "--update", "--yes"], env=env, stdout=subprocess.PIPE,
                       stderr=subprocess.STDOUT, universal_newlines=True)
    say("canworks-config --update without a configurator: exit %d" % r.returncode)
    if r.returncode != 0:
        fail("canworks-config --update exited with %d:\n%s" % (r.returncode, r.stdout))
    # Only the run file is watched meanwhile: on Windows a tools program
    # started during the install would hold its files.
    run_file = os.path.join(cfg, "update-run.json")

    def finished():
        try:
            with open(run_file, encoding="utf-8") as f:
                return json.load(f).get("result")
        except (OSError, ValueError):
            return None

    # macOS and Linux: done when the command ends (it takes the result).
    result = wait_for("the command line update", finished, 300) if WIN else {"state": "ok"}
    say("command line update: %s" % result)
    if result.get("state") != "ok" or installed() != NEW:
        fail("expected %s to be installed, got %r, installed %s" % (NEW, result, installed()))
    if instance(cfg) is not None:
        fail("canworks-config --update without a configurator started one")
    if not WIN:
        # Reinstalled as 99.0.0 while a configurator of the version under test
        # runs (Windows keeps a running install's files): it restarts into
        # 99.0.0 and installs nothing.
        reinstall()
        p, port, cookie = start_configurator(env)
        inst = wait_for("instance.json", lambda: instance(cfg), 30)
        uv("tool", "install", "--force", "--compile-bytecode", "--python", python, "--overrides", overrides, new_wheel)
        token = cookie.split("=", 1)[1]
        status, _, data = request(port, "GET", "/api/update", headers={"X-CANopen-Token": token})
        view = json.loads(data.decode())
        if not view.get("restart") or view.get("installed") != NEW:
            fail("the configurator should offer a restart into %s: %r" % (NEW, view))
        status, _, data = request(port, "POST", "/api/update/start", {"version": NEW, "when": "now"},
                                  {"X-CANopen-Token": token})
        if status != 200:
            fail("restart refused: %d %r" % (status, data[:200]))
        old_pid = inst["pid"]
        inst = wait_for("the restarted configurator", lambda: (lambda i: i if i and i["pid"] != old_pid else None)(instance(cfg)), 150)
        status, _, data = request(inst["port"], "GET", "/api/update", headers={"X-CANopen-Token": token})
        view = json.loads(data.decode())
        say("restart into the installed version: %s" % view.get("result"))
        if view.get("version") != NEW or (view.get("result") or {}).get("state") != "already":
            fail("expected the configurator %s with result already, got %r" % (NEW, view))
        request(inst["port"], "POST", "/api/quit", {}, {"X-CANopen-Token": token})
        wait_for("the configurator to stop", lambda: instance(cfg) is None, 30)
        p.wait(timeout=30)
    reinstall()
    httpd.shutdown()
    shutil.rmtree(work, ignore_errors=True)
    say("passed")


if __name__ == "__main__":
    if len(sys.argv) < 3:
        raise SystemExit(__doc__)
    main(sys.argv[1], os.path.abspath(sys.argv[2]))
