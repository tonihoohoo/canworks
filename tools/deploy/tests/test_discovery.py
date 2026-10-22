"""Discovery in the PC tools (runtime-discovery): the one-shot question from
unbound sockets, answers with several services, and the source address as
the first address. A fake responder on 127.0.0.1 stands in for Avahi."""

import socket
import struct
import threading
import unittest
from unittest import mock

from canworks.link import discovery


def _name(text, ptr=None):
    out = b"".join(bytes([len(p)]) + p.encode() for p in text.split(".") if p)
    return out + (struct.pack(">H", 0xC000 | ptr) if ptr is not None else b"\0")


def _rr(owner, rtype, rdata):
    return owner + struct.pack(">HHIH", rtype, 0x8001, 10, len(rdata)) + rdata


def _txt(*items):
    return b"".join(bytes([len(t)]) + t.encode() for t in items)


def _answer(services, host="benchbox.local", address="192.0.2.9", srv=True):
    """A legacy unicast answer: the question echoed, a PTR per service and,
    with `srv`, its SRV and TXT records, plus the host's A record.
    `services` is [(instance, port, [txt items])]."""
    q = _name("_canworks._tcp.local")                    # at offset 12
    records = []
    for instance, port, txt in services:
        records.append(_rr(b"\xc0\x0c", 12, _name(instance, 12)))
        if srv:
            records.append(_rr(_name(instance, 12), 33, struct.pack(">HHH", 0, 0, port) + _name(host)))
            records.append(_rr(_name(instance, 12), 16, _txt(*txt)))
    if srv:
        records.append(_rr(_name(host), 1, socket.inet_aton(address)))
    return struct.pack(">HHHHHH", 0x6377, 0x8400, 1, len(records), 0, 0) + q + struct.pack(">HH", 12, 1) + \
        b"".join(records)


RUNTIME = ("line3", 7531, ["v=1", "diag=7531", "runtime=8443", "id=abc", "link=7533"])
ADAPTER = ("benchbox adapter slcan:0", 7536, ["v=1", "kind=adapter", "name=benchbox", "adapter=slcan:0",
                                               "bitrate=500"])
LOOPBACK = [(socket.AF_INET, "127.0.0.1", 0)]


class Parse(unittest.TestCase):
    def test_several_services_in_one_answer(self):
        instances, hosts = discovery.parse_answers(_answer([RUNTIME, ADAPTER]))
        self.assertEqual(sorted(instances), ["benchbox adapter slcan:0", "line3"])
        self.assertEqual(instances["line3"]["port"], 7531)
        self.assertEqual(instances["line3"]["txt"]["id"], "abc")
        self.assertEqual(instances["line3"]["target"], "benchbox.local")
        self.assertEqual(instances["benchbox adapter slcan:0"]["txt"]["kind"], "adapter")
        self.assertEqual(hosts, {"benchbox.local": ["192.0.2.9"]})

    def test_ptr_only(self):
        instances, _ = discovery.parse_answers(_answer([RUNTIME], srv=False))
        self.assertEqual(instances, {"line3": {"port": None, "txt": {}, "target": None}})

    def test_parse_answer_takes_the_first_with_a_port(self):
        r = discovery.parse_answer(_answer([RUNTIME, ADAPTER]))
        self.assertEqual((r["name"], r["port"]), ("line3", 7531))
        self.assertIsNone(discovery.parse_answer(struct.pack(">HHHHHH", 1, 0x8400, 0, 0, 0, 0)))

    def test_cut_answer(self):
        data = _answer([RUNTIME])
        with self.assertRaises((ValueError, struct.error, IndexError)):
            discovery.parse_answers(data[:-3])

    def test_question_asks_for_a_unicast_answer(self):
        q = discovery._question()
        self.assertEqual(q[-4:], struct.pack(">HH", 12, 0x8001))
        self.assertIn(b"\x09_canworks\x04_tcp\x05local\x00", q)


