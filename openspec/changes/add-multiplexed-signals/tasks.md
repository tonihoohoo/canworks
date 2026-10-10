# Tasks

Each group lands its own tests. Shared fixture files make the plugin and the PC tools give the same messages.

## 1. Shared signal model

- [x] 1.1 Fixture files under `test/fixtures/` for multiplexing: simple, extended (nested switch, ranges), every check error and warning of `can-multiplexed-signals` with its expected message, per-page overlap cases, page lists for `all`/`rotate`.
- [x] 1.2 `plugin/src/can/mux.*`: parse `multiplexer`/`mux` into a flat condition table built at start (switch index + sorted value ranges per signal); `active()` with no allocation; page enumeration with the 64-page cap; per-page overlap and needed bytes. Unit tests against 1.1.
- [ ] 1.3 `canworks/raw/mux.py`: the same rule, page list, overlap and checks; tests against 1.1.

## 2. Raw CAN in the plugin

- [x] 2.1 `raw/config.*`: parse `multiplexer`, `mux`, `valid_location` (rx only), `pages` (tx); switch-location rules per mode; per-page overlap warning and short-frame need.
- [x] 2.2 `raw/engine.cpp` receive: active signals only, hold others, unknown-page counter, per-signal valid bits with `timeout_ms`; sim-bus tests for the scenarios of "Receiving multiplexed messages", "Unknown pages on receive" and "Page validity bits".
- [x] 2.3 `raw/engine.cpp` send: `program`/`all`/`rotate`, page-wise on change, trigger by mode, `unknown_page` status; sim-bus tests for the send scenarios.
- [ ] 2.4 Diagnostics status: `unknown_pages` per rx entry, `unknown_page` per tx entry; online view rows.

## 3. J1939 in the plugin

- [x] 3.1 `j1939_config.*`: same fields (`valid_location` exists already), overlap error per page, `length` per page, `pages` on `tx`.
- [x] 3.2 J1939 receive (multi-packet included) and send by page, request answers by mode; sim-bus tests incl. a BAM multiplexed PGN.

## 4. Schema and contract

- [ ] 4.1 `canworks.v2.schema.json` and `canworks-sim.v2.schema.json`: the new optional fields.
- [ ] 4.2 Python contract checks (`raw/contract.py`, J1939 contract) call 1.3; parity corpus files run in both plugin and PC tools tests.

## 5. DBC import and export

- [ ] 5.1 `raw/dbc.py read_dbc` and `j1939/dbc.py`: import switches and `mux` (ids folded into ranges); "several switches but no SG_MUL_VAL_" problem; remove the "multiplexed left out" note and the J1939 skip.
- [ ] 5.2 `dbcexport.write`: `M`, `mN`, `mNM`, `SG_MUL_VAL_`; golden files; cantools strict round trip for raw and J1939 (simple and extended).

## 6. Configurator

- [ ] 6.1 CAN messages page: Switch and Page columns, valid location for receive, sort by page, `pages` choice on send, Suggest addresses per mode.
- [ ] 6.2 Bit grid page picker and per-page overlap marks; same on the J1939 page.
- [ ] 6.3 DBC import pickers show switches and pages; browser test importing a multiplexed message and saving with no problems.

## 7. Trace, inspector, simulator

- [ ] 7.1 `raw/decode.py RawDecoder` and `bustrace/j1939.py J1939Decoder`: decode by page with our own rule (no `cantools.decode`), page in the row text, unknown pages shown; DBC messages keep multiplexing. Test that a multiplexed J1939 DBC no longer decodes inactive pages.
- [ ] 7.2 Frame inspector marks switch and active bits only; graph series take points only from active frames.
- [ ] 7.3 Simulator: `raw_send` multiplexing and `pages` (`all` default, `rotate`) in the plugin's raw devices and standalone simulator; `canworks-j1939-sim` sends multiplexed DBC messages page by page, `--mux rotate`.

## 8. Docs, examples, release

- [x] 8.1 `docs/raw-can.md` and `docs/j1939.md`: multiplexing section, `pages` modes, valid bits, a CAN_RECEIVE + CAN_GET_BITS example for hand decoding; remove the "not supported" limits.
- [x] 8.2 README: limits lines for raw CAN and J1939 updated, feature bullet.
- [x] 8.3 `examples/raw-can/`: a simulated multiplexed status message (made-up identifiers) received by the PLC.
- [ ] 8.4 PC tools minor version bump.
- [ ] 8.5 CI: tests run in existing jobs; compare wall time and summed job time against the baseline in the PR.

## 9. Hardware (bench, when the Pi is reachable)

- [ ] 9.1 PC adapter as a multiplexed raw device (`canworks-sim` standalone, `pages` `all`), PLC on the Pi receives both pages with valid bits; stop one page and see its valid bit drop.
- [ ] 9.2 PLC sends a multiplexed message in `program` and `rotate` modes; the PC trace decodes the pages.
