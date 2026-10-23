"""canworks-local-runtime and the `local` target (canopen-local-runtime).

The container engine is a fake that records its command lines; the runtime
behind the published port is the HTTPS stub of the runtime client tests."""

import contextlib
import io
import json
import os
import stat
import subprocess
import unittest
from unittest import mock

from canworks import __version__, diag, localruntime

from .helpers import StubRuntime, make_cert, pingpong_config, tmpdir
from .test_deploy import deploy


STARTED = "[INFO] [CANWORKS] canworks-bridge: config /etc/canworks-bridge/canworks.json, protocols canopen\n"


class FakeEngine:
    """Stands in for _run: answers docker/podman command lines from a small
    model of the two containers and remembers every call."""

    def __init__(self, info_ok=("docker",), image_present=True, run_errors=()):
        self.info_ok = set(info_ok)
        self.image_present = image_present
        self.run_errors = list(run_errors)  # stderr of the next failing `create`s
        self.containers = {}  # name -> [status, image, volume]
        self.volumes = set()
        self.copied = []  # (source, destination) of each `cp`
        self.bridge_log = STARTED  # what `logs` of the bridge says after a restart
        self.calls = []

    @property
    def container(self):
        """(status, image) of the runtime container."""
        c = self.containers.get(localruntime.CONTAINER)
        return (c[0], c[1]) if c else None

    @container.setter
    def container(self, value):
        for name, image in ((localruntime.CONTAINER, value[1]), (localruntime.BRIDGE, localruntime.default_image())):
            self.containers[name] = [value[0], image, name + "-volume"]

    @property
    def bridge(self):
        c = self.containers.get(localruntime.BRIDGE)
        return (c[0], c[1]) if c else None

    def __call__(self, argv, capture=True, timeout=None, merge=False):
        self.calls.append(list(argv))
        self.merged = merge
        prefix = 3 if argv[0] == "wsl" else 1
        name, args = " ".join(argv[:prefix]), argv[prefix:]

        def done(code=0, out="", err=""):
            return subprocess.CompletedProcess(argv, code, out, err)

        cmd = args[0]
        if cmd == "info":
            return done(0) if name in self.info_ok else done(1, err="Cannot connect to the daemon")
        if cmd == "inspect":
            c = self.containers.get(args[-1])
            if not c:
                return done(1, err="no such container")
            return done(0, "%s|%s\n" % (c[0], c[1]))
        if cmd == "image":
            return done(0 if self.image_present else 1)
        if cmd == "pull":
            self.image_present = True
            return done(0)
        if cmd in ("create", "run"):
            if cmd == "create" and self.run_errors:
                return done(125, err=self.run_errors.pop(0))
            cname = args[args.index("--name") + 1]
            volume = args[args.index("-v") + 1].split(":")[0]
            self.containers[cname] = ["created" if cmd == "create" else "running", args[-1], volume]
            self.volumes.add(volume)
            return done(0, "abc123\n")
        if cmd in ("start", "stop", "restart"):
            self.containers[args[-1]][0] = "exited" if cmd == "stop" else "running"
            return done(0)
        if cmd == "cp":
            self.copied.append((args[1], args[2]))
            if os.path.isdir(os.path.dirname(args[2])):  # out of a container: a file on this PC
                with open(args[2], "w") as f:
                    f.write("pem")
            return done(0)
        if cmd == "exec":
            return done(0)
        if cmd == "rm":
            self.containers.pop(args[-1], None)
            return done(0)
        if cmd == "volume":
            had = args[-1] in self.volumes
            self.volumes.discard(args[-1])
            return done(0 if had else 1)
        if cmd == "logs":
            if args[-1] == localruntime.BRIDGE:
                return done(0, "", self.bridge_log if "--since" in args else
                            "[INFO] [CANWORKS] simulation forced by the runtime environment\n")
            return done(0, "runtime log\n")
        return done(1, err="unknown command")

    def runs(self):
        """The `create` and `run` calls."""
        return [c for c in self.calls if c[1] in ("create", "run")]


