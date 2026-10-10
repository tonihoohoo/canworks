## Context

How PDOs are configured today (all in `plugin/src/canopen/dcf_gen.cpp` and `plugin/src/can/config.cpp`):
- `make_dcfgen_yaml` passes each node's `tx_pdos` and `rx_pdos` to dcfgen (`emit_pdos`). dcfgen writes the node side (COB-ID off, parameters, mapping, COB-ID on) into `node_<id>.bin` and creates the matching master side in `master.dcf`: one master RPDO per node TPDO, one master TPDO per node RPDO. PDOs of the EDS that the config does not use are switched off, except those with a read-only COB-ID (`kept_tpdos`/`kept_rpdos`).
- `generate_device_config` then post-processes each node's download: drops read-only PDO sub-index writes (`ro_pdo_comm`), adds explicit parameters (`add_explicit_pdo_writes`), drops dcfgen's 0x1016 clear when `heartbeat_consumer` is unset, appends TIME COB-ID, RPDO deadlines, 0x60C2, startup SDOs, and last the 0x1020 stamp, which is a hash over everything before it.
- `check_node_ids` refuses two PDOs on one COB-ID; `resolve_auto_cob_ids` gives `"auto"` PDOs above 4 a free COB-ID.
- `check_mapping` in `eds_check.cpp` resolves `device_mapping` and checks entries of a fixed mapping against the EDS default mapping.
- A PDO entry may already have no `iec_location` when only a gateway route uses it (`has_location`, `report_unlocated`).
- A node's `heartbeat_consumer` makes dcfgen write one 0x1016 entry watching the master: an entry that already names the master, else the first unused one (time 0 or node ID 0/above 127).
- `Network::StopNodes` sends the `on_plc_stop` command to every node that is up, then the network closes.
- Simulated devices are Lely slave stacks on an in-process virtual bus (`sim_device.h`); any RPDO the master configures on them works as on a real device.

CiA 301 producer/consumer: a PDO is a broadcast frame. Any RPDO whose COB-ID equals a TPDO's COB-ID receives it; the receiver maps the bytes in order onto its own objects. Only one node may transmit on a COB-ID. The master's role is limited to configuring both ends and starting them.

## Goals / Non-Goals

**Goals:**
- Express a TPDO → RPDO(s) link between nodes of one master network in `canworks.json`, with the master configuring both ends at boot.
- Refuse at load every link that cannot work on the bus, against both EDS files, with the same messages in the plugin, the deploy tool and the configurator.
- Let a consumer supervise its producer itself (node-to-node 0x1016).
- Define what happens on loss, reboot, PLC stop and with SYNC, and let a link keep running while the PLC is stopped.
- Keep every existing config's files and behaviour unchanged.

**Non-Goals:**
- Links between networks (that is what the gateway does), links on slave, J1939 or plain CAN networks.
- MPDO (CiA 301 multiplexed PDOs) and SRDO (CiA 304); the README limits stay.
- Master-side reaction to a lost producer beyond logging (see open question 1).
- Reading a consumer's received values back for diagnostics.
- Keeping the master's heartbeat or SYNC running while the PLC is stopped.

## Decisions

1. **The producer TPDO stays in `tx_pdos`; the link names it.** `from: { "node": 10, "tpdo": 1 }` refers to the `tx_pdos` entry with that number. Every TPDO setting (COB-ID including `"auto"`, transmission, inhibit time, event timer, mapping, `timeout_ms`) keeps one place and one meaning, and the master keeps its RPDO for it, so the PLC can read the value and the receive timeout and late PDO check keep working. A TPDO feeds at most one link; all its consumers are listed in that link's `to`. Alternative: a self-contained link that also defines the TPDO. Rejected: it duplicates the TPDO fields and their EDS checks, and a TPDO could then be defined twice.

