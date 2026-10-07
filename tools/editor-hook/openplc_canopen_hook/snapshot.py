"""Takes the CANopen config out of an OpenPLC Editor project snapshot.

The editor (4.3.x) uploads the whole project folder as a zip next to the
program. A project may carry its CANopen config as canopen/canopen.json plus
the EDS files it names, relative to canopen/. materialize() checks that
config the way the deploy tool does and, only if everything is in order,
writes it into the upload's conf/ directory in the deploy tool's layout:

    conf/canopen.json              (each node's eds -> canopen/eds/<name>,
                                    software_file -> canopen/fw/<name>)
    conf/canopen/eds/<name>
    conf/canopen/fw/<name>

so the runtime's own plugin configuration step enables the plugin. A
simulation file next to the config (canopen/simulation.json, its paths
relative to canopen/ as well) is checked against the config and travels
too, in the deploy tool's layout:

    conf/canopen/simulation.json   (each extra device's eds -> eds/<name>,
                                    each CSV file -> sim/<name>)
    conf/canopen/eds/<name>        (the extra devices' EDS files)
    conf/canopen/sim/<name>        (its CSV files)

It never writes anything when a check fails.
"""

import json
import os
import posixpath
import shutil
import stat
import tempfile
import zipfile

from openplc_canopen_deploy import bundle, contract, simfile
from openplc_canopen_deploy.bundle import EDS_DIR, FW_DIR, SIM_CSV_DIR, SIM_FILE

PROJECT_DIR = "canopen"
CONFIG_NAME = "canopen.json"
SIM_NAME = simfile.FILE_NAME
MAX_TOTAL_BYTES = 16 * 1024 * 1024
REPLACEMENT_CHAR = b"\xef\xbf\xbd"  # U+FFFD in UTF-8

INFO, WARNING = "INFO", "WARNING"


class Rejected(Exception):
    """The project's CANopen config cannot be used; the message says why."""


def _project_root(names):
    """The prefix of the project folder inside the zip: "" when the project
    is at the zip root, "<dir>/" when everything sits in one folder."""
    if PROJECT_DIR + "/" + CONFIG_NAME in names:
        return ""
    tops = {n.split("/", 1)[0] for n in names if n}
    if len(tops) == 1:
        top = tops.pop() + "/"
        if top + PROJECT_DIR + "/" + CONFIG_NAME in names:
            return top
    return None


def _safe_relative(value):
    """The normalized relative path of an `eds` value inside canopen/, or
    None when it is absolute, leaves canopen/ or is otherwise unusable."""
    if not isinstance(value, str) or not value or "\\" in value or "\0" in value:
        return None
    if value.startswith("/") or (len(value) > 1 and value[1] == ":"):
        return None
    parts = value.split("/")
    if any(p in ("", ".", "..") for p in parts):
        return None
    return posixpath.join(*parts)


def _member(z, name):
    """The zip entry `name` if it is a regular file, else None."""
    try:
        info = z.getinfo(name)
    except KeyError:
        return None
    # Unix file type bits, when the zip has them (a symlink is S_IFLNK); a
    # zip without them holds only plain files and folders.
    kind = stat.S_IFMT(info.external_attr >> 16)
    if info.is_dir() or (kind and kind != stat.S_IFREG):
        return None
    return info


