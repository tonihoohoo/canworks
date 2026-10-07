"""Bundle assembly: an editor build output plus conf/canopen.json, the EDS
files under conf/canopen/eds/ and any program files (`software_file`) under
conf/canopen/fw/, zipped the way the runtime's upload expects.

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

EDS_DIR = "canopen/eds"  # under conf/, and as the rewritten `eds` value prefix
FW_DIR = "canopen/fw"  # the same for `software_file`


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
    """{name under conf/canopen/fw: source path} for the program files."""
    return _by_name(software_files(cfg, config_path), "program files")


def rewrite(cfg, config_path):
    """Returns (deployed config, {name under conf/canopen/eds: source path}).
    Each node's and slave's `eds` becomes canopen/eds/<file name>, and a
    `software_file` canopen/fw/<file name> (see software_by_name())."""
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


def assemble(bundle_dir, deployed_cfg, eds_by_name, work_dir, fw_by_name=None):
    """Copies the bundle to work_dir/bundle and adds the CANopen files, each
    EDS as UTF-8 (see eds.to_utf8). Every other file is copied unchanged.
    Returns (staged directory, names of the EDS files converted to UTF-8)."""
    staged = os.path.join(work_dir, "bundle")
    shutil.copytree(bundle_dir, staged, symlinks=False)
    conf = os.path.join(staged, "conf")
    os.makedirs(conf, exist_ok=True)
    shutil.rmtree(os.path.join(conf, "canopen"), ignore_errors=True)
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
    with open(os.path.join(conf, "canopen.json"), "w", encoding="utf-8") as f:
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
    return tempfile.mkdtemp(prefix="openplc-canopen-deploy-")
