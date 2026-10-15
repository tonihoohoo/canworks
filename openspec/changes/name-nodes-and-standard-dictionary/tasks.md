## 1. Identity of heard nodes

- [ ] 1.1 `server.py`: `/api/online/identify {node, port}` reads 0x1018:1 (probe), 0x1018:2-4, 0x1000, 0x1008, 0x1009, 0x100A through the connection's manual SDO read; decode strings as the scan does; add `eds_matches`; keep the answer per connection and node and include it in the status answer; drop it when the node boots up
- [ ] 1.2 `commission.js` (and the with-config table in `app.js`): queue identity reads one node at a time for heard rows without identity; wait while STOPPED; re-read after boot-up; a scan result fills the record
- [ ] 1.3 Device cell text with the fallback order of design decision 2, muted details, "Reading…", "No SDO answer" with Read again; with a config, device name under the configured name
- [ ] 1.4 Node heading, Commission-a-device tree label and Add to a config… name suggestion use the device name
- [ ] 1.5 Status tab: Device line with Read again
- [ ] 1.6 Unit tests: identify on the PC-direct client with the device simulator (named device, device without 0x1008, no answer); page tests: heard nodes get names without a scan, stopped node waits, boot-up re-reads, scan result avoids a second read

## 2. Standard object dictionary

- [ ] 2.1 `builtin_od/cia301.eds`, `cia401.eds`, `cia402.eds`: CiA standard objects with names, data types, access and PDO mappable flags, no defaults; package data in `pyproject.toml`; the banned-word guard passes
- [ ] 2.2 Join 301 with the profile from 0x1000 into one EDS text, parse with the existing reader, cache per profile; `od_entries` / `od_read` accept `{standard: true, device_type}`; entries carry `standard: true`
- [ ] 2.3 `app.js`: `nodeSource` falls back to the standard source; `odPanel` top line (standard objects, profile, EDS matches, Pick EDS file…); `sdoPanel` picker from the same entries
- [ ] 2.4 "not on this device" for aborts 0x06020000 / 0x06090011; **Hide objects the device lacks** filter, on by default for the standard dictionary
- [ ] 2.5 Array sub-entries follow the read sub-index 0; Read all reads sub 0 first, skips missing objects, probes RPDO/TPDO 5+ until the first missing one
- [ ] 2.6 Picking an EDS replaces the standard dictionary and drops cached entries; Parameters tab without an EDS says what it needs and offers the EDS choices
- [ ] 2.7 Tests: standard EDS files parse and lint clean; od_entries for 301, 401 and 402 profiles; page tests for the OD tab and picker without an EDS, Read all hiding missing objects on a simulated device, picking an EDS afterwards

## 3. Docs and release

- [ ] 3.1 `docs/configurator.md` and README: Nodes table device names, standard object dictionary
- [ ] 3.2 Tools version 0.61.x -> 0.62.0
- [ ] 3.3 Light and dark, 1100 px and phone width: long device names wrap in the Device column and heading

## 4. Hardware

- [ ] 4.1 On the bench: connect the adapter without scanning; node 23 shows its name in the Nodes table; its Object dictionary tab without an EDS shows the standard objects and Read all hides what it lacks
