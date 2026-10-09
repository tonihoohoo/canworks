"""Multi-frame views of a trace (canopen-bus-trace: "SDO conversations",
"SYNC cycle view", "Boot story"; canopen-frame-explain design D5).

All functions work on a trace (model.Trace) with the analysis' per-frame
kind codes (stats.Analysis.kinds), so only the frames that matter are
unpacked, and on the trace's decoder for names and values. Frame numbers
in the results are indexes into the trace (the caller adds trace.dropped
for absolute numbers).

- sdo_conversations(): every SDO transfer from its initiate request to the
  final answer or abort, with the raw bytes written or read;
- sync_cycles() / sync_cycle(): one row per SYNC period, and the frames of
  one period with their offsets;
- boot_stories(): per node, from boot-up (or a reset command) to its first
  PDO after the NMT start, with the master's writes compared to the writes
  the configuration makes at boot.
"""

from .. import diag
from .stats import KIND_CODE

SDO = KIND_CODE["sdo"]
SYNC = KIND_CODE["sync"]
PDO = KIND_CODE["pdo"]
NMT = KIND_CODE["nmt"]
HEARTBEAT = KIND_CODE["heartbeat"]
GAP = KIND_CODE["gap"]
MAX_CONVERSATIONS = 20000


def _obj(dec, nid, index, sub):
    eds = dec.eds.get(nid)
    name = None
    if eds is not None:
        parent, n = eds.object_name(index, sub)
        name = "%s / %s" % (parent, n) if parent and n and n != parent else (n or parent or None)
    return name


def _value_text(dec, nid, index, sub, data):
    t = dec.object_type(nid, index, sub)
    if t:
        return diag.decode(t, data)["text"]
    if 0 < len(data) <= 4:
        v = int.from_bytes(data, "little")
        return "%d (0x%0*X)" % (v, len(data) * 2, v)
    return diag.hex_bytes(data) or "(empty)"


class _Conv:
    def __init__(self, nid, index, sub, op, mode, i, f):
        self.nid, self.index, self.sub, self.op, self.mode = nid, index, sub, op, mode
        self.steps = []
        self.data = bytearray()
        self.size = None
        self.result = "open"
        self.abort = None
        self.last_seg = False
        self.phase = "init"
        self.start_i = i
        self.start_us = f.time_us
        self.end_us = f.time_us

    def step(self, i, f, server, text):
        prev = self.steps[-1]["t_us"] if self.steps else f.time_us
        self.steps.append({"index": i, "t_us": f.time_us, "dt_us": f.time_us - prev,
                           "from": "node" if server else "PLC", "text": text, "data": f.data_text(),
                           "id": f.id_text()})
        self.end_us = f.time_us

    def as_dict(self, dec, base=0):
        name = _obj(dec, self.nid, self.index, self.sub)
        value = None
        if self.result == "done":
            value = _value_text(dec, self.nid, self.index, self.sub, bytes(self.data))
        steps = [dict(s, seq=s["index"] + base) for s in self.steps]
        return {"seq": self.start_i + base, "node": self.nid, "node_label": dec.node_label(self.nid),
                "index": self.index, "subindex": self.sub, "object": "%04Xh:%02X" % (self.index, self.sub),
                "object_name": name, "op": self.op, "mode": self.mode, "result": self.result,
                "value": value, "data": diag.hex_bytes(bytes(self.data)), "size": len(self.data),
                "abort": self.abort, "abort_text": diag.abort_text(self.abort) if self.abort is not None else None,
                "frames": len(self.steps), "start_us": self.start_us, "end_us": self.end_us,
                "duration_us": self.end_us - self.start_us, "steps": steps}


def _step_text(d, server):
    """A short text for one SDO frame of a conversation."""
    if not d:
        return "empty frame"
    cmd, cs = d[0], d[0] >> 5
    if cs == 4:
        return "abort 0x%08X" % int.from_bytes(d[4:8], "little")
    if not server:
        return {1: "write request", 2: "read request", 0: "segment (t=%d%s)" % (cmd >> 4 & 1, ", last" if cmd & 1 else ""),
                3: "segment request (t=%d)" % (cmd >> 4 & 1), 5: "block read command", 6: "block write command"
                }.get(cs, "command 0x%02X" % cmd)
    return {3: "write accepted", 2: "read answer", 0: "segment (t=%d%s)" % (cmd >> 4 & 1, ", last" if cmd & 1 else ""),
            1: "segment confirmed (t=%d)" % (cmd >> 4 & 1), 5: "block write answer", 6: "block read answer"
            }.get(cs, "command 0x%02X" % cmd)


