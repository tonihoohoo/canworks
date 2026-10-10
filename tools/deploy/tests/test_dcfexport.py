"""DCF export (canworks.dcfexport): the download list, the DCF
text, its validation, and parity with the plugin's own download list
(canopen_check --dump-writes)."""

import contextlib
import copy
import datetime
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from unittest import mock

from canworks import cli, dcfexport, edslint

from .test_contract import FIXTURES, REPO, load_cases, patched

NOW = datetime.datetime(2026, 10, 4, 13, 5)
EDS_DIR = os.path.join(FIXTURES, "eds")
FIXTURE_CONFIG = os.path.join(EDS_DIR, "canworks.json")


def base_config():
    return copy.deepcopy(load_cases()["base"])


def compact_config():
    cfg = base_config()
    cfg["nodes"][0]["eds"] = "compact.eds"
    cfg["nodes"][0]["sdo"] = [
        {"index": "0x2100", "subindex": 2, "type": "UNSIGNED16", "value": 0x22},
        {"index": "0x2100", "subindex": 3, "type": "UNSIGNED16", "value": "0x33"},
    ]
    return cfg


def export(cfg, path=FIXTURE_CONFIG, **kw):
    files, _ = dcfexport.export(cfg, path, now=NOW, **kw)
    return files


def section(text, name):
    """{key: value} of a section of a DCF text."""
    out, cur = {}, None
    for line in text.splitlines():
        s = line.strip()
        if s.startswith("["):
            cur = s[1:-1].lower()
        elif cur == name.lower() and "=" in s and not s.startswith(";"):
            k, v = s.split("=", 1)
            out[k.strip()] = v.strip()
    return out


class Loader(unittest.TestCase):
    def test_dcfgen_loads_with_stand_ins_and_leaves_no_trace(self):
        before = {k: sys.modules.get(k) for k in ("dcf", "em", "yaml", "pkg_resources")}
        cli = dcfexport.dcfgen_cli()
        self.assertTrue(hasattr(cli, "Slave") and hasattr(cli, "Master"))
        self.assertIs(cli.dcf, dcfexport._lely_dcf)
        self.assertEqual({k: sys.modules.get(k) for k in before}, before)

    def test_loads_in_a_clean_interpreter(self):
        # Neither em, yaml nor pkg_resources is needed (the deploy tool
        # depends on jsonschema only).
        code = ("import sys; sys.modules.update(em=None, yaml=None, pkg_resources=None)\n"
                "from canworks import dcfexport\n"
                "for k in ('em', 'yaml', 'pkg_resources'): sys.modules.pop(k)\n"
                "print(dcfexport.dcfgen_cli().Slave.__name__)")
        out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True,
                             env=dict(os.environ, PYTHONPATH=os.path.join(REPO, "tools", "deploy")))
        self.assertEqual(out.stdout.strip(), "Slave", out.stderr)


