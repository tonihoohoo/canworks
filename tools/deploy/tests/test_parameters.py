"""Device parameters: read-all, backup DCF, compare, restore and store
(canopen-device-parameters), against the fake diagnostics channel."""

import datetime
import io
import json
import os
import shutil
import sys
import tempfile
import unittest
from unittest import mock

from openplc_canopen_deploy import diag
from openplc_canopen_deploy import eds as eds_mod
from openplc_canopen_deploy import parameters as P

from . import fake_diag
from .helpers import REPO

RTD_EDS = os.path.join(REPO, "config", "rtd-sensor", "rtd8.eds")
RTD_CONFIG = os.path.join(REPO, "config", "rtd-sensor", "canopen_config.json")
SERVO_EDS = os.path.join(REPO, "test", "fixtures", "eds", "drives", "servo-drive.eds")
COMPACT_EDS = os.path.join(REPO, "test", "fixtures", "eds", "compact.eds")
NOW = datetime.datetime(2026, 10, 5, 14, 30, 0)
NODE = 5


def device_values(eds, node_id=NODE):
    """{(index, sub): bytes} a device with factory settings would answer."""
    out = {}
    for e in P.readable(eds):
        data = P.text_value(e.obj.default, e.data_type, node_id)
        if data is None:
            size = (P._int_type(e.data_type) or (4,))[0]
            name = diag.type_name(e.data_type)
            data = b"dev" if name == "VISIBLE_STRING" else bytes(8 if name == "REAL64" else size)
        out[e.key] = data
    out[(0x1018, 1)] = (0x195).to_bytes(4, "little")
    out[(0x1018, 2)] = (0x3E8).to_bytes(4, "little")
    out[(0x1018, 3)] = (0x10001).to_bytes(4, "little")
    out[(0x1018, 4)] = (0x1234).to_bytes(4, "little")
    return out


class FakeDevice(fake_diag.FakePlugin):
    """The fake channel with node 5 answering from an EDS."""

    def __init__(self, eds_path=RTD_EDS, allow_changes=True):
        super().__init__(allow_changes=allow_changes)
        self.eds, _ = P.read_eds(eds_path)
        for key, data in device_values(self.eds).items():
            self.objects[(NODE,) + key] = data
        self.present.add(NODE)
        self.configured.add(NODE)

    def value(self, index, sub):
        return self.objects[(NODE, index, sub)]

    def set(self, index, sub, data):
        self.objects[(NODE, index, sub)] = data

    def sdo_requests(self, op):
        return [(r["index"], r["subindex"]) for r in self.requests if r.get("op") == op and r.get("node") == NODE]


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp)

    def connect(self, fp):
        c = diag.Client("127.0.0.1", fp.port, fake_diag.TOKEN)
        c.connect()
        self.addCleanup(c.close)
        return c


class ReadAllTest(Base):
    def test_reads_every_readable_entry_once(self):
        with FakeDevice() as fp:
            eds = fp.eds
            r = P.read_all(self.connect(fp), NODE, eds)
            want = [e.key for e in P.entries(eds) if e.access in P.READABLE and e.data_type != 0x0F]
            self.assertEqual(fp.sdo_requests("sdo_read"), want)
            self.assertEqual(len(r.values), len(want))
            self.assertIsNone(r.stopped)
            self.assertFalse(fp.sdo_requests("sdo_write"))
            for req in fp.requests:
                self.assertEqual(req["timeout_ms"], P.READ_TIMEOUT_MS)

    def test_domain_and_write_only_entries_are_skipped(self):
        eds, _ = P.read_eds(RTD_EDS)
        keys = {e.key for e in P.readable(eds)}
        self.assertNotIn((0x2500, 1), keys)  # wo password
        for e in P.entries(eds):
            if e.data_type == 0x0F:
                self.assertNotIn(e.key, keys)

    def test_abort_is_recorded_and_the_read_goes_on(self):
        with FakeDevice() as fp:
            del fp.objects[(NODE, 0x6110, 3)]
            r = P.read_all(self.connect(fp), NODE, fp.eds)
            self.assertEqual(r.failed[(0x6110, 3)][0], 0x06020000)
            self.assertIn((0x6110, 4), r.values)
            self.assertIsNone(r.stopped)

    def test_three_timeouts_stop(self):
        with FakeDevice() as fp:
            fp.present.discard(NODE)
            r = P.read_all(self.connect(fp), NODE, fp.eds)
            self.assertEqual(len(fp.sdo_requests("sdo_read")), 3)
            self.assertIn("does not answer SDO", r.stopped)
            self.assertIn("STOPPED", r.stopped)

    def test_cancel(self):
        with FakeDevice() as fp:
            seen = []
            r = P.read_all(self.connect(fp), NODE, fp.eds, progress=lambda d, t: seen.append(d),
                           cancel=lambda: len(seen) >= 5)
            self.assertTrue(r.cancelled)
            self.assertEqual(len(r.values), 5)

    def test_works_read_only(self):
        with FakeDevice(allow_changes=False) as fp:
            r = P.read_all(self.connect(fp), NODE, fp.eds)
            self.assertTrue(r.values)


