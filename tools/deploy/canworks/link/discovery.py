"""Finding runtimes on the local network: the device advertises
_canworks._tcp over mDNS/DNS-SD (an Avahi service file, `avahi_service`), the
PC tools ask for it with their own one-shot query rather than the operating
system's .local lookup, which is unreliable on Windows. An adapter server
(canworks-diag adapter-serve) advertises the same service type with TXT
kind=adapter (`avahi_adapter_service`); answers carry their kind.

The question goes out from sockets that are never bound to a port, so the
responders answer by legacy unicast (RFC 6762 6.7) straight back to them:
nothing listens on 5353, Windows Defender Firewall does not ask to allow
Python, and the answers get in on a Public network too (Windows lets unicast
answers to a multicast question in)."""

import ipaddress
import select
import socket
import struct
import time
from xml.sax.saxutils import escape

SERVICE = "_canworks._tcp.local."
MDNS_PORT = 5353
GROUP_V4, GROUP_V6 = "224.0.0.251", "ff02::fb"
RESEND_S = 1.0  # the question goes out again after this, in case UDP lost it


def available():
    """Whether this PC can browse: always, the query needs only the standard library and ifaddr."""
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


def avahi_adapter_service(port, name, adapter, bitrate_kbit):
    """The Avahi service file of an adapter server: kind=adapter with its
    machine's name, the adapter and the bit rate it serves."""
    txt = ["v=1", "kind=adapter", "name=%s" % name, "adapter=%s" % adapter, "bitrate=%d" % bitrate_kbit]
    records = "".join("    <txt-record>%s</txt-record>\n" % escape(t) for t in txt)
    return ('<?xml version="1.0" standalone="no"?>\n'
            '<!DOCTYPE service-group SYSTEM "avahi-service.dtd">\n'
            '<service-group>\n'
            '  <name>%s</name>\n'
            '  <service>\n'
            '    <type>_canworks._tcp</type>\n'
            '    <port>%d</port>\n'
            '%s'
            '  </service>\n'
            '</service-group>\n') % (escape("%s adapter %s" % (name, adapter)), port, records)


def _entry(name, addresses, port, txt):
    """One answer as browse() and query_host() give it: a runtime ({name,
    addresses, diag, runtime, id, link, kind: "runtime"}) or an adapter
    server (kind "adapter", with its machine's name, adapter and bitrate in
    kbit/s; diag is its port)."""
    kind = "adapter" if txt.get("kind") == "adapter" else "runtime"
    out = {"name": name, "addresses": addresses, "diag": _int(txt.get("diag"), port),
           "runtime": _int(txt.get("runtime"), None), "id": txt.get("id") or None,
           "link": _int(txt.get("link"), None), "kind": kind}
    if kind == "adapter":
        out.update(machine=txt.get("name") or name, adapter=txt.get("adapter") or "",
                   bitrate=_int(txt.get("bitrate"), None))
    return out


def _int(text, default):
    try:
        return int(text)
    except (TypeError, ValueError):
        return default


def _question(unicast_answer=True):
    """A PTR question for _canworks._tcp.local, with the QU bit by default."""
    q = b"".join(bytes([len(p)]) + p.encode() for p in SERVICE.split(".") if p) + b"\0"
    return struct.pack(">HHHHHH", 0x6377, 0, 1, 0, 0, 0) + q + struct.pack(">HH", 12, 0x8001 if unicast_answer else 1)


def _interfaces():
    """[(family, address, scope id)] to ask on: each IPv4 address that is not
    loopback (169.254.x.x included, for a direct cable) and each IPv6
    link-local scope once."""
    import ifaddr
    out, scopes = [], set()
    for adapter in ifaddr.get_adapters():
        for ip in adapter.ips:
            if isinstance(ip.ip, str):
                if not ip.ip.startswith("127."):
                    out.append((socket.AF_INET, ip.ip, 0))
            else:
                addr, _, scope = ip.ip
                if addr.lower().startswith("fe80") and scope and scope not in scopes:
                    scopes.add(scope)
                    out.append((socket.AF_INET6, addr, scope))
    return out


