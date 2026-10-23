"""Writes the CODESYS export folder and runs the CODESYS script headless
(canworks-deploy --export-codesys and --codesys-import)."""

import glob
import json
import os
import re
import subprocess
import sys
import tempfile

from . import plan as plan_mod
from ..userdirs import replace_file

# Where CODESYS installs itself on Windows: <root>\CODESYS <version>\CODESYS\Common\CODESYS.exe
PROGRAM_ROOTS = ("PROGRAMFILES", "PROGRAMFILES(X86)", "PROGRAMW6432")


class CodesysError(Exception):
    pass


def write_folder(files, out_dir):
    """Writes {name: text} into out_dir; returns the written paths."""
    written = []
    for name, text in sorted(files.items()):
        path = os.path.join(out_dir, *name.split("/"))
        os.makedirs(os.path.dirname(path), exist_ok=True)
        fd, tmp = tempfile.mkstemp(prefix="." + os.path.basename(path) + ".", dir=os.path.dirname(path))
        try:
            with os.fdopen(fd, "w", encoding="utf-8", newline="") as f:
                f.write(text)
            replace_file(tmp, path)
        except BaseException:
            if os.path.exists(tmp):
                os.remove(tmp)
            raise
        written.append(path)
    return written


def _version(path):
    m = re.search(r"CODESYS[ _]V?(\d+(?:\.\d+)*)", path)
    return tuple(int(x) for x in m.group(1).split(".")) if m else ()


def find_codesys(environ=None):
    """The newest CODESYS.exe in the standard program folders, or None."""
    environ = os.environ if environ is None else environ
    found = set()
    for var in PROGRAM_ROOTS:
        root = environ.get(var)
        if root:
            found.update(glob.glob(os.path.join(root, "CODESYS*", "CODESYS", "Common", "CODESYS.exe")))
    return max(found, key=lambda p: (_version(p), p)) if found else None


def find_profile(exe):
    """The newest profile name of the CODESYS install `exe` belongs to, or None."""
    folder = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(exe))), "Profiles")
    names = [os.path.basename(p)[:-len(".profile.xml")] for p in glob.glob(os.path.join(folder, "*.profile.xml"))]

    def key(name):
        return [int(x) for x in re.findall(r"\d+", name)], name
    return max(names, key=key) if names else None


def command_line(exe, profile, script):
    """The CODESYS command line. CODESYS reads --profile="..." and
    --runscript="..." with the quotes inside the argument, so the line is
    built by hand rather than by subprocess's quoting."""
    return '"%s" --profile="%s" --noUI --runscript="%s"' % (exe, profile, script)


def run_codesys(exe, profile, folder, timeout=1800, runner=None):
    """Runs the script in `folder` headless and returns the report text.
    Raises CodesysError when CODESYS fails to run or writes no report."""
    script = os.path.join(folder, plan_mod.SCRIPT_NAME)
    report = os.path.join(folder, plan_mod.REPORT_NAME)
    if os.path.exists(report):
        os.remove(report)
    line = command_line(exe, profile, script)
    try:
        if runner is not None:
            runner(line)
        elif sys.platform == "win32":
            subprocess.run(line, timeout=timeout, check=False)
        else:
            raise CodesysError("CODESYS runs on Windows; run the script there")
    except (OSError, subprocess.SubprocessError) as e:
        raise CodesysError("CODESYS did not run: %s" % e)
    try:
        with open(report, encoding="utf-8") as f:
            return f.read()
    except OSError:
        raise CodesysError("CODESYS wrote no %s: check that the profile %r fits %s" % (plan_mod.REPORT_NAME, profile,
                                                                                    exe))


EXPORT_SCRIPT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "script", "export_canworks_xml.py")
IN_USE = ("the project is open in CODESYS: close it there, or export it in CODESYS (Project > Export PLCopenXML, "
          "the device with the CANopen Manager) and import that .xml file")


