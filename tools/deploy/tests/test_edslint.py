"""The EDS lint the plugin runs before dcfgen (canopen-master-bringup:
"Prepared EDS copy", "EDS lint scope"): prepare's corrections, the blocking
rule on dcf.lint's messages, the read step and the JSON command line."""

import ast
import contextlib
import io
import json
import os
import unittest

from canworks import edslint

from .helpers import tmpdir

HERE = os.path.dirname(os.path.abspath(__file__))
FIXTURES = os.path.join(HERE, "..", "..", "..", "test", "fixtures", "eds")
LINT = os.path.join(FIXTURES, "lint")
REPO_GATEWAY = os.path.join(os.path.dirname(__file__), "..", "..", "..", "config", "gateway")
DRIVES = os.path.join(FIXTURES, "drives")
DRIVE_FILES = ("servo-drive.eds", "fixed-drive.eds")


def read(path):
    with open(path, "rb") as f:
        return f.read()


EDS = """[DeviceInfo]
VendorName=Test
ProductName=Test

[MandatoryObjects]
SupportedObjects=3
1=0x1000
2=0x1001
3=0x1018

[1000]
ParameterName=Device type
ObjectType=0x7
DataType=0x0007
AccessType=ro
DefaultValue=0x00000000
PDOMapping=0

[1001]
ParameterName=Error register
ObjectType=0x7
DataType=0x0005
AccessType=ro
DefaultValue=0
PDOMapping=1

[1018]
ParameterName=Identity
ObjectType=0x9
SubNumber=2

[1018sub0]
ParameterName=Highest sub-index
ObjectType=0x7
DataType=0x0005
AccessType=const
DefaultValue=1
PDOMapping=0

[1018sub1]
ParameterName=Vendor-ID
ObjectType=0x7
DataType=0x0007
AccessType=ro
DefaultValue=0x00000001
PDOMapping=0

[OptionalObjects]
SupportedObjects=0

[ManufacturerObjects]
SupportedObjects={count}
{listing}
{objects}"""


def eds(*objects):
    """A minimal valid EDS with extra manufacturer objects (index, body)."""
    listing = "".join("%d=0x%04X\n" % (i + 1, index) for i, (index, _) in enumerate(objects))
    body = "".join("\n[%04X]\n%s" % (index, text.strip("\n") + "\n") for index, text in objects)
    return EDS.format(count=len(objects), listing=listing.rstrip("\n"), objects=body)


def var(data_type, **keys):
    head = "ParameterName=x\nObjectType=0x7\nDataType=%s\nAccessType=rw\nPDOMapping=0\n" % data_type
    return head + "".join("%s=%s\n" % (k, v) for k, v in keys.items())