class Downloads(unittest.TestCase):
    def test_pingpong(self):
        path = os.path.join(REPO, "config", "pingpong", "canopen_config.json")
        with open(path, encoding="utf-8") as f:
            cfg = json.load(f)
        d = dcfexport.plugin_downloads(cfg, path)[2]
        lines = ["write 2 0x%04X %d %s" % (i, s, b.hex()) for i, s, b in d.writes]
        with open(os.path.join(REPO, "test", "dump", "pingpong.expected"), encoding="utf-8") as f:
            self.assertEqual(lines, f.read().split("\n")[:-1])

    def test_config_stamp_and_save_last(self):
        cfg = base_config()
        cfg["nodes"][0].update(eds="config-check.eds", config_check=True, store_configuration=1)
        d = dcfexport.plugin_downloads(cfg, FIXTURE_CONFIG)[2]
        self.assertEqual([(i, s) for i, s, _ in d.writes[-3:]], [(0x1020, 1), (0x1020, 2), (0x1010, 1)])
        self.assertEqual(d.writes[-1][2], b"save")
        self.assertNotIn((0x1010, 1), d.final_values())
        self.assertIn('writes "save" to 0x1010 sub 1', "\n".join(d.steps()))
        date, time = dcfexport.config_stamp(d.writes[:-3], 1)
        self.assertEqual(d.final_values()[(0x1020, 1)], date.to_bytes(4, "little"))
        self.assertEqual(d.final_values()[(0x1020, 2)], time.to_bytes(4, "little"))

    def test_rpdo_deadline_and_time_cob_id(self):
        cfg = base_config()
        cfg["nodes"][0]["eds"] = "node-options.eds"
        cfg["nodes"][0]["rx_pdos"][0]["event_timer_ms"] = 250
        cfg["nodes"][0]["time_cob_id"] = "0x40000100"
        values = dcfexport.plugin_downloads(cfg, FIXTURE_CONFIG)[2].final_values()
        self.assertEqual(values[(0x1400, 5)], (250).to_bytes(2, "little"))
        self.assertEqual(values[(0x1012, 0)], (0x40000100).to_bytes(4, "little"))
        # The EDS value already: nothing to write.
        cfg["nodes"][0]["time_cob_id"] = "0x80000100"
        values = dcfexport.plugin_downloads(cfg, FIXTURE_CONFIG)[2].final_values()
        self.assertNotIn((0x1012, 0), values)

    def test_explicit_pdo_values_equal_to_the_eds_default(self):
        # dcfgen leaves these out (the EDS default); the node's real value
        # may differ, so they are written, right after the PDO is switched off.
        cfg = base_config()
        node = cfg["nodes"][0]
        node["tx_pdos"][0].update(transmission=1, inhibit_time_us=0, event_timer_ms=0)
        node["rx_pdos"][0]["transmission"] = 1
        w = dcfexport.plugin_downloads(cfg, FIXTURE_CONFIG)[2].writes
        keys = [(i, s) for i, s, _ in w]
        for key, data in (((0x1800, 2), b"\x01"), ((0x1800, 3), b"\x00\x00"), ((0x1800, 5), b"\x00\x00"),
                          ((0x1400, 2), b"\x01")):
            self.assertEqual(keys.count(key), 1, key)
            i = keys.index(key)
            self.assertEqual(w[i][2], data)
            off = [j for j, (x, s, d) in enumerate(w) if (x, s) == (key[0], 1) and d[3] & 0x80]
            on = [j for j, (x, s, d) in enumerate(w) if (x, s) == (key[0], 1) and not d[3] & 0x80]
            self.assertTrue(off and off[0] < i < on[-1], (key, off, i, on))
        # A value other than the default is dcfgen's own write, once.
        node["tx_pdos"][0]["transmission"] = 254
        w = dcfexport.plugin_downloads(cfg, FIXTURE_CONFIG)[2].writes
        self.assertEqual([d for i, s, d in w if (i, s) == (0x1800, 2)], [b"\xfe"])

    def test_firmware_step_needs_a_version(self):
        cfg = base_config()
        cfg["nodes"][0]["software_file"] = "fw/node2.bin"
        self.assertIsNone(dcfexport.plugin_downloads(cfg, FIXTURE_CONFIG)[2].firmware)
        cfg["nodes"][0]["software_version"] = 3
        self.assertEqual(dcfexport.plugin_downloads(cfg, FIXTURE_CONFIG)[2].firmware, "fw/node2.bin")


