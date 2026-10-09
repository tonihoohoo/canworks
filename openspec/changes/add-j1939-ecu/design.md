## Context

The plugin today runs one bus thread per network (canopen-networks), each with a Lely master on a CAN_RAW connection. Around it sits protocol-neutral code:
- `can_adapter` (SocketCAN/slcan link setup)
- `bitrate_sweep`, `slcan_sweep`, `bus_monitor`
- `trace_capture` and raw `frame_tx`
- the diagnostics server (`diag`, `secure_channel`)
- `process_image` and `iec_location`

The PC tools carry a CANopen-specific contract and EDS layer and a protocol-neutral rest: adapter, bustrace recorder/formats, configurator shell, deploy/upload, clash check and the DBC writer.

Decisions from the exploration (2026-10-08): both ECU roles in slice 1, the Linux kernel J1939 stack in the runtime, can-j1939 on the PC, one repository (renamed `canworks` first), and no real J1939 device (simulator on a second adapter).

## Goals / Non-Goals

**Goals:**
- A PLC reads SPNs from other ECUs' PGNs into `%I` and sends its own PGNs from `%Q`, with a claimed address, on the same runtime that runs CANopen networks.
- Configured, deployed, traced and diagnosed with the existing tools.
- Testable in CI on vcan and on the bench with an adapter-to-adapter simulator.
- No CI wall-time increase.

**Non-Goals:**
- DM1/DM2/DM3/DM11, DM14/15, PLC function blocks, J1939-FD, ISOBUS, NMEA 2000 (later changes).
- J1939 on the in-process simulated bus, and therefore in the cloud-container tests and the Docker Desktop local sim runtime.
- CANopen and J1939 on one physical bus.
- Shipping any SAE J1939 Digital Annex content.
- Scaling to engineering units in the runtime.

## Decisions

### 1. One plugin, protocol per network

The `protocol` field selects the engine per network. This keeps one config file (`conf/canopen.json`, on-device name kept by the rename), one deploy injection, one diagnostics port and one clash check, and the plugin line in `plugins.conf` is unchanged.

*Alternative:* a second plugin `j1939`. Rejected: it would need a second config path through the editor upload (a hand-added plugin does not survive uploads), a second diag port, and cross-plugin clash checks.

### 2. Kernel CAN_J1939 sockets

The J1939 bus thread uses `socket(PF_CAN, SOCK_DGRAM, CAN_J1939)` on the network's interface:
- **Receive socket:** bound with `addr = J1939_NO_ADDR`, `name = J1939_NO_NAME`, `pgn = J1939_NO_PGN`, with `SO_J1939_FILTER` set to the configured RX PGNs plus 59904 (Request) and 60928 (Address Claimed). The kernel reassembles TP/ETP before delivery. `recvmsg` gives the source address, source NAME, destination and priority in control messages.
- **ECU socket:** bound with the configured NAME and the claimed address. It sends TX PGNs with `sendto` (destination address or `J1939_NO_ADDR` for global) and priority via `SO_J1939_SEND_PRIO`. Payloads over 8 bytes go through the kernel TP (BAM for global, RTS/CTS otherwise), and the kernel enforces the transmit side of address-claim state.
- **Address claim:** the kernel tracks claims, but user space must send them. This follows the logic of can-utils `jacd`, reimplemented, not copied (jacd is GPL):
  - send Address Claimed with our NAME for the preferred address
  - wait 250 ms; on a contending claim with a lower NAME, take the next free address in `address_range` if arbitrary-address-capable, otherwise send Cannot Claim (SA 254) and stop sending
  - answer Request for Address Claimed
  - re-claim on bus-off recovery

The claim state and current address go to the configured PLC locations and the diag status.

*Alternatives:* our own engine over CAN_RAW (testable on the simulated bus, but new code, not production-proven), Open-SAE-J1939 (MIT, one ECU per process), commercial stacks (closed source, cannot ship). See the project notes.

### 3. Module loading and failure

The plugin does not load modules (no CAP_SYS_MODULE in the runtime container). The install script:
- writes `/etc/modules-load.d/canworks-j1939.conf` (`can-j1939`)
- runs `modprobe can-j1939` on the host, in both native and Docker mode

`socket()` failing with `EPROTONOSUPPORT` makes that network fail at start with "J1939 needs the can-j1939 kernel module (modprobe can-j1939)". Other networks run, which follows canopen-networks "Networks run independently". This is a runtime failure, not a config error.

### 4. Signals reach the PLC raw

Each signal is packed and unpacked as an unsigned or signed integer of `length` bits at `start_bit` with `byte_order` (`little`, the J1939 default, or `big`). It is written to an IEC location of the matching size (`%IX` for length 1, `%IB`/`%IW`/`%ID`/`%IL` for ≤8/16/32/64 bits). Scale, offset and unit stay in the config for tools and declarations only.

J1939 "not available" (all ones) and "error" (all ones minus one) raw values for lengths ≥ 2 set the signal's optional `valid_location` bit FALSE. TX bits not covered by a signal are sent as 1, per J1939-71.

*Why raw:* OpenPLC's located REAL types are awkward, and the CANopen side already passes raw values. Scaling in ST is one line, and the generated declaration comment carries scale, offset and unit.

