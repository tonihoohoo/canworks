## 1. Plugin

- [x] 1.1 Track the time of the last frame received per configured node (heartbeat, boot-up, EMCY, TPDO, SDO answer); report `last_heard_ms` in the status answer
- [x] 1.2 `diag.py status` and `commissioning.py` read `last_heard_ms`; host/unit test

## 2. Commission layout

- [x] 2.1 Network entry: network page (bus, SYNC, Nodes table, Unconfigured devices); node entry: node header + live tabs only, in both Commission with a config and Commission a device
- [x] 2.2 Node header (ID, name, state, last heard, boot, simulated, back to Nodes); table row click opens the node page
- [x] 2.3 Scroll to the top of the work area on page and tab changes

## 3. Object dictionary and flags

- [x] 3.1 Read all unfolds groups with values and objects with differing entries
- [x] 3.2 Watch list card only while something is watched; hint line otherwise
- [x] 3.3 EMCY 0x0000 clears the diagnosis flag; "cleared (0x0000)" in Last EMCY

## 4. Checks and docs

- [x] 4.1 Page tests: master/detail in both modes (tree pick, row click, back link, tab kept), Read all unfolding, watch card, EMCY 0x0000 flag, last heard shown against the plugin host
- [x] 4.2 docs/configurator.md (Commission); PC tools minor version bump (the plugin version comes from git describe)

## 5. Hardware test (Pi)

- [x] 5.1 Node 23 with heartbeat: Last heard stays under the heartbeat period in the Nodes table and node header; switch it off and Last heard grows (criterion corrected: "under 0.2 s" only fits a ~100 ms heartbeat)
  - PASSED 2026-10-22 on the bench Pi from the Mac: node 23 heartbeat 1000 ms; Last heard sampled every 250 ms ran a 0 to ~0.8-1 s sawtooth (438, 708, 126, 267, 537, 807, 78 ms). After SDO write 0x1017:00 = 0 it grew without reset (18, 548, 807 ms ... ) until the master's own 3000 ms heartbeat timeout rebooted node 23, which restored 0x1017 = 1000. Wrote 1000 back by hand; no store, 0x1010 untouched.
