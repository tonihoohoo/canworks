"""The Devices workspace against a device over SSH (device-install task 4.2):
an in-process paramiko server (fake_ssh.py) for host key trust, a changed
key, password and key login, sudo with the password on standard input, and
install jobs that start, are followed, survive a dropped connection, stop
and refuse a second job; no password reaches a file."""

import os
import shutil
import sys
import time
import unittest
import unittest.mock

from .helpers import tmpdir

try:
    import paramiko
except ImportError:  # the Devices workspace's dependency; the tools job installs it
    paramiko = None

if paramiko is not None:
    from canworks.devices import jobs, service, ssh, store
    from . import fake_ssh

SSH_PW, SUDO_PW = "ssh-secret", "sudo-secret"


def files_text(folder):
    out = []
    for dirpath, _, names in os.walk(folder):
        for n in names:
            try:
                with open(os.path.join(dirpath, n), "rb") as f:
                    out.append(f.read().decode("utf-8", "replace"))
            except OSError:
                pass
    return "\n".join(out)


@unittest.skipUnless(paramiko is not None and sys.platform != "win32" and shutil.which("flock")
                     and shutil.which("setsid"), "needs paramiko, sh, flock and setsid")
class Device(unittest.TestCase):
    def setUp(self):
        d = tmpdir(self)
        env = unittest.mock.patch.dict(os.environ, {"HOME": os.path.join(d, "pc-home")})
        env.start()
        self.addCleanup(env.stop)
        os.environ.pop("SSH_AUTH_SOCK", None)
        self.settings = os.path.join(d, "settings")
        self.store = store.Store(self.settings)
        self.device = fake_ssh.Device(os.path.join(d, "device"))
        self.addCleanup(self.device.close)
        self.port = self.device.port

    def connect(self, **kw):
        return ssh.connect(self.store, "127.0.0.1", "pi", self.port, **kw)

    def trusted(self, password=SSH_PW):
        try:
            self.connect(password=password).close()
        except ssh.NeedTrust as e:
            conn = self.connect(password=password, trust=e.fingerprint)
            conn.close()

    def wait_done(self, conn, job, paths, timeout=20.0):
        offset, steps, lines, deadline = 0, [], [], time.monotonic() + timeout
        while time.monotonic() < deadline:
            out = jobs.follow(conn, job, offset, paths)
            offset = out["offset"]
            steps += out.get("steps", [])
            lines += out.get("lines", [])
            if out.get("found") and (out.get("exit") is not None or out.get("state") == "inactive") \
                    and not out.get("more"):
                return dict(out, steps=steps, lines=lines)
            time.sleep(0.1)
        self.fail("the job did not end")


class HostKeys(Device):
    def test_new_device_asks_first(self):
        with self.assertRaises(ssh.NeedTrust) as cm:
            self.connect(password=SSH_PW)
        self.assertEqual(cm.exception.fingerprint, ssh.fingerprint(self.device.host_key))
        self.assertEqual(self.device.commands, [])
        self.assertEqual(self.device.logins, [])
        conn = self.connect(password=SSH_PW, trust=cm.exception.fingerprint)
        self.assertEqual(conn.run("echo hi")[:2], (0, "hi\n"))
        conn.close()
        self.connect(password=SSH_PW).close()  # trusted now

    def test_changed_key_is_refused_and_kept(self):
        self.trusted()
        keys = paramiko.HostKeys(self.store.known_hosts)
        entry = "[127.0.0.1]:%d" % self.port
        keys.add(entry, "ssh-ed25519", paramiko.Ed25519Key.from_private_key_file(
            fake_ssh._new_key(tmpdir(self))))
        keys.save(self.store.known_hosts)
        with open(self.store.known_hosts) as f:
            before = f.read()
        with self.assertRaises(ssh.KeyChanged) as cm:
            self.connect(password=SSH_PW)
        self.assertIn("key changed", str(cm.exception))
        with open(self.store.known_hosts) as f:
            self.assertEqual(f.read(), before)
        self.assertTrue(ssh.forget_host_key(self.store, "127.0.0.1", self.port))
        with self.assertRaises(ssh.NeedTrust):
            self.connect(password=SSH_PW)