class Writer(unittest.TestCase):
    def test_only_named_lines_change(self):
        # Removing the added lines gives back the prepared EDS.
        cfg = base_config()
        text = export(cfg)["node_2.dcf"]
        with open(os.path.join(EDS_DIR, "cpp-slave.eds"), "rb") as f:
            eds, _ = edslint.prepare(f.read())
        kept, cur, dropped_keys = [], None, {"filename", "lasteds", "modifiedby", "modificationdate",
                                             "modificationtime"}
        eds_fileinfo = section(eds, "FileInfo")
        for line in text.splitlines(True):
            s = line.strip()
            if s.startswith("["):
                cur = s[1:-1].lower()
            if text.index(line) < text.index("[") and s.startswith(";") and line not in eds:
                continue  # the export's leading comment
            if cur == "devicecomissioning":
                continue
            if s.lower().startswith("parametervalue="):
                continue
            if cur == "fileinfo" and s.split("=", 1)[0].lower() in dropped_keys:
                continue
            kept.append(line)
        expected = [line for line in eds.splitlines(True)
                    if not (line.strip().split("=", 1)[0].lower() in dropped_keys and
                            line.strip().split("=", 1)[0] in eds_fileinfo)]
        self.assertEqual("".join(kept).rstrip("\n"), "".join(expected).rstrip("\n"))

    def test_values_commissioning_and_file_info(self):
        cfg = base_config()
        cfg["nodes"][0]["serial_number"] = "0x1234"
        text = export(cfg)["node_2.dcf"]
        self.assertEqual(section(text, "1017")["ParameterValue"], "0x64")
        self.assertEqual(section(text, "1800sub1")["ParameterValue"], "0x182")
        self.assertEqual(section(text, "1A00sub1")["ParameterValue"], "0x40010020")
        self.assertEqual(section(text, "DeviceComissioning"),
                         {"NodeID": "2", "NodeName": "pingpong", "Baudrate": "125", "NetNumber": "1",
                          "NetworkName": "OpenPLC CANopen", "CANopenManager": "0",
                          "LSS_SerialNumber": "0x00001234"})
        info = section(text, "FileInfo")
        self.assertEqual(info["FileName"], "node_2.dcf")
        self.assertEqual(info["LastEDS"], "cpp-slave.eds")
        self.assertEqual(info["ModificationDate"], "10-04-2026")
        self.assertEqual(info["ModificationTime"], "01:05PM")
        self.assertTrue(info["ModifiedBy"].startswith("canworks-deploy "))

    def test_compact_array_values(self):
        text = export(compact_config())["node_2.dcf"]
        self.assertEqual(section(text, "2100Value"), {"NrOfEntries": "2", "2": "0x22", "3": "0x33"})
        self.assertNotIn("ParameterValue", section(text, "2100"))

    def test_line_endings_kept(self):
        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp)
        with open(os.path.join(EDS_DIR, "cpp-slave.eds"), "rb") as f:
            data = f.read().replace(b"\r\n", b"\n").replace(b"\n", b"\r\n")
        with open(os.path.join(tmp, "crlf.eds"), "wb") as f:
            f.write(data)
        cfg = base_config()
        cfg["nodes"][0]["eds"] = "crlf.eds"
        text = export(cfg, os.path.join(tmp, "canworks.json"))["node_2.dcf"]
        self.assertEqual(text.count("\n"), text.count("\r\n"))

    def test_value_forms(self):
        self.assertEqual(dcfexport.parameter_value(b"\xff", 0x0002), "-1")
        self.assertEqual(dcfexport.parameter_value(b"\x01", 0x0001), "1")
        self.assertEqual(dcfexport.parameter_value(b"\x00\x00\x80\x3f", 0x0008), "0x3F800000")
        self.assertEqual(dcfexport.parameter_value(b"\x2c\x01", 0x0006), "0x12C")
        self.assertIsNone(dcfexport.parameter_value(b"ab", 0x0009))


