"""IEC address clashes across every plugin config in a bundle's conf/*.json.

Every string under a key in LOCATION_KEYS (`iec_location`, the node status,
state, EMCY and NMT command keys, the SDO variable keys, the master's bus
diagnostic keys, a slave network's status keys) is a location, wherever it
sits in the file; a sibling integer `len` (the Modbus master's format) makes it
a run of that many consecutive elements. This works
for the EtherCAT and Modbus master configs without knowing their schemas.

Each size letter is its own table in the OpenPLC image, so two locations clash
only in the same area and size: %IW100 and %ID100 are different variables,
%IX1.0 and %IB1 too. Rules (design D8):
  %I between two plugins: error (both write the same input)
  %Q between two plugins: warning (both only read the output)
  %M between two plugins: warning
Inside canopen.json any overlap is an error, as in the plugin.
"""

import glob
import json
import os

from .iec import parse_location, element_str

LOCATION_KEYS = ("iec_location", "status_location", "state_location", "boot_error_location", "bus_state_location",
                 "tx_error_count_location", "rx_error_count_location", "bus_off_count_location",
                 "emcy_code_location", "error_register_location", "nmt_command_location", "trigger_location",
                 "abort_code_location", "comm_ok_location", "sync_count_location")


class Use:
    def __init__(self, file, path, loc, count):
        self.file = file
        self.path = path
        self.loc = loc
        self.first = loc.element
        self.last = loc.element + count - 1

    def describe(self):
        return "%s %s (%s)" % (self.file, self.path, self.span(self.first, self.last))

    def span(self, first, last):
        a = element_str(self.loc.area, self.loc.size, first)
        return a if first == last else "%s..%s" % (a, element_str(self.loc.area, self.loc.size, last))


def _path(parts):
    out = ""
    for p in parts:
        out += "[%d]" % p if isinstance(p, int) else ("." if out else "") + str(p)
    return out


def collect(value, file, parts, out):
    if isinstance(value, dict):
        for key, child in value.items():
            if key in LOCATION_KEYS and isinstance(child, str):
                loc = parse_location(child)
                if loc is None:
                    continue
                count = value.get("len") if key == "iec_location" else None
                if not isinstance(count, int) or isinstance(count, bool) or count < 1:
                    count = 1
                out.append(Use(file, _path(parts + [key]), loc, count))
            else:
                collect(child, file, parts + [key], out)
    elif isinstance(value, list):
        for i, child in enumerate(value):
            collect(child, file, parts + [i], out)


def bundle_uses(bundle_dir):
    """Locations of every conf/*.json in the bundle (the files the runtime
    hands to plugins). Returns (uses, problems)."""
    uses, problems = [], []
    for path in sorted(glob.glob(os.path.join(bundle_dir, "conf", "*.json"))):
        rel = "conf/" + os.path.basename(path)
        try:
            with open(path, encoding="utf-8") as f:
                text = f.read()
            if not text.strip():
                continue  # the editor writes an empty ethercat.json into every build
            doc = json.loads(text)
        except (OSError, ValueError) as e:
            problems.append("%s: not readable JSON (%s); its locations are not checked" % (rel, e))
            continue
        collect(doc, rel, [], uses)
    return uses, problems


def check(uses, allow_clash=False):
    """Returns (errors, warnings)."""
    errors, warnings = [], []
    by_table = {}
    for u in uses:
        by_table.setdefault((u.loc.area, u.loc.size), []).append(u)
    for (area, _), group in sorted(by_table.items()):
        group.sort(key=lambda u: (u.first, u.file, u.path))
        for i, a in enumerate(group):
            for b in group[i + 1:]:
                if b.first > a.last:
                    break
                same_file = a.file == b.file
                if same_file and a.file != "conf/canopen.json":
                    continue  # another plugin's own business
                lo, hi = max(a.first, b.first), min(a.last, b.last)
                span = a.span(lo, hi)
                if same_file:
                    errors.append("%s: %s and %s both map %s" % (a.file, a.path, b.path, span))
                elif area == "I":
                    msg = ("input clash: %s and %s both write %s; two plugins would overwrite each other's inputs"
                           % (a.describe(), b.describe(), span))
                    (warnings if allow_clash else errors).append(msg + (" (allowed by --allow-clash)" if allow_clash else ""))
                elif area == "Q":
                    warnings.append("%s and %s both read output %s" % (a.describe(), b.describe(), span))
                else:
                    warnings.append("%s and %s both use memory %s" % (a.describe(), b.describe(), span))
    return errors, warnings