class Logins(Device):
    def test_password_then_key_login(self):
        self.trusted()
        with self.assertRaises(ssh.NeedPassword) as cm:
            self.connect()
        self.assertFalse(cm.exception.wrong)
        with self.assertRaises(ssh.NeedPassword) as cm:
            self.connect(password="nope")
        self.assertTrue(cm.exception.wrong)
        conn = self.connect(password=SSH_PW)
        line = ssh.own_public_key(self.store)
        ssh.add_key_login(conn, line)
        ssh.add_key_login(conn, line)
        conn.close()
        with open(os.path.join(self.device.home("pi"), ".ssh", "authorized_keys")) as f:
            self.assertEqual(f.read(), line + "\n")
        if os.name == "posix":
            self.assertEqual(os.stat(self.store.key_path).st_mode & 0o777, 0o600)
        self.connect().close()
        self.assertEqual(self.device.logins[-1], ("pi", "key"))


class Jobs(Device):
    def setUp(self):
        super().setUp()
        self.trusted()
        self.conn = self.connect(password=SSH_PW)
        self.addCleanup(self.conn.close)
        self.paths = self.device.paths()

    def test_sudo_password_on_stdin_only(self):
        with self.assertRaises(jobs.NeedSudo) as cm:
            jobs.start(self.conn, "password", None, "install_plugin", ["true"], self.paths)
        self.assertFalse(cm.exception.wrong)
        with self.assertRaises(jobs.NeedSudo) as cm:
            jobs.start(self.conn, "password", "wrong", "install_plugin", ["true"], self.paths)
        self.assertTrue(cm.exception.wrong)
        self.assertFalse(os.path.isdir(self.paths.log_dir))  # the wrong password never met the script
        job = jobs.start(self.conn, "password", SUDO_PW, "install_plugin",
                         ['echo "::canworks-step 1/1 Doing it"', "echo done"], self.paths)
        out = self.wait_done(self.conn, job, self.paths)
        self.assertEqual(out["exit"], 0)
        self.assertEqual([s["text"] for s in out["steps"]], ["Doing it"])
        self.assertIsInstance(out["steps"][0]["at"], int)
        self.assertIn("done", out["lines"])
        for command in self.device.commands:
            self.assertNotIn(SUDO_PW, command)
        self.assertNotIn(SUDO_PW, files_text(self.device.root))
        self.assertNotIn(SUDO_PW, files_text(self.settings))

    def test_follow_after_a_dropped_connection_and_stop(self):
        self.device.sudo_nopasswd = True
        job = jobs.start(self.conn, "nopasswd", None, "install_plugin",
                         ['echo "::canworks-step 1/2 First"', "echo one", "sleep 1",
                          'echo "::canworks-step 2/2 Second"', "echo two"], self.paths)
        first = jobs.follow(self.conn, job, 0, self.paths)
        self.device.drop_connections()
        conn = self.connect(password=SSH_PW)  # the job went on without the connection
        self.addCleanup(conn.close)
        out = self.wait_done(conn, job, self.paths)
        self.assertEqual(out["exit"], 0)
        self.assertEqual([s["text"] for s in out["steps"]], ["First", "Second"])
        self.assertGreaterEqual(first["offset"], 0)

        job = jobs.start(conn, "nopasswd", None, "install_plugin",
                         ['echo "::canworks-step 1/1 Waiting"', "sleep 30"], self.paths)
        time.sleep(0.3)
        jobs.stop(conn, "nopasswd", None, job, self.paths)
        out = self.wait_done(conn, job, self.paths, timeout=5.0)
        self.assertIsNone(out["exit"])
        self.assertEqual(out["state"], "inactive")

    def test_second_job_refused(self):
        self.device.sudo_nopasswd = True
        first = jobs.start(self.conn, "nopasswd", None, "install_plugin", ["sleep 2", "echo first"], self.paths)
        time.sleep(0.3)
        second = jobs.start(self.conn, "nopasswd", None, "install_plugin", ["echo second"], self.paths)
        out = self.wait_done(self.conn, second, self.paths)
        self.assertEqual(out["exit"], 75)
        self.assertIn("Another install is running on this device.", out["lines"])
        self.assertIn("wait until it ends", jobs.failure(self.conn, second, self.paths)["hint"])
        out = self.wait_done(self.conn, first, self.paths)
        self.assertEqual((out["exit"], out["lines"][-1:]), (0, ["first"]))

    def test_last_five_logs_kept(self):
        self.device.sudo_nopasswd = True
        ids = []
        for i in range(7):
            ids.append(jobs.start(self.conn, "nopasswd", None, "install_plugin", ["true"], self.paths,
                                  job_id="20261021T1200%02dZ-abcd" % i))
            self.wait_done(self.conn, ids[-1], self.paths)
        self.assertEqual(sorted(os.listdir(self.paths.log_dir)), [i + ".log" for i in ids[-5:]])


