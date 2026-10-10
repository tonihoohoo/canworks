# canopen-pdo-links Specification

## Purpose
PDO links: one node's TPDO received directly by other nodes' RPDOs (CiA 301 producer/consumer), configured by the master at boot; the config, the consumer download, the layout and COB-ID checks, and the behaviour on loss, reboot, PLC stop and with SYNC.

## Requirements

### Requirement: Links in the network config
A CANopen master network MAY have a `links` list (at the top level of a version 1 file, in the network object of a version 2 file). Each link SHALL give `from`, a producer `node` and the `tpdo` number of one of that node's `tx_pdos`, and `to`, one or more consumers, each with a `node` and an `rpdo` number. A link MAY give a `name` (default `link <n>`, its 1-based place in the list) and `on_plc_stop` (`"follow"`, the default, or `"keep"`). A consumer MAY give `transmission`, `event_timer_ms`, and either `entries` (index, subindex and type of the consumer's own objects, in frame order, without `iec_location`) or `"mapping": "device"`. Without `links` the plugin SHALL generate the same master DCF and node downloads as before.

#### Scenario: One producer, two consumers
- **WHEN** a link has `from` node 10 TPDO 1 and `to` node 20 RPDO 2 and node 21 RPDO 1
- **THEN** the config loads and the plugin logs the link with its COB-ID, producer and consumers

#### Scenario: Unchanged config
- **WHEN** a config has no `links`
- **THEN** the generated master DCF and every node's download are byte-identical to those of the previous release

#### Scenario: Producer TPDO not configured
- **WHEN** a link's `from` names node 10 TPDO 3 and node 10 has no `tx_pdos` entry with number 3
- **THEN** the configuration is rejected naming the link, node 10 and TPDO 3

#### Scenario: Links on a slave network
- **WHEN** a version 2 network with `"role": "slave"` or `"protocol": "j1939"` has `links`
- **THEN** the configuration is rejected naming the network and saying links need a CANopen master network

### Requirement: Consumer RPDO is configured by the master at boot
For each consumer the plugin SHALL write, in that node's normal configuration download and before its startup SDOs, the RPDO's COB-ID with the invalid bit set, then the configured `transmission` and `event_timer_ms` (sub-indices 2 and 5) when given, then the mapping (sub-index 0 to 0, each entry, sub-index 0 to the count) unless the consumer uses the device mapping, then the COB-ID equal to the producer TPDO's resolved COB-ID. Read-only sub-indices SHALL be left out as for every PDO. The master SHALL NOT get a TPDO on the link's COB-ID, and the consumer RPDO SHALL NOT be switched off as an unused PDO. A consumer RPDO number SHALL NOT also appear in that node's `rx_pdos`.

#### Scenario: Consumer download
- **WHEN** node 10 TPDO 1 uses 0x18A and links to node 20 RPDO 2 with two 16-bit entries and `"transmission": 255`
- **THEN** `canopen_check --dump-writes` lists for node 20: 0x1401 sub 1 = 0x8000018A, 0x1401 sub 2 = 255, 0x1601 sub 0 = 0, sub 1 and sub 2 with the two objects, sub 0 = 2, 0x1401 sub 1 = 0x18A, and the master DCF has no TPDO on 0x18A

#### Scenario: RPDO also in rx_pdos
- **WHEN** node 20 has an `rx_pdos` entry number 2 and is a link consumer on RPDO 2
- **THEN** the configuration is rejected naming node 20, RPDO 2 and the link

#### Scenario: Configuration check sees a link change
- **WHEN** node 20 has `config_check` and a link's consumer entries for node 20 change
- **THEN** node 20's expected configuration stamp changes and the next boot downloads its configuration again

### Requirement: Producer entries visible to the PLC on request
The master SHALL keep receiving a linked producer TPDO as for any `tx_pdos` entry. An entry of a TPDO that feeds a link MAY leave out `iec_location`; such an entry SHALL be received but not written to the PLC image. Entries with a location SHALL be exchanged with the PLC as today, and the TPDO's `timeout_ms`, `timeout_location` and late PDO check SHALL work as for any TPDO.

#### Scenario: PLC also reads the value
- **WHEN** the producer TPDO's first entry has `"iec_location": "%IW100"` and the second has none
- **THEN** `%IW100` follows the first value and the second value reaches only the consumers

#### Scenario: Unlocated entry without a link
- **WHEN** a `tx_pdos` entry has no `iec_location`, its TPDO feeds no link and no gateway route uses it
- **THEN** the configuration is rejected naming the node, the PDO and the entry

