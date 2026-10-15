"""Device notes (spec canopen-device-notes): the notes file format, the
built-in CiA notes, the merge and the checks."""

import contextlib
import filecmp
import io
import json
import os
import re
import unittest

import jsonschema

from canworks import cli, notes
from canworks.eds import Eds

from .helpers import REPO, tmpdir

SERVO = os.path.join(REPO, "config", "cia402-drive", "servo402.eds")
RTD = os.path.join(REPO, "config", "rtd-sensor", "rtd8.eds")
DIO = os.path.join(REPO, "examples", "gantry-cell", "canworks", "dio16.eds")
BUILTIN = os.path.join(REPO, "tools", "deploy", "canworks", "builtin_notes")

# A small valve: two VARs, a RECORD, a bit field, an array of pressures.
VALVE = """[DeviceInfo]
VendorName=Example
VendorNumber=0xAB
ProductName=Valve
ProductNumber=0x1234
RevisionNumber=0x00010002

[MandatoryObjects]
SupportedObjects=2
1=0x1000
2=0x1018

[OptionalObjects]
SupportedObjects=0

[ManufacturerObjects]
SupportedObjects=5
1=0x2010
2=0x2011
3=0x2100
4=0x2200
5=0x2300

[1000]
ParameterName=Device type
ObjectType=0x7
DataType=0x0007
AccessType=ro
DefaultValue=0x00000000
PDOMapping=0

[1018]
ParameterName=Identity
ObjectType=0x9
SubNumber=2

[1018sub0]
ParameterName=Highest sub-index supported
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
DefaultValue=0xAB
PDOMapping=0

[2010]
ParameterName=Ramp time
ObjectType=0x7
DataType=0x0006
AccessType=rw
DefaultValue=100
PDOMapping=0

[2011]
ParameterName=Fault handling
ObjectType=0x9
SubNumber=3

[2011sub0]
ParameterName=Highest sub-index supported
ObjectType=0x7
DataType=0x0005
AccessType=const
DefaultValue=2
PDOMapping=0

[2011sub1]
ParameterName=Fault delay
ObjectType=0x7
DataType=0x0006
AccessType=rw
DefaultValue=0
PDOMapping=0

[2011sub2]
ParameterName=Fault reaction
ObjectType=0x7
DataType=0x0005
AccessType=rw
DefaultValue=0
PDOMapping=0

[2100]
ParameterName=Fault bits
ObjectType=0x7
DataType=0x0005
AccessType=ro
DefaultValue=0
PDOMapping=1

[2200]
ParameterName=Pressure
ObjectType=0x8
SubNumber=3

[2200sub0]
ParameterName=Number of channels
ObjectType=0x7
DataType=0x0005
AccessType=const
DefaultValue=2
PDOMapping=0

[2200sub1]
ParameterName=Pressure 1
ObjectType=0x7
DataType=0x0003
AccessType=ro
DefaultValue=0
PDOMapping=1

[2200sub2]
ParameterName=Pressure 2
ObjectType=0x7
DataType=0x0003
AccessType=ro
DefaultValue=0
PDOMapping=1

[2300]
ParameterName=Label
ObjectType=0x7
DataType=0x0009
AccessType=rw
DefaultValue=valve
PDOMapping=0
"""


def valve():
    return Eds.read("valve.eds", VALVE)


def doc(objects):
    return {"format": notes.FORMAT, "objects": objects}


