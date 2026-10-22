"""Updates from inside the tools (pc-tools-self-update): the check, where
an install can update itself, the guard, the hand-off and the updater's
steps. No network: the release page is a local server, uv and the installed
commands are small fakes. The end-to-end update with real uv runs in the PC
tools workflow (test/pc-tools/update_e2e.py)."""

import http.client
import http.server
import json
import os
import sys
import threading
import time
import unittest
from unittest import mock

from canworks import updater
from canworks.configurator import server as srv, update

from .helpers import python_program, tmpdir


class Release(http.server.BaseHTTPRequestHandler):
    location = "/releases/tag/deploy-v9.1.0"
    status = 302
    seen = []

    def log_message(self, *args):
        pass

    def do_GET(self):
        Release.seen.append((self.path, self.headers.get("User-Agent")))
        self.send_response(self.status)
        if self.status in (301, 302):
            self.send_header("Location", self.location)
        self.send_header("Content-Length", "0")
        self.end_headers()


class ReleaseServer(unittest.TestCase):
    def setUp(self):
        self.dir = tmpdir(self)
        Release.location, Release.status, Release.seen = "/releases/tag/deploy-v9.1.0", 302, []
        self.httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Release)
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()
        self.addCleanup(self.httpd.server_close)
        self.addCleanup(self.httpd.shutdown)
        env = {"CANWORKS_REPO": "http://127.0.0.1:%d" % self.httpd.server_port,
               "CANWORKS_CONFIG_DIR": os.path.join(self.dir, "cfg")}
        p = mock.patch.dict(os.environ, env)
        p.start()
        self.addCleanup(p.stop)
        os.environ.pop(update.OFF_ENV, None)


class Check(ReleaseServer):
    def test_versions(self):
        self.assertEqual(update.version_key("0.102.0"), (0, 102, 0))
        self.assertIsNone(update.version_key("0.102"))
        self.assertTrue(update.is_newer("0.103.0", "0.102.9"))
        self.assertTrue(update.is_newer("1.0.0", "0.999.0"))
        self.assertFalse(update.is_newer("0.102.0", "0.102.0"))
        self.assertFalse(update.is_newer(None, "0.102.0"))

    def test_latest_from_the_redirect(self):
        self.assertEqual(update.latest_version(), "9.1.0")
        path, agent = Release.seen[-1]
        self.assertEqual(path, "/releases/latest")
        self.assertTrue(agent.startswith("canworks-config/"))

    def test_not_a_tools_release(self):
        Release.location = "/releases/tag/v2.0.0"
        with self.assertRaises(ValueError):
            update.latest_version()
        Release.status = 404
        with self.assertRaises(ValueError):
            update.latest_version()

    def test_once_a_day_and_dismissed(self):
        now = [1000000.0]
        u = update.Updates(info=lambda: {"kind": "other", "why": "x"}, clock=lambda: now[0])
        self.assertTrue(u.due())
        self.assertTrue(u.check_in_background())
        for _ in range(100):
            if not u.checking and u.state().get("latest"):
                break
            time.sleep(0.02)
        self.assertEqual(u.state()["latest"], "9.1.0")
        v = u.view()
        self.assertTrue(v["newer"])
        self.assertFalse(v["dismissed"])
        self.assertEqual(v["release_url"], os.environ["CANWORKS_REPO"] + "/releases/tag/deploy-v9.1.0")
        # Within a day: no request.
        now[0] += 3600
        seen = len(Release.seen)
        self.assertFalse(u.check_in_background())
        self.assertEqual(len(Release.seen), seen)
        now[0] += update.CHECK_EVERY_S
        self.assertTrue(u.due())
        # Dismissed for this version only.
        u.dismiss("9.1.0")
        self.assertTrue(u.view()["dismissed"])
        Release.location = "/releases/tag/deploy-v9.2.0"
        u.check()
        self.assertFalse(u.view()["dismissed"])
        with self.assertRaises(ValueError):
            u.dismiss("latest")

    def test_off(self):
        u = update.Updates(info=lambda: {"kind": "other", "why": "x"})
        self.assertFalse(u.check_in_background(ui_on=False))
        self.assertEqual(u.view(ui_on=False)["off"], "setting")
        with mock.patch.dict(os.environ, {update.OFF_ENV: "1"}):
            self.assertFalse(u.check_in_background())
            self.assertEqual(u.view()["off"], "env")
            # Check now still checks.
            self.assertTrue(u.check_in_background(force=True))

    def test_offline(self):
        os.environ["CANWORKS_REPO"] = "http://127.0.0.1:1"
        u = update.Updates(info=lambda: {"kind": "other", "why": "x"})
        self.assertIsNone(u.check())
        v = u.view()
        self.assertFalse(v["newer"])
        self.assertTrue(v["error"])
        self.assertFalse(u.due())  # tried: not again for a day


