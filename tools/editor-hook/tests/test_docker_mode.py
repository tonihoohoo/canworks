"""The editor hook's Docker-mode duties (canopen-docker-install): the canopen
line across new runtime containers, the runtime version guard, and loading
through sitecustomize."""

import os
import shutil
import subprocess
import sys
import tempfile
import textwrap
import unittest

from openplc_canopen_hook import docker_mode

HOOK_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
DEFAULT_CONF = "modbus,./x.so,0,1,./modbus.json,\nethercat,./e.so,0,1,./e.json,\n"


class Base(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="docker-mode-")
        self.prefix = os.path.join(self.dir, "opt")
        os.makedirs(os.path.join(self.prefix, "lib"))
        self.rt = os.path.join(self.dir, "workdir")
        os.makedirs(self.rt)
        self.conf = os.path.join(self.rt, "plugins.conf")
        self.default = os.path.join(self.rt, "plugins_default.conf")
        with open(self.default, "w") as f:
            f.write(DEFAULT_CONF)

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def stamp(self, version):
        with open(os.path.join(self.prefix, "lib", "runtime-version"), "w") as f:
            f.write("%s\nghcr.io/autonomy-logic/openplc-runtime:%s\nsha256:abc\n" % (version, version))

    def enabled_line(self):
        lib = os.path.join(self.prefix, "lib")
        return "canopen,%s/libcanopen_plugin.so,1,1,%s/canopen.json," % (lib, lib)

    def text(self):
        with open(self.conf) as f:
            return f.read()

    def lines(self):
        with open(self.conf) as f:
            return f.read().splitlines()

    def canopen(self):
        return [l for l in self.lines() if l.startswith("canopen,")]


class AtStart(Base):
    def test_new_container_without_record_gets_a_disabled_line(self):
        self.stamp("v4.2.4")
        msgs = docker_mode.at_start(self.prefix, self.conf, self.default, "v4.2.4")
        self.assertEqual(self.canopen(), [docker_mode.disabled_line(self.prefix)])
        self.assertEqual(self.lines()[:2], DEFAULT_CONF.splitlines())
        self.assertIn("disabled canopen line", msgs[0][1])

    def test_new_container_restores_the_last_upload(self):
        self.stamp("v4.2.4")
        with open(self.conf, "w") as f:
            f.write(DEFAULT_CONF + self.enabled_line() + "\n")
        docker_mode.record(self.prefix, self.conf)
        os.remove(self.conf)  # the bootloader created a new container
        msgs = docker_mode.at_start(self.prefix, self.conf, self.default, "v4.2.4")
        self.assertEqual(self.canopen(), [self.enabled_line()])
        self.assertEqual(msgs[0][0], "INFO")

    def test_disabled_record_restored_disabled(self):
        self.stamp("v4.2.4")
        with open(self.conf, "w") as f:
            f.write(DEFAULT_CONF + docker_mode.disable(self.enabled_line()) + "\n")
        docker_mode.record(self.prefix, self.conf)
        with open(self.conf, "w") as f:
            f.write(DEFAULT_CONF)
        docker_mode.at_start(self.prefix, self.conf, self.default, "v4.2.4")
        self.assertEqual(self.canopen(), [docker_mode.disable(self.enabled_line())])

    def test_existing_line_left_alone(self):
        self.stamp("v4.2.4")
        with open(self.conf, "w") as f:
            f.write(DEFAULT_CONF + self.enabled_line() + "\n")
        before = self.text()
        self.assertEqual(docker_mode.at_start(self.prefix, self.conf, self.default, "v4.2.4"), [])
        self.assertEqual(self.text(), before)

    def test_version_change_keeps_canopen_off(self):
        self.stamp("v4.2.4")
        with open(self.conf, "w") as f:
            f.write(DEFAULT_CONF + self.enabled_line() + "\n")
        docker_mode.record(self.prefix, self.conf)
        os.remove(self.conf)
        msgs = docker_mode.at_start(self.prefix, self.conf, self.default, "v4.2.5")
        self.assertEqual(self.canopen(), [docker_mode.disable(self.enabled_line())])
        self.assertEqual(len(msgs), 1)
        level, text = msgs[0]
        self.assertEqual(level, "ERROR")
        self.assertIn("built for runtime v4.2.4 but the runtime is v4.2.5", text)
        self.assertIn("install-stock.sh", text)

    def test_no_stamp_keeps_canopen_off(self):
        msgs = docker_mode.at_start(self.prefix, self.conf, self.default, "v4.2.4")
        self.assertEqual(self.canopen(), [docker_mode.disabled_line(self.prefix)])
        self.assertEqual(msgs[0][0], "ERROR")


