"""Bundle assembly: an editor build output plus conf/canworks.json, the EDS
files under conf/canworks/eds/ and any program files (`software_file`) under
conf/canworks/fw/, zipped the way the runtime's upload expects. A simulation
file goes to conf/canworks/simulation.json; the EDS/DCF files of its extra
devices join the node EDS files in conf/canworks/eds/ (its `eds` values become
eds/<file>, relative to the simulation file), its CSV files go to
conf/canworks/sim/ (`file` values sim/<file>) and the machine files its
sections name go next to it under their relative names (machine.json).

The editor's "Build only" (and `openplc-cli compile`) writes the runtime v4
bundle to <project>/build/<target>/src/: generated.hpp, the generated *.cpp,
strucpp_runtime/include/ and conf/ with the other plugins' configs. The
runtime extracts the zip to core/generated/ and compiles it there.
"""

import glob
import json
import os
import shutil
import tempfile
import zipfile

from .contract import all_nodes, eds_users
from .eds import to_utf8

EDS_DIR = "canworks/eds"  # under conf/, and as the rewritten `eds` value prefix
FW_DIR = "canworks/fw"  # the same for `software_file`
SIM_FILE = "canworks/simulation.json"  # under conf/
SIM_CSV_DIR = "canworks/sim"  # under conf/: the simulation file's CSV files


class BundleError(Exception):
    pass


def check_editor_bundle(path):
    """Raises BundleError unless `path` is a runtime v4 bundle directory."""
    if not os.path.isdir(path):
        raise BundleError("%s is not a directory" % path)
    if not os.path.isfile(os.path.join(path, "generated.hpp")) or not glob.glob(os.path.join(path, "*.cpp")):
        raise BundleError(
            "%s is not an editor build output: it has no generated.hpp and *.cpp program sources for the runtime "
            "to compile. Build the project with the editor's \"Build only\" for the OpenPLC Runtime v4 target "
            "(or openplc-cli compile) and pass <project>/build/<target>/src" % path)


def eds_files(cfg, config_path):
    """{eds value: absolute path on this PC} for every node and every slave
    network's own EDS, relative values resolved against the config file's
    directory."""
    base = os.path.dirname(os.path.abspath(config_path))
    out = {}
    for n in eds_users(cfg):
        value = n.get("eds")
        if isinstance(value, str) and value:
            out[value] = value if os.path.isabs(value) else os.path.join(base, value)
    return out


def missing_eds(cfg, config_path):
    """Messages for EDS files that do not exist, naming node ID (or the
    slave) and file."""
    files = eds_files(cfg, config_path)
    nodes = all_nodes(cfg)
    problems = []
    for n in eds_users(cfg):
        value = n.get("eds")
        if isinstance(value, str) and value and not os.path.isfile(files[value]):
            problems.append("%s: EDS file %s not found (eds: \"%s\" in %s)"
                            % ("node %s" % n.get("node_id") if any(n is x for x in nodes) else "slave", files[value],
                               value, config_path))
    return problems


def software_files(cfg, config_path):
    """{software_file value: absolute path on this PC}, like eds_files()."""
    base = os.path.dirname(os.path.abspath(config_path))
    out = {}
    for n in all_nodes(cfg):
        value = n.get("software_file")
        if isinstance(value, str) and value:
            out[value] = value if os.path.isabs(value) else os.path.join(base, value)
    return out


def _by_name(files, what):
    by_name = {}
    for value, src in files.items():
        name = os.path.basename(src)
        other = by_name.get(name)
        if other and os.path.realpath(other) != os.path.realpath(src):
            raise BundleError("two different %s are both named %s (%s and %s); rename one" % (what, name, other, src))
        by_name[name] = src
    return by_name


def software_by_name(cfg, config_path):
    """{name under conf/canworks/fw: source path} for the program files."""
    return _by_name(software_files(cfg, config_path), "program files")


def rewrite(cfg, config_path):
    """Returns (deployed config, {name under conf/canworks/eds: source path}).
    Each node's and slave's `eds` becomes canworks/eds/<file name>, and a
    `software_file` canworks/fw/<file name> (see software_by_name())."""
    files = eds_files(cfg, config_path)
    by_name = _by_name(files, "EDS files")
    software = software_files(cfg, config_path)
    _by_name(software, "program files")
    out = json.loads(json.dumps(cfg))
    for n in eds_users(out):
        n["eds"] = "%s/%s" % (EDS_DIR, os.path.basename(files[n["eds"]]))
        if n.get("software_file"):
            n["software_file"] = "%s/%s" % (FW_DIR, os.path.basename(software[n["software_file"]]))
    return out, by_name


def merge_by_name(by_name, more, what):
    """Adds {name: source} entries to by_name; BundleError when a name is
    taken by a different file."""
    for name, src in more.items():
        other = by_name.get(name)
        if other and os.path.realpath(other) != os.path.realpath(src):
            raise BundleError("two different %s are both named %s (%s and %s); rename one" % (what, name, other, src))
        by_name[name] = src
    return by_name