class Install(unittest.TestCase):
    def setUp(self):
        self.dir = tmpdir(self)
        self.tools = os.path.join(self.dir, "tools")
        self.prefix = os.path.join(self.tools, "canworks")
        os.makedirs(self.prefix)

    def receipt(self, python='python = "3.14"\n'):
        with open(os.path.join(self.prefix, "uv-receipt.toml"), "w") as f:
            f.write('[tool]\nrequirements = [{ name = "canworks" }]\n' + python)

    def info(self, **kw):
        uv = python_program(os.path.join(self.dir, "uv"), "")
        env = dict(kw.pop("env", {}), PATH=self.dir)
        dirs = {(): self.tools, ("--bin",): os.path.join(self.dir, "bin")}
        return update.install_info(prefix=self.prefix, env=env, uv_dir=lambda u, *a: dirs[a], **kw), uv

    def test_uv_tool(self):
        self.receipt()
        info, uv = self.info()
        self.assertEqual(info["kind"], "uv-tool", info)
        self.assertEqual(os.path.normcase(info["uv"]), os.path.normcase(os.path.abspath(uv)))
        self.assertEqual(info["python"], "3.14")
        self.assertEqual(info["bin"], os.path.join(self.dir, "bin"))

    def test_no_receipt(self):
        info, _ = self.info()
        self.assertEqual(info["kind"], "other")
        self.assertIn("one-line installer", info["why"])

    def test_not_in_uvs_tools_folder(self):
        self.receipt()
        dirs = {(): os.path.join(self.dir, "elsewhere"), ("--bin",): self.dir}
        python_program(os.path.join(self.dir, "uv"), "")
        info = update.install_info(prefix=self.prefix, env={"PATH": self.dir}, uv_dir=lambda u, *a: dirs[a])
        self.assertEqual(info["kind"], "other")

    def test_sandboxed_on_windows(self):
        local = os.path.join(self.dir, "Local")
        self.prefix = os.path.join(local, "Packages", "SomeApp_x", "LocalCache", "Roaming", "uv", "tools", "canworks")
        os.makedirs(self.prefix)
        self.receipt()
        info = update.install_info(prefix=self.prefix, platform="win32", env={"LOCALAPPDATA": local})
        self.assertEqual(info["kind"], "sandboxed")

    def test_receipt_python(self):
        self.receipt("")
        self.assertEqual(update.receipt_python(self.prefix), "%d.%d" % sys.version_info[:2])
        self.receipt('python = "3.13"\n')
        self.assertEqual(update.receipt_python(self.prefix), "3.13")

    def test_install_command(self):
        self.assertIn("install-pc.ps1", update.install_command("win32"))
        self.assertIn("RemoteSigned", update.install_command("win32"))
        self.assertTrue(update.install_command("linux").startswith("curl -LsSf "))


UV_TOOL = {"kind": "uv-tool", "why": None, "uv": "uv", "python": "3.14", "base": sys.executable,
           "env": "/tools/canworks", "bin": "/bin"}