class Prepare(unittest.TestCase):
    def test_valid_file_unchanged(self):
        text = eds((0x2000, var("0x0007", DefaultValue="5")))
        out, corrections = edslint.prepare(text.encode("utf-8"))
        self.assertEqual(out, text)
        self.assertEqual(corrections, [])
        crlf = text.replace("\n", "\r\n")
        self.assertEqual(edslint.prepare(crlf.encode("utf-8")), (crlf, []))

    def test_utf8(self):
        text = eds((0x2000, var("0x0007", DefaultValue="5"))).replace("VendorName=Test", "VendorName=Grüne Geräte")
        out, corrections = edslint.prepare(text.encode("cp1252"))
        self.assertEqual(out, text)
        self.assertEqual([c.kind for c in corrections], ["utf8"])

    def test_nodeid_suffix(self):
        text = eds((0x2000, var("0x0007", DefaultValue="0x180+$NODEID", HighLimit="0x200 + $NODEID")))
        out, corrections = edslint.prepare(text.encode("utf-8"))
        self.assertIn("DefaultValue=$NODEID+0x180\n", out)
        self.assertIn("HighLimit=$NODEID+0x200\n", out)
        self.assertEqual([c.kind for c in corrections], ["nodeid"])
        self.assertEqual(corrections[0].items[0],
                         {"section": "2000", "key": "DefaultValue", "old": "0x180+$NODEID", "new": "$NODEID+0x180"})

    def test_real(self):
        text = eds((0x2000, var("0x0008", DefaultValue="12.345", LowLimit="-1e3")),
                   (0x2001, var("0x0011", DefaultValue="0.5")),
                   (0x2002, var("0x0008", DefaultValue="0x3F800000")),
                   (0x2003, var("0x0007", DefaultValue="12")))
        out, corrections = edslint.prepare(text.encode("utf-8"))
        self.assertIn("DefaultValue=0x4145851F\n", out)  # 12.345f
        self.assertIn("LowLimit=0xC47A0000\n", out)  # -1000.0f
        self.assertIn("DefaultValue=0x3FE0000000000000\n", out)  # 0.5 as REAL64
        self.assertIn("DefaultValue=0x3F800000\n", out)
        self.assertEqual([c.kind for c in corrections], ["real"])
        self.assertEqual(len(corrections[0].items), 3)

    def test_octet_string(self):
        text = eds((0x2000, var("0x000A", DefaultValue="----")),
                   (0x2001, var("0x000F", ParameterValue="+1")),
                   (0x2002, var("0x000A", DefaultValue="abcd")),
                   (0x2003, var("0x000A", DefaultValue="1-2")),
                   (0x2004, var("0x0009", DefaultValue="----")))
        out, corrections = edslint.prepare(text.encode("utf-8"))
        self.assertIn("[2000]\n", out)
        self.assertEqual(out.count("DefaultValue=\n"), 1)
        self.assertIn("ParameterValue=\n", out)
        self.assertIn("DefaultValue=abcd\n", out)
        self.assertIn("DefaultValue=1-2\n", out)
        self.assertIn("DefaultValue=----\n", out)  # VISIBLE_STRING: Lely reads it as text
        self.assertEqual([c.kind for c in corrections], ["string"])
        self.assertEqual([i["old"] for i in corrections[0].items], ["----", "+1"])

    def test_comments_kept(self):
        text = eds((0x2000, var("0x0008", DefaultValue="1.5 ; volts")))
        out, _ = edslint.prepare(text.encode("utf-8"))
        self.assertIn("DefaultValue=0x3FC00000 ; volts\n", out)