def _open_senders(interfaces, group_v4, group_v6, port):
    """One unbound UDP socket per interface, set to send the question out of
    it: [(socket, destination)]. An interface that refuses is left out."""
    out = []
    for fam, addr, scope in interfaces:
        s = socket.socket(fam, socket.SOCK_DGRAM)
        try:
            if fam == socket.AF_INET:
                s.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_IF, socket.inet_aton(addr))
                s.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 255)
                dest = (group_v4, port)
            else:
                s.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_MULTICAST_IF, scope)
                s.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_MULTICAST_HOPS, 255)
                dest = (group_v6, port, 0, scope)
        except OSError:
            s.close()
            continue
        out.append((s, dest))
    return out


def _source(src):
    """The address text of a recvfrom() source, with the scope of an IPv6 link-local one."""
    addr = src[0]
    if len(src) >= 4 and src[3] and "%" not in addr and addr.lower().startswith("fe80"):
        addr = "%s%%%d" % (addr, src[3])
    return addr


def browse(timeout=2.0, interfaces=None, group_v4=GROUP_V4, group_v6=GROUP_V6, port=MDNS_PORT):
    """Runtimes and adapter servers that answer within `timeout` seconds
    (see _entry), sorted by name. The question goes out on every interface
    (`interfaces`, as _interfaces() gives them) from an unbound socket; an
    answer's source address is the service's first address."""
    q = _question()
    senders = _open_senders(_interfaces() if interfaces is None else interfaces, group_v4, group_v6, port)
    found = {}   # instance -> {"port", "txt", "addresses"}
    try:
        sent_at = []
        for s, dest in senders:
            try:
                s.sendto(q, dest)
            except OSError:
                continue
            sent_at.append(s)
        start = time.monotonic()
        resent = False
        while sent_at:
            now = time.monotonic()
            if now - start >= timeout:
                break
            if not resent and now - start >= RESEND_S:
                resent = True
                for s, dest in senders:
                    try:
                        s.sendto(q, dest)
                    except OSError:
                        pass
            until = timeout if resent else min(timeout, RESEND_S)
            # Short waits: on Windows Ctrl+C only gets through between select calls.
            ready, _, _ = select.select(sent_at, [], [], min(0.5, max(0.01, until - (now - start))))
            for s in ready:
                try:
                    data, src = s.recvfrom(9000)
                except OSError:
                    continue
                try:
                    instances, hosts = parse_answers(data)
                except (ValueError, struct.error, IndexError):
                    continue
                addr = _source(src)
                for name, rec in instances.items():
                    item = found.setdefault(name, {"port": None, "txt": {}, "addresses": []})
                    if rec["port"] is not None:
                        item["port"] = rec["port"]
                    item["txt"].update(rec["txt"])
                    extra = hosts.get((rec["target"] or "").lower(), [])
                    for a in [addr] + extra:
                        if a not in item["addresses"]:
                            item["addresses"].append(a)
    finally:
        for s, _ in senders:
            s.close()
    missing = {item["addresses"][0] for item in found.values() if item["port"] is None and item["addresses"]}
    for addr in sorted(missing):
        # The answer named an instance but left out its SRV record: ask that host directly.
        r = query_host(addr, port=port)
        if r and r["name"] in found:
            found[r["name"]].update(port=r["diag"], txt=dict(found[r["name"]]["txt"], **_txt_of(r)))
    out = [_entry(name, item["addresses"], item["port"], item["txt"])
           for name, item in found.items() if item["port"] is not None and item["addresses"]]
    return sorted(out, key=lambda r: r["name"].lower())


def _txt_of(entry):
    """The TXT keys an _entry carries, for merging a direct answer."""
    return {k: str(entry[k]) for k in ("diag", "runtime", "id", "link") if entry.get(k) is not None}


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


