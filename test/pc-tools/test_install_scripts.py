"""The one-line installers (scripts/install-pc.sh, install-pc.ps1,
install-runtime.sh, install-runtime.ps1, install-bridge.sh, install-bridge.ps1):
release lookup, options and the commands they would run, against a local
stand-in for GitHub, without network access or installing anything
(--dry-run). install-bridge.sh from a checkout also runs for real into
temporary folders with a stub bridge and a stub systemctl."""

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

@POSIX_ONLY
class InstallBridgeSh(_Base):
    """install-bridge.sh run as from GitHub: the script alone, outside a checkout."""

    def setUp(self):
        super().setUp()
        self.script = os.path.join(self.tmp, "install-bridge.sh")
        shutil.copy(os.path.join(SCRIPTS, "install-bridge.sh"), self.script)
        self.cfg = os.path.join(self.tmp, "line 1")
        os.makedirs(os.path.join(self.cfg, "old"))
        for name in ("canworks.json", "dio16.eds"):
            open(os.path.join(self.cfg, name), "w").close()

    def would_run(self, out):
        return [l for l in out.splitlines() if l.startswith("would run:")]

    def test_on_the_device(self):
        r = self.run_script(["bash", self.script, "--dry-run", "--without-j1939", "--prefix", "/opt/my bridge"])
        self.assertEqual(r.returncode, 0, r.stdout)
        self.assertIn("Installing canworks-bridge 1.2.3", r.stdout)
        self.assertIn("would download: %s/archive/refs/tags/deploy-v1.2.3.tar.gz" % self.repo_url, r.stdout)
        self.assertIn("install-bridge.sh --without-j1939 --prefix /opt/my\\ bridge", r.stdout)
        self.assertIn("/owner/canworks/releases/latest", _Releases.seen)

    def test_given_version_and_uninstall(self):
        r = self.run_script(["bash", self.script, "--dry-run", "--version", "deploy-v0.9.0", "--uninstall", "--purge"])
        self.assertEqual(r.returncode, 0, r.stdout)
        self.assertIn("deploy-v0.9.0.tar.gz", r.stdout)
        self.assertIn("install-bridge.sh --uninstall --purge", r.stdout)
        self.assertEqual(_Releases.seen, [])

    def test_instance_on_the_device(self):
        r = self.run_script(["bash", self.script, "--dry-run", "--instance", "line1", "--config", self.cfg])
        self.assertEqual(r.returncode, 0, r.stdout)
        self.assertIn("--instance line1 --config %s" % self.cfg.replace(" ", "\\ "), r.stdout)

    def test_over_ssh(self):
        r = self.run_script(["bash", self.script, "--dry-run", "--ssh", "pi@rpi.local", "--port", "2222",
                             "--identity", "/k/id", "--with-link", "line1"])
        self.assertEqual(r.returncode, 0, r.stdout)
        self.assertIn("Installing canworks-bridge 1.2.3 on pi@rpi.local", r.stdout)
        lines = self.would_run(r.stdout)
        self.assertEqual(len(lines), 1, r.stdout)
        self.assertIn("ssh -t -p 2222 -i /k/id pi@rpi.local", lines[0])
        # The device fetches the script of the release it installs, pinned to it.
        self.assertIn("https://raw.example/canworks/deploy-v1.2.3/scripts/install-bridge.sh", lines[0])
        self.assertIn("sudo bash -s -- --version 1.2.3 --with-link line1", lines[0])

    def test_over_ssh_with_config(self):
        r = self.run_script(["bash", self.script, "--dry-run", "--ssh", "pi@rpi.local", "--port", "2222",
                             "--instance", "line1", "--config", self.cfg])
        self.assertEqual(r.returncode, 0, r.stdout)
        mk, scp, install = self.would_run(r.stdout)
        self.assertIn("ssh -p 2222 pi@rpi.local mktemp -d /tmp/canworks-bridge-upload.XXXXXX", mk)
        self.assertTrue(scp.startswith("would run: scp -P 2222 "), scp)
        self.assertIn(os.path.join(self.cfg, "canworks.json"), scp)
        self.assertIn(os.path.join(self.cfg, "dio16.eds"), scp)
        self.assertNotIn(os.path.join(self.cfg, "old"), scp, "subfolders stay on the PC")
        self.assertIn("ssh -t -p 2222 pi@rpi.local", install)
        self.assertIn("--instance line1 --config", install)
        self.assertIn("--remove-config-dir", install)

    def test_refusals(self):
        for argv, message in (
                (["--instance", "line1"], "--instance NAME and --config DIR go together"),
                (["--config", self.cfg], "--instance NAME and --config DIR go together"),
                (["--instance", "a/b", "--config", self.cfg], "letters, digits"),
                (["--instance", "x", "--config", self.tmp], "has no canworks.json"),
                (["--port", "22"], "--port and --identity need --ssh"),
                (["--remove-config-dir", "--instance", "x", "--config", self.cfg], "only for an uploaded config")):
            r = self.run_script(["bash", self.script, "--dry-run"] + argv)
            self.assertNotEqual(r.returncode, 0, argv)
            self.assertIn(message, r.stdout, argv)
        self.assertEqual(_Releases.seen, [], "nothing is looked up before the checks")

    @unittest.skipIf(getattr(os, "geteuid", lambda: -1)() == 0, "runs as root here; the refusal is for non-root users")
    def test_not_root(self):
        r = self.run_script(["bash", self.script])
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("run it as root", r.stdout)
        self.assertIn("install-bridge.sh | sudo bash", r.stdout)
        self.assertEqual(_Releases.seen, [], "nothing is downloaded before the root check")