class HandOff(unittest.TestCase):
    def setUp(self):
        self.dir = tmpdir(self)
        self.u = update.Updates(folder=self.dir, fetch=lambda: "9.1.0", info=lambda: dict(UV_TOOL))

    def test_run_file(self):
        d = self.u.run_file("9.1.0", 123, 4567, "tok", restart=True)
        self.assertEqual((d["from"], d["to"], d["pid"], d["port"], d["token"], d["restart"]),
                         (srv.__version__, "9.1.0", 123, 4567, "tok", True))
        self.assertTrue(d["wheel"].endswith("/releases/download/deploy-v9.1.0/canworks-9.1.0-py3-none-any.whl"))
        self.assertIn("deploy-v%s" % srv.__version__, d["old_wheel"])
        self.assertEqual(d["check_cmd"][1], "--version")
        self.assertIn("--from-shortcut", d["restart_cmd"])
        u = update.Updates(folder=self.dir, info=lambda: {"kind": "other", "why": "pip"})
        with self.assertRaises(ValueError):
            u.run_file("9.1.0", 1, 1, "t", True)

    def write_run(self, result, port=4567, token="tok"):
        with open(self.u.run_path, "w") as f:
            json.dump({"from": "0.1.0", "to": "9.1.0", "port": port, "token": token, "result": result}, f)

    def test_take_result_and_resume(self):
        self.assertIsNone(self.u.take_result())
        self.write_run(None)
        self.assertIsNone(self.u.take_result())
        self.assertTrue(os.path.exists(self.u.run_path))  # still running: kept
        self.write_run({"state": "ok", "message": "Updated to 9.1.0.", "at": time.time()})
        self.assertEqual(self.u.take_result(self.u.run_path), {"port": 4567, "token": "tok"})
        self.assertFalse(os.path.exists(self.u.run_path))
        self.assertEqual(self.u.result["state"], "ok")
        self.assertEqual(self.u.result["to"], "9.1.0")
        # Old, or a normal start: the result only.
        self.write_run({"state": "ok", "message": "m", "at": time.time() - 3600})
        self.assertIsNone(self.u.take_result(self.u.run_path))
        self.write_run({"state": "ok", "message": "m", "at": time.time()})
        self.assertIsNone(self.u.take_result())

    @unittest.skipIf(os.name == "nt", "file modes")
    def test_run_file_private(self):
        with mock.patch("subprocess.Popen"):
            self.u.start_updater(self.u.run_file("9.1.0", 1, 2, "secret", True))
        self.assertEqual(os.stat(self.u.run_path).st_mode & 0o777, 0o600)

    def test_one_update_at_a_time(self):
        with mock.patch("subprocess.Popen") as popen:
            self.u.start_updater(self.u.run_file("9.1.0", 1, 2, "t", True))
            cmd = popen.call_args[0][0]
            self.assertEqual(cmd[:3], [sys.executable, "-I", "-S"])
            self.assertTrue(cmd[3].endswith("updater.py") and os.path.isfile(cmd[3]))
            self.assertNotEqual(os.path.dirname(cmd[3]), os.path.dirname(updater.__file__))
            with self.assertRaises(ValueError):
                self.u.start_updater(self.u.run_file("9.1.0", 1, 2, "t", True))


def get(port, path, token, method="GET", body=None):
    c = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
    c.request(method, path, json.dumps(body) if body is not None else None,
              {"Host": "127.0.0.1:%d" % port, srv.TOKEN_HEADER: token, "Content-Type": "application/json"})
    r = c.getresponse()
    data = json.loads(r.read().decode() or "{}")
    c.close()
    return r.status, data


