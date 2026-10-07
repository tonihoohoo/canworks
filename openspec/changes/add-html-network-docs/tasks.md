## 1. Shared resolution helpers

- [x] 1.1 Make the DBC node identifier function public and add a frame list helper to `dbcexport.py` that also returns the master heartbeat, TIME and each node's SDO channels; verify the DBC golden files are unchanged and unit-test the extra frames on the example configs.
- [x] 1.2 Tag each write in `dcfexport.Download.writes` with its source (PDO configuration, plugin, startup SDO, device parameters, identity/config check); verify the DCF golden files and the `test/dump/` parity are unchanged and unit-test the tags for the rtd-sensor and cia402-drive examples.

## 2. Document model

- [x] 2.1 Add `docexport.py` building the JSON-serialisable model (summary, networks, master settings, frames, nodes, PDOs with byte layout, boot writes, I/O rows, OD extract, warnings) with `doc_schema_version` 1, injectable `now`, file names relative to the config folder; verify with model unit tests on all `config/` examples.
- [x] 2.2 Implement the bus-load estimate (frame bits with worst-case stuffing, cyclic and worst-case totals, event PDOs by inhibit time or event timer, unbounded warning, PLC-cycle SYNC with and without a given cycle, 60 % warning); verify the scenario numbers of the spec in unit tests.
- [x] 2.3 Add the privacy rules (no token or its hash, no absolute paths, diagnostics reduced to enabled/port/changes allowed); verify with a test that greps every example's output for the token hash and the build directory.
- [x] 2.4 Check the model against the exports: COB-IDs and layouts equal the DBC model's, boot writes equal the DCF export's per node; verify in a parity test over the examples.

## 3. HTML writer

- [x] 3.1 Add `docwriter.py` rendering the model to one HTML file with inline CSS, script and SVG: contents sidebar, summary, topology diagram, network settings, COB-ID map, bus-load table, node sheets, PDO byte grid and table, boot list, SDO variables, I/O cross-reference, OD extract, config appendix, embedded JSON; light/dark with a switch; verify well-formedness with `html.parser`-based checks and golden files for the three examples.
- [x] 3.2 Add sorting, filtering, collapsing and theme switch as a small inline script, with every table rendered server-side; verify with a headless Chromium page test (sort, filter, deep link) and a no-script render.
- [x] 3.3 Add the print stylesheet; verify by printing the cia402-drive document to A4 PDF in headless Chromium in CI (no sidebar, node on a new page, no table wider than the page).
- [x] 3.4 Add `--doc-embed-eds` data links and the OD `all` mode; verify the embedded file round-trips byte for byte.
- [x] 3.5 Check stable output: two exports with different `now` differ only in the timestamp; verify in a test.

## 4. Deploy tool and configurator

- [x] 4.1 Add `--export-html`, `--doc-title`, `--doc-od`, `--doc-embed-eds`, `--doc-cycle-ms` to `cli.py` with `--network`, editor-project variable names and task interval, refusals without `--export-html`, temp-file write; verify with CLI tests for export, failure and option refusal.
- [x] 4.2 Add `POST /api/export_html` and the "Export documentation" header action (unsaved config, project mode names and cycle, Problems pane on errors and warnings, no file written in the project); verify with configurator API and page tests.
- [x] 4.3 Bump the deploy tool minor version.

## 5. Docs

- [x] 5.1 Write `docs/network-docs.md` (what the document contains, the bus-load method and its limits, options, printing to PDF) with a screenshot of a generated document from an example config.
- [x] 5.2 Update `docs/deploy.md`, `docs/configurator.md` and README (PC tools list, OpenSpec capability list).

## 6. Hardware check

- [ ] 6.1 Export the document of the hardware bench config and compare the boot list and COB-ID map with a bus trace of a boot; the identity and EDS hash must match the device.