def sdo_conversations(trace, kinds, dec, nodes=None, base=0, limit=MAX_CONVERSATIONS):
    """[conversation dict], oldest first (at most `limit`, the newest kept)."""
    open_ = {}
    done = []

    def close(c, result):
        c.result = result
        done.append(c)
        open_.pop(c.nid, None)
        if len(done) > limit:
            del done[0]

    for i in range(len(kinds)):
        if kinds[i] != SDO:
            continue
        f = trace.frame(i)
        if f.rtr or f.ext or not f.data:
            continue
        server = f.can_id < 0x600
        nid = f.can_id & 0x7F
        if nodes and nid not in nodes:
            continue
        d = f.data.ljust(8, b"\0")
        cmd, cs = d[0], d[0] >> 5
        c = open_.get(nid)
        # a segment of a block transfer, from the side sending the data
        if c is not None and c.mode == "block" and c.phase == "data" and server == (c.op == "read") \
                and cmd != 0x80:
            c.step(i, f, server, "block segment %d%s" % (cmd & 0x7F, ", last" if cmd & 0x80 else ""))
            c.data += d[1:8]
            if cmd & 0x80:
                c.last_seg = True
            continue
        index, sub = int.from_bytes(d[1:3], "little"), d[3]
        if not server and (cs in (1, 2) or (cs == 6 and not cmd & 1) or (cs == 5 and cmd & 3 == 0)):
            if c is not None:
                close(c, "unanswered")
            op = "write" if cs in (1, 6) else "read"
            mode = "block" if cs in (5, 6) else "expedited"
            c = open_[nid] = _Conv(nid, index, sub, op, mode, i, f)
            c.phase = "init"
            if cs == 1:
                e, s = cmd >> 1 & 1, cmd & 1
                if e:
                    c.data += d[4:4 + (4 - (cmd >> 2 & 3) if s else 4)]
                else:
                    c.mode = "segmented"
                    c.size = int.from_bytes(d[4:8], "little") if s else None
            elif cs == 6 and cmd & 2:
                c.size = int.from_bytes(d[4:8], "little")
            c.step(i, f, server, _step_text(d, server))
            continue
        if c is None:
            continue
        c.step(i, f, server, _step_text(d, server))
        if cmd == 0x80:
            c.abort = int.from_bytes(d[4:8], "little")
            close(c, "aborted")
            continue
        if c.mode == "block":
            if cmd == 0xA2:  # a block received
                if c.last_seg:
                    c.phase = "end"
                continue
            if c.op == "write":
                if server and cs == 5 and c.phase == "init":
                    c.phase = "data"
                elif not server and cs == 6 and cmd & 1:
                    unused = cmd >> 2 & 7
                    if unused:
                        del c.data[len(c.data) - unused:]
                    c.phase = "done"
                elif server and cmd == 0xA1:
                    close(c, "done")
            else:
                if server and cs == 2:  # the server chose a normal upload
                    c.mode = "expedited"
                    if cmd & 2:
                        c.data += d[4:4 + (4 - (cmd >> 2 & 3) if cmd & 1 else 4)]
                        close(c, "done")
                    else:
                        c.mode = "segmented"
                        c.size = int.from_bytes(d[4:8], "little") if cmd & 1 else None
                elif server and cs == 6 and not cmd & 1 and c.phase == "init":
                    if cmd & 2:
                        c.size = int.from_bytes(d[4:8], "little")
                    c.phase = "start"
                elif not server and cmd == 0xA3:
                    c.phase = "data"
                elif server and cs == 6 and cmd & 1:
                    unused = cmd >> 2 & 7
                    if unused:
                        del c.data[len(c.data) - unused:]
                    c.phase = "done"
                elif not server and cmd == 0xA1:
                    close(c, "done")
            continue
        if c.op == "write":
            if server and cs == 3 and c.mode == "expedited":
                close(c, "done")
            elif not server and cs == 0:
                n = cmd >> 1 & 7
                c.data += d[1:8 - n]
                c.last_seg = bool(cmd & 1)
            elif server and cs == 1 and c.last_seg:
                close(c, "done")
        else:
            if server and cs == 2:
                e, s = cmd >> 1 & 1, cmd & 1
                if e:
                    c.data += d[4:4 + (4 - (cmd >> 2 & 3) if s else 4)]
                    close(c, "done")
                else:
                    c.mode = "segmented"
                    c.size = int.from_bytes(d[4:8], "little") if s else None
            elif server and cs == 0:
                n = cmd >> 1 & 7
                c.data += d[1:8 - n]
                if cmd & 1:
                    close(c, "done")
    out = [c.as_dict(dec, base) for c in done]
    out += [c.as_dict(dec, base) for c in open_.values()]
    out.sort(key=lambda c: c["seq"])
    return out