class MessageForms(unittest.TestCase):
    """Every message the vendored dcf.lint can give, and how the blocking
    rule reads it. A vendor update that changes one fails here."""

    # How the rule reads each form: "object" blocks in 0x1000-0x1FFF, "limit"
    # is limit-only, "value" depends on the value and its data type,
    # "listing" never blocks, "section" goes by the section it names (an
    # object list such as [OptionalObjects] never blocks, a compact object's
    # [1003Value] is that object), "none" names no object.
    FORMS = {
        "AccessType not specified in [{}]": "object",
        "AccessType not supported in [{}]": "object",
        "DataType not specified in [{}]": "object",
        "DataType should be UNSIGNED8 in [{}]": "object",
        "HighLimit not supported in [{}]": "limit",
        "LowLimit not supported in [{}]": "limit",
        "NrOfEntries entry missing in [{}]": "section",
        "ObjectType should be 0x08 (ARRAY) or 0x09 (RECORD) in [{}]": "object",
        "ParameterName not specified in [{}]": "object",
        "SubNumber and CompactSubObj specified in [{}]": "object",
        "SupportedObjects entry missing in [{}]": "section",
        "data type objects are not supported: 0x{:04X}": "listing",
        "entry {} missing in [{}]": "section",
        "invalid DataType in [{}]: {}": "object",
        "invalid HighLimit in [{}]: {}": "limit",
        "invalid LowLimit in [{}]: {}": "limit",
        "invalid entry in [{}]: {}": "section",
        "invalid object index for entry {} in [{}]: {}": "section",
        "invalid sub-index in [{}]: {}": "object",
        "invalid sub-index: {}": "none",
        "invalid value for NrOfEntries in [{}]: {}": "section",
        "invalid value for SupportedObjects in [{}]: {}": "section",
        "invalid value for {} in [{}]: {}": "section",
        "invalid {} in [{}]: {}": "object",
        "object 0x{:04X} is manufacturer-specific": "listing",
        "object 0x{:04X} is not mandatory": "listing",
        "object 0x{:04X} is not manufacturer-specific": "listing",
        "object 0x{:04X} not found": "object",
        "object 0x{} does not support compact storage": "object",
        "object 0x{} not defined: {}": "object",
        "too few entries in [{}]": "section",
        "too many entries in [{}]": "section",
        "unknown section in DCF: {}": "none",
        "{} extra sub-object(s) for object 0x{:04X}": "object",
        "{} missing sub-object(s) for object 0x{:04X}": "object",
        "{} overflow in [{}]": "value",
        "{} underflow in [{}]": "value",
    }

    @staticmethod
    def forms():
        """The message templates of every warnings.warn call in lint.py."""
        path = os.path.join(os.path.dirname(edslint.__file__), "_lely_dcf", "lint.py")
        with open(path, encoding="utf-8") as f:
            tree = ast.parse(f.read())

        def template(node):
            if isinstance(node, ast.Constant):
                return node.value
            if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
                return template(node.left) + template(node.right)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "format":
                return template(node.func.value)
            return "{}"

        return {template(n.args[0]) for n in ast.walk(tree)
                if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr == "warn"}

    def test_forms_pinned(self):
        self.assertEqual(self.forms(), set(self.FORMS))

    def test_each_form(self):
        # A communication object (0x1800 sub 1, UNSIGNED32, $NODEID+0x180) in
        # every form; "object" forms block, the others do not.
        cfg = {"1800sub1": {"DataType": "0x0007", "DefaultValue": "$NODEID+0x180"}}
        examples = {
            "listing": ["entry 3 missing in [OptionalObjects]", "too many entries in [MandatoryObjects]",
                        "object 0x1F80 is not mandatory", "object 0x1005 is manufacturer-specific",
                        "data type objects are not supported: 0x0005"],
            "limit": ["LowLimit not supported in [1800sub1]", "invalid HighLimit in [1800sub1]: 0xZZ",
                      "HighLimit overflow in [1800sub1]"],
            "object": ["DataType should be UNSIGNED8 in [1A00sub0]", "AccessType not specified in [1800sub1]",
                       "invalid DefaultValue in [1800sub1]: x", "object 0x1018 not found",
                       "2 missing sub-object(s) for object 0x1A00", "object 0x1A00 not defined: 1A00sub1",
                       "NrOfEntries entry missing in [1003Value]", "too many entries in [1003Name]"],
            "none": ["unknown section in DCF: Foo", "invalid sub-index: 1800subXY"],
        }
        for kind, messages in examples.items():
            for message in messages:
                f = edslint.classify(cfg, message, 5)
                with self.subTest(message=message):
                    self.assertEqual(f.blocking, kind == "object")
                    self.assertEqual(f.limit_only, kind == "limit")

    def test_value_range(self):
        cfg = {"1800sub1": {"DataType": "0x0007", "DefaultValue": "$NODEID+0x180"},
               "1801sub1": {"DataType": "0x0005", "DefaultValue": "0x1FF"},
               "1802sub1": {"DataType": "0x0002", "DefaultValue": "-129"},
               "1803sub1": {"DataType": "0x0002", "DefaultValue": "-12"},
               "1804sub1": {"DataType": "0x0007", "DefaultValue": "$NODEID"}}
        within = {"1800sub1": True, "1801sub1": False, "1802sub1": False, "1803sub1": True, "1804sub1": True}
        for section, inside in within.items():
            f = edslint.classify(cfg, "DefaultValue overflow in [%s]" % section, 5)
            with self.subTest(section=section):
                self.assertEqual(f.limit_only, inside)
                self.assertEqual(f.blocking, not inside)

    def test_manufacturer_area_never_blocks(self):
        for message in ("DataType should be UNSIGNED8 in [2000sub0]", "invalid DefaultValue in [6061]: x",
                        "DefaultValue overflow in [6061]"):
            self.assertFalse(edslint.classify({}, message, 1).blocking, message)


