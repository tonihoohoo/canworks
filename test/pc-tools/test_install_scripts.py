"""The one-line installers (scripts/install-pc.sh, install-pc.ps1,
install-runtime.sh, install-runtime.ps1, install-bridge.sh, install-bridge.ps1):
release lookup, options and the commands they would run, against a local
stand-in for GitHub, without network access or installing anything
(--dry-run). install-bridge.sh from a checkout also runs for real into
temporary folders with a stub bridge and a stub systemctl."""

import hashlib
import http.server
import io
import os
import re
import shutil
import socket
import stat
import subprocess
import sys
import tempfile
import threading
import unittest
import zipfile

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
SCRIPTS = os.path.join(REPO, "scripts")
IN_CI = bool(os.environ.get("CI"))


class _Releases(http.server.BaseHTTPRequestHandler):
    """releases/latest redirects to releases/tag/deploy-v1.2.3, like GitHub;
    `files` are served as they are (a stand-in uv installer)."""
    seen = []
    files = {}

    def do_GET(self):
        self.seen.append(self.path)
        if self.path in self.files:
            body = self.files[self.path]
            body = body if isinstance(body, bytes) else body.encode()
            self.send_response(200)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        elif self.path.endswith("/releases/latest"):
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
        _Releases.files = {}
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp)
        self.home = os.path.join(self.tmp, "home")
        self.bin = os.path.join(self.tmp, "bin")
        os.makedirs(self.home)
        os.makedirs(self.bin)

    def fake_uv(self, listed=None, python="3.14.8", uv_version=None, self_update_rc=0):
        """A uv on PATH that only answers 'tool dir --bin', 'tool list' with
        `listed` (an installed version of canworks, on `python`) when given,
        '--version' with `uv_version` when given, and 'self update' with
        exit code `self_update_rc`."""
        path = os.path.join(self.bin, "uv")
        listing = ('[ "$1 $2" = "tool list" ] && echo "canworks v%s [CPython %s]" && echo "- canworks-config"\n'
                   % (listed, python) if listed else "")
        version = '[ "$1" = "--version" ] && echo "uv %s (x86_64-unknown-linux-gnu)"\n' % uv_version if uv_version else ""
        update = '[ "$1 $2" = "self update" ] && exit %d\n' % self_update_rc
        with open(path, "w") as f:
            f.write('#!/bin/sh\n[ "$1 $2 $3" = "tool dir --bin" ] && echo "%s/uvbin"\n%s%s%sexit 0\n'
                    % (self.tmp, listing, version, update))
        os.chmod(path, os.stat(path).st_mode | stat.S_IEXEC)
        if os.name == "nt":
            # PowerShell on Windows runs uv.cmd for "uv".
            with open(path + ".cmd", "w") as f:
                f.write('@echo off\r\nif "%%1 %%2 %%3"=="tool dir --bin" echo %s\\uvbin\r\n' % self.tmp
                        + ('if "%%1 %%2"=="tool list" echo canworks v%s [CPython %s]\r\n' % (listed, python)
                           if listed else "")
                        + ('if "%%1"=="--version" echo uv %s (x86_64-pc-windows-msvc)\r\n' % uv_version
                           if uv_version else "")
                        + 'if "%%1 %%2"=="self update" exit /b %d\r\n' % self_update_rc
                        + "exit /b 0\r\n")

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
        self.assertRegex(r.stdout, r"tool install --force --compile-bytecode --python 3\.14 --overrides \S+overrides\.txt "
                         + re.escape("canworks @ %s/releases/download/deploy-v1.2.3/canworks-1.2.3-py3-none-any.whl"
                                     % self.repo_url))
        self.assertNotIn("uv.example", r.stdout)
        self.assertIn("/owner/canworks/releases/latest", _Releases.seen)
        # The app shortcut, after the install.
        self.assertIn("would run: %s/uvbin/canworks-config --create-shortcut" % self.tmp, r.stdout)
        self.assertLess(r.stdout.index("tool install"), r.stdout.index("--create-shortcut"))

    # skip-reinstall-faster-start: the newest version already installed.
    def test_up_to_date_skips(self):
        self.fake_uv(listed="1.2.3")
        r = self.run_script(["sh", self.script, "--dry-run"])
        self.assertEqual(r.returncode, 0, r.stdout)
        self.assertIn("canworks 1.2.3 is already installed; --force installs it again", r.stdout)
        self.assertNotIn("tool install", r.stdout)
        self.assertNotIn("shortcut", r.stdout)

    # newest-python: the same version on an older Python is installed again.
    def test_same_version_older_python_installs(self):
        self.fake_uv(listed="1.2.3", python="3.12.15")
        r = self.run_script(["sh", self.script, "--dry-run"])
        self.assertEqual(r.returncode, 0, r.stdout)
        self.assertIn("installing canworks 1.2.3 again on Python 3.14 (it was on 3.12)", r.stdout)
        self.assertIn("tool install --force --compile-bytecode --python 3.14", r.stdout)
        self.assertIn("--create-shortcut", r.stdout)

    def test_given_python_version_compared(self):
        self.fake_uv(listed="1.2.3", python="3.14.8")
        r = self.run_script(["sh", self.script, "--dry-run", "--python", "3.15"])
        self.assertIn("tool install --force --compile-bytecode --python 3.15", r.stdout)
        r = self.run_script(["sh", self.script, "--dry-run", "--python", "3.14.2"])
        self.assertIn("1.2.3 is already installed", r.stdout)

    def test_python_path_compares_version_only(self):
        self.fake_uv(listed="1.2.3", python="3.12.15")
        r = self.run_script(["sh", self.script, "--dry-run", "--python", "/usr/bin/python3"])
        self.assertEqual(r.returncode, 0, r.stdout)
        self.assertIn("1.2.3 is already installed", r.stdout)

    def test_old_uv_updated(self):
        self.fake_uv(uv_version="0.8.22")
        r = self.run_script(["sh", self.script, "--dry-run"])
        self.assertEqual(r.returncode, 0, r.stdout)
        self.assertIn("uv 0.8.22 is older than 0.9.0; updating it", r.stdout)
        self.assertLess(r.stdout.index("self update"), r.stdout.index("tool install"))

    def test_new_uv_not_updated(self):
        for version in ("0.9.0", "0.13.4", "1.0"):
            self.fake_uv(uv_version=version)
            r = self.run_script(["sh", self.script, "--dry-run"])
            self.assertEqual(r.returncode, 0, r.stdout)
            self.assertNotIn("self update", r.stdout)

    def test_old_uv_update_fails(self):
        self.fake_uv(uv_version="0.8.22", self_update_rc=1)
        r = self.run_script(["sh", self.script])
        self.assertNotEqual(r.returncode, 0, r.stdout)
        self.assertIn("could not update uv 0.8.22; update it with the tool that installed it", r.stdout)
        self.assertNotIn("installing canworks", r.stdout)

    def test_older_version_installs(self):
        self.fake_uv(listed="1.2.2")
        r = self.run_script(["sh", self.script, "--dry-run"])
        self.assertEqual(r.returncode, 0, r.stdout)
        self.assertIn("tool install --force", r.stdout)

    def test_force_installs_same_version(self):
        self.fake_uv(listed="1.2.3")
        r = self.run_script(["sh", self.script, "--dry-run", "--force"])
        self.assertEqual(r.returncode, 0, r.stdout)
        self.assertIn("tool install --force", r.stdout)
        self.assertIn("--create-shortcut", r.stdout)

    def test_no_shortcut(self):
        self.fake_uv()
        r = self.run_script(["sh", self.script, "--dry-run", "--no-shortcut"])
        self.assertEqual(r.returncode, 0, r.stdout)
        self.assertIn("tool install", r.stdout)
        self.assertNotIn("shortcut", r.stdout)

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
        self.assertRegex(r.stdout, r"tool install --force --compile-bytecode --python 3\.13 --overrides \S+ "
                         + re.escape(wheel))
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
        # The shortcut goes first, while canworks-config is still there.
        self.assertIn("would run: %s/uvbin/canworks-config --remove-shortcut" % self.tmp, r.stdout)
        self.assertLess(r.stdout.index("--remove-shortcut"), r.stdout.index("tool uninstall"))
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

    # A real run with a stand-in uv (configurator-survive-sleep): it records
    # what it was given, and warns as uv does when its bin folder is not on
    # PATH; the tools it "installs" are stubs.
    def stub_uv(self, folder):
        self.log = os.path.join(self.tmp, "uv-log")
        os.makedirs(self.log, exist_ok=True)
        uvbin = os.path.join(self.tmp, "uvbin")
        os.makedirs(uvbin, exist_ok=True)
        for name in ("canworks-deploy", "canworks-config"):
            path = os.path.join(uvbin, name)
            with open(path, "w") as f:
                f.write("#!/bin/sh\necho %s \"$@\" >> %s/tools\n" % (name, self.log))
            os.chmod(path, 0o755)
        os.makedirs(folder, exist_ok=True)
        path = os.path.join(folder, "uv")
        with open(path, "w") as f:
            f.write("""#!/bin/sh
log=%(log)s
case "$1 $2" in
    "tool dir") echo %(uvbin)s ;;
    "tool install")
        echo "$*" > "$log/args"
        prev=""
        for a in "$@"; do
            [ "$prev" = --overrides ] && cp "$a" "$log/overrides"
            prev=$a
        done
        case ":$PATH:" in
            *":%(uvbin)s:"*) ;;
            *) echo "warning: \\`%(uvbin)s\\` is not on your PATH. To use installed tools, run \\`uv tool update-shell\\`." >&2 ;;
        esac ;;
    "tool update-shell") echo update-shell >> "$log/calls" ;;
esac
exit 0
""" % {"log": self.log, "uvbin": uvbin})
        os.chmod(path, 0o755)

    def read_log(self, name):
        with open(os.path.join(self.log, name)) as f:
            return f.read()

    def test_only_runtime_dependencies(self):
        self.stub_uv(self.bin)
        tmpdir = os.path.join(self.tmp, "t")
        os.makedirs(tmpdir)
        r = self.run_script(["sh", self.script, "--version", "1.2.3"], env=self.env(TMPDIR=tmpdir))
        self.assertEqual(r.returncode, 0, r.stdout)
        self.assertIn("--overrides", self.read_log("args"))
        self.assertEqual(self.read_log("overrides").strip(), "pytest; sys_platform == 'never'")
        self.assertIn("canworks-deploy --version", self.read_log("tools"))
        self.assertEqual(os.listdir(tmpdir), [], "the overrides file is removed at the end")

    def test_no_uv_path_warning_over_ssh(self):
        # A non-login shell: uv's bin folder is not on PATH.
        self.stub_uv(self.bin)
        r = self.run_script(["sh", self.script, "--version", "1.2.3"])
        self.assertEqual(r.returncode, 0, r.stdout)
        self.assertNotIn("is not on your PATH", r.stdout)
        self.assertEqual(r.stdout.count("open a new terminal"), 1, r.stdout)
        self.assertIn("update-shell", self.read_log("calls"))

    def uv_installer(self, quiet_option):
        """A stand-in uv installer that puts the stub uv into ~/.local/bin and
        records its arguments; with or without a --quiet option."""
        local = os.path.join(self.home, ".local", "bin")
        self.stub_uv(os.path.join(self.tmp, "staged"))
        _Releases.files["/uv/install.sh"] = (
            "#!/bin/sh\n# usage: install.sh%s\n"
            "echo \"$*\" > %s/installer-args\nmkdir -p %s\ncp %s %s/uv\n"
            "[ \"$1\" = --qu\"\"iet ] || echo 'To add %s to your PATH, restart your shell'\n"
            % (" [--quiet]" if quiet_option else "", self.log, local, os.path.join(self.tmp, "staged", "uv"), local,
               local))
        return self.env(CANWORKS_UV_INSTALLER="http://127.0.0.1:%d/uv/install.sh" % self.server.server_address[1])

    def test_uv_installer_quiet(self):
        r = self.run_script(["sh", self.script, "--version", "1.2.3"], env=self.uv_installer(True))
        self.assertEqual(r.returncode, 0, r.stdout)
        self.assertEqual(self.read_log("installer-args").strip(), "--quiet")
        self.assertNotIn("to your PATH", r.stdout)
        self.assertNotIn("is not on your PATH", r.stdout)
        self.assertEqual(r.stdout.count("open a new terminal"), 1, r.stdout)

    def test_uv_installer_without_quiet(self):
        r = self.run_script(["sh", self.script, "--version", "1.2.3"], env=self.uv_installer(False))
        self.assertEqual(r.returncode, 0, r.stdout)
        self.assertEqual(self.read_log("installer-args").strip(), "")


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

    def test_docker_runtime_prefix_with_an_old_bridge_in_it(self):
        self.docker_runtime_prefix()
        os.makedirs(os.path.join(self.default, "bin"))
        old = self.stub(os.path.join("opt-canworks", "bin", "canworks-bridge"), "echo old")
        r = self.install()
        self.assertEqual(r.returncode, 0, r.stdout)
        self.assertIn("installing the bridge into %s" % self.fallback, r.stdout)
        self.assertTrue(os.path.exists(os.path.join(self.fallback, "bin", "canworks-bridge")))
        r = self.install("--uninstall")
        self.assertEqual(r.returncode, 0, r.stdout)
        self.assertFalse(os.path.exists(os.path.join(self.fallback, "bin", "canworks-bridge")))
        self.assertTrue(os.path.exists(old), "the runtime's prefix is not touched")

    def test_uninstall_keeps_the_runtimes_link(self):
        units = os.path.join(self.tmp, "units")
        link = os.path.join(self.tmp, "link")
        os.makedirs(units)
        os.makedirs(link)
        open(os.path.join(units, "canworks-link.service"), "w").close()
        with open(os.path.join(link, "link.json"), "w") as f:
            f.write('{\n  "config": "/opt/canworks/lib/canworks.json",\n  "port": 7533\n}\n')
        self.assertEqual(self.install().returncode, 0)
        os.environ["CANWORKS_LINK_DIR"] = link
        self.addCleanup(os.environ.pop, "CANWORKS_LINK_DIR")
        r = self.install("--uninstall", "--purge")
        self.assertEqual(r.returncode, 0, r.stdout)
        self.assertIn("remote link serves another config and stays", r.stdout)
        self.assertTrue(os.path.exists(os.path.join(units, "canworks-link.service")))
        self.assertTrue(os.path.exists(os.path.join(link, "link.json")))

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
        self.assertRegex(r.stdout, r"tool install --force --compile-bytecode --python 3\.14 --overrides \S+\.txt "
                         + re.escape("canworks @ %s/releases/download/deploy-v1.2.3/canworks-1.2.3-py3-none-any.whl"
                                     % self.repo_url))
        self.assertIn("canworks-config.exe --create-shortcut", r.stdout)
        r = self.pwsh("install-pc.ps1", "-DryRun", "-NoShortcut")
        self.assertEqual(r.returncode, 0, r.stdout)
        self.assertNotIn("shortcut", r.stdout)

    def test_install_pc_up_to_date(self):
        self.fake_uv(listed="1.2.3")
        r = self.pwsh("install-pc.ps1", "-DryRun")
        self.assertEqual(r.returncode, 0, r.stdout)
        self.assertIn("canworks 1.2.3 is already installed; -Force installs it again", r.stdout)
        self.assertNotIn("tool install", r.stdout)
        r = self.pwsh("install-pc.ps1", "-DryRun", "-Force")
        self.assertIn("tool install --force", r.stdout)
        self.fake_uv(listed="1.2.2")
        r = self.pwsh("install-pc.ps1", "-DryRun")
        self.assertIn("tool install --force", r.stdout)
        # newest-python: the same version on an older Python is installed again;
        # a path to a Python compares the version only.
        self.fake_uv(listed="1.2.3", python="3.12.15")
        r = self.pwsh("install-pc.ps1", "-DryRun")
        self.assertEqual(r.returncode, 0, r.stdout)
        self.assertIn("installing canworks 1.2.3 again on Python 3.14 (it was on 3.12)", r.stdout)
        self.assertIn("tool install --force --compile-bytecode --python 3.14", r.stdout)
        r = self.pwsh("install-pc.ps1", "-DryRun", "-Python", "C:\\Python312\\python.exe")
        self.assertIn("1.2.3 is already installed", r.stdout)

    def test_install_pc_old_uv(self):
        self.fake_uv(uv_version="0.8.22")
        r = self.pwsh("install-pc.ps1", "-DryRun")
        self.assertEqual(r.returncode, 0, r.stdout)
        self.assertIn("uv 0.8.22 is older than 0.9.0; updating it", r.stdout)
        self.assertLess(r.stdout.index("self update"), r.stdout.index("tool install"))
        self.fake_uv(uv_version="0.13.4")
        r = self.pwsh("install-pc.ps1", "-DryRun")
        self.assertNotIn("self update", r.stdout)
        self.fake_uv(uv_version="0.8.22", self_update_rc=1)
        r = self.pwsh("install-pc.ps1", "-NoShortcut")
        self.assertNotEqual(r.returncode, 0, r.stdout)
        # PowerShell wraps the error to the console width: short pieces only.
        self.assertIn("could not update uv 0.8.22", r.stdout)
        self.assertIn("winget upgrade astral-sh.uv", r.stdout)
        self.assertNotIn("installing canworks", r.stdout)

    def test_install_pc_version_and_uninstall(self):
        self.fake_uv()
        r = self.pwsh("install-pc.ps1", "-DryRun", "-Version", "0.9.0")
        self.assertIn("deploy-v0.9.0/canworks-0.9.0-py3-none-any.whl", r.stdout)
        r = self.pwsh("install-pc.ps1", "-DryRun", "-Uninstall")
        self.assertEqual(r.returncode, 0, r.stdout)
        self.assertIn("tool uninstall canworks", r.stdout)
        self.assertLess(r.stdout.index("canworks-config.exe --remove-shortcut"), r.stdout.index("tool uninstall"))

    # uv from its release zip (windows-installer-defender): a stand-in zip and
    # .sha256 on the local server, and a PATH without any uv.
    def path_without_uv(self):
        dirs = [d for d in os.environ.get("PATH", "").split(os.pathsep)
                if d and not any(os.path.exists(os.path.join(d, n)) for n in ("uv", "uv.exe"))]
        return os.pathsep.join(dirs)

    def serve_uv(self, arch="x86_64", checksum=None):
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as z:
            for name in ("uv.exe", "uvx.exe", "uvw.exe"):
                z.writestr(name, "stand-in " + name)
        data = buf.getvalue()
        path = "/uv/uv-%s-pc-windows-msvc.zip" % arch
        _Releases.files[path] = data
        _Releases.files[path + ".sha256"] = "%s *uv-%s-pc-windows-msvc.zip\n" % (
            checksum or hashlib.sha256(data).hexdigest(), arch)
        return self.repo_url.replace("/owner/canworks", "/uv")

    def pwsh_without_uv(self, *args, **extra):
        env = dict(os.environ, **self.env(PATH=self.path_without_uv()))
        env.update(extra)
        return self.run_script(["pwsh", "-NoProfile", "-NonInteractive", "-File", os.path.join(SCRIPTS, "install-pc.ps1")]
                               + list(args), env=env)

    def local_bin(self):
        return os.path.join(self.home, ".local", "bin")

    def test_install_pc_uv_from_zip(self):
        r = self.pwsh_without_uv(CANWORKS_UV_DOWNLOAD=self.serve_uv())
        self.assertIn("installing uv from", r.stdout)
        for name in ("uv.exe", "uvx.exe", "uvw.exe"):
            with open(os.path.join(self.local_bin(), name)) as f:
                self.assertEqual(f.read(), "stand-in " + name)
        self.assertIn("/uv/uv-x86_64-pc-windows-msvc.zip.sha256", _Releases.seen)

    def test_install_pc_uv_checksum_mismatch(self):
        r = self.pwsh_without_uv(CANWORKS_UV_DOWNLOAD=self.serve_uv(checksum="0" * 64))
        self.assertNotEqual(r.returncode, 0, r.stdout)
        self.assertIn("did not match its checksum", r.stdout)
        self.assertFalse(os.path.exists(os.path.join(self.local_bin(), "uv.exe")))

    def test_install_pc_uv_arm64(self):
        r = self.pwsh_without_uv("-DryRun", CANWORKS_UV_DOWNLOAD="https://uv.example/dl", PROCESSOR_ARCHITECTURE="ARM64")
        self.assertEqual(r.returncode, 0, r.stdout)
        self.assertIn("would download: https://uv.example/dl/uv-aarch64-pc-windows-msvc.zip", r.stdout)
        self.assertEqual(_Releases.seen.count("/uv/uv-aarch64-pc-windows-msvc.zip"), 0)

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
        # PowerShell gives the long form of a Windows path that Python may have in its short (8.3) form.
        self.assertIn(os.sep + "dio16.eds", runs[1])
        self.assertIn(os.sep + "canworks.json", runs[1])
        self.assertNotIn(os.sep + "old", runs[1])
        self.assertIn("'--instance' 'line1' '--config'", runs[2])
        self.assertIn("'--remove-config-dir'", runs[2])

    def test_install_bridge_refusals(self):
        r = self.pwsh("install-bridge.ps1", "-DryRun", "-Ssh", "pi@rpi.local", "-Instance", "line1")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("-Instance NAME and -Config DIR go together", r.stdout)
        self.assertEqual(_Releases.seen, [])


