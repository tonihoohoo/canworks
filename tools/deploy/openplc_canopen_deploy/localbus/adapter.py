"""Opening a CAN adapter on this PC with python-can (canopen-local-bus).

An adapter is written TYPE:CHANNEL: slcan:COM5, slcan:/dev/tty.usbmodem14101,
socketcan:can0, or any other python-can interface (gs_usb:0, pcan:PCAN_USBBUS1,
...), which is passed through untested. `virtual:NAME` is python-can's
in-process bus, for tests.

open() is the one place an adapter is opened. It takes `listen_only` so a
later change (raw frames and bit rate detection) can open an adapter without
acknowledging frames; this change always passes False.
"""

import json
import os
import re
import subprocess
import sys
import tempfile

SUPPORTED = ("slcan", "socketcan")  # tested; anything else python-can knows is passed through
TEST_ONLY = ("virtual",)

# USB IDs of adapters that run slcan firmware out of the box.
SLCAN_USB_IDS = {
    (0xAD50, 0x60C4): "CANable (slcan firmware)",
    (0x16D0, 0x117E): "CANable 2.0 (slcan firmware)",
}
# USB IDs of adapters that need another interface type.
OTHER_USB_IDS = {
    (0x1D50, 0x606F): ("gs_usb", "candleLight / gs_usb firmware (socketcan on Linux, gs_usb elsewhere)"),
}


class AdapterError(Exception):
    """kind: usage (bad spec or bit rate), busy (another tool has it open),
    unreachable (cannot be opened)."""

    def __init__(self, kind, message):
        super().__init__(message)
        self.kind = kind


class Spec:
    def __init__(self, kind, channel, options=None):
        self.kind, self.channel = kind, channel
        self.options = dict(options or {})

    def __str__(self):
        return "%s:%s" % (self.kind, self.channel)

    def __repr__(self):
        return "Spec(%r)" % str(self)

    def __eq__(self, other):
        return isinstance(other, Spec) and (self.kind, self.channel, self.options) == \
            (other.kind, other.channel, other.options)

    def __hash__(self):
        return hash((self.kind, self.channel))


def _interfaces():
    try:
        import can
        return set(can.VALID_INTERFACES)
    except ImportError:
        return set(SUPPORTED) | set(TEST_ONLY)


def _option_value(text):
    for conv in (lambda t: int(t, 0), float):
        try:
            return conv(text)
        except ValueError:
            pass
    if text.lower() in ("true", "false"):
        return text.lower() == "true"
    return text


def parse(text, options=()):
    """'TYPE:CHANNEL' (plus KEY=VALUE options) -> Spec. Raises AdapterError."""
    text = (text or "").strip()
    kind, sep, channel = text.partition(":")
    kind = kind.strip().lower()
    if not sep or not kind or not channel.strip():
        raise AdapterError("usage", "write the adapter as TYPE:CHANNEL, e.g. slcan:COM5, "
                                    "slcan:/dev/tty.usbmodem14101 or socketcan:can0")
    if kind not in _interfaces():
        raise AdapterError("usage", "unknown adapter type %r; python-can knows %s" % (
            kind, ", ".join(sorted(_interfaces()))))
    opts = {}
    for item in options or ():
        key, eq, value = str(item).partition("=")
        if not eq or not key.strip():
            raise AdapterError("usage", "--adapter-option %r: write KEY=VALUE" % item)
        opts[key.strip()] = _option_value(value.strip())
    return Spec(kind, channel.strip(), opts)


def untested(spec):
    return spec.kind not in SUPPORTED and spec.kind not in TEST_ONLY


# ---------------------------------------------------------------------------
# One tool per adapter


class _Lock:
    """An OS file lock named after the adapter, held while it is open, so a
    second tool (another configurator, a CLI) gets a clear message instead of
    sharing the adapter."""

    def __init__(self, spec):
        folder = os.path.join(tempfile.gettempdir(), "openplc-canopen-adapters")
        os.makedirs(folder, exist_ok=True)
        name = re.sub(r"[^A-Za-z0-9_.-]+", "_", str(spec))
        self.path = os.path.join(folder, name + ".lock")
        self.fd = None

    def acquire(self):
        fd = os.open(self.path, os.O_RDWR | os.O_CREAT, 0o600)
        try:
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            os.close(fd)
            return False
        self.fd = fd
        return True

    def release(self):
        if self.fd is None:
            return
        try:
            if os.name == "nt":
                import msvcrt
                try:
                    os.lseek(self.fd, 0, 0)
                    msvcrt.locking(self.fd, msvcrt.LK_UNLCK, 1)
                except OSError:
                    pass
            os.close(self.fd)
        finally:
            self.fd = None


# ---------------------------------------------------------------------------
# SocketCAN link


def _link(interface):
    """(up, bitrate or None, kind) of a SocketCAN link from `ip`, or None
    when `ip` cannot tell."""
    try:
        out = subprocess.run(["ip", "-details", "-json", "link", "show", "dev", interface],
                             capture_output=True, text=True, timeout=5)
    except (OSError, subprocess.SubprocessError):
        return None
    if out.returncode != 0:
        raise AdapterError("unreachable", "no CAN interface %s on this PC%s" % (
            interface, ": " + out.stderr.strip() if out.stderr.strip() else ""))
    try:
        info = json.loads(out.stdout)[0]
    except (ValueError, IndexError, TypeError):
        return None
    flags = info.get("flags") or []
    linkinfo = info.get("linkinfo") or {}
    kind = linkinfo.get("info_kind")
    bitrate = ((linkinfo.get("info_data") or {}).get("bittiming") or {}).get("bitrate")
    return "UP" in flags, bitrate, kind


