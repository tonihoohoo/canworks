"""LSS master (CiA 305): switch state, fastscan, configure node ID and bit
timing, store (only when asked), inquire node ID."""

import struct

from .core import LSS_RX_COB, LSS_TX_COB

TIMEOUT_S = 0.5  # a configuration service's answer
FASTSCAN_STEP_S = 0.1  # one fastscan probe

# CiA 305 bit timing table 0: kbit/s -> index
BIT_TIMING = {1000: 0, 800: 1, 500: 2, 250: 3, 125: 4, 50: 6, 20: 7, 10: 8}


class LssError(Exception):
    def __init__(self, message, timed_out=False):
        super().__init__(message)
        self.timed_out = timed_out


def _send(core, cs, payload=b""):
    core.transmit(LSS_TX_COB, (bytes([cs]) + bytes(payload)).ljust(8, b"\0"))


def _wait(rx, cs, timeout):
    """The next answer with command specifier `cs`, or None."""
    import time
    end = time.monotonic() + timeout
    while True:
        data = rx.get(end - time.monotonic())
        if data is None:
            return None
        data = bytes(data).ljust(8, b"\0")
        if data[0] == cs:
            return data


def switch_global(core, configuration):
    _send(core, 0x04, bytes([1 if configuration else 0]))


def switch_selective(core, address):
    """Puts the device with this address (vendor, product, revision, serial)
    into configuration state. Raises LssError(timed_out=True) when none
    answers."""
    with core.expect(LSS_RX_COB) as rx:
        for cs, value in zip((0x40, 0x41, 0x42, 0x43), address):
            _send(core, cs, struct.pack("<I", value))
        if _wait(rx, 0x44, TIMEOUT_S) is None:
            raise LssError("no answer", timed_out=True)


def _configure(core, cs, payload, what):
    with core.expect(LSS_RX_COB) as rx:
        _send(core, cs, payload)
        data = _wait(rx, cs, TIMEOUT_S)
    if data is None:
        raise LssError("%s: no answer" % what, timed_out=True)
    if data[1] == 0xFF:
        raise LssError("%s: refused by the device (its own error 0x%02X)" % (what, data[2]))
    if data[1]:
        raise LssError("%s: refused by the device (error %d)" % (what, data[1]))


def inquire_node_id(core):
    with core.expect(LSS_RX_COB) as rx:
        _send(core, 0x5E)
        data = _wait(rx, 0x5E, TIMEOUT_S)
    if data is None:
        raise LssError("LSS inquire node ID failed: no answer", timed_out=True)
    return data[1]


def configure_node_id(core, node):
    _configure(core, 0x11, bytes([node]), "LSS configure node-ID failed")


def configure_bit_timing(core, kbit):
    _configure(core, 0x13, bytes([0, BIT_TIMING[kbit]]), "LSS configure bit timing failed")


def store(core):
    _configure(core, 0x17, b"", "LSS store configuration failed")


def fastscan(core, vendor_id=None, product_code=None, step_s=FASTSCAN_STEP_S, should_stop=None, attempts=3):
    """Finds one device without a node ID; its address (4 ints) or None. The
    found device is left in configuration state. Known vendor and product
    skip the search of those parts."""
    known = {0: vendor_id, 1: product_code} if vendor_id is not None and product_code is not None else {}

    with core.expect(LSS_RX_COB) as rx:
        def probe(idn, bit, sub, nxt, step):
            rx.drain()
            _send(core, 0x51, struct.pack("<IBBB", idn & 0xFFFFFFFF, bit, sub, nxt))
            return _wait(rx, 0x4F, step) is not None

        def scan(step):
            address = [0, 0, 0, 0]
            for sub in range(4):
                nxt = (sub + 1) % 4
                if sub in known:
                    address[sub] = known[sub]
                else:
                    for bit in range(31, -1, -1):
                        if should_stop and should_stop():
                            return None
                        if not probe(address[sub], bit, sub, sub, step):
                            address[sub] |= 1 << bit
                if not probe(address[sub], 0, sub, nxt, step):
                    return None
            return tuple(address)

        # Anyone without a node ID? Asked up to three times: on a busy PC one
        # answer can come later than a probe step.
        if not any(probe(0, 0x80, 0, 0, step_s) for _ in range(3)):
            return None
        # A missing answer reads as a 1 bit, so one late answer on a busy PC
        # spoils the address and the check of that part fails. Then the scan
        # starts over (the 0x80 probe resets every device's scan position)
        # with longer steps.
        for attempt in range(attempts):
            step = step_s * 2 ** attempt
            if attempt and not probe(0, 0x80, 0, 0, step):
                continue
            address = scan(step)
            if address is not None or (should_stop and should_stop()):
                return address
        return None
