"""SDO client (CiA 301) on the default channel of a node: expedited and
segmented upload and download, enough for the diagnostics channel's limit of
4096 bytes. Block transfer is not used."""

import struct
import threading

ABORT_TIMEOUT = 0x05040000
ABORT_BAD_COMMAND = 0x05040001
ABORT_TOGGLE = 0x05030000
MAX_BYTES = 4096

_node_locks = {}
_node_locks_lock = threading.Lock()


class SdoAbort(Exception):
    def __init__(self, code, text=None):
        super().__init__(text or "abort 0x%08X" % code)
        self.code = code


class SdoTimeout(Exception):
    pass


def _lock(core, node):
    with _node_locks_lock:
        return _node_locks.setdefault((id(core), node), threading.Lock())


def _abort(core, node, index, sub, code):
    try:
        core.transmit(0x600 + node, struct.pack("<BHBI", 0x80, index, sub, code))
    except Exception:
        pass


def _answer(rx, timeout_s, node, index, sub, core):
    data = rx.get(timeout_s)
    if data is None:
        _abort(core, node, index, sub, ABORT_TIMEOUT)
        raise SdoTimeout()
    data = bytes(data).ljust(8, b"\0")
    if data[0] == 0x80:
        raise SdoAbort(struct.unpack_from("<I", data, 4)[0])
    return data


def _check_mux(data, index, sub, core, node):
    i, s = struct.unpack_from("<HB", data, 1)
    if (i, s) != (index, sub):
        _abort(core, node, index, sub, ABORT_BAD_COMMAND)
        raise SdoAbort(ABORT_BAD_COMMAND, "answer for 0x%04X:%d, not 0x%04X:%d" % (i, s, index, sub))


def upload(core, node, index, sub, timeout_s):
    """Read an object; the bytes. Raises SdoAbort or SdoTimeout."""
    with _lock(core, node):
        core.wait_foreign_sdo(node)
        with core.expect(0x580 + node) as rx:
            core.transmit(0x600 + node, struct.pack("<BHB4x", 0x40, index, sub))
            data = _answer(rx, timeout_s, node, index, sub, core)
            if data[0] >> 5 != 2:
                _abort(core, node, index, sub, ABORT_BAD_COMMAND)
                raise SdoAbort(ABORT_BAD_COMMAND, "unexpected answer 0x%02X" % data[0])
            _check_mux(data, index, sub, core, node)
            expedited, sized = data[0] & 0x02, data[0] & 0x01
            if expedited:
                n = (data[0] >> 2) & 0x03 if sized else 0
                return bytes(data[4:8 - n])
            size = struct.unpack_from("<I", data, 4)[0] if sized else None
            if size is not None and size > MAX_BYTES:
                _abort(core, node, index, sub, 0x05040005)  # out of memory
                raise SdoAbort(0x05040005, "the object holds %d bytes, more than the %d a manual read returns"
                               % (size, MAX_BYTES))
            out = bytearray()
            toggle = 0
            while True:
                core.transmit(0x600 + node, bytes([0x60 | toggle << 4]) + bytes(7))
                seg = _answer(rx, timeout_s, node, index, sub, core)
                if seg[0] >> 5 != 0:
                    _abort(core, node, index, sub, ABORT_BAD_COMMAND)
                    raise SdoAbort(ABORT_BAD_COMMAND, "unexpected segment 0x%02X" % seg[0])
                if (seg[0] >> 4) & 1 != toggle:
                    _abort(core, node, index, sub, ABORT_TOGGLE)
                    raise SdoAbort(ABORT_TOGGLE)
                n = (seg[0] >> 1) & 0x07
                out += seg[1:8 - n]
                if len(out) > MAX_BYTES:
                    _abort(core, node, index, sub, 0x05040005)
                    raise SdoAbort(0x05040005, "the object holds more than the %d bytes a manual read returns"
                                   % MAX_BYTES)
                if seg[0] & 0x01:
                    break
                toggle ^= 1
            return bytes(out[:size] if size is not None else out)


def download(core, node, index, sub, payload, timeout_s):
    """Write an object. Raises SdoAbort or SdoTimeout."""
    payload = bytes(payload)
    with _lock(core, node):
        core.wait_foreign_sdo(node)
        with core.expect(0x580 + node) as rx:
            if 0 < len(payload) <= 4:
                n = 4 - len(payload)
                core.transmit(0x600 + node, struct.pack("<BHB", 0x23 | n << 2, index, sub) + payload.ljust(4, b"\0"))
                data = _answer(rx, timeout_s, node, index, sub, core)
                if data[0] != 0x60:
                    _abort(core, node, index, sub, ABORT_BAD_COMMAND)
                    raise SdoAbort(ABORT_BAD_COMMAND, "unexpected answer 0x%02X" % data[0])
                _check_mux(data, index, sub, core, node)
                return
            core.transmit(0x600 + node, struct.pack("<BHBI", 0x21, index, sub, len(payload)))
            data = _answer(rx, timeout_s, node, index, sub, core)
            if data[0] != 0x60:
                _abort(core, node, index, sub, ABORT_BAD_COMMAND)
                raise SdoAbort(ABORT_BAD_COMMAND, "unexpected answer 0x%02X" % data[0])
            _check_mux(data, index, sub, core, node)
            toggle, pos = 0, 0
            while True:
                chunk = payload[pos:pos + 7]
                pos += len(chunk)
                last = pos >= len(payload)
                cmd = toggle << 4 | (7 - len(chunk)) << 1 | (1 if last else 0)
                core.transmit(0x600 + node, bytes([cmd]) + chunk.ljust(7, b"\0"))
                seg = _answer(rx, timeout_s, node, index, sub, core)
                if seg[0] & 0xEF != 0x20:
                    _abort(core, node, index, sub, ABORT_BAD_COMMAND)
                    raise SdoAbort(ABORT_BAD_COMMAND, "unexpected answer 0x%02X" % seg[0])
                if (seg[0] >> 4) & 1 != toggle:
                    _abort(core, node, index, sub, ABORT_TOGGLE)
                    raise SdoAbort(ABORT_TOGGLE)
                if last:
                    return
                toggle ^= 1
