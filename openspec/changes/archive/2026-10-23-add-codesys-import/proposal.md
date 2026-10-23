## Why

canworks can build a CANopen network into a CODESYS project, but not the other way. Someone with an existing CODESYS project has to re-enter every node, PDO and startup SDO by hand to use canworks, and after an edit in canworks, **Build into CODESYS project** deletes and re-adds every node it manages, so settings made in CODESYS on those nodes are lost. Toni wants to move a configuration back and forth between the two without losing data.

Four checks on a real CODESYS V3.5 SP22 (2026-10-23, report `research/codesys-import-2026-10-23.md` in the project files) settled the route:
- CODESYS's PLCopenXML export of a CANbus holds the whole network: every CANbus, manager and node parameter by fixed id, the SDO list with generated rows marked, and the I/O variable names. A full export imported into a new project gave zero differences.
- An existing node can be updated in place by script: PDO settings, mapping values, SDO values and flags, node ID, heartbeat, guarding, flags, variable names and fixed I/O addresses through the public API; adding or removing mapping entries, channels and SDO rows, and the identity-check ticks, only through an internal API.
- A canworks-written PLCopenXML would have to reproduce CODESYS's whole parameter catalogue per device; the script route stays for writing.

## What Changes

- **Import from CODESYS (new).** canworks reads a CODESYS PLCopenXML export of a device or CANbus and makes a canworks config from its CANopen manager networks: bus (network number, bit rate), manager settings, nodes (node ID, name, flags, heartbeat, guarding, identity checks), PDOs (COB-ID, transmission, inhibit, event timer, enabled, mapping), user startup SDOs (generated ones skipped) and channel variable names as entry names.
  - The configurator's **Import from CODESYS…** takes a `.project` (canworks runs CODESYS headless to export it, when CODESYS is on this PC) or an `.xml` exported by hand (any PC, Mac too). With several devices that have a manager, the user picks one. A preview lists networks, nodes, each node's EDS (found in the library by identity / taken from CODESYS's device repository / missing with **Add EDS…**) and what does not carry over. **Create config** makes a new CODESYS config; **Add to this config** adds the networks.
  - `canworks-deploy --from-codesys FILE` does the same from the command line.
- **CODESYS-only settings carried in the config (new fields).** Values canworks has no field for travel in `codesys` objects on the node, PDO, entry and startup SDO (device name, PDO processed by the manager, fixed I/O address, SDO abort-on-error / jump-to-line), so an import followed by a build gives the same project.
- **Build updates in place (changed).** Build into CODESYS project compares each planned node with the project's node of the same node ID and changes only what differs, through the public API. Untouched nodes and every setting canworks does not manage stay as they are. A node whose PDO mapping layout or startup SDO list changed in structure (entry or row added, removed, reordered or resized) is replaced from its DCF as today, then gets its carried CODESYS settings back; the report names it and why. Identity checks (vendor, product, revision ticks) are set through CODESYS's internal parameter API; where that is not available the report says which ticks to set by hand. New nodes are added; a node removed in canworks is removed from the project only after the build dialog asks.
- **Reliable COB-IDs.** PDO COB-IDs are written through CODESYS's generic COB-ID setting, `$NODEID`-based when the EDS default is node based, so a node ID change moves them.
- `docs/codesys.md`, README.md, PC tools version.

## Capabilities

### New Capabilities
- `codesys-import`: reading a CODESYS PLCopenXML export into a canworks config, what maps and what is reported as not carried.

### Modified Capabilities
- `codesys-export`: "Re-runnable" becomes update in place; "Nodes from their DCF" applies to new and replaced nodes; carried CODESYS settings are written back.
- `canopen-config-contract`: `codesys` objects on node, PDO, PDO entry and startup SDO.
- `canopen-configurator`: Import from CODESYS…; build dialog asks before removing nodes.
- `canopen-deploy`: `--from-codesys`.

## Impact

- New `tools/deploy/canworks/codesys/xmlimport.py` (reader + converter), a headless export step in `codesys/script/` (same IronPython/CPython rules), configurator dialog and API, CLI option.
- `import_canworks.py`: in-place update path, write-back of carried settings, COB-ID via generic setting; `tests/fake_codesys.py` grows parameters with elements and a node update log.
- Schema v2: new optional `codesys` objects. No change for existing configs.
- CI fixture: a PLCopenXML export of the virtual-plant example made with CODESYS SP22 (no vendor content).
- Depends on fix-codesys-export-names (multi-network builds).
