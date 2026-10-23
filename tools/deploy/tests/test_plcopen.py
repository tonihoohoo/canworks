"""PLCopen XML export (canworks.plcopen, canworks.plcopen_targets and the
CODESYS script import_canworks_modbus.py): the ST parser, the TC6 writer
against the PLCopen schema, the three targets' files (golden files), the
CLI, the CODESYS script on the fake script engine, and, with the pinned truST
CLI (CANWORKS_TRUST, test/plcopen/fetch-trust.sh), truST's import and build."""

import contextlib
import io
import json
import os
import shutil
import subprocess
import tempfile
import unittest
import xml.etree.ElementTree as ET

from canworks import __version__, cli, editorproject, plcopen, plcopen_targets

from . import fake_codesys
from .helpers import tmpdir
from .test_contract import REPO

EXAMPLE_DIR = os.path.join(REPO, "examples", "openplc-modbus")
DATA = os.path.join(os.path.dirname(__file__), "data", "plcopen")
XSD = os.path.join(DATA, "tc6_xml_v201.xsd")
NS = {"p": plcopen.NS}
CREATED = "2026-10-23T00:00:00"


def link_config(dir_, mailboxes=True):
    """The OpenPLC Modbus example as a PLC link config for another PLC,
    with its EDS files, in dir_; returns (path, cfg)."""
    for name in os.listdir(EXAMPLE_DIR):
        if name.endswith((".eds", ".json")):
            shutil.copy(os.path.join(EXAMPLE_DIR, name), dir_)
    path = os.path.join(dir_, "canworks.json")
    with open(path, encoding="utf-8") as f:
        cfg = json.load(f)
    b = cfg["bridge"]
    del b["openplc"]
    b.update({"plc_link": True, "listen": "0.0.0.0:1502", "writers": ["192.168.10.20"]})
    if mailboxes == "trimmed":
        # What fits truST's one request each way: one request mailbox.
        b["mailboxes"].update({"requests": 1, "receive": False, "network_info": False, "cyclic_jobs": 0})
    elif not mailboxes:
        del b["mailboxes"]
    with open(path, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2)
    return path, cfg


def export(test, target, mailboxes=None, **kw):
    """{file name: text} of the example's export for target."""
    d = tmpdir(test)
    path, cfg = link_config(d, mailboxes=target != "trust" if mailboxes is None else mailboxes)
    kw.setdefault("created", CREATED)
    if target == "codesys":
        kw.setdefault("host", "192.168.10.5")
    return plcopen_targets.files(cfg, editorproject.declarations(cfg, path), target, config_name="canworks.json",
                                 **kw)


def schema_errors(text):
    """Problems of an XML text against the TC6 2.01 schema, or None when no
    validator is at hand (xmllint or lxml)."""
    text = text.replace("tc6_0200", "tc6_0201")
    try:
        from lxml import etree
    except ImportError:
        etree = None
    if etree is not None:
        schema = etree.XMLSchema(etree.parse(XSD))
        doc = etree.fromstring(text.encode("utf-8"))
        return [] if schema.validate(doc) else [str(e) for e in schema.error_log]
    if shutil.which("xmllint"):
        with tempfile.TemporaryDirectory() as tmp:
            p = os.path.join(tmp, "x.xml")
            with open(p, "w", encoding="utf-8") as f:
                f.write(text)
            r = subprocess.run(["xmllint", "--noout", "--schema", XSD, p], capture_output=True, text=True)
            return [] if r.returncode == 0 else r.stderr.splitlines()
    return None


