"""Texts of the frame explanation (canopen-frame-explain; design D2).

Plain data only: what each CANopen message type is for, what every field
and flag means, and what the bits on the wire are. Written for people who
are new to CAN and CANopen; the CiA name of a thing is given once next to a
plain description. Abort codes and EMCY classes come from diag.py.
"""

# Function codes of the CiA 301 predefined connection set:
# (first id, last id, short name, kind, what it is, who sends it).
FUNCTIONS = (
    (0x000, 0x000, "NMT", "nmt", "network management command", "the NMT master (the PLC)"),
    (0x080, 0x080, "SYNC", "sync", "SYNC, the master's clock tick", "the SYNC producer (the PLC)"),
    (0x081, 0x0FF, "EMCY", "emcy", "emergency message", "the node"),
    (0x100, 0x100, "TIME", "time", "time stamp", "the TIME producer"),
    (0x181, 0x1FF, "TPDO1", "pdo", "process data the node transmits (set 1)", "the node"),
    (0x201, 0x27F, "RPDO1", "pdo", "process data the node receives (set 1)", "the PLC"),
    (0x281, 0x2FF, "TPDO2", "pdo", "process data the node transmits (set 2)", "the node"),
    (0x301, 0x37F, "RPDO2", "pdo", "process data the node receives (set 2)", "the PLC"),
    (0x381, 0x3FF, "TPDO3", "pdo", "process data the node transmits (set 3)", "the node"),
    (0x401, 0x47F, "RPDO3", "pdo", "process data the node receives (set 3)", "the PLC"),
    (0x481, 0x4FF, "TPDO4", "pdo", "process data the node transmits (set 4)", "the node"),
    (0x501, 0x57F, "RPDO4", "pdo", "process data the node receives (set 4)", "the PLC"),
    (0x581, 0x5FF, "SDO answer", "sdo", "service data answer from the node's SDO server", "the node"),
    (0x601, 0x67F, "SDO request", "sdo", "service data request to the node's SDO server", "the PLC (SDO client)"),
    (0x701, 0x77F, "Heartbeat", "heartbeat", "node state report (heartbeat, boot-up or node guarding)",
     "the node"),
    (0x7E4, 0x7E4, "LSS answer", "lss", "layer setting services answer", "the device being set up"),
    (0x7E5, 0x7E5, "LSS request", "lss", "layer setting services request", "the LSS master (the PLC)"),
)

ABOUT = {
    "nmt": ("NMT (network management) commands switch nodes between their states. Only the master sends them, on "
            "identifier 0, the highest priority on the bus. Nodes do not answer; their next heartbeat shows the "
            "new state."),
    "sync": ("SYNC is the master's clock tick. Nodes with synchronous PDOs sample their inputs and send them right "
             "after it, and apply the outputs they received before it. The frame usually has no data: its arrival "
             "is the message."),
    "time": "The TIME message gives every node the same clock: milliseconds after midnight and days since 1984-01-01.",
    "emcy": ("A node sends an emergency (EMCY) once when an error appears, and once more with code 0000 when all "
             "errors are gone. The plugin hands the latest one to the PLC program."),
    "heartbeat": ("Every node repeats its NMT state at its producer heartbeat time (object 1017h). If the "
                  "heartbeat stops, the master marks the node as lost. A boot-up message is a heartbeat with state "
                  "0: the master then configures the node over SDO and starts it."),
    "guarding": ("Node guarding is the older way to watch a node: the master sends a remote request and the node "
                 "answers with its state and a toggle bit that flips on every answer."),
    "sdo": ("SDO (service data) is a question-and-answer service to read and write a node's object dictionary. "
            "The master (SDO client) asks on 600h + node ID and the node (SDO server) answers on 580h + node ID. It "
            "is for settings and diagnostics, not for fast process data. Values of up to 4 bytes fit in one frame "
            "(expedited); longer ones go in segments of 7 bytes, or in blocks."),
    "pdo": ("A PDO (process data object) carries live values with no header at all: what each bit means comes from "
            "the PDO mapping (objects 1600h-17FFh for RPDOs, 1A00h-1BFFh for TPDOs), which the master writes at "
            "boot. That is why one frame carries many values at once. A TPDO is sent by the node, an RPDO is "
            "received by the node."),
    "lss": ("LSS (layer setting services, CiA 305) gives a device its node ID and bit rate over the bus, finding it "
            "by its identity (vendor, product, revision, serial number)."),
    "error": ("An error frame is the CAN controller's report of a bus problem. SocketCAN delivers it as a frame "
              "whose identifier says the error class and whose data gives the details. It is not a frame that "
              "was on the bus."),
    "other": "This identifier is not one of the CANopen predefined identifiers and not configured, so its data has "
             "no known meaning.",
    "ext": ("An extended (29-bit) identifier. CANopen uses 11-bit identifiers; extended frames on the same bus come "
            "from other protocols (for example J1939)."),
}