def export_project(project, device=None, exe=None, profile=None, folder=None, timeout=600, runner=None):
    """Exports a CODESYS project headless for Import from CODESYS: (the
    devices that have a CANopen Manager [{name, buses, nodes, active}], the
    PLCopenXML path or None when there are several devices and none was
    named). Never changes the project."""
    exe = exe or find_codesys()
    if not exe:
        raise CodesysError("CODESYS is not installed on this PC: export the project in CODESYS (Project > Export "
                           "PLCopenXML) and import that .xml file")
    profile = profile or find_profile(exe)
    if not profile:
        raise CodesysError("no CODESYS profile found next to %s" % exe)
    folder = folder or tempfile.mkdtemp(prefix="canworks-codesys-import-")
    with open(EXPORT_SCRIPT, encoding="utf-8") as f:
        script = f.read()
    with open(os.path.join(folder, "export_canworks_xml.py"), "w", encoding="utf-8", newline="") as f:
        f.write(script)
    with open(os.path.join(folder, "canworks-export.json"), "w", encoding="utf-8", newline="") as f:
        json.dump({"project": os.path.abspath(project), "device": device}, f)
    for name in ("export_report.txt", "devices.json", "canworks-export.xml"):
        if os.path.exists(os.path.join(folder, name)):
            os.remove(os.path.join(folder, name))
    line = command_line(exe, profile, os.path.join(folder, "export_canworks_xml.py"))
    try:
        if runner is not None:
            runner(line)
        elif sys.platform == "win32":
            subprocess.run(line, timeout=timeout, check=False)
        else:
            raise CodesysError("CODESYS runs on Windows")
    except (OSError, subprocess.SubprocessError) as e:
        raise CodesysError("CODESYS did not run: %s" % e)
    try:
        with open(os.path.join(folder, "export_report.txt"), encoding="utf-8") as f:
            report = f.read()
    except OSError:
        raise CodesysError("CODESYS wrote no export_report.txt: check that the profile %r fits %s" % (profile, exe))
    if not report_ok(report):
        detail = report.split("\n", 1)[1].strip() if "\n" in report else report
        if "in use" in detail:
            raise CodesysError(IN_USE)
        raise CodesysError("the CODESYS export failed: %s" % detail.replace("error: ", "", 1))
    with open(os.path.join(folder, "devices.json"), encoding="utf-8") as f:
        found = json.load(f)
    xml = os.path.join(folder, "canworks-export.xml")
    return found, xml if os.path.isfile(xml) else None


def report_ok(text):
    return text.startswith("result: ok")


def set_target(folder, project, create=None):
    """Puts the project (or the new project) into the folder's plan."""
    path = os.path.join(folder, plan_mod.PLAN_NAME)
    with open(path, encoding="utf-8") as f:
        plan = json.load(f)
    plan["project"] = None if create else os.path.abspath(project)
    plan["create"] = create
    with open(path, "w", encoding="utf-8", newline="") as f:
        f.write(json.dumps(plan, indent=2) + "\n")


# The PLC device type of CODESYS device descriptions (DeviceIdentification Type).
PLC_TYPE = 4096


def repository_roots(exe=None, environ=None):
    """The device repository folders of CODESYS, existing ones only: the
    `Devices=` folders of <install>\\CODESYS\\Settings\\RepositoryLocations.ini
    next to `exe` (the newest CODESYS when None), else
    <ProgramData>\\CODESYS\\Devices."""
    import configparser
    environ = os.environ if environ is None else environ
    exe = exe or find_codesys(environ)
    roots = []
    if exe:
        ini = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(exe))), "Settings",
                           "RepositoryLocations.ini")
        parser = configparser.ConfigParser(interpolation=None, strict=False)
        try:
            parser.read(ini, encoding="utf-8-sig")
        except (configparser.Error, OSError, UnicodeDecodeError):
            pass
        for section in parser.sections():
            path = parser.get(section, "Devices", fallback=None)
            if path and os.path.isdir(path) and path not in roots:
                roots.append(path)
    if not roots:
        for var in ("PROGRAMDATA", "ALLUSERSPROFILE"):
            base = environ.get(var)
            path = os.path.join(base, "CODESYS", "Devices") if base else None
            if path and os.path.isdir(path) and path not in roots:
                roots.append(path)
    return roots