class ParseSt(unittest.TestCase):
    SOURCE = """(* Adds. *)
FUNCTION_BLOCK FB_X
VAR_INPUT
  A, B : INT := 3; (* two inputs *)
  T : TIME;
END_VAR
VAR_OUTPUT
  Q : WORD; // the sum
END_VAR
VAR_IN_OUT
  LINK : ARRAY[0..9] OF WORD;
END_VAR
VAR CONSTANT
  K : UINT := 7;
END_VAR
VAR
  s : STRING[20] := 'a; b';
  io AT %IB4 : BYTE;
END_VAR
Q := INT_TO_WORD(A + B); (* END_FUNCTION_BLOCK in a comment *)
END_FUNCTION_BLOCK

FUNCTION F_Y : BOOL
(* Is IN set? *)
VAR_INPUT
  IN : BOOL;
END_VAR
F_Y := IN;
END_FUNCTION
"""

    def test_pous(self):
        fb, fn = plcopen.parse_st(self.SOURCE)
        self.assertEqual((fb.kind, fb.name, fb.result, fb.doc), ("functionBlock", "FB_X", None, "Adds."))
        self.assertEqual((fn.kind, fn.name, fn.result, fn.doc), ("function", "F_Y", "BOOL", "Is IN set?"))
        self.assertEqual([(s.keyword, s.constant) for s in fb.sections],
                         [("VAR_INPUT", False), ("VAR_OUTPUT", False), ("VAR_IN_OUT", False), ("VAR", True),
                          ("VAR", False)])
        a, b, t = fb.sections[0].vars
        self.assertEqual((a.name, a.type, a.init, a.doc), ("A", "INT", "3", "two inputs"))
        self.assertEqual((b.name, b.init), ("B", "3"))
        self.assertEqual(fb.sections[1].vars[0].doc, "the sum")
        s, io_ = fb.sections[4].vars
        self.assertEqual((s.type, s.init), ("STRING[20]", "'a; b'"))
        self.assertEqual((io_.address, io_.type), ("%IB4", "BYTE"))
        self.assertEqual(fb.body, "Q := INT_TO_WORD(A + B); (* END_FUNCTION_BLOCK in a comment *)\n")

    def test_unreadable_declaration(self):
        with self.assertRaisesRegex(plcopen.PlcopenError, "cannot read the declaration"):
            plcopen.parse_st("PROGRAM p\nVAR\n  x y : INT;\nEND_VAR\nEND_PROGRAM\n")

    def test_whole_library(self):
        pous = plcopen_targets.library_pous()
        names = [p.name for p in pous]
        self.assertEqual(len(names), len(set(names)))
        for name in ("CO_SDO_READ", "CAN_RECEIVE", "CW_LINK_SERVICE", "CW_DWORD_TO_REAL", "J1939_NAME_SPLIT"):
            self.assertIn(name, names)
        for p in pous:
            self.assertTrue(p.body.strip(), p.name)
            self.assertNotIn("canworks library", p.doc)


# Names a strict or vendor compiler refuses for a POU or a variable: IEC
# 61131-3 keywords and generic types, IL operators (CODESYS reserves S, R,
# N and the rest even in ST), and elementary types such as BIT.
RESERVED = set("""
ACTION AND ANY ANY_BIT ANY_DATE ANY_DERIVED ANY_ELEMENTARY ANY_INT ANY_MAGNITUDE ANY_NUM ANY_REAL ANY_STRING
ARRAY AT BIT BOOL BY BYTE CAL CALC CALCN CASE CHAR CLASS CONFIGURATION CONSTANT DATE DATE_AND_TIME DINT DIV DO DT
DWORD ELSE ELSIF END_CASE END_FOR END_IF END_REPEAT END_STRUCT END_VAR END_WHILE EN ENO EQ EXIT EXTENDS F_EDGE
FALSE FOR FROM FUNCTION FUNCTION_BLOCK GE GT IF IMPLEMENTS INT INTERFACE INTERNAL JMP JMPC JMPCN LD LDN LE LINT
LREAL LT LWORD METHOD MOD MUL N NE NEW NOT OF ON OR ORN PRIVATE PROGRAM PROPERTY PROTECTED PUBLIC R R_EDGE READ_ONLY
READ_WRITE REAL REF REF_TO REPEAT RESOURCE RET RETAIN RETC RETCN RETURN S SINT ST STN STEP STRING STRUCT SUB SUPER
TASK THEN THIS TIME TO TOD TRANSITION TRUE TYPE UDINT UINT ULINT UNTIL USINT VAR VAR_ACCESS VAR_CONFIG VAR_EXTERNAL
VAR_GLOBAL VAR_INPUT VAR_IN_OUT VAR_OUTPUT VAR_TEMP WCHAR WHILE WITH WORD WSTRING XOR XORN
""".split())


class LibraryNames(unittest.TestCase):
    def test_no_reserved_names(self):
        """Every POU, pin and local of the library has a name strict IEC
        compilers and CODESYS accept (NEW, ANY, R, S and BIT were not)."""
        bad = []
        for p in plcopen_targets.library_pous():
            names = [p.name] + [v.name for s in p.sections for v in s.vars]
            bad += ["%s.%s" % (p.name, n) for n in names if n.upper() in RESERVED]
        self.assertEqual(bad, [])

    def test_the_check_sees_a_reserved_local(self):
        pou, = plcopen.parse_st("FUNCTION_BLOCK X\nVAR\n  r : INT;\nEND_VAR\nr := 1;\nEND_FUNCTION_BLOCK\n")
        self.assertIn("R", [v.name.upper() for s in pou.sections for v in s.vars if v.name.upper() in RESERVED])


