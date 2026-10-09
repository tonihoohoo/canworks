"""Device notes (spec canopen-device-notes): the notes file format, the
built-in CiA notes, the merge and the checks."""

import filecmp
import json
import os
import unittest

import jsonschema

from canworks import notes
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


if __name__ == "__main__":
    unittest.main()
