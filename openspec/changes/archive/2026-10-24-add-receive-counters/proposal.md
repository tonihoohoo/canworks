## Why

Through the Modbus bridge a client sees only the latest value of each received PDO and J1939 PGN per poll. Two frames of one message within a poll look like one, and a short pulse (a bit that is 1 in one frame and 0 in the next) can be missed without a trace. The timeout and status bits say whether a message still arrives, not how many came.

Raw CAN `rx` messages already have `counter_location`, a word input that counts matching frames. PDOs the nodes send and J1939 rx PGNs have nothing like it. The README row "Can a CAN message go unseen?" says so: "PDOs and J1939 PGNs can't".

Practical uses: count event PDOs that stand for one event each (a meter pulse, a scan, a button press), notice that a pulse came and went within one poll, tell a sensor that repeats the same value from one that stopped, and check that a SYNC PDO comes once per SYNC.

Toni (2026-10-24): "Explore calculating also pdo frames etc? Reasonable?", then "Propose". Explore report: `research/pdo-frame-counters-2026-10-24.md`.

## What Changes

- **`counter_location` on received PDOs.** A `nodes[].tx_pdos[]` entry (a PDO the node sends) MAY have `counter_location`, an `%IW` input that counts the PDO's frames that updated its inputs (full length), wrapping at 65535. The same field name and meaning as `raw.rx[].counter_location`. Short PDOs do not count; they stay in the log as today.
- **`counter_location` on J1939 rx PGNs.** A `j1939.rx` entry MAY have `counter_location`, an `%IW` input that counts the messages that the entry took (a multi-packet message counts once, when it is complete).
- **Opt-in.** Without the field nothing changes: no location, no register, no extra Modbus request.
- **Everywhere the location goes.** Location clash and image checks, the bridge variable list (`<node>_tpdo<N>_count`, `<message>_count`, `UINT`, "frames received"), the Modbus map, the Node-RED **canworks in** values, and the HTML network docs treat it like the PDO's `timeout_location` and the PGN's `status_location`.
- **Configurator.** A "Frame counter" address field next to the TPDO's timeout bit and the J1939 rx message's status bit, included in the address suggestion and the clash check.
- **Docs and README.** `docs/config.md`, `docs/j1939.md` and `docs/modbus-bridge.md` describe the field; the README row "Can a CAN message go unseen?" says every received message can count its frames.

Not in this change (explore report): latching short pulses (the bridge cannot know that a given client has read a bit), a receive timestamp per message (freshness is covered by the timeout and status bits; `CAN_RECEIVE` gives every frame with its time), and EMCY or heartbeat counters (`CO_RECV_EMCY` already counts lost EMCYs; heartbeats change no values).

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `canopen-pdo-io`: received PDOs may count their frames.
- `j1939-config`: `j1939.rx` entries list `counter_location`.
- `j1939-ecu`: received PGNs count their messages.
- `canopen-configurator`: the frame counter field on TPDOs and J1939 rx messages.

## Impact

- Bridge (C++): `plugin/src/can/config.cpp` / `config.h` (parse, location kind, clash list), `plugin/src/canopen/network.cpp` (`OnRpdo` counts, the image write with the inputs), `plugin/src/j1939/j1939_config.*` and `j1939_network.cpp`.
- PC tools: `contract.py` and both schema copies, `configurator/declare.py`, `j1939` declare, configurator PDO and J1939 pages, `targets.py` (not a CODESYS field), `docexport.py`/`docwriter.py`, tests. The local runtime runs the bridge image, so it needs nothing of its own.
- No change to the Modbus map format, the mailboxes, the ST library or the CODESYS export (a CODESYS-target PDO has no locations; the field is not offered there).