class Writer(unittest.TestCase):
    def test_types(self):
        self.assertEqual(plcopen._type_xml("udint"), "<UDINT/>")
        self.assertEqual(plcopen._type_xml("ARRAY[0..1279] OF WORD"),
                         '<array><dimension lower="0" upper="1279"/><baseType><WORD/></baseType></array>')
        self.assertEqual(plcopen._type_xml("STRING[40]"), '<string length="40"/>')
        self.assertEqual(plcopen._type_xml("TON"), '<derived name="TON"/>')

    def test_dialects(self):
        fb = plcopen.parse_st(ParseSt.SOURCE)
        lst = plcopen.GlobalList("canworks", [plcopen.Var("ok", "BOOL", doc="up")])
        task = plcopen.Task("t", 20, ["p1", "p2"])
        for dialect in plcopen.DIALECTS:
            with self.subTest(dialect):
                text = plcopen.writer(fb, [lst], dialect, [task], created=CREATED)
                root = ET.fromstring(text)
                vendor = root.findall("p:addData/p:data", NS)
                structs = root.findall(".//p:dataTypes/p:dataType", NS)
                tasks = root.findall(".//p:resource/p:task", NS)
                if dialect == "codesys":
                    self.assertEqual([d.get("name") for d in vendor], [plcopen.GLOBALVARS])
                    self.assertIn("{attribute 'qualified_only'}", text)
                    self.assertEqual((structs, tasks), ([], []))
                else:
                    self.assertEqual(vendor, [])
                    self.assertEqual([s.get("name") for s in structs], ["canworks_values"])
                    self.assertEqual([[i.get("typeName") for i in t] for t in tasks], [["p1", "p2"]])
                    g = root.find(".//p:resource/p:globalVars/p:variable", NS)
                    self.assertEqual((g.get("name"), g.find("p:type/p:derived", NS).get("name")),
                                     ("canworks", "canworks_values"))
                errors = schema_errors(text)
                if errors is not None:
                    self.assertEqual(errors, [])

    def test_plain_text_comment_before_semicolon(self):
        text = plcopen._section_text(plcopen.Section("VAR", variables=[plcopen.Var("a", "INT", doc="x *) y")]))
        self.assertIn("  a : INT (* x * ) y *);", text)