class Routes(unittest.TestCase):
    def setUp(self):
        self.dir = tmpdir(self)
        p = mock.patch.dict(os.environ, {"CANWORKS_CONFIG_DIR": os.path.join(self.dir, "cfg")})
        p.start()
        self.addCleanup(p.stop)
        os.environ.pop(update.OFF_ENV, None)  # tests/__init__.py turns the check off; restored by the patch
        self.server = srv.Server()
        self.server.updates = update.Updates(fetch=lambda: "9.1.0", info=lambda: dict(UV_TOOL))
        self.server.updates.check()
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)
        self.port, self.token = self.server.server_port, self.server.token

    def api(self, path, body=None):
        return get(self.port, path, self.token, "POST" if body is not None else "GET", body)

    def test_view_and_dismiss(self):
        status, v = self.api("/api/update")
        self.assertEqual(status, 200)
        self.assertEqual((v["latest"], v["newer"], v["kind"]), ("9.1.0", True, "uv-tool"))
        status, v = self.api("/api/update/dismiss", {"version": "9.1.0"})
        self.assertTrue(v["dismissed"])
        status, v = self.api("/api/update/dismiss", {"version": "x"})
        self.assertEqual(status, 400)

    def test_setting(self):
        status, ui = self.api("/api/ui", {"update_check": "off"})
        self.assertEqual((status, ui["update_check"]), (200, "off"))
        self.assertEqual(self.api("/api/update")[1]["off"], "setting")
        self.assertEqual(self.api("/api/ui", {"update_check": "never"})[0], 400)

    def test_refused_with_unsaved_changes(self):
        self.server.heartbeat("page-1", unsaved=True)
        with mock.patch.object(update.Updates, "start_updater") as start:
            status, body = self.api("/api/update/start", {"version": "9.1.0", "when": "now"})
        self.assertEqual(status, 409)
        self.assertIn("unsaved changes", body["error"])
        self.assertTrue(body["on_quit"])
        start.assert_not_called()

    def test_only_the_known_newer_version(self):
        status, body = self.api("/api/update/start", {"version": "0.0.1", "when": "now"})
        self.assertEqual(status, 409)
        self.server.updates.info_fn = lambda: {"kind": "other", "why": "pip"}
        self.server.updates._info = None
        status, body = self.api("/api/update/start", {"version": "9.1.0", "when": "now"})
        self.assertEqual(status, 409)
        self.assertEqual(body["kind"], "other")
        self.assertIn("install-pc", body["command"])

    def test_update_now_stops(self):
        with mock.patch.object(update.Updates, "start_updater") as start:
            status, body = self.api("/api/update/start", {"version": "9.1.0", "when": "now"})
        self.assertEqual((status, body["updating"]), (200, True))
        data = start.call_args[0][0]
        self.assertEqual((data["pid"], data["port"], data["token"], data["restart"]),
                         (os.getpid(), self.port, self.token, True))
        for _ in range(100):
            if self.server.stopped_why:
                break
            time.sleep(0.02)
        self.assertEqual(self.server.stopped_why, "update")

    def test_update_when_i_quit(self):
        status, v = self.api("/api/update/start", {"version": "9.1.0", "when": "quit"})
        self.assertEqual(v["on_quit"], "9.1.0")
        status, v = self.api("/api/update/start", {"version": "9.1.0", "when": "cancel"})
        self.assertIsNone(v["on_quit"])
        self.api("/api/update/start", {"version": "9.1.0", "when": "quit"})
        with mock.patch.object(update.Updates, "start_updater") as start:
            self.server.stop("it was told to stop (a signal)")
            start.assert_not_called()
            self.server.stop("Quit")
        data = start.call_args[0][0]
        self.assertEqual((data["to"], data["restart"], data["port"], data["token"]), ("9.1.0", False, None, None))

    def test_guard_clean(self):
        self.assertEqual(update.guard(self.server), [])
        self.server.jobs.jobs[1] = mock.Mock(state="running")
        self.assertEqual(update.guard(self.server), ["a job runs on the bus"])


