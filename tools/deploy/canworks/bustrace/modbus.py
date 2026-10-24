"""The bridge's Modbus records in a trace (canopen-bus-trace "Modbus records
in a trace", "Modbus decoding with the register map", "Delay between Modbus
and CAN", "Modbus records in saved traces").

A Record is one answered request as the bridge's recorder keeps it
(plugin/src/bridge/modbus_trace.h): the request and answer PDUs with the
time, client and the number of identical requests skipped before it. A
MapDecoder names the range with the config's register map and gives hints
for the usual mistakes; delays() finds the CAN frame that carried a written
value, or the one a read value came from; ByRequest is the By request table.

    dec = MapDecoder(cfg, network="field")
    row = dec.decode(record)   # {"client", "short", "range", "values", "result", "hints", "text", ...}
"""

import struct

from .. import modbusmap
from ..iec import CO_TYPES

HEAD = struct.Struct("<QQIIHBBHBBBx")  # 34 bytes
REFUSED = 1
DELAY_WINDOW_US = 1_000_000

FUNCTIONS = {1: "read coils", 2: "read discrete inputs", 3: "read holding registers", 4: "read input registers",
             5: "write single coil", 6: "write single register", 8: "diagnostics", 15: "write multiple coils",
             16: "write multiple registers", 23: "read/write multiple registers", 43: "read device identification"}
WRITES = (5, 6, 15, 16, 23)
EXCEPTIONS = {1: "illegal function", 2: "illegal data address", 3: "illegal data value", 4: "server device failure",
              0x0B: "gateway target device failed to respond"}
TABLES = {1: "coil", 2: "discrete input", 3: "holding register", 4: "input register", 5: "coil",
          6: "holding register", 15: "coil", 16: "holding register", 23: "holding register"}
SHORT = {"coil": "CO", "discrete input": "DI", "holding register": "HR", "input register": "IR"}


def _be16(b, at):
    return (b[at] << 8) | b[at + 1] if len(b) >= at + 2 else None


