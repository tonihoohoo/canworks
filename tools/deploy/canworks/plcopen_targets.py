"""`canworks-deploy --export-plcopen OUT --for generic`: the program side
of a PLC link config for a Modbus PLC other than OpenPLC, as one PLCopen XML
file plus the register map (plcopen-export spec). The Other PLC connection
downloads the same folder as a zip (modbus-connections).

The boundary is change 3's channel arrays: input register k is in
`canworks.in_w[k]`, holding register k is taken from `canworks.out_w[k]`.
canworks_in and canworks_out are the same copy code `--export-modbus-map
OUT.st` writes; the PLC's Modbus client channels move registers in and out
of the arrays. canworks.xml is in standard TC6 form, the register map comes
as CSV.

CODESYS is not a Modbus client of the bridge: a CODESYS PLC runs the CANopen
master itself (the CODESYS target, --export-codesys).
"""

import ipaddress
import os

from . import __version__, bridgecheck, modbusmap, openplcmodbus, plclibrary, plcopen

TARGETS = ("generic",)
CODESYS_REFUSED = ("CODESYS is not a Modbus client of canworks-bridge: CODESYS runs the CANopen master itself as the "
                   "CODESYS target (canworks-deploy --codesys-import)")
XML_NAME = "canworks.xml"
README_NAME = "README.txt"
GENERIC_CSV = "canworks-modbus-map.csv"
LIBRARY_XML_NAME = "canworks-library.xml"
TASK = "canworks_task"
MAIN = "main"
_WILDCARD = ("", "0.0.0.0", "::", "[::]", "*")
_LOOPBACK = ("localhost", "::1", "[::1]")


class ExportError(ValueError):
    pass


def library_pous():
    """[Pou] of the canworks library, in source file order."""
    out = []
    for s in sorted(plclibrary.archive()["sources"], key=lambda s: s["fileName"]):
        out += plcopen.parse_st(s["source"])
    return out


def listen_host(cfg):
    listen = bridgecheck.link_settings(cfg)["listen"]
    host = listen.rsplit(":", 1)[0] if ":" in listen else ""
    return host


def is_loopback(host):
    return host.lower() in _LOOPBACK or host.startswith("127.")


def writer_covers(cfg, address):
    """Whether `writers` lets `address` write (an address or prefix of the
    list holds it); None when `address` is not an IP address."""
    try:
        ip = ipaddress.ip_address(address.strip().strip("[]"))
    except ValueError:
        return None
    for w in (cfg.get("bridge") or {}).get("writers") or []:
        try:
            if ip in ipaddress.ip_network(w, strict=False):
                return True
        except (TypeError, ValueError):
            continue
    return False


def default_host(cfg, target):
    """The bridge address the PLC uses when none is given: `listen`'s host
    unless that is a wildcard."""
    host = listen_host(cfg)
    if host in _WILDCARD:
        return None
    return host.strip("[]")


