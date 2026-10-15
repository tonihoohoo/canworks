"""A node's identity read with the manual SDO read of a client (diag.Client
for a runtime, localbus.LocalBus for a CAN adapter on this PC), for the
configurator's Nodes table (canopen-configurator: Device identity of heard
nodes): 0x1018 sub-indices 1-4, 0x1000, 0x1008, 0x1009 and 0x100A, the
fields a scan gives plus the versions.

0x1018:1 goes first as the probe: a node that does not answer it (STOPPED,
gone) is not read further. Reads the device refuses are left out."""

from .diag import parse_hex

PROBE = (0x1018, 1, "vendor_id")
NUMBERS = ((0x1018, 2, "product_code"), (0x1018, 3, "revision_number"), (0x1018, 4, "serial_number"),
           (0x1000, 0, "device_type"))
STRINGS = ((0x1008, 0, "device_name"), (0x1009, 0, "hardware_version"), (0x100A, 0, "software_version"))
PROBE_MS = 300
READ_MS = 300
MAX_TEXT = 128  # characters of a name kept


def _data(res):
    return parse_hex(res.get("data") or "") if res.get("success") and res.get("data") else None


def text(data):
    """A VISIBLE_STRING as shown: up to the first NUL, Latin-1, control
    characters as spaces, trimmed, at most MAX_TEXT characters."""
    s = data.split(b"\0", 1)[0].decode("latin-1")
    s = "".join(c if 32 <= ord(c) != 127 else " " for c in s).strip()
    return s[:MAX_TEXT]


def read(client, node):
    """{node_id, answered, vendor_id?, product_code?, revision_number?,
    serial_number?, device_type?, device_name?, hardware_version?,
    software_version?}. answered is False when the probe got no answer
    (timeout or refusal); refusals of the channel raise DiagError."""
    out = {"node_id": node, "answered": False}
    index, sub, key = PROBE
    res = client.sdo_read(node, index, sub, PROBE_MS)
    data = _data(res)
    if data is None:
        # An abort is an answer: the device is there, it has no 0x1018:1.
        if res.get("abort_code") not in (None, 0x05040000):
            out["answered"] = True
        else:
            return out
    else:
        out["answered"] = True
        out[key] = int.from_bytes(data[:4].ljust(4, b"\0"), "little")
    for index, sub, key in NUMBERS:
        data = _data(client.sdo_read(node, index, sub, READ_MS))
        if data:
            out[key] = int.from_bytes(data[:4].ljust(4, b"\0"), "little")
    for index, sub, key in STRINGS:
        data = _data(client.sdo_read(node, index, sub, READ_MS))
        if data:
            t = text(data)
            if t:
                out[key] = t
    return out
