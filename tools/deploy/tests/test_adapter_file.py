"""The adapter server file (canopen-remote-adapter "Adapter server file",
canopen-ci "Adapter server file test"): scripts/build-adapter-pyz.py, run on
a bare Python (-I -S: no site packages) with a virtual adapter, and a client
with the full tools through it.

Builds the file with pip (network), so it runs only with
CANWORKS_ADAPTER_FILE=1: the tools job sets it when the file's paths changed
(.github/ci/adapter-file-paths.txt)."""

import importlib.util
import os
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import types
import unittest
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
DEPLOY = os.path.dirname(HERE)
REPO = os.path.dirname(os.path.dirname(DEPLOY))
BUILD = os.path.join(REPO, "scripts", "build-adapter-pyz.py")

# Imported by the server, the service install and the adapters it serves.
MODULES = ("canworks.diag", "canworks.localbus.serve", "canworks.localbus.client", "canworks.link.discovery",
           "can.interfaces.socketcan", "can.interfaces.slcan", "can.interfaces.virtual", "serial")


def _build_module():
    spec = importlib.util.spec_from_file_location("build_adapter_pyz", BUILD)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class MainCheck(unittest.TestCase):
    """The file's entry refuses an old Python before it imports canworks."""

    def test_old_python(self):
        fake = types.SimpleNamespace(version_info=(3, 9, 18), stderr=types.SimpleNamespace(text="", write=None))
        fake.stderr.write = lambda t: setattr(fake.stderr, "text", fake.stderr.text + t)

        def exit_(code):
            raise SystemExit(code)
        fake.exit = exit_
        code = _build_module().MAIN.replace("import sys\n", "", 1)
        with self.assertRaises(SystemExit) as e:
            exec(compile(code, "__main__.py", "exec"), {"sys": fake})
        self.assertEqual(e.exception.code, 1)
        self.assertIn("needs Python 3.11 or newer (this is Python 3.9)", fake.stderr.text)