class Lint(unittest.TestCase):
    def test_rule_examples(self):
        # 0x1800 sub 1 $NODEID+0x180 over HighLimit=0x18F: limit-only.
        r = edslint.lint_file(os.path.join(LINT, "comm-limit.eds"), 5)
        self.assertEqual([(f.where(), f.limit_only, f.blocking) for f in r.findings],
                         [("0x1800 sub 1", True, False)])
        # 0x1A00 sub 0 UNSIGNED16: blocks.
        r = edslint.lint_file(os.path.join(LINT, "comm-broken.eds"), 5)
        self.assertEqual([(f.where(), f.blocking) for f in r.findings], [("0x1A00 sub 0", True)])
        self.assertEqual(r.failing("communication"), r.findings)
        self.assertEqual(r.failing("off"), [])
        # 0x6061 HighLimit=0xFF on an INTEGER8: accepted.
        r = edslint.lint_file(os.path.join(LINT, "signed-hex.eds"), 5)
        self.assertIn(("0x6061", False), [(f.where(), f.blocking) for f in r.findings])
        self.assertEqual(r.failing("communication"), [])
        self.assertEqual(r.accepted("communication"), r.findings)
        self.assertEqual(r.failing("all"), r.findings)

    def test_read_error_without_prepare(self):
        r = edslint.lint_file(os.path.join(LINT, "real-decimal.eds"), 1)
        self.assertIn("dcfgen cannot read the file", r.read_error)
        _, corrections, r = edslint.check(read(os.path.join(LINT, "real-decimal.eds")), 1)
        self.assertIsNone(r.read_error)
        self.assertEqual([c.kind for c in corrections], ["real"])

    def test_mapping_to_a_missing_object_is_named(self):
        # A backup's live RPDO mapping can name an object the EDS lacks.
        with open(os.path.join(REPO_GATEWAY, "cpp-slave.eds"), encoding="utf-8") as f:
            text = f.read().replace("[1600sub1]\nParameterName=Application object 1\nDataType=0x0007\nAccessType=rw\n"
                                    "DefaultValue=0x40000020", "[1600sub1]\nParameterName=Application object 1\n"
                                    "DataType=0x0007\nAccessType=rw\nDefaultValue=0x20620101")
        self.assertIn("0x20620101", text)
        path = os.path.join(tmpdir(self), "missing.eds")
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)
        r = edslint.lint_file(path, 23)
        self.assertEqual(r.read_error, "dcfgen cannot read the file: an entry refers to object 0x2062, which the file "
                                       "does not have (a PDO mapping, for example)")

    def test_non_utf8_without_prepare(self):
        r = edslint.lint_file(os.path.join(LINT, "cp1252.eds"), 1)
        self.assertIn("dcfgen cannot read the file", r.read_error)

    def test_fixtures(self):
        with open(os.path.join(LINT, "expected.json"), encoding="utf-8") as f:
            expected = json.load(f)
        names = sorted(n for n in os.listdir(LINT) if n.endswith(".eds"))
        self.assertEqual(names, sorted(expected))
        for name in names:
            _, corrections, r = edslint.check(read(os.path.join(LINT, name)), 5)
            got = {"corrections": [c.kind for c in corrections], "read_error": r.read_error is not None,
                   "findings": [{"object": f.where(), "message": f.message, "limit_only": f.limit_only,
                                 "blocking": f.blocking} for f in r.findings]}
            with self.subTest(eds=name):
                self.assertEqual(got, expected[name])
                self.assertFalse(r.read_error)
                # Only the communication-area fixture blocks by default;
                # every fixture with a finding fails under "all".
                self.assertEqual(bool(r.failing("communication")), name == "comm-broken.eds")
                self.assertEqual(bool(r.failing("all")), bool(r.findings))

    def test_drive_files(self):
        for name in DRIVE_FILES:
            _, _, r = edslint.check(read(os.path.join(DRIVES, name)), 3)
            with self.subTest(eds=name):
                self.assertIsNone(r.read_error)
                self.assertTrue(r.findings)
                self.assertEqual(r.failing("communication"), [])
                self.assertEqual(r.failing("all"), r.findings)