def _bits(data, count):
    return [bool(data[k // 8] >> (k % 8) & 1) for k in range(min(count, len(data) * 8))]


class Record:
    __slots__ = ("time_us", "seq", "conn", "skipped", "transaction", "unit", "flags", "port", "address", "req",
                 "resp")

    def __init__(self, time_us, address, req, resp, seq=0, conn=0, skipped=0, transaction=0, unit=1, flags=0,
                 port=0):
        self.time_us, self.seq, self.conn, self.skipped = int(time_us), seq, conn, skipped
        self.transaction, self.unit, self.flags, self.port = transaction, unit, flags, port
        self.address, self.req, self.resp = address, bytes(req), bytes(resp)

    def pack(self):
        a = self.address.encode()[:63]
        return HEAD.pack(self.time_us, self.seq, self.conn, self.skipped, self.transaction, self.unit, self.flags,
                         self.port, len(a), len(self.req), len(self.resp)) + a + self.req + self.resp

    @classmethod
    def unpack_all(cls, data):
        out, i = [], 0
        while i + HEAD.size <= len(data):
            t, seq, conn, skipped, tid, unit, flags, port, alen, qlen, plen = HEAD.unpack_from(data, i)
            i += HEAD.size
            a = data[i:i + alen].decode("utf-8", "replace")
            req = data[i + alen:i + alen + qlen]
            resp = data[i + alen + qlen:i + alen + qlen + plen]
            i += alen + qlen + plen
            out.append(cls(t, a, req, resp, seq, conn, skipped, tid, unit, flags, port))
        return out

    # -- what the PDUs say ----------------------------------------------------
    @property
    def function(self):
        return self.req[0] if self.req else 0

    @property
    def exception(self):
        """The exception code, or None for a normal answer."""
        return self.resp[1] if len(self.resp) >= 2 and self.resp[0] & 0x80 else None

    @property
    def refused(self):
        return bool(self.flags & REFUSED)

    @property
    def is_write(self):
        return self.function in WRITES

    @property
    def table(self):
        return TABLES.get(self.function)

    def ranges(self):
        """[(table, start, count, data, written)]: what the request names and
        the values that went each way (register bytes, or bools for bits).
        The data is None when the answer is an exception."""
        fn, q, p = self.function, self.req, self.resp
        ok = self.exception is None
        if fn in (1, 2, 3, 4) and len(q) >= 5:
            start, count = _be16(q, 1), _be16(q, 3)
            data = None
            if ok and len(p) >= 2:
                data = _bits(p[2:], count) if fn in (1, 2) else p[2:2 + count * 2]
            return [(TABLES[fn], start, count, data, False)]
        if fn == 5 and len(q) >= 5:
            return [("coil", _be16(q, 1), 1, [q[3] == 0xFF] if ok else None, True)]
        if fn == 6 and len(q) >= 5:
            return [("holding register", _be16(q, 1), 1, q[3:5] if ok else None, True)]
        if fn in (15, 16) and len(q) >= 6:
            start, count = _be16(q, 1), _be16(q, 3)
            data = (_bits(q[6:], count) if fn == 15 else q[6:6 + count * 2]) if ok else None
            return [(TABLES[fn], start, count, data, True)]
        if fn == 23 and len(q) >= 10:
            rs, rc, ws, wc = _be16(q, 1), _be16(q, 3), _be16(q, 5), _be16(q, 7)
            return [("holding register", ws, wc, q[10:10 + wc * 2] if ok else None, True),
                    ("holding register", rs, rc, p[2:2 + rc * 2] if ok and len(p) >= 2 else None, False)]
        return []

    def __repr__(self):
        return "Record(%d, %s, fn %d, %s)" % (self.time_us, self.address, self.function,
                                               "exception 0x%02X" % self.exception if self.exception else "ok")


def range_text(start, count):
    return str(start) if count <= 1 else "%d-%d" % (start, start + count - 1)


def _row_value(row, raw, word_order):
    """A map row's value from its bytes as the bridge serves them."""
    t = row["type"]
    if t == "BLOCK":
        return raw.hex(" ").upper()
    n = len(raw)
    if n >= 4 and word_order == "low_first":
        words = [raw[k:k + 2] for k in range(0, n, 2)]
        raw = b"".join(reversed(words))
    if t == "REAL32" and n == 4:
        return struct.unpack(">f", raw)[0]
    if t == "REAL64" and n == 8:
        return struct.unpack(">d", raw)[0]
    v = int.from_bytes(raw, "big")
    bits = CO_TYPES[t][1] if t in CO_TYPES else n * 8
    v &= (1 << bits) - 1 if bits < n * 8 else (1 << (n * 8)) - 1
    if t.startswith("INTEGER") and v >> (bits - 1) & 1:
        v -= 1 << bits
    return v


def value_text(v):
    if isinstance(v, bool):
        return "TRUE" if v else "FALSE"
    if isinstance(v, float):
        return "%g" % v
    return str(v)


# The bit table whose bits a register table serves too.
BITS_IN = {"holding register": "coil", "input register": "discrete input"}


class MapDecoder:
    """Names Modbus records with a config's register map. Without a bridge
    config (or with one whose map cannot be laid out) the records show
    undecoded."""

    def __init__(self, cfg=None, network=None, bridge_hash=None):
        self.rows, self.problem = [], None
        self.inputs = self.outputs = None
        self.word_order = "high_first"
        self.names = {}
        self.network = network
        self.map_hash = None
        self.bridge_hash = bridge_hash
        if not cfg or not modbusmap.is_bridge_config(cfg):
            self.problem = "no bridge config: the Modbus records are not named"
            return
        try:
            self.rows = modbusmap.register_map(cfg)
            self.inputs, self.outputs = modbusmap.image_sizes(self.rows)
            self.word_order = modbusmap.word_order_of(cfg)
            self.map_hash = "0x%08x" % modbusmap.map_hash(cfg)
        except (modbusmap.MapError, AttributeError, KeyError, TypeError, ValueError) as e:
            self.rows, self.problem = [], "the config's register map cannot be laid out (%s)" % e
        for c in (cfg.get("bridge") or {}).get("connections") or []:
            if isinstance(c, dict) and c.get("address") and c.get("name"):
                self.names.setdefault(str(c["address"]), c["name"])
        self.writers = (cfg.get("bridge") or {}).get("writers")

    def set_bridge_hash(self, h):
        self.bridge_hash = h

    @property
    def mismatch(self):
        """The line saying the config is not the one the bridge runs, or None."""
        if self.bridge_hash and self.map_hash and self.bridge_hash.lower() != self.map_hash.lower():
            return ("the config on this PC (map hash %s) is not the one the bridge runs (%s): the Modbus records "
                    "are shown undecoded" % (self.map_hash, self.bridge_hash))
        return None

    def client(self, rec):
        return self.names.get(rec.address) or rec.address

    def image_registers(self, table):
        n = self.inputs if table in ("input register", "discrete input") else self.outputs
        if n is None:
            return None
        return n * 8 if table in ("coil", "discrete input") else n // 2

    def values(self, table, start, count, data):
        """[{name, location, type, value, row, split}] for the map rows in a
        range. `split`: the range covers only part of the value."""
        out = []
        if self.mismatch or not self.rows or start is None or count is None:
            return out
        end = start + count
        bits = BITS_IN.get(table)
        for r in self.rows:
            if bits and r["table"] == bits:
                # A bit's byte n is served in register n // 2 too (even n the
                # high byte): name it in a register range as well.
                a = r["byte"] // 2
                if not start <= a < end:
                    continue
                v = {"name": r["name"], "location": r["location"], "type": r["type"], "row": r, "split": False,
                     "value": None}
                off = (a - start) * 2 + (r["byte"] % 2)
                if data is not None and off < len(data):
                    v["value"] = bool(data[off] >> (r["address"] % 8) & 1)
                out.append(v)
                continue
            if r["table"] != table:
                continue
            a, n = r["address"], r["count"]
            if a + n <= start or a >= end:
                continue
            v = {"name": r["name"], "location": r["location"], "type": r["type"], "row": r,
                 "split": a < start or a + n > end, "value": None}
            if data is not None and not v["split"]:
                if table in ("coil", "discrete input"):
                    k = a - start
                    v["value"] = data[k] if k < len(data) else None
                else:
                    off = (a - start) * 2
                    if r.get("byte_in_register"):
                        off += 1 if r["byte_in_register"] == "low" else 0
                        raw = data[off:off + 1]
                    else:
                        raw = data[off:off + n * 2]
                    if len(raw) == (1 if r.get("byte_in_register") else n * 2):
                        v["value"] = _row_value(r, bytes(raw), r.get("word_order") or self.word_order)
            out.append(v)
        return out

    def hints(self, rec):
        out = []
        fn, ex = rec.function, rec.exception
        for table, start, count, _, written in rec.ranges():
            if start is None:
                continue
            if table == "input register" and start >= 30000 or table == "holding register" and start >= 40000:
                notation = "3xxxx" if table == "input register" else "4xxxx"
                n = self.image_registers(table)
                out.append("%ss start at 0 here: %d looks like %s notation (%d is %s %d)%s" % (
                    table.capitalize(), start, notation, start, table, max(0, start - (30001 if notation == "3xxxx" else 40001)),
                    "; the image has %d %ss" % (n, table) if n is not None else ""))
            elif ex == 2:
                n = self.image_registers(table)
                if n is not None and start + count > n:
                    out.append("past the image: it has %d %ss (%s 0-%d)" % (n, table, table, max(n - 1, 0)))
            for v in self.values(table, start, count, None):
                if v["split"]:
                    out.append("the range cuts %s (%s %s) in part; read or write all %d registers of it at once" % (
                        v["name"], SHORT[table], range_text(v["row"]["address"], v["row"]["count"]),
                        v["row"]["count"]))
        if ex == 1 and (rec.refused or fn in WRITES):
            out.append("this client may not write: its address %s is not in the bridge's writers%s" % (
                rec.address, " (%s)" % ", ".join(self.writers) if isinstance(self.writers, list) and self.writers
                else ""))
        return out

    def decode(self, rec):
        """The row of a record for the trace view and the command line."""
        fn = rec.function
        parts, values = [], []
        for table, start, count, data, written in rec.ranges():
            vs = self.values(table, start, count, data)
            values += [{"name": v["name"], "location": v["location"], "type": v["type"], "value": v["value"],
                        "text": "?" if v["value"] is None else value_text(v["value"]), "written": written,
                        "network": v["row"].get("network") or ""}
                       for v in vs if not v["split"]]
            named = ", ".join("%s = %s" % (v["name"], "?" if v["value"] is None else value_text(v["value"]))
                              for v in vs if not v["split"])
            raw = ""
            if not named and data is not None:
                raw = " ".join(("1" if b else "0") for b in data) if table in ("coil", "discrete input") else \
                    " ".join("%04X" % _be16(data, k) for k in range(0, len(data) - 1, 2))
            parts.append(("%s %s %s" % ("write" if written else "read", SHORT.get(table, table),
                                        range_text(start, count)) + (" " + (named or raw) if (named or raw) else "")))
        ex = rec.exception
        if ex is not None:
            result = "exception 0x%02X (%s)" % (ex, EXCEPTIONS.get(ex, "unknown"))
            if rec.refused:
                result += ", refused write"
        else:
            result = "ok"
        if not parts:
            parts.append(FUNCTIONS.get(fn, "function %d" % fn))
        rngs = rec.ranges()
        text = "; ".join(parts) + ("" if ex is None else " -> " + result)
        return {"time_us": rec.time_us, "seq": rec.seq, "client": self.client(rec), "address": rec.address,
                "port": rec.port, "unit": rec.unit, "transaction": rec.transaction, "function": fn,
                "function_name": FUNCTIONS.get(fn, "function %d" % fn), "table": rngs[0][0] if rngs else None,
                "short": SHORT.get(rngs[0][0]) if rngs else None,
                "start": rngs[0][1] if rngs else None, "count": rngs[0][2] if rngs else None,
                "range": range_text(rngs[0][1], rngs[0][2]) if rngs and rngs[0][1] is not None else "",
                "write": rec.is_write, "values": values, "result": result, "exception": ex, "refused": rec.refused,
                "skipped": rec.skipped, "hints": self.hints(rec), "text": text,
                "request": rec.req.hex(" ").upper(), "answer": rec.resp.hex(" ").upper(),
                "undecoded": self.mismatch}

    def kind(self, rec):
        """The By request row a record counts in: client, function, range."""
        rngs = rec.ranges()
        return (rec.address, rec.function,) + tuple((t, s, c) for t, s, c, _, _ in rngs)


# ---------------------------------------------------------------------------
# Delays (canopen-bus-trace "Delay between Modbus and CAN")

def signal_keys_by_location(decoder):
    """{%Q/%I location: CAN decoder signal key} of the traced network's PDO
    entries and raw message signals."""
    out = {}
    for p in list(getattr(decoder, "pdos", {}).values()):
        for sig, info in zip(p.signals, p.info or []):
            loc = ((info or {}).get("location") or "").strip().rstrip(";")
            if loc:
                out.setdefault(loc.upper(), (sig[0], p.name))
    raw = getattr(decoder, "raw", None)
    for _, m in (raw.entries if raw is not None else []):
        mname = m.get("name") or "0x%X" % m["id"]
        for j, sg in enumerate(m.get("signals") or []):
            loc = sg.get("iec_location") if isinstance(sg, dict) else None
            if loc:
                out.setdefault(loc.upper(), ("%s.%s" % (mname, sg.get("name") or "s%d" % j), mname))
    return out


def _same(a, b):
    if isinstance(a, float) or isinstance(b, float):
        return abs(float(a) - float(b)) <= 1e-6 * max(1.0, abs(float(a)))
    return int(a) == int(b)


def delays(trace, decoder, values, rec_time_us, written, network=None, window_us=DELAY_WINDOW_US):
    """Per value {name, delay_us, frame (absolute frame number), text}: for a
    write the first frame after it on the traced network carrying the new
    value, for a read the frame that first carried the value read (the start
    of its run before the read)."""
    keys = signal_keys_by_location(decoder)
    out = []
    dec = decoder.clone()
    for v in values:
        entry = {"name": v["name"], "location": v["location"], "delay_us": None, "frame": None}
        net = v.get("network") or ""
        if network and net and net != network:
            entry["text"] = "on %s, not traced" % net
            out.append(entry)
            continue
        key = keys.get(v["location"].upper())
        if key is None or v["value"] is None or isinstance(v["value"], str):
            entry["text"] = "not decoded on this network"
            out.append(entry)
            continue
        skey, msg = key
        found = None
        if written:
            a, b = trace.range(rec_time_us, rec_time_us + window_us)
            for i in range(a, b):
                f = trace.frame(i)
                if f.modbus or f.gap or f.err:
                    continue
                d = dec.decode(f)
                for k, val in d.signals:
                    if k == skey and _same(val, v["value"]):
                        found = (i, f.time_us - rec_time_us)
                        break
                if found:
                    break
        else:
            a, b = trace.range(rec_time_us - window_us, rec_time_us)
            first = None
            for i in range(b - 1, a - 1, -1):
                f = trace.frame(i)
                if f.modbus or f.gap or f.err:
                    continue
                d = dec.decode(f)
                hit = [val for k, val in d.signals if k == skey]
                if not hit:
                    continue
                if _same(hit[0], v["value"]):
                    first = (i, rec_time_us - f.time_us)
                    continue
                break
            found = first
        if found:
            entry["frame"] = found[0] + trace.dropped
            entry["delay_us"] = found[1]
            entry["text"] = "%.1f ms %s %s" % (found[1] / 1000.0, "to" if written else "from", msg)
        else:
            entry["text"] = "not seen on the bus"
        out.append(entry)
    return out


class ByRequest:
    """The By request table: one row per client, function and range, fed in
    time order (skipped requests count too)."""

    def __init__(self):
        self.rows = {}

    def feed(self, rec, decoded):
        key = (rec.address,) + tuple(decoded["kind"]) if "kind" in decoded else (rec.address, rec.function)
        r = self.rows.get(key)
        n = 1 + rec.skipped
        if r is None:
            r = self.rows[key] = {"client": decoded["client"], "address": rec.address, "function": rec.function,
                                  "function_name": decoded["function_name"], "short": decoded["short"],
                                  "range": decoded["range"], "count": 0, "records": 0, "first_us": rec.time_us,
                                  "last_us": rec.time_us, "exceptions": 0, "last_exception": None,
                                  "values": [], "delays": []}
        r["count"] += n
        r["records"] += 1
        r["last_us"] = rec.time_us
        if decoded["exception"] is not None:
            r["exceptions"] += n
            r["last_exception"] = decoded["result"]
        elif decoded["values"]:
            r["values"] = [{"name": v["name"], "text": v["text"]} for v in decoded["values"]]
        r["hints"] = decoded["hints"]

    def add_delay(self, key, delay_us):
        r = self.rows.get(key)
        if r is not None:
            r["delays"].append(delay_us)

    def table(self):
        out = []
        for r in sorted(self.rows.values(), key=lambda r: (r["client"], r["function"], r["range"])):
            row = {k: v for k, v in r.items() if k != "delays"}
            span = r["last_us"] - r["first_us"]
            row["cycle_avg_ms"] = span / 1000.0 / (r["count"] - 1) if r["count"] > 1 and span > 0 else None
            d = r["delays"]
            row["delay_min_ms"] = min(d) / 1000.0 if d else None
            row["delay_avg_ms"] = sum(d) / len(d) / 1000.0 if d else None
            row["delay_max_ms"] = max(d) / 1000.0 if d else None
            out.append(row)
        return out


def decode_all(mapdec, trace, decoder=None, network=None):
    """Every record of a trace decoded, with each changed value's delay
    (against that client's previous record of the same kind), and the By
    request table."""
    by = ByRequest()
    last = {}
    rows = []
    for rec in trace.modbus:
        d = mapdec.decode(rec)
        d["kind"] = [str(x) for x in mapdec.kind(rec)[1:]]
        k = mapdec.kind(rec)
        prev = last.get(k)
        changed = [v for v in d["values"] if prev is None or prev.get(v["location"]) != v["value"]]
        last[k] = {v["location"]: v["value"] for v in d["values"]}
        d["delays"] = []
        if decoder is not None and changed and d["exception"] is None:
            for written in (True, False):
                part = [v for v in changed if v["written"] == written]
                if part:
                    d["delays"] += delays(trace, decoder, part, rec.time_us, written, network)
        by.feed(rec, d)
        for x in d["delays"]:
            if x["delay_us"] is not None:
                by.add_delay((rec.address,) + tuple(d["kind"]), x["delay_us"])
        rows.append(d)
    return rows, by.table()