class BackupTest(Base):
    def backup(self, eds_path, name="rtd"):
        with FakeDevice(eds_path) as fp:
            fp.set(0x1008, 0, b"RTD-8")
            for key, low in (((0x2212, 1), 16), ((0x2213, 1), 64)):  # servo drive encoders: LowLimit, no default
                if (NODE,) + key in fp.objects:
                    fp.set(*key, low.to_bytes(4, "little"))
            del fp.objects[(NODE, 0x1018, 3)]
            client = self.connect(fp)
            eds, text = P.read_eds(eds_path)
            r = P.read_all(client, NODE, eds)
            dcf, file_name = P.build_backup(text, eds, os.path.basename(eds_path), r, 125, name, "plc.local", NOW)
            return fp, eds, text, r, dcf, file_name

    def test_round_trip_and_lint(self):
        for path in (RTD_EDS, SERVO_EDS, COMPACT_EDS):
            with self.subTest(eds=os.path.basename(path)):
                fp, eds, text, r, dcf, _ = self.backup(path)
                self.assertEqual(P.lint_backup(dcf, text, NODE), [])
                b = P.read_backup(dcf, "b.dcf")
                self.assertEqual(b.node_id, NODE)
                for key, data in r.values.items():
                    if key == (0x2100, 0):  # CompactSubObj count: no section holds it
                        continue
                    self.assertIn(key, b.values, key)
                    self.assertTrue(P.same(data, b.values[key], eds.find(*key).data_type), key)

    def test_file_content(self):
        fp, eds, text, r, dcf, name = self.backup(RTD_EDS)
        self.assertEqual(name, "node5-rtd-20261005-143000.dcf")
        self.assertIn("[DeviceComissioning]\nNodeID=5\nNodeName=rtd\nBaudrate=125\nLSS_SerialNumber=0x00001234\n",
                      dcf.replace("\r\n", "\n"))
        self.assertIn("Description=Backup of node 5 read from plc.local at 2026-10-05 14:30:00", dcf)
        self.assertIn("not read: 0x1018 sub 3: 0x06020000", dcf)
        b = P.read_backup(dcf)
        self.assertEqual(b.values[(0x1008, 0)], b"RTD-8")
        self.assertIn("ParameterValue=RTD-8", dcf)
        self.assertEqual(b.identity(), {"vendor_id": 0x195, "product_code": 0x3E8, "serial_number": 0x1234})

    def test_identity_not_read_is_said(self):
        with FakeDevice() as fp:
            del fp.objects[(NODE, 0x1018, 1)]
            eds, text = P.read_eds(RTD_EDS)
            r = P.read_all(self.connect(fp), NODE, eds)
            dcf, _ = P.build_backup(text, eds, "rtd8.eds", r, now=NOW)
            self.assertIn("restore cannot check the device", dcf)

    def test_other_tools_dcf(self):
        # A DCF with ParameterValue lines, quoted string and $NODEID.
        with open(RTD_EDS, "rb") as f:
            text = f.read().decode("latin-1")
        text = text.replace("[6110sub1]\n", "[6110sub1]\nParameterValue=0x0020\n", 1).replace(
            "[6110sub1]\r\n", "[6110sub1]\r\nParameterValue=0x0020\r\n", 1)
        text += "\n[DeviceComissioning]\nNodeID=7\n"
        b = P.read_backup(text.encode("latin-1"))
        self.assertEqual(b.node_id, 7)
        self.assertEqual(b.values[(0x6110, 1)], b"\x20\x00")


