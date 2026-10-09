"""The configurator's CAN messages page on the server side (spec
canopen-configurator, "CAN messages page"): address suggestions, the DBC
import dialog and Copy as ST call. The page sends the whole draft config;
nothing here writes a file."""

from ..iec import parse_location
from ..raw import assist
from ..raw.contract import locations as raw_locations
from . import layout

KINDS = ("rx", "tx")


class RawPageError(ValueError):
    """A request the page should not have sent (bad network or message)."""


def raw_uses(cfg):
    """[(json path, Location)] of every raw message location in the config."""
    out = []
    if not isinstance(cfg, dict):
        return out
    nets = cfg.get("networks") if isinstance(cfg.get("networks"), list) else [cfg]
    for i, net in enumerate(nets):
        if not isinstance(net, dict) or not isinstance(net.get("raw"), dict):
            continue
        prefix = "networks[%d].raw" % i if net is not cfg else "raw"
        for text, path in raw_locations(net["raw"], prefix):
            loc = parse_location(text)
            if loc:
                out.append((path, loc))
    return out


def _used(cfg, project_uses):
    used = layout.taken(cfg, project_uses) if isinstance(cfg, dict) else set()
    used.update((l.area, l.size, l.element) for _, l in raw_uses(cfg))
    return used


def _raw(cfg, network):
    nets = cfg.get("networks") if isinstance(cfg, dict) and isinstance(cfg.get("networks"), list) else [cfg]
    try:
        net = nets[int(network or 0)]
    except (IndexError, TypeError, ValueError):
        raise RawPageError("no network %r" % network)
    if not isinstance(net, dict):
        raise RawPageError("no network %r" % network)
    return net.get("raw") if isinstance(net.get("raw"), dict) else {}


def _entry(cfg, network, kind, index):
    if kind not in KINDS:
        raise RawPageError("kind must be rx or tx")
    lst = _raw(cfg, network).get(kind) or []
    try:
        entry = lst[int(index)]
    except (IndexError, TypeError, ValueError):
        raise RawPageError("no %s message %r" % (kind, index))
    if not isinstance(entry, dict):
        raise RawPageError("no %s message %r" % (kind, index))
    return entry


def suggest(cfg, network, kind, index, project_uses, start=None):
    """The message with every missing location filled; {"entry", "filled"}."""
    entry = dict(_entry(cfg, network, kind, index))
    entry["signals"] = [dict(s) for s in entry.get("signals") or [] if isinstance(s, dict)]
    start = assist.DEFAULT_START if start in (None, "") else int(start)
    filled = assist.suggest_locations(entry, kind, _used(cfg, project_uses), start)
    return {"entry": entry, "filled": filled}


def dbc_messages(text):
    """The DBC file's messages for the import dialog."""
    from ..raw import dbc
    try:
        messages = dbc.read_dbc(text if "\n" in text else text + "\n")
    except ImportError:
        raise RawPageError("DBC import needs the cantools package (pip install cantools)")
    except Exception as e:  # cantools raises many kinds of parse errors
        raise RawPageError("not a DBC file: %s" % e)
    return {"messages": [{"name": m["name"], "id": m["id"], "extended": m["extended"], "dlc": m["dlc"],
                          "senders": m["senders"], "cycle_ms": m["cycle_ms"], "multiplexed": m["multiplexed"],
                          "signals": len(m["signals"])} for m in messages]}


def dbc_import(cfg, network, text, picks, project_uses, start=None):
    """New raw entries for the picked DBC messages, with suggested addresses;
    {"rx": [...], "tx": [...], "notes": [...]}. Messages whose identifier the
    network's raw object already has in that direction are left out and named
    in the notes."""
    from ..raw import dbc
    try:
        messages = dbc.read_dbc(text if "\n" in text else text + "\n")
    except ImportError:
        raise RawPageError("DBC import needs the cantools package (pip install cantools)")
    except Exception as e:
        raise RawPageError("not a DBC file: %s" % e)
    new, notes = assist.import_messages(messages, picks or {})
    raw = _raw(cfg, network)
    used = _used(cfg, project_uses)
    start = assist.DEFAULT_START if start in (None, "") else int(start)
    out = {"rx": [], "tx": [], "notes": notes}
    for kind in KINDS:
        have = {(e.get("id"), bool(e.get("extended"))) for e in raw.get(kind) or [] if isinstance(e, dict)}
        for e in new[kind]:
            if (e["id"], bool(e.get("extended"))) in have:
                out["notes"].append("%s: the network already has a %s message with this identifier" % (
                    e["name"], "receive" if kind == "rx" else "send"))
                continue
            assist.suggest_locations(e, kind, used, start)
            out[kind].append(e)
    return out


def st_call(cfg, network, kind, index):
    return {"text": assist.st_call(_entry(cfg, network, kind, index), kind, int(network or 0))}
