## 1. Spike (vcan, kernel J1939)

- [x] 1.1 Set `SO_J1939_FILTER` again on an open, bound promiscuous receive socket while messages arrive; confirm the new PGNs arrive (vcan test: a receiver for PGN 65310, which no config entry receives, opened on the running network)
- [x] 1.2 Find the kernel's completion and abort signal for a transport protocol send on the ECU socket (`SO_J1939_ERRQUEUE`, TX timestamps) for BAM and RTS/CTS; record the result in design.md (Decision 5; vcan test sends both)
- [x] 1.3 Build a C++ block with an `ARRAY[0..1784] OF BYTE` in-out in strucpp 0.7.0 (the compiler of OpenPLC Editor 4.3.2): `library/build.sh` builds all three blocks; every data pin is an in-out (design Decision 3)

## 2. Plugin

- [x] 2.1 `j1939_plc_api.h`: version 2 table (v1 functions first, then send, receiver, request, ECU info and find); `canworks_j1939_api` returns v1 and v2; log line for a version the plugin lacks
- [x] 2.2 `j1939_plc_msgs.h`: send and request jobs in 32 slots of their own, data buffers preallocated; receiver table (16 per network, depth up to 32, queues allocated by the bus thread)
- [x] 2.3 `j1939_network.*`: serve send jobs on the ECU socket (no address: 11, owned PGNs: 4 with the `raw.program_override_protocol` rule), completion and abort (14), timeouts
- [x] 2.4 Receivers: union of PGNs into the receive filter (`ANY` = no filter), fan out matching messages (source, destination, own messages left out), overflow counting, close on PLC stop and network restart
- [x] 2.5 Requests: send, match the answer by PGN and source, NACK/Access Denied/Cannot Respond to 12 with the code, global done once sent
- [x] 2.6 ECU snapshot (state, address, NAME, claims seen) published with each commit for `ecu_info` and `find_ecu`
- [x] 2.7 Status answer: program receivers, sends, aborts and requests
- [x] 2.8 Unit tests in test/j1939_unit and test/j1939_blocks with the fake socket (send owned PGN, no address, address moved, receiver filter and overflow, request answer/NACK/timeout, find by NAME, v1 and v2 tables, header copy matches `library/src/j1939_common.inc`)

## 3. Library

- [x] 3.1 `library/generate.py`: `J1939_SEND`, `J1939_RECEIVE`, `J1939_REQUEST`, `J1939_ECU_INFO`, `J1939_FIND_ECU` on the version 2 table; `library/src/j1939_common.inc` updated
- [x] 3.2 ST functions `J1939_GET_BITS`, `J1939_SET_BITS`, `J1939_NAME_MAKE`, block `J1939_NAME_SPLIT`; tests that their results match the plugin's signal packing and the tools' NAME packing
- [x] 3.3 Rebuild `canworks.stlib` (`library/build.sh`) into the deploy package

## 4. PC tools

- [x] 4.1 Rename `canworks/sdolibrary.py` to `plclibrary.py` and `tests/test_sdolibrary.py` to `test_plclibrary.py` (clean cut); update imports and `.github/ci/tool-test-times.json`
- [x] 4.2 `canworks-deploy library --help` and the project creation output describe the whole library (spec `plc-library`); the block list includes the J1939 message blocks
- [x] 4.3 Configurator: Copy as ST call on J1939 `rx` and `tx` entries, with tests
- [x] 4.4 `canworks-diag status` prints the program's J1939 receivers and counts
- [x] 4.5 Minor version bump of the tools

## 5. Integration test (vcan)

- [x] 5.1 vcan J1939 test with `canworks-j1939-sim`: program sends 40 bytes by RTS/CTS to the simulator and 20 by BAM globally, receives a 40-byte PGN and one no config entry receives, requests a PGN, reads the ECU info and finds the simulator (NACK and timeout in the block tests); in the existing J1939 CI group

## 6. Docs

- [x] 6.1 New `docs/plc-library.md` (families, install and enable, handshakes, interface versions); move the install sections out of `docs/plc-sdo.md`, which becomes the SDO and EMCY block reference
- [x] 6.2 `docs/j1939.md` "Blocks": the message blocks, ST functions, one error ID table for all J1939 blocks, an example program
- [x] 6.3 `docs/deploy.md` ("The function block library"), `docs/configurator.md` (**Enable the canworks function blocks**), `docs/development.md`, `docs/raw-can.md`, `docs/plc-nmt.md`, `docs/cia402.md`: link to `plc-library.md`, no "SDO library" wording
- [x] 6.4 README: J1939 blocks in the J1939 section, the library described as a whole, links to `docs/plc-library.md`
- [x] 6.5 `docs/j1939.md` "Limits": none of them no longer holds; the program blocks' limits added

## 7. Hardware (Pi + PC adapter running canworks-j1939-sim)

- [ ] 7.1 On the Pi, a program with `J1939_SEND` (8 and 40 bytes, to the simulator and global), `J1939_RECEIVE` (a 40-byte PGN from the simulator) and `J1939_REQUEST` (answer and NACK); check with the trace; clean PLC start afterwards
