"""scripts/install-stock.sh in Docker mode (canopen-docker-install), with a
stub `docker` on PATH, and scripts/docker_spec.py.

    sudo python3 -m unittest discover -s test/docker -v

Root is needed because the script refuses to edit the runtime spec otherwise.
The real image build runs in CI's Docker job (test/docker/run.sh).
"""

import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import textwrap
import unittest

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
SCRIPT = os.path.join(REPO, "scripts", "install-stock.sh")
sys.path.insert(0, os.path.join(REPO, "scripts"))
import docker_spec  # noqa: E402

# What upstream's install-docker.sh writes (write_spec), byte for byte.
UPSTREAM_SPEC = textwrap.dedent("""\
    {
      "repository": "ghcr.io/autonomy-logic/openplc-runtime",
      "version": "v4.2.4",
      "dataDir": "/var/lib/openplc-runtime",
      "bootloaderPort": 8445
    }
    """)
SPEC_WITH_MOUNT = textwrap.dedent("""\
    {
      "repository": "ghcr.io/autonomy-logic/openplc-runtime",
      "version": "v4.2.4",
      "dataDir": "/var/lib/openplc-runtime",
      "bootloaderPort": 8445,
      "extraBinds": ["/lib/modules:/lib/modules:ro"],
      "extraEnv": ["TZ=Europe/Helsinki"]
    }
    """)

STUB_DOCKER = textwrap.dedent("""\
    #!/bin/sh
    # Logs each call; `run` stands in for the in-image build.
    echo "$*" >> "$DOCKER_LOG"
    case "$1" in
        image) [ "$2" = inspect ] && { echo sha256:feed; exit 0; } ;;
        ps) printf '%s' "$STUB_CONTAINERS"; exit 0 ;;
        inspect) echo ghcr.io/autonomy-logic/openplc-runtime:v4.2.4; exit 0 ;;
        run)
            [ -n "$STUB_RUN_FAILS" ] && exit 1
            mkdir -p "$STUB_PREFIX/lib/sitecustomize"
            echo so > "$STUB_PREFIX/lib/libcanworks_plugin.so"
            exit 0 ;;
    esac
    exit 0
    """)


class SpecTool(unittest.TestCase):
    BIND = "/opt/canworks:/opt/canworks"
    ENV = "PYTHONPATH=/opt/canworks/lib/sitecustomize"

    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="spec-")
        self.path = os.path.join(self.dir, "runtime-spec.json")

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def write(self, text):
        with open(self.path, "w") as f:
            f.write(text)
        os.chmod(self.path, 0o640)

    def read(self):
        with open(self.path) as f:
            return f.read()

    def tool(self, *args):
        return docker_spec.main([args[0], self.path] + list(args[1:]))

    def test_image(self):
        self.write(UPSTREAM_SPEC)
        self.assertEqual(docker_spec.image(docker_spec.load(self.path)),
                         "ghcr.io/autonomy-logic/openplc-runtime:v4.2.4")

    def test_add_once_and_remove_restores(self):
        self.write(UPSTREAM_SPEC)
        self.tool("add", self.BIND, self.ENV)
        self.tool("add", self.BIND, self.ENV)
        spec = json.loads(self.read())
        self.assertEqual(spec["extraBinds"], [self.BIND])
        self.assertEqual(spec["extraEnv"], [self.ENV])
        self.assertEqual(stat.S_IMODE(os.stat(self.path).st_mode), 0o640)
        self.tool("remove", self.BIND, self.ENV)
        self.assertEqual(self.read(), UPSTREAM_SPEC)

    def test_operator_entries_kept(self):
        self.write(SPEC_WITH_MOUNT)
        before = json.loads(SPEC_WITH_MOUNT)
        self.tool("add", self.BIND, self.ENV)
        spec = json.loads(self.read())
        self.assertEqual(list(spec), list(before))
        self.assertEqual(spec["extraBinds"], before["extraBinds"] + [self.BIND])
        self.assertEqual(spec["extraEnv"], before["extraEnv"] + [self.ENV])
        self.tool("remove", self.BIND, self.ENV)
        self.assertEqual(json.loads(self.read()), before)

    def test_unknown_layout_refused(self):
        self.write('{"image": "x"}\n')
        self.assertEqual(self.tool("add", self.BIND, self.ENV), 1)
        self.assertEqual(self.read(), '{"image": "x"}\n')

    def test_failed_write_keeps_the_old_spec(self):
        self.write(UPSTREAM_SPEC)
        real = os.replace

        def boom(*a):
            raise OSError("disk full")
        os.replace = boom
        try:
            with self.assertRaises(OSError):
                self.tool("add", self.BIND, self.ENV)
        finally:
            os.replace = real
        self.assertEqual(self.read(), UPSTREAM_SPEC)
        self.assertEqual(os.listdir(self.dir), ["runtime-spec.json"])