@POSIX_ONLY
@unittest.skipUnless(sys.platform.startswith("linux"), "install-bridge.sh installs on Linux")
class InstallBridgeCheckout(unittest.TestCase):
    """install-bridge.sh from this checkout, for real, into temporary folders:
    a stub bridge (--binary), a stub systemctl that records its calls."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp)
        self.log = os.path.join(self.tmp, "systemctl.log")
        self.active = os.path.join(self.tmp, "active")
        open(self.active, "w").close()
        open(self.log, "w").close()
        self.systemctl = self.stub("systemctl", 'echo "$*" >> %s\n'
                                   'case "$*" in *--state=active*) cat %s ;; esac\nexit 0' % (self.log, self.active))
        # Accepts a config unless its folder has a file named BAD.
        self.bridge = self.stub("canworks-bridge", '[ "$1" = --config ] || exit 2\n'
                                'if [ -e "$(dirname "$2")/BAD" ]; then echo "config: dio16.eds is missing"; exit 1; fi\n'
                                'echo "config accepted"')
        self.conf = os.path.join(self.tmp, "etc")
        self.default = os.path.join(self.tmp, "opt-canworks")
        self.fallback = os.path.join(self.tmp, "opt-bridge")

    def stub(self, name, body):
        path = os.path.join(self.tmp, name)
        with open(path, "w") as f:
            f.write("#!/bin/sh\n" + body + "\n")
        os.chmod(path, 0o755)
        return path

    def install(self, *args):
        env = dict(os.environ, CANWORKS_UNIT_DIR=os.path.join(self.tmp, "units"), CANWORKS_BRIDGE_CONF_DIR=self.conf,
                   CANWORKS_SYSTEMCTL=self.systemctl, CANWORKS_MODULES_LOAD_DIR=os.path.join(self.tmp, "modules"),
                   CANWORKS_MODPROBE="true", CANWORKS_DEFAULT_PREFIX=self.default,
                   CANWORKS_FALLBACK_PREFIX=self.fallback)
        return subprocess.run(["bash", os.path.join(SCRIPTS, "install-bridge.sh"), "--no-deps", "--without-canopen",
                               "--binary", self.bridge] + list(args),
                              stdout=subprocess.PIPE, stderr=subprocess.STDOUT, universal_newlines=True, env=env,
                              timeout=60)

    def calls(self):
        with open(self.log) as f:
            return f.read().splitlines()

    def config(self, *names):
        d = tempfile.mkdtemp(dir=self.tmp)
        for name in ("canworks.json", "dio16.eds") + names:
            with open(os.path.join(d, name), "w") as f:
                f.write(name)
        return d

    def test_update_restarts_running_bridges(self):
        with open(self.active, "w") as f:
            f.write("canworks-bridge@press.service loaded active running canworks Modbus TCP bridge (press)\n")
        r = self.install()
        self.assertEqual(r.returncode, 0, r.stdout)
        self.assertTrue(os.access(os.path.join(self.default, "bin", "canworks-bridge"), os.X_OK))
        self.assertIn("restart canworks-bridge@press.service", self.calls())
        self.assertIn("Restarted canworks-bridge@press.service", r.stdout)

    def test_instance(self):
        cfg = self.config()
        r = self.install("--instance", "line1", "--config", cfg)
        self.assertEqual(r.returncode, 0, r.stdout)
        self.assertEqual(sorted(os.listdir(os.path.join(self.conf, "line1"))), ["canworks.json", "dio16.eds"])
        calls = self.calls()
        self.assertIn("enable canworks-bridge@line1.service", calls)
        self.assertIn("restart canworks-bridge@line1.service", calls)
        self.assertIn("config accepted", r.stdout)

    def test_rejected_config_changes_nothing(self):
        cfg = self.config("BAD")
        r = self.install("--instance", "line1", "--config", cfg)
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("dio16.eds is missing", r.stdout)
        self.assertIn("unchanged", r.stdout)
        self.assertFalse(os.path.exists(os.path.join(self.conf, "line1")))
        self.assertFalse([c for c in self.calls() if "line1" in c])

    def test_uploaded_config_is_removed(self):
        up = tempfile.mkdtemp(prefix="canworks-bridge-upload.", dir="/tmp")
        self.addCleanup(shutil.rmtree, up, True)
        for name in ("canworks.json", "dio16.eds"):
            open(os.path.join(up, name), "w").close()
        r = self.install("--instance", "line1", "--config", up, "--remove-config-dir")
        self.assertEqual(r.returncode, 0, r.stdout)
        self.assertFalse(os.path.exists(up))
        self.assertTrue(os.path.exists(os.path.join(self.conf, "line1", "canworks.json")))

    def docker_runtime_prefix(self):
        """The default prefix as a Docker runtime leaves it: a venv of another Python."""
        os.makedirs(os.path.join(self.default, "venv", "bin"))
        with open(os.path.join(self.default, "venv", "pyvenv.cfg"), "w") as f:
            f.write("home = /usr/local/bin\nversion = 3.99.0\n")
        self.stub(os.path.join("opt-canworks", "venv", "bin", "python"), "echo 3.1")

    def test_prefix_next_to_a_docker_runtime(self):
        self.docker_runtime_prefix()
        r = self.install()
        self.assertEqual(r.returncode, 0, r.stdout)
        self.assertIn("installing the bridge into %s" % self.fallback, r.stdout)
        self.assertTrue(os.path.exists(os.path.join(self.fallback, "bin", "canworks-bridge")))
        self.assertFalse(os.path.exists(os.path.join(self.default, "bin")))
        # An update and the uninstall find it there.
        r = self.install()
        self.assertIn("Using the bridge installed in %s" % self.fallback, r.stdout)
        r = self.install("--uninstall")
        self.assertEqual(r.returncode, 0, r.stdout)
        self.assertFalse(os.path.exists(os.path.join(self.fallback, "bin", "canworks-bridge")))

    def test_explicit_prefix_still_refused(self):
        self.docker_runtime_prefix()
        r = self.install("--prefix", self.default)
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("--prefix %s" % self.fallback, r.stdout)


class Shellcheck(unittest.TestCase):
    def test_scripts(self):
        tool = shutil.which("shellcheck")
        if not tool:
            # Linux runners ship shellcheck; macOS and Windows runners do not.
            if IN_CI and sys.platform.startswith("linux"):
                self.fail("shellcheck is missing on the Linux CI runner")
            self.skipTest("shellcheck is not installed")
        r = subprocess.run([tool] + [os.path.join(SCRIPTS, name) for name in
                                    ("install-pc.sh", "install-runtime.sh", "install-bridge.sh")],
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

    def test_install_bridge_over_ssh(self):
        r = self.pwsh("install-bridge.ps1", "-DryRun", "-Ssh", "pi@rpi.local", "-Port", "2222",
                      "-Options", "--without-j1939")
        self.assertEqual(r.returncode, 0, r.stdout)
        self.assertIn("installing canworks-bridge 1.2.3 on pi@rpi.local", r.stdout)
        self.assertIn("ssh -t -p 2222 pi@rpi.local", r.stdout)
        self.assertIn("'https://raw.example/canworks/deploy-v1.2.3/scripts/install-bridge.sh' | sudo bash -s -- "
                      "'--version' '1.2.3' '--without-j1939'", r.stdout)

    def test_install_bridge_with_config(self):
        cfg = os.path.join(self.tmp, "line 1")
        os.makedirs(os.path.join(cfg, "old"))
        for name in ("canworks.json", "dio16.eds"):
            open(os.path.join(cfg, name), "w").close()
        r = self.pwsh("install-bridge.ps1", "-DryRun", "-Ssh", "pi@rpi.local", "-Identity", "/k/id",
                      "-Instance", "line1", "-Config", cfg)
        self.assertEqual(r.returncode, 0, r.stdout)
        runs = [l for l in r.stdout.splitlines() if l.startswith("would run:")]
        self.assertEqual(len(runs), 3, r.stdout)
        self.assertIn("ssh -i /k/id pi@rpi.local", runs[0])
        self.assertIn("mktemp -d /tmp/canworks-bridge-upload.XXXXXX", runs[0])
        self.assertIn("scp -i /k/id", runs[1])
        self.assertIn(os.path.join(cfg, "dio16.eds"), runs[1])
        self.assertNotIn(os.path.join(cfg, "old"), runs[1])
        self.assertIn("'--instance' 'line1' '--config'", runs[2])
        self.assertIn("'--remove-config-dir'", runs[2])

    def test_install_bridge_refusals(self):
        r = self.pwsh("install-bridge.ps1", "-DryRun", "-Ssh", "pi@rpi.local", "-Instance", "line1")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("-Instance NAME and -Config DIR go together", r.stdout)
        self.assertEqual(_Releases.seen, [])


if __name__ == "__main__":
    unittest.main()
