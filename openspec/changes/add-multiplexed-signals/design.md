## Context

Raw CAN (`can-raw-messages`) and J1939 (`j1939-config`, `j1939-ecu`) share one signal model: a signal is `start_bit`, `length`, `byte_order`, `signed` and an IEC location, packed by `plugin/src/can/signals.*` in the plugin and `canworks/raw/signals.py` in the PC tools. Every matching frame writes every signal of its entry (`RawEngine::on_frame`, J1939 receive), and every send packs every signal (`RawEngine::build`, J1939 send).

The only multiplexing in the project today is the CANopen DBC export's optional SDO frames: an `Object` multiplexor with one data signal per object (`canopen-dbc-export`, "Optional SDO frames"). The DBC writer (`dbcexport.write`) already emits `M` and `mN`.

cantools 44.2.1, already a PC tools dependency, was checked during the exploration:
- simple and extended multiplexing load in strict mode
- each signal has `is_multiplexer`, `multiplexer_ids` (ranges expanded) and `multiplexer_signal`
- decoding a frame whose switch value has no page raises `DecodeError`
- a message with two `M` signals and no `SG_MUL_VAL_` loads without error but loses all multiplexing (`multiplexer_ids` is None everywhere)

Decisions from the exploration (Toni, 2026-10-10): raw CAN and J1939 in one change, extended multiplexing included, send default `program`, the J1939 trace fix rides here.

## Goals / Non-Goals

**Goals:**
- Receive and send DBC-multiplexed messages on raw CAN and J1939 networks with no ST code.
- Round-trip DBC import and export of simple and extended multiplexing.
- Trace, inspector and graphs decode by page.
- Same checks and messages in the plugin and the PC tools, from shared fixtures.

**Non-Goals:**
- CANopen MPDO (CiA 301 destination/source address mode multiplexed PDOs). It is a different mechanism and would be its own change.
- Multiplexing in CANopen PDO mappings or the CANopen DBC export beyond today's SDO `Object` multiplexor.
- New ST blocks. `CAN_RECEIVE` with `CAN_GET_BITS` already lets a program decode pages itself; the docs get an example.
- Scaling in the runtime (values stay raw integers).

## Decisions

### 1. Flat, DBC-shaped fields on each signal

```json
"signals": [
  { "name": "Page", "start_bit": 0,  "length": 8,  "multiplexer": true, "iec_location": "%IB10" },
  { "name": "Temp", "start_bit": 8,  "length": 16, "mux": { "values": [1] }, "iec_location": "%IW12" },
  { "name": "Sub",  "start_bit": 8,  "length": 8,  "multiplexer": true, "mux": { "on": "Page", "values": [3] }, "iec_location": "%IB14" },
  { "name": "C",    "start_bit": 24, "length": 8,  "mux": { "on": "Page", "values": [[1, 2], [5, 9]] }, "iec_location": "%IB15" }
]
```

- `multiplexer: true` marks a switch: unsigned, at most 32 bits.
- `mux.on` names a switch of the same message. It may be left out only when the message has exactly one switch.
- `mux.values` is a non-empty list of integers or `[low, high]` ranges (low ≤ high), each inside the switch's range.
- A signal with both fields is a nested switch. Simple multiplexing is the one-switch case, so one model covers simple and extended, and maps 1:1 to DBC `M`, `mN`, `mNM` and `SG_MUL_VAL_`.
- Every signal keeps its own IEC location, as today. A page does not get a location block of its own.

*Alternative:* `pages: [{ "value": 1, "signals": [...] }]`. Rejected: it cannot express ranges or nested switches without a second shape, and DBC round trips would lose information.

*Alternative:* names `multiplexer_ids` / `multiplexer_signal` as in cantools. Rejected: `mux.on` and `mux.values` read better in a hand-written config, and the DBC terms stay in the import and export code.

### 2. When a signal is in a frame

A signal is **active** in a frame when it has no `mux`, or when its switch is active and the frame's value of that switch is in `mux.values`. Switches without `mux` are always active. This one recursive rule serves receive, send, checks, trace and DBC export.

The plugin turns it into a flat table at start: for each signal, the list of (switch index, value set) conditions up its chain, with value sets as sorted ranges. Receive evaluates each condition with one extract and a range search, no allocation.

Checks (plugin and PC tools, same messages, shared fixture files):
- `mux.on` names an existing switch of the message; `on` missing with several switches is an error naming the signal
- switch signed or longer than 32 bits: error
- values outside the switch's range, empty `values`, `low > high`: error
- cycles (`A` on `B`, `B` on `A`): error naming both
- a switch no signal depends on: warning
- `mux` on a message whose signals have no switch: error

### 3. Overlap and length per page

Two signals **can share a frame** when both can be active at once: for every switch both depend on (directly or up their chains), their value sets on it intersect. Only signals that can share a frame are checked for overlap. Raw keeps its warning and J1939 keeps its error, both now per page.

The bytes a frame must have become per page: the always-present signals plus the switches plus the active page's signals. A received frame shorter than its own page needs is short (counted, nothing written). A raw `tx` default `dlc` stays the smallest that holds every signal of every page, so every page goes out with one DLC; J1939 `length` likewise.

### 4. Receive