class Format(unittest.TestCase):
    def test_schema_files_match(self):
        self.assertTrue(filecmp.cmp(os.path.join(REPO, "schema", "canworks-notes.v1.schema.json"),
                                    os.path.join(REPO, "tools", "deploy", "canworks", "schema",
                                                 "canworks-notes.v1.schema.json"), shallow=False))
        with open(os.path.join(REPO, "schema", "canworks-notes.v1.schema.json"), encoding="utf-8") as f:
            jsonschema.Draft202012Validator.check_schema(json.load(f))

    def test_schema(self):
        good = doc({"0x2010": {"name": "Ramp time", "text": "Opening ramp of the valve", "unit": "ms"},
                    "0x2011:2": {"text": "What the valve does on a bus fault", "values": {"0": "hold position", "1": "close"}},
                    "0x2100": {"bits": {"0": "coil A open", "7": "overtemperature"}},
                    "0x2200:1": {"unit": "bar", "scale": 0.01, "manual": "section 7.3"}})
        self.assertEqual(notes.schema_problems(good), [])
        self.assertTrue(notes.schema_problems({"format": "canworks-notes.v2", "objects": {}}))
        self.assertTrue(notes.schema_problems(doc({"0x6060:sub1": {}})))
        self.assertTrue(notes.schema_problems(doc({"0x2010": {"text": "x" * 201}})))
        self.assertTrue(notes.schema_problems(doc({"0x2010": {"scale": 0}})))
        self.assertTrue(notes.schema_problems(doc({"0x2010": {"bits": {"64": "too far"}}})))

    def test_keys(self):
        self.assertEqual(notes.parse_key("0x2011:2"), (0x2011, 2))
        self.assertEqual(notes.parse_key("0x2010"), (0x2010, None))
        self.assertIsNone(notes.parse_key("0x2010:256"))
        self.assertIsNone(notes.parse_key("2010"))
        self.assertEqual(notes.key(0x6060), "0x6060")
        self.assertEqual(notes.key(0x1800, 2), "0x1800:2")


class Builtin(unittest.TestCase):
    def test_files_are_valid(self):
        for name in sorted(os.listdir(BUILTIN)):
            with open(os.path.join(BUILTIN, name), encoding="utf-8") as f:
                data = json.load(f)
            self.assertEqual(notes.schema_problems(data), [], name)
            for k in data["objects"]:
                index = notes.parse_key(k)[0]
                if name == "cia301.json":
                    self.assertTrue(0x1000 <= index <= 0x1FFF, k)
                else:
                    self.assertTrue(0x6000 <= index <= 0x9FFF, (name, k))

    def test_coverage(self):
        """Bits and value names the configurator used to hard-code are in the notes."""
        def table(name):
            with open(os.path.join(BUILTIN, name), encoding="utf-8") as f:
                return json.load(f)["objects"]
        c301, c402 = table("cia301.json"), table("cia402.json")
        self.assertEqual(len(c301["0x1001"]["bits"]), 8)
        self.assertEqual(c301["0x1002"]["bits"], {})
        self.assertEqual(c301["0x1800:2"]["values"]["254"], "event-driven, manufacturer-specific")
        self.assertIn("254", c301["0x1400:2"]["values"])
        for k in ("0x6040", "0x6041"):
            self.assertEqual(len(c402[k]["bits"]), 16)
        for k in ("0x6060", "0x6061"):
            self.assertEqual(c402[k]["values"]["3"], "profile velocity")
        self.assertIn("values", c402["0x6098"])

    def test_cia402_drive(self):
        eds = Eds.read(SERVO)
        self.assertEqual(notes.profile(eds), 402)
        n = notes.Notes.for_eds(eds, "servo402.eds")
        self.assertEqual(notes.value_text(n.note(0x6061, 0), 3), "3 (profile velocity)")
        self.assertIn("bits", n.note(0x6041, 0))

    def test_profile_from_device_type(self):
        """A CiA 401 device's vendor object at 0x6060 gets no drive mode names."""
        eds = Eds.read(DIO)
        self.assertEqual(notes.profile(eds), 401)
        b = notes.builtin(eds)
        self.assertFalse(any(k.startswith("0x6060") for k in b))
        self.assertTrue(any(k.startswith("0x6000") for k in b))
        self.assertEqual(notes.profile(Eds.read(RTD)), 404)  # no built-in notes for CiA 404: CiA 301 only

    def test_pdo_ranges_share_the_first_note(self):
        eds = Eds.read(SERVO)
        n = notes.Notes.for_eds(eds, "servo402.eds")
        for index in (0x1800, 0x1801, 0x1803):
            self.assertEqual(n.note(index, 2)["values"]["254"], "event-driven, manufacturer-specific")
        self.assertIn("index in bits 16-31", n.note(0x1A01, 2)["text"])
        self.assertIn("Number of mapped objects", n.note(0x1A01, 0)["text"])


