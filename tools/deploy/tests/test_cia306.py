"""The strict CiA 306 check (canworks.cia306): each rule on a small file, and
the sweep CI runs over every EDS and DCF canworks writes for the fixtures and
examples (canopen-ci "Written EDS and DCF files checked against CiA 306").
Vendor EDS files canworks only reads are never checked."""

import copy
import datetime
import glob
import json
import os
import unittest

from canworks import cia306, contract, dcfexport, slaveeds

from .test_contract import FIXTURES, REPO, load_cases

NOW = datetime.datetime(2026, 10, 16, 9, 30)
GENERATED_BY = "CreatedBy=canworks-deploy slave-eds"
BASE = os.path.join(FIXTURES, "eds", "canworks.json")  # the contract tests' base case, beside its EDS


def good():
    """A minimal EDS that passes every rule."""
    text, _ = slaveeds.generate({"device_name": "check", "date": "2026-10-16"})
    return text


def messages(text, **kw):
    return [str(f) for f in cia306.check(text, **kw)]


class Rules(unittest.TestCase):
    def test_generated_file_passes(self):
        self.assertEqual(messages(good()), [])

    def test_file_and_device_info_keys(self):
        text = good().replace("CreationDate=10-16-2026\r\n", "").replace("OrderCode=check\r\n", "")
        self.assertEqual(messages(text), ["[FileInfo] CreationDate: missing (CiA 306)",
                                          "[DeviceInfo] OrderCode: missing (CiA 306)"])
        self.assertIn("[DeviceInfo]: section missing (CiA 306)",
                      messages(good().replace("[DeviceInfo]", "[DeviceInformation]")))

    def test_date_and_time_forms(self):
        text = good().replace("CreationDate=10-16-2026", "CreationDate=2026-10-16").replace(
            "CreationTime=12:00AM", "CreationTime=00:00")
        self.assertEqual(messages(text), ["[FileInfo] CreationDate: '2026-10-16' is not a CiA 306 date (mm-dd-yyyy)",
                                          "[FileInfo] CreationTime: '00:00' is not a CiA 306 time (hh:mm followed "
                                          "by AM or PM)"])

    def test_ascii_and_line_length(self):
        text = good().replace("Description=check,", "Description=käyttö,")
        self.assertEqual(messages(text), ["[FileInfo] Description: only printable ASCII is allowed (CiA 306)"])
        text = good().replace("Description=check,", "Description=" + "x" * 300 + ",")
        self.assertIn("characters, CiA 306 allows 255", messages(text)[0])

    def test_name_lengths(self):
        text = good().replace("ProductName=check", "ProductName=" + "p" * 244)
        self.assertIn("[DeviceInfo] ProductName: is 244 characters, CiA 306 allows 243", messages(text))
        dcf = good() + "\r\n[DeviceComissioning]\r\nNodeID=2\r\nNodeName=" + "n" * 247 + "\r\n"
        self.assertIn("[DeviceComissioning] NodeName: is 247 characters, CiA 306 allows 246", messages(dcf))

    def test_object_lists(self):
        text = good().replace("[MandatoryObjects]\r\nSupportedObjects=3", "[MandatoryObjects]\r\nSupportedObjects=2")
        found = messages(text)
        self.assertIn("[MandatoryObjects] 3: entry beyond SupportedObjects=2", found)
        self.assertIn("[MandatoryObjects]: must list exactly 0x1000, 0x1001 and 0x1018 (CiA 306)", found)
        self.assertIn("[1018]: object is in no object list", found)
        text = good().replace("1=0x1000\r\n2=0x1001", "1=0x1001\r\n2=0x1000", 1)
        self.assertEqual(messages(text), ["[MandatoryObjects]: objects are not in ascending order"])

    def test_real_values_decimal(self):
        text, _ = slaveeds.generate({"date": "2026-10-16",
                                     "objects": [{"name": "t", "type": "REAL32", "direction": "to_master",
                                                  "default": 21.5}]})
        self.assertEqual(messages(text), [])
        text = text.replace("DefaultValue=21.5", "DefaultValue=0x41AC0000")
        self.assertEqual(messages(text), ["[2100sub1] DefaultValue: REAL value 0x41AC0000 is a hex bit pattern; "
                                          "CiA 306 writes REALs as decimal numbers"])

    def test_cia301_defaults(self):
        text = good().replace("ParameterName=Number of errors\r\nObjectType=0x7\r\nDataType=0x0005\r\n"
                              "AccessType=rw\r\nDefaultValue=0", "ParameterName=Number of errors\r\nObjectType=0x7\r\n"
                              "DataType=0x0005\r\nAccessType=rw\r\nDefaultValue=8")
        self.assertEqual(messages(text), ["[1003sub0] DefaultValue: is 8; CiA 301 gives 0"])
        self.assertEqual(messages(text, defaults=False), [])

    def test_only(self):
        text = good().replace("OrderCode=check\r\n", "")
        self.assertEqual(messages(text, only=lambda section, key: section == "FileInfo"), [])


def _generated_eds():
    """Every EDS file in the repository that the slave EDS generator wrote."""
    out = []
    for root in ("config", "examples", "test"):
        for path in sorted(glob.glob(os.path.join(REPO, root, "**", "*.eds"), recursive=True)):
            with open(path, encoding="utf-8", errors="replace") as f:
                if GENERATED_BY in f.read():
                    out.append(path)
    return out


def _configs():
    """Every config of the fixtures and examples with a CANopen master network."""
    paths = sorted(glob.glob(os.path.join(REPO, "examples", "*", "canworks", "canworks.json")))
    paths += sorted(glob.glob(os.path.join(REPO, "examples", "*", "canworks.json")))
    paths += sorted(glob.glob(os.path.join(REPO, "config", "*", "canopen_config.json")))
    return paths


class Sweep(unittest.TestCase):
    """What CI checks on every run: the files canworks writes."""

    def test_generated_slave_eds_files(self):
        found = _generated_eds()
        self.assertGreaterEqual(len(found), 3)
        for path in found:
            with self.subTest(os.path.relpath(path, REPO)), open(path, encoding="utf-8", newline="") as f:
                self.assertEqual(messages(f.read()), [])

    def test_exported_dcf_files(self):
        exported = 0
        for path in [BASE] + _configs():
            if path == BASE:
                cfg = copy.deepcopy(load_cases()["base"])
            else:
                with open(path, encoding="utf-8") as f:
                    cfg = json.load(f)
            if not any(n["role"] == "master" for n in contract.networks(cfg)):
                continue
            try:
                files, _ = dcfexport.export(cfg, path, now=NOW)
            except dcfexport.ExportFailed as e:
                # A config the export refuses for its own reasons (not CiA 306)
                # is the export tests' business.
                self.assertNotIn("CiA 306", str(e), os.path.relpath(path, REPO))
                continue
            for name, text in files.items():
                exported += 1
                with self.subTest(os.path.relpath(path, REPO) + ": " + name):
                    self.assertEqual(messages(text, only=dcfexport._exported, defaults=False), [])
        self.assertGreaterEqual(exported, 5)


if __name__ == "__main__":
    unittest.main()