class Service(Device):
    """The configurator's Devices object: probe, plan, the job and the store."""

    def setUp(self):
        super().setUp()
        self.trusted()
        root = os.path.join(self.device.root, "fs")
        os.makedirs(os.path.join(root, "run", "systemd", "system"))
        self.devices = service.Devices(self.settings, paths=self.device.paths(), latest=lambda: "0.98.0",
                                       probe_env={"CANWORKS_PROBE_ROOT": root, "CANWORKS_PROBE_URL": "file:///"})
        self.addCleanup(self.devices.close_all)
        self.did = self.devices.add("/proj", "127.0.0.1", "pi", self.port)

    def test_probe_job_and_no_password_kept(self):
        with self.assertRaises(ssh.NeedPassword):
            self.devices.probe("/proj", self.did, "openplc", "proj", None, "0.98.0")
        out = self.devices.probe("/proj", self.did, "openplc", "proj", None, "0.98.0", password=SSH_PW)
        self.assertTrue(out["offer_key_login"])
        self.assertEqual(out["latest"], "0.98.0")
        self.assertEqual(out["plan"]["main"]["action"], "install_openplc")
        self.assertEqual(self.store.get("/proj", self.did)["latest"], "0.98.0")
        # The connection is kept: the next calls need no password.
        self.store.update("/proj", self.did, probe=dict(out["probe"], sudo="password"))
        with self.assertRaises(jobs.NeedSudo):
            self.devices.start("/proj", self.did, "install_plugin", {}, None)
        self.assertEqual(self.devices.running_jobs("/proj"), [])
        self.assertNotIn(SSH_PW, files_text(self.settings))
        self.assertNotIn(SUDO_PW, files_text(self.settings))

    def test_typical_time_and_failure(self):
        self.devices.probe("/proj", self.did, "openplc", "proj", None, "0.98.0", password=SSH_PW)
        conn, _ = self.devices.connection("/proj", self.did)
        self.device.sudo_nopasswd = True
        job = jobs.start(conn, "nopasswd", None, "install_plugin", ["echo ok"], self.devices.paths)
        self.store.update("/proj", self.did, job={"id": job, "action": "install_plugin", "version": "0.98.0"})
        deadline = time.monotonic() + 20
        out, offset = {}, 0
        while not out.get("done") and time.monotonic() < deadline:
            out = self.devices.follow("/proj", self.did, job, offset)
            offset = out["offset"]
            time.sleep(0.1)
        self.assertEqual(out["exit"], 0)
        self.assertIn("install_plugin", self.store.get("/proj", self.did)["job_seconds"])

        job = jobs.start(conn, "nopasswd", None, "install_plugin",
                         ["echo 'cp: write error: No space left on device'", "exit 3"], self.devices.paths)
        out, offset = {}, 0
        while not out.get("done") and time.monotonic() < deadline:
            out = self.devices.follow("/proj", self.did, job, offset)
            offset = out["offset"]
            time.sleep(0.1)
        self.assertEqual(out["exit"], 3)
        self.assertIn("disk is full", out["failure"]["hint"])
        self.assertEqual(out["failure"]["tail"], ["cp: write error: No space left on device"])


if __name__ == "__main__":
    unittest.main()
