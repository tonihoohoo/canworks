"""The deploy tool end to end: bundle assembly, checks, clash rules and the
upload against a stub runtime (canopen-deploy spec)."""

import contextlib
import io
import json
import os
import unittest
from unittest import mock

from canworks import cli, clash, runtime
from canworks.iec import parse_location

from .helpers import (StubRuntime, editor_bundle, fake_editor_cli, make_cert, pingpong_config, python_program, tmpdir,
                      zip_contents)


def deploy(*argv, env=None):
    """Runs the tool; returns (exit code, stdout, stderr)."""
    out, err = io.StringIO(), io.StringIO()
    environ = {"OPENPLC_PASSWORD": "secret", "OPENPLC_USER": "openplc"}
    environ.update(env or {})
    with mock.patch.dict(os.environ, environ), contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = cli.main(list(argv))
    return code, out.getvalue(), err.getvalue()


ETHERCAT = {"slaves": [{"name": "EK1100", "channels": [
    {"name": "in1", "iec_location": "%IX0.0"}, {"name": "ain", "iec_location": "%IW100"}]}]}


class Bundle(unittest.TestCase):
    def setUp(self):
        self.dir = tmpdir(self)
        self.src = editor_bundle(os.path.join(self.dir, "src"), {"ethercat.json": ETHERCAT})
        self.config = pingpong_config(self.dir)
        self.zip = os.path.join(self.dir, "program.zip")

    def test_help_lists_options(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out), self.assertRaises(SystemExit):
            cli.main(["--help"])
        for opt in ("--bundle", "--project", "--config", "--runtime", "--user", "--allow-clash", "--ca",
                    "--fingerprint", "--insecure"):
            self.assertIn(opt, out.getvalue())

    def test_bundle_with_ethercat_config(self):
        code, out, err = deploy("--bundle", self.src, "--config", self.config, "--check-only", "--output", self.zip)
        self.assertEqual(code, 0, err)
        files = zip_contents(self.zip)
        # Every file of the editor's build is unchanged.
        for root, _, names in os.walk(self.src):
            for name in names:
                path = os.path.join(root, name)
                rel = os.path.relpath(path, self.src).replace(os.sep, "/")
                with open(path, "rb") as f:
                    self.assertEqual(files[rel], f.read(), rel)
        with open(os.path.join(self.dir, "cpp-slave.eds"), "rb") as f:
            self.assertEqual(files["conf/canworks/eds/cpp-slave.eds"], f.read())
        deployed = json.loads(files["conf/canworks.json"])
        self.assertEqual(deployed["nodes"][0]["eds"], "canworks/eds/cpp-slave.eds")
        with open(self.config, encoding="utf-8") as f:
            original = json.load(f)
        original["nodes"][0]["eds"] = "canworks/eds/cpp-slave.eds"
        self.assertEqual(deployed, original)
        self.assertEqual(len(files), 10)
        self.assertNotIn("Note:", out)  # the editor warning follows an upload

    def test_cp1252_eds_converted(self):
        eds = os.path.join(self.dir, "cpp-slave.eds")
        with open(eds, "rb") as f:
            data = f.read()
        with open(eds, "wb") as f:
            f.write(data.replace(b"[Comments]\nLines=0\n", b"[Comments]\nLines=1\nLine1=Range 0-100 \x94C\n"))
        with open(eds, "rb") as f:
            original = f.read()
        code, out, err = deploy("--bundle", self.src, "--config", self.config, "--check-only", "--output", self.zip)
        self.assertEqual(code, 0, err)
        shipped = zip_contents(self.zip)["conf/canworks/eds/cpp-slave.eds"]
        self.assertEqual(shipped, original.decode("cp1252").encode("utf-8"))
        self.assertIn("Line1=Range 0-100 \u201dC", shipped.decode("utf-8"))
        with open(eds, "rb") as f:
            self.assertEqual(f.read(), original)  # the source on the PC is unchanged
        self.assertIn("converted cpp-slave.eds from CP1252 to UTF-8", out)

    def test_program_file_shipped(self):
        os.makedirs(os.path.join(self.dir, "fw"))
        with open(os.path.join(self.dir, "fw", "node2.bin"), "wb") as f:
            f.write(b"\x02\x00\x00\x00\xff\xfe firmware")
        with open(self.config, encoding="utf-8") as f:
            cfg = json.load(f)
        cfg["nodes"][0].update(software_file="fw/node2.bin", software_version=2)
        with open(self.config, "w", encoding="utf-8") as f:
            json.dump(cfg, f)
        code, out, err = deploy("--bundle", self.src, "--config", self.config, "--check-only", "--output", self.zip)
        self.assertEqual(code, 0, err)
        self.assertIn("and 1 program file", out)
        files = zip_contents(self.zip)
        self.assertEqual(files["conf/canworks/fw/node2.bin"], b"\x02\x00\x00\x00\xff\xfe firmware")
        self.assertEqual(json.loads(files["conf/canworks.json"])["nodes"][0]["software_file"], "canworks/fw/node2.bin")

    def test_program_file_missing(self):
        with open(self.config, encoding="utf-8") as f:
            cfg = json.load(f)
        cfg["nodes"][0].update(software_file="fw/node2.bin", software_version=2)
        with open(self.config, "w", encoding="utf-8") as f:
            json.dump(cfg, f)
        code, _, err = deploy("--bundle", self.src, "--config", self.config, "--check-only")
        self.assertEqual(code, 1)
        self.assertIn('software_file "fw/node2.bin" not found', err)

    def test_eds_file_missing(self):
        config = pingpong_config(self.dir)
        os.remove(os.path.join(self.dir, "cpp-slave.eds"))
        code, _, err = deploy("--bundle", self.src, "--config", config, "--check-only")
        self.assertEqual(code, 1)
        self.assertIn("node 2: EDS file", err)
        self.assertIn("cpp-slave.eds not found", err)
        self.assertIn("nothing was uploaded", err)

    def test_not_an_editor_bundle(self):
        empty = os.path.join(self.dir, "empty")
        os.makedirs(empty)
        code, _, err = deploy("--bundle", empty, "--config", self.config, "--check-only")
        self.assertEqual(code, 1)
        self.assertIn("is not an editor build output", err)

    def test_schema_violation(self):
        with open(self.config, encoding="utf-8") as f:
            cfg = json.load(f)
        cfg["nodes"][0]["node_id"] = 200
        with open(self.config, "w", encoding="utf-8") as f:
            json.dump(cfg, f)
        code, _, err = deploy("--bundle", self.src, "--config", self.config, "--check-only")
        self.assertEqual(code, 1)
        self.assertIn("nodes[0].node_id: 200 is greater than the maximum of 127", err)

    def test_eds_check_fails_with_the_plugins_message(self):
        eds = os.path.join(self.dir, "cpp-slave.eds")
        with open(eds, encoding="utf-8") as f:
            text = f.read().replace("DataType=0x0007\nAccessType=rww", "DataType=0x0007\nAccessType=ro")
        with open(eds, "w", encoding="utf-8") as f:
            f.write(text)
        code, _, err = deploy("--bundle", self.src, "--config", self.config, "--check-only")
        self.assertEqual(code, 1)
        self.assertIn("node 2, index 0x4000, subindex 0: rx_pdos entry needs an object the slave can receive "
                      "(AccessType wo, rw or rww), but its AccessType is ro", err)

    def test_project_built_with_openplc_cli(self):
        # A stand-in openplc-cli that writes the bundle where the real one does.
        project = os.path.join(self.dir, "project")
        os.makedirs(project)
        fake = python_program(os.path.join(self.dir, "openplc-cli"),
                              "import sys, os\n"
                              "sys.path.insert(0, %r)\n"
                              "from tests.helpers import editor_bundle\n"
                              "assert sys.argv[1] == 'compile' and sys.argv[3:5] == ['--target', 'OpenPLC Runtime v4'], "
                              "sys.argv\n"
                              "assert os.path.isabs(sys.argv[2]), sys.argv\n"
                              "editor_bundle(os.path.join(sys.argv[2], 'build', 'OpenPLC Runtime v4', 'src'))\n"
                              % os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
        code, out, err = deploy("--project", project, "--config", self.config, "--check-only", "--output", self.zip,
                                env={"OPENPLC_CLI": fake})
        self.assertEqual(code, 0, err)
        self.assertIn("conf/canworks.json", zip_contents(self.zip))
        # A relative project path reaches openplc-cli as an absolute one.
        os.makedirs(os.path.join(self.dir, "relative"))
        cwd = os.getcwd()
        os.chdir(self.dir)
        try:
            code, out, err = deploy("--project", "relative", "--config", self.config, "--check-only",
                                    env={"OPENPLC_CLI": fake})
        finally:
            os.chdir(cwd)
        self.assertEqual(code, 0, err)

    def test_deprecated_keys_warn(self):
        config = pingpong_config(self.dir)
        with open(config, encoding="utf-8") as f:
            cfg = json.load(f)
        adapter = cfg.pop("adapter")
        cfg["interface"], cfg["bitrate"] = adapter["interface"], adapter["bitrate"]
        with open(config, "w", encoding="utf-8") as f:
            json.dump(cfg, f)
        code, _, err = deploy("--bundle", self.src, "--config", config, "--check-only")
        self.assertEqual(code, 0, err)
        self.assertIn("warning:", err)
        self.assertIn("deprecated", err)


class NewProject(unittest.TestCase):
    """--new-project (add-editor-project-template task 3.1)."""

    def setUp(self):
        self.dir = tmpdir(self)
        self.config = pingpong_config(self.dir)
        self.env = {"OPENPLC_CLI": fake_editor_cli(self.dir)}
        self.target = os.path.join(self.dir, "pp-project")

    def test_create(self):
        code, out, err = deploy("--config", self.config, "--new-project", self.target, "--task-interval", "T#10ms",
                                env=self.env)
        self.assertEqual(code, 0, err)
        self.assertIn("created %s with 3 CANopen variables declared in main" % self.target, out)
        with open(os.path.join(self.dir, "cli-args.json")) as f:
            self.assertIn("--time=T#10ms", json.load(f))
        with open(os.path.join(self.target, "pous", "programs", "main.st")) as f:
            self.assertIn(" : UDINT AT %ID100;", f.read())
        self.assertTrue(os.path.isfile(os.path.join(self.target, "canworks", "canworks.json")))

    def test_existing_folder(self):
        os.makedirs(self.target)
        with open(os.path.join(self.target, "x"), "w") as f:
            f.write("x")
        code, _, err = deploy("--config", self.config, "--new-project", self.target, env=self.env)
        self.assertEqual(code, 1)
        self.assertIn("already exists", err)
        self.assertEqual(os.listdir(self.target), ["x"])

    def test_interval_needs_new_project(self):
        code, _, err = deploy("--config", self.config, "--check-only", "--bundle", self.dir, "--task-interval",
                              "T#10ms", env=self.env)
        self.assertEqual(code, 1)
        self.assertIn("--task-interval needs --new-project", err)

    def test_no_upload_options(self):
        code, _, err = deploy("--config", self.config, "--new-project", self.target, "--runtime", "x", env=self.env)
        self.assertEqual(code, 1)
        self.assertIn("leave out --runtime", err)
        self.assertFalse(os.path.exists(self.target))


class Clashes(unittest.TestCase):
    def uses(self, files):
        out = []
        for name, doc in files.items():
            clash.collect(doc, "conf/" + name, [], out)
        return out

    def canopen(self, loc_in="%ID100", loc_out="%QD100"):
        return {"nodes": [{"node_id": 2, "status_location": "%IX10.0",
                           "tx_pdos": [{"entries": [{"iec_location": loc_in}]}],
                           "rx_pdos": [{"entries": [{"iec_location": loc_out}]}]}]}

    def test_input_clash_with_ethercat(self):
        ethercat = {"slaves": [{"channels": [{"iec_location": "%ID100"}]}]}
        errors, _ = clash.check(self.uses({"ethercat.json": ethercat, "canworks.json": self.canopen()}))
        self.assertEqual(len(errors), 1)
        for part in ("conf/ethercat.json slaves[0].channels[0].iec_location",
                     "conf/canworks.json nodes[0].tx_pdos[0].entries[0].iec_location", "both write %ID100"):
            self.assertIn(part, errors[0])

    def test_different_sizes_are_different_tables(self):
        # %IW100 (int_input[100]) and %ID100 (dint_input[100]) are separate variables.
        ethercat = {"slaves": [{"channels": [{"iec_location": "%IW100"}]}]}
        self.assertEqual(clash.check(self.uses({"ethercat.json": ethercat, "canworks.json": self.canopen()})),
                         ([], []))

    def test_output_shared_with_modbus_master(self):
        modbus = {"devices": [{"points": [{"iec_location": "%QD99", "len": 2}]}]}
        errors, warnings = clash.check(self.uses({"modbus_master.json": modbus, "canworks.json": self.canopen()}))
        self.assertEqual(errors, [])
        self.assertEqual(len(warnings), 1)
        self.assertIn("conf/modbus_master.json devices[0].points[0].iec_location (%QD99..%QD100)", warnings[0])
        self.assertIn("both read output %QD100", warnings[0])

    def test_bit_runs(self):
        modbus = {"points": [{"iec_location": "%IX9.0", "len": 16}]}
        errors, _ = clash.check(self.uses({"modbus_master.json": modbus, "canworks.json": self.canopen()}))
        self.assertEqual(len(errors), 1)
        self.assertIn("both write %IX10.0", errors[0])

    def test_memory_overlap_warns(self):
        a = {"x": [{"iec_location": "%MW5"}]}
        b = {"y": {"iec_location": "%MW5"}}
        errors, warnings = clash.check(self.uses({"a.json": a, "b.json": b}))
        self.assertEqual(errors, [])
        self.assertIn("both use memory %MW5", warnings[0])

    def test_allow_clash(self):
        ethercat = {"c": [{"iec_location": "%ID100"}]}
        errors, warnings = clash.check(self.uses({"ethercat.json": ethercat, "canworks.json": self.canopen()}),
                                       allow_clash=True)
        self.assertEqual(errors, [])
        self.assertIn("allowed by --allow-clash", warnings[0])

    def test_inside_canopen_is_an_error(self):
        errors, _ = clash.check(self.uses({"canworks.json": self.canopen(loc_in="%IX10.0")}))
        self.assertEqual(len(errors), 1)

    def test_boot_error_byte_inside_canopen(self):
        cfg = self.canopen()
        cfg["master"] = {"state_location": "%IB20"}
        cfg["nodes"][0]["boot_error_location"] = "%IB20"
        errors, _ = clash.check(self.uses({"canworks.json": cfg}))
        self.assertEqual(len(errors), 1)
        self.assertIn("master.state_location", errors[0])
        self.assertIn("nodes[0].boot_error_location", errors[0])

    def test_locations(self):
        self.assertEqual(parse_location("%ix1.7").element, 15)
        self.assertIsNone(parse_location("%IX1.8"))
        self.assertIsNone(parse_location("%IW1.0"))
        self.assertEqual(str(parse_location("%qd7")), "%QD7")

    def test_cli_input_clash_stops_the_deploy(self):
        d = tmpdir(self)
        ethercat = {"slaves": [{"channels": [{"name": "x", "iec_location": "%ID100"}]}]}
        src = editor_bundle(os.path.join(d, "src"), {"ethercat.json": ethercat})
        config = pingpong_config(d)
        code, _, err = deploy("--bundle", src, "--config", config, "--check-only")
        self.assertEqual(code, 1)
        self.assertIn("input clash", err)
        self.assertIn("--allow-clash", err)
        code, _, err = deploy("--bundle", src, "--config", config, "--check-only", "--allow-clash")
        self.assertEqual(code, 0, err)
        self.assertIn("warning: input clash", err)


class Upload(unittest.TestCase):
    def setUp(self):
        self.dir = tmpdir(self)
        pair = make_cert(self.dir)
        if pair is None:
            self.skipTest("openssl is not available")
        self.cert, self.key = pair
        self.src = editor_bundle(os.path.join(self.dir, "src"), {"ethercat.json": ETHERCAT})
        self.config = pingpong_config(self.dir)

    def run_against(self, stub, *extra, env=None):
        with stub:
            return deploy("--bundle", self.src, "--config", self.config, "--runtime", "127.0.0.1:%d" % stub.port,
                          *extra, env=env)

    def test_successful_deploy(self):
        stub = StubRuntime(self.cert, self.key)
        zip_path = os.path.join(self.dir, "out.zip")
        code, out, err = self.run_against(stub, "--ca", self.cert, "--output", zip_path)
        self.assertEqual(code, 0, err)
        with open(zip_path, "rb") as f:
            self.assertEqual(stub.uploaded, f.read())
        self.assertIn("Final state - canworks: enabled=True", out)
        self.assertIn("canworks plugin enabled", out)
        last = out.strip().splitlines()[-1]
        self.assertIn("\"Build and upload\" sends no conf/canworks.json", last)
        self.assertEqual(stub.requests[:2], [("POST", "/api/login"), ("POST", "/api/upload-file")])
        self.assertIn(("GET", "/api/start-plc"), stub.requests)
        self.assertIn("the PLC is running", out)
        self.assertEqual(stub.plc, "RUNNING")

    def test_no_start_leaves_the_plc_stopped(self):
        stub = StubRuntime(self.cert, self.key)
        code, out, err = self.run_against(stub, "--ca", self.cert, "--no-start")
        self.assertEqual(code, 0, err)
        self.assertNotIn(("GET", "/api/start-plc"), stub.requests)
        self.assertIn("the PLC is stopped (--no-start)", out)

    def test_start_refused_by_the_run_switch(self):
        stub = StubRuntime(self.cert, self.key, start_answer="START:ERROR_SWITCH_STOP")
        code, out, err = self.run_against(stub, "--ca", self.cert)
        self.assertEqual(code, 1)
        self.assertIn("but the PLC was not started: the device's run/stop switch is at STOP", err)

    def test_note_with_editor_hook(self):
        stub = StubRuntime(self.cert, self.key, editor_hook=True)
        code, out, err = self.run_against(stub, "--ca", self.cert)
        self.assertEqual(code, 0, err)
        last = out.strip().splitlines()[-1]
        self.assertIn("has the CANopen editor hook", last)
        self.assertIn("--into-project", last)

    def test_wrong_credentials(self):
        stub = StubRuntime(self.cert, self.key)
        code, _, err = self.run_against(stub, "--ca", self.cert, env={"OPENPLC_PASSWORD": "wrong"})
        self.assertEqual(code, 1)
        self.assertIn("Wrong username or password", err)
        self.assertNotIn(("POST", "/api/upload-file"), stub.requests)
        self.assertIn("nothing was uploaded", err)

    def test_compile_fails(self):
        stub = StubRuntime(self.cert, self.key, build_ok=False)
        code, out, err = self.run_against(stub, "--ca", self.cert)
        self.assertEqual(code, 1)
        self.assertIn("error: boom", out)
        self.assertIn("build failed", err)

    def test_unknown_certificate(self):
        stub = StubRuntime(self.cert, self.key)
        code, _, err = self.run_against(stub)  # system trust store only
        self.assertEqual(code, 1)
        self.assertIn("not trusted", err)
        self.assertIn("--fingerprint", err)
        self.assertEqual(stub.requests, [])  # no credentials sent

    def test_pinned_fingerprint(self):
        import ssl
        with open(self.cert, encoding="ascii") as f:
            fp = runtime.fingerprint_of(ssl.PEM_cert_to_DER_cert(f.read()))
        code, _, err = self.run_against(StubRuntime(self.cert, self.key), "--fingerprint", fp)
        self.assertEqual(code, 0, err)
        stub = StubRuntime(self.cert, self.key)
        code, _, err = self.run_against(stub, "--fingerprint", "00" * 32)
        self.assertEqual(code, 1)
        self.assertIn("does not match --fingerprint", err)
        self.assertEqual(stub.requests, [])

    def test_plugin_not_installed_on_runtime(self):
        code, _, err = self.run_against(StubRuntime(self.cert, self.key, canopen_line=False), "--ca", self.cert)
        self.assertEqual(code, 1)
        self.assertIn("did not enable the canworks plugin", err)

    def test_canopen_turned_off_by_the_editor_hook(self):
        # Docker: the runtime enables the line, then the hook turns it off.
        problem = ("the CANopen plugin was built for runtime v4.2.4 but the runtime is v4.2.3; re-run "
                   "scripts/install-stock.sh to rebuild it; CANopen stays off")
        code, out, err = self.run_against(StubRuntime(self.cert, self.key, hook_error=problem), "--ca", self.cert)
        self.assertEqual(code, 1)
        self.assertIn("CANopen was turned off: " + problem, err)
        self.assertNotIn("canworks plugin enabled", out)


if __name__ == "__main__":
    unittest.main()
