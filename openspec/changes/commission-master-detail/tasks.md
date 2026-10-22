## 1. Plugin

- [ ] 1.1 Track the time of the last frame received per configured node (heartbeat, boot-up, EMCY, TPDO, SDO answer); report `last_heard_ms` in the status answer
- [ ] 1.2 `diag.py status` and `commissioning.py` read `last_heard_ms`; host/unit test

## 2. Commission layout

- [ ] 2.1 Network entry: network page (bus, SYNC, Nodes table, Unconfigured devices); node entry: node header + live tabs only, in both Commission with a config and Commission a device
- [ ] 2.2 Node header (ID, name, state, last heard, boot, simulated, back to Nodes); table row click opens the node page
- [ ] 2.3 Scroll to the top of the work area on page and tab changes

## 3. Object dictionary and flags

- [ ] 3.1 Read all unfolds groups with values and objects with differing entries
- [ ] 3.2 Watch list card only while something is watched; hint line otherwise
- [ ] 3.3 EMCY 0x0000 clears the diagnosis flag; "cleared (0x0000)" in Last EMCY

## 4. Checks and docs

- [ ] 4.1 Page tests: master/detail in both modes (tree pick, row click, back link, tab kept), Read all unfolding, watch card, EMCY 0x0000 flag, last heard shown against the plugin host
- [ ] 4.2 docs/configurator.md (Commission); PC tools minor and plugin patch version bump

## 5. Hardware test (Pi)

- [ ] 5.1 Node 23 with heartbeat: Last heard under 0.2 s in the Nodes table and node header; switch it off and Last heard grows
