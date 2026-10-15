"""The Trace tab's transmit list and view settings on this PC
(canopen-configurator: "Transmit list", "Transmit list storage and files",
"Docked inspector and transmit pane").

trace.json in the settings folder keeps, per project folder and network, the
transmit list's rows, and the trace view's settings (view, inspector split,
sort, transmit pane). It is not in the project folder or the config: sending
is a test activity, and the config is uploaded to the runtime.

A list file (Save list… / Open list…) is JSON:
{"format": "canworks-transmit", "version": 1, "network": "io", "frames": [row...]}.
"""

import json
import os
import threading

FORMAT = "canworks-transmit"
VERSION = 1
STORE = "trace.json"
MAX_ROWS = 256
NO_NETWORK = ""  # the key of a config with one network, or no config

VIEWS = ("ids", "frames", "graph", "sequences", "trigger")
SORT_KEYS = ("id", "dir", "name", "dlc", "count", "cycle_last", "cycle_avg", "cycle_min", "cycle_max", "last_seen")

_lock = threading.Lock()


class Invalid(ValueError):
    pass


def _hex_id(v):
    if isinstance(v, bool):
        raise Invalid("the identifier must be hex, e.g. 205 or 0x205")
    if isinstance(v, int):
        return v
    t = str(v or "").strip()
    t = t[2:] if t[:2].lower() == "0x" else t
    if not t or any(c not in "0123456789abcdefABCDEF" for c in t):
        raise Invalid("the identifier must be hex, e.g. 205 or 0x205")
    return int(t, 16)


def data_bytes(text):
    """'0F 01' or '0f01' -> bytes; raises Invalid with the page's wording."""
    t = "".join(str(text or "").split())
    if len(t) % 2:
        raise Invalid("the data needs whole bytes (two hex digits each)")
    try:
        b = bytes.fromhex(t)
    except ValueError:
        raise Invalid("the data must be hex bytes, e.g. 0F 01")
    if len(b) > 8:
        raise Invalid("at most 8 data bytes")
    return b


def check_row(row):
    """A transmit row as stored: name, id (hex text), ext, rtr, dlc, data
    (spaced hex), period_ms (None for one frame), count (None: no limit)."""
    if not isinstance(row, dict):
        raise Invalid("a row must be an object")
    ext, rtr = bool(row.get("ext")), bool(row.get("rtr"))
    can_id = _hex_id(row.get("id"))
    if can_id > (0x1FFFFFFF if ext else 0x7FF):
        raise Invalid("identifier %X is out of range for a %s identifier%s"
                      % (can_id, "29-bit" if ext else "11-bit", "" if ext else " (tick Extended for a 29-bit one)"))
    data = b"" if rtr else data_bytes(row.get("data"))
    dlc = row.get("dlc")
    if rtr:
        try:
            dlc = int(dlc or 0)
        except (TypeError, ValueError):
            raise Invalid("DLC must be 0-8")
        if not 0 <= dlc <= 8:
            raise Invalid("DLC must be 0-8")
    else:
        dlc = len(data)
    period = row.get("period_ms")
    if period in (None, ""):
        period = None
    else:
        try:
            period = int(period)
        except (TypeError, ValueError):
            raise Invalid("the period must be a number of milliseconds")
        if not 10 <= period <= 60000:
            raise Invalid("the period must be 10 to 60000 ms")
    count = row.get("count")
    if count in (None, ""):
        count = None
    else:
        try:
            count = int(count)
        except (TypeError, ValueError):
            raise Invalid("the count must be a number")
        if count < 1:
            raise Invalid("the count must be at least 1")
    name = str(row.get("name") or "").strip()[:80]
    return {"name": name, "id": ("%08X" if ext else "%03X") % can_id, "ext": ext, "rtr": rtr, "dlc": dlc,
            "data": " ".join("%02X" % b for b in data), "period_ms": period, "count": count}


def check_rows(rows):
    if not isinstance(rows, list):
        raise Invalid("frames must be a list")
    if len(rows) > MAX_ROWS:
        raise Invalid("at most %d frames in a transmit list" % MAX_ROWS)
    out = []
    for k, r in enumerate(rows):
        try:
            out.append(check_row(r))
        except Invalid as e:
            raise Invalid("frame %d: %s" % (k + 1, e))
    return out


