## Why

The datasheet notes skill (PR #110) was tried once on three real devices: a servo driver's EDS with a 37-page PDF manual and with the 45-page manual of its newer firmware, and an open-source demo device's EDS with its Markdown object dictionary. All three files checked clean and imported, but the runs showed where the skill's instructions fall short:

- **One question per difference is too many.** A real manual gave 13 and 15 questions even with "same for the rest of this kind". Toni (2026-10-15): "yes table would be good".
- **Built-in bit and value names get lost.** A note's `bits`, `values`, `text` or `details` replace the built-in field as a whole. The skill does not say so; one run dropped the built-in names of two statusword bits, another kept them by guessing.
- **"Follow EDS" is undefined.** Runs had to guess whether a note may still describe a byte layout or bit field that the EDS range contradicts, and how to map a shifted array.
- **The difference list is too narrow.** Names and PDO mapping are not in it, and an empty EDS default, sub 0 and access such as `RW/S` are unclear. EDS errors on objects that get no note (device type default, identity sub 0, PDO COB-ID access) were found but had no place in the report.
- **Page references are ambiguous.** In both manuals the printed page number is one less than the PDF page. A Markdown document has neither.
- **Contradictions inside the datasheet** (two tables disagreeing, a copied row) have no rule.
- **Comparing by hand is error-prone.** Two runs wrote their own EDS parser to compare; one still missed a sub-object. The skeleton lists only manufacturer objects, without defaults, limits or PDO mapping.
- **Inheritance surprises.** A unit on an object key is inherited by sub 0 (the count) and by sub-objects that pack two values.

A second trial (2026-10-15) ran the skill once each on 11 more devices from free vendor downloads, 11 vendors: a flow controller, a frequency inverter with an XLSX parameter list, a servo drive, digital and analog I/O modules, an electric valve actuator, an encoder, an inclinometer, a draw-wire sensor, a pressure transmitter, and a bus coupler with an HTML manual (19-225 pages; 0-34 pages read as images; 11-1014 notes; 1-9 difference questions). Every notes file checked clean, one only on a patched copy of its EDS. The fixes above were voted Yes by 11 runs for Follow EDS, other EDS problems and contradictions, 10 for `--all`, 7 for the table and for complete lists, and 2 for printed + PDF page (the other manuals had no offset or no pages). It also found:

- **EDS files that do not load.** 2 of 11 vendor EDS files stop `skeleton`, `builtin` and `check` (a missing `=`; an object count one higher than the list). The syntax error does not name the line, and the skill has no step for it.
- **No built-in notes for the device's profile.** 5 of 11 devices are CiA 404, 406 or 410, and an EDS without a 0x1000 default gets no profile at all. `builtin` then gives CiA 301 only without saying so, and "only where the built-in note does not cover it" has nothing to compare with.
- **`values` and `bits` on an ARRAY/RECORD key are silently unused** (sub-objects do not inherit them); `check` passes them.
- **The skeleton misses the object keys.** It has no entry for an ARRAY or RECORD itself, although notes are written on it; it drops the product code without a word when the EDS has none; it prints UNSIGNED24/40/48/56 as type codes; and on a 628-object EDS it is 2,500 lines with no way to pick a range.
- **Several documents.** One device's objects are split over a CANopen manual (the index rule) and a parameter manual (the meanings); `manual` cannot say which document. Index rules (base + parameter number, process/parameter), hex sub-indices and family manuals covering several variants have no rule.
- **Values the datasheet writes differently.** Bits numbered from 1, hex values of signed types, one row for two raw values, value ranges, multi-bit fields, write signatures and a scale that depends on another object or is derived from a full-scale value.
- **Spreadsheets.** An XLSX with 1,000 rows: "short summaries in your own words" does not fit, and row numbers change when the sheet is sorted.

## What Changes

- **Differences in one table.** The skill collects every EDS/datasheet difference, then shows them in one table before writing: one row per difference or group of the same kind (the objects it covers listed in the row), what the EDS says, what the datasheet says with its page, and the answer it will use, **Follow EDS** by default. The user answers only the rows to change (**Use datasheet** or **Skip**), or accepts the table as it is. This replaces one question per difference and "same for the rest of this kind".
- **`canworks-deploy notes skeleton --all`**: an entry for every object and sub-object of the EDS, standard ones included, each with `x-type`, `x-access`, `x-default`, `x-low`, `x-high` and `x-pdo` (when the EDS gives them), plus an entry for each ARRAY and RECORD object itself with its name, so the skill compares row against row. `--index LOW-HIGH` limits the entries to a range of indices. The skeleton names UNSIGNED24-56 and INTEGER24-56, and says on stderr which identity fields the EDS lacks. Without `--all` the output is as today.
- **`notes builtin`** says on stderr which built-in sets applied, and names the device profile when there are no built-in notes for it.
- **EDS read errors** of the `notes` commands name the line or section.
- **`notes check`** (and the configurator's Problems pane) warns about `values` or `bits` on an ARRAY or RECORD object key.
- **Skill rules** (SKILL.md):
  - A device note's `bits`, `values`, `text` and `details` replace the built-in field: on a standard object write the device's complete list, and keep built-in entries the datasheet does not contradict.
  - **Follow EDS** means: keep the EDS's layout, type, size and range; use the datasheet's wording where it fits; the note states nothing the EDS contradicts, and `details` names the difference.
  - Differences include names and PDO mapping; an EDS without a default against a datasheet default is a difference; access `RW/S` (or similar) equals `rw`.
  - Page references: the printed page number, with "PDF n" when it differs; for a document without pages or section numbers, the heading. With several documents, `manual` starts with the document's number or short title.
  - Contradictions inside the datasheet: prefer the detailed section over the summary table, say so in `details`, list it in the report.
  - Unit and scale go on sub-objects, not the object key, when sub 0 or a packed sub-object would inherit them.
  - A table row with only name, type and default is not a description.
  - The import may also change notes the user wrote; the hand-off says to check those rows in the preview.
  - An EDS that does not load: stop, report the error and its line, do not patch the EDS.
  - No built-in notes for the profile: standard objects get a note where the datasheet describes them beyond name, type and default.
  - Index rules: apply a rule the datasheet states (base + parameter number, process/parameter, hex sub-index) to find the EDS key, and write nothing from the rule alone. Family manuals: only what applies to the EDS's device; objects of other variants are not differences.
  - Values as the EDS reads them: bits numbered from 0, signed hex as negative decimal, every raw value of a row; value ranges, multi-bit fields, write signatures and scales that depend on another object go in `details`; a scale derived from a stated full-scale value is allowed and said in `details`; a unit only implied by a name is not stated.
  - Spreadsheets: `text` may be the parameter's name from the sheet, `manual` names the sheet and the parameter code, not the row.
- **Report** adds "Other EDS problems seen": differences on objects that got no note.
- Docs (`docs/configurator.md` Notes from a datasheet, `docs/deploy.md` Device notes) follow; PC tools version bump.

## Non-goals

- Built-in notes for CiA 404, 406, 410 or other profiles: a change of its own.
- Notes format fields for multi-bit fields or value ranges; `details` holds them for now.
- Reading a malformed EDS anyway: the configurator refuses it too, so the skill stops.

## Capabilities

### New Capabilities
None.

### Modified Capabilities
- `canopen-device-notes`: differences in one table; report lists other EDS problems; page and document references; profiles without built-in notes; values as the EDS reads them; check of `values`/`bits` on object keys.
- `canopen-deploy`: `notes skeleton --all` and `--index`; `notes builtin` names the sets used; EDS read errors name the line.

## Impact

- `.claude/skills/canworks-datasheet-notes/SKILL.md`.
- `tools/deploy/canworks/notes.py` (`skeleton` with all objects and the EDS fields, `builtin` sets, `check` finding), `eds.py` (line in read errors, type names), `cli.py` (`--all`, `--index`), `tools/deploy/tests/test_notes.py`.
- Docs, PC tools version.
- No notes format, plugin or config change. The configurator shows one more notes finding. No hardware tasks. Trial files stay in the project's private folder, not in the repo or CI.