def machine_name(value, src):
    """The name under conf/canworks/ of a machine file the simulation file
    names `value`: the value itself when it is a plain relative path that
    stays out of the folders the bundle fills, else the file's name."""
    parts = value.replace("\\", "/").split("/")
    reserved = {EDS_DIR.split("/", 1)[1], FW_DIR.split("/", 1)[1], SIM_CSV_DIR.split("/", 1)[1]}
    if os.path.isabs(value) or any(p in ("", ".", "..") for p in parts) or ":" in value or \
            (len(parts) > 1 and parts[0] in reserved):
        return os.path.basename(src)
    return "/".join(parts)


def sim_rewrite(sim_data, sim_path):
    """Returns (deployed simulation file, {name under conf/canworks/eds: source}
    for its extra devices, {name under conf/canworks/sim: source} for its CSV
    files, {name under conf/canopen: source} for its machine files)."""
    from . import simfile
    files = simfile.referenced_files(sim_data, sim_path)
    eds_by = _by_name(files["eds"], "EDS files of extra devices")
    csv_by = _by_name(files["csv"], "CSV files")
    machine_by = {}
    for value, src in sorted(files["machine"].items()):
        name = machine_name(value, src)
        if name == SIM_FILE.split("/", 1)[1] or name == "canworks.json":
            raise BundleError("a machine file may not be named %s" % name)
        merge_by_name(machine_by, {name: src}, "machine files")
    eds_rel = EDS_DIR.split("/", 1)[1]
    csv_rel = SIM_CSV_DIR.split("/", 1)[1]
    out = simfile.rewrite(sim_data, sim_path, lambda p: "%s/%s" % (eds_rel, os.path.basename(p)),
                          lambda p: "%s/%s" % (csv_rel, os.path.basename(p)), machine_name)
    return out, eds_by, csv_by, machine_by


def assemble(bundle_dir, deployed_cfg, eds_by_name, work_dir, fw_by_name=None, sim=None):
    """Copies the bundle to work_dir/bundle and adds the CANopen files, each
    EDS as UTF-8 (see eds.to_utf8). Every other file is copied unchanged.
    sim: (deployed simulation file, {CSV name: source}[, {machine file name:
    source}]), whose extra devices' EDS files are already in eds_by_name.
    Returns (staged directory, names of the EDS files converted to UTF-8)."""
    staged = os.path.join(work_dir, "bundle")
    shutil.copytree(bundle_dir, staged, symlinks=False)
    conf = os.path.join(staged, "conf")
    os.makedirs(conf, exist_ok=True)
    shutil.rmtree(os.path.join(conf, "canworks"), ignore_errors=True)
    eds_dir = os.path.join(conf, *EDS_DIR.split("/"))
    os.makedirs(eds_dir)
    converted = []
    for name, src in sorted(eds_by_name.items()):
        with open(src, "rb") as f:
            data, was = to_utf8(f.read())
        if was:
            converted.append(name)
        with open(os.path.join(eds_dir, name), "wb") as f:
            f.write(data)
    if fw_by_name:
        fw_dir = os.path.join(conf, *FW_DIR.split("/"))
        os.makedirs(fw_dir)
        for name, src in sorted(fw_by_name.items()):
            shutil.copyfile(src, os.path.join(fw_dir, name))
    if sim is not None:
        sim_data, csv_by_name = sim[:2]
        for name, src in sorted((sim[2] if len(sim) > 2 else {}).items()):
            dst = os.path.join(conf, "canworks", *name.split("/"))
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            shutil.copyfile(src, dst)
        if csv_by_name:
            csv_dir = os.path.join(conf, *SIM_CSV_DIR.split("/"))
            os.makedirs(csv_dir)
            for name, src in sorted(csv_by_name.items()):
                shutil.copyfile(src, os.path.join(csv_dir, name))
        with open(os.path.join(conf, *SIM_FILE.split("/")), "w", encoding="utf-8", newline="\n") as f:
            json.dump(sim_data, f, indent=2)
            f.write("\n")
    # LF on every OS: the configurator compares the runtime's SHA-256 of this
    # file with the LF form (online.fingerprints).
    with open(os.path.join(conf, "canworks.json"), "w", encoding="utf-8", newline="\n") as f:
        json.dump(deployed_cfg, f, indent=2)
        f.write("\n")
    return staged, converted


def make_zip(staged, zip_path):
    """Zips the staged bundle with its files at the zip root."""
    entries = []
    for root, dirs, files in os.walk(staged):
        dirs.sort()
        for name in sorted(files):
            full = os.path.join(root, name)
            rel = os.path.relpath(full, staged).replace(os.sep, "/")
            if ":" in rel or ".." in rel.split("/"):
                raise BundleError("%s: the runtime rejects this file name" % rel)
            entries.append((full, rel))
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as z:
        for full, rel in entries:
            z.write(full, rel)
    return [rel for _, rel in entries]


def temp_dir():
    return tempfile.mkdtemp(prefix="canworks-deploy-")
