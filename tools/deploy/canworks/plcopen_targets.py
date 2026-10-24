"""`canworks-deploy --export-plcopen OUT --for trust|generic`: the program
side of a PLC link config for a Modbus PLC other than OpenPLC, as one
PLCopen XML file plus the per-PLC transport (plcopen-export spec). The
truST and Other PLC connections download the same folder as a zip
(modbus-connections).

The boundary is change 3's channel arrays: input register k is in
`canworks.in_w[k]`, holding register k is taken from `canworks.out_w[k]`.
canworks_in and canworks_out are the same copy code `--export-modbus-map
OUT.st` writes; each target only moves registers in and out of the arrays:

    trust     canworks.xml with byte arrays at %IB0/%QB0 that canworks_in
              and canworks_out copy, and io.toml.part: truST's modbus-tcp
              driver reads the input registers into %IB0.. and writes %QB0..
              into the holding registers, one request each way
    generic   canworks.xml in standard TC6 form and the register map as CSV

CODESYS is not a Modbus client of the bridge: a CODESYS PLC runs the CANopen
master itself (the CODESYS target, --export-codesys).
"""

import copy
import ipaddress
import os

from . import __version__, bridgecheck, modbusmap, openplcmodbus, plclibrary, plcopen

TARGETS = ("trust", "generic")
CODESYS_REFUSED = ("CODESYS is not a Modbus client of canworks-bridge: CODESYS runs the CANopen master itself as the "
                   "CODESYS target (canworks-deploy --codesys-import)")