def conversation_at(convs, seq):
    """The conversation that holds frame `seq` (absolute), or None."""
    for c in convs:
        if any(s["seq"] == seq for s in c["steps"]):
            return c
    return None


# -- SYNC cycles ----------------------------------------------------------------

def sync_indexes(trace, kinds):
    return [i for i in range(len(kinds)) if kinds[i] == SYNC]


def _sync_pdo(dec, f):
    """(is a PDO, synchronous) for a frame."""
    p = dec.pdos.get(f.can_id) if not f.ext else None
    if p is None:
        return False, False
    t = p.transmission
    return True, t is not None and (t == 0 or 1 <= t <= 240)


def sync_cycles(trace, kinds, dec, base=0):
    """[{"n", "seq", "start_us", "period_us", "frames", "last_sync_pdo_us", "late"}] per SYNC."""
    syncs = sync_indexes(trace, kinds)
    window = dec.sync_window_us
    out = []
    for k, i in enumerate(syncs):
        end = syncs[k + 1] if k + 1 < len(syncs) else len(kinds)
        t0 = trace.times[i]
        last = None
        late = 0
        for j in range(i + 1, end):
            if kinds[j] != PDO:
                continue
            f = trace.frame(j)
            is_pdo, sync = _sync_pdo(dec, f)
            p = dec.pdos.get(f.can_id)
            if sync and p is not None and p.tx:
                dt = f.time_us - t0
                last = dt if last is None else max(last, dt)
                if window and dt > window:
                    late += 1
        out.append({"n": k, "seq": i + base, "start_us": t0,
                    "period_us": (trace.times[syncs[k + 1]] - t0) if k + 1 < len(syncs) else None,
                    "frames": end - i - 1, "last_sync_pdo_us": last, "late": late})
    return out


def sync_cycle(trace, kinds, dec, n, base=0):
    """The frames of SYNC period n with their offsets from the SYNC."""
    syncs = sync_indexes(trace, kinds)
    if not syncs:
        return None
    n = max(0, min(n, len(syncs) - 1))
    i = syncs[n]
    end = syncs[n + 1] if n + 1 < len(syncs) else len(kinds)
    t0 = trace.times[i]
    window = dec.sync_window_us
    rows = []
    for j in range(i, end):
        if kinds[j] == GAP:
            continue
        f = trace.frame(j)
        d = dec.clone().decode(f) if kinds[j] != SDO else None
        is_pdo, sync = _sync_pdo(dec, f)
        p = dec.pdos.get(f.can_id) if is_pdo else None
        if j == i:
            group = "sync"
        elif is_pdo and sync:
            group = "sync_pdo"
        elif kinds[j] == PDO:
            group = "pdo"
        elif kinds[j] == SDO:
            group = "sdo"
        else:
            group = "other"
        dt = f.time_us - t0
        row = {"seq": j + base, "offset_us": dt, "id": f.id_text(), "data": f.data_text(), "group": group,
               "name": d.name if d else "SDO", "text": d.text if d else f.data_text(), "tx": f.tx}
        if p is not None:
            row["pdo"] = p.name
            row["transmission"] = p.transmission
            row["direction"] = "TPDO" if p.tx else "RPDO"
            if sync and p.tx and window:
                row["in_window"] = dt <= window
        rows.append(row)
    return {"n": n, "count": len(syncs), "seq": i + base, "start_us": t0,
            "period_us": (trace.times[syncs[n + 1]] - t0) if n + 1 < len(syncs) else None,
            "window_us": window, "sync_period_us": dec.sync_period_us, "frames": rows}


