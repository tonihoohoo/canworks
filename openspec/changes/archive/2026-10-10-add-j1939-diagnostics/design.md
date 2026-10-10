## Context

A J1939 network (`j1939-ecu`) runs on the kernel's `CAN_J1939` sockets: one promiscuous receive socket with a PGN filter, one ECU socket bound to the claimed address. The kernel reassembles and sends the transport protocol (BAM, RTS/CTS, up to 1785 bytes), so a DM1 with many trouble codes arrives as one message and our own long DM1 goes out with one `send`. `J1939Engine` (`plugin/src/j1939/j1939_network.*`) handles claim, `rx`/`tx`, requests (with the 50 ms reply gate) and status; `J1939Image` moves values through triple buffers.

The PLC reaches the plugin from library blocks through `dlopen("libcanworks_plugin.so", RTLD_NOLOAD)` and a versioned function table (`canworks_can_api(1)` for the frame blocks, the SDO table for the SDO blocks). The PC tools already depend on can-j1939 2.0.12, which has `DTC`, `DtcLamp`, `Dm1` and `Dm11`; DM2, DM3 and DM22 have no classes there but share DM1's layout or are a bare Request.

Decisions from the exploration (Toni, 2026-10-10): both directions in one change, config mapping and blocks, DM13 in, after `add-multiplexed-signals`.

## Goals / Non-Goals

**Goals:**
- A program sees other ECUs' lamps and trouble codes without ST code (mapping), and the full list when it wants it (blocks).
- A PLC acting as an ECU reports faults the way J1939 service tools expect: DM1 every second, DM2 on request, DM3/DM11 clears acknowledged.
- PC tools list, read and clear codes through the PLC or straight from a USB adapter; trace and simulator speak DMs.

**Non-Goals:**
- Freeze frames, emissions DMs, memory access, sending DM22, persistence (see proposal).
- SPN and FMI catalogues from SAE J1939DA. FMI texts (0..31) are written in our own words; SPN names come only from the user's DBC.
- Older SPN conversion methods (CM bit set) beyond decoding them as version 4 and saying so.

## Decisions

### 1. Config shape: `j1939.diagnostics`

```json
"diagnostics": {
  "rx": [ { "source": 0, "status_location": "%IX220.0", "lamps_location": "%IB221",
            "count_location": "%IB222", "dtcs_location": "%ID56", "dtcs": 4 } ],
  "dtcs": [ { "spn": 520192, "fmi": 3, "active_location": "%QX230.0", "lamps": ["amber"] },
            { "spn": 520193, "fmi": 1, "active_location": "%QX230.1", "lamps": ["red"], "flash": "fast" } ],
  "lamps_location": "%QB231",
  "clear_location": "%IB232",
  "accept_clear": true,
  "dm13": true
}
```

- `rx[]`: `source` (0..253) or `source_name` + `source_name_mask` (as on `j1939.rx`), `timeout_ms` (default 3000, 0 = none), `status_location` (%IX), `lamps_location` (%IB), `flash_location` (%IB), `count_location` (%IB), `dtcs_location` (%ID) with `dtcs` 1..32. Every location is optional, at least one is required. One entry per source filter.
- `dtcs[]`: `spn` 0..524287, `fmi` 0..31, `active_location` (%QX), `lamps` (subset of `mil`, `red`, `amber`, `protect`), `flash` (`slow` | `fast`, default none). `(spn, fmi)` unique.
- `lamps_location` (%QB): lamp bits in the wire layout, ORed with the lamps of the active codes.
- `clear_location` (%IB): counts accepted clears (wraps at 255), so the program can reset latched faults on a change.
- `accept_clear` default true; `dm13` default true.

*Alternative:* a separate top-level `dm` object. Rejected: diagnostics belong to one J1939 network and its address.

### 2. One DTC in one `UDINT`

The wire layout splits the SPN over three bytes. The PLC gets a repacked value:

`DTC = SPN + FMI * 2^19 + OC * 2^24 + CM * 2^31`

so `SPN := DTC AND 16#7FFFF`, `FMI := (DTC SHR 19) AND 31`, `OC := (DTC SHR 24) AND 127`. `J1939_DTC_SPLIT` and `J1939_DTC_MAKE` do this in ST. `dtcs_location` `%IDn` takes `dtcs` consecutive double words (`%IDn`, `%IDn+1`, ...), in the order of the message; unused slots read 0. A DM1 that says "no codes" (one all-zero code) gives count 0.