class Updater(unittest.TestCase):
    """The updater's steps with a fake uv that installs by writing the
    version a fake canworks-deploy prints."""

    def setUp(self):
        self.dir = tmpdir(self)
        self.version_file = os.path.join(self.dir, "installed")
        with open(self.version_file, "w") as f:
            f.write("0.1.0")
        self.deploy = python_program(os.path.join(self.dir, "canworks-deploy"),
                                     "print('canworks-deploy', open(%r).read())\n" % self.version_file)
        self.uv_log = os.path.join(self.dir, "uv-args.json")
        self.env_dir = os.path.join(self.dir, "env")
        os.makedirs(self.env_dir)

    def fake_uv(self, behaviour):
        """behaviour: wheel URL substring -> (exit code, version written or None)."""
        src = ("import json, sys\n"
               "args = sys.argv[1:]\n"
               "log = %r\n"
               "try:\n    seen = json.load(open(log))\nexcept OSError:\n    seen = []\n"
               "json.dump(seen + [args], open(log, 'w'))\n"
               "spec = args[-1]\n"
               "for key, (code, version) in %r.items():\n"
               "    if key in spec:\n"
               "        if version: open(%r, 'w').write(version)\n"
               "        print('uv says: done' if code == 0 else 'error: no such wheel')\n"
               "        sys.exit(code)\n"
               "sys.exit(9)\n") % (self.uv_log, behaviour, self.version_file)
        return python_program(os.path.join(self.dir, "uv"), src)

    def run_file(self, uv, **extra):
        data = {"from": "0.1.0", "to": "9.1.0", "wheel": "http://x/new.whl", "old_wheel": "http://x/old.whl",
                "uv": uv, "python": "3.14", "env": self.env_dir, "bin": self.dir, "pid": None, "port": 1,
                "token": "t", "restart": False, "restart_cmd": None, "check_cmd": [self.deploy, "--version"],
                "shortcut_cmd": None, "shortcut_paths": [], "install_command": "curl ... | sh",
                "log": os.path.join(self.dir, "update.log"), "result": None}
        data.update(extra)
        path = os.path.join(self.dir, "update-run.json")
        with open(path, "w") as f:
            json.dump(data, f)
        return path

    def result(self, path):
        with open(path) as f:
            return json.load(f)["result"]

    def test_ok(self):
        path = self.run_file(self.fake_uv({"new.whl": (0, "9.1.0")}))
        self.assertEqual(updater.main([path]), 0)
        r = self.result(path)
        self.assertEqual((r["state"], r["version"]), ("ok", "9.1.0"))
        with open(self.uv_log) as f:
            args = json.load(f)[0]
        self.assertEqual(args[:4], updater.UV_INSTALL)
        self.assertEqual(args[4:6], ["--python", "3.14"])
        self.assertEqual(args[6], "--overrides")
        self.assertEqual(args[8], "canworks @ http://x/new.whl")
        with open(os.path.join(self.dir, "update.log")) as f:
            self.assertIn("uv says: done", f.read())

    def test_failed_unchanged(self):
        path = self.run_file(self.fake_uv({"new.whl": (1, None)}))
        self.assertEqual(updater.main([path]), 1)
        r = self.result(path)
        self.assertEqual((r["state"], r["version"]), ("failed", "0.1.0"))
        self.assertIn("no such wheel", r["message"])
        with open(self.uv_log) as f:
            self.assertEqual(len(json.load(f)), 1)  # no rollback: nothing changed

    def test_rolled_back(self):
        path = self.run_file(self.fake_uv({"new.whl": (1, "broken"), "old.whl": (0, "0.1.0")}))
        self.assertEqual(updater.main([path]), 1)
        self.assertEqual(self.result(path)["state"], "rolled-back")
        with open(self.version_file) as f:
            self.assertEqual(f.read(), "0.1.0")

    def test_broken_shows_the_command(self):
        path = self.run_file(self.fake_uv({"new.whl": (1, "broken"), "old.whl": (1, None)}))
        with mock.patch.object(updater, "message_window") as window:
            self.assertEqual(updater.main([path]), 2)
        self.assertEqual(self.result(path)["state"], "broken")
        self.assertIn("curl ... | sh", window.call_args[0][0])

    def test_waits_for_the_configurator(self):
        path = self.run_file(self.fake_uv({"new.whl": (0, "9.1.0")}), pid=os.getpid())
        with mock.patch.object(updater, "WAIT_PID_S", 0.2):
            self.assertEqual(updater.main([path]), 1)
        self.assertEqual(self.result(path)["state"], "failed")
        self.assertFalse(os.path.exists(self.uv_log))  # nothing installed while it runs

    def test_restart(self):
        path = self.run_file(self.fake_uv({"new.whl": (0, "9.1.0")}), restart=True, restart_cmd=["cfg", "--from-shortcut"])
        with mock.patch.object(updater, "start_detached") as start:
            updater.main([path])
        self.assertEqual(start.call_args[0][0], ["cfg", "--from-shortcut", "--resume", path])

    def test_files_free(self):
        self.assertTrue(updater.files_free(self.env_dir, wait_s=0))
        self.assertTrue(os.path.isdir(self.env_dir))
        self.assertTrue(updater.files_free(os.path.join(self.dir, "missing"), wait_s=0))

    @unittest.skipUnless(os.name == "nt", "Windows keeps open files' folders from being renamed")
    def test_files_in_use(self):
        held = open(os.path.join(self.env_dir, "held.txt"), "w")
        self.addCleanup(held.close)
        self.assertFalse(updater.files_free(self.env_dir, wait_s=0))


if __name__ == "__main__":
    unittest.main()