class Base(unittest.TestCase):
    def setUp(self):
        self.dir = tmpdir(self)
        env = mock.patch.dict(os.environ, {"CANWORKS_CONFIG_DIR": os.path.join(self.dir, "cfg")})
        env.start()
        self.addCleanup(env.stop)
        os.environ.pop(localruntime.ENGINE_ENV, None)
        self.engine = FakeEngine()
        for target, value in (("canworks.localruntime._run", self.engine),
                              ("canworks.localruntime.shutil.which", lambda name: "/usr/bin/" + name),
                              ("canworks.localruntime.READY_TIMEOUT", 5.0)):
            p = mock.patch(target, value)
            p.start()
            self.addCleanup(p.stop)

    def cli(self, *argv):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = localruntime.main(list(argv))
        return code, out.getvalue(), err.getvalue()


class Engines(Base):
    def test_first_engine_that_runs(self):
        self.engine.info_ok = {"podman"}
        self.assertEqual(localruntime.detect_engine(platform="darwin").name, "podman")

    def test_wsl_on_windows(self):
        self.engine.info_ok = {"wsl -e docker"}
        eng = localruntime.detect_engine(platform="win32")
        self.assertEqual((eng.name, eng.argv), ("wsl-docker", ["wsl", "-e", "docker"]))
        with self.assertRaises(localruntime.LocalRuntimeError):
            localruntime.detect_engine(platform="linux")  # WSL is tried on Windows only

    def test_no_engine(self):
        self.engine.info_ok = set()
        with self.assertRaises(localruntime.LocalRuntimeError) as cm:
            localruntime.detect_engine(platform="darwin")
        self.assertIn("no container engine is running", str(cm.exception))
        self.assertIn("colima start", str(cm.exception))
        self.assertIn("docker: Cannot connect to the daemon", str(cm.exception))

    def test_not_installed(self):
        with mock.patch("canworks.localruntime.shutil.which", lambda name: None):
            with self.assertRaises(localruntime.LocalRuntimeError) as cm:
                localruntime.detect_engine(platform="linux")
        self.assertIn("docker: not installed; podman: not installed", str(cm.exception))

    def test_choice_and_environment(self):
        self.engine.info_ok = {"docker", "podman"}
        self.assertEqual(localruntime.detect_engine("podman").name, "podman")
        with mock.patch.dict(os.environ, {localruntime.ENGINE_ENV: "podman"}):
            self.assertEqual(localruntime.detect_engine().name, "podman")
        with self.assertRaises(localruntime.LocalRuntimeError):
            localruntime.detect_engine("lxc")

    def test_no_engine_creates_nothing(self):
        self.engine.info_ok = set()
        code, out, err = self.cli("start")
        self.assertEqual(code, 1)
        self.assertIn("docs/local-runtime.md", err)
        self.assertEqual(self.engine.runs(), [])
        self.assertIsNone(localruntime.load_settings())


class WithRuntime(Base):
    def setUp(self):
        super().setUp()
        pair = make_cert(self.dir)
        if pair is None:
            self.skipTest("openssl is not available")
        self.stub = StubRuntime(*pair, plc="STOPPED")
        self.stub.users = []
        self.stub.__enter__()
        self.addCleanup(self.stub.__exit__)
        self.port = self.stub.port

    def start(self, *extra):
        return self.cli("start", "--port", str(self.port), *extra)