def slowest_cycle(cycles):
    """The period whose last synchronous TPDO came latest after its SYNC."""
    best = None
    for c in cycles:
        if c["last_sync_pdo_us"] is None:
            continue
        if best is None or c["last_sync_pdo_us"] > best["last_sync_pdo_us"]:
            best = c
    return best


# -- boot stories ---------------------------------------------------------------

def boot_stories(trace, kinds, dec, expected=None, base=0, convs=None):
    """Per node and boot: [{"node", "seq", "start_us", "steps", "writes", "result"}].

    expected: {node: [(index, sub, data bytes, source)]}, the writes the
    configuration makes at boot (dcfexport.plugin_downloads)."""
    convs = convs if convs is not None else sdo_conversations(trace, kinds, dec, base=base)
    starts = []  # (index, node, how)
    nmt_start = []  # (index, target)
    for i in range(len(kinds)):
        k = kinds[i]
        if k == HEARTBEAT:
            f = trace.frame(i)
            if not f.rtr and f.data and f.data[0] == 0 and 0x701 <= f.can_id <= 0x77F:
                starts.append((i, f.can_id - 0x700, "boot-up"))
        elif k == NMT:
            f = trace.frame(i)
            if len(f.data) >= 2:
                if f.data[0] in (0x81, 0x82):
                    targets = [f.data[1]] if f.data[1] else sorted(dec.node_names)
                    for t in targets:
                        starts.append((i, t, "reset node" if f.data[0] == 0x81 else "reset communication"))
                elif f.data[0] == 0x01:
                    nmt_start.append((i, f.data[1]))
    stories = []
    by_node = {}
    for i, nid, how in starts:
        by_node.setdefault(nid, []).append((i, how))
    for nid, lst in by_node.items():
        # a reset followed by the node's boot-up is one boot
        merged = []
        for i, how in lst:
            if merged and how == "boot-up" and merged[-1][1].startswith("reset") and \
                    trace.times[i] - trace.times[merged[-1][0]] < 5_000_000:
                merged[-1] = (merged[-1][0], merged[-1][1] + ", boot-up")
                continue
            merged.append((i, how))
        for k, (i, how) in enumerate(merged):
            end = merged[k + 1][0] if k + 1 < len(merged) else len(kinds)
            stories.append(_story(trace, kinds, dec, nid, i, end, how, nmt_start, convs, expected, base))
    stories.sort(key=lambda s: s["seq"])
    return stories