class Store:
    """trace.json in `folder` (the configurator's settings folder)."""

    def __init__(self, folder):
        self.path = os.path.join(folder, STORE)

    def _load(self):
        try:
            with open(self.path, encoding="utf-8") as f:
                d = json.load(f)
            return d if isinstance(d, dict) else {}
        except (OSError, ValueError):
            return {}

    def _save(self, d):
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        tmp = self.path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(d, f, indent=1)
        os.replace(tmp, self.path)

    # -- the transmit list ----------------------------------------------------
    def rows(self, folder, network):
        with _lock:
            d = self._load()
        lists = d.get("lists") if isinstance(d.get("lists"), dict) else {}
        per = lists.get(os.path.abspath(folder)) if isinstance(lists.get(os.path.abspath(folder)), dict) else {}
        try:
            return check_rows(per.get(network or NO_NETWORK) or [])
        except Invalid:
            return []

    def set_rows(self, folder, network, rows):
        rows = check_rows(rows)
        with _lock:
            d = self._load()
            lists = d.setdefault("lists", {})
            if not isinstance(lists, dict):
                lists = d["lists"] = {}
            per = lists.setdefault(os.path.abspath(folder), {})
            if not isinstance(per, dict):
                per = lists[os.path.abspath(folder)] = {}
            per[network or NO_NETWORK] = rows
            self._save(d)
        return rows

    # -- view settings --------------------------------------------------------
    def prefs(self):
        with _lock:
            d = self._load()
        p = d.get("prefs") if isinstance(d.get("prefs"), dict) else {}
        return check_prefs(p, lenient=True)

    def set_prefs(self, changes):
        with _lock:
            d = self._load()
            p = d.get("prefs") if isinstance(d.get("prefs"), dict) else {}
            p = check_prefs(p, lenient=True)
            p.update(check_prefs(changes))
            d["prefs"] = p
            self._save(d)
        return p


DEFAULT_PREFS = {"view": "ids", "split": 42, "inspector": True, "sort": "id", "sort_desc": False,
                 "pane": 220, "pane_open": True, "fx_fold": []}
# The inspector layers that can be folded (frame-lab-usability).
FX_LAYERS = ("id", "data", "wire")


def check_prefs(p, lenient=False):
    """The view settings; lenient keeps the defaults for bad stored values."""
    if not isinstance(p, dict):
        raise Invalid("settings must be an object")
    out = dict(DEFAULT_PREFS) if lenient else {}
    rules = {"view": lambda v: v in VIEWS, "split": lambda v: isinstance(v, (int, float)) and 15 <= v <= 85,
             "inspector": lambda v: isinstance(v, bool), "sort": lambda v: v in SORT_KEYS,
             "sort_desc": lambda v: isinstance(v, bool),
             "pane": lambda v: isinstance(v, (int, float)) and 80 <= v <= 2000,
             "pane_open": lambda v: isinstance(v, bool),
             "fx_fold": lambda v: isinstance(v, list) and len(set(v)) == len(v) and all(x in FX_LAYERS for x in v)}
    for k, v in p.items():
        if k not in rules:
            if lenient:
                continue
            raise Invalid("unknown setting %r" % k)
        if not rules[k](v):
            if lenient:
                continue
            raise Invalid("%s: %r is not allowed" % (k, v))
        out[k] = v
    return out


# -- list files ----------------------------------------------------------------
def dump_file(network, rows):
    return json.dumps({"format": FORMAT, "version": VERSION, "network": network or None,
                       "frames": check_rows(rows)}, indent=1) + "\n"


def load_file(text):
    """(network, rows) from a list file's text."""
    try:
        d = json.loads(text)
    except ValueError as e:
        raise Invalid("not a transmit list file: %s" % e)
    if not isinstance(d, dict) or d.get("format") != FORMAT:
        raise Invalid("not a transmit list file (format must be %s)" % FORMAT)
    if d.get("version") != VERSION:
        raise Invalid("transmit list version %r is not supported (this version reads %d)" % (d.get("version"), VERSION))
    net = d.get("network")
    return (net if isinstance(net, str) and net else None), check_rows(d.get("frames") or [])