class Browse(unittest.TestCase):
    def setUp(self):
        self.responder = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.responder.bind(("127.0.0.1", 0))
        self.addCleanup(self.responder.close)
        self.port = self.responder.getsockname()[1]

    def _serve(self, reply):
        """Answer each question with reply(question data) (None: stay silent) until closed."""
        def run():
            while True:
                try:
                    data, asker = self.responder.recvfrom(9000)
                except OSError:
                    return
                for packet in reply(data) or []:
                    self.responder.sendto(packet, asker)
        threading.Thread(target=run, daemon=True).start()

    def _browse(self, timeout=0.5):
        return discovery.browse(timeout, interfaces=LOOPBACK, group_v4="127.0.0.1", port=self.port)

    def test_runtime_and_adapter_server_at_the_source_address(self):
        self._serve(lambda q: [_answer([RUNTIME, ADAPTER])])
        found = self._browse()
        self.assertEqual([r["name"] for r in found], ["benchbox adapter slcan:0", "line3"])
        adapter, runtime = found
        # The source first, then the A record the answer carried.
        self.assertEqual(runtime["addresses"], ["127.0.0.1", "192.0.2.9"])
        self.assertEqual((runtime["kind"], runtime["diag"], runtime["runtime"], runtime["id"], runtime["link"]),
                         ("runtime", 7531, 8443, "abc", 7533))
        self.assertEqual((adapter["kind"], adapter["machine"], adapter["adapter"], adapter["bitrate"],
                          adapter["diag"]), ("adapter", "benchbox", "slcan:0", 500, 7536))

    def test_asks_twice_and_keeps_one_entry(self):
        questions = []

        def reply(q):
            questions.append(q)
            return [_answer([RUNTIME])]
        self._serve(reply)
        found = discovery.browse(1.3, interfaces=LOOPBACK, group_v4="127.0.0.1", port=self.port)
        self.assertEqual(len(questions), 2)
        self.assertEqual([r["name"] for r in found], ["line3"])

    def test_no_socket_is_bound(self):
        bound = []

        class Socket(socket.socket):
            def bind(self, *args):
                bound.append(args)
                return super().bind(*args)
        self._serve(lambda q: [_answer([RUNTIME])])
        with mock.patch.object(discovery.socket, "socket", Socket):
            found = self._browse()
        self.assertEqual(bound, [])
        self.assertEqual([r["name"] for r in found], ["line3"])

    def test_missing_srv_asks_the_host_directly(self):
        def reply(q):
            if struct.unpack(">H", q[-2:])[0] & 0x8000:      # the multicast question (QU)
                return [_answer([RUNTIME], srv=False)]
            return [_answer([RUNTIME])]                       # query_host's
        self._serve(reply)
        found = self._browse()
        self.assertEqual([(r["name"], r["diag"], r["id"]) for r in found], [("line3", 7531, "abc")])

    def test_nothing_answers(self):
        self._serve(lambda q: None)
        self.assertEqual(self._browse(0.2), [])

    def test_garbage_is_ignored(self):
        self._serve(lambda q: [b"\x00\x01junk", _answer([RUNTIME])])
        self.assertEqual([r["name"] for r in self._browse()], ["line3"])

    def test_an_interface_that_refuses_is_left_out(self):
        self._serve(lambda q: [_answer([RUNTIME])])
        found = discovery.browse(0.5, interfaces=[(socket.AF_INET, "not an address", 0)] + LOOPBACK,
                                 group_v4="127.0.0.1", port=self.port)
        self.assertEqual([r["name"] for r in found], ["line3"])


class Interfaces(unittest.TestCase):
    def test_no_loopback_and_one_ipv6_scope(self):
        class Ip:
            def __init__(self, ip):
                self.ip = ip

        class Adapter:
            def __init__(self, *ips):
                self.ips = [Ip(i) for i in ips]
        adapters = [Adapter("127.0.0.1", ("::1", 0, 1)),
                    Adapter("192.168.1.20", "169.254.3.4", ("fe80::1", 0, 7), ("fe80::2", 0, 7), ("fd00::5", 0, 0))]
        import ifaddr
        with mock.patch.object(ifaddr, "get_adapters", return_value=adapters):
            got = discovery._interfaces()
        self.assertEqual(got, [(socket.AF_INET, "192.168.1.20", 0), (socket.AF_INET, "169.254.3.4", 0),
                               (socket.AF_INET6, "fe80::1", 7)])


if __name__ == "__main__":
    unittest.main()
