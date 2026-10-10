# Tasks

## 1. Spike

- [x] 1.1 On the simulated bus, check that a frame one simulated device sends reaches the RPDOs of the other simulated devices (not only the master), with a consumer RPDO set up by hand through startup SDOs. Note the result here. Result: yes; a simulated consumer receives the simulated producer TPDO with the RPDO the master configures (sim_pdo_link, test/sim/sim_tests.cpp), so no startup SDO stand-in was needed.
- [x] 1.2 Check dcfgen's output when an EDS RPDO is neither in the YAML nor `enabled: false` (the `kept_rpdos` path): no write to 0x1400+n-1/0x1600+n-1 for the node and no master TPDO for it. Verify with `canopen_check --dump-writes` on a fixture; note the result here. Result: dcfgen writes nothing to the linked RPDO and makes no master TPDO on the link's COB-ID (cases-links.json base: only the producer sends on 0x18A). It does give the master a TPDO for every node RPDO its model keeps enabled with an EDS default mapping, on that RPDO's EDS default COB-ID; that holds for switched-off RPDOs too and is unchanged behaviour (design.md, Implementation notes).
- [x] 1.3 Check how the slave stack reports a heartbeat consumer timeout on a simulated device (EMCY 0x8130, 0x1029 sub 1 reaction) and that monitoring starts only at the first heartbeat received. Note the result here. Result: Lely's slave sends EMCY 0x8130 on a watch timeout and applies 0x1029 sub 1 (sim_pdo_link_loss); the consumer resumes after the producer is back, without a boot loop.

## 2. Plugin configuration

- [x] 2.1 `config.h`: `LinkConsumer` (node, rpdo, transmission, event timer, mapping, entries), `LinkConfig` (number, name, producer node and TPDO, consumers, keep on PLC stop, resolved COB-ID) in `Config::links`; `HeartbeatWatch` (node, timeout_ms, resolved sub-index) in `NodeConfig::heartbeat_watch`; `NodeConfig::linked_rpdos`.
- [x] 2.2 `config.cpp`: parse `links` (v1 top level, v2 per CANopen master network; rejected on slave, J1939 and plain networks) and `heartbeat_watch`, `check_known` lists, defaults (`name`, `on_plc_stop`), rejection of consumer entries with `iec_location`. Verify: unit tests per field and an unchanged config.
- [x] 2.3 Cross checks after nodes are read: producer TPDO configured, consumer node and RPDO not in `rx_pdos` and in one link only, producer is not a consumer, TPDO feeds at most one link; `report_unlocated` accepts entries of linked TPDOs; `check_node_ids` COB-ID map with link owners and listeners (message names the link); `check_sdo_overrides` covers 0x1016 with `heartbeat_watch` and 0x1400-0x17FF writes on linked RPDOs. Verify: unit tests for each message in the spec.
- [x] 2.4 `heartbeat_watch` rules: watched node configured, not self or master, has a heartbeat (config or EDS 0x1017), default timeout, timeout above the watched period. Verify: unit tests.

## 3. EDS checks

- [x] 3.1 `eds_check.cpp`: producer layout (config entries, or EDS default mapping incl. unused and dummy objects), consumer layout (entries or default mapping, `mapping` resolution as `check_mapping`), position-by-position bit lengths, totals, dummy entries against `[DummyUsage]`, same-size type warning, RPDO-mappable, AccessType and DataType of consumer objects.
- [x] 3.2 Consumer communication checks: RPDO objects exist, read-only COB-ID equal to the link's (message suggests the producer `cob_id`), read-only transmission/deadline equal when set, effective synchronous type needs SYNC.
- [x] 3.3 0x1016 capacity: count entries of the EDS 0x1016, subtract the one dcfgen uses for the master, resolve each watch's sub-index the way dcfgen does (entry naming that node, else first unused).
- [x] 3.4 Load-time notes and warnings: link summary (COB-ID, producer, consumers, latency in SYNC periods for synchronous ends); kept links with synchronous types or nodes with `heartbeat_consumer`. Verify: unit tests with fixture EDS files (one fixed-mapping consumer, one with a read-only COB-ID).

## 4. Device configuration

- [x] 4.1 `dcf_gen.cpp` `emit_pdos`: leave `linked_rpdos` out of the YAML and out of the switch-off list.
- [x] 4.2 `add_link_writes` in `generate_device_config` after `add_explicit_pdo_writes`: COB-ID off, sub 2, sub 5, mapping, COB-ID on, skipping `ro_pdo_comm`; heartbeat watch 0x1016 writes after dcfgen's 0x1016 handling. Input hash gets a links and watch key; bump the post-processing tag.
- [x] 4.3 `canopen_check --dump-writes` prints the link writes in download order. Verify: master DCF byte-identical with and without links; node downloads of every example config unchanged; config stamp changes when a link changes.

## 5. Runtime behaviour

- [x] 5.1 `network.cpp` `StopNodes`: skip the producer and consumers of links with `"on_plc_stop": "keep"`; one log line naming the nodes kept and their links.
- [x] 5.2 Loss log: when a node that produces for a link is lost, one info line naming the links and consumer RPDOs that no longer get data; nothing more until it is back.

## 6. Tests