class Mode(unittest.TestCase):
    def test_effective_mode(self):
        cases = [({}, "communication"), ({"eds_lint": "all"}, "all"), ({"eds_lint": "off"}, "off"),
                 ({"strict_eds": True}, "all"), ({"strict_eds": False}, "off"), (None, "communication")]
        for master, mode in cases:
            self.assertEqual(edslint.effective_mode(master), mode, master)

    def test_texts(self):
        blocking = edslint.Finding("DataType should be UNSIGNED8 in [1A00sub0]", "1A00sub0", 0x1A00, False, True)
        limit = edslint.Finding("HighLimit overflow in [6061]", "6061", 0x6061, True, False)
        self.assertEqual(
            edslint.error_text("node 4 (valve)", "v.eds", [blocking], "communication"),
            "node 4 (valve): EDS v.eds fails dcfgen's lint (eds_lint \"communication\"): 0x1A00 sub 0: DataType "
            "should be UNSIGNED8 in [1A00sub0]; eds_lint: \"off\" would accept it")
        self.assertIn("eds_lint: \"communication\" would accept it",
                      edslint.error_text("node 4", "v.eds", [limit], "all"))
        text = edslint.warning_text("v.eds", [limit] * 4)
        self.assertTrue(text.startswith("EDS v.eds: 4 lint findings accepted"), text)
        self.assertTrue(text.endswith("; ..."), text)


    def test_verdict(self):
        _, corrections, r = edslint.check(read(os.path.join(LINT, "octet-string.eds")), 2)
        error, warning, notes = edslint.verdict("node 2 (servo)", "m.eds", corrections, r, "communication", "/x.eds")
        self.assertIsNone(error)
        self.assertIsNone(warning)
        self.assertEqual(notes, ["node 2 (servo): EDS m.eds read through a prepared copy (/x.eds): OCTET_STRING/DOMAIN "
                                 "values Lely cannot read cleared (1): 0x2051 DefaultValue was \"----\""])
        _, corrections, r = edslint.check(read(os.path.join(LINT, "signed-hex.eds")), 2)
        error, warning, notes = edslint.verdict("node 2", "s.eds", corrections, r, "off")
        self.assertIsNone(error)
        self.assertEqual(notes, [])
        self.assertTrue(warning.startswith("EDS s.eds: 2 lint findings accepted (eds_lint \"off\"): 0x6061"), warning)
        error, warning, _ = edslint.verdict("node 2", "s.eds", corrections, r, "all")
        self.assertIn("node 2: EDS s.eds fails dcfgen's lint (eds_lint \"all\"): 0x6061: HighLimit overflow", error)
        self.assertIsNone(warning)
        r = edslint.lint_file(os.path.join(LINT, "real-decimal.eds"), 2)
        error, _, _ = edslint.verdict("node 2", "r.eds", [], r, "off")
        self.assertTrue(error.startswith("node 2: EDS r.eds: dcfgen cannot read the file"), error)


class Cli(unittest.TestCase):
    def run_cli(self, *argv):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = edslint.main(list(argv))
        return code, out.getvalue()

    def test_json(self):
        d = tmpdir(self)
        copy = os.path.join(d, "node_5.eds")
        code, out = self.run_cli("--json", "--node-id", "5", "--out", copy, os.path.join(LINT, "real-decimal.eds"))
        self.assertEqual(code, 0)
        result = json.loads(out)
        self.assertEqual(result["prepared"], copy)
        self.assertEqual([c["kind"] for c in result["corrections"]], ["real"])
        self.assertEqual(result["corrections"][0]["items"][0]["new"], "0x4145851F")
        self.assertIsNone(result["read_error"])
        self.assertEqual(result["findings"], [])
        self.assertIsNone(result["error"])
        self.assertEqual(len(result["notes"]), 1)
        with open(copy, encoding="utf-8") as f:
            self.assertIn("DefaultValue=0x4145851F", f.read())

    def test_json_no_copy_without_corrections(self):
        d = tmpdir(self)
        copy = os.path.join(d, "node_5.eds")
        code, out = self.run_cli("--json", "--node-id", "5", "--out", copy, os.path.join(LINT, "comm-broken.eds"))
        self.assertEqual(code, 0)
        result = json.loads(out)
        self.assertIsNone(result["prepared"])
        self.assertFalse(os.path.exists(copy))
        self.assertEqual(result["findings"][0]["object"], "0x1A00 sub 0")
        self.assertTrue(result["findings"][0]["blocking"])
        self.assertIn("node 5: EDS comm-broken.eds fails dcfgen's lint", result["error"])

    def test_text(self):
        code, out = self.run_cli(os.path.join(LINT, "comm-broken.eds"))
        self.assertEqual(code, 1)
        self.assertIn("BLOCKS 0x1A00 sub 0", out)
        code, _ = self.run_cli("--mode", "off", os.path.join(LINT, "comm-broken.eds"))
        self.assertEqual(code, 0)
        code, _ = self.run_cli("--mode", "all", os.path.join(LINT, "signed-hex.eds"))
        self.assertEqual(code, 1)

    def test_missing_file(self):
        code, out = self.run_cli("--json", "/nonexistent.eds")
        self.assertEqual(code, 2)
        self.assertIn("error", json.loads(out))


if __name__ == "__main__":
    unittest.main()