class Targets(unittest.TestCase):
    maxDiff = None

    def test_golden_files(self):
        for target in plcopen_targets.TARGETS:
            files = export(self, target, library=False)
            folder = os.path.join(DATA, target)
            if os.environ.get("UPDATE_GOLDEN"):
                shutil.rmtree(folder, ignore_errors=True)
                os.makedirs(folder)
                for name, text in files.items():
                    if name not in (plcopen_targets.CODESYS_SCRIPT, plcopen_targets.CODESYS_HELPER):
                        with open(os.path.join(folder, name), "w", encoding="utf-8", newline="\n") as f:
                            f.write(text.replace(__version__, "VERSION"))
            for name, text in files.items():
                if name in (plcopen_targets.CODESYS_SCRIPT, plcopen_targets.CODESYS_HELPER):
                    continue
                with self.subTest(target=target, file=name), open(os.path.join(folder, name), encoding="utf-8") as f:
                    self.assertEqual(text.replace(__version__, "VERSION"), f.read(),
                                     "UPDATE_GOLDEN=1 rewrites tests/data/plcopen")

    def test_schema(self):
        for target in plcopen_targets.TARGETS:
            with self.subTest(target):
                errors = schema_errors(export(self, target)[plcopen_targets.XML_NAME])
                if errors is None:
                    self.skipTest("neither lxml nor xmllint")
                self.assertEqual(errors, [])
        errors = schema_errors(plcopen_targets.library_xml(created=CREATED))
        self.assertEqual(errors, [])

    def test_files(self):
        self.assertEqual(sorted(export(self, "codesys")), ["README.txt", "canworks-codesys-modbus.json",
                                                           "canworks.xml", "import_canworks.py",
                                                           "import_canworks_modbus.py"])
        self.assertEqual(sorted(export(self, "trust")), ["README.txt", "canworks.xml", "canworks_io.st",
                                                         "io.toml.part"])
        self.assertEqual(sorted(export(self, "generic")), ["README.txt", "canworks-modbus-map.csv", "canworks.xml"])

    def test_library_and_main(self):
        xml = export(self, "generic")[plcopen_targets.XML_NAME]
        self.assertIn('<pou name="CAN_RECEIVE"', xml)
        xml = export(self, "trust", with_main=True)[plcopen_targets.XML_NAME]
        self.assertIn('<pou name="CAN_RECEIVE"', xml)
        self.assertIn('<pou name="CO_SDO_READ"', xml)
        root = ET.fromstring(xml)
        self.assertEqual([i.get("typeName") for i in root.findall(".//p:task/p:pouInstance", NS)],
                         ["canworks_in", "main", "canworks_out"])
        xml = export(self, "codesys", library=False)[plcopen_targets.XML_NAME]
        self.assertEqual([p.get("name") for p in ET.fromstring(xml).findall(".//p:pou", NS)],
                         ["canworks_in", "canworks_out"])

    def test_codesys_plan(self):
        plan = json.loads(export(self, "codesys", codesys_plc="PLC1")[plcopen_targets.CODESYS_PLAN])
        self.assertEqual((plan["format"], plan["plc"], plan["bridge"], plan["cycle_ms"]),
                         (1, "PLC1", {"host": "192.168.10.5", "port": 1502, "unit_id": 1}, 200))
        for ch in plan["channels"]:
            self.assertLessEqual(ch["count"], 125 if ch["function"] == 4 else 123)
            self.assertEqual(ch["variable"], "canworks.in_w" if ch["function"] == 4 else "canworks.out_w")
        self.assertEqual(plan["channels"][0]["start"], 0)

    def test_trust_io(self):
        files = export(self, "trust")
        self.assertIn('address = "127.0.0.1:1502"', files[plcopen_targets.TRUST_IO])
        self.assertIn("cw_in AT %IB0 : ARRAY[0..65] OF BYTE;", files[plcopen_targets.TRUST_IO_ST])
        self.assertIn('address = "10.0.0.7:1502"', export(self, "trust", host="10.0.0.7")[plcopen_targets.TRUST_IO])

    def test_trust_with_trimmed_mailboxes(self):
        files = export(self, "trust", mailboxes="trimmed")
        self.assertIn("cw_in AT %IB0 : ARRAY[0..209] OF BYTE;", files[plcopen_targets.TRUST_IO_ST])
        self.assertIn("cw_out AT %QB0 : ARRAY[0..175] OF BYTE;", files[plcopen_targets.TRUST_IO_ST])
        self.assertIn("link_service(LINK := canworks.link);", files[plcopen_targets.XML_NAME])

    def test_refusals(self):
        d = tmpdir(self)
        path, cfg = link_config(d)
        decls = editorproject.declarations(cfg, path)
        with self.assertRaisesRegex(plcopen_targets.ExportError, "one request each way.*\"requests\": 1, "
                                    "\"receive\": false.*CAN_RECEIVE"):
            plcopen_targets.files(cfg, decls, "trust")
        with self.assertRaisesRegex(plcopen_targets.ExportError, "bridge's address as the PLC sees it"):
            plcopen_targets.files(cfg, decls, "codesys")
        cfg["bridge"]["listen"] = "127.0.0.1:1502"
        with self.assertRaisesRegex(plcopen_targets.ExportError, "bridge's address as the PLC sees it"):
            plcopen_targets.files(cfg, decls, "codesys")
        del cfg["bridge"]["plc_link"]
        with self.assertRaisesRegex(plcopen_targets.ExportError, "no PLC link"):
            plcopen_targets.files(cfg, decls, "generic")
        del cfg["bridge"]
        with self.assertRaisesRegex(plcopen_targets.ExportError, "not a Modbus bridge config"):
            plcopen_targets.files(cfg, decls, "generic")

    def test_interval(self):
        self.assertEqual(plcopen_targets.task_interval_ms({"bridge": {"plc_link": True}}), 200)
        self.assertEqual(plcopen_targets.task_interval_ms({"bridge": {"plc_link": True, "watchdog_ms": 30}}), 10)
        self.assertEqual(plcopen_targets.task_interval_ms({"bridge": {"plc_link": True, "watchdog_ms": 333}}), 65)