XML_NAME = "canworks.xml"
README_NAME = "README.txt"
TRUST_IO = "io.toml.part"
TRUST_IO_ST = "canworks_io.st"
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
    unless that is a wildcard; truST on the bridge's own device may use
    loopback."""
    host = listen_host(cfg)
    if host in _WILDCARD:
        return "127.0.0.1" if target == "trust" else None
    return host.strip("[]")


def task_interval_ms(cfg):
    """The cycle of the canworks task and the client channels: a fifth of
    the bridge's watchdog, at least 10 ms, in steps of 5 ms."""
    wd = bridgecheck.link_settings(cfg)["watchdog_ms"] or 1000
    return max(10, int(wd // 5) // 5 * 5)


# The shortest bridge watchdog a truST export takes: a truST scan with the
# copy programs and the library takes about 100-125 ms on a Pi 5.
TRUST_MIN_WATCHDOG_MS = 500


def check(cfg, target):
    """Problems that stop an export, as texts."""
    if target == "codesys":
        return [CODESYS_REFUSED]
    if target not in TARGETS:
        return ["unknown PLC %r (trust or generic)" % target]
    if not modbusmap.is_bridge_config(cfg):
        return ["not a Modbus bridge config: it has no \"bridge\" object"]
    if not modbusmap.has_plc_link(cfg):
        return ["the bridge has no PLC link: turn it on (\"plc_link\": true) and run Pack for Modbus"]
    out = []
    if target == "trust":
        n = openplcmodbus.channel_sizes(cfg)
        if not _fits(n):
            hint = "locate fewer values, then run Pack for Modbus"
            if (cfg.get("bridge") or {}).get("mailboxes") is not None:
                # Offer the trim only when the trimmed, packed map fits
                # (plcopen-export "truST trim offered only when it fits").
                trimmed = _trimmed_sizes(cfg)
                if trimmed is None or _fits(trimmed):
                    hint = ("trim the mailboxes to \"requests\": 1, \"receive\": false, \"network_info\": false, "
                            "\"cyclic_jobs\": 0 (the SDO, NMT and CAN_SEND blocks still work; CAN_RECEIVE, "
                            "J1939_RECEIVE and CO_RECV_EMCY need the receive mailbox) or leave them out, then run "
                            "Pack for Modbus")
                else:
                    over = [("%d input registers, more than %d" % (trimmed["I"], modbusmap.MAX_READ_REGISTERS))
                            if trimmed["I"] > modbusmap.MAX_READ_REGISTERS else None,
                            ("%d holding registers, more than %d" % (trimmed["Q"], modbusmap.MAX_WRITE_REGISTERS))
                            if trimmed["Q"] > modbusmap.MAX_WRITE_REGISTERS else None]
                    hint = ("with a request mailbox this map needs %s: leave the mailboxes out (canworks blocks "
                            "None on the connection) or locate fewer values, then run Pack for Modbus"
                            % " and ".join(o for o in over if o))
            out.append("truST's Modbus driver moves one request each way (at most %d input and %d holding "
                       "registers); this map uses %d and %d: %s"
                       % (modbusmap.MAX_READ_REGISTERS, modbusmap.MAX_WRITE_REGISTERS, n["I"], n["Q"], hint))
        wd = bridgecheck.link_settings(cfg)["watchdog_ms"]
        if 0 < wd < TRUST_MIN_WATCHDOG_MS:
            out.append("a truST scan with the library takes about 100-125 ms, so the bridge's watchdog of %d ms "
                       "would switch the outputs off and on every scan: set \"watchdog_ms\": %d or more in "
                       "\"bridge\"" % (wd, TRUST_MIN_WATCHDOG_MS))
    return out


def _fits(n):
    return n["I"] <= modbusmap.MAX_READ_REGISTERS and n["Q"] <= modbusmap.MAX_WRITE_REGISTERS


def _trimmed_sizes(cfg):
    """channel_sizes() of `cfg` with the mailboxes trimmed to one request
    mailbox and packed, as Problems' "Trim the mailboxes for truST" does;
    None when that map cannot be laid out."""
    trimmed = copy.deepcopy(cfg)
    mb = dict(trimmed["bridge"].get("mailboxes") or {})
    mb.update({"requests": 1, "receive": False, "network_info": False, "cyclic_jobs": 0})
    mb.pop("receive_blocks", None)
    trimmed["bridge"]["mailboxes"] = mb
    try:
        return openplcmodbus.channel_sizes(modbusmap.pack(trimmed))
    except (modbusmap.MapError, openplcmodbus.OpenplcError, KeyError, TypeError, ValueError, AttributeError):
        return None


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
    kinds = ("trust",) if target == "trust" else ("plc",)
    in_st, out_st = openplcmodbus.programs(cfg, decls, other=True,
                                           on_loss=on_loss or openplcmodbus.inputs_on_loss(cfg, kinds))
    pin, = plcopen.parse_st(in_st)
    pout, = plcopen.parse_st(out_st)
    for pou in (pin, pout):
        pou.sections.insert(0, _external())
    if target == "trust":
        n = openplcmodbus.channel_sizes(cfg)
        pin.sections.insert(0, plcopen.Section("VAR", variables=[plcopen.Var("k", "INT")]))
        pin.body = ("FOR k := 0 TO %d DO\n  canworks.in_w[k] := SHL(BYTE_TO_WORD(cw_in[2 * k]), 8) OR "
                    "BYTE_TO_WORD(cw_in[2 * k + 1]);\nEND_FOR;\n" % (n["I"] - 1)) + pin.body
        pout.sections.insert(0, plcopen.Section("VAR", variables=[plcopen.Var("k", "INT")]))
        pout.body += ("FOR k := 0 TO %d DO\n  cw_out[2 * k] := WORD_TO_BYTE(SHR(canworks.out_w[k], 8));\n"
                      "  cw_out[2 * k + 1] := WORD_TO_BYTE(canworks.out_w[k]);\nEND_FOR;\n" % (n["Q"] - 1))
    return [pin, pout]


def trust_io_st(cfg):
    """canworks_io.st, truST's process image as byte arrays: its modbus-tcp
    driver reads the input registers into %IB0.. and writes %QB0.. into the
    holding registers, high byte first. A file of its own: truST 0.24's
    PLCopen import drops every AT address."""
    n = openplcmodbus.channel_sizes(cfg)
    return ("(* canworks: truST's I/O image for canworks-bridge; copy into the project's src folder. *)\n"
            "VAR_GLOBAL\n"
            "    cw_in AT %%IB0 : ARRAY[0..%d] OF BYTE; (* input registers 0..%d *)\n"
            "    cw_out AT %%QB0 : ARRAY[0..%d] OF BYTE; (* holding registers 0..%d *)\n"
            "END_VAR\n" % (2 * n["I"] - 1, n["I"] - 1, 2 * n["Q"] - 1, n["Q"] - 1))


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


def trust_io(cfg, host):
    s = openplcmodbus.settings(cfg)
    n = openplcmodbus.channel_sizes(cfg)
    return "\n".join([
        "# truST io.toml for canworks-bridge (canworks-deploy --export-plcopen --for trust).",
        "# Replace the [io] tables of the project's io.toml with these. The driver reads input",
        "# registers 0..%d into %%IB0.. and writes %%QB0.. into holding registers 0..%d every cycle;"
        % (n["I"] - 1, n["Q"] - 1),
        "# canworks_in and canworks_out copy them to and from canworks.in_w and canworks.out_w.",
        "[io]",
        'driver = "modbus-tcp"',
        "",
        "[io.params]",
        'address = "%s:%d"' % (host if ":" not in host else "[%s]" % host, s["port"]),
        "unit_id = %d" % s["unit_id"],
        "input_start = 0",
        "output_start = 0",
        "timeout_ms = %d" % max(100, min(1000, s["watchdog_ms"] // 2)),
        "# canworks.ok goes FALSE when the bridge stops answering; keep the PLC running.",
        'on_error = "warn"',
        ""])


def _readme(target, cfg, host, interval, with_main):
    s = openplcmodbus.settings(cfg)
    writers = (cfg.get("bridge") or {}).get("writers") or []
    lines = ["canworks for %s (canworks-deploy %s)" % ({"trust": "truST", "generic": "a PLC that imports PLCopen XML"}[target],
                                                      __version__),
             "",
             "%s holds the canworks list (canworks.ok, the typed values, canworks.link and the channel arrays "
             "canworks.in_w and canworks.out_w), the programs canworks_in and canworks_out and the canworks "
             "library. The bridge listens on port %d, unit %d; the PLC reaches it at %s."
             % (XML_NAME, s["port"], s["unit_id"], host or "<the bridge's address>"),
             ""]
    if writers:
        lines += ["The bridge takes writes only from %s: the PLC's address must be one of them." % ", ".join(writers),
                  ""]
    if target == "trust":
        lines += ["1. Import the file into the truST project:",
                  "     trust-runtime plcopen import --input %s --project <project folder>" % XML_NAME,
                  "   (or in VS Code: truST: Import PLCopen XML).",
                  "2. Copy %s into the project's src folder (truST's import drops AT addresses, so the "
                  "I/O image comes as its own file)." % TRUST_IO_ST,
                  "3. Replace the [io] tables of the project's io.toml with %s, and set the [resource] name in "
                  "runtime.toml to canworks_res (the imported configuration's resource)." % TRUST_IO,
                  "4. %s" % ("Write your program into main (it runs between canworks_in and canworks_out)."
                             if with_main else
                             "Add your program to canworks_task between canworks_in and canworks_out in the "
                             "imported configuration."),
                  "5. trust-runtime build --project <project folder>, then run it.",
                  "",
                  "The task runs every %d ms. The project's %%I and %%Q image belongs to the bridge: don't locate "
                  "other variables there." % interval]
    else:
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
    if not host and target != "generic":
        raise ExportError("give the bridge's address as the PLC sees it (the bridge listens on %r)"
                          % (bridgecheck.link_settings(cfg)["listen"] or "the default address"))
    out = {XML_NAME: xml_text(cfg, decls, target, library, with_main, created, on_loss)}
    interval = task_interval_ms(cfg)
    out[README_NAME] = _readme(target, cfg, host, interval, with_main)
    if target == "trust":
        out[TRUST_IO] = trust_io(cfg, host)
        out[TRUST_IO_ST] = trust_io_st(cfg)
    else:
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