def _socketcan_up(interface, bitrate):
    """Use the link's own bit rate when it is up; bring it up at `bitrate`
    when it is down and this user may. Returns the bit rate in use."""
    link = _link(interface)
    if link is None:
        return bitrate
    up, rate, kind = link
    if up:
        return rate or bitrate
    cmd = ["ip", "link", "set", "dev", interface, "up"]
    if kind == "can":
        cmd += ["type", "can", "bitrate", str(bitrate)]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=5)
    except (OSError, subprocess.SubprocessError) as e:
        r = None
        err = str(e)
    else:
        err = r.stderr.strip()
    if r is None or r.returncode != 0:
        raise AdapterError("unreachable", "CAN interface %s is down and could not be brought up (%s); run "
                                          "'sudo %s' first" % (interface, err or "not permitted", " ".join(cmd)))
    return bitrate


# ---------------------------------------------------------------------------
# Opening


class Opened:
    """An open adapter: `bus` (a python-can Bus), the bit rate in use, and the
    lock that keeps other tools off it."""

    def __init__(self, spec, bus, bitrate, lock):
        self.spec, self.bus, self.bitrate, self._lock = spec, bus, bitrate, lock

    def close(self):
        try:
            self.bus.shutdown()
        except Exception:  # an adapter unplugged meanwhile
            pass
        self._lock.release()


def open(spec, bitrate, listen_only=False, options=None):  # noqa: A001 - the module's one entry point
    """Open `spec` (a Spec) at `bitrate` (bit/s). Raises AdapterError."""
    if not bitrate:
        raise AdapterError("usage", "the bit rate is needed: give --bitrate KBIT, or --config with the network's "
                                    "adapter.bitrate")
    try:
        import can
    except ImportError:
        raise AdapterError("unreachable", "python-can is not installed; reinstall the PC tools")
    lock = _Lock(spec)
    if not lock.acquire():
        raise AdapterError("busy", "adapter %s in use (another tool has it open)" % spec)
    kwargs = dict(spec.options)
    kwargs.update(options or {})
    try:
        if spec.kind == "socketcan":
            if not sys.platform.startswith("linux"):
                raise AdapterError("usage", "socketcan adapters exist on Linux only; use slcan:PORT on this PC")
            bitrate = _socketcan_up(spec.channel, bitrate)
        elif spec.kind == "virtual":
            kwargs.setdefault("receive_own_messages", False)
        else:
            kwargs["bitrate"] = bitrate
        if listen_only:
            kwargs["listen_only"] = True
        bus = can.Bus(interface=spec.kind, channel=spec.channel, **kwargs)
    except AdapterError:
        lock.release()
        raise
    except Exception as e:  # python-can raises CanError, OSError, serial errors, ValueError, ...
        lock.release()
        text = str(e) or e.__class__.__name__
        if spec.kind == "slcan" and ("busy" in text.lower() or "denied" in text.lower()):
            raise AdapterError("busy", "adapter %s in use (another program has the serial port open): %s"
                               % (spec, text))
        raise AdapterError("unreachable", "cannot open adapter %s: %s" % (spec, text))
    return Opened(spec, bus, bitrate, lock)


# ---------------------------------------------------------------------------
# What is plugged in


def _serial_ports():
    out = []
    try:
        from serial.tools import list_ports
    except ImportError:
        return out
    for p in list_ports.comports():
        vid, pid = getattr(p, "vid", None), getattr(p, "pid", None)
        entry = {"type": "slcan", "channel": p.device, "description": p.description or "",
                 "usb_id": "%04X:%04X" % (vid, pid) if vid is not None and pid is not None else None,
                 "known": None}
        if (vid, pid) in SLCAN_USB_IDS:
            entry["known"] = SLCAN_USB_IDS[(vid, pid)]
        elif (vid, pid) in OTHER_USB_IDS:
            entry["type"], entry["known"] = OTHER_USB_IDS[(vid, pid)]
        out.append(entry)
    return out


def _socketcan_links():
    out = []
    root = "/sys/class/net"
    if not sys.platform.startswith("linux") or not os.path.isdir(root):
        return out
    for name in sorted(os.listdir(root)):
        try:
            with _read(os.path.join(root, name, "type")) as f:
                kind = f.read().strip()
        except OSError:
            continue
        if kind == "280":  # ARPHRD_CAN
            out.append({"type": "socketcan", "channel": name, "description": "SocketCAN interface",
                        "usb_id": None, "known": "SocketCAN"})
    return out


def _read(path):
    import builtins
    return builtins.open(path, encoding="utf-8")


def _detected(interfaces):
    import logging
    out = []
    log = logging.getLogger("can")
    level = log.level
    log.setLevel(logging.CRITICAL)  # python-can logs every missing vendor driver while it looks
    try:
        import can
        configs = can.detect_available_configs(interfaces=list(interfaces))
    except Exception:
        return out
    finally:
        log.setLevel(level)
    for c in configs:
        kind, channel = c.get("interface"), c.get("channel")
        if kind and channel is not None and kind not in ("socketcan", "slcan", "virtual"):
            out.append({"type": kind, "channel": str(channel), "description": "found by python-can",
                        "usb_id": None, "known": None})
    return out


def list_adapters(probe=("pcan", "kvaser", "ixxat", "vector", "gs_usb")):
    """The adapters this PC has: serial ports (slcan candidates, known USB IDs
    marked), SocketCAN links on Linux, and what python-can finds for the
    other interfaces it has drivers for. Each: type, channel, description,
    usb_id, known (a name when the adapter is recognised), text (the
    --adapter value)."""
    out = _socketcan_links() + _serial_ports() + _detected(probe)
    for a in out:
        a["text"] = "%s:%s" % (a["type"], a["channel"])
    return out