class CompareTest(Base):
    def test_against_backup(self):
        with FakeDevice() as fp:
            client = self.connect(fp)
            r = P.read_all(client, NODE, fp.eds)
            _, text = P.read_eds(RTD_EDS)
            dcf, _ = P.build_backup(text, fp.eds, "rtd8.eds", r, now=NOW)
            fp.set(0x6110, 1, (0).to_bytes(2, "little"))
            backup = P.read_backup(dcf)
            keys = P.compare_keys(fp.eds, backup.values)
            rows = P.compare(fp.eds, P.read_entries(client, NODE, keys), backup.values)
            self.assertEqual(rows[0]["result"], "different")
            self.assertEqual((rows[0]["index"], rows[0]["subindex"]), (0x6110, 1))
            self.assertEqual(rows[0]["reference"], "30 (0x001E)")
            self.assertEqual(rows[0]["device"], "0 (0x0000)")
            self.assertEqual(P.summary(rows)["different"], 1)

    def test_read_only_entries_only_on_request(self):
        eds, _ = P.read_eds(RTD_EDS)
        ro = [e.key for e in P.entries(eds) if e.access == "ro"]
        self.assertFalse(set(ro) & set(P.compare_keys(eds, {})))
        self.assertTrue(set(ro) <= set(P.compare_keys(eds, {}, include_ro=True)))

    def test_against_eds_defaults(self):
        with FakeDevice() as fp:
            fp.set(0x6110, 2, (40).to_bytes(2, "little"))
            ref = P.reference_from_eds(fp.eds, NODE)
            client = self.connect(fp)
            rows = P.compare(fp.eds, P.read_entries(client, NODE, P.compare_keys(fp.eds, ref)), ref)
            diff = [(r["index"], r["subindex"]) for r in rows if r["result"] == "different"]
            self.assertIn((0x6110, 2), diff)

    def test_against_config(self):
        with FakeDevice() as fp:
            with open(RTD_CONFIG, encoding="utf-8") as f:
                cfg = json.load(f)
            writes, owned = P.config_writes(cfg, RTD_CONFIG, NODE)
            self.assertEqual(writes[(0x6110, 1)], (30).to_bytes(2, "little"))
            client = self.connect(fp)
            keys = P.compare_keys(fp.eds, writes, only_reference=True)
            rows = P.compare(fp.eds, P.read_entries(client, NODE, keys), writes, only_reference=True)
            self.assertTrue(all(r["reference"] is not None for r in rows))
            by_key = {(r["index"], r["subindex"]): r["result"] for r in rows}
            self.assertEqual(by_key[(0x6110, 1)], "equal")  # EDS default 0x1E == 30

    def test_number_and_string_comparison(self):
        self.assertTrue(P.same(b"\x0a", b"\x0a\x00", 0x0006))
        self.assertTrue(P.same(P.text_value("0x0A", 0x0006, 1), P.text_value("10", 0x0006, 1), 0x0006))
        self.assertTrue(P.same(b"abc\0\0", b"abc", 0x0009))
        self.assertFalse(P.same(b"\x01\x02", b"\x01\x03", 0x000A))
        self.assertEqual(P.text_value("$NODEID+0x180", 0x0007, 5), (0x185).to_bytes(4, "little"))

    def test_limits(self):
        """improve-od-browser 1.1: LowLimit/HighLimit as numbers of the entry's type."""
        eds, _ = P.read_eds(RTD_EDS)
        e = next(x for x in P.entries(eds) if x.key == (0x6110, 1))
        d = e.to_json(NODE)
        self.assertEqual((d["low_limit"], d["high_limit"]), (0x1E, 0x21))
        self.assertEqual(d["sub_name"], "AI0_Sensor_Type")
        self.assertEqual(d["name"], "AI Sensor Type: AI0_Sensor_Type")
        self.assertNotIn("low_limit", next(x for x in P.entries(eds) if x.key == (0x1018, 1)).to_json(NODE))
        self.assertEqual(P.limit_number("0xFF", 0x0002, 1), -1)  # INTEGER8 as two's complement
        self.assertEqual(P.limit_number("-5", 0x0003, 1), -5)
        self.assertEqual(P.limit_number("$NODEID+0x180", 0x0007, 5), 0x185)
        self.assertEqual(P.limit_number("1.5", 0x0008, 1), 1.5)
        self.assertIsNone(P.limit_number("", 0x0007, 1))
        self.assertIsNone(P.limit_number("x", 0x0007, 1))
        self.assertEqual(eds.object_types[0x6110], 0x8)
        self.assertEqual(eds.object_types[0x1000], 0x7)