class AfterUpload(Base):
    def test_records_the_runtime_line(self):
        self.stamp("v4.2.4")
        with open(self.conf, "w") as f:
            f.write(DEFAULT_CONF + self.enabled_line() + "\n")
        self.assertEqual(docker_mode.after_upload(self.prefix, self.conf, "v4.2.4"), [])
        self.assertEqual(docker_mode.recorded(self.prefix), self.enabled_line())

    def test_mismatch_disables_what_the_upload_enabled(self):
        self.stamp("v4.2.4")
        with open(self.conf, "w") as f:
            f.write(DEFAULT_CONF + self.enabled_line() + "\n")
        msgs = docker_mode.after_upload(self.prefix, self.conf, "v4.2.5")
        self.assertEqual(self.canopen(), [docker_mode.disable(self.enabled_line())])
        self.assertIn("CANopen stays off", msgs[0][1])
        self.assertIsNone(docker_mode.recorded(self.prefix))


class Loader(Base):
    """sitecustomize on PYTHONPATH loads the hook in Docker mode, restores the
    line when the webserver starts, and leaves other Pythons alone."""

    def setUp(self):
        super().setUp()
        self.stamp("v4.2.4")
        lib = os.path.join(self.prefix, "lib")
        shutil.copytree(os.path.join(HOOK_ROOT, "openplc_canopen_hook"),
                        os.path.join(lib, "python", "openplc_canopen_hook"),
                        ignore=shutil.ignore_patterns("__pycache__"))
        os.makedirs(os.path.join(lib, "sitecustomize"))
        shutil.copy(os.path.join(HOOK_ROOT, "docker", "sitecustomize.py"), os.path.join(lib, "sitecustomize"))
        # A stand-in webserver: prints the canopen line it finds at start.
        os.makedirs(os.path.join(self.rt, "webserver"))
        open(os.path.join(self.rt, "webserver", "__init__.py"), "w").close()
        with open(os.path.join(self.rt, "webserver", "app.py"), "w") as f:
            f.write(textwrap.dedent("""\
                for line in open("plugins.conf"):
                    if line.startswith("canopen,"):
                        print("LINE " + line.strip())
                """))

    def run_python(self, *args, extra_path=None, version="v4.2.4"):
        paths = [os.path.join(self.prefix, "lib", "sitecustomize")] + ([extra_path] if extra_path else [])
        env = {k: v for k, v in os.environ.items() if k not in ("PYTHONPATH", "OPENPLC_CANOPEN_PREFIX")}
        env.update(PYTHONPATH=os.pathsep.join(paths), RUNTIME_VERSION=version)
        return subprocess.run([sys.executable] + list(args), cwd=self.rt, env=env, capture_output=True, text=True)

    def test_webserver_start_restores_the_line(self):
        p = self.run_python("-m", "webserver.app")
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertIn("LINE " + docker_mode.disabled_line(self.prefix), p.stdout)
        self.assertIn("added a disabled canopen line", p.stderr)

    def test_version_mismatch_at_webserver_start(self):
        p = self.run_python("-m", "webserver.app", version="v4.2.5")
        self.assertIn("LINE " + docker_mode.disabled_line(self.prefix), p.stdout)
        self.assertIn("ERROR: the CANopen plugin was built for runtime v4.2.4 but the runtime is v4.2.5", p.stderr)

    def test_other_pythons_untouched(self):
        p = self.run_python("-c", "import sys; print('ok')")
        self.assertEqual((p.returncode, p.stdout.strip(), p.stderr), (0, "ok", ""))
        self.assertFalse(os.path.exists(self.conf))

    def test_other_sitecustomize_still_runs(self):
        other = os.path.join(self.dir, "other")
        os.makedirs(other)
        with open(os.path.join(other, "sitecustomize.py"), "w") as f:
            f.write("import os\nos.environ['OTHER_SITECUSTOMIZE'] = '1'\n")
        p = self.run_python("-c", "import os, openplc_canopen_hook as h; "
                                  "print(os.environ.get('OTHER_SITECUSTOMIZE'), h._state['docker'])",
                            extra_path=other)
        self.assertEqual(p.stdout.strip(), "1 True", p.stderr)


if __name__ == "__main__":
    unittest.main()