class Cli(unittest.TestCase):
    def run_cli(self, *argv):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            try:
                code = cli.main(list(argv))
            except SystemExit as e:
                code = e.code
        return code, out.getvalue(), err.getvalue()

    def test_export(self):
        d = tmpdir(self)
        path, _ = link_config(d)
        out_dir = os.path.join(d, "out")
        code, out, err = self.run_cli("--config", path, "--export-plcopen", out_dir, "--for", "codesys",
                                      "--bridge-host", "10.0.0.2", "--codesys-plc", "PLC1")
        self.assertEqual(code, 0, err)
        self.assertIn("wrote 5 files", out)
        with open(os.path.join(out_dir, plcopen_targets.CODESYS_PLAN), encoding="utf-8") as f:
            plan = json.load(f)
        self.assertEqual((plan["bridge"]["host"], plan["plc"], plan["config"]), ("10.0.0.2", "PLC1", "canworks.json"))

    def test_trust_with_trimmed_mailboxes(self):
        files = export(self, "trust", mailboxes="trimmed")
        self.assertIn("cw_in AT %IB0 : ARRAY[0..209] OF BYTE;", files[plcopen_targets.TRUST_IO_ST])
        self.assertIn("cw_out AT %QB0 : ARRAY[0..175] OF BYTE;", files[plcopen_targets.TRUST_IO_ST])
        self.assertIn("link_service(LINK := canworks.link);", files[plcopen_targets.XML_NAME])

    def test_refusals(self):
        d = tmpdir(self)
        path, _ = link_config(d)
        out_dir = os.path.join(d, "out")
        for argv, text in (
                (["--export-plcopen", out_dir], "needs --for"),
                (["--export-plcopen", out_dir, "--for", "codesys", "--with-main"], "--with-main goes with"),
                (["--export-plcopen", out_dir, "--for", "generic", "--codesys-plc", "x"], "go with --for codesys"),
                (["--check", "--for", "generic"], "--for needs --export-plcopen"),
                (["--export-plcopen", out_dir, "--for", "trust"], "one request each way")):
            with self.subTest(argv):
                code, out, err = self.run_cli("--config", path, *argv)
                self.assertNotEqual(code, 0)
                self.assertIn(text, err)
        self.assertFalse(os.path.exists(out_dir))

    def test_library(self):
        d = tmpdir(self)
        code, out, err = self.run_cli("library", "--out", d, "--format", "plcopen")
        self.assertEqual(code, 0, err)
        with open(os.path.join(d, plcopen_targets.LIBRARY_XML_NAME), encoding="utf-8") as f:
            root = ET.fromstring(f.read())
        self.assertIn("CO_SDO_READ", [p.get("name") for p in root.findall(".//p:pou", NS)])
        code, out, err = self.run_cli("library", "--list", "--format", "plcopen")
        self.assertIn("writes the library with --out DIR", err)


class CodesysScript(unittest.TestCase):
    def folder(self, **kw):
        d = tmpdir(self)
        plcopen_targets.write(d, export(self, "codesys", library=False, **kw))
        return d

    def project(self, w, tasks=(("MainTask", ["PLC_PRG"]),)):
        proj = w.project_with_plc(os.path.join(tmpdir(self), "x.project"))
        plc = proj.find("PLC")[0]
        w.add_application(proj, plc)
        for name, pous in tasks:
            w.add_task(plc, name, pous)
        return proj, plc

    def test_first_run_and_again(self):
        d = self.folder()
        w = fake_codesys.World()
        proj, plc = self.project(w)
        report = w.run(d, proj, "import_canworks_modbus.py")
        self.assertTrue(report.startswith("result: ok"), report)
        self.assertIn("imported canworks.xml into Application", report)
        self.assertIn("set      Modbus TCP Slave canworks_bridge: IP address = 192.168.10.5", report)
        self.assertIn("by hand  Modbus TCP Slave canworks_bridge: channel Read Input Registers (function 4), "
                      "cyclic every 200 ms, offset 0, length 105, mapped to canworks.in_w[0..104]", report)
        self.assertIn("set      task MainTask: canworks_in, PLC_PRG, canworks_out", report)
        slave = plc.find("canworks_bridge", True)[0]
        self.assertEqual([fake_codesys.param(slave, i).value for i in (1, 2, 3)], ["192.168.10.5", "1502", "1"])
        self.assertFalse(proj.saved)
        report = w.run(d, proj, "import_canworks_modbus.py")
        self.assertTrue(report.startswith("result: ok"), report)
        self.assertIn("kept     Modbus TCP Slave: canworks_bridge", report)
        self.assertEqual(len(plc.find("canworks_bridge", True)), 1)
        self.assertEqual(plc.find("MainTask", True)[0].pous, ["canworks_in", "PLC_PRG", "canworks_out"])
        self.assertEqual(sum(1 for e in w.log if e[0] == "import_xml"), 2)

    def test_several_tasks(self):
        d = self.folder()
        w = fake_codesys.World()
        proj, plc = self.project(w, (("Fast", ["Motion"]), ("Slow", ["Logging"])))
        report = w.run(d, proj, "import_canworks_modbus.py")
        self.assertIn("by hand  task: 2 tasks (Fast, Slow): add canworks_in as the first", report)
        self.assertEqual(plc.find("Fast", True)[0].pous, ["Motion"])

    def test_named_plc_and_no_project(self):
        d = self.folder(codesys_plc="Other")
        w = fake_codesys.World()
        proj, _ = self.project(w)
        report = w.run(d, proj, "import_canworks_modbus.py")
        self.assertIn("no device named Other", report)
        report = w.run(d, None, "import_canworks_modbus.py")
        self.assertIn("open the PLC project in CODESYS first", report)

    def test_missing_devices(self):
        d = self.folder()
        w = fake_codesys.World()
        w.repo.names = {}
        proj, _ = self.project(w)
        report = w.run(d, proj, "import_canworks_modbus.py")
        self.assertIn("this CODESYS has no ethernet device installed", report)
        self.assertIn("set      task MainTask", report)


