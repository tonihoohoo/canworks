"""The files canworks-bridge gets for a config: canworks.json, the EDS
files under canworks/eds/ (the config's `eds` values rewritten to them), and
a simulation file as canworks/simulation.json, the EDS/DCF files of its extra
devices joining the node EDS files in canworks/eds/ (its `eds` values become
eds/<file>, relative to the simulation file) and its CSV files in
canworks/sim/ (`file` values sim/<file>).
"""

import json
import os

from .contract import all_nodes, eds_users
from .eds import to_utf8

EDS_DIR = "canworks/eds"  # also the rewritten `eds` value prefix
SIM_FILE = "canworks/simulation.json"
SIM_CSV_DIR = "canworks/sim"  # the simulation file's CSV files


class BundleError(Exception):
    pass


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


def _by_name(files, what):
    by_name = {}
    for value, src in files.items():
        name = os.path.basename(src)
        other = by_name.get(name)
        if other and os.path.realpath(other) != os.path.realpath(src):
            raise BundleError("two different %s are both named %s (%s and %s); rename one" % (what, name, other, src))
        by_name[name] = src
    return by_name


def rewrite(cfg, config_path):
    """Returns (deployed config, {name under conf/canworks/eds: source path}).
    Each node's and slave's `eds` becomes canworks/eds/<file name>."""
    files = eds_files(cfg, config_path)
    by_name = _by_name(files, "EDS files")
    out = json.loads(json.dumps(cfg))
    for n in eds_users(out):
        n["eds"] = "%s/%s" % (EDS_DIR, os.path.basename(files[n["eds"]]))
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


def sim_rewrite(sim_data, sim_path):
    """Returns (deployed simulation file, {name under conf/canworks/eds: source}
    for its extra devices, {name under conf/canworks/sim: source} for its CSV
    files)."""
    from . import simfile
    files = simfile.referenced_files(sim_data, sim_path)
    eds_by = _by_name(files["eds"], "EDS files of extra devices")
    csv_by = _by_name(files["csv"], "CSV files")
    eds_rel = EDS_DIR.split("/", 1)[1]
    csv_rel = SIM_CSV_DIR.split("/", 1)[1]
    out = simfile.rewrite(sim_data, sim_path, lambda p: "%s/%s" % (eds_rel, os.path.basename(p)),
                          lambda p: "%s/%s" % (csv_rel, os.path.basename(p)))
    return out, eds_by, csv_by


def files(deployed_cfg, eds_by_name, sim=None):
    """{path: bytes} of the config, its EDS files (each as UTF-8, see
    eds.to_utf8) and, with `sim` (deployed simulation file, {CSV name:
    source}), the simulation file and its CSV files; the extra devices' EDS
    files are already in eds_by_name."""
    out = {}
    for name, src in sorted(eds_by_name.items()):
        with open(src, "rb") as f:
            out[EDS_DIR + "/" + name] = to_utf8(f.read())[0]
    if sim is not None:
        sim_data, csv_by_name = sim
        for name, src in sorted(csv_by_name.items()):
            with open(src, "rb") as f:
                out[SIM_CSV_DIR + "/" + name] = f.read()
        out[SIM_FILE] = (json.dumps(sim_data, indent=2) + "\n").encode("utf-8")
    # LF on every OS: the configurator compares the bridge's SHA-256 of this
    # file with the LF form (online.fingerprints).
    out["canworks.json"] = (json.dumps(deployed_cfg, indent=2) + "\n").encode("utf-8")
    return out
