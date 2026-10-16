## 1. Plugin and Check

- [x] 1.1 `eds_check.cpp`: reject `emcy_cob_id` (any value) on a node whose EDS has no 0x1014; keep the `emcy_code_location` / `error_register_location` refusal and give all three one message naming the node, the field and 0x1014
- [x] 1.2 `eds_check.cpp`: reject `heartbeat_consumer` (true or false) when the node's EDS has no 0x1016 with a writable sub-index, naming the node and 0x1016
- [x] 1.3 `contract.py`: the same refusals in the Check with the plugin's text, pointed at the field paths
- [x] 1.4 Unit tests for both refusals (plugin and contract); fix fixtures that set these fields on nodes without the objects (new `test/fixtures/eds/emcy-slave.eds`: the ping-pong EDS with 0x1014)

## 2. Configurator

- [x] 2.1 EMCY section: disable EMCY code, Error register, their Suggest buttons and the EMCY COB-ID choice when the EDS has no 0x1014; one grey hint line in the section
- [x] 2.2 Watches the master heartbeat: disabled on "EDS default" with the grey reason when the EDS has no writable 0x1016
- [x] 2.3 Leftover settings: when the loaded node still has an EMCY field or `heartbeat_consumer` the EDS cannot back, amber text with a "Remove ..." link; Save refused until removed
- [x] 2.4 LSS: the "EDS has no LSS" reason becomes grey hint text; amber only while the node still has an `lss` object (with the existing Remove link)
- [x] 2.5 Check that the Configuration check and store reasons use the same grey hint and the leftover rule
- [x] 2.6 Browser tests: node without 0x1014 (fields disabled, grey reason, no EMCY saved), node without 0x1016 (choice disabled), leftover settings (amber + Remove), LSS reason colour matches the Configuration check hint in light and dark

## 3. Docs and release

- [x] 3.1 README node settings section
- [x] 3.2 PC tools minor version bump (0.77.0), doc golden files (the plugin's version comes from git)
- [ ] 3.3 Archive the change on the branch once CI is green

## 4. Hardware

- [ ] 4.1 On the bench: the real node's page shows EMCY and heartbeat consumer as its EDS allows; deploy and clean PLC start, node reaches OPERATIONAL