class Merge(unittest.TestCase):
    def test_device_over_builtin_field_by_field(self):
        eds = Eds.read(SERVO)
        n = notes.Notes(eds, "servo402.eds", device=doc({"0x6060": {"values": {"-1": "vendor jog mode"}}}))
        merged = n.note(0x6060, 0)
        self.assertEqual(merged["values"], {"-1": "vendor jog mode"})
        self.assertIn("Modes of operation", merged["text"])

    def test_sub_objects_inherit(self):
        eds = valve()
        n = notes.Notes(eds, "valve.eds", device=doc({"0x2200": {"text": "Analog input value", "unit": "mV",
                                                                   "values": {"0": "zero"}}}))
        for sub in (1, 2):
            note = n.note(0x2200, sub)
            self.assertEqual((note["text"], note["unit"]), ("Analog input value", "mV"))
            self.assertNotIn("values", note)

    def test_var_takes_its_object_entry(self):
        n = notes.Notes(valve(), "valve.eds", device=doc({"0x2100": {"bits": {"0": "coil A open"}}}))
        self.assertEqual(n.note(0x2100, 0)["bits"], {"0": "coil A open"})

    def test_value_text(self):
        self.assertEqual(notes.value_text({"values": {"1": "close"}}, 1), "1 (close)")
        self.assertEqual(notes.value_text({"unit": "bar", "scale": 0.01}, 1234), "1234 (12.34 bar)")
        self.assertEqual(notes.value_text({"unit": "ms"}, 50), "50 (50 ms)")
        self.assertEqual(notes.value_text({}, 7), "7")

    def test_merged_document(self):
        eds = Eds.read(SERVO)
        n = notes.Notes(eds, "servo402.eds", device=doc({"0x6060": {"values": {"-1": "vendor jog mode"}}}))
        merged = n.merged()
        self.assertEqual(merged["0x6060"]["values"], {"-1": "vendor jog mode"})
        self.assertIn("0x1018:1", merged)
        self.assertEqual(notes.schema_problems({"format": notes.FORMAT, "objects": merged}), [])


class Files(unittest.TestCase):
    def test_skeleton(self):
        sk = notes.skeleton(valve(), "valve.eds", eds_text=VALVE)
        self.assertEqual(sk["eds"], {"file": "valve.eds", "vendor_id": "0x000000AB", "product_code": "0x00001234",
                                     "revision": "0x00010002"})
        self.assertEqual(list(sk["objects"]), ["0x2010", "0x2011:0", "0x2011:1", "0x2011:2", "0x2100", "0x2200:0",
                                               "0x2200:1", "0x2200:2", "0x2300"])
        self.assertEqual(sk["objects"]["0x2011:2"], {"name": "Fault reaction"})
        self.assertEqual(notes.schema_problems(sk), [])

    def test_update_keeps_hand_written_entries(self):
        eds = valve()
        base = doc({"0x2010": {"text": "Ramp", "x-source": "manual p. 12"}, "0x2011:1": {"name": "old name"}})
        new = notes.update(base, {"0x2011:1": {"text": "Delay before the fault reaction", "unit": "ms"}}, eds)
        self.assertEqual(new["objects"]["0x2010"], {"text": "Ramp", "x-source": "manual p. 12"})
        self.assertEqual(new["objects"]["0x2011:1"], {"name": "Fault delay", "text": "Delay before the fault reaction",
                                                      "unit": "ms"})
        self.assertEqual(list(new["objects"]), ["0x2010", "0x2011:1"])
        # A new entry goes in index order; {} clears the user's fields, None the entry.
        new = notes.update(new, {"0x2011:2": {"values": {"1": "close"}}, "0x2010": {}, "0x2011:1": None}, eds)
        self.assertEqual(new["objects"], {"0x2010": {"x-source": "manual p. 12"},
                                          "0x2011:2": {"name": "Fault reaction", "values": {"1": "close"}}})

    def test_load(self):
        d = tmpdir(self)
        path = os.path.join(d, "valve.eds.notes.json")
        self.assertEqual(notes.load(path), (None, None))
        with open(path, "w", encoding="utf-8") as f:
            f.write("{ not json")
        data, error = notes.load(path)
        self.assertIsNone(data)
        self.assertIn("valve.eds.notes.json cannot be read", error)
        with open(path, "w", encoding="utf-8") as f:
            json.dump({"format": "canworks-notes.v9", "objects": {}}, f)
        self.assertIn("is not a canworks-notes.v1 file", notes.load(path)[1])
        with open(path, "w", encoding="utf-8") as f:
            json.dump(doc({"0x2010": {"text": "Ramp"}}), f)
        self.assertEqual(notes.load(path), (doc({"0x2010": {"text": "Ramp"}}), None))

    def test_for_eds_reads_the_file_next_to_it(self):
        d = tmpdir(self)
        eds_path = os.path.join(d, "valve.eds")
        with open(eds_path, "w", encoding="utf-8") as f:
            f.write(VALVE)
        with open(eds_path + ".notes.json", "w", encoding="utf-8") as f:
            json.dump(doc({"0x2011:2": {"values": {"1": "close"}}}), f)
        n = notes.Notes.for_eds(valve(), "valve.eds", eds_path)
        self.assertEqual(notes.value_text(n.note(0x2011, 2), 1), "1 (close)")
        self.assertTrue(n.to_json()["exists"])


