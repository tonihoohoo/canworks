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


# -- words inside the blocks ----------------------------------------------------
# The register layout of plugin/src/bridge/mailboxes.h for clients that speak
# the mailboxes themselves (the Node-RED package, nodered-blocks). A test
# checks these against the header.

CHUNK = 128              # data bytes per request or response
BUFFER = 1785            # staging and result buffer
MAX_RECEIVERS = 32
OPS = {"stage": 1, "fetch": 2, "sdo_read": 3, "sdo_write": 4, "can_send": 5, "cyclic_set": 6,
       "cyclic_stop": 7, "rx_open": 8, "rx_close": 9, "rx_fetch": 10, "j1939_send": 11,
       "j1939_request": 12, "dm_read": 13, "dm_clear": 14, "find_ecu": 15}
STATES = {"idle": 0, "busy": 1, "done": 2, "error": 3}
RX_KINDS = {"can": 1, "j1939": 2, "emcy": 3}
RECORD_FLAGS = {"long": 0x01, "restart": 0x02, "overflow": 0x04}
RX_OPEN_FLAGS = {"can_extended": 0x01, "j1939_all_pgns": 0x01, "j1939_all_destinations": 0x02,
                 "j1939_filter_source": 0x04, "emcy_skip_old": 0x01}
CAN_FLAGS = {"extended": 0x01, "rtr": 0x02}
BATCH_TIME_WORD = 21     # the batch time (UTC microseconds, 4 words) in the receive header
# A record: word 0 receiver << 8 | kind << 4 | flags, 1 still queued, 2
# dropped, then the kind's words (RECORD_WORDS above): CAN and J1939 from
# word 3; EMCY its receive time (UTC microseconds) in 3-6, then the rest.
RECORD_BODY_WORD = {"can": 3, "j1939": 3, "emcy": 7}
EMCY_TIME_WORD = 3
INFO_WORDS = NET_INFO_BYTES // 2
JOB_WORDS = CYCLIC_JOB_BYTES // 2


def client_layout():
    """The constants above as one object (lib/layout.js of the Node-RED package)."""
    return {"chunk": CHUNK, "buffer": BUFFER, "maxReceivers": MAX_RECEIVERS, "mailboxWords": MAILBOX_BYTES // 2,
            "receiveWords": RECEIVE_BYTES // 2, "rxHeaderWords": RX_HEADER_WORDS, "ops": OPS, "states": STATES,
            "rxKinds": RX_KINDS, "recordFlags": RECORD_FLAGS, "rxOpenFlags": RX_OPEN_FLAGS, "canFlags": CAN_FLAGS,
            "recordWords": RECORD_WORDS, "batchTimeWord": BATCH_TIME_WORD, "emcyTimeWord": EMCY_TIME_WORD,
            "recordBodyWord": RECORD_BODY_WORD, "maxReceiveBlocks": MAX_RECEIVE_BLOCKS,
            "infoWords": INFO_WORDS, "jobWords": JOB_WORDS}