# windows-installer-defender: what antivirus products flag in malicious
# PowerShell stays out of the Windows scripts and the documented lines.
_SCRIPT_PATTERNS = [
    (r"\biex\b|Invoke-Expression", "runs a string as code"),
    (r"scriptblock\]::Create", "builds a script block from text"),
    (r"-EncodedCommand|-enc\b", "passes encoded commands"),
    (r"ExecutionPolicy\s+Bypass", "switches the execution policy off"),
    (r"(^|[\s&(;|])(powershell|pwsh)(\.exe)?\s", "starts another PowerShell"),
]
_LINE_PATTERNS = [
    (r"\|\s*iex\b|Invoke-Expression", "pipes into iex"),
    (r"scriptblock\]::Create", "builds a script block from text"),
    (r"ExecutionPolicy\s+Bypass", "switches the execution policy off"),
]


class WindowsPatterns(unittest.TestCase):
    def test_scripts(self):
        for name in sorted(os.listdir(SCRIPTS)):
            if not name.endswith(".ps1"):
                continue
            with open(os.path.join(SCRIPTS, name), encoding="utf-8") as f:
                for number, line in enumerate(f, 1):
                    code = line.split("#", 1)[0]
                    for pattern, why in _SCRIPT_PATTERNS:
                        self.assertIsNone(re.search(pattern, code, re.I),
                                          "scripts/%s:%d %s: %s" % (name, number, why, line.strip()))

    def test_documented_windows_lines(self):
        docs = os.path.join(REPO, "docs")
        files = ["README.md", os.path.join("tools", "deploy", "release-notes.md")] + [
            os.path.join("docs", n) for n in sorted(os.listdir(docs)) if n.endswith(".md")]
        for rel in files:
            with open(os.path.join(REPO, rel), encoding="utf-8") as f:
                for number, line in enumerate(f, 1):
                    if not re.search(r"\.ps1|powershell", line, re.I):
                        continue
                    for pattern, why in _LINE_PATTERNS:
                        self.assertIsNone(re.search(pattern, line, re.I),
                                          "%s:%d %s" % (rel, number, why))


if __name__ == "__main__":
    unittest.main()