For a matching frame:
1. extract the switches in dependency order and decide each signal's activity
2. if a switch value selects no signal at all on a switch that has dependent signals, the frame is an **unknown page**: the entry's `unknown_pages` diagnostics counter grows, and only the always-present signals and the switches are written
3. otherwise write the always-present signals, the switches and the active signals; every other signal holds its last value, the same rule as a sender that stops
4. message-level status, counter, `id`, `dlc` and `data` locations behave as today (every matching frame counts)

`valid_location` (bit, `%IX`):
- raw signals gain it. It is TRUE once the signal was written and FALSE again when `timeout_ms` passes without a frame that made it active (or never, with `timeout_ms` 0)
- J1939 signals keep today's meaning (FALSE on not available or error) and gain the same page rule
- per-page freshness therefore lives on the signals the program cares about, with no separate pages table

### 5. Send: `pages` on the send entry

A multiplexed send entry is several frames. `pages` picks how they go out:

| `pages` | What the plugin sends | Switch locations |
|---|---|---|
| `program` (default) | the page the program's switch outputs select, at each send the entry's timing asks for | required (`%Q`), as any signal |
| `all` | every page, back to back, at each periodic send | not allowed: the plugin sets them |
| `rotate` | the next page in page order, at each periodic send | not allowed |

- **Page list** (for `all` and `rotate`): every combination of switch values that the `mux.values` of the message's signals name, ranges expanded, in ascending order of the top switch and then the nested ones. More than 64 pages is a config error naming the message, which points to `program`.
- In every mode, only the active signals of the page are packed; other bits come from `data_location` and `fill` (raw) or are set to 1 (J1939), as today.
- **on change**: `program` sends when any output location changed (today's rule). `all` sends only the pages that have a changed active signal (an always-present signal counts for every page). `rotate` sends the next page that has a pending change, no sooner than `min_gap_ms`.
- **trigger** (raw): `program` sends the selected page, `all` every page, `rotate` the next page.
- **J1939 requests**: answered with the selected page (`program`), every page (`all`) or the next page (`rotate`).
- **Unknown page from the program** (`program` mode, the switch outputs select no page): the frame is sent with the switches and always-present signals only, and the entry's diagnostics show `unknown_page`. This keeps the program in charge, which is the reason `program` is the default.

*Why `program` is the default*: nothing goes on the bus that the program did not choose, and a config imported from a DBC behaves like a non-multiplexed message until the user picks `all` or `rotate`.

### 6. PC tools

- A new `canworks/raw/mux.py` (next to `signals.py`) has the activity rule, page list and per-page overlap; raw and J1939 contract checks call it.
- **DBC import** (`raw/dbc.py`, `j1939/dbc.py`): `is_multiplexer` → `multiplexer: true`; `multiplexer_signal` + `multiplexer_ids` → `mux` with the ids folded back into ranges. The "multiplexed left out" note and the J1939 skip are removed. A message with several `M` signals whose dependents all have `multiplexer_ids` None is a problem ("several switches but no SG_MUL_VAL_; multiplexing left out"), imported with its signals unmultiplexed only when the user picks it anyway.
- **DBC export** (`dbcexport.write` used by raw and J1939): `M` for a top switch, `mN` for a signal with one value on a top switch, `mNM` for a nested switch with one value, and `SG_MUL_VAL_` lines whenever a signal has ranges, several values or a nested chain. Golden files and a cantools strict-mode round trip in the tests.
- **Trace** (`raw/decode.py RawDecoder`, `bustrace/j1939.py J1939Decoder`): decode with our own rule, not `cantools.decode`, so unknown pages do not raise. The row text names the page: `Status [Page=2] Press=400 kPa`, `Status [Page=4 unknown]`. DBC messages read for the trace keep their multiplexing fields. Graph series of a multiplexed signal take a point only from frames where it is active.
- **Frame inspector**: marks the switch bits and the active page's bits only.
- **Simulator**: `raw_send` signals take `multiplexer` and `mux`, and `raw_send` takes `pages` (`all` default, `rotate`); `canworks-j1939-sim` sends each page of a multiplexed DBC message at the message's cycle time (`all`), or `--mux rotate`.

### 7. Configurator

- Signal rows: a "Switch" checkbox and a "Page" cell (`Page = 1`, `Page = 1-2, 5-9`, editable as text, `on` picked from the message's switches).
- Rows sorted by page, always-present first.
- The bit grid shows one page at a time with a page picker; overlaps are marked per page.
- Send entries with switches show the `pages` choice.
- "Suggest addresses" leaves switch locations empty in `all` and `rotate`.
- Same controls on the J1939 page.
- The online view lists `unknown_pages` per message.

## Risks / Trade-offs

- [Page explosion with ranges in `all`/`rotate`] → 64-page cap with an error that points to `program`.
- [Overlap check cost with deep nesting] → done once at load; messages have at most 64 signals in practice; the check is pairwise over the condition lists.
- [J1939 behaviour change for existing overlapping configs] → none exist in real use (clean cut allowed); per-page checking only relaxes the rule.
- [cantools differences, e.g. dumping nested switches as `M` + `SG_MUL_VAL_`] → our writer is hand-written; tests load our output with cantools strict.
- [Bench has no multiplexed device] → the PC adapter plays one with the simulator; the logic is covered on the simulated bus and vcan.

## Migration Plan

New optional fields only. Configs without them behave as before. Schema version stays 2. PC tools minor version bump; plugin and tools ship together as usual.

## Open Questions

None. Toni answered the exploration's four questions on 2026-10-10.