def task_interval_ms(cfg):
    """The cycle of the canworks task and the client channels: a fifth of
    the bridge's watchdog, at least 10 ms, in steps of 5 ms."""
    wd = bridgecheck.link_settings(cfg)["watchdog_ms"] or 1000
    return max(10, int(wd // 5) // 5 * 5)


def check(cfg, target):
    """Problems that stop an export, as texts."""
    if target == "codesys":
        return [CODESYS_REFUSED]
    if target not in TARGETS:
        return ["unknown PLC %r (generic)" % target]
    if not modbusmap.is_bridge_config(cfg):
        return ["not a Modbus bridge config: it has no \"bridge\" object"]
    if not modbusmap.has_plc_link(cfg):
        return ["the bridge has no PLC link: turn it on (\"plc_link\": true) and run Pack for Modbus"]
    return []


def global_list(cfg, decls):
    """The `canworks` list: change 1's typed values, `ok`, `link`, and the
    channel arrays."""
    lst = openplcmodbus.global_list(decls)
    n = openplcmodbus.channel_sizes(cfg)
    variables = []
    for v in lst["variables"]:
        variables.append(plcopen.Var(v["name"], v["type"]["value"], doc=v["documentation"]))
        if v["name"] == "link":
            variables.append(plcopen.Var("in_w", "ARRAY[0..%d] OF WORD" % (n["I"] - 1),
                                         doc="input registers 0..%d, read with function 4" % (n["I"] - 1)))
            variables.append(plcopen.Var("out_w", "ARRAY[0..%d] OF WORD" % (n["Q"] - 1),
                                         doc="holding registers 0..%d, written with function 16" % (n["Q"] - 1)))
    return plcopen.GlobalList(openplcmodbus.LIST_NAME, variables, doc=lst["documentation"].replace(
        "Save rewrites it", "export again after a config change"))


def _programs(cfg, decls, target, on_loss=None):
    in_st, out_st = openplcmodbus.programs(cfg, decls, other=True,
                                           on_loss=on_loss or openplcmodbus.inputs_on_loss(cfg, ("plc",)))
    pin, = plcopen.parse_st(in_st)
    pout, = plcopen.parse_st(out_st)
    for pou in (pin, pout):
        pou.sections.insert(0, _external())
    return [pin, pout]


def _external():
    """VAR_EXTERNAL canworks: IEC 61131-3 wants it in every program that
    uses the resource global (plcopen-export "Standard globals in the
    generic dialect")."""
    return plcopen.Section("VAR_EXTERNAL", variables=[plcopen.Var(openplcmodbus.LIST_NAME, plcopen.struct_name(
        plcopen.GlobalList(openplcmodbus.LIST_NAME, [])))])


def _main_stub():
    return plcopen.Pou("program", MAIN, sections=[_external()], body="(* Your program: canworks_in runs before it and canworks_out after it "
                                             "in canworks_task. Use canworks.ok and canworks.<value>, and give "
                                             "the canworks blocks LINK := canworks.link. *)\n")


def xml_text(cfg, decls, target, library=True, with_main=False, created=None, on_loss=None):
    """The PLCopen XML text for `target`."""
    problems = check(cfg, target)
    if problems:
        raise ExportError("; ".join(problems))
    dialect = target
    pous = library_pous() if library else []
    pous += _programs(cfg, decls, target, on_loss)
    programs = [openplcmodbus.IN_PROGRAM, openplcmodbus.OUT_PROGRAM]
    if with_main:
        pous.append(_main_stub())
        programs.insert(1, MAIN)
    tasks = [plcopen.Task(TASK, task_interval_ms(cfg), programs)]
    s = openplcmodbus.settings(cfg)
    doc = ("canworks PLC link for canworks-bridge: Modbus TCP port %d, unit %d, word order %s, map hash 16#%08X. "
           "Generated by canworks-deploy %s; export again after a config change."
           % (s["port"], s["unit_id"], modbusmap.word_order_of(cfg), modbusmap.map_hash(cfg), __version__))
    return plcopen.writer(pous, [global_list(cfg, decls)], dialect, tasks, name="canworks",
                          product_version=__version__, created=created or "1970-01-01T00:00:00", doc=doc)


def library_xml(created=None):
    """`canworks-deploy library --format plcopen`: every library POU, with
    CODESYS's plain-text declarations next to the standard interfaces."""
    return plcopen.writer(library_pous(), [], "codesys", name="canworks_library", product_version=__version__,
                          created=created or "1970-01-01T00:00:00", doc="canworks library %s" % __version__)


def write_library(out_dir):
    """Writes canworks-library.xml into out_dir; returns its path."""
    out_dir = os.path.abspath(os.path.expanduser(out_dir))
    if not os.path.isdir(out_dir):
        raise plclibrary.LibraryError("%s is not a folder" % out_dir)
    return write(out_dir, {LIBRARY_XML_NAME: library_xml()})[0]


def channels(cfg):
    """[{function, start, count, variable}] of the client channels: as few
    requests as the Modbus limits allow (modbusmap.suggest_channels)."""
    out = []
    for f, start, count, d in modbusmap.suggest_channels(modbusmap.register_map(cfg)):
        out.append({"function": f, "start": start, "count": count,
                    "variable": "%s.%s" % (openplcmodbus.LIST_NAME, "in_w" if d == "input" else "out_w")})
    return out


def _readme(target, cfg, host, interval, with_main):
    s = openplcmodbus.settings(cfg)
    writers = (cfg.get("bridge") or {}).get("writers") or []
    lines = ["canworks for a PLC that imports PLCopen XML (canworks-deploy %s)" % __version__,
             "",
             "%s holds the canworks list (canworks.ok, the typed values, canworks.link and the channel arrays "
             "canworks.in_w and canworks.out_w), the programs canworks_in and canworks_out and the canworks "
             "library. The bridge listens on port %d, unit %d; the PLC reaches it at %s."
             % (XML_NAME, s["port"], s["unit_id"], host or "<the bridge's address>"),
             ""]
    if writers:
        lines += ["The bridge takes writes only from %s: the PLC's address must be one of them." % ", ".join(writers),
                  ""]
    lines += ["1. Import %s into the PLC project (PLCopen XML import)." % XML_NAME,
              "2. Set up the PLC's Modbus TCP client with the channels below, at a cycle of %d ms or less."
              % interval,
              "3. Run canworks_in first and canworks_out last in the task that uses the values (the file's "
              "canworks_task does that). Your program goes between them.",
              "",
              "Channels (%s has every register):" % GENERIC_CSV]
    for ch in channels(cfg):
        lines.append("  function %-2d registers %d..%d -> %s[%d..%d]"
                     % (ch["function"], ch["start"], ch["start"] + ch["count"] - 1, ch["variable"], ch["start"],
                        ch["start"] + ch["count"] - 1))
    lines += ["", "Export again after any config change: a program built for another map leaves the bridge's "
                  "outputs off (canworks.ok stays FALSE).", ""]
    return "\n".join(lines)


def files(cfg, decls, target, host=None, library=True, with_main=False, created=None, on_loss=None):
    """{file name: text} of the export folder."""
    if target not in TARGETS:
        raise ExportError("; ".join(check(cfg, target)))
    if host is None:
        host = default_host(cfg, target)
    out = {XML_NAME: xml_text(cfg, decls, target, library, with_main, created, on_loss)}
    interval = task_interval_ms(cfg)
    out[README_NAME] = _readme(target, cfg, host, interval, with_main)
    out[GENERIC_CSV] = modbusmap.to_csv(modbusmap.register_map(cfg))
    return out


def write(out_dir, texts):
    """Writes {file name: text} into out_dir (made when missing); returns
    the paths."""
    os.makedirs(out_dir, exist_ok=True)
    paths = []
    for name in sorted(texts):
        path = os.path.join(out_dir, name)
        with open(path, "w", encoding="utf-8", newline="\n") as f:
            f.write(texts[name])
        paths.append(path)
    return paths