class PlanTest(Base):
    def plan(self, backup_values, live_values=None, eds_path=RTD_EDS, **kw):
        eds, _ = P.read_eds(eds_path)
        backup = P.Backup(eds, "", dict(backup_values), NODE)
        live = P.Reading(NODE)
        live.values = dict(live_values if live_values is not None else device_values(eds))
        return P.restore_plan(backup, eds, live, **kw)

    def identity(self, changes=None):
        ident = {(0x1018, 1): (0x195).to_bytes(4, "little"), (0x1018, 2): (0x3E8).to_bytes(4, "little"),
                 (0x1018, 3): (0x10001).to_bytes(4, "little"), (0x1018, 4): (0x1234).to_bytes(4, "little")}
        ident.update(changes or {})
        return ident

    def test_skip_reasons(self):
        values = self.identity()
        values.update({(0x6110, 1): b"\x20\x00", (0x6110, 2): b"\x21\x00", (0x1017, 0): b"\x64\x00",
                       (0x1800, 5): b"\x10\x00", (0x1010, 1): b"save", (0x2000, 1): b"\x01", (0x7130, 1): b"\x01\x00"})
        config = {(0x6110, 1): b"\x1e\x00"}
        owned = {(0x6110, 2): "type2"}
        plan = self.plan(values, config=config, owned=owned)
        reasons = {(s["index"], s["subindex"]): s["reason"] for s in plan.skipped}
        self.assertEqual(reasons[(0x6110, 1)], "written by the configuration at boot")
        self.assertEqual(reasons[(0x6110, 2)], "written by SDO variable type2")
        self.assertIn("include communication objects", reasons[(0x1017, 0)])
        self.assertNotIn((0x7130, 1), reasons)  # read-only value: compare only
        self.assertEqual([(w["index"], w["subindex"]) for w in plan.writes], [(0x2000, 1)])
        plan = self.plan(values, config=config, owned=owned, include_comm=True)
        reasons = {(s["index"], s["subindex"]): s["reason"] for s in plan.skipped}
        self.assertEqual(reasons[(0x1800, 5)], "PDO object, set by the configuration or the device")
        self.assertEqual(reasons[(0x1010, 1)], "store/restore command")
        self.assertIn((0x1017, 0), [(w["index"], w["subindex"]) for w in plan.writes])
        self.assertNotIn(0x1010, [w["index"] for w in plan.writes])

    def test_only_differences_in_order_sub0_last(self):
        eds, _ = P.read_eds(RTD_EDS)
        live = device_values(eds)
        values = self.identity()
        values.update({(0x6112, 2): b"\x01", (0x6110, 3): b"\x20\x00", (0x6110, 1): live[(0x6110, 1)],
                       (0x2000, 2): b"\x00\x02"})
        plan = self.plan(values, live)
        self.assertEqual([(w["index"], w["subindex"]) for w in plan.writes], [(0x2000, 2), (0x6110, 3), (0x6112, 2)])
        self.assertEqual([(u["index"], u["subindex"]) for u in plan.unchanged], [(0x6110, 1)])

    def test_sub0_after_subindices(self):
        sub = lambda: eds_mod.SubObject(0x0005, "rw", False)  # noqa: E731
        items = [(P.Entry(0x2001, s, sub()), b"") for s in (2, 0, 1)] + [(P.Entry(0x2000, 0, sub()), b"")]
        self.assertEqual([e.key for e, _ in P._restore_order(items)],
                         [(0x2000, 0), (0x2001, 1), (0x2001, 2), (0x2001, 0)])

    def test_unreadable_entry_is_written(self):
        values = self.identity()
        values[(0x6110, 4)] = b"\x20\x00"
        live = {k: v for k, v in self.identity().items()}
        plan = self.plan(values, live)
        self.assertEqual(plan.writes[0]["device"], None)

    def test_identity(self):
        plan = self.plan(self.identity({(0x1018, 2): (0x3E9).to_bytes(4, "little")}),
                         self.identity())
        self.assertIn("product code differs: backup 0x000003E9, device 0x000003E8", plan.refused)
        plan = self.plan(self.identity({(0x1018, 2): (0x3E9).to_bytes(4, "little")}),
                         self.identity(), ignore_identity=True)
        self.assertIsNone(plan.refused)
        plan = self.plan(self.identity({(0x1018, 3): (0x20001).to_bytes(4, "little"),
                                          (0x1018, 4): (0x9).to_bytes(4, "little")}), self.identity())
        self.assertIsNone(plan.refused)
        levels = {i["field"]: i["level"] for i in plan.identity}
        self.assertEqual(levels, {"revision number": "warning", "serial number": "info"})
        backup = self.identity()
        del backup[(0x1018, 1)]
        plan = self.plan(backup, self.identity())
        self.assertIn("the backup has no vendor ID", plan.refused)


