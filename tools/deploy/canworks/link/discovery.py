"""Finding runtimes on the local network: the device advertises
_canworks._tcp over mDNS/DNS-SD (an Avahi service file, `avahi_service`), the
PC tools browse for it with python-zeroconf rather than the operating
system's .local lookup, which is unreliable on Windows."""

import socket
import struct
import time
from xml.sax.saxutils import escape

SERVICE = "_canworks._tcp.local."
NOT_AVAILABLE = "discovery needs the zeroconf package"


def available():
    try:
        import zeroconf  # noqa: F401
    except Exception:
        return False
    return True


def avahi_service(diag_port=7531, runtime_port=8443, link_id=None, link_port=7533, name=None):
    """The /etc/avahi/services/canworks.service file. `name` None: Avahi's %h
    (the host name). runtime_port None on a bridge."""
    txt = ["v=1", "diag=%d" % diag_port]
    if runtime_port:
        txt.append("runtime=%d" % runtime_port)
    if link_id:
        txt += ["id=%s" % link_id, "link=%d" % link_port]
    records = "".join("    <txt-record>%s</txt-record>\n" % escape(t) for t in txt)
    return ('<?xml version="1.0" standalone="no"?>\n'
            '<!DOCTYPE service-group SYSTEM "avahi-service.dtd">\n'
            '<service-group>\n'
            '  <name replace-wildcards="yes">%s</name>\n'
            '  <service>\n'
            '    <type>_canworks._tcp</type>\n'
            '    <port>%d</port>\n'
            '%s'
            '  </service>\n'
            '</service-group>\n') % (escape(name) if name else "%h", diag_port, records)


def _txt(props):
    out = {}
    for k, v in (props or {}).items():
        try:
            out[k.decode("utf-8") if isinstance(k, bytes) else str(k)] = (
                v.decode("utf-8") if isinstance(v, bytes) else (v or ""))
        except UnicodeDecodeError:
            pass
    return out


def _int(text, default):
    try:
        return int(text)
    except (TypeError, ValueError):
        return default


def browse(timeout=2.0):
    """Runtimes that answer within `timeout` seconds: [{name, addresses,
    diag, runtime, id, link}], sorted by name. [] without zeroconf."""
    if not available():
        return []
    from zeroconf import ServiceBrowser, Zeroconf
    found = {}

    class Listener:
        def add_service(self, zc, type_, name):
            found[name] = None

        def update_service(self, zc, type_, name):
            found[name] = None

        def remove_service(self, zc, type_, name):
            found.pop(name, None)

    zc = Zeroconf()
    try:
        ServiceBrowser(zc, SERVICE, Listener())
        time.sleep(timeout)
        out = []
        for name in list(found):
            info = zc.get_service_info(SERVICE, name, timeout=1000)
            if not info:
                continue
            txt = _txt(info.properties)
            addrs = info.parsed_scoped_addresses() if hasattr(info, "parsed_scoped_addresses") else [
                socket.inet_ntoa(a) for a in info.addresses if len(a) == 4]
            out.append({
                "name": name[:-len(SERVICE) - 1] if name.endswith("." + SERVICE) else name,
                "addresses": addrs, "diag": _int(txt.get("diag"), info.port),
                "runtime": _int(txt.get("runtime"), None), "id": txt.get("id") or None,
                "link": _int(txt.get("link"), None),
            })
        return sorted(out, key=lambda r: r["name"].lower())
    finally:
        zc.close()


def _dns_name(data, pos):
    """(name, position after it) of a DNS name at `pos`, following pointers."""
    labels, end, jumps = [], None, 0
    while True:
        n = data[pos]
        if n & 0xC0 == 0xC0:
            if end is None:
                end = pos + 2
            pos = ((n & 0x3F) << 8) | data[pos + 1]
            jumps += 1
            if jumps > 20:
                raise ValueError("pointer loop")
            continue
        pos += 1
        if n == 0:
            return ".".join(labels), (end if end is not None else pos)
        labels.append(data[pos:pos + n].decode("utf-8", "replace"))
        pos += n


def parse_answer(data):
    """The _canworks._tcp records of an mDNS answer: {name, port, txt} or None."""
    count = sum(struct.unpack(">HHHH", data[4:12])[1:])  # answers + authority + additional
    pos = 12
    for _ in range(struct.unpack(">H", data[4:6])[0]):  # skip the questions
        _, pos = _dns_name(data, pos)
        pos += 4
    found = {"name": None, "port": None, "txt": {}}
    for _ in range(count):
        name, pos = _dns_name(data, pos)
        rtype, _, _, length = struct.unpack(">HHIH", data[pos:pos + 10])
        pos += 10
        rdata = data[pos:pos + length]
        if SERVICE[:-1] in name.lower() or name.lower().endswith("._canworks._tcp.local"):
            if rtype == 33 and len(rdata) >= 6:     # SRV: priority, weight, port, target
                found["port"] = struct.unpack(">H", rdata[4:6])[0]
                found["name"] = name.split("._canworks._tcp", 1)[0]
            elif rtype == 16:                        # TXT
                i = 0
                while i < len(rdata):
                    n = rdata[i]
                    k, _, v = rdata[i + 1:i + 1 + n].decode("utf-8", "replace").partition("=")
                    found["txt"][k] = v
                    i += 1 + n
            elif rtype == 12 and found["name"] is None:  # PTR to the instance
                target, _ = _dns_name(data, pos)
                found["name"] = target.split("._canworks._tcp", 1)[0]
        pos += length
    return found if found["name"] else None


def query_host(ip, timeout=1.5):
    """Ask one host directly for _canworks._tcp (a legacy unicast mDNS query,
    RFC 6762 6.7): the answer comes back to this socket, so it gets through
    firewalls that drop multicast answers (Windows on a Public network).
    Returns a runtime like browse() does, or None."""
    q = b"".join(bytes([len(p)]) + p.encode() for p in SERVICE.split(".") if p) + b"\0"
    msg = struct.pack(">HHHHHH", 0x6377, 0, 1, 0, 0, 0) + q + struct.pack(">HH", 12, 1)
    fam = socket.AF_INET6 if ":" in ip else socket.AF_INET
    s = socket.socket(fam, socket.SOCK_DGRAM)
    try:
        s.settimeout(timeout)
        s.sendto(msg, (ip.split("%")[0], 5353))
        data, _ = s.recvfrom(9000)
        r = parse_answer(data)
    except (OSError, ValueError, struct.error, IndexError):
        return None
    finally:
        s.close()
    if not r:
        return None
    txt = r["txt"]
    return {"name": r["name"], "addresses": [ip], "diag": _int(txt.get("diag"), r["port"]),
            "runtime": _int(txt.get("runtime"), None), "id": txt.get("id") or None,
            "link": _int(txt.get("link"), None)}


def find_address(host, timeout=2.0):
    """The advertised runtime whose addresses include `host` (an IP or a name
    that resolves to one), else None: asked directly first, then by browsing."""
    try:
        ips = {ai[4][0] for ai in socket.getaddrinfo(host, None)}
    except OSError:
        ips = {host}
    for ip in sorted(ips, key=lambda a: (":" in a, a)):   # IPv4 first
        r = query_host(ip)
        if r:
            return r
    for r in browse(timeout):
        if ips & {a.split("%")[0] for a in r["addresses"]} or host.rstrip(".").lower() in (
                r["name"].lower(), r["name"].lower() + ".local"):
            return r
    return None