### Requirement: Link layout checked against both EDS files
The plugin SHALL compare the producer layout (the TPDO's config `entries` in order, or the EDS default mapping of a device-mapped TPDO, including objects the PLC does not use and dummy entries) with each consumer layout (its `entries`, or the EDS default mapping for `"mapping": "device"` or a read-only consumer mapping). Both SHALL have the same number of positions with the same bit length at each position. A consumer entry MAY be a dummy entry (index 0x0001-0x0007) where the consumer EDS allows that dummy, to skip a position. A position whose data types differ at the same size SHALL give a warning naming both objects. Each consumer object SHALL exist, be PDO-mappable, have AccessType wo, rw or rww, and have the configured DataType in the consumer EDS. Every mismatch SHALL reject the configuration naming the link, the consumer, the position and both objects.

#### Scenario: Matching layout
- **WHEN** the producer maps two INTEGER16 objects and the consumer maps 0x6411:1 INTEGER16 and dummy 0x0003
- **THEN** the configuration loads

#### Scenario: Length mismatch
- **WHEN** the producer maps 32 bits and the consumer maps one 16-bit object
- **THEN** the configuration is rejected naming the link, the consumer, 32 and 16 bits

#### Scenario: Different type, same size
- **WHEN** the producer's first object is INTEGER16 and the consumer's is UNSIGNED16
- **THEN** the configuration loads with a warning naming both objects

#### Scenario: Fixed mapping on the consumer
- **WHEN** the consumer's EDS fixes RPDO 1's mapping to one UNSIGNED8 and the producer TPDO carries 16 bits
- **THEN** the configuration is rejected naming the consumer's default mapping from its EDS and the producer layout

#### Scenario: Read-only consumer object
- **WHEN** a consumer entry names an object whose AccessType is ro
- **THEN** the configuration is rejected naming the consumer, the object and its AccessType

### Requirement: Link COB-ID rules
A link's COB-ID SHALL be the producer TPDO's resolved COB-ID (explicit, `"auto"` or the CiA 301 default). The COB-ID clash check SHALL allow that COB-ID only for the producer TPDO, the master's RPDO for it and the link's consumer RPDOs; any other PDO, raw message or reserved frame on it SHALL be rejected naming both uses and the link. When the consumer EDS makes the RPDO's COB-ID read-only, the configuration SHALL be rejected unless that COB-ID equals the link's, and the message SHALL name the producer `cob_id` that would match. A TPDO SHALL feed at most one link, and a consumer RPDO SHALL belong to at most one link; producer and consumer SHALL be different nodes of the same network.

#### Scenario: Clash with another PDO
- **WHEN** a link uses 0x18A and node 30's TPDO 5 has `"cob_id": "0x18A"`
- **THEN** the configuration is rejected naming node 30 TPDO 5, the link and 0x18A

#### Scenario: Auto COB-ID producer
- **WHEN** the producer TPDO 5 has `"cob_id": "auto"` and resolves to 0x57F
- **THEN** each consumer RPDO is written with 0x57F

#### Scenario: Consumer with a fixed COB-ID
- **WHEN** node 21's EDS fixes RPDO 1's COB-ID at 0x215 and the link's COB-ID is 0x18A
- **THEN** the configuration is rejected saying node 21 RPDO 1 can only receive 0x215 and that the producer TPDO needs `"cob_id": "0x215"`

#### Scenario: Two links from one TPDO
- **WHEN** two links name node 10 TPDO 1 in `from`
- **THEN** the configuration is rejected naming both links and saying to list all consumers in one link

### Requirement: Synchronous links need SYNC
An effective synchronous transmission type (0-240, from the consumer's `transmission` or its EDS) on a consumer RPDO SHALL need a master that produces SYNC, as for any PDO, and the configuration SHALL be rejected without one. A synchronous consumer SHALL apply received data at the next SYNC; an event-driven consumer (254 or 255) SHALL apply it on reception. The plugin SHALL log at load each link with synchronous ends and its expected latency in SYNC periods.

#### Scenario: Synchronous consumer without SYNC
- **WHEN** the master produces no SYNC and a consumer has `"transmission": 1`
- **THEN** the configuration is rejected naming the consumer RPDO and saying it needs SYNC

#### Scenario: Synchronous link timing
- **WHEN** SYNC runs every 10 ms, the producer TPDO has type 1 and the consumer RPDO type 1
- **THEN** data sampled at SYNC k is applied by the consumer at SYNC k+1

### Requirement: Link nodes lost or rebooted
A lost producer or consumer SHALL be handled by the existing node supervision and recovery, with no other action by the master. When a link's producer is lost the plugin SHALL log once which consumer RPDOs no longer get data; consumers keep their last values unless their own deadline (`event_timer_ms`) or heartbeat watch makes them react. A producer or consumer that boots again SHALL get its whole configuration, including its link writes, and the link SHALL carry data again once both are OPERATIONAL.

#### Scenario: Producer lost
- **WHEN** node 10 feeds a link to node 20 and loses its heartbeat
- **THEN** the log names node 10 lost and the link to node 20 RPDO 2, and node 20 stays OPERATIONAL

#### Scenario: Consumer power cycled
- **WHEN** node 20 is power cycled while node 10 keeps sending
- **THEN** the master boots node 20 with its link RPDO and node 20 receives node 10's TPDO again once OPERATIONAL

### Requirement: Links on PLC stop
With a link's `on_plc_stop` `"follow"` its nodes SHALL get the master's `on_plc_stop` command like every node. With `"keep"` the master SHALL send no NMT command on PLC stop to that link's producer and consumers, and SHALL send the master's command to every other node. The plugin SHALL warn at load when a `"keep"` link has an effective synchronous type on its producer or a consumer (it stops with SYNC) or a node with `heartbeat_consumer` (it sees the master's heartbeat stop).

#### Scenario: Link keeps running
- **WHEN** a link has `"on_plc_stop": "keep"`, event-driven types on both ends, the master's `on_plc_stop` is `"preop"`, and the PLC is stopped
- **THEN** the producer and its consumers stay OPERATIONAL and the consumer keeps receiving the producer's TPDO, and every other node gets ENTER PRE-OPERATIONAL

#### Scenario: Synchronous kept link
- **WHEN** a `"keep"` link's producer TPDO has transmission type 1
- **THEN** the config loads with a warning that the link stops when the PLC stops because SYNC stops
