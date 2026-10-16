# Proposal: fix-pdo-layout-read

## Why

In Commission a device, Trace > Decoding, **Read PDOs from device** for node 49 shows "Node 49: TPDO1, TPDO2, TPDO3 read from the device.", yet the node's PDO layout column stays "unknown" and its PDO frames stay bytes. Nodes 23 and 32, read automatically, also stay "unknown".

The server names a PDO in that message as soon as its communication object (0x18xx:1, COB-ID) answers. A layout needs more: the mapping object's count (0x1Axx:0) and every mapping entry. When one of those reads fails (an SDO abort or a timeout), `params.pdo_values` leaves the value out without a word, `NodeLayouts.pdos` then drops the PDO, and the read still reports success. The user sees a success message and "unknown", with nothing saying what went wrong or what to do.

Reproduced on the virtual bus: a device whose TPDO1-3 communication objects answer and whose mapping objects do not gives exactly the screen of the report (banner with TPDO1, TPDO2, TPDO3; layout "unknown"). Which mapping read failed on the real devices, and why, is not known yet; the trace recorded at the time holds the devices' SDO answers.

## What Changes

- The read keeps, for each PDO, either its layout or the first object that could not be read and why (the abort code with its CiA 301 text, or "no answer").
- A mapping read that gets no answer is tried once more before it counts as failed.
- The message after **Read PDOs from device** names only PDOs that now decode, and each other one with its reason, e.g. "Node 49: TPDO1, TPDO2 read from the device. TPDO3 not usable: 0x1A02:1 not read (no answer)." When none decodes it is an error message, not a success one.
- The Decoding panel's PDO layout column says what the last read found instead of a bare "unknown": "read from the device at …" with the PDOs that decode, and the PDOs that do not with their reason; "not read: …" when the read gave nothing usable. Automatic reads fill the same text.
- A node with an EDS keeps decoding with the EDS defaults ("assumed") for the PDOs whose mapping the device did not give.
- If the recorded trace or the bench shows a reader or decoder fault behind the failed reads (an SDO answer the reader handles wrongly), that fault is fixed in this change too.

No config, schema, plugin or runtime change.

## Capabilities

### Modified Capabilities
- `canopen-configurator`: the result of a PDO layout read says which PDOs decode and why the others do not.

## Impact

- Code: `tools/deploy/canworks/configurator/params.py` (`pdo_values` keeps failures and retries a timed-out mapping read), `server.py` (`/api/online/pdo_layout` answers per PDO), `tracing.py` (`Workspace.decoding` adds the last read's result per node), `static/trace.js` (message and the PDO layout column).
- Tests: unit tests for `pdo_values` with aborts and timeouts; the browser test `test_trace_decoding_page.py` gains a device whose mapping objects do not answer, and a manual **Read PDOs from device** click (only the automatic read is covered today).
- Docs: README and the trace guide sentence on Read PDOs from device.
- Hardware: repeat the read on the bench with real nodes.