### 5. Timing

- **TX** `period_ms` comes from the DBC cycle time when imported. 0 means only on change (with `min_gap_ms`, default 0) and on request.
- **RX** `timeout_ms` is 0 (no supervision) unless set. The configurator fills 3 × the DBC cycle time on import, so the default is visible in the file.
- **Requests** use `period_ms`. A response counts for the matching `rx` entry.

TX values are sampled from the output snapshot the scan publishes (process_image), the same way CANopen RPDOs are, and sent from the bus thread on a 1 ms timer.

### 6. Source filtering

An `rx` entry filters by `source` (address 0..253, or omitted for any) or by `source_name` (64-bit NAME with optional `source_name_mask`). A NAME filter survives address changes, because the kernel reports the sender's NAME when it has seen its claim. With several senders of one PGN and no filter, the last one wins, and the diag status lists every source seen.

### 7. Config shape (schema v2, additive)

```json
{ "schema_version": 2, "networks": [
  { "name": "machine", "protocol": "j1939",
    "adapter": { "type": "socketcan", "interface": "can1", "bitrate": 250000 },
    "j1939": {
      "ecu": { "name": { "identity_number": 1234, "manufacturer_code": 0, "function": 130,
                         "industry_group": 0, "arbitrary_address_capable": true },
               "address": 128, "address_range": [128, 247],
               "state_location": "%IB200", "address_location": "%IB201" },
      "dbc": "machine.dbc",
      "rx": [ { "pgn": 65280, "source": 0, "timeout_ms": 300, "status_location": "%IX200.0",
                "signals": [ { "name": "Pressure", "start_bit": 0, "length": 16,
                               "scale": 0.1, "offset": 0, "unit": "bar",
                               "iec_location": "%IW200", "valid_location": "%IX200.1" } ] } ],
      "tx": [ { "pgn": 65281, "priority": 6, "period_ms": 100,
                "signals": [ { "name": "Setpoint", "start_bit": 0, "length": 16,
                               "iec_location": "%QW200" } ] } ],
      "requests": [ { "pgn": 65282, "destination": 0, "period_ms": 1000 } ] } } ] }
```

Writers use version 2 whenever a J1939 network exists (canopen-config-contract "lowest version" rule).

### 8. Simulator and tests

`canworks-j1939-sim --dbc FILE --interface vcan0|--adapter slcan:PORT [--name …] [--address N] [--scenario FILE]` is built on can-j1939:
- claims an address
- sends every message whose DBC sender is the simulated node with ramping or scenario values
- answers requests
- can contend for an address (for claim tests)

CI coverage:
- vcan tests in an existing vcan group: claim, RX/TX values both ways, TP 1785 bytes, request answer, timeout bit, module-missing message (unload is not possible in CI, so this is a unit test of the error mapping)
- C++ unit tests for packing and config checks in the `test` job
- Python tests for DBC import, trace decode and declarations in the tools shards

### 9. CI area classifier

`.github/scripts/ci_changes.py` adds a third output, `areas`, a subset of `canopen,j1939,shared`, from path rules:
- **j1939:** `plugin/src/j1939/**`, `tools/deploy/canworks/j1939/**`, `test/j1939/**`, `examples/j1939/**`
- **canopen:** Lely-bound plugin files, the EDS/DCF modules, `test/` CANopen folders
- **shared:** everything else that is code

Jobs and steps run when their area or `shared` is present. A J1939 step lives inside the existing vcan group with the most headroom (times recorded in the workflow), so no runner gets longer than today's slowest.

### 10. PGN and identifier rules checked

- PGN must be 0..0x3FFFF.
- PDU1 PGNs (PF < 240) must have PS = 0 in the config, and the destination is given separately.
- TX PGNs must be unique per network.
- `address` must be 0..253.
- NAME fields must be in range.
- Two J1939 networks cannot share an interface.
- A J1939 network cannot share an interface with a CANopen network.
- `adapter.simulate: true` is rejected on J1939 ("use vcan").

## Risks / Trade-offs

- [Docker Desktop kernels may lack `can-j1939`, so the local sim runtime cannot run J1939] → J1939 networks are refused there with a clear message, and this is checked in a later task.
- [The kernel stack is not on the simulated bus, so cloud-container tests cannot cover J1939] → vcan tests in CI, unit tests for everything above the socket.
- [can-j1939 pulls numpy into the PC wheel's dependencies (size, install time on Windows)] → accepted at the exploration. The wheel stays platform-independent because numpy installs as its own wheel.
- [Address claim logic bugs could make the PLC silent on a real machine] → claim state is a PLC input, so the program can react, the simulator's contention mode is tested in CI, and a HW task covers it.
- [DBC files from vendors may use non-standard J1939 attributes] → import reads `VFrameFormat`, `GenMsgCycleTime` and the 29-bit ID only, and names unsupported things in a problem list instead of guessing.

## Migration Plan

Additive. Existing configs are unchanged and `protocol` defaults to `canopen`. The PC tools get a minor version bump. A runtime upgrade needs `install-stock.sh` re-run once, to load the module.

## Open Questions

- Should the J1939 example use 250 kbit/s (J1939-11) or 500 kbit/s (J1939-14)? Default: 250, with the bit rate in the adapter as usual.
