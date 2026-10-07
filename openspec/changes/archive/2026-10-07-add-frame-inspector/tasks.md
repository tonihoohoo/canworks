## 1. Explanation model

- [x] 1.1 Add `bustrace/explain_texts.py` with the texts for function codes, NMT commands and states, SDO command specifiers and bits per direction, abort codes, EMCY classes and error register bits, LSS commands, SocketCAN error classes and details and the wire fields, reusing the `diag.py` tables; verify every table entry has a text in a unit test.
- [x] 1.2 Add `bustrace/explain.py` with the meaning, identifier and data layers for NMT, SYNC, TIME, EMCY, heartbeat/boot-up/node guarding, SDO (expedited, segmented, block, abort), LSS, PDO (EDS types incl. signed and float, bit-mapped PLC addresses, PLC variable names in project mode) and error frames; every data bit in exactly one field; share the PDO and SDO value helpers with `decode.py`; verify with golden JSON per frame kind on the example configs and a test that no bit is left without a field.
- [x] 1.3 Add SDO context from the decoder's per-node SDO state for segments and block segments; verify on traces built from frames the frame builder makes, with a segmented upload and a block download.
- [x] 1.4 Add the wire reconstruction (base/extended, data/remote, CRC-15, stuffing, ACK, EOF, intermission, bit-to-layer links, timing from config, trace or option, 500 kbit/s assumed); verify the CRC check value 0x059E, the 76 + 3 stuff bits and 158 µs of `185#2500EA00` at 500 kbit/s, golden wire bits for an extended and a remote frame, and that removing the stuff bits gives back the unstuffed bits.
- [x] 1.5 Add the frame builder and the example frames from a configuration (SDO read/write expedited and segmented with answers, PDO from signal values with range checks, NMT, heartbeat, EMCY); verify that built frames explain back to the values they were built from.

## 2. Sequences

- [x] 2.1 Add `bustrace/sequences.py` with SDO conversations (initiate to answer or abort, segmented and block folded, step times); verify on built traces including an abort.
- [x] 2.2 Add SYNC cycles (frames per cycle with offsets, groups, transmission type, SYNC window check, slowest cycle); verify on a built trace with a delayed TPDO.
- [x] 2.3 Add boot stories (boot-up or reset to first PDO after start, writes compared with `dcfexport.plugin_downloads`, missing/extra/different/refused marked); verify on a built trace of a boot (the configuration's own boot writes) and of a boot with a refused write.

## 3. Command line

- [x] 3.1 Add `openplc-canopen-diag explain` (candump frame syntax, `--trace/--index`, `--config`, `--network`, `--bitrate`, `--format text|json`, errors for bad syntax and frames over 8 bytes); verify with CLI tests for text and JSON output, a trace file frame and each error.

## 4. Configurator

- [x] 4.1 Add `POST /api/trace/explain`, `POST /api/trace/sequence`, `POST /api/explain` and `POST /api/explain/build` (unsaved config, project-mode variable names); verify with API tests.
- [x] 4.2 Add `static/explain.js` with the inspector panel (layers, explanation box, linked highlight, keyboard, phone width, light/dark) and open it from the Trace view's frame list with arrow-key following; verify with a headless Chromium page test (point at a bit, keyboard, highlight in grid and wire).
- [x] 4.3 Add the Sequences tab (conversation and boot lists with filters, sequence diagrams, SYNC timeline with stepping and slowest cycle, steps open the inspector); verify with a page test on an opened trace file.
- [x] 4.4 Add the Frame lab view (typed and pasted frames, examples from the config, builder, bit rate picker, arbitration demo, "nothing is sent" note); verify with a page test including the 0x183 vs 0x185 arbitration and a no-network check that no request goes to a runtime.

## 5. Network document

- [x] 5.1 Add per-bit explanations to the PDO byte grid in `docwriter.py` from the explanation model, inlined; verify with the docs page test (point at a bit), the no-script render and updated golden files.

## 6. Docs and release

- [x] 6.1 Write `docs/frame-inspector.md` (the inspector, sequences, Frame lab, `explain`, the reconstruction limit, and a short CAN/CANopen primer built around example frames) with screenshots made from an opened trace and the Frame lab.
- [x] 6.2 Update `docs/trace.md`, `docs/configurator.md`, `docs/diagnostics.md`, `docs/network-docs.md` and README (features, PC tools, capability list).
- [x] 6.3 Bump the deploy tool minor version. 0.37.0 (chain step 6).

## 7. Hardware check

- [x] 7.1 On the hardware bench, record a trace of a node boot and its PDO traffic, open the boot story and an SDO conversation, explain a TPDO and an RPDO frame and check the bit values against the PLC variables in the online view.
  Partial run (2026-10-07, Pi + one real node, test copy without node TPDOs): a 30 s trace with an NMT reset of the node (3149 frames, 0 lost); the boot story found the boot (reset node, boot-up; operational) with all 20 configured writes ok; 53 SDO conversations listed, matching the request/answer pairs; the inspector and `explain --trace` decoded the reset and the SDO writes correctly; offline explanations of the node's RPDO matched the live PLC outputs (all FALSE). Fixed from this run: the boot story now ends at the first PDO or the first OPERATIONAL heartbeat (it kept periodic SDO reads and showed 23 s), writes after the NMT start are no longer compared as extra, long diagram labels are cut to fit, and a 1-bit PDO field at bit 0 shows its bit line. Live PDO run (2026-10-07, same bench): a 30 s trace while one RPDO output was forced TRUE, then FALSE, then released (3083 frames, 0 lost, 0 error frames). The two RPDO frames (`217#01`, `217#00`) were explained, in the CLI and in the configurator inspector, as that output TRUE then FALSE, with the bit positions in mapping order, matching the forced PLC values. The bench copy has no TPDO, so the TPDO side was checked offline against the configuration.