- [x] 6.1 In-process simulation: producer counter on a linked TPDO, consumer echo through an expression in its own TPDO; the PLC reads both; the producer entry without a location writes nothing to the image.
- [x] 6.2 Same with a dummy position and with a device-mapped consumer.
- [x] 6.3 Power off the producer: consumer with `heartbeat_watch` sends EMCY 0x8130 and follows its 0x1029; master logs the link loss; power on: link carries data again. Consumer power cycle: link resumes after its boot.
- [x] 6.4 PLC stop with a kept event-driven link: link nodes stay OPERATIONAL and data still moves on the simulated bus; other nodes PRE-OPERATIONAL. Synchronous link: SYNC 10 ms, consumer applies at the next SYNC.
- [x] 6.5 Regression: all existing tests pass; master DCFs and node downloads of the example configs unchanged. New tests go into existing CI jobs and stay within the CI time baseline.

## 7. Tools

- [x] 7.1 JSON Schema v1 and v2 (shared `link` and `heartbeat_watch` definitions), `contract.py` with the same rules and messages; cases in `test/fixtures/config/cases.json` and `cases-v2.json` for each rejection and warning; parity test.
- [x] 7.2 `dcfexport.py` `plugin_downloads`: linked RPDO and heartbeat watch writes; comparison with `canopen_check --dump-writes` for the new fixtures.
- [x] 7.3 `dbcexport.py`: consumer receivers on the producer message and per signal, link comment.
- [x] 7.4 `docexport.py`: Links table, COB-ID map consumers, consumer node sheets, layout warnings; bus load unchanged.
- [x] 7.5 `simfile.py` and the simulator's file check: objects written by linked RPDOs refuse value sources, naming the link.
- [x] 7.6 Configurator: Links page (producer and consumer pickers, layout grids, dummy and device mapping, watch producer checkbox, delete confirmation), heartbeat watch list on the node page, producer TPDO marked as feeding a link with optional addresses, links in the online view; page tests for each configurator scenario. Deploy tool minor version bump.
- [x] 7.7 Example config under `config/` with a simulated producer and consumer link, swept by the browser example test.

## 8. Docs

- [x] 8.1 docs/config.md: "PDO links" section (fields, layout rules with a dummy example, COB-ID rules, loss and reboot, PLC stop, SYNC timing, fixed-mapping devices), `heartbeat_watch` in Node options, both in "Compatibility rules" and "What is rejected".
- [x] 8.2 docs/configurator.md (Links page, heartbeat watch), docs/simulator.md (linked PDOs, producer power off), docs/network-docs.md (Links table), docs/deploy.md (link checks and warnings).
- [x] 8.3 README: bullet under "CANopen on the PLC" ("PDO links: one node's TPDO feeds other nodes' RPDOs directly, CiA 301 producer/consumer, optionally running on while the PLC is stopped").

## 9. Hardware (runtime device, CAN adapter, two real nodes)

- [ ] 9.1 Link an event-driven TPDO of one real node to an RPDO of a second real node with the configurator, upload, and check in the Trace view that only the producer sends on the link's COB-ID and that the consumer's object follows (read it in the object dictionary view).
- [ ] 9.2 Stop the PLC with `"on_plc_stop": "keep"` on the link: the consumer keeps following the producer; with `"follow"`: both go PRE-OPERATIONAL. Start the PLC again: the link resumes after the boot.
- [ ] 9.3 With `heartbeat_watch` on the consumer, unplug the producer: the consumer sends EMCY 0x8130 and reacts per its 0x1029 setting; plug it back: the master boots it and the link resumes. Put the template project back afterwards.

Run on 2026-10-10 on the Pi bench (managed Docker runtime, main at 0a8ca26, tools 0.56.0) with its one real CANopen I/O node (node 23, 500 kbit/s). That node has no 0x1003, 0x1014, 0x1016 or 0x1029, so where a step needs them or a second device, simulated devices ran on the same real can0 bus next to it (the plugin's `simulate: true` nodes, or a standalone `canworks-sim --real-bus` in the runtime container).
- 9.1: link from the real node's TPDO 1 (0x2090:1, event timer 100 ms) to a simulated consumer's RPDO 2
  (0x6411:1), uploaded with canworks-deploy: 0x197 seen 30 times in 3 s (one sender, the master sends nothing on
  it), the consumer's 0x1401:1 read 0x197 and its 0x6411:1 equal to the producer's value; also through
  canworks-bridge. Checked with candump and SDO reads rather than the configurator's Trace and OD views; the second
  real node was simulated.
- 9.2: consumer in a standalone `canworks-sim` so it outlives a PLC stop: with `"keep"` the PLC stop left both nodes
  OPERATIONAL (log "left running for their PDO links") and the 0x197 frames went on; with `"follow"` both went
  PRE-OPERATIONAL and 0x197 stopped; after the next start the link ran again.
- 9.3: `heartbeat_watch` on the consumer, real producer unplugged for about 10 s: the consumer went PRE-OPERATIONAL
  2 s later per its 0x1029; its EMCY 0x8130 could not reach the bus, because with the only other physical node
  unplugged nothing acknowledged the Pi's frames (can0 error-passive), a limit of this bench. Plugged back: the
  master booted both nodes and the link ran again. To repeat with a third physical node.