class RestoreTest(Base):
    def make_plan(self, fp, client, changes, **kw):
        values = device_values(fp.eds)
        values.update(changes)
        backup = P.Backup(fp.eds, "", values, NODE)
        keys = P.plan_keys(backup, fp.eds)
        return P.restore_plan(backup, fp.eds, P.read_entries(client, NODE, keys), **kw)

    def test_writes_differences_only(self):
        with FakeDevice() as fp:
            client = self.connect(fp)
            plan = self.make_plan(fp, client, {(0x6110, 5): b"\x20\x00", (0x6112, 1): b"\x01"})
            fp.requests.clear()
            res = P.restore(client, NODE, plan)
            self.assertEqual(fp.sdo_requests("sdo_write"), [(0x6110, 5), (0x6112, 1)])
            self.assertEqual(fp.value(0x6110, 5), b"\x20\x00")
            self.assertEqual(len(res["written"]), 2)
            self.assertIn("not stored", res["note"])

    def test_failed_write_continues_and_hold_released(self):
        with FakeDevice() as fp:
            client = self.connect(fp)
            plan = self.make_plan(fp, client, {(0x6110, 5): b"\x20\x00", (0x6112, 1): b"\x01"})
            fp.refuse_writes[(NODE, 0x6110, 5)] = 0x06090030
            fp.requests.clear()
            res = P.restore(client, NODE, plan, hold=True)
            ops = [(r["op"], r.get("command")) for r in fp.requests]
            self.assertEqual(ops[0], ("nmt", "preop"))
            self.assertEqual(ops[-1], ("nmt", "start"))
            self.assertEqual(res["failed"][0]["abort_code"], 0x06090030)
            self.assertEqual(len(res["written"]), 1)
            self.assertTrue(res["released"])

    def test_cancel_releases_hold(self):
        with FakeDevice() as fp:
            client = self.connect(fp)
            plan = self.make_plan(fp, client, {(0x6110, 5): b"\x20\x00", (0x6112, 1): b"\x01"})
            fp.requests.clear()
            res = P.restore(client, NODE, plan, hold=True, cancel=lambda: True)
            self.assertTrue(res["cancelled"])
            self.assertEqual([r.get("command") for r in fp.requests], ["preop", "start"])

    def test_refused_plan_writes_nothing(self):
        with FakeDevice() as fp:
            client = self.connect(fp)
            plan = self.make_plan(fp, client, {(0x1018, 2): b"\x00\x00\x00\x00", (0x6112, 1): b"\x01"})
            fp.requests.clear()
            with self.assertRaises(P.ParameterError):
                P.restore(client, NODE, plan)
            self.assertFalse(fp.requests)

    def test_read_only_runtime(self):
        with FakeDevice(allow_changes=False) as fp:
            client = self.connect(fp)
            plan = self.make_plan(fp, client, {(0x6112, 1): b"\x01"})
            with self.assertRaises(diag.DiagError):
                P.restore(client, NODE, plan, hold=True)


