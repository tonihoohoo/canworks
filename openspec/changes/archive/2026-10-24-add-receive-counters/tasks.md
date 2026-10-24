## 1. Bridge

- [x] 1.1 `plugin/src/can/config.cpp` / `config.h`: `counter_location` on `tx_pdos` (an `%IW`; refused on `rx_pdos` naming the field, as `timeout_location`), in the location clash list and image bounds check
- [x] 1.2 `network.cpp`: `InputPdo` count, incremented in a deferred handler from `OnRpdo` when `!ec`; written to the image after the inputs; never reset while the bridge runs; not counted while the program holds the network stopped
- [x] 1.3 J1939: `j1939_config.*` parse `rx[].counter_location` (`%IW`), `j1939_network.cpp` counts each taken message (TP/ETP once when complete) and writes it with the signal values
- [x] 1.4 C++ tests: `sim_input_pdo_counter` (counts what the simulated bus carried, stops and is not reset on a timeout), shared fixtures (accepted, RPDO refused, not a word, clash; J1939 accepted, not a word, clash), `j1939_engine_counts_messages` (source filter, TP message once, timeout)

## 2. PC tools

- [x] 2.1 `contract.py`, both schema copies: the field and its checks, same messages as the bridge (shared fixtures run by both)
- [x] 2.2 Variable list: `<node>_tpdo<N>_count` and `<network>_<message>_count`, `UINT`; the Modbus map, Node-RED **canworks in** and address suggestions pick it up as a located value; `targets.py`: not a CODESYS field
- [x] 2.3 `docexport.py` / `docwriter.py`: "Frame counter" on the PDO and "Message counter" on the J1939 message, and the I/O cross-reference
- [x] 2.4 Local runtime: nothing to do (it runs the bridge image)

## 3. Configurator

- [x] 3.1 TPDO settings: "Counter" row with a "Frame counter" `%IW` field and Suggest (always shown, not tied to `timeout_ms`), not shown on CODESYS projects; J1939 rx message: "Message counter" next to its status bit
- [x] 3.2 Page tests: suggest, clash in Problems, save, clear (field removed); J1939 suggest, a bit refused, save

## 4. Docs

- [x] 4.1 `docs/config.md` (TPDO fields), `docs/j1939.md` (rx fields), `docs/modbus-bridge.md` (timing: counters show merged frames; `CAN_RECEIVE` for every value), `docs/configurator.md`
- [x] 4.2 README row "Can a CAN message go unseen?": received PDOs, CAN messages and J1939 PGNs can count their frames
- [x] 4.3 Version bump (minor, 0.138.0); release notes from the PR

## 5. Archive

- [ ] 5.1 `openspec archive add-receive-counters --yes` on the branch; one PR with spec, code and archive; squash auto-merge

## 6. Hardware check (Pi, after merge)

- [ ] 6.1 Simulated node with a 10 ms event TPDO on the Pi's CAN interface, `counter_location` set, OpenPLC at the default poll: the counter grows about 100 per second and matches `candump` over 60 s; the value alone changes far less often