`lamps_location` holds byte 1 of the message unchanged (MIL bits 7-6, red stop 5-4, amber 3-2, protect 1-0; 00 off, 01 on), `flash_location` byte 2. The same layout is used for `%QB` `lamps_location`, so one set of constants serves both.

### 3. Receive store

The network always adds PGN 65226 (DM1) to its receive filter, and 65227 (DM2) plus 59392 (ACK) while a DM2 read or a clear is pending. Per source address it keeps the lamps, flash byte, the code list (the first 64 codes; more are counted as `truncated`, a DM1 can carry up to 445), the time of the last DM1 and a change counter. Mapped `rx` entries copy from this store into the image on each DM1; on `timeout_ms` without a DM1 the status bit goes FALSE and values hold, the same rule as `j1939.rx`. Sources not mapped are still kept (bounded: 254 addresses), for diagnostics and the blocks.

A code with CM set is stored as received, counted per source in diagnostics (`old_spn_format`) and logged once per source.

### 4. Sending own DM1

Active when `dtcs` is non-empty or `lamps_location` is set. While claimed and not suspended by DM13:
- every 1000 ms, and once within one scan after the active set or the lamps change, but at most one change-driven send per 1000 ms (J1939-73)
- an occurrence count per code increases on each FALSE→TRUE of its `active_location`, up to 126, and starts at 0 at plugin start
- a code that goes inactive moves to the previously active list (deduplicated by SPN/FMI, keeping its count)
- with no active codes the message carries the lamps and one all-zero code with bytes 7-8 0xFF
- priority 6, global, length 2 + 4 × codes (minimum 8), TP by the kernel above 8

The send uses the existing `send()` path, so a refused send stays pending (`Failed sends stay pending`).

### 5. Requests and clears

- Request for DM1 or DM2 (to us or global): answered with the current list, through the 50 ms reply gate.
- Request for DM3 (to us): clears the previously active list and answers ACK. Request for DM11 (to us): clears the previously active list and every occurrence count, answers ACK; codes whose bit is still TRUE stay active with count 1. Global DM3/DM11: same action, no ACK (J1939-73).
- Each accepted clear increments `clear_location`.
- `accept_clear: false`: requests to us answered with NACK, global ignored.
- DM22 commands addressed to us are answered with DM22's negative acknowledgement ("not supported").
- Without `dtcs` and `lamps_location` the network does not claim DM1/DM2/DM3/DM11 and the existing "unknown PGN → NACK" rule applies.

### 6. DM13

With `dm13` true, a DM13 (PGN 57088) to us or global whose "current data link" field says stop suspends DM1 and every `tx` entry with `period_ms` > 0 (on-change and request answers keep working, as do claims). Broadcasts resume on "start" for the current data link, or 6 s after the last DM13 stop or hold. `diagnostics` status shows the suspension. The exact field values (2-bit codes, suspend signal) follow J1939-73 and are tested against the trace fixtures.

*Alternative:* honour DM13 only for DM1. Rejected: the point of DM13 is a quiet bus for flashing.

### 7. PLC interface: `canworks_j1939_api(1)`

A separate exported symbol, not version 2 of `canworks_can_api`, so the frame blocks' table never changes for J1939. Same rules as the frame table: called on the PLC thread, never waits, allocates or logs; handles per block instance.

```c
uint32_t (*dm_read_start)(uint8_t network, uint8_t source, uint8_t previous, uint32_t timeout_ms, uint16_t* error_id);
int      (*dm_read_poll)(uint32_t handle, canworks_j1939_dm* out, uint16_t* error_id);  /* 0 wait, 1 done, 2 error */
uint32_t (*dm_clear_start)(uint8_t network, uint8_t destination, uint8_t previous_only, uint32_t timeout_ms, uint16_t* error_id);
int      (*dm_clear_poll)(uint32_t handle, uint16_t* error_id);
void     (*cancel)(uint32_t handle);
```

`canworks_j1939_dm` holds lamps, flash, count, and up to 32 codes in the `UDINT` form. A DM1 read copies the store (done on the next call, no bus traffic); a DM2 read sends a Request and waits for the answer.

### 8. Block pins and error IDs