2. **The consumer RPDO is defined only in the link.** `to[]` items give `node`, `rpdo` (number), optional `transmission`, optional `event_timer_ms` (sub-index 5, the consumer's CiA 301 deadline), and `entries` (index, subindex, type, no location) or `"mapping": "device"`. The RPDO number SHALL NOT also be in that node's `rx_pdos`. Alternative: an `rx_pdos` entry with a `from` field. Rejected: `rx_pdos` means "fed by the master from `%Q`", and dcfgen would create a master TPDO on the producer's COB-ID, a second transmitter on one COB-ID.

3. **`iec_location` optional on a linked TPDO's entries.** `report_unlocated` accepts entries without a location when their TPDO feeds a link, as it does for gateway routes. With a location the PLC sees the value as today; without one the master still receives the PDO (cheap, and it keeps `timeout_ms` and the diagnostics working) but writes nothing to the image.

4. **The plugin writes the consumer RPDO itself, not dcfgen.** Linked RPDO numbers go into a new `NodeConfig::linked_rpdos` set that `emit_pdos` treats like `kept_rpdos` (not listed, not switched off), so dcfgen creates no master TPDO. A new step `add_link_writes` in `generate_device_config`, after `add_explicit_pdo_writes` and before TIME COB-ID, deadlines and startup SDOs, appends for each consumer RPDO: 0x1400+n-1 sub 1 = COB-ID | 0x80000000, sub 2 (if `transmission`), sub 5 (if `event_timer_ms`), 0x1600+n-1 sub 0 = 0, sub 1..k, sub 0 = k (not for a device mapping), then sub 1 = COB-ID. Read-only sub-indices are skipped by the existing `ro_pdo_comm` rule. Because the stamp is a hash over the download, `config_check` sees a link change. The input hash gets a `links` key and the post-processing tag is bumped, so cached output is regenerated. The master DCF does not change.

5. **Layout check: same bit lengths, position by position.** The producer layout is the TPDO's mapped objects in order: the config `entries`, or the EDS default mapping (unused and dummy objects included) for a device-mapped TPDO. The consumer layout (its `entries`, or its EDS default mapping) must have the same number of positions with the same bit length each, and so the same total. Dummy entries (0x0001-0x0007, allowed by the consumer EDS `[DummyUsage]`) take a position without an object, for data the consumer does not need. A different data type at the same size (INTEGER16 into UNSIGNED16) is a warning, not an error, because CiA 301 copies bits. A consumer shorter or longer than the producer is refused: CiA 301 lets a device reject a too-short PDO (EMCY 0x8210) and optionally signal a too-long one (0x8220), so a mismatch is a bus fault, not a configuration. Alternative: compare only total length. Rejected: it accepts a 16-bit value split across two unrelated 8-bit objects, which is almost always a mistake (open question 2).

6. **Other consumer checks** (in `eds_check.cpp`, mirrored in `contract.py`): the RPDO's 0x1400/0x1600 objects exist; each entry object exists, is PDO-mappable, has AccessType wo, rw or rww and the configured DataType; `"mapping": "config"` on a fixed consumer mapping is refused as for any PDO; a read-only consumer COB-ID must equal the producer's resolved COB-ID (the message names the `cob_id` to set on the producer); an effective synchronous consumer transmission type (config or EDS) needs a master that produces SYNC, as the existing rule for any PDO; producer and consumer differ and are configured nodes of the same network; one consumer RPDO belongs to one link.

7. **COB-ID clash check includes links.** `check_node_ids` registers each link's COB-ID once with the producer as owner and its consumers as allowed listeners; any other PDO, raw message or reserved COB-ID on it is a clash, named with the link. `"auto"` resolution is unchanged because only the producer has a COB-ID of its own; a consumer RPDO's CiA 301 default COB-ID was already in the taken set as part of the node's predefined set.

8. **Heartbeat watch is its own node field.** `heartbeat_watch: [{ "node": 10, "timeout_ms": 300 }]` on the watching node. `timeout_ms` defaults to the watched node's heartbeat timeout as the master uses it (`heartbeat_timeout_ms`, else three times its heartbeat period). The plugin appends one 0x1016 write per entry after dcfgen's: an entry that already names that node, else the first unused entry that dcfgen did not take for the master. Refused at load: the watched node has no heartbeat (guarding, or an effective 0x1017 of 0), `timeout_ms` is not above its heartbeat period, the node watches itself or the master (use `heartbeat_consumer`), or the EDS has no 0x1016 or too few writable entries. A link does not add a watch by itself: the master writes only what the config says, and what the consumer does on a heartbeat event is device-specific (0x1029 sub 1 via the existing `error_behavior`, usually EMCY 0x8130). The configurator offers it as a "watch producer" checkbox in the link row, which edits `heartbeat_watch`.

9. **Loss and reboot need no new runtime machinery.** A lost producer is handled by the existing supervision; its consumers keep their last received values unless they have a deadline (`event_timer_ms`, the device reacts on expiry, EMCY 0x8250) or a heartbeat watch. The master logs once per loss which links lose their data (`node 10 lost: link stick_to_valves feeds node 20 RPDO 2, node 21 RPDO 1`). A rebooted producer or consumer is configured again by the normal boot, which includes the link writes, and the link resumes when both are OPERATIONAL. A consumer that leaves OPERATIONAL through its own error behaviour is booted again by the existing background recovery; CiA 301 heartbeat consumption starts again only at the first heartbeat from the producer, so this does not loop.

10. **PLC stop: per link `on_plc_stop`.** `"follow"` (default): the link's nodes get the master's `on_plc_stop` command like every node, so the link stops when they leave OPERATIONAL (with `"keep"` on the master everything keeps running, as today). `"keep"`: `StopNodes` sends no NMT command to that link's producer and consumers; every other node gets the master's command. The network still closes, so the master's heartbeat and SYNC stop. The plugin therefore warns when a kept link has a synchronous producer or consumer type (it stops with SYNC) and when one of its nodes has `heartbeat_consumer` (it sees the master vanish and reacts per 0x1029). The scan watchdog closes only master TPDOs and does not touch links. At the next PLC start the master boots and configures the nodes as usual, so the link pauses for the boot.

11. **SYNC.** A synchronous producer TPDO is sent after every n-th SYNC; a synchronous consumer RPDO applies its data at the next SYNC (one SYNC period of latency, all consumers in step); event-driven types on both ends pass data immediately. With `"sync_source": "plc_cycle"` a synchronous link runs at the PLC frame rate and stops with the PLC. Docs recommend event-driven types (254/255 with an event timer on the producer) for links that must survive a PLC stop.

12. **Tools reuse the plugin's rules.** `contract.py` implements decisions 5-8 with the same messages and the shared fixtures prove parity. DCF export follows the plugin download (decision 4 and 8 writes get ParameterValue). The DBC keeps one message per COB-ID: the producer TPDO message gets the consumers as extra receivers and a comment naming the link and the consumer objects. The HTML docs list consumers in the COB-ID map, add a Links table per network and show linked RPDOs on node sheets. Bus load does not change.

13. **Simulator.** Simulated devices need no new PDO code; the work is the simulation file check (an object a linked RPDO writes counts as written, so a value source on it is refused, naming the link) and a CI scenario: producer counter → consumer object, consumer echoes it in its own TPDO, the PLC reads both. This runs inside an existing simulation test job.

## Example

```json
"nodes": [
  { "node_id": 10, "name": "stick", "eds": "stick.eds", "heartbeat_ms": 100,
    "tx_pdos": [ { "transmission": 254, "event_timer_ms": 50, "entries": [
      { "index": "0x6401", "subindex": 1, "type": "INTEGER16", "iec_location": "%IW100" },
      { "index": "0x6401", "subindex": 2, "type": "INTEGER16" } ] } ] },
  { "node_id": 20, "name": "valves", "eds": "valves.eds", "heartbeat_ms": 100,
    "heartbeat_watch": [ { "node": 10 } ], "error_behavior": { "1": 0 } }
],
"links": [
  { "name": "stick_to_valves", "from": { "node": 10, "tpdo": 1 },
    "to": [ { "node": 20, "rpdo": 2, "transmission": 255, "event_timer_ms": 200, "entries": [
      { "index": "0x6411", "subindex": 1, "type": "INTEGER16" },
      { "index": "0x0003", "subindex": 0, "type": "INTEGER16" } ] } ],
    "on_plc_stop": "keep" }
]
```

Node 20's RPDO 2 takes 0x18A; the first value drives its analog output 1, the second is skipped by a dummy entry. The PLC reads the first value in `%IW100`. Node 20 watches node 10's heartbeat for 300 ms and goes PRE-OPERATIONAL on loss. The link keeps running while the PLC is stopped.

## Risks / Trade-offs

- [A consumer with a wrong device mapping receives garbage silently] → layout check against both EDS files at load; the HTML docs and DBC show the byte layout of both ends.
- [Users expect the master to stop consumers when the producer is lost] → documented per decision 9; deadline and heartbeat watch are the CiA 301 tools; open question 1.
- [`"keep"` links run with no PLC supervision at all] → opt-in per link, warnings for the cases that cannot work, docs say the safety of that path is the devices' (their deadlines and error behaviour).
- [Devices with few 0x1016 entries] → capacity check at load names the EDS and the count.
- [dcfgen behaviour when an EDS RPDO is neither listed nor switched off] → spike 1.2 before relying on the `kept_rpdos` path.

## Migration Plan

None: new optional fields within `schema_version` 1 and 2; configs without them generate the same files and behave exactly as before. An older plugin reading a file with `links` warns about the unknown field and runs the nodes without the links (consumer RPDOs stay as their EDS gives them). Rollback is deleting the fields.

## Open Questions

1. Should the master offer `on_producer_loss` (hold the link's consumers PRE-OPERATIONAL while the producer is lost)? Left out: it makes the master part of a path meant to work without it.
2. Allow bit-level layouts that differ from the producer's positions (one 16-bit value into two 8-bit objects) or a consumer shorter than the producer? Refused for now; could become an explicit `"layout": "bits"` option.
3. Should a new link default to a heartbeat watch on its producer? Not in the config; the configurator pre-ticks "watch producer" when the producer has a heartbeat. Revisit after field use.
4. Should a kept link also keep the master's heartbeat and SYNC running after PLC stop? Needs the bus thread to outlive the PLC session; a separate change if asked.
5. Should the diagnostics status list links with derived state (producer up, consumers up, time since last producer PDO)? The online view derives it from existing node status for now.

## Implementation notes

Defaults taken for the open questions and for what the decisions left open:

- Open questions 1, 2 and 4: as proposed. No `on_producer_loss`; a consumer layout must match the producer position by position (no `"layout": "bits"`); a kept link does not keep the master's heartbeat or SYNC running.
- Open question 3: the config adds no watch by itself; the configurator's "watch producer" checkbox is ticked when a consumer is added and the producer has a heartbeat (config or EDS 0x1017), and editing it edits `heartbeat_watch`.
- Open question 5: no new diagnostics fields. The Online view shows a "PDO links" table derived from the node states and the producer TPDO's `pdo_timeouts` of the existing status; the Links page shows the states of the Online view's last status next to each node.
- A consumer may give `"mapping": "config"` (refused on a fixed mapping, as for any PDO). A device-mapped consumer may leave out `entries`; when it gives them they must list its EDS default mapping in order.
- `transmission` and `event_timer_ms` of a consumer are written whenever they are given (not only when they differ from the EDS), like the explicit PDO parameters of `add_explicit_pdo_writes`.
- The heartbeat watch's 0x1016 entries are written after the link RPDOs, both after dcfgen's 0x1016 handling and before the TIME COB-ID, RPDO deadlines, 0x60C2 and startup SDOs. Only writable 0x1016 sub-indices count towards the capacity.
- The schema: `tx_entry` of version 1 no longer requires `iec_location` (version 2's `field_tx_entry` never did); the plugin and the deploy tool still refuse an entry without one unless its TPDO feeds a link or a gateway route uses it. A consumer entry with `iec_location` is refused by the schema (`not required`), the plugin and the deploy tool.
- The shared fixtures for links are a file of their own, `test/fixtures/config/cases-links.json`, with a base of two made-up link modules and a fixed-mapping module (`test/fixtures/eds/make_link_eds.py` writes `link-io.eds` and `link-io-small.eds`), instead of patches of the one-node base of `cases.json`; `cases-v2.json` keeps the version 2 message change. Both the plugin's unit tests and the deploy tool run it.
- The example (task 7.7) is `examples/pdo-link` rather than a folder under `config/`: the browser example sweep (`test_configurator_examples_page.py`) opens the folders under `examples/`.
- The deploy tool's shared link code is `tools/deploy/canworks/links.py`; the configurator's page is `static/links.js`.

Spike results (tasks 1.1-1.3): simulated devices receive each other's PDOs once the master configured the consumer RPDO (`sim_pdo_link`). dcfgen writes nothing to an RPDO that is neither listed nor switched off and makes no master TPDO on the link's COB-ID; it does make a master TPDO for every node RPDO its model keeps enabled with an EDS default mapping, on that RPDO's default COB-ID, which is unchanged behaviour (also for RPDOs the plugin switches off) and never the link's COB-ID. Lely's slave sends EMCY 0x8130 on a heartbeat watch timeout and applies 0x1029 sub 1; the consumer starts watching again at the producer's first heartbeat, so a power cycle of either end resumes the link without a boot loop (`sim_pdo_link_loss`).