@unittest.skipUnless(os.geteuid() == 0, "needs root (sudo)")
class Installer(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="install-docker-")
        self.bin = os.path.join(self.dir, "bin")
        os.makedirs(self.bin)
        with open(os.path.join(self.bin, "docker"), "w") as f:
            f.write(STUB_DOCKER)
        os.chmod(os.path.join(self.bin, "docker"), 0o755)
        self.prefix = os.path.join(self.dir, "opt")
        self.spec = os.path.join(self.dir, "bootloader", "runtime-spec.json")
        os.makedirs(os.path.dirname(self.spec))
        self.log = os.path.join(self.dir, "docker.log")
        self.bind = "%s:/opt/canworks" % self.prefix
        self.env_entry = "PYTHONPATH=/opt/canworks/lib/sitecustomize"

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def run_script(self, *args, spec=True, **env):
        e = dict(os.environ, PATH=self.bin + os.pathsep + os.environ["PATH"], DOCKER_LOG=self.log,
                 STUB_PREFIX=self.prefix, STUB_CONTAINERS="",
                 OPENPLC_BOOTLOADER_SPEC=self.spec if spec else os.path.join(self.dir, "none.json"),
                 OPENPLC_SERVICE_FILE=os.path.join(self.dir, "no.service"))
        e.update(env)
        return subprocess.run(["bash", SCRIPT, "--prefix", self.prefix] + list(args), env=e,
                              capture_output=True, text=True)

    def calls(self):
        if not os.path.exists(self.log):
            return []
        with open(self.log) as f:
            return f.read().splitlines()

    def write_spec(self, text=UPSTREAM_SPEC):
        with open(self.spec, "w") as f:
            f.write(text)

    def read_spec(self):
        with open(self.spec) as f:
            return f.read()

    def test_install_reinstall_uninstall(self):
        self.write_spec()
        p = self.run_script()
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        spec = json.loads(self.read_spec())
        self.assertEqual(spec["extraBinds"], [self.bind])
        self.assertEqual(spec["extraEnv"], [self.env_entry])
        calls = self.calls()
        run = [c for c in calls if c.startswith("run ")]
        self.assertEqual(len(run), 1)
        self.assertIn("ghcr.io/autonomy-logic/openplc-runtime:v4.2.4 /src/scripts/install-stock.sh --in-image", run[0])
        self.assertIn("-v %s" % self.bind, run[0])
        self.assertIn("CANOPEN_IMAGE_ID=sha256:feed", run[0])
        # The PLC restart is announced before the container goes.
        self.assertIn("the PLC stops now", p.stdout)
        self.assertEqual(calls[-2:], ["rm -f openplc-runtime", "restart openplc-bootloader"])
        # Slave networks' saved parameters live on the bind-mounted prefix.
        self.assertTrue(os.path.isdir(os.path.join(self.prefix, "state")))

        p = self.run_script()
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        spec = json.loads(self.read_spec())
        self.assertEqual((spec["extraBinds"], spec["extraEnv"]), ([self.bind], [self.env_entry]))

        p = self.run_script("--uninstall")
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        self.assertEqual(self.read_spec(), UPSTREAM_SPEC)
        self.assertFalse(os.path.exists(os.path.join(self.prefix, "lib")))
        self.assertTrue(os.path.isdir(os.path.join(self.prefix, "state")))  # kept without --purge
        self.assertEqual(self.calls()[-2:], ["rm -f openplc-runtime", "restart openplc-bootloader"])

    def test_failed_build_changes_nothing(self):
        self.write_spec()
        p = self.run_script(STUB_RUN_FAILS="1")
        self.assertNotEqual(p.returncode, 0)
        self.assertEqual(self.read_spec(), UPSTREAM_SPEC)
        self.assertFalse(any(c.startswith(("rm ", "restart ")) for c in self.calls()))

    def test_no_editor_hook_refused(self):
        self.write_spec()
        p = self.run_script("--no-editor-hook")
        self.assertNotEqual(p.returncode, 0)
        self.assertIn("--no-editor-hook is not available", p.stderr)
        self.assertEqual(self.calls(), [])

    def test_unmanaged_container_refused_with_hint(self):
        p = self.run_script(spec=False, STUB_CONTAINERS="openplc-runtime\n")
        self.assertNotEqual(p.returncode, 0)
        self.assertIn("--docker-image ghcr.io/autonomy-logic/openplc-runtime:v4.2.4", p.stderr)
        self.assertFalse(any(c.startswith(("run ", "rm ", "restart ")) for c in self.calls()))

    def test_hand_run_container(self):
        p = self.run_script("--docker-image", "ghcr.io/autonomy-logic/openplc-runtime:v4.2.4", spec=False)
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        self.assertIn("-v %s -e %s" % (self.bind, self.env_entry), p.stdout)
        self.assertFalse(any(c.startswith(("rm ", "restart ")) for c in self.calls()))


if __name__ == "__main__":
    unittest.main()