- `J1939_DM_READ`: in `EXECUTE`, `NETWORK : USINT`, `SOURCE : USINT`, `PREVIOUS : BOOL`, `TIMEOUT : TIME`; in-out `DTCS : ARRAY[0..31] OF UDINT`; out `BUSY`, `DONE`, `ERROR`, `ERROR_ID : UINT`, `LAMPS : BYTE`, `FLASH : BYTE`, `COUNT : UINT` (all codes in the message, may exceed 32), `AGE : TIME` (DM1 only).
- `J1939_DM_CLEAR`: in `EXECUTE`, `NETWORK`, `DESTINATION : USINT` (255 global), `PREVIOUS_ONLY : BOOL` (TRUE DM3, FALSE DM11), `TIMEOUT`; out `BUSY`, `DONE`, `ERROR`, `ERROR_ID`.
- Handshake as `CAN_SEND` / the SDO blocks. `TIMEOUT` `T#0s` = 1 s.
- Error IDs reuse the frame blocks' numbers where they mean the same (1 not running, 2 no such network, 3 invalid input, 5 another read or clear for that address is pending, 6 timeout, 7 bus, 8 cancelled) and add: 10 the network is not J1939, 11 not claimed (no address to send from), 12 NACK from the destination, 13 no DM1 seen from that source.

### 9. Diagnostics channel

The J1939 status gains `dm`: per source the lamps, codes (SPN, FMI, OC, CM), seconds since the last DM1 and `old_spn_format`; own active and previous lists with counts, suspension by DM13, clears accepted. New operations `j1939_dm_read` (DM2 of an address, through the PLC's address) and `j1939_dm_clear` (DM3/DM11). Clears need `force`, like SDO writes on a running network, because they act on another ECU. Both go through the same pending-request machinery as the blocks, so a block and a tool cannot both wait for the same answer: the second gets "busy".

### 10. PC tools

- One codec, `canworks/j1939/dm.py`: parse and build DM1/DM2, lamps text, FMI texts (own words), DTC ↔ `UDINT`. Used by the trace, `canworks-diag`, the simulator and the configurator; tested against byte fixtures shared with the plugin tests.
- `canworks-diag dm list` (status answer, or on a local adapter: listen 1.5 s), `dm read --address N` (DM2), `dm clear --address N [--previous] --force`. On a local adapter the tool claims 249 (off-board service tool) with a NAME of its own (`--address` to change), using can-j1939, and releases it at exit.
- DBC import: messages with DM PGNs (65226-65236, 57088, 49920) are listed as problems "diagnostic message: use diagnostics" and not added as `rx`/`tx`.
- Declarations: `<network>_dm_<source>_lamps`, `_count`, `_status`, and one `UDINT` per slot `_dtc0`, `_dtc1`, ... (located variables cannot be arrays), own codes `<network>_dtc_<spn>_<fmi> AT %QX...`.

### 11. Trace

DM1 and DM2 show the lamps (`MIL off, amber on`) and each code as `SPN 520192 FMI 3 (voltage above normal) OC 2`, with the SPN's name when the DBC has a signal with that SPN (`SPN` attribute). DM3, DM11 as named requests; their ACK/NACK; DM13 with the per-link commands; DM22 with its control byte. Component ID (65249) and Software ID (65242) as text fields split at `*`. The frame inspector explains the four DTC bytes bit by bit.

## Risks / Trade-offs

- [DM13 field details] → test against J1939-73 field tables during apply; the behaviour is narrow (suspend/resume) and the fixtures pin it.
- [A clear from a tool reaches a real machine] → `force` on the diag channel and a confirmation in the configurator; the PLC block is the program's own decision.
- [History lost on restart] → stated in the docs; persistence can come later as an opt-in file (the no-automatic-writes rule).
- [Two answers waited for at once] → one pending DM2/clear per destination per network; the rest get error 5 (blocks) or "busy" (tools).
- [Store memory] → bounded: 254 sources × 445 codes worst case is about 450 kB; the store keeps at most 64 codes per source and counts the rest (`truncated`), which is still more than any real ECU sends.

## Migration Plan

New optional object; existing configs load unchanged. A config whose `j1939.rx` maps PGN 65226 by hand still works; the configurator suggests moving it to `diagnostics.rx`.

## Open Questions

None that change what gets built.