def _read(z, info, budget):
    if info.file_size > budget[0]:
        raise Rejected("the CANopen files in the project are larger than %d MiB in total"
                       % (MAX_TOTAL_BYTES // (1024 * 1024)))
    with z.open(info) as f:
        data = f.read(budget[0] + 1)
    if len(data) > budget[0]:
        raise Rejected("the CANopen files in the project are larger than %d MiB in total"
                       % (MAX_TOTAL_BYTES // (1024 * 1024)))
    budget[0] -= len(data)
    return data


def _load(snapshot_zip):
    """Reads and checks the project's config. Returns (config, {eds value:
    bytes}, {software_file value: bytes}, warnings), or None when the
    project has no CANopen config."""
    with zipfile.ZipFile(snapshot_zip) as z:
        names = set(z.namelist())
        root = _project_root(names)
        if root is None:
            return None
        where = PROJECT_DIR + "/" + CONFIG_NAME
        info = _member(z, root + where)
        if info is None:
            raise Rejected("%s is not a regular file" % where)
        budget = [MAX_TOTAL_BYTES]
        try:
            cfg = json.loads(_read(z, info, budget).decode("utf-8"))
        except (UnicodeDecodeError, ValueError) as e:
            raise Rejected("%s is not valid JSON: %s" % (where, e))
        if not isinstance(cfg, dict) or not isinstance(cfg.get("nodes"), list):
            raise Rejected("%s: top level must be an object with a 'nodes' list" % where)

        eds = {}
        for n in cfg["nodes"]:
            value = n.get("eds") if isinstance(n, dict) else None
            if value in eds or value is None:
                continue
            rel = _safe_relative(value)
            if rel is None:
                raise Rejected("%s: invalid EDS path %r (it must be a relative path inside %s/)"
                               % (where, value, PROJECT_DIR))
            member = _member(z, root + PROJECT_DIR + "/" + rel)
            if member is None:
                raise Rejected("%s/%s is missing from the project (named by %s)" % (PROJECT_DIR, rel, where))
            data = _read(z, member, budget)
            if REPLACEMENT_CHAR in data:
                raise Rejected("%s/%s is not UTF-8: the editor replaced some of its characters when it "
                               "uploaded the project. Save the EDS as UTF-8, or copy it into the project "
                               "with openplc-canopen-deploy --into-project, which converts it"
                               % (PROJECT_DIR, rel))
            eds[value] = data

        software = {}
        for n in cfg["nodes"]:
            value = n.get("software_file") if isinstance(n, dict) else None
            if value in software or value is None:
                continue
            rel = _safe_relative(value)
            if rel is None:
                raise Rejected("%s: invalid software_file path %r (it must be a relative path inside %s/)"
                               % (where, value, PROJECT_DIR))
            member = _member(z, root + PROJECT_DIR + "/" + rel)
            if member is None:
                raise Rejected("%s/%s is missing from the project (named by %s)" % (PROJECT_DIR, rel, where))
            data = _read(z, member, budget)
            if REPLACEMENT_CHAR in data:
                raise Rejected("%s/%s was corrupted: the editor uploads project files as text. Deploy a "
                               "program file with openplc-canopen-deploy --runtime instead" % (PROJECT_DIR, rel))
            software[value] = data

        sim = _read_sim(z, root, names, budget)

    # The deploy tool's checks, on the files as they arrived.
    work = tempfile.mkdtemp(prefix="openplc-canopen-hook-")
    try:
        def stage(files, tag):
            paths = {}
            for i, (value, data) in enumerate(sorted(files.items())):
                d = os.path.join(work, "%s%d" % (tag, i))
                os.makedirs(d)
                p = os.path.join(d, posixpath.basename(value))
                with open(p, "wb") as f:
                    f.write(data)
                paths[value] = p
            return paths

        eds_paths = stage(eds, "e")
        result = contract.check_config(cfg, where, eds_paths=eds_paths, software_paths=stage(software, "f"))
        if not result.ok:
            raise Rejected("; ".join(result.errors))
        warnings = list(result.warnings)
        if sim is not None:
            sim, sim_warnings = _check_sim(sim, cfg, eds_paths, work)
            warnings += sim_warnings
    finally:
        shutil.rmtree(work, ignore_errors=True)
    return cfg, eds, software, warnings, sim


def _read_sim(z, root, names, budget):
    """(parsed simulation file, {relative path inside canopen/: bytes} of
    the files it names), or None when the project has none."""
    where = PROJECT_DIR + "/" + SIM_NAME
    if root + where not in names:
        return None
    info = _member(z, root + where)
    if info is None:
        raise Rejected("%s is not a regular file" % where)
    try:
        data = json.loads(_read(z, info, budget).decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as e:
        raise Rejected("%s is not valid JSON: %s" % (where, e))
    files = {}
    # Paths as the simulation file names them; "/" stands for canopen/.
    referenced = simfile.referenced_files(data, "/" + SIM_NAME)
    for kind, what in (("eds", "EDS path"), ("csv", "CSV file path")):
        for value in sorted(referenced[kind]):
            rel = _safe_relative(value)
            if rel is None:
                raise Rejected("%s: invalid %s %r (it must be a relative path inside %s/)"
                               % (where, what, value, PROJECT_DIR))
            if rel in files:
                continue
            member = _member(z, root + PROJECT_DIR + "/" + rel)
            if member is None:
                raise Rejected("%s/%s is missing from the project (named by %s)" % (PROJECT_DIR, rel, where))
            content = _read(z, member, budget)
            if REPLACEMENT_CHAR in content:
                raise Rejected("%s/%s (named by %s) is not UTF-8: the editor replaced some of its characters "
                               "when it uploaded the project. Save it as UTF-8" % (PROJECT_DIR, rel, where))
            files[rel] = content
    return data, files


def _check_sim(sim, cfg, eds_paths, work):
    """The deploy tool's simulation file checks and rewrite, on the files as
    they arrived, staged in work/canopen/. Returns ((deployed simulation
    file, {extra device EDS name: bytes}, {CSV name: bytes}), warnings)."""
    data, files = sim
    top = os.path.join(work, PROJECT_DIR)
    for rel, content in files.items():
        p = os.path.join(top, *rel.split("/"))
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "wb") as f:
            f.write(content)
    os.makedirs(top, exist_ok=True)
    path = os.path.join(top, SIM_NAME)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f)

    def shown(text):  # the staged paths as the project names them
        return text.replace(work + os.sep, "")

    result = simfile.check(data, path, cfg, eds_paths=eds_paths)
    if not result.ok:
        raise Rejected("; ".join(shown(e) for e in result.errors))
    try:
        out, eds_by, csv_by = bundle.sim_rewrite(data, path)
    except bundle.BundleError as e:
        raise Rejected(shown(str(e)))

    def contents(by_name):
        out = {}
        for name, src in by_name.items():
            with open(src, "rb") as f:
                out[name] = f.read()
        return out

    return (out, contents(eds_by), contents(csv_by)), [shown(w) for w in result.warnings]


def materialize(snapshot_zip, conf_dir):
    """Puts the project's CANopen config from `snapshot_zip` into `conf_dir`
    unless the upload already brought one. Returns (applied, [(level, text)])."""
    if os.path.exists(os.path.join(conf_dir, CONFIG_NAME)):
        return False, [(INFO, "CANopen: the upload carries conf/canopen.json; the project snapshot is not used")]
    if not os.path.isfile(snapshot_zip):
        return False, []
    try:
        loaded = _load(snapshot_zip)
    except Rejected as e:
        return False, [(WARNING, "CANopen: project config ignored: %s" % e)]
    except (zipfile.BadZipFile, OSError) as e:
        return False, [(WARNING, "CANopen: project config ignored: cannot read the project snapshot: %s" % e)]
    if loaded is None:
        return False, []
    cfg, eds, software, warnings, sim = loaded

    by_name = {}
    for value, data in eds.items():
        name = posixpath.basename(value)
        if name in by_name and by_name[name] != data:
            return False, [(WARNING, "CANopen: project config ignored: two different EDS files are both "
                                     "named %s; rename one" % name)]
        by_name[name] = data
    if sim is not None:
        for name, data in sim[1].items():
            if name in by_name and by_name[name] != data:
                return False, [(WARNING, "CANopen: project config ignored: two different EDS files are both "
                                         "named %s (one of them for an extra device of %s/%s); rename one"
                                % (name, PROJECT_DIR, SIM_NAME))]
            by_name[name] = data
    fw_by_name = {}
    for value, data in software.items():
        name = posixpath.basename(value)
        if name in fw_by_name and fw_by_name[name] != data:
            return False, [(WARNING, "CANopen: project config ignored: two different program files are both "
                                     "named %s; rename one" % name)]
        fw_by_name[name] = data
    out = json.loads(json.dumps(cfg))
    for n in out["nodes"]:
        n["eds"] = "%s/%s" % (EDS_DIR, posixpath.basename(n["eds"]))
        if n.get("software_file"):
            n["software_file"] = "%s/%s" % (FW_DIR, posixpath.basename(n["software_file"]))

    eds_dir = os.path.join(conf_dir, *EDS_DIR.split("/"))
    shutil.rmtree(os.path.join(conf_dir, EDS_DIR.split("/")[0]), ignore_errors=True)
    os.makedirs(eds_dir)
    for name, data in sorted(by_name.items()):
        with open(os.path.join(eds_dir, name), "wb") as f:
            f.write(data)
    if fw_by_name:
        fw_dir = os.path.join(conf_dir, *FW_DIR.split("/"))
        os.makedirs(fw_dir)
        for name, data in sorted(fw_by_name.items()):
            with open(os.path.join(fw_dir, name), "wb") as f:
                f.write(data)
    if sim is not None:
        sim_data, sim_eds, sim_csv = sim
        if sim_csv:
            csv_dir = os.path.join(conf_dir, *SIM_CSV_DIR.split("/"))
            os.makedirs(csv_dir)
            for name, data in sorted(sim_csv.items()):
                with open(os.path.join(csv_dir, name), "wb") as f:
                    f.write(data)
        with open(os.path.join(conf_dir, *SIM_FILE.split("/")), "w", encoding="utf-8") as f:
            json.dump(sim_data, f, indent=2)
            f.write("\n")
    with open(os.path.join(conf_dir, CONFIG_NAME), "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2)
        f.write("\n")
    msgs = [(WARNING, "CANopen: %s" % w) for w in warnings]
    simulated = simfile.describe_simulated(cfg)
    if simulated:
        msgs.append((WARNING, "CANopen: this config simulates devices: %s. Outputs to a simulated device go "
                              "nowhere; never leave a machine's config simulated." % simulated))
    msgs.append((INFO, "CANopen: config taken from the project snapshot (%s/%s, %d EDS file%s)"
                 % (PROJECT_DIR, CONFIG_NAME, len(by_name), "" if len(by_name) == 1 else "s")))
    if sim is not None:
        msgs.append((INFO, "CANopen: simulation file carried (%s/%s, %d extra device EDS file%s, %d CSV file%s)%s"
                     % (PROJECT_DIR, SIM_NAME, len(sim_eds), "" if len(sim_eds) == 1 else "s",
                        len(sim_csv), "" if len(sim_csv) == 1 else "s",
                        "" if simulated else "; the config simulates nothing, so it has no effect")))
    return True, msgs


def main(argv=None):
    """python -m openplc_canopen_hook.snapshot <snapshot.zip> <conf dir>:
    runs materialize() and prints {"applied": bool, "messages": [[level, text]]}."""
    import sys
    args = sys.argv[1:] if argv is None else argv
    if len(args) != 2:
        sys.stderr.write("usage: python -m openplc_canopen_hook.snapshot <snapshot.zip> <conf dir>\n")
        return 2
    applied, messages = materialize(args[0], args[1])
    json.dump({"applied": applied, "messages": messages}, sys.stdout)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