class Checks(unittest.TestCase):
    def test_findings(self):
        eds = valve()
        found = notes.check(eds, doc({"0x2011:3": {"text": "gone"}, "0x2300": {"values": {"0": "x"}},
                                      "0x2100": {"bits": {"9": "beyond"}}, "0x2010": {"text": "ok"}}),
                            "valve.eds.notes.json", "valve.eds")
        self.assertIn("valve.eds.notes.json has a note for 0x2011:3, which valve.eds does not have", found)
        self.assertTrue(any("0x2300 has values, but its type VISIBLE_STRING is not an integer type" in f for f in found))
        self.assertTrue(any("0x2100 names bit 9, but UNSIGNED8 has only 8 bits" in f for f in found))
        self.assertEqual(len(found), 3)

    def test_skeleton_and_builtin_are_clean(self):
        for path in (SERVO, RTD, DIO):
            eds = Eds.read(path)
            self.assertEqual(notes.check(eds, notes.skeleton(eds, "x.eds", eds_path=path), "n", "x.eds"), [])
            self.assertEqual(notes.check(eds, {"format": notes.FORMAT, "objects": notes.builtin(eds)}, "n", "x.eds"), [])


SKILL = os.path.join(REPO, ".claude", "skills", "canworks-datasheet-notes", "SKILL.md")