def _story(trace, kinds, dec, nid, i, end, how, nmt_start, convs, expected, base):
    t0 = trace.times[i]
    steps = [{"seq": i + base, "t_us": t0, "dt_us": 0, "what": how, "text": "%s: %s" % (dec.node_label(nid), how)}]
    started = None
    for j, target in nmt_start:
        if i < j < end and target in (0, nid):
            started = j
            break
    result = "not started"
    end_j = end
    hb = pdo = None
    if started is not None:
        result = "started"
        for j in range(started + 1, end):
            if kinds[j] == HEARTBEAT and hb is None:
                f = trace.frame(j)
                if f.can_id == 0x700 + nid and f.data and f.data[0] & 0x7F == 5:
                    hb = j
            elif kinds[j] == PDO and pdo is None:
                f = trace.frame(j)
                p = dec.pdos.get(f.can_id)
                if p is not None and p.node == nid:
                    pdo = j
            if pdo is not None and hb is not None:
                break
        # The boot ends at its first PDO, else at the first heartbeat in
        # OPERATIONAL: later SDO traffic (SDO variables, the program) is
        # not part of it.
        if pdo is not None:
            end_j = pdo + 1
        elif hb is not None:
            end_j = hb + 1
    my_convs = [c for c in convs if c["node"] == nid and i + base <= c["seq"] < end_j + base]
    for c in my_convs:
        steps.append({"seq": c["seq"], "t_us": c["start_us"], "what": "sdo", "conversation": c["seq"],
                      "text": "%s %s%s: %s" % (
                          c["op"], c["object"], " " + c["object_name"] if c["object_name"] else "",
                          c["value"] if c["result"] == "done" else (c["abort_text"] or c["result"]))})
    if started is not None:
        steps.append({"seq": started + base, "t_us": trace.times[started], "what": "nmt",
                      "text": "NMT start %s" % ("all nodes" if trace.frame(started).data[1] == 0 else "node %d" % nid)})
        if hb is not None:
            steps.append({"seq": hb + base, "t_us": trace.times[hb], "what": "heartbeat",
                          "text": "first heartbeat in OPERATIONAL"})
            result = "operational"
        if pdo is not None:
            f = trace.frame(pdo)
            steps.append({"seq": pdo + base, "t_us": f.time_us, "what": "pdo",
                          "text": "first PDO: %s" % dec.pdos[f.can_id].name})
            result = "running"
    steps.sort(key=lambda s: s["seq"])
    prev = t0
    for s in steps:
        s["offset_us"] = s["t_us"] - t0
        s["dt_us"] = s["t_us"] - prev
        prev = s["t_us"]
    # The configuration's boot writes come before the NMT start; writes after
    # it come from SDO variables or the program, so they are not compared.
    boot_writes = [c for c in my_convs if c["op"] == "write" and (started is None or c["seq"] < started + base)]
    writes = _compare(dec, nid, boot_writes, (expected or {}).get(nid)) if expected is not None else None
    return {"node": nid, "node_label": dec.node_label(nid), "seq": i + base, "start_us": t0, "how": how,
            "result": result, "end_seq": end_j - 1 + base, "duration_us": trace.times[max(i, end_j - 1)] - t0,
            "steps": steps, "writes": writes,
            "summary": _summary(writes)}


def _summary(writes):
    if writes is None:
        return None
    out = {}
    for w in writes:
        out[w["status"]] = out.get(w["status"], 0) + 1
    return out


def _compare(dec, nid, done_writes, expected):
    """Expected boot writes against the trace's: ok, different, refused, missing, extra."""
    if expected is None:
        expected = []
    used = [False] * len(done_writes)
    out = []
    for index, sub, data, source in expected:
        match = None
        for k, c in enumerate(done_writes):
            if not used[k] and c["index"] == index and c["subindex"] == sub:
                match = k
                break
        name = _obj(dec, nid, index, sub)
        row = {"index": index, "subindex": sub, "object": "%04Xh:%02X" % (index, sub), "object_name": name,
               "source": source, "expected": diag.hex_bytes(data),
               "expected_text": _value_text(dec, nid, index, sub, bytes(data))}
        if match is None:
            row["status"] = "missing"
        else:
            used[match] = True
            c = done_writes[match]
            row["seq"] = c["seq"]
            row["actual"] = c["data"]
            if c["result"] == "aborted":
                row["status"] = "refused"
                row["abort_text"] = c["abort_text"]
            elif c["result"] != "done":
                row["status"] = "unanswered"
            elif bytes.fromhex(c["data"].replace(" ", "")) == bytes(data):
                row["status"] = "ok"
            else:
                row["status"] = "different"
                row["actual_text"] = c["value"]
        out.append(row)
    for k, c in enumerate(done_writes):
        if not used[k]:
            out.append({"index": c["index"], "subindex": c["subindex"], "object": c["object"],
                        "object_name": c["object_name"], "source": None, "seq": c["seq"],
                        "actual": c["data"], "actual_text": c["value"], "status": "extra"
                        if c["result"] == "done" else ("refused" if c["result"] == "aborted" else c["result"]),
                        "abort_text": c["abort_text"]})
    return out


def expected_writes(cfg, config_path, network=None, eds_paths=None):
    """{node: [(index, sub, data, source)]} the configuration writes at boot, or
    None when it cannot be computed (the reason is not needed here)."""
    from .. import contract, dcfexport
    try:
        c = contract.network_config(cfg, network)
        downloads = dcfexport.plugin_downloads(c, config_path, eds_paths)
    except Exception:  # noqa: BLE001 - any config problem: no comparison
        return None
    return {nid: [w + (s,) for w, s in zip(d.writes, d.sources)] for nid, d in downloads.items()}
