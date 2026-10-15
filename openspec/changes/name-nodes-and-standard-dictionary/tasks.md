## 1. Identity of heard nodes

- [x] 1.1 `identity.py` + `server.py`: `/api/online/identify {node, port}` reads 0x1018:1 (probe), 0x1018:2-4, 0x1000, 0x1008, 0x1009, 0x100A through the connection's manual SDO read; decode strings as the scan does; add `eds_matches`. The page keeps the answers per connection (design decision 1)
- [x] 1.2 `identity.js`, called from the connection poll: queue identity reads one node at a time for heard rows without identity; wait while STOPPED; re-read after boot-up; a scan result fills the record
- [x] 1.3 Device cell text with the fallback order of design decision 2, muted details, "Reading…", "No SDO answer" with Read again; with a config, device name under the configured name
- [x] 1.4 Node heading and Add to a config… name suggestion use the device name
- [x] 1.5 Status tab: Device line with Read again
- [x] 1.6 Unit tests: identify over the local bus with a simulated device; page tests: heard nodes get names without a scan, stopped node waits, no answer and Read again

## 2. Standard object dictionary

- [x] 2.1 `standardod.py`: CiA 301, 401 and 402 standard objects with names, data types, access and PDO mappable flags, no defaults
- [x] 2.2 Join 301 with the profile from 0x1000 into one EDS text, parse with the existing reader, cache per profile and PDO count; `od_entries` / `od_read` accept `{standard: true, device_type}`; entries carry `standard: true`
- [x] 2.3 `app.js`: `odSource` falls back to the standard source; OD tab top line (standard objects, profile, EDS matches, Pick EDS file…); `sdoPanel` picker from the same entries
- [x] 2.4 "Not on this device" for aborts 0x06020000 / 0x06090011; **Hide objects the device lacks** filter, on by default for the standard dictionary
- [x] 2.5 Array sub-entries follow the read sub-index 0; Read all reads sub 0 first, skips missing objects, probes RPDO/TPDO 5+ until the first missing one
- [x] 2.6 Picking an EDS replaces the standard dictionary and drops cached entries; Parameters tab without an EDS says what it needs and offers the EDS choices
- [x] 2.7 EDS cell: file name with a **Change EDS…** dialog (matches, Pick EDS file…, Clear EDS or Remove node); drop the node's cached entries and values of the old EDS; Commissioning log line; a config's EDS says where to change it
- [x] 2.8 Tests: standard dictionary for 301, 401 and 402 profiles and Read all on a simulated device; page tests for the OD tab and picker without an EDS, Read all hiding missing objects, picking an EDS afterwards, changing to another EDS and clearing back, removing a node only added from an EDS

## 3. Docs and release

- [x] 3.1 `docs/configurator.md` and README: Nodes table device names, standard object dictionary, Change EDS…
- [x] 3.2 Tools version 0.62.x -> 0.63.0
- [x] 3.3 Light and dark, 1100 px and phone width: long device names wrap in the Device column and heading
- [x] 3.4 CI time: new page tests join the existing configurator page shards; no new job

## 4. Hardware

- [ ] 4.1 On the bench: connect the adapter without scanning; a real node shows its name in the Nodes table; its Object dictionary tab without an EDS shows the standard objects and Read all hides what it lacks