@unittest.skipUnless(os.environ.get("CANWORKS_ADAPTER_FILE") == "1", "CANWORKS_ADAPTER_FILE=1 builds and runs the file")
class AdapterFile(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix="canworks-adapter-file-")
        constraints = os.path.join(DEPLOY, "constraints.txt")
        if not os.path.exists(constraints):
            constraints = os.path.join(cls.tmp, "constraints.txt")
            subprocess.run(["uv", "export", "--project", DEPLOY, "--frozen", "--no-hashes", "--no-emit-project",
                            "--no-dev", "--format", "requirements-txt", "-q", "-o", constraints], check=True)
        cls.file = os.path.join(cls.tmp, "canworks-adapter.pyz")
        subprocess.run([sys.executable, BUILD, "--source", DEPLOY, "--constraints", constraints, "--out", cls.file],
                       check=True, stdout=subprocess.DEVNULL)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def bare(self, *args, **kw):
        """The file's Python without site packages, with an empty home."""
        home = tempfile.mkdtemp(dir=self.tmp)
        env = {"PATH": os.environ.get("PATH", ""), "HOME": home, "XDG_CONFIG_HOME": os.path.join(home, ".config"),
               "LC_ALL": "C.UTF-8"}
        return [sys.executable, "-I", "-S"] + list(args), env

    def test_size_and_contents(self):
        self.assertLessEqual(os.path.getsize(self.file), _build_module().MAX_BYTES)
        with zipfile.ZipFile(self.file) as z:
            names = z.namelist()
        tops = {n.split("/")[0] for n in names}
        self.assertIn("canworks", tops)
        self.assertIn("can", tops)
        self.assertIn("serial", tops)
        for gone in ("cantools", "paramiko", "jsonschema", "iroh", "j1939"):
            self.assertNotIn(gone, tops)
        self.assertFalse([n for n in names if n.startswith("canworks/configurator/")])
        self.assertFalse([n for n in names if n.endswith((".so", ".pyd", ".pyc"))])

    def test_version(self):
        from canworks import __version__
        cmd, env = self.bare(self.file, "--version")
        r = subprocess.run(cmd, env=env, capture_output=True, text=True, timeout=60)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(r.stdout.split()[-1], __version__)

    def test_only_stdlib_and_the_file(self):
        """Every module the server needs comes from the standard library or
        the file: a new dependency fails here, by name."""
        script = ("import sys, importlib\n"
                  "sys.path.insert(0, %r)\n"
                  "for m in %r:\n"
                  "    importlib.import_module(m)\n"
                  "bad = sorted({n.split('.')[0] for n, m in list(sys.modules.items())\n"
                  "              if n.split('.')[0] not in sys.stdlib_module_names\n"
                  "              and not (getattr(m, '__file__', None) or '').startswith(%r)\n"
                  "              and getattr(m, '__file__', None)})\n"
                  "print('outside:', ' '.join(bad))\n") % (self.file, MODULES, self.file)
        cmd, env = self.bare("-c", script)
        r = subprocess.run(cmd, env=env, capture_output=True, text=True, timeout=60)
        self.assertEqual(r.returncode, 0, "a module the file does not carry:\n" + r.stderr[-2000:])
        self.assertEqual(r.stdout.strip(), "outside:")

    def test_service_runs_the_file(self):
        script = ("import sys\nsys.argv = [%r]\nsys.path.insert(0, %r)\n"
                  "from canworks.localbus import serve\nprint(serve._command())\n") % (self.file, self.file)
        cmd, env = self.bare("-c", script)
        r = subprocess.run(cmd, env=env, capture_output=True, text=True, timeout=60)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(r.stdout.strip(), str([sys.executable, os.path.realpath(self.file)]))

    def test_serves_a_pc(self):
        port = _free_port()
        cmd, env = self.bare(self.file, "adapter-serve", "--adapter", "virtual:file-test", "--bitrate", "500",
                             "--allow-changes", "--bind", "127.0.0.1", "--port", str(port))
        server = subprocess.Popen(cmd, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)

        def stop():
            server.terminate()
            server.communicate(timeout=10)
        self.addCleanup(stop)
        line = server.stdout.readline()
        m = re.match(r"token: (\S+)", line)
        self.assertIsNotNone(m, line + server.stderr.read() if server.poll() is not None else line)
        token = m.group(1)
        # The server logs "serving adapter ..." once it listens.
        self.assertIn("serving adapter virtual:file-test", server.stderr.readline())

        def pc(*args):
            home = tempfile.mkdtemp(dir=self.tmp)
            env_pc = dict(os.environ, HOME=home, XDG_CONFIG_HOME=os.path.join(home, ".config"))
            r = subprocess.run([sys.executable, "-m", "canworks.diag", "--adapter", "remote:127.0.0.1:%d" % port,
                                "--token", token, "--allow-changes", "--force", "--timeout", "10"] + list(args),
                               cwd=DEPLOY, env=env_pc, capture_output=True, text=True, timeout=90)
            return r.returncode, r.stdout + r.stderr

        code, out = pc("status")
        self.assertEqual(code, 0, out)
        self.assertIn("adapter virtual:file-test, 500 kbit/s, changes allowed", out)
        code, out = pc("scan")
        self.assertEqual(code, 0, out)
        self.assertIn("no device answered", out)
        # Nobody else is on the virtual bus: the read reaches it and times out there.
        code, out = pc("sdo-read", "5", "0x1000", "0")
        self.assertIn("node 5 0x1000:0: timeout", out)
        code, out = pc("send", "0x123", "01", "02")
        self.assertEqual(code, 0, out)
        self.assertIn("sent 0x123 [2] 01 02", out)
        trace = os.path.join(self.tmp, "trace.csv")
        code, out = pc("trace", "-o", trace, "--duration", "1")
        self.assertEqual(code, 0, out)
        self.assertTrue(os.path.exists(trace), out)


if __name__ == "__main__":
    unittest.main()