class Validation(unittest.TestCase):
    def _forged(self, writes, cfg=None, eds="cpp-slave.eds"):
        """Exports with the node's download replaced by `writes`, as only a
        test can (the config checks refuse these values)."""
        cfg = cfg or base_config()
        cfg["nodes"][0]["eds"] = eds
        real = dcfexport.plugin_downloads

        def forged(*a, **kw):
            out = real(*a, **kw)
            out[2].writes = writes
            return out
        with mock.patch.object(dcfexport, "plugin_downloads", forged):
            with self.assertRaises(dcfexport.ExportFailed) as cm:
                export(cfg)
        return "\n".join(m for m, _ in cm.exception.problems)

    def test_overflow(self):
        text = self._forged([(0x1800, 2, (300).to_bytes(2, "little"))])
        self.assertIn("ParameterValue overflow in [1800sub2]", text)
        self.assertIn("node 2 (pingpong): node_2.dcf", text)

    def test_read_only(self):
        text = self._forged([(0x2101, 0, b"\x09")], eds="compact.eds")
        self.assertIn("[2101] ParameterValue", text)
        self.assertIn("AccessType ro", text)

    def test_read_only_equal_to_eds_is_fine(self):
        cfg = base_config()
        cfg["nodes"][0]["eds"] = "compact.eds"
        real = dcfexport.plugin_downloads

        def forged(*a, **kw):
            out = real(*a, **kw)
            out[2].writes = [(0x2101, 0, b"\x07")]
            return out
        with mock.patch.object(dcfexport, "plugin_downloads", forged):
            self.assertIn("node_2.dcf", export(cfg))

    def test_unsupported_baud_rate(self):
        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp)
        with open(os.path.join(EDS_DIR, "cpp-slave.eds"), encoding="utf-8") as f:
            eds = f.read().replace("BaudRate_1000=1", "BaudRate_1000=0")
        with open(os.path.join(tmp, "slow.eds"), "w", encoding="utf-8") as f:
            f.write(eds)
        cfg = base_config()
        cfg["nodes"][0]["eds"] = "slow.eds"
        cfg["adapter"]["bitrate"] = 1000000
        with self.assertRaises(dcfexport.ExportFailed) as cm:
            export(cfg, os.path.join(tmp, "canworks.json"))
        text = "\n".join(m for m, _ in cm.exception.problems)
        self.assertIn("[DeviceComissioning] Baudrate", text)
        self.assertIn("does not support 1000 kbit/s", text)

    def test_baud_rate_not_cia306(self):
        # The config schema already allows only CiA 306 rates; the DCF check
        # is the second line.
        cfg = base_config()
        cfg["adapter"]["bitrate"] = 100000
        with self.assertRaises(dcfexport.ExportFailed) as cm:
            export(cfg)
        self.assertIn("adapter.bitrate", str(cm.exception))
        node = dcfexport._load_nodes(base_config(), FIXTURE_CONFIG, None)[0]
        d = dcfexport.Download(2)
        text = export(base_config())["node_2.dcf"].replace("Baudrate=125", "Baudrate=100")
        problems = dcfexport.validate(node, d, text, base_config())
        self.assertIn("Baudrate 100 kbit/s is not a CiA 306 bit rate", str(problems))

    def test_config_errors_stop_the_export(self):
        cfg = base_config()
        cfg["nodes"][0]["node_id"] = 1  # the master's
        with self.assertRaises(dcfexport.ExportFailed) as cm:
            export(cfg)
        self.assertIn("is the master's node ID", str(cm.exception))

    def test_one_node(self):
        cfg = base_config()
        second = copy.deepcopy(cfg["nodes"][0])
        second.update(node_id=3, name="second", status_location="%IX10.1")
        for p in second["tx_pdos"] + second["rx_pdos"]:
            for e in p["entries"]:
                e["iec_location"] = e["iec_location"].replace("100", "104")
        cfg["nodes"].append(second)
        self.assertEqual(sorted(export(cfg)), ["node_2.dcf", "node_3.dcf"])
        self.assertEqual(list(export(cfg, node_id=3)), ["node_3.dcf"])
        with self.assertRaises(dcfexport.ExportFailed):
            export(cfg, node_id=9)

    def test_write_files(self):
        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp)
        out = os.path.join(tmp, "out")
        paths = dcfexport.write_files({"node_2.dcf": "a\r\n"}, out)
        self.assertEqual(paths, [os.path.join(out, "node_2.dcf")])
        with open(paths[0], "rb") as f:
            self.assertEqual(f.read(), b"a\r\n")
        self.assertEqual(os.listdir(out), ["node_2.dcf"])