class StoreTest(Base):
    def test_store_writes_save_once(self):
        with FakeDevice() as fp:
            fp.set(0x1010, 1, b"\0\0\0\0")
            res = P.store(self.connect(fp), NODE, fp.eds)
            self.assertTrue(res["stored"])
            writes = [r for r in fp.requests if r["op"] == "sdo_write"]
            self.assertEqual(len(writes), 1)
            self.assertEqual((writes[0]["index"], writes[0]["subindex"], writes[0]["data"]), (0x1010, 1, "73 61 76 65"))
            self.assertEqual(writes[0]["timeout_ms"], P.STORE_TIMEOUT_MS)

    def test_no_store_object(self):
        eds, _ = P.read_eds(os.path.join(REPO, "config", "pingpong", "cpp-slave.eds"))
        with FakeDevice() as fp:
            with self.assertRaises(P.ParameterError) as cm:
                P.store(self.connect(fp), NODE, eds)
            self.assertIn("no store object", str(cm.exception))
            self.assertFalse([r for r in fp.requests if r["op"] == "sdo_write"])


class CliTest(Base):
    def run_cli(self, fp, *argv, stdin=""):
        out, err = io.StringIO(), io.StringIO()
        with mock.patch.object(sys, "stderr", err), mock.patch.object(sys, "stdin", io.StringIO(stdin)), \
                mock.patch.dict(os.environ, {diag.TOKEN_ENV: fake_diag.TOKEN}):
            try:
                code = diag.run(diag.parser().parse_args(["--runtime", fp.runtime] + list(argv)), out)
            except diag.DiagError as e:
                err.write(str(e))
                code = 1
        return code, out.getvalue(), err.getvalue()

    def test_backup_compare_restore_store(self):
        with FakeDevice() as fp:
            fp.set(0x1010, 1, b"\0\0\0\0")
            path = os.path.join(self.tmp, "b.dcf")
            code, out, _ = self.run_cli(fp, "backup", "5", "-o", path, "--config", RTD_CONFIG)
            self.assertEqual(code, 0, out)
            self.assertRegex(out, r"b\.dcf: \d+ entries read, 0 not read")
            with open(path, encoding="utf-8") as f:
                self.assertIn("NodeName=rtd", f.read())

            fp.set(0x6112, 3, b"\x02")
            code, out, err = self.run_cli(fp, "compare", "5", "--with", path, "--config", RTD_CONFIG)
            self.assertEqual(code, 0, err)
            self.assertIn("0x6112 sub 3   different", out)

            fp.requests.clear()
            code, out, _ = self.run_cli(fp, "restore", "5", path, "--config", RTD_CONFIG, "--dry-run")
            self.assertEqual(code, 0)
            self.assertIn("write 0x6112 sub 3", out)
            self.assertIn("written by the configuration at boot", out)  # 0x6110 sub 1-4 from the startup SDOs
            self.assertFalse(fp.sdo_requests("sdo_write"))

            code, out, err = self.run_cli(fp, "restore", "5", path, "--config", RTD_CONFIG, stdin="n\n")
            self.assertNotEqual(code, 0)
            self.assertIn("not confirmed", err)
            self.assertFalse(fp.sdo_requests("sdo_write"))

            code, out, err = self.run_cli(fp, "restore", "5", path, "--config", RTD_CONFIG, "--yes")
            self.assertEqual(code, 0, err)
            self.assertIn("1 written, 0 failed", out)
            self.assertEqual(fp.value(0x6112, 3), b"\x00")
            self.assertNotIn((0x1010, 1), fp.sdo_requests("sdo_write"))

            code, out, err = self.run_cli(fp, "store", "5", "--config", RTD_CONFIG, stdin="no\n")
            self.assertNotEqual(code, 0)
            self.assertNotIn((0x1010, 1), fp.sdo_requests("sdo_write"))
            code, out, err = self.run_cli(fp, "store", "5", "--config", RTD_CONFIG, stdin="y\n")
            self.assertEqual(code, 0, err)
            self.assertEqual(fp.sdo_requests("sdo_write").count((0x1010, 1)), 1)

    def test_compare_with_config_and_eds(self):
        with FakeDevice() as fp:
            code, out, err = self.run_cli(fp, "compare", "5", "--with-config", "--config", RTD_CONFIG)
            self.assertEqual(code, 0, err)
            code, out, err = self.run_cli(fp, "compare", "5", "--with-eds-defaults", "--eds", RTD_EDS)
            self.assertEqual(code, 0, err)
            self.assertIn("0 different", out)

    def test_failed_write_exits_non_zero(self):
        with FakeDevice() as fp:
            path = os.path.join(self.tmp, "b.dcf")
            self.assertEqual(self.run_cli(fp, "backup", "5", "-o", path, "--eds", RTD_EDS)[0], 0)
            fp.set(0x6112, 3, b"\x02")
            fp.refuse_writes[(NODE, 0x6112, 3)] = 0x08000022
            code, out, err = self.run_cli(fp, "restore", "5", path, "--eds", RTD_EDS, "--yes")
            self.assertNotEqual(code, 0)
            self.assertIn("present device state", out)

    def test_wrong_device_refused(self):
        with FakeDevice() as fp:
            path = os.path.join(self.tmp, "b.dcf")
            self.assertEqual(self.run_cli(fp, "backup", "5", "-o", path, "--eds", RTD_EDS)[0], 0)
            fp.set(0x1018, 2, (0x777).to_bytes(4, "little"))
            fp.set(0x6112, 3, b"\x02")
            code, out, err = self.run_cli(fp, "restore", "5", path, "--eds", RTD_EDS, "--yes")
            self.assertNotEqual(code, 0)
            self.assertIn("product code differs", err)
            self.assertFalse(fp.sdo_requests("sdo_write"))

    def test_silent_node(self):
        with FakeDevice() as fp:
            fp.present.discard(NODE)
            code, out, err = self.run_cli(fp, "backup", "5", "-o", os.path.join(self.tmp, "x.dcf"), "--eds", RTD_EDS)
            self.assertNotEqual(code, 0)
            self.assertIn("does not answer SDO", err)