def parse_answers(data):
    """The _canworks._tcp records of an mDNS answer: ({instance: {port, txt,
    target}}, {host name: [addresses]}). An instance named only by a PTR has
    port None; host names are lower case without the trailing dot."""
    count = sum(struct.unpack(">HHHH", data[4:12])[1:])  # answers + authority + additional
    pos = 12
    for _ in range(struct.unpack(">H", data[4:6])[0]):  # skip the questions
        _, pos = _dns_name(data, pos)
        pos += 4
    instances, hosts = {}, {}

    def instance(owner):
        return instances.setdefault(owner.split("._canworks._tcp", 1)[0], {"port": None, "txt": {}, "target": None})
    for _ in range(count):
        name, pos = _dns_name(data, pos)
        rtype, _, _, length = struct.unpack(">HHIH", data[pos:pos + 10])
        pos += 10
        rdata = data[pos:pos + length]
        if len(rdata) != length:
            raise ValueError("record past the end")
        lname = name.lower()
        if lname.endswith("._canworks._tcp.local"):
            if rtype == 33 and len(rdata) >= 6:     # SRV: priority, weight, port, target
                rec = instance(name)
                rec["port"] = struct.unpack(">H", rdata[4:6])[0]
                rec["target"] = _dns_name(data, pos + 6)[0].lower()
            elif rtype == 16:                        # TXT
                rec = instance(name)
                i = 0
                while i < len(rdata):
                    n = rdata[i]
                    k, _, v = rdata[i + 1:i + 1 + n].decode("utf-8", "replace").partition("=")
                    if k:
                        rec["txt"][k] = v
                    i += 1 + n
        elif lname == SERVICE[:-1] and rtype == 12:  # PTR to the instance
            instance(_dns_name(data, pos)[0])
        elif rtype == 1 and length == 4:             # A
            hosts.setdefault(lname, []).append(socket.inet_ntoa(rdata))
        elif rtype == 28 and length == 16:           # AAAA
            a = socket.inet_ntop(socket.AF_INET6, rdata)
            if not a.lower().startswith("fe80"):     # a link-local one needs its scope, which only the source has
                hosts.setdefault(lname, []).append(a)
        pos += length
    return instances, hosts


def parse_answer(data):
    """The first _canworks._tcp instance of an mDNS answer: {name, port, txt} or None."""
    instances, _ = parse_answers(data)
    if not instances:
        return None
    name = next((n for n, r in instances.items() if r["port"] is not None), next(iter(instances)))
    return {"name": name, "port": instances[name]["port"], "txt": instances[name]["txt"]}


def _same_ip(a, b):
    try:
        return ipaddress.ip_address(a.split("%")[0]) == ipaddress.ip_address(b.split("%")[0])
    except ValueError:
        return False


def query_host(ip, timeout=1.5, port=MDNS_PORT):
    """Ask one host directly for _canworks._tcp (a legacy unicast mDNS query,
    RFC 6762 6.7): the answer comes back to this socket, so it gets through
    firewalls that drop multicast answers (Windows on a Public network).
    Only an answer from `ip` itself counts: datagrams from other hosts are
    dropped. Returns a runtime like browse() does, or None."""
    msg = _question(unicast_answer=False)
    fam = socket.AF_INET6 if ":" in ip else socket.AF_INET
    s = socket.socket(fam, socket.SOCK_DGRAM)
    deadline = time.monotonic() + timeout
    try:
        s.sendto(msg, (ip.split("%")[0], port))
        while True:
            left = deadline - time.monotonic()
            if left <= 0:
                return None
            s.settimeout(left)
            data, src = s.recvfrom(9000)
            if not _same_ip(src[0], ip):
                continue
            try:
                r = parse_answer(data)
            except (ValueError, struct.error, IndexError):
                continue
            if r:
                break
    except OSError:
        return None
    finally:
        s.close()
    return _entry(r["name"], [ip], r["port"], r["txt"])


def find_address(host, timeout=2.0, kind=None):
    """The advertised runtime (or adapter server) whose addresses include
    `host` (an IP or a name that resolves to one), else None: asked directly
    first, then by browsing. `kind` "runtime" or "adapter" takes only that
    kind."""
    try:
        ips = {ai[4][0] for ai in socket.getaddrinfo(host, None)}
    except OSError:
        ips = {host}
    for ip in sorted(ips, key=lambda a: (":" in a, a)):   # IPv4 first
        r = query_host(ip)
        if r and kind in (None, r["kind"]):
            return r
    for r in browse(timeout):
        if kind not in (None, r["kind"]):
            continue
        if ips & {a.split("%")[0] for a in r["addresses"]} or host.rstrip(".").lower() in (
                r["name"].lower(), r["name"].lower() + ".local"):
            return r
    return None