class Cli(unittest.TestCase):
    def run_cli(self, *argv):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = cli.main(list(argv))
        return code, out.getvalue(), err.getvalue()

    def config_in(self, cfg):
        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp)
        shutil.copytree(EDS_DIR, os.path.join(tmp, "eds"))
        path = os.path.join(tmp, "eds", "canworks.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(cfg, f)
        return tmp, path

    def test_export(self):
        tmp, path = self.config_in(base_config())
        out_dir = os.path.join(tmp, "out")
        code, out, err = self.run_cli("--config", path, "--export-dcf", out_dir)
        self.assertEqual(code, 0, err)
        self.assertEqual(os.listdir(out_dir), ["node_2.dcf"])
        self.assertIn("wrote " + os.path.join(out_dir, "node_2.dcf"), out)
        self.assertIn("ok: 1 DCF file checked against CiA 306", out)

    def test_failure_writes_nothing(self):
        tmp, path = self.config_in(base_config())
        out_dir = os.path.join(tmp, "out")
        real = dcfexport.plugin_downloads

        def forged(*a, **kw):
            out = real(*a, **kw)
            out[2].writes = [(0x1800, 2, (300).to_bytes(2, "little"))]
            return out
        with mock.patch.object(dcfexport, "plugin_downloads", forged):
            code, out, err = self.run_cli("--config", path, "--export-dcf", out_dir)
        self.assertEqual(code, 1)
        self.assertIn("ParameterValue overflow in [1800sub2]", err)
        self.assertIn("no DCF was written", err)
        self.assertFalse(os.path.exists(out_dir))

    def test_refuses_upload_options(self):
        tmp, path = self.config_in(base_config())
        code, _, err = self.run_cli("--config", path, "--export-dcf", tmp, "--runtime", "plc.local")
        self.assertEqual(code, 1)
        self.assertIn("--export-dcf only writes DCF files", err)

    def test_excludes_other_sources(self):
        tmp, path = self.config_in(base_config())
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            cli.main(["--config", path, "--export-dcf", tmp, "--into-project", tmp])


def _canopen_check():
    path = os.environ.get("CANWORKS_CHECK") or os.path.join(REPO, "build", "canopen_check")
    return path if os.path.isfile(path) and os.access(path, os.X_OK) else None


class Links(unittest.TestCase):
    """canopen-dcf-export "Linked consumer RPDO", "Heartbeat watch entry"."""

    def setUp(self):
        doc = load_cases("cases-links.json")
        self.cfg = doc["base"]
        self.path = os.path.join(EDS_DIR, "canworks.json")

    def test_consumer_download(self):
        w = dcfexport.plugin_downloads(self.cfg, self.path)[20].writes
        start = w.index((0x1401, 1, (0x8000018A).to_bytes(4, "little")))
        self.assertEqual(w[start:start + 9], [
            (0x1401, 1, (0x8000018A).to_bytes(4, "little")), (0x1401, 2, b"\xff"), (0x1401, 5, (200).to_bytes(2, "little")),
            (0x1601, 0, b"\x00"), (0x1601, 1, (0x64110110).to_bytes(4, "little")),
            (0x1601, 2, (0x00030010).to_bytes(4, "little")), (0x1601, 0, b"\x02"),
            (0x1401, 1, (0x18A).to_bytes(4, "little")), (0x1016, 1, (0x000A012C).to_bytes(4, "little"))])

    def test_dcf_values(self):
        files, _ = dcfexport.export(self.cfg, self.path)
        text = files["node_20.dcf"]
        self.assertEqual(int(section(text, "1401sub1")["ParameterValue"], 0), 0x18A)
        self.assertEqual(int(section(text, "1601sub0")["ParameterValue"], 0), 2)
        self.assertEqual(int(section(text, "1016sub1")["ParameterValue"], 0), 0x000A012C)

    def test_watch_next_to_the_master(self):
        cfg = patched(self.cfg, [["set", "master/heartbeat_ms", 100], ["set", "nodes/1/heartbeat_consumer", True]])
        w = dcfexport.plugin_downloads(cfg, self.path)[20].writes
        hb = [x for x in w if x[0] == 0x1016]
        self.assertEqual(hb, [(0x1016, 1, (0x0001012C).to_bytes(4, "little")),
                              (0x1016, 2, (0x000A012C).to_bytes(4, "little"))])

    def test_no_link_writes_without_links(self):
        cfg = patched(self.cfg, [["delete", "links"], ["delete", "nodes/1/heartbeat_watch"],
                                 ["set", "nodes/0/tx_pdos/0/entries/1/iec_location", "%IW101"]])
        w = dcfexport.plugin_downloads(cfg, self.path)[20].writes
        self.assertFalse([x for x in w if x[0] in (0x1016, 0x1601)])


class Parity(unittest.TestCase):
    """Every accepted fixture config, the examples and the compact fixture:
    the export's download equals canopen_check --dump-writes, and its DCF
    holds the final value of every non-command write."""

    def setUp(self):
        self.check = _canopen_check()
        if not self.check:
            if os.environ.get("CANWORKS_REQUIRE_PARITY") == "1":
                self.fail("canopen_check not found (build it, or set CANWORKS_CHECK)")
            self.skipTest("canopen_check not built")

    def _run_check(self, path):
        return subprocess.run([self.check, "--dump-writes", path], capture_output=True, text=True)

    def _dump(self, path, out=None):
        out = out or self._run_check(path)
        self.assertEqual(out.returncode, 0, out.stdout + out.stderr)
        writes, steps = {}, {}
        for line in out.stdout.splitlines():
            p = line.split()
            if p and p[0] == "write":
                writes.setdefault(int(p[1]), []).append((int(p[2], 16), int(p[3]), bytes.fromhex(p[4])))
            elif p and p[0] == "step":
                steps.setdefault(int(p[1]), []).append(p[2])
        return writes, steps

    def _compare(self, cfg, path, out=None):
        writes, steps = self._dump(path, out)
        downloads = dcfexport.plugin_downloads(cfg, path)
        files = export(cfg, path)
        for node_id, d in downloads.items():
            self.assertEqual(d.writes, writes.get(node_id, []), "node %d download" % node_id)
            self.assertEqual("restore" in steps.get(node_id, []), d.restore is not None)
            text = files["node_%d.dcf" % node_id]
            for (index, sub), data in d.final_values().items():
                name = "%04Xsub%X" % (index, sub)
                got = section(text, name).get("ParameterValue") if name.lower() in text.lower() else (
                    section(text, "%04XValue" % index).get(str(sub)) if "%04XValue" % index in text
                    else section(text, "%04X" % index).get("ParameterValue"))
                self.assertIsNotNone(got, "node %d 0x%04X sub %d" % (node_id, index, sub))
                self.assertEqual(int(got, 0) & ((1 << (8 * len(data))) - 1), int.from_bytes(data, "little"))

    def _in_copy(self, cfg):
        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp)
        shutil.copytree(EDS_DIR, os.path.join(tmp, "eds"))
        path = os.path.join(tmp, "eds", "canworks.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(cfg, f)
        return path

    def test_fixture_cases(self):
        doc = load_cases()
        cases = []
        for case in doc["cases"]:
            if case["verdict"] == "accept":
                cfg = patched(doc["base"], case["patch"])
                cases.append((case["name"], cfg, self._in_copy(cfg)))
        # canopen_check takes most of the time (up to a second of CPU per case): the
        # runs go side by side, the comparisons stay in case order.
        with ThreadPoolExecutor(os.cpu_count() or 2) as pool:
            runs = [pool.submit(self._run_check, path) for _, _, path in cases]
            for (name, cfg, path), run in zip(cases, runs):
                with self.subTest(name):
                    self._compare(cfg, path, run.result())
        self.assertGreater(len(cases), 30)

    def test_link_fixture_cases(self):
        # PDO links and heartbeat watch (cases-links.json): the consumer RPDO
        # and 0x1016 writes as the plugin adds them.
        doc = load_cases("cases-links.json")
        cases = []
        for case in doc["cases"]:
            if case["verdict"] == "accept":
                cfg = patched(doc["base"], case["patch"])
                cases.append((case["name"], cfg, self._in_copy(cfg)))
        with ThreadPoolExecutor(os.cpu_count() or 2) as pool:
            runs = [pool.submit(self._run_check, path) for _, _, path in cases]
            for (name, cfg, path), run in zip(cases, runs):
                with self.subTest(name):
                    self._compare(cfg, path, run.result())
        self.assertGreater(len(cases), 5)

    def test_compact_fixture(self):
        cfg = compact_config()
        self._compare(cfg, self._in_copy(cfg))

    def test_examples(self):
        for name in ("pingpong", "rtd-sensor"):
            with self.subTest(name):
                tmp = tempfile.mkdtemp()
                self.addCleanup(shutil.rmtree, tmp)
                shutil.copytree(os.path.join(REPO, "config", name), os.path.join(tmp, name))
                path = os.path.join(tmp, name, "canopen_config.json")
                with open(path, encoding="utf-8") as f:
                    self._compare(json.load(f), path)


if __name__ == "__main__":
    unittest.main()