class Commands(unittest.TestCase):
    """canworks-deploy notes skeleton | builtin | check (spec canopen-deploy)."""

    def setUp(self):
        self.dir = tmpdir(self)
        self.eds = os.path.join(self.dir, "valve.eds")
        with open(self.eds, "w", encoding="utf-8") as f:
            f.write(VALVE)

    def run_cli(self, *argv):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            rc = cli.main(["notes"] + list(argv))
        return rc, out.getvalue(), err.getvalue()

    def write_notes(self, objects):
        path = os.path.join(self.dir, "valve.eds.notes.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(doc(objects), f)
        return path

    def test_skeleton_has_types_and_access(self):
        rc, out, _ = self.run_cli("skeleton", self.eds)
        self.assertEqual(rc, 0)
        sk = json.loads(out)
        self.assertEqual(sk["format"], notes.FORMAT)
        self.assertEqual(sk["eds"]["product_code"], "0x00001234")
        self.assertEqual(sk["objects"]["0x2010"], {"name": "Ramp time", "x-type": "UNSIGNED16", "x-access": "rw"})
        self.assertEqual(sk["objects"]["0x2011:0"]["x-access"], "const")
        self.assertIn("0x2011:2", sk["objects"])
        self.assertNotIn("0x1000", sk["objects"])
        self.assertEqual(notes.schema_problems(sk), [])

    def test_output_file(self):
        target = os.path.join(self.dir, "out.json")
        rc, out, _ = self.run_cli("skeleton", self.eds, "-o", target)
        self.assertEqual((rc, out), (0, ""))
        with open(target, encoding="utf-8") as f:
            self.assertIn("0x2300", json.load(f)["objects"])

    def test_builtin_by_profile(self):
        rc, out, _ = self.run_cli("builtin", self.eds)
        objects = json.loads(out)["objects"]
        self.assertEqual(rc, 0)
        self.assertIn("0x1000", objects)
        self.assertFalse([k for k in objects if k.startswith("0x6")])
        rc, out, _ = self.run_cli("builtin", SERVO)
        objects = json.loads(out)["objects"]
        self.assertEqual(objects["0x6040"]["bits"]["0"], "switch on")
        self.assertEqual(json.loads(out)["eds"]["file"], "servo402.eds")

    def test_check_clean(self):
        path = self.write_notes({"0x2011:2": {"text": "Fault reaction", "values": {"0": "hold", "1": "close"}}})
        self.assertEqual(self.run_cli("check", self.eds, path), (0, "", ""))

    def test_check_findings(self):
        path = self.write_notes({"0x2999": {"text": "Not in the EDS"}, "0x2100": {"bits": {"8": "too far"}}})
        rc, out, _ = self.run_cli("check", self.eds, path)
        self.assertEqual(rc, 1)
        lines = out.splitlines()
        self.assertIn("valve.eds.notes.json has a note for 0x2999, which valve.eds does not have", lines)
        self.assertIn("valve.eds.notes.json: 0x2100 names bit 8, but UNSIGNED8 has only 8 bits", lines)

    def test_unreadable_files(self):
        broken = os.path.join(self.dir, "broken.json")
        with open(broken, "w", encoding="utf-8") as f:
            f.write("{")
        rc, _, err = self.run_cli("check", self.eds, broken)
        self.assertEqual(rc, 1)
        self.assertIn("broken.json cannot be read", err)
        rc, _, err = self.run_cli("check", self.eds, os.path.join(self.dir, "missing.json"))
        self.assertEqual(rc, 1)
        self.assertIn("missing.json", err)
        rc, _, err = self.run_cli("skeleton", os.path.join(self.dir, "missing.eds"))
        self.assertEqual(rc, 1)
        self.assertIn("cannot read", err)


    def test_skeleton_all(self):
        rc, out, err = self.run_cli("skeleton", "--all", self.eds)
        self.assertEqual((rc, err), (0, ""))
        objects = json.loads(out)["objects"]
        self.assertIn("0x1000", objects)
        self.assertIn("0x1018:1", objects)
        self.assertEqual(objects["0x2011"], {"name": "Fault handling"})
        self.assertEqual(objects["0x2200"], {"name": "Pressure"})
        self.assertEqual(objects["0x2010"], {"name": "Ramp time", "x-type": "UNSIGNED16", "x-access": "rw",
                                             "x-default": "100", "x-pdo": False})
        self.assertIs(objects["0x2200:1"]["x-pdo"], True)
        self.assertEqual(objects["0x1018:1"]["x-default"], "0xAB")
        self.assertEqual(list(objects).index("0x2011") + 1, list(objects).index("0x2011:0"))
        self.assertEqual(notes.schema_problems(json.loads(out)), [])

    def test_skeleton_limits_as_written(self):
        text = VALVE.replace("DefaultValue=100\n", "DefaultValue=100\nLowLimit=0x0A\nHighLimit=$NODEID+0x10\n")
        text = text.replace("ParameterName=Fault delay\nObjectType=0x7\nDataType=0x0006\nAccessType=rw\n"
                            "DefaultValue=0\n", "ParameterName=Fault delay\nObjectType=0x7\nDataType=0x0006\n"
                            "AccessType=rw\n")
        with open(self.eds, "w", encoding="utf-8") as f:
            f.write(text)
        objects = json.loads(self.run_cli("skeleton", "--all", self.eds)[1])["objects"]
        self.assertEqual((objects["0x2010"]["x-low"], objects["0x2010"]["x-high"]), ("0x0A", "$NODEID+0x10"))
        self.assertNotIn("x-default", objects["0x2011:1"])

    def test_skeleton_index_range(self):
        objects = json.loads(self.run_cli("skeleton", "--all", "--index", "0x2011-0x2100", self.eds)[1])["objects"]
        self.assertEqual(sorted(objects), ["0x2011", "0x2011:0", "0x2011:1", "0x2011:2", "0x2100"])
        objects = json.loads(self.run_cli("skeleton", "--index", "0x1000-0x2010", self.eds)[1])["objects"]
        self.assertEqual(list(objects), ["0x2010"])
        err = io.StringIO()
        with contextlib.redirect_stderr(err), self.assertRaises(SystemExit):
            cli.main(["notes", "skeleton", "--index", "0x3000-0x2000", self.eds])
        self.assertIn("not an index range", err.getvalue())

    def test_skeleton_type_names(self):
        with open(self.eds, "w", encoding="utf-8") as f:
            f.write(VALVE.replace("[2010]\nParameterName=Ramp time\nObjectType=0x7\nDataType=0x0006",
                                  "[2010]\nParameterName=Ramp time\nObjectType=0x7\nDataType=0x0016"))
        objects = json.loads(self.run_cli("skeleton", self.eds)[1])["objects"]
        self.assertEqual(objects["0x2010"]["x-type"], "UNSIGNED24")
        self.assertEqual(notes.type_text(type("O", (), {"type_name": None, "data_type": 0x14})()), "INTEGER56")

    def test_skeleton_missing_identity(self):
        with open(self.eds, "w", encoding="utf-8") as f:
            f.write(VALVE.replace("ProductNumber=0x1234\n", ""))
        rc, out, err = self.run_cli("skeleton", self.eds)
        self.assertEqual(rc, 0)
        self.assertNotIn("product_code", json.loads(out)["eds"])
        self.assertIn("valve.eds gives no product code", err)

    def test_builtin_names_sets(self):
        self.assertEqual(self.run_cli("builtin", self.eds)[2],
                         "built-in notes: CiA 301\n")
        self.assertEqual(self.run_cli("builtin", SERVO)[2], "built-in notes: CiA 301, CiA 402\n")
        with open(self.eds, "w", encoding="utf-8") as f:
            f.write(VALVE.replace("DefaultValue=0x00000000", "DefaultValue=0x00010196"))
        rc, out, err = self.run_cli("builtin", self.eds)
        self.assertEqual(err, "built-in notes: CiA 301; there are no built-in notes for profile 406\n")
        self.assertFalse([k for k in json.loads(out)["objects"] if k.startswith("0x6")])
        with open(self.eds, "w", encoding="utf-8") as f:
            f.write(VALVE.replace("DefaultValue=0x00000000\n", ""))
        self.assertIn("0x1000 has no device type default", self.run_cli("builtin", self.eds)[2])

    def test_eds_errors_name_the_line_or_section(self):
        lines = VALVE.splitlines()
        at = lines.index("[2010]") + 2
        lines[at] = "ObjectType0x7"
        with open(self.eds, "w", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")
        rc, _, err = self.run_cli("skeleton", self.eds)
        self.assertEqual(rc, 1)
        self.assertIn("line %d is not a key=value line: ObjectType0x7" % (at + 1), err)
        with open(self.eds, "w", encoding="utf-8") as f:
            f.write(VALVE.replace("SupportedObjects=5", "SupportedObjects=6"))
        rc, _, err = self.run_cli("builtin", self.eds)
        self.assertEqual(rc, 1)
        self.assertIn("[manufacturerobjects] lists 6 objects but has no entry 6", err)

    def test_check_values_on_record_key(self):
        path = self.write_notes({"0x2011": {"text": "Fault handling", "values": {"0": "hold"}},
                                 "0x2200": {"bits": {"0": "low"}}})
        rc, out, _ = self.run_cli("check", self.eds, path)
        self.assertEqual(rc, 1)
        self.assertEqual(out.splitlines(), [
            "valve.eds.notes.json: the values of 0x2011 are not used by its sub-objects; write them on its "
            "sub-object keys",
            "valve.eds.notes.json: the bits of 0x2200 are not used by its sub-objects; write them on its "
            "sub-object keys"])


class Skill(unittest.TestCase):
    """The datasheet notes skill names only commands that exist."""

    def test_frontmatter_and_commands(self):
        with open(SKILL, encoding="utf-8") as f:
            text = f.read()
        m = re.match(r"^---\n(.*?)\n---\n", text, re.S)
        self.assertTrue(m)
        self.assertRegex(m.group(1), r"(?m)^name: canworks-datasheet-notes$")
        self.assertRegex(m.group(1), r"(?m)^description: \S")
        used = set(re.findall(r"canworks-deploy notes (\w+)", text))
        self.assertEqual(used, {"skeleton", "builtin", "check"})
        choices = cli.notes_parser()._subparsers._group_actions[0].choices
        self.assertLessEqual(used, set(choices))
        flags = set(re.findall(r"canworks-deploy notes skeleton((?: --\w+(?: \S+)?)+)", text))
        named = {f for group in flags for f in re.findall(r"--\w+", group)}
        self.assertEqual(named, {"--all", "--index"})
        options = {o for a in choices["skeleton"]._actions for o in a.option_strings}
        self.assertLessEqual(named, options)


if __name__ == "__main__":
    unittest.main()