class Start(WithRuntime):
    def test_first_start(self):
        code, out, err = self.start()
        self.assertEqual(code, 0, err)
        run, bridge = self.engine.runs()
        self.assertEqual(run[-1], localruntime.runtime_image())
        self.assertTrue(run[-1].startswith("ghcr.io/autonomy-logic/openplc-runtime:"))
        self.assertIn("127.0.0.1:%d:8443" % self.port, run)
        self.assertIn("127.0.0.1:7531:7531", run)
        self.assertIn("canworks-local-runtime-data:/var/run/runtime", run)
        self.assertIn("unless-stopped", run)
        self.assertIn("SYS_NICE", run)
        self.assertIn("memlock=-1:-1", run)
        self.assertEqual(bridge[-1], "%s:%s" % (localruntime.IMAGE_REPO, __version__))
        self.assertIn("container:" + localruntime.CONTAINER, bridge)
        self.assertIn("CANWORKS_FORCE_SIMULATE=1", bridge)
        self.assertIn("canworks-local-bridge-config:/etc/canworks-bridge", bridge)
        self.assertEqual(self.engine.bridge[0], "running")
        saved = localruntime.load_settings()
        self.assertEqual(saved["user"], "openplc")
        self.assertGreaterEqual(len(saved["password"]), 20)
        self.assertEqual(self.stub.password, saved["password"])
        self.assertEqual(saved["engine"], "docker")
        self.assertEqual(saved["port"], self.port)
        self.assertEqual(len(saved["fingerprint"].split(":")), 32)
        if os.name != "nt":
            self.assertEqual(stat.S_IMODE(os.stat(localruntime.settings_path()).st_mode), 0o600)
        self.assertIn("address localhost:%d, user openplc" % self.port, out)
        self.assertNotIn(saved["password"], out)  # only `status --show-password` prints it
        self.assertIn("canworks-local-runtime status --show-password", out)
        self.assertIn("Every network runs simulated here", out)
        self.assertIn("--bridge local", out)

    def test_pull_when_missing(self):
        self.engine.image_present = False
        code, out, err = self.start()
        self.assertEqual(code, 0, err)
        self.assertIn(["docker", "pull", localruntime.runtime_image()], self.engine.calls)

    def test_restart_keeps_credentials(self):
        self.assertEqual(self.start()[0], 0)
        first = localruntime.load_settings()
        self.assertEqual(self.cli("stop")[0], 0)
        self.assertEqual(self.engine.container[0], "exited")
        code, out, err = self.start()
        self.assertEqual(code, 0, err)
        self.assertIn(["docker", "start", localruntime.CONTAINER], self.engine.calls)
        self.assertIn(["docker", "start", localruntime.BRIDGE], self.engine.calls)
        self.assertEqual(localruntime.load_settings(), first)
        self.assertEqual(len(self.engine.runs()), 2)

    def pin_other_certificate(self):
        """The saved fingerprint stops matching: another program now answers
        on the port with its own certificate."""
        doc = localruntime.load_settings()
        doc["fingerprint"] = ":".join(["00"] * 32)
        localruntime.save_settings(doc)
        self.stub.requests.clear()
        return doc

    def test_changed_certificate_refused(self):
        self.assertEqual(self.start()[0], 0)
        doc = self.pin_other_certificate()
        self.assertEqual(self.cli("stop")[0], 0)
        for _ in range(2):  # a stopped container started again, and one already running
            code, out, err = self.start()
            self.assertEqual(code, 1)
            self.assertIn("certificate changed", err)
            self.assertIn("canworks-local-runtime start", err)
            self.assertNotIn(("POST", "/api/login"), self.stub.requests)  # the password was not sent
            self.assertEqual(localruntime.load_settings(), doc)
            self.assertNotIn(doc["password"], out + err)

    def test_recreated_container_pinned_again(self):
        self.assertEqual(self.start()[0], 0)
        first = localruntime.load_settings()
        self.pin_other_certificate()
        self.assertEqual(self.cli("remove")[0], 0)
        code, out, err = self.start()
        self.assertEqual(code, 0, err)
        self.assertIn("the runtime's certificate changed; the new fingerprint is saved", out)
        self.assertEqual(localruntime.load_settings()["fingerprint"], first["fingerprint"])

    def test_lost_credentials(self):
        self.assertEqual(self.start()[0], 0)
        os.remove(localruntime.settings_path())
        code, out, err = self.start()
        self.assertEqual(code, 1)
        self.assertIn("cannot be recovered", err)
        self.assertIn("remove --data", err)
        self.assertEqual(self.engine.container[0], "running")

    def test_capabilities_refused(self):
        self.engine.run_errors = ["Error: invalid capability: cap_sys_nice"]
        code, out, err = self.start()
        self.assertEqual(code, 0, err)
        self.assertIn("refused the real-time capabilities", out)
        runs = self.engine.runs()
        self.assertEqual(len(runs), 3)  # the refused runtime, the runtime without them, the bridge
        self.assertNotIn("SYS_NICE", runs[1])
        self.assertNotIn("memlock=-1:-1", runs[1])

    def test_memlock_refused(self):
        self.engine.run_errors = ["Error: crun: setrlimit `RLIMIT_MEMLOCK`: Operation not permitted"]
        code, out, err = self.start()
        self.assertEqual(code, 0, err)
        self.assertIn("refused the real-time capabilities", out)
        self.assertNotIn("memlock=-1:-1", self.engine.runs()[1])

    def test_port_in_use(self):
        self.engine.run_errors = ["Bind for 127.0.0.1:8443 failed: port is already allocated"]
        code, out, err = self.start()
        self.assertEqual(code, 1)
        self.assertIn("already in use", err)
        self.assertIn("--port", err)
        self.assertIsNone(self.engine.container)
        self.assertIsNone(self.engine.bridge)
        self.assertIn(["docker", "rm", "-f", localruntime.CONTAINER], self.engine.calls)

    def test_other_image(self):
        self.engine.container = ("running", localruntime.runtime_image())
        self.engine.containers[localruntime.BRIDGE][1] = "%s:0.1.0" % localruntime.IMAGE_REPO
        code, out, err = self.start()
        self.assertEqual(code, 0, err)
        self.assertIn("bridge runs image %s:0.1.0; `canworks-local-runtime update` switches it"
                      % localruntime.IMAGE_REPO, out)
        self.assertEqual(localruntime.load_settings()["bridge_image"], "%s:0.1.0" % localruntime.IMAGE_REPO)
        code, out, err = self.start("--image", "other:1")
        self.assertEqual(code, 1)
        self.assertIn("update --image other:1", err)


