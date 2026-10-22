## 1. Defaults

- [x] 1.1 One per-protocol defaults table in app.js (bit rate per protocol, CANopen master without SYNC); used by the model fallback, Add network…, role switch to master and protocol switch
- [x] 1.2 `empty_config()` in server.py: 500000 and `{"node_id": 1}`
- [x] 1.3 `newJ1939Network` keeps 250000; Add network… uses the protocol's default rate instead of the first network's
- [x] 1.4 Protocol switch: a rate equal to the old protocol's default moves to the new protocol's default; other rates are kept

## 2. SYNC on the bus page

- [x] 2.1 SYNC source Off / Timer / PLC cycle, derived from the config; Timer fills 10 ms; emptying the period goes to Off; Off clears all SYNC keys
- [x] 2.2 Hints: drop "New configs start with 10 ms"; Off says PDOs need an event-driven type
- [x] 2.3 CODESYS and Modbus bridge targets: Off and Timer only

## 3. New nodes on a network without SYNC

- [x] 3.1 Add node with default PDOs: PDOs whose EDS type needs SYNC get transmission 255 (not when the EDS marks it read-only); add message lists them

## 4. Checks and docs

- [x] 4.1 Server test: new config has 500000 and no SYNC; page tests per scenario; update tests that expect 10 ms or 250 kbit/s on a new network
- [x] 4.2 docs/configurator.md (defaults, SYNC Off); README if it names the defaults; PC tools minor version bump and release notes line
