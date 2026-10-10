## 1. Lely text layer and build

- [x] 1.1 Confirm at the pinned ref (`scripts/build-lely.sh`, `88848aa2`) that `liblely-co` exports `co_gw_txt_create`, `co_gw_txt_send`, `co_gw_txt_recv`, `co_gw_txt_set_send_func`, `co_gw_txt_set_recv_func`; add a CI step that checks the symbols with `nm -D` after the Lely build
- [x] 1.2 `plugin/CMakeLists.txt`: `check_symbol_exists(co_gw_txt_create lely/co/gw_txt.h ...)`; define `CANWORKS_WITH_CIA309` when present; build the gateway sources only then
- [x] 1.3 A small C++ wrapper (`plugin/src/can/cia309_text.h`/`.cpp`) around one `co_gw_txt_t`: feed a line, get parsed `co_gw_req` through the send callback, format a `co_gw_con_*`/`co_gw_ind_*` into text through the receive callback; RAII create/destroy
- [x] 1.4 Unit tests for the wrapper: every service in the design's table parsed with its fields, every answer and indication formatted, a syntax error giving `ERROR: 101`, lines split over several reads

## 2. Config

- [x] 2.1 `config.h`/`config.cpp`: parse top-level `cia309` (version 2) and `master.cia309` (version 1): `port`, `bind` (loopback only), `max_clients`, `allow_changes`, `allow_force`, `nets`, `default_net`; errors name the field; without `CANWORKS_WITH_CIA309` reject `cia309` with the missing-Lely message
- [x] 2.2 Schema (`schema/canworks.v1.schema.json`, its v2 counterpart and the deploy package's copy) and `tools/deploy/canworks/contract.py` apply the same rules
- [x] 2.3 Config fixture cases (`test/fixtures/config/cases.json`): valid object, non-loopback bind, unknown field, `nets` with an unknown network, duplicate numbers, `default_net` not in `nets`

## 3. Hub and bus thread

- [x] 3.1 `DiagRequest`: new ops `pdo_read` (node, TPDO number), `lss_store` (address), and a `from_cia309` flag so log lines say where a request came from; `force` set from `allow_force`
- [x] 3.2 `network_diag.cpp`: `pdo_read` answers the values the master last received in that TPDO (entry count, raw values) or "PDO not configured"; no new SDO
- [x] 3.3 `network_lss.cpp`: `lss_store` (switch selective, store configuration, switch all to waiting) under the existing LSS lock
- [x] 3.4 `DiagHub` event queue: bounded (1024), short mutex, enabled by an atomic flag while a gateway session is open; push EMCY, boot-up, NMT state change and heartbeat loss where the bus thread already records them; per-reader cursor with lost count
- [x] 3.5 Unit tests: `pdo_read` on a configured and an unmapped TPDO, `lss_store` against the LSS fake, event queue overflow and the flag off (no events recorded)

## 4. Gateway server and dispatcher

- [x] 4.1 `plugin/src/can/cia309_server.cpp`/`.h`: own thread and poll loop; plain listener on `bind`:`port` with the 10 s retry; accepted hand-overs from `DiagServer` (socket, `TlsConn`, peer) through a queue; per-session input/output buffers, 16 KiB line limit, 256 KiB output cap with the 10 s rule, `max_clients` over both kinds
- [x] 4.2 `plugin/src/canopen/cia309_dispatch.cpp`/`.h`: `co_gw_req` to `DiagRequest` per the design's table (network numbering, default net and node, SDO timeout, node 0 for NMT as one request per configured node), answers to `co_gw_con_*`, guard refusals to `ERROR: 102` with the reason logged, not-served services to `ERROR: 100`, at most 8 outstanding per session, command timeout `ERROR: 103`
- [x] 4.3 Per-session LSS selection for `lss_switch_sel`, cleared on `lss_switch_glob 0` and at session end
- [x] 4.4 Notifications: fan the hub events out to sessions as `co_gw_ind_*`; boot-up indication on/off per session; `#` line with the lost count
- [x] 4.5 `diag.cpp`: the `cia309` op after login (refusals `cia309 gateway not configured`, `too many gateway clients`), hand the client over and drop it from the diagnostics client list; `cia309` in the login answer; status part with the gateway's address and sessions
- [x] 4.6 `engine.cpp`: create and start `Cia309Server` next to `DiagServer` when `cia309` is set; make the networks create their `DiagHub` when either `diagnostics` or `cia309` is set (with `cia309` alone: plain port only, no diagnostics listener); stop it before the networks
- [x] 4.7 Unit tests against a fake hub: each served service, each refusal with and without `allow_changes`/`allow_force`, OPERATIONAL nodes, unconfigured node NMT, numbering with and without `nets`, pipelining limit, slow reader closed, hand-over from a TLS diagnostics connection

## 5. Bridge

- [x] 5.1 `bridge_host.cpp`: gateway sessions in the bridge status part; confirm gateway requests never touch the watchdog feed
- [x] 5.2 `test/bridge/bridge_host_tests.cpp`: a gateway client alone lets the watchdog run out; gateway NMT follows the gateway guards

## 6. PC tools

- [x] 6.1 `tools/deploy/canworks/cia309.py`: standard-library client (connect plain or through a logged-in `diag.Client`, send lines, read answers and notifications)
- [x] 6.2 `cli.py`: `canworks-diag gateway` with `--listen`, `--listen-any`, `--exec`, `--list`, interactive prompt, `--network` as default net; "too old" message on `unknown op`; `status` prints the gateway line
- [x] 6.3 Configurator: CiA 309-3 gateway part in Online access (`server.py`, the Online access page), Check messages from the contract
- [x] 6.4 HTML network docs: network numbers and gateway RPDO numbers per node TPDO
- [x] 6.5 Tests: `tools/deploy/tests` for the client, the tunnel against `tests/fake_diag.py` (extended with the `cia309` op), CLI options, configurator settings and Check
- [x] 6.6 Deploy tool version bump

## 7. CI integration on the simulated bus

- [x] 7.1 `test/cia309/run.sh`: plugin on vcan with the device simulator; Python client over the loopback port and through `canworks-diag gateway`: SDO read and write, segmented read of 0x1008, NMT with holds, `r p`, simulator EMCY and boot-up notifications, LSS find and set node on the simulator's unconfigured device, refusals (read-only, OPERATIONAL without force, unserved services)
- [x] 7.2 The same client against `canworks-bridge` with `examples/modbus-bridge` plus a `cia309` object, while a Modbus client writes; check the watchdog is unaffected
- [x] 7.3 Scan timing: repeat the trace test's scan-time check with 4 gateway sessions reading in a loop
- [x] 7.4 Add the step to `.github/workflows/ci.yml` next to `test/lss/run.sh`; add the new tool tests to the shard times file if needed (the test needs no vcan: it runs on the simulated bus as the ctest test `cia309_gateway` in the plugin job, with `cia309_tests`; the Lely symbol check is a step of the build-plugin action)
- [x] 7.5 Run `scripts/check-banned-words.py --files` and fix findings

## 8. Docs

- [x] 8.1 New `docs/cia309-gateway.md`: what it is, config, the two ways in, network numbering, service table with what is refused and why, guards, notifications, limits, examples with a Python socket and with `canworks-diag gateway`, security
- [x] 8.2 `docs/diagnostics.md`: the `cia309` op in the protocol table, the login answer's `cia309`, `canworks-diag gateway`, the security section (plain gateway port loopback only, remote through the channel)
- [x] 8.3 `docs/modbus-bridge.md` (gateway on the bridge, watchdog), `docs/config.md` (`cia309`), `docs/configurator.md` (Online access part), `docs/network-docs.md` (numbers)
- [x] 8.4 README: one feature line for the CiA 309-3 gateway, link to the new page
- [x] 8.5 When `add-remote-access` has landed: one line in `docs/remote-access.md` that `canworks-diag gateway` works over the link

## 9. Hardware (Pi and bench, separate from CI)

- [ ] 9.1 Pi: install the updated plugin with `cia309` in the template project; the log shows the listener and the numbering; `[1] 1 N r 0x1018 1 u32` from a Python script on the Pi reads a real node's vendor ID
- [ ] 9.2 Pi: from the engineering PC through `canworks-diag gateway`, SDO write to a PRE-OPERATIONAL node, NMT stop refused on an OPERATIONAL node without `allow_force`, EMCY notification when the node reports a fault
- [ ] 9.3 Pi: 4 gateway sessions reading in a loop for 60 s at full bus load; PLC scan average and maximum unchanged, no lost node
- [ ] 9.4 Bench: LSS find and set node ID on a real device without a node ID through the gateway, without store; power cycle undoes it
- [ ] 9.5 Bench: `canworks-bridge` on the Pi with a real node and the gateway; Modbus writer stops, watchdog takes outputs off while a gateway client keeps reading
- [ ] 9.6 Put the template project back on the Pi (main plugin, original project, node operational)