class Manage(WithRuntime):
    def test_status(self):
        self.assertEqual(self.start()[0], 0)
        code, out, err = self.cli("status", "--show-password")
        self.assertEqual(code, 0, err)
        self.assertIn("canworks-local-runtime: running, image " + localruntime.runtime_image(), out)
        self.assertIn("canworks-local-bridge: running, image " + localruntime.default_image(), out)
        self.assertIn("password " + localruntime.load_settings()["password"], out)
        self.assertIn("PLC: STOPPED", out)
        self.assertIn("simulation forced by the runtime environment", out)
        code, out, err = self.cli("status")
        self.assertNotIn("password", out)

    def test_status_without_container(self):
        code, out, err = self.cli("status")
        self.assertEqual(code, 1)
        self.assertIn("containers: none", out)

    def test_update(self):
        self.assertEqual(self.start()[0], 0)
        first = localruntime.load_settings()
        code, out, err = self.cli("update", "--port", str(self.port), "--image", "%s:9.9.9" % localruntime.IMAGE_REPO)
        self.assertEqual(code, 0, err)
        self.assertEqual(self.engine.bridge, ("running", "%s:9.9.9" % localruntime.IMAGE_REPO))
        self.assertEqual(self.engine.container, ("running", localruntime.runtime_image()))
        saved = localruntime.load_settings()
        self.assertEqual((saved["password"], saved["fingerprint"]), (first["password"], first["fingerprint"]))
        self.assertEqual(saved["bridge_image"], "%s:9.9.9" % localruntime.IMAGE_REPO)
        # The runtime's certificate goes out of the old container and into the new one.
        cert = "%s:%s/certOPENPLC.pem" % (localruntime.CONTAINER, localruntime.CERT_DIR)
        self.assertEqual([src == cert for src, dst in self.engine.copied if cert in (src, dst)], [True, False])
        self.assertIn("upload the PLC program again", out)

    def test_remove(self):
        self.assertEqual(self.start()[0], 0)
        code, out, err = self.cli("remove")
        self.assertEqual(code, 0, err)
        self.assertIsNone(self.engine.container)
        self.assertIsNone(self.engine.bridge)
        self.assertIsNotNone(localruntime.load_settings())  # without --data the credentials stay
        self.assertEqual(self.start()[0], 0)
        code, out, err = self.cli("remove", "--data")
        self.assertEqual(code, 0, err)
        self.assertIn("removed the volume canworks-local-runtime-data", out)
        self.assertIn("removed the volume canworks-local-bridge-config", out)
        self.assertIsNone(localruntime.load_settings())
        self.assertEqual(self.engine.volumes, set())