@unittest.skipUnless(os.environ.get("CANWORKS_TRUST"), "CANWORKS_TRUST names the truST CLI "
                                                       "(test/plcopen/fetch-trust.sh)")
class TrustImport(unittest.TestCase):
    """truST imports the trust export and builds it with the whole library
    and a program that uses the blocks, mailbox blocks too (CI runs this when the export changes)."""

    MAIN = """PROGRAM main
VAR
  sdo : CO_SDO_READ;
  live : CO_NODE_LIVE;
  nmt : CO_NMT;
  rx : CAN_RECEIVE;
  name : CO_SDO_READ_STRING;
  dm : J1939_DM_READ;
  data : ARRAY[0..7] OF BYTE;
  dtcs : ARRAY[0..31] OF UDINT;
  v : REAL;
END_VAR
sdo(EXECUTE := canworks.ok, NETWORK := 0, NODE := 5, INDEX := 16#1018, SUBINDEX := 1, LINK := canworks.link);
live(NETWORK := 0, NODE := 6, LINK := canworks.link);
nmt(EXECUTE := FALSE, NETWORK := 0, NODE := 6, COMMAND := 1, LINK := canworks.link);
rx(ENABLE := canworks.ok, NETWORK := 0, ALL_IDS := TRUE, LINK := canworks.link, RX_DATA := data);
name(EXECUTE := rx.RECEIVED, NETWORK := 0, NODE := 5, INDEX := 16#1008, SUBINDEX := 0, LINK := canworks.link);
dm(EXECUTE := FALSE, NETWORK := 1, LINK := canworks.link, DTCS := dtcs);
v := CW_DWORD_TO_REAL(UDINT_TO_DWORD(sdo.DATA));
canworks.dio_Write_analogue_output_1 := canworks.rtd_AI0_Input_PV;
END_PROGRAM
"""

    def run_trust(self, *args):
        return subprocess.run([os.environ["CANWORKS_TRUST"]] + list(args), capture_output=True, text=True,
                              timeout=300)

    def test_import_and_build(self):
        files = export(self, "trust", mailboxes="trimmed", with_main=True)
        d = tmpdir(self)
        src = os.path.join(d, "export")
        plcopen_targets.write(src, files)
        project = os.path.join(d, "project")
        os.makedirs(os.path.join(project, "src"))
        r = self.run_trust("plcopen", "import", "--input", os.path.join(src, plcopen_targets.XML_NAME),
                           "--project", project, "--json")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        report = json.loads(r.stdout)
        self.assertEqual((report["unsupported_nodes"], report["compatibility_coverage"]["verdict"]), ([], "full"))
        shutil.copy(os.path.join(src, plcopen_targets.TRUST_IO_ST), os.path.join(project, "src"))
        with open(os.path.join(project, "src", "main.st"), "w", encoding="utf-8") as f:
            f.write(self.MAIN)
        r = self.run_trust("build", "--project", project)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("program.stbc", r.stdout + r.stderr)
