# Tasks

## 1. Config contract and schema

- [ ] 1.1 Schema: `bits` on PDO entries (`bit`, `name`, `iec_location`); `iec_location` of an entry optional when it has bits.
- [ ] 1.2 `contract.py` checks, with tests: integer types only, bit range, duplicates, area and size, overlap with every other location, RPDO entry with both a location and bits, names unique within the node with entry names, target rules (no location on CODESYS and bridge, bridge bit on an entry without a location).
- [ ] 1.3 Plugin `config.cpp`: parse and the same checks, with unit tests whose messages name node, PDO, object and bit.

## 2. Plugin exchange

- [ ] 2.1 `ProcessImage`: bit records per input and output binding; `copy_to_plc` writes the bits after the entry's value, `copy_from_plc` builds output entries from their `%QX` bits (unlisted bits 0); entries with only bits have no whole-value location.
- [ ] 2.2 Unit tests: input bits, input value plus bits, output from bits, NULL `%QX` pointers read 0, timed-out PDO holds bits like its value.
- [ ] 2.3 vcan scan test in an existing CTest job: a simulated CiA 401 node's input byte reaches `%IX` bits and `%QX` bits reach its output byte.

## 3. Names and exports

- [ ] 3.1 `configurator/declare.py`: one BOOL per located bit channel after its entry, default name `<entry part>_bit<n>`, comment with the note's bit text; new editor project uses it. Tests.
- [ ] 3.2 Bus trace decode: bit lines under the entry, declared names in editor-project mode. Tests.
- [ ] 3.3 DBC export: one-bit signals per bit channel. Test with cantools.
- [ ] 3.4 HTML documents: bit rows in PDO details and the cross-reference. Test.
- [ ] 3.5 Modbus bridge map and Node-RED flow: named bit rows at the entry's byte. Tests.

## 4. Configurator

- [ ] 4.1 PDOs tab: **Bits…** with count, bit table (note name, tick, name, location with **Suggest**), **Map all bits** and **Unmap all**, the RPDO question, "sent as 0", one undo step per change, problems naming the bit; CODESYS and bridge columns.
- [ ] 4.2 Names copied from device notes when a bit is mapped, as identifiers; note edits never rename a mapped bit.
- [ ] 4.3 Online: mapped bits with names and states under the entry's live value.
- [ ] 4.4 Browser test in the existing browser job: map all bits of a CiA 402 statusword, rename one, see the declaration; RPDO question; 1280 px with no clipped text.

## 5. CODESYS

- [ ] 5.1 Check whether the CODESYS scripting API reaches a channel's bit sub-channels (I/O mapping of a BYTE channel); adjust the spec delta to what it allows before archive.
- [ ] 5.2 Plan: `bits` per channel with variable names; script maps them or lists them in the report. Tests on the plan.

## 6. Docs and versions

- [ ] 6.1 README feature line; `docs/config.md` (PDO entries: `bits`), `docs/configurator.md`, `docs/trace.md`, `docs/codesys.md`, `docs/modbus-bridge.md`; tour line for **Bits…**.
- [ ] 6.2 Bump plugin and PC tools versions (minor).
- [ ] 6.3 Compare the PR's CI wall and summed job time with the main baseline and note both in the PR.

## 7. Hardware

- [ ] 7.1 Pi: deploy a config with bit channels on a real node's integer input entry and an output entry; the bits change in the PLC with the device, and output bits set by the program reach the device. Clean PLC start after.
- [ ] 7.2 Windows: run the CODESYS export with bit channels on the real CODESYS install and check the bit variables in the I/O mapping.