# Node 2 on two networks: the RTD module on io (125 kbit/s), the servo drive
# on drives (500 kbit/s).
TWO_NETWORKS = [{"name": "io", "interface": "vcan0", "bitrate": 125000, "master_node_id": 1},
                {"name": "drives", "interface": "vcan1", "bitrate": 500000, "master_node_id": 1}]


def two_network_config(folder):
    for path in (RTD_EDS, SERVO_EDS):
        shutil.copy(path, folder)
    cfg = {"schema_version": 2, "networks": [
        {"name": net["name"], "adapter": {"type": "socketcan", "interface": net["interface"],
                                          "bitrate": net["bitrate"]},
         "master": {"node_id": 1},
         "nodes": [{"node_id": 2, "name": name, "eds": os.path.basename(eds)}]}
        for net, name, eds in ((TWO_NETWORKS[0], "rtd", RTD_EDS), (TWO_NETWORKS[1], "drive", SERVO_EDS))]}
    path = os.path.join(folder, "canopen.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(cfg, f)
    return path


class TwoNetworkDevices(fake_diag.FakePlugin):
    """A plugin with networks io and drives, node 2 answering on each from
    its own EDS."""

    def __init__(self):
        super().__init__(allow_changes=True, networks=TWO_NETWORKS)
        for name, path in (("io", RTD_EDS), ("drives", SERVO_EDS)):
            net = self.network(name)
            eds, _ = P.read_eds(path)
            for key, data in device_values(eds, 2).items():
                net.objects[(2,) + key] = data
            net.present.add(2)
        self.network("drives").objects[(2, 0x1018, 2)] = (0x3E9).to_bytes(4, "little")

    def sdo_requests(self, op, network):
        return [(r["index"], r["subindex"]) for r in self.requests
                if r.get("op") == op and r.get("node") == 2 and r.get("network") == network]


class NetworkTest(Base):
    run_cli = CliTest.run_cli

    def setUp(self):
        super().setUp()
        self.config = two_network_config(self.tmp)

    def test_backup_on_each_network(self):
        with TwoNetworkDevices() as fp:
            for network, eds_path, name, kbit, servo in (("drives", SERVO_EDS, "drive", 500, True),
                                                          ("io", RTD_EDS, "rtd", 125, False)):
                path = os.path.join(self.tmp, "%s.dcf" % network)
                fp.requests.clear()
                code, out, err = self.run_cli(fp, "backup", "2", "--network", network, "-o", path,
                                              "--config", self.config)
                self.assertEqual(code, 0, err)
                self.assertRegex(out, r"%s\.dcf: \d+ entries read, 0 not read" % network)
                # Every read went to that network, entry by entry of that node's EDS.
                eds, _ = P.read_eds(eds_path)
                self.assertEqual(sorted(fp.sdo_requests("sdo_read", network)), sorted(e.key for e in P.readable(eds)))
                self.assertFalse([r for r in fp.requests if r.get("network") != network])
                with open(path, encoding="utf-8") as f:
                    text = f.read()
                self.assertIn("NodeName=%s" % name, text)
                self.assertIn("Baudrate=%d" % kbit, text)
                self.assertEqual("[6040]" in text, servo)  # the drive's controlword

    def test_compare_restore_store_on_drives(self):
        with TwoNetworkDevices() as fp:
            path = os.path.join(self.tmp, "drives.dcf")
            self.assertEqual(self.run_cli(fp, "backup", "2", "--network", "drives", "-o", path,
                                          "--config", self.config)[0], 0)
            code, out, err = self.run_cli(fp, "compare", "2", "--with", path, "--network", "drives",
                                          "--config", self.config)
            self.assertEqual(code, 0, err)
            self.assertIn(" 0 different", out)
            fp.requests.clear()
            code, out, err = self.run_cli(fp, "restore", "2", path, "--network", "drives", "--config", self.config,
                                          "--dry-run")
            self.assertEqual(code, 0, err)
            self.assertIn("0 to write", out)
            fp.requests.clear()
            code, out, err = self.run_cli(fp, "store", "2", "--network", "drives", "--config", self.config, "--yes")
            self.assertEqual(code, 0, err)
            self.assertEqual(fp.sdo_requests("sdo_write", "drives"), [(0x1010, 1)])
            self.assertFalse(fp.sdo_requests("sdo_write", "io"))

    def test_network_needed(self):
        with TwoNetworkDevices() as fp:
            for argv in (["backup", "2"], ["compare", "2", "--with-eds-defaults"], ["store", "2", "--yes"],
                         ["restore", "2", "x.dcf"]):
                code, _, err = self.run_cli(fp, *(argv + ["--config", self.config]))
                self.assertEqual(code, 1, argv)
                self.assertIn("(io, drives); give --network NAME", err)
            code, _, err = self.run_cli(fp, "backup", "2", "--network", "motion", "--config", self.config)
            self.assertEqual(code, 1)
            self.assertIn("no network 'motion'", err)
        # The config alone names the networks too, also for a runtime with one.
        with self.assertRaises(P.ParameterError) as cm:
            P.node_context(2, self.config)
        self.assertIn("2 networks (io, drives); name one with --network NAME", str(cm.exception))
        with self.assertRaises(P.ParameterError) as cm:
            P.node_context(2, self.config, network="motion")
        self.assertIn("no network 'motion' in the config (io, drives)", str(cm.exception))
        with self.assertRaises(P.ParameterError) as cm:
            P.node_context(5, self.config, network="io")
        self.assertIn("node 5 is not on network 'io'", str(cm.exception))
        ctx = P.node_context(2, self.config, network="drives")
        self.assertEqual((ctx.name, ctx.bitrate_kbit, ctx.eds_name), ("drive", 500, "servo-drive.eds"))


if __name__ == "__main__":
    unittest.main()
