"""The bridge's mailbox areas (modbus-bridge-mailboxes): what `bridge.mailboxes`
puts where. The same rules as BridgeConfig's mailbox fields and
Parser::bridge_uses in plugin/src/can/config.cpp; the register layout of each
block is in plugin/src/bridge/mailboxes.h.
"""

MAILBOX_BYTES = 144      # one request or one response block (72 registers)
RECEIVE_BYTES = 240      # one receive mailbox block (120 registers)
RECEIVE_ACK_BYTES = 6    # its acknowledgement
NET_INFO_BYTES = 36      # one network info block
CYCLIC_JOB_BYTES = 8     # one cyclic job in the table, after a 2-byte tick
MAX_REQUESTS = 4
MAX_RECEIVE_BLOCKS = 2
MAX_CYCLIC_JOBS = 16
MAX_INFO_NETWORKS = 8
KEYS = ("requests", "receive", "receive_blocks", "cyclic_jobs", "network_info", "input_location", "output_location")

# Defaults of a mailboxes object, and of a new OpenPLC config.
DEFAULTS = {"requests": 1, "receive": True, "receive_blocks": 1, "cyclic_jobs": 4, "network_info": True}


def settings(mailboxes, networks):
    """The effective counts of a `mailboxes` object: requests, receive,
    receive_blocks, cyclic_jobs, info_networks."""
    m = dict(DEFAULTS)
    m.update({k: v for k, v in (mailboxes or {}).items() if k in DEFAULTS})
    info = min(networks, MAX_INFO_NETWORKS) if m["network_info"] else 0
    return {"requests": m["requests"], "receive": bool(m["receive"]), "receive_blocks": m["receive_blocks"],
            "cyclic_jobs": m["cyclic_jobs"], "info_networks": info}


RX_HEADER_WORDS = 25
RECORD_WORDS = {"can": 10, "j1939": 12, "emcy": 12}


def records_per_batch(kind, receive_blocks):
    """How many records of one kind ("can", "j1939", "emcy") one receive
    batch carries with 1 or 2 receive blocks."""
    return (receive_blocks * RECEIVE_BYTES // 2 - RX_HEADER_WORDS) // RECORD_WORDS[kind]


def blocks(mailboxes, networks):
    """[(area, offset, nbytes, name, who)] of the mailbox blocks, offsets
    from the area's start, in the order the bridge lists them. `name` is the
    register map's, `who` the bridge's words in its messages."""
    s = settings(mailboxes, networks)
    out = []
    i = o = 0
    for m in range(s["requests"]):
        out.append(("I", i, MAILBOX_BYTES, "bridge.mailbox.%d.response" % m, "bridge mailbox %d response" % m))
        out.append(("Q", o, MAILBOX_BYTES, "bridge.mailbox.%d.request" % m, "bridge mailbox %d request" % m))
        i += MAILBOX_BYTES
        o += MAILBOX_BYTES
    if s["receive"]:
        for k in range(s["receive_blocks"]):
            out.append(("I", i, RECEIVE_BYTES, "bridge.mailbox.receive.%d" % k, "bridge receive mailbox block %d" % k))
            i += RECEIVE_BYTES
        out.append(("Q", o, RECEIVE_ACK_BYTES, "bridge.mailbox.receive_ack", "bridge receive acknowledgement"))
        o += RECEIVE_ACK_BYTES
    for n in range(s["info_networks"]):
        out.append(("I", i, NET_INFO_BYTES, "bridge.mailbox.network_info.%d" % n, "bridge network info %d" % n))
        i += NET_INFO_BYTES
    if s["cyclic_jobs"]:
        out.append(("I", i, 2 + s["cyclic_jobs"] * CYCLIC_JOB_BYTES, "bridge.mailbox.cyclic_jobs", "bridge cyclic job table"))
        out.append(("Q", o, 2 * s["cyclic_jobs"], "bridge.mailbox.keepalives", "bridge cyclic job keepalives"))
    return out


def area_bytes(mailboxes, networks):
    """(input bytes, output bytes) of the mailbox areas."""
    ins = sum(n for a, _, n, _, _ in blocks(mailboxes, networks) if a == "I")
    outs = sum(n for a, _, n, _, _ in blocks(mailboxes, networks) if a == "Q")
    return ins, outs
