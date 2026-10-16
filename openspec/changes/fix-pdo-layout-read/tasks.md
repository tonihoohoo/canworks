# Tasks: fix-pdo-layout-read

## 1. Tests first
- [ ] 1.1 Unit test: `pdo_values` against a fake client whose mapping reads abort or time out returns the failures per PDO; a timed-out mapping read is tried once more, an abort is not.
- [ ] 1.2 Browser test: a virtual device with TPDO1-3 communication objects and no mapping objects; Read PDOs from device gives an error message naming 0x1A00:0, and the PDO layout column reads "not read" with the reason.
- [ ] 1.3 Browser test: a manual Read PDOs from device click on a complete device updates the column (today only the automatic read is tested), and a device with TPDO3's mapping aborting lists TPDO1, TPDO2 as read and TPDO3 with its reason.

## 2. Cause on real devices
- [ ] 2.1 Look at the reported trace's SDO answers of node 49 (0x5B1), or repeat the read on the bench, to see which mapping read failed and why; if our SDO client or trace decoder handles the answer wrongly, fix it with a unit test of that answer.

## 3. Read and panel
- [ ] 3.1 `params.pdo_values`: keep failures per PDO, one retry on no answer for mapping reads.
- [ ] 3.2 `/api/online/pdo_layout`: per PDO `usable` and `reason`, `usable` from `NodeLayouts.pdos`.
- [ ] 3.3 `Workspace`: keep the last read's result per node with `device_reads`; `decoding()` returns it.
- [ ] 3.4 `trace.js`: the message names only usable PDOs and the others with reasons (error when none); the PDO layout column shows the result.

## 4. Docs
- [ ] 4.1 README and the trace guide: what Read PDOs from device says when a PDO cannot be read. Tools version bump and release notes.

## 5. Hardware
- [ ] 5.1 On the bench: Read PDOs from device for each node in Commission a device; the column shows "read from the device" with its PDOs, or the reason when a PDO cannot be read.

## 6. CI time
- [ ] 6.1 PR body: CI wall and summed job time vs the main baseline.
