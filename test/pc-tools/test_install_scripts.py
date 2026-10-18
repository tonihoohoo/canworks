"""The one-line installers (scripts/install-pc.sh, install-pc.ps1,
install-runtime.sh, install-runtime.ps1): release lookup, options and the
commands they would run, against a local stand-in for GitHub, without
network access or installing anything (--dry-run)."""

import http.server
import os
import shutil
import socket
import stat
import subprocess
import sys
import tempfile
import threading
import unittest

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
SCRIPTS = os.path.join(REPO, "scripts")
IN_CI = bool(os.environ.get("CI"))


class _Releases(http.server.BaseHTTPRequestHandler):
    """releases/latest redirects to releases/tag/deploy-v1.2.3, like GitHub."""
    seen = []

    def do_GET(self):
        self.seen.append(self.path)
        if self.path.endswith("/releases/latest"):
            self.send_response(302)
            self.send_header("Location", self.path[:-len("latest")] + "tag/deploy-v1.2.3")
            self.send_header("Content-Length", "0")
            self.end_headers()
        else:
            body = b"ok"
            self.send_response(200)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    def log_message(self, *args):
        pass


def _free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


class _Base(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _Releases)
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()
        cls.repo_url = "http://127.0.0.1:%d/owner/canworks" % cls.server.server_address[1]

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()

    def setUp(self):
        _Releases.seen = []
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp)
        self.home = os.path.join(self.tmp, "home")
        self.bin = os.path.join(self.tmp, "bin")
        os.makedirs(self.home)
        os.makedirs(self.bin)

    def fake_uv(self):
        """A uv on PATH that only answers 'tool dir --bin'."""
        path = os.path.join(self.bin, "uv")
        with open(path, "w") as f:
            f.write('#!/bin/sh\n[ "$1 $2 $3" = "tool dir --bin" ] && echo "%s/uvbin"\nexit 0\n' % self.tmp)
        os.chmod(path, os.stat(path).st_mode | stat.S_IEXEC)

    def env(self, **extra):
        env = {"PATH": self.bin + os.pathsep + "/usr/bin:/bin", "HOME": self.home, "USERPROFILE": self.home,
               "CANWORKS_REPO": self.repo_url, "CANWORKS_API": self.repo_url + "/api",
               "CANWORKS_RAW": "https://raw.example/canworks", "CANWORKS_UV_INSTALLER": "https://uv.example/install.sh"}
        env.update(extra)
        return env

    def run_script(self, argv, env=None):
        return subprocess.run(argv, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, universal_newlines=True,
                              env=env or self.env(), timeout=60)


# The POSIX scripts are for macOS and Linux; Windows uses the .ps1 ones.
POSIX_ONLY = unittest.skipIf(os.name == "nt", "POSIX shell script; Windows uses the PowerShell installer")


@POSIX_ONLY
class InstallPcSh(_Base):
    script = os.path.join(SCRIPTS, "install-pc.sh")

    def test_newest_release(self):
        self.fake_uv()
        r = self.run_script(["sh", self.script, "--dry-run"])
        self.assertEqual(r.returncode, 0, r.stdout)
        self.assertIn("installing canworks 1.2.3", r.stdout)
        self.assertIn("tool install --force --compile-bytecode --python 3.12 canworks @ %s/releases/download/"
                      "deploy-v1.2.3/canworks-1.2.3-py3-none-any.whl" % self.repo_url, r.stdout)
        self.assertNotIn("uv.example", r.stdout)
        self.assertIn("/owner/canworks/releases/latest", _Releases.seen)

    def test_given_version_skips_lookup(self):
        self.fake_uv()
        r = self.run_script(["sh", self.script, "--dry-run", "--version", "deploy-v0.9.0"])
        self.assertEqual(r.returncode, 0, r.stdout)
        self.assertIn("deploy-v0.9.0/canworks-0.9.0-py3-none-any.whl", r.stdout)
        self.assertEqual(_Releases.seen, [])

    def test_local_wheel(self):
        self.fake_uv()
        wheel = os.path.join(self.tmp, "canworks-1.0.0-py3-none-any.whl")
        open(wheel, "w").close()
        r = self.run_script(["sh", self.script, "--dry-run", "--wheel", wheel, "--python", "3.13"])
        self.assertEqual(r.returncode, 0, r.stdout)
        self.assertIn("tool install --force --compile-bytecode --python 3.13 " + wheel, r.stdout)
        self.assertEqual(_Releases.seen, [])

    def test_installs_uv_when_missing(self):
        r = self.run_script(["sh", self.script, "--dry-run"])
        self.assertEqual(r.returncode, 0, r.stdout)
        self.assertIn("would run: curl -LsSf https://uv.example/install.sh | sh", r.stdout)

    def test_uv_found_in_local_bin(self):
        local = os.path.join(self.home, ".local", "bin")
        os.makedirs(local)
        self.bin, saved = local, self.bin
        self.fake_uv()
        self.bin = saved
        r = self.run_script(["sh", self.script, "--dry-run"])
        self.assertEqual(r.returncode, 0, r.stdout)
        self.assertNotIn("uv.example", r.stdout)
        self.assertIn(os.path.join(local, "uv") + " tool install", r.stdout)

    def test_uninstall(self):
        self.fake_uv()
        r = self.run_script(["sh", self.script, "--dry-run", "--uninstall"])
        self.assertEqual(r.returncode, 0, r.stdout)
        self.assertIn("tool uninstall canworks", r.stdout)
        self.assertEqual(_Releases.seen, [])

    def test_unreachable(self):
        self.fake_uv()
        url = "http://127.0.0.1:%d/owner/canworks" % _free_port()
        r = self.run_script(["sh", self.script, "--dry-run"], env=self.env(CANWORKS_REPO=url))
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("could not reach %s/releases/latest" % url, r.stdout)

    def test_unknown_option(self):
        r = self.run_script(["sh", self.script, "--frobnicate"])
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("unknown option: --frobnicate", r.stdout)