NMT_COMMANDS = {
    0x01: ("Start remote node", "go to OPERATIONAL: PDOs run"),
    0x02: ("Stop remote node", "go to STOPPED: only NMT and heartbeat"),
    0x80: ("Enter pre-operational", "go to PRE-OPERATIONAL: SDO works, PDOs stop"),
    0x81: ("Reset node", "restart the application, all objects back to their stored or default values"),
    0x82: ("Reset communication", "restart the communication objects (1000h-1FFFh) only"),
}

NMT_STATES = {
    0x00: ("Boot-up", "the node has just started"),
    0x04: ("STOPPED", "only NMT and heartbeat run"),
    0x05: ("OPERATIONAL", "everything runs, including PDOs"),
    0x7F: ("PRE-OPERATIONAL", "SDO, SYNC, EMCY and heartbeat run; PDOs do not"),
}

ERROR_REGISTER = (
    "generic error", "current", "voltage", "temperature", "communication error (overrun, error state)",
    "device profile specific", "reserved (always 0)", "manufacturer specific",
)

# SDO command specifiers: (name, plain text).
SDO_CLIENT = {
    0: ("download segment", "a segment of the value being written"),
    1: ("initiate download", "start writing an object"),
    2: ("initiate upload", "start reading an object"),
    3: ("upload segment request", "ask for the next segment of the value being read"),
    4: ("abort", "stop the transfer"),
    5: ("block upload", "a block read command"),
    6: ("block download", "a block write command"),
}
SDO_SERVER = {
    0: ("upload segment", "a segment of the value being read"),
    1: ("download segment response", "the segment was received"),
    2: ("initiate upload response", "the start of the read answer"),
    3: ("initiate download response", "the write was accepted"),
    4: ("abort", "the transfer failed"),
    5: ("block download response", "a block write answer"),
    6: ("block upload", "a block read answer or data"),
}

SDO_BITS = {
    "ccs": "Client command specifier (bits 7-5 of byte 0): what this request does.",
    "scs": "Server command specifier (bits 7-5 of byte 0): what this answer is.",
    "n_init": ("n (bits 3-2): with e=1 and s=1, how many of the 4 data bytes carry no data. 0 means all 4 carry "
               "data, 3 means only byte 4 does."),
    "e": "e (bit 1), expedited: 1 means the value is in this frame; 0 means it follows in segments.",
    "s": "s (bit 0), size indicated: 1 means the size is given, by n or by bytes 4-7.",
    "t": "t (bit 4), toggle bit: alternates 0, 1, 0, ... from segment to segment so a lost frame is noticed.",
    "n_seg": "n (bits 3-1): how many of the 7 data bytes of this segment carry no data.",
    "c": "c (bit 0), complete: 1 marks the last segment.",
    "x": "Not used, sent as 0.",
    "index": "Object dictionary index. Little-endian: byte 1 is the low byte, byte 2 the high byte.",
    "sub": "Subindex: the entry inside the object.",
    "size": "The total number of bytes the transfer will carry.",
    "abort": "Abort code (CiA 301): why the transfer stopped.",
    "seg_data": "Up to 7 bytes of the value, in order.",
    "cc": "cc (bit 2): 1 means the client can use a CRC over the block data.",
    "sc": "sc (bit 2): 1 means the server can use a CRC over the block data.",
    "sub_cmd": "Subcommand (bits 1-0 or bit 0) of the block transfer.",
    "blksize": "Number of segments per block (1-127).",
    "pst": "Protocol switch threshold: below this size the server may answer with a normal upload instead.",
    "ackseq": "Sequence number of the last segment received correctly in this block.",
    "crc": "CRC-16 over all data of the block transfer (0 when no CRC is used).",
    "n_block": "n (bits 4-2): how many bytes of the last segment carry no data.",
    "seqno": "Sequence number of this segment in its block (1-127).",
    "c_block": "c (bit 7): 1 marks the last segment of the whole transfer.",
}

LSS_COMMANDS = {
    0x04: "switch state global", 0x11: "configure node-ID", 0x13: "configure bit timing",
    0x15: "activate bit timing", 0x17: "store configuration", 0x40: "switch state selective, vendor-ID",
    0x41: "switch state selective, product code", 0x42: "switch state selective, revision number",
    0x43: "switch state selective, serial number", 0x44: "switch state selective, answer",
    0x46: "identify remote slave, vendor-ID", 0x47: "identify remote slave, product code",
    0x48: "identify remote slave, revision low", 0x49: "identify remote slave, revision high",
    0x4A: "identify remote slave, serial low", 0x4B: "identify remote slave, serial high",
    0x4C: "identify non-configured remote slave", 0x4F: "identify slave (answer)",
    0x50: "identify non-configured slave (answer)", 0x51: "fastscan", 0x5A: "inquire vendor-ID",
    0x5B: "inquire product code", 0x5C: "inquire revision number", 0x5D: "inquire serial number",
    0x5E: "inquire node-ID",
}
LSS_BIT_RATES = {0: "1000 kbit/s", 1: "800 kbit/s", 2: "500 kbit/s", 3: "250 kbit/s", 4: "125 kbit/s",
                 6: "50 kbit/s", 7: "20 kbit/s", 8: "10 kbit/s"}