def _local(tag):
    return tag.rsplit("}", 1)[-1]


def read_device(path):
    """{type, id, version, name, vendor, hidden} of a device description
    (device.xml), or None when it has no readable device identification."""
    import xml.etree.ElementTree as ET
    ident, info = {}, {}
    where = []
    hidden = False
    try:
        for event, elem in ET.iterparse(path, events=("start", "end")):
            tag = _local(elem.tag)
            if event == "start":
                where.append(tag)
                if tag == "Device" and elem.get("hideInCatalogue") == "true":
                    hidden = True
                continue
            where.pop()
            parent = where[-1] if where else None
            if parent == "DeviceIdentification" and tag in ("Type", "Id", "Version"):
                ident[tag] = (elem.text or "").strip()
            elif parent == "DeviceInfo" and tag in ("Name", "Vendor") and tag not in info:
                info[tag] = (elem.text or "").strip()
            elif tag == "DeviceInfo" and len(ident) == 3:
                break
            if tag in ("Connector", "Functional", "ExtendedSettings"):
                elem.clear()
    except (ET.ParseError, OSError, UnicodeDecodeError):
        return None
    if not ident.get("Type", "").isdigit() or not ident.get("Id") or not ident.get("Version"):
        return None
    return {"type": int(ident["Type"]), "id": ident["Id"], "version": ident["Version"],
            "name": info.get("Name") or ident["Id"], "vendor": info.get("Vendor") or "", "hidden": hidden}


def list_plc_devices(roots=None):
    """The PLC devices installed in CODESYS, as the device catalogue shows
    them: each <root>\\4096\\<Id>\\<Version>\\device.xml of type 4096 not
    hidden in the catalogue, sorted by name and newest version first."""
    roots = repository_roots() if roots is None else roots
    found = {}
    for root in roots:
        for folder, _, names in os.walk(os.path.join(root, str(PLC_TYPE))):
            for name in names:
                if name.lower() != "device.xml":
                    continue
                d = read_device(os.path.join(folder, name))
                if d and d["type"] == PLC_TYPE and not d.pop("hidden"):
                    found.setdefault((d["type"], d["id"], d["version"]), d)

    def key(d):
        return d["name"].lower(), [-n for n in _version_numbers(d["version"])]
    return sorted(found.values(), key=key)


def _version_numbers(version):
    return [int(x) for x in re.findall(r"\d+", version)]


def project_path(path):
    """The project file CODESYS writes for `path`: `.project` added when the
    name has no extension."""
    name = re.split(r"[\\/]", path.rstrip("\\/"))[-1]
    return path if os.path.splitext(name)[1] else path + ".project"


def parse_device(text):
    """TYPE:ID:VERSION -> {type, id, version}."""
    parts = (text or "").split(":", 2)
    if len(parts) != 3 or not parts[0].strip().isdigit() or not parts[1].strip() or not parts[2].strip():
        raise ValueError("give the PLC device as TYPE:ID:VERSION, for example 4096:0000 0004:3.5.22.40")
    return {"type": int(parts[0]), "id": parts[1].strip(), "version": parts[2].strip()}


def parse_net(values):
    """['field=1', ...] -> {'field': 1}."""
    out = {}
    for v in values or []:
        name, sep, number = v.partition("=")
        if not sep or not name or not number.strip().isdigit():
            raise ValueError("--codesys-net takes NAME=N with a network number N, not %r" % v)
        out[name] = int(number)
    return out


def parse_can(values):
    """['field=CAN2', ...] -> {'field': 'CAN2'}: the CAN interface object
    in the CODESYS device that gets a network's bus."""
    out = {}
    for v in values or []:
        name, sep, obj = v.partition("=")
        if not sep or not name or not obj.strip():
            raise ValueError("--codesys-can takes NETWORK=OBJECT with the name of a CAN interface object in the "
                             "CODESYS device, not %r" % v)
        out[name] = obj.strip()
    return out
