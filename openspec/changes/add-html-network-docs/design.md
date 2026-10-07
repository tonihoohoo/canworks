# Design

## Context

The deploy package already resolves everything a network document needs, on the PC, without a runtime:

- `contract.check_config`, `networks`, `network_config`, `location_uses`: validation, the networks, every IEC location with who uses it.
- `dbcexport.build`: the frames on the bus with the plugin's COB-IDs (auto and default), PDO bit layouts from the config or the EDS default mapping, transmission types (marked when taken from the EDS), SYNC-derived cycle times, and PLC variable names in editor-project mode.
- `dcfexport.plugin_downloads`: the ordered SDO writes the plugin makes at boot (dcfgen output plus the plugin's own post-processing), and the non-setting boot steps (restore, program download, store).
- `eds.Eds`, `eds.device_info`, `edslint`: object names, access, types, limits and defaults, identity.

A throwaway prototype (about 190 lines, outside the repo) built a usable document for the three example configs from these functions alone. It showed three gaps: the DBC model has no master heartbeat, TIME or SDO channel frames; boot writes do not say where they come from; and event-driven PDOs are invisible to a load estimate based only on SYNC cycles.

## Goals / Non-Goals

**Goals:**
- One file that a person can read offline, print to PDF, mail, and archive with a machine.
- Every value in the document comes from the same code paths the deploy, DCF and DBC exports use, never a re-implementation.
- Output that can be compared between two exports (stable order, stable ids, date only in one place).

**Non-Goals:**
- Live state (node states, EMCY history, measured load). The online variant is a follow-up.
- A comparison with an earlier export. A follow-up, made easy by the embedded JSON.
- User-supplied templates or other output formats (Word, PDF, Markdown).
- Documenting the PLC program beyond the variables that the config maps.

## Decisions

### D1. Two layers: document model, then writer
`docexport.build(cfg, config_path, ...) -> dict` builds a plain, JSON-serialisable model (networks, nodes, frames, PDOs, boot writes, I/O rows, warnings). `docwriter.write(model) -> str` renders HTML. The model is also embedded in the page as `<script type="application/json" id="canopen-doc">`, so other tools (and the later diff) read the same data the page shows. Alternative: render straight from the config objects; rejected because it couples the HTML to internals and leaves nothing machine-readable.

### D2. Reuse the export code, extend it in place
- `dbcexport`: make the node identifier function public and add a `frames(cfg, ...)` helper returning every frame including master heartbeat (0x700 + master node ID, when `master.heartbeat_ms` is set), TIME (when produced) and each node's SDO server channel (0x600/0x580 + ID). The DBC output itself does not change.
- `dcfexport.Download.writes` gains a source tag per write: `dcfgen` (communication and mapping from the config), `plugin` (the plugin's own additions such as 0x1012 or RPDO sub 5), `startup_sdo`, `device_parameters`, `identity` / `config_check`. The DCF output does not change.
Alternative: a separate resolver for the document; rejected, it would drift from the bus.

### D3. Bus-load estimate
Per frame: bits = 47 + 8·DLC + worst-case stuff bits ⌊(34 + 8·DLC − 1) / 4⌋ (11-bit identifiers, interframe space included). Rates:
- SYNC: 1 / sync period; SYNC-driven PDOs: 1 / (sync period × transmission type); acyclic SYNC PDOs (type 0) counted at the SYNC rate as the upper bound.
- Heartbeats (nodes and master): 1 / heartbeat period; node guarding: two frames per guard time.
- Event-driven PDOs (254/255): typical = event timer rate if set; worst case = 1 / inhibit time if set, else 1 / event timer, else marked "unbounded" and listed as a warning.
- PLC-cycle SYNC: the period is the PLC task's, which the config does not hold; the document asks for it with `--doc-cycle-ms` (configurator: the project's task interval in project mode) and otherwise shows the cyclic part as "per PLC cycle".
- NMT, EMCY, SDO and LSS are not counted (event, start-up or on demand) and are labelled so.
Two figures are shown: cyclic load and worst case, with a warning above 60 % worst case. This is an estimate, labelled as one.

### D4. One self-contained file
Inline CSS, a small inline script (sorting, filtering, theme toggle, collapsing), inline SVG diagrams, no web fonts, no CDN, no external images. The page must also read fully with script disabled (every table rendered, nothing built client-side), so it prints and archives well. Alternative: a static site folder; rejected, a single file is what people mail and attach to a commissioning record.

### D5. Layout
Sticky contents sidebar (collapses on narrow screens), sections in a fixed order: Summary → per network (topology, settings, COB-ID map, bus load, nodes) → PLC I/O → Appendices. Per node: identity, settings, PDOs, boot configuration, SDO variables, object dictionary extract. Each PDO shows a byte grid (8 columns × DLC rows, each mapped object a coloured span labelled with its name) above the table. Ids are `net-<name>`, `node-<net>-<id>`, `pdo-<net>-<id>-tpdo<n>`, so links into the document stay stable between exports.

### D6. Print
`@media print`: no sidebar and controls, collapsed sections expanded, one page break before each network and node, table headers repeated on each page, links followed by their target text where helpful, a running footer with config name and hash via `@page` where browsers support it. Tested by printing to PDF in headless Chromium in CI (page count > 0, no clipped tables at A4 width).

### D7. Determinism and privacy
Order is by network order, node ID, PDO number and COB-ID; no dictionaries in iteration order. The generation date appears only in the header and in the JSON `generated` field, and `now` is injectable for tests. File references show file names relative to the config folder, never absolute paths. The `diagnostics` object is reduced to "enabled, port, changes allowed"; `token_sha256` never appears. A test greps the output of every example config for the token hash and the build directory.

### D8. Embedding EDS files
`--doc-embed-eds` adds each EDS as a download link (`data:` URI, `download="<name>"`). Off by default: EDS files can be large and vendor files may carry licence terms; the document always carries each file's name and SHA-256 so the right file can be matched.

### D9. Object dictionary appendix
`used` (default): every object the config, dcfgen or the plugin writes or maps, with ParameterName, type, access, limits, EDS default and configured value. `all`: every object of the EDS, with the configured value where there is one. Large EDS files make `all` long; it renders collapsed.

### D10. Slave role
If `add-canopen-slave` is merged first, networks whose PLC is a slave get the same sections with the PLC's own object dictionary and PDOs; the model has a `role` field from the start so this does not change its shape.

## Risks / Trade-offs

- [The estimate is mistaken for a measurement] → labelled "estimate" with the method spelled out in a footnote; the online variant later shows measured load next to it.
- [Very large networks make one page heavy] → tables are plain HTML (no client rendering); 127 nodes × 8 PDOs stays well under a few MB; OD `all` and EDS embedding are opt-in.
- [Browser print differences] → print CSS uses only widely supported features; `@page` margins are best-effort.
- [Model changes break the embedded JSON for consumers] → the JSON carries `doc_schema_version: 1`.

## Migration Plan

Additive: new module, new options and a new configurator action; no config or runtime change. Deploy tool minor version bump.