@POSIX_ONLY
class InstallRuntimeSh(_Base):
    script = os.path.join(SCRIPTS, "install-runtime.sh")

    def test_on_the_device(self):
        r = self.run_script(["bash", self.script, "--dry-run", "--with-link", "--runtime-dir", "/srv/my runtime"])
        self.assertEqual(r.returncode, 0, r.stdout)
        self.assertIn("would download: %s/archive/refs/tags/deploy-v1.2.3.tar.gz" % self.repo_url, r.stdout)
        self.assertIn("install-stock.sh --with-link --runtime-dir /srv/my\\ runtime", r.stdout)

    def test_over_ssh(self):
        r = self.run_script(["bash", self.script, "--dry-run", "--ssh", "pi@rpi.local", "--port", "2222",
                             "--identity", "/k/id", "--with-link"])
        self.assertEqual(r.returncode, 0, r.stdout)
        self.assertIn("installing canworks 1.2.3 on pi@rpi.local", r.stdout)
        line = [l for l in r.stdout.splitlines() if l.startswith("would run:")][0]
        self.assertIn("ssh -t -p 2222 -i /k/id pi@rpi.local", line)
        # The device fetches the script of the release it installs, pinned to it.
        self.assertIn("https://raw.example/canworks/deploy-v1.2.3/scripts/install-runtime.sh", line)
        self.assertIn("sudo bash -s -- --version 1.2.3 --with-link", line)

    def test_ssh_options_need_ssh(self):
        r = self.run_script(["bash", self.script, "--dry-run", "--port", "22"])
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("--port and --identity need --ssh", r.stdout)

    def test_given_version(self):
        r = self.run_script(["bash", self.script, "--dry-run", "--version", "0.9.0", "--uninstall"])
        self.assertEqual(r.returncode, 0, r.stdout)
        self.assertIn("deploy-v0.9.0.tar.gz", r.stdout)
        self.assertIn("install-stock.sh --uninstall", r.stdout)
        self.assertEqual(_Releases.seen, [])

    @unittest.skipIf(getattr(os, "geteuid", lambda: -1)() == 0, "runs as root here; the refusal is for non-root users")
    def test_not_root(self):
        r = self.run_script(["bash", self.script])
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("run it as root", r.stdout)
        self.assertIn("| sudo bash", r.stdout)
        self.assertEqual(_Releases.seen, [], "nothing is downloaded before the root check")


class Shellcheck(unittest.TestCase):
    def test_scripts(self):
        tool = shutil.which("shellcheck")
        if not tool:
            # Linux runners ship shellcheck; macOS and Windows runners do not.
            if IN_CI and sys.platform.startswith("linux"):
                self.fail("shellcheck is missing on the Linux CI runner")
            self.skipTest("shellcheck is not installed")
        r = subprocess.run([tool, os.path.join(SCRIPTS, "install-pc.sh"), os.path.join(SCRIPTS, "install-runtime.sh")],
                           stdout=subprocess.PIPE, stderr=subprocess.STDOUT, universal_newlines=True)
        self.assertEqual(r.returncode, 0, r.stdout)


@unittest.skipUnless(shutil.which("pwsh"), "PowerShell (pwsh) is not installed")
class PowerShellScripts(_Base):
    def pwsh(self, script, *args):
        # The whole environment: on Windows pwsh needs SystemRoot and the like.
        return self.run_script(["pwsh", "-NoProfile", "-NonInteractive", "-File", os.path.join(SCRIPTS, script)]
                               + list(args), env=dict(os.environ, **self.env(PATH=self.bin + os.pathsep + os.environ.get("PATH", ""))))

    def test_install_pc(self):
        self.fake_uv()
        r = self.pwsh("install-pc.ps1", "-DryRun")
        self.assertEqual(r.returncode, 0, r.stdout)
        self.assertIn("tool install --force --compile-bytecode --python 3.12 canworks @ %s/releases/download/"
                      "deploy-v1.2.3/canworks-1.2.3-py3-none-any.whl" % self.repo_url, r.stdout)

    def test_install_pc_version_and_uninstall(self):
        self.fake_uv()
        r = self.pwsh("install-pc.ps1", "-DryRun", "-Version", "0.9.0")
        self.assertIn("deploy-v0.9.0/canworks-0.9.0-py3-none-any.whl", r.stdout)
        r = self.pwsh("install-pc.ps1", "-DryRun", "-Uninstall")
        self.assertEqual(r.returncode, 0, r.stdout)
        self.assertIn("tool uninstall canworks", r.stdout)

    def test_install_runtime_over_ssh(self):
        r = self.pwsh("install-runtime.ps1", "-DryRun", "-Ssh", "pi@rpi.local", "-Port", "2222",
                      "-Options", "--with-link")
        self.assertEqual(r.returncode, 0, r.stdout)
        self.assertIn("ssh -t -p 2222 pi@rpi.local", r.stdout)
        self.assertIn("'https://raw.example/canworks/deploy-v1.2.3/scripts/install-runtime.sh' | sudo bash -s -- "
                      "--version '1.2.3' '--with-link'", r.stdout)


if __name__ == "__main__":
    unittest.main()