# SocketCAN error frames (linux/can/error.h).
ERROR_CLASSES = (
    "TX timeout (by the network layer)", "lost arbitration", "controller problem", "protocol violation",
    "transceiver status", "no acknowledgement on transmission", "bus-off", "bus error (may flood)",
    "controller restarted", "error counters in bytes 6 and 7",
)
ERROR_CTRL = (
    "RX buffer overflow", "TX buffer overflow", "RX error warning (error counter over 96)",
    "TX error warning (error counter over 96)", "RX error passive (counter over 127)",
    "TX error passive (counter over 127)", "back to error active", "reserved",
)
ERROR_PROT_TYPE = (
    "single bit error", "frame format error", "bit stuffing error", "unable to send dominant bit",
    "unable to send recessive bit", "bus overload", "active error announcement", "error during transmission",
)
ERROR_PROT_LOCATION = {
    0x03: "start of frame", 0x02: "ID bits 28-21", 0x06: "ID bits 20-18", 0x04: "substitute RTR",
    0x05: "identifier extension", 0x07: "ID bits 17-13", 0x0F: "ID bits 12-5", 0x0E: "ID bits 4-0",
    0x0C: "RTR bit", 0x0D: "reserved bit 1", 0x09: "reserved bit 0", 0x0B: "data length code",
    0x0A: "data section", 0x08: "CRC sequence", 0x18: "CRC delimiter", 0x19: "ACK slot", 0x1B: "ACK delimiter",
    0x1A: "end of frame", 0x12: "intermission",
}
ERROR_TRANSCEIVER = {
    0x00: "unspecified", 0x04: "CAN-H no wire", 0x05: "CAN-H short to battery", 0x06: "CAN-H short to VCC",
    0x07: "CAN-H short to ground", 0x40: "CAN-L no wire", 0x50: "CAN-L short to battery",
    0x60: "CAN-L short to VCC", 0x70: "CAN-L short to ground", 0x80: "CAN-L short to CAN-H",
}

# The bits on the wire.
WIRE = {
    "sof": ("Start of frame", "One dominant bit. Every node synchronises its clock on this edge."),
    "id": ("Identifier", "Sent most significant bit first. During arbitration every sender compares the bus with "
                         "its own bit; a sender of a recessive 1 that reads a dominant 0 has lost and stops."),
    "srr": ("SRR", "Substitute remote request: recessive, so a base frame with the same first 11 bits wins."),
    "ide": ("IDE", "Identifier extension: dominant (0) for an 11-bit identifier, recessive (1) for 29 bits."),
    "rtr": ("RTR", "Remote transmission request: dominant (0) for a data frame, recessive (1) for a remote "
                   "request, so a data frame wins over a request with the same identifier."),
    "r1": ("r1", "Reserved bit, sent dominant."),
    "r0": ("r0", "Reserved bit, sent dominant."),
    "dlc": ("DLC", "Data length code: the number of data bytes, 0-8."),
    "data": ("Data", "The data bytes, byte 0 first, each byte most significant bit first."),
    "crc": ("CRC", "15-bit CRC (polynomial 4599h) over the bits from start of frame to the end of the data, before "
                   "stuffing. Every receiver computes it too; on a mismatch it sends an error frame."),
    "crcdel": ("CRC delimiter", "Always recessive."),
    "ack": ("ACK slot", "The sender sends recessive here; every node that received the frame correctly overwrites "
                        "it with dominant. No acknowledge means no other node got the frame: a wrong bit rate, a "
                        "missing termination or a single node on the bus."),
    "ackdel": ("ACK delimiter", "Always recessive."),
    "eof": ("End of frame", "Seven recessive bits."),
    "ifs": ("Intermission", "Three recessive bits before the next frame may start."),
    "stuff": ("Stuff bit", "The five bits before this one had the same level, so the sender inserted one bit of the "
                           "opposite level. Receivers remove it again. Stuffing keeps level changes on the bus so "
                           "every node stays in step; six equal bits in a row would be a stuff error."),
}
WIRE_NOTE = ("Rebuilt from the identifier and data as a correct CAN controller sends them. SocketCAN hands over "
             "finished frames, so real bit timing, real stuff bits and error flags are not measured here.")
ARBITRATION = ("The identifier is also the frame's priority: when several nodes start sending at once, the one "
               "with the lowest identifier wins the bus and the others try again afterwards.")
