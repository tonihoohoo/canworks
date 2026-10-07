## Why

The tools export the configured network for machines (DCF for devices and other tools, DBC for bus analysers, an editor project for the PLC), but nothing for people. Commissioning engineers, maintenance staff and reviewers need one readable record of a CANopen installation: which devices sit on which network, what every frame on the bus carries, which PLC address each value lands in, and exactly what the master writes into each device at boot. Today that record is assembled by hand from the config, the EDS files and screenshots, and it goes stale with the next change.

Existing CANopen documentation generators document one device's object dictionary for its manual (HTML, Word or Markdown from the device's EDS). None documents a whole network as it is configured: topology, COB-ID map, PDO bit layout down to PLC variables, the boot SDO sequence and a bus-load estimate. The deploy tool already resolves all of this, because it has to in order to deploy, check and export DCF and DBC files, so a document built from the same code always matches what the plugin puts on the bus.

## What Changes

- **New export**: one self-contained HTML document of the configured CANopen networks, built on the engineering PC from the config and the EDS files alone (no PLC, runtime or bus), from the same resolution code as the DCF and DBC exports.
- **Contents**:
  - Cover and summary: config file name and hash, tool version, date, optional title; per network the interface, bitrate, node and PDO count and estimated bus load; every check warning.
  - Per network: a topology diagram, the master's settings (SYNC, heartbeat, TIME, NMT start, error behaviour, timing), a COB-ID map of every frame on the bus (producer, consumers, length, period, load share) and a bus-load budget (cyclic load plus the worst case of event-driven PDOs).
  - Per node: identity from the EDS and the config's identity checks, EDS file and hash, supervision, boot and store settings, LSS, CiA 402 axis, program download, status and error PLC addresses; each PDO with its communication settings and a bit-level layout down to the object, type, PLC address and PLC variable name; the ordered list of every SDO write the master makes at boot with object name, value, access, EDS default and where the write comes from; startup SDOs and SDO variables.
  - A PLC I/O cross-reference of every `%I`/`%Q` address the config uses.
  - Appendices: the objects of each node's object dictionary the config touches (or all objects on request), and the config file itself; optionally the EDS files embedded.
- **Quality**: one `.html` file with inline CSS, script and SVG (no network access needed to view it), light and dark themes, a print stylesheet so the browser's "Print to PDF" gives a paginated document, sortable and filterable tables, stable deep links, and the same content as machine-readable JSON inside the file. Two exports of an unchanged config differ only in the generation date.
- **Never in the document**: the diagnostics token or its hash, absolute paths of the engineering PC.
- **Deploy tool**: `openplc-canopen-deploy --export-html FILE`, with `--network NAME`, `--doc-title TEXT`, `--doc-od used|all`, `--doc-embed-eds` and `--doc-cycle-ms MS` (the PLC task interval, for configs whose SYNC follows the PLC cycle).
- **Configurator**: an "Export documentation" action that downloads the document for the config as shown, saved or not, with PLC variable names in project mode.

## Capabilities

### New Capabilities
- `canopen-network-docs`: the HTML network document: its contents, how each value is resolved, the bus-load estimate, layout and offline, print and theme behaviour, embedded JSON, determinism and what it must never contain.

### Modified Capabilities
- `canopen-deploy`: the `--export-html` command-line export and its options.
- `canopen-configurator`: the "Export documentation" action.

## Impact

- `tools/deploy/openplc_canopen_deploy/`: new `docexport.py` (document model) and `docwriter.py` (HTML writer with inline assets); small public helpers in `dbcexport.py` (node identifiers, frame list including master heartbeat, TIME and SDO channels) and `dcfexport.py` (source of each boot write); `cli.py` options; configurator endpoint `POST /api/export_html` and header action.
- No plugin, runtime, schema or config-format change. No new runtime dependency.
- Tests: golden HTML/JSON for the example configs, an HTML well-formedness check, a check that the token and absolute paths never appear, configurator page test; deploy tool minor version bump.
- Docs: new `docs/network-docs.md`, `docs/deploy.md`, `docs/configurator.md`, README.
- Follow-ups, not in this change: a comparison with a previous export (change record), and an online variant with live node state and measured bus load from the diagnostics channel and trace.
