## Context

The bridge's Modbus server (`plugin/src/bridge/modbus_server.cpp`) is one thread with `poll()`: it frames MBAP requests, applies the client limits and allowlists, and answers each PDU through `handle_pdu()` under one image access. Per client it keeps `ClientInfo` (address, request count, writer flag, queued and buffered bytes), which the bridge's status part lists.

The CAN trace (`can/diag.cpp`, `trace_capture.h`) is per network: a ring of 24-byte frame records, filled only while a client traces, fetched with `trace_start`/`trace_fetch`/`trace_stop`. On the PC, `bustrace/recorder.py` fetches into a session, `stats.py` builds the By identifier table, and `formats.py` saves pcapng (LINKTYPE 227, SocketCAN) and five other formats.

OpenPLC's Modbus master polls every group every 10 ms by default: a typical project sends 5 to 10 requests per poll, so 500 to 1000 requests per second whose answers rarely change.

## Goals / Non-Goals

**Goals:**
- Show, for each client, what it asked for and what it got, named with the register map, without a packet capture tool.
- Cost nothing while nobody watches, and little while someone does (no noticeable delay for OpenPLC's 10 ms poll on a Pi).
- Put Modbus and CAN on one timeline, so "the PLC wrote, then the RPDO went out" is visible.

**Non-Goals:**
- No Modbus-side triggers or graphs in this change (the CAN values the writes cause are already graphable).
- No capture of non-Modbus traffic, TCP handshakes or raw bytes of malformed requests (a malformed request is recorded as its exception with its first bytes).
- No change to what the server answers.

## Decisions

**1. Counters always on, in the server thread.** Each client gets per-function request counts (the functions served plus "other"), per-exception counts (0x01-0x04, 0x0B), refused writes (writes from a non-writer: exception 0x01 with a flag), the time, table and range of its last accepted write, and a reply rate over the last 5 s. They are plain integers updated in the server thread and copied under the existing `info_mu_` when the status asks. A closed connection moves to a list of the last 8, kept 10 minutes, with its close reason: `closed by the client`, `idle 60 s`, `incomplete request 5 s`, `replies not read`, `slot taken by a writer`, `per-address limit`, `not in readers`, `keepalive`. Alternative considered: count only on demand, rejected because the interesting moment ("why did my HMI drop at 03:12") is usually in the past.

**2. Trace ring in the bridge, variable-length records.** A read of 125 registers returns 250 bytes, and the decoding needs the values, so records carry their data: header (time in UTC microseconds, client slot and connection generation, transaction id, unit, function, table, start, count, exception code, flags, skipped count, data length) plus up to 250 data bytes (the values written, or the values read). The ring is 4 MiB of bytes, about 15000 full reads or far more small ones; fetches return at most 256 KiB. Records are written by the server thread after the answer is queued, so recording never delays an answer. Fixed 24-byte records like the CAN ring were rejected: they cannot hold the values.

**3. "Only changes" filtered in the bridge, not on the PC.** For each client and request kind (function, start, count) the recorder keeps a 64-bit hash of the last data; a request whose data hashes the same, and whose result is the same, is counted as skipped and not recorded. The next recorded one of that kind carries the skipped count, so the PC can show "×512 unchanged" and By request still counts every request. This keeps OpenPLC's 1000 requests/s to the few that change. `"changes_only": false` on `modbus_trace_start` records everything (for timing questions). Exceptions, refused writes, function 8 and 43 are always recorded. Filtering on the PC was rejected: it would move every request over the diagnostics channel, and remote links are slow.

**4. Operations follow the CAN trace's.** `modbus_trace_start` (`changes_only`, optional `clients`: addresses or prefixes) returns the next sequence number and the ring size; `modbus_trace_fetch` (`after`, `max` up to 4000 records) returns the records base64-packed with `lost` when the ring wrapped; `modbus_trace_stop`. A trace ends after 10 s without a fetch. Read-only: the token is enough, no `allow_changes`, because the CAN trace shows the same values. They take no network: Modbus is bridge-wide. A runtime that is not a bridge answers them with `not a bridge`. Alternative considered: a `source` field on `trace_start`, rejected because the CAN trace is per network and the records differ.

**5. One timeline on the PC.** The recorder runs both fetches in its loop when **Modbus requests** is ticked and puts both kinds into one session sorted by time. Both clocks are the bridge host's UTC (kernel receive time for CAN, `CLOCK_REALTIME` at the answer for Modbus), so they line up to well under a millisecond. Modbus records do not count in frames per second or bus load; the statistics line gets "N Modbus requests (M shown)".

**6. Names and hints from the register map.** `modbusmap.py` already computes the map the bridge serves. The decoder splits each record's range into the map's values (a 32-bit value across two registers in the config's word order, bits of a coil range as their bit names) and names the client from `bridge.connections` by address, else the address. Hints: exception 0x02 on a range past the image says the image size; a start of 30000 or more on input or 40000 or more on holding registers says Modbus addresses here start at 0; a range that cuts a 32-bit value in half says so; exception 0x01 on a write names `writers`. A record whose map hash differs from the config's (the bridge reports its hash at `modbus_trace_start`) is shown undecoded with a line saying the config on this PC is not the one the bridge runs.

**7. pcapng as IPv4/TCP.** The saved file gets a second interface block, LINKTYPE_IPV4 (228), and each record becomes one synthetic IPv4/TCP packet from the client's address to the bridge's port carrying the request's MBAP and PDU, followed by one back with the answer. Sequence numbers are made up per client so Wireshark's Modbus/TCP dissector decodes them. The canworks reader recognises its own packets by an option on the interface block and reads them back as records, with the skipped counts in a packet comment. Alternative considered: LINKTYPE_USER0 with the raw record, rejected because nothing but canworks could read it. ASC, BLF, TRC, candump and CSV keep CAN frames only; saving says "Modbus requests are kept in pcapng only".

**8. Clients panel.** The Modbus bridge page, while connected, polls the status once a second and shows one row per connection of the config (name, address, connected or not, requests per second, exceptions, refused writes, last write and its range by name) and one row per other client seen (**Not in connections**), with the recently closed ones under a disclosure. A connection with `writes` false whose client wrote gets its refused count in amber with a link to the connection's Settings.

**9. Delays matched on the PC from decoded values.** The bridge's trace stays dumb: the PC matches. A write's changed values (compared with that client's previous write of the same range) are looked up in the map to their binding. The decoder then finds the first frame after the write on the traced network whose decoded value of that binding equals the written one. A read goes backwards to the last frame that carried the value read. Matching by value, not just "the next RPDO", avoids blaming an RPDO that left before the bridge applied the write. The search stops after 1 s. By request keeps the minimum, average and maximum per request kind, so the bridge's added delay is a number in the table: the README's "up to one poll more each way" can be checked on a real bench. Alternative considered: the bridge stamps the snapshot it published and the frame it sent with it. That would be more exact, but it needs changes to the CAN thread for a figure the value match gives to well under a millisecond.

## Risks / Trade-offs

- [Recording cost on a Pi at 1000 requests/s] → hashing 250 bytes and a ring copy per request is a few microseconds; the HW check measures it with OpenPLC's master at a 10 ms poll, and the bridge's CPU must stay under 5 %.
- [Values of a whole image cross the diagnostics channel] → same exposure as the CAN trace, behind the same token and TLS.
- [Wireshark's dissector refuses packets without a handshake] → each client's stream starts with a synthetic SYN/SYN-ACK/ACK in the file; checked against tshark in the tests where tshark is installed.
- [Same value written twice in a row, or a value that equals the old one] → only changed values are matched; an unchanged write has no delay to show.
- [Clock steps on the bridge host (NTP)] → both kinds use the same clock, so a step moves both.

## Open Questions

- Should the counters also go into the HTML network docs' Modbus page as "what to check" text, or stay online only? Proposed: online only.