class Logs(WithRuntime):
    def test_logs_one_stream(self):
        self.assertEqual(self.start()[0], 0)
        self.assertEqual(self.cli("logs")[0], 0)
        self.assertEqual(self.engine.calls[-1], ["docker", "logs", localruntime.BRIDGE])
        self.assertTrue(self.engine.merged)
        self.assertEqual(self.cli("logs", "--runtime")[0], 0)
        self.assertEqual(self.engine.calls[-1], ["docker", "logs", localruntime.CONTAINER])


class LocalTarget(WithRuntime):
    def setUp(self):
        super().setUp()
        p = mock.patch("canworks.localruntime.time.sleep", lambda s: None)
        p.start()
        self.addCleanup(p.stop)

    def test_deploy_to_local(self):
        self.assertEqual(self.start()[0], 0)
        config = pingpong_config(self.dir)
        code, out, err = deploy("--config", config, "--bridge", "local")
        self.assertEqual(code, 0, err)
        self.assertIn("local runtime: every network runs simulated", out)
        self.assertIn("ok: the local bridge runs the new config", out)
        dst = [d for _, d in self.engine.copied if d.startswith(localruntime.BRIDGE + ":")]
        self.assertEqual(dst, ["%s:%s" % (localruntime.BRIDGE, localruntime.BRIDGE_CONF)])
        self.assertIn(["docker", "restart", localruntime.BRIDGE], self.engine.calls)

    def test_bridge_refuses_the_config(self):
        self.assertEqual(self.start()[0], 0)
        self.engine.bridge_log = "[ERROR] [CANWORKS] node 2: EDS bad; canworks-bridge not started\n"
        code, out, err = deploy("--config", pingpong_config(self.dir), "--bridge", "local")
        self.assertEqual(code, 1)
        self.assertIn("the local bridge did not start the config: [ERROR] [CANWORKS] node 2: EDS bad", err)

    def test_simulated_config_not_asked(self):
        self.assertEqual(self.start()[0], 0)
        config = pingpong_config(self.dir)
        with open(config, encoding="utf-8") as f:
            cfg = json.load(f)
        cfg["networks"][0]["adapter"]["simulate"] = True
        with open(config, "w", encoding="utf-8") as f:
            json.dump(cfg, f)
        with mock.patch("canworks.cli._ask") as ask:
            code, out, err = deploy("--config", config, "--bridge", "local")
        self.assertEqual(code, 0, err)
        self.assertFalse(ask.called)

    def test_no_local_runtime(self):
        code, out, err = deploy("--config", pingpong_config(self.dir), "--bridge", "local")
        self.assertEqual(code, 1)
        self.assertIn("run `canworks-local-runtime start` first", err)

    def test_diag_host(self):
        self.assertEqual(diag.parse_runtime("local"), ("127.0.0.1", 7531))
        self.assertEqual(self.cli("start", "--port", str(self.port), "--diag-port", "7600")[0], 0)
        self.assertEqual(diag.parse_runtime("LOCAL"), ("127.0.0.1", 7600))


class DiagStatus(unittest.TestCase):
    def test_forced_simulation_line(self):
        out = io.StringIO()
        diag._print_status({"version": "1", "uptime_s": 3, "config_sha256": "ab" * 32, "simulated_network": True,
                            "simulation_forced": True, "bus": {"interface": "simulated", "state": 1},
                            "master": {"node_id": 1, "state": 5}, "nodes": []}, out)
        self.assertIn("simulation forced by the runtime (local runtime)", out.getvalue())
        self.assertIn("simulated network: no CAN interface is used", out.getvalue())


if __name__ == "__main__":
    unittest.main()
