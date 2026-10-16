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
            os.replace(tmp, path)
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
