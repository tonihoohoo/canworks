# Design

## Words on the page, not in edslint

`edslint.Correction.text` is shared with the plugin's log line (`prepared_note`), which speaks to someone reading the PLC log. The banner speaks to someone who just picked a file. The page already gets each correction's `kind` and `items`, so `importReport()` maps the kind to its sentence and uses `count`. An unknown kind falls back to `c.text (count)`, so a new correction kind added later still shows.

## Who reads the copy

| Import | Target | Reader sentence | REAL line |
|---|---|---|---|
| node | OpenPLC | The OpenPLC plugin reads a corrected copy, because its CANopen stack cannot read these values: | shown |
| node | Modbus bridge | The Modbus bridge reads a corrected copy, because its CANopen stack cannot read these values: | shown |
| node | CODESYS | The DCFs exported to CODESYS are built from a corrected copy: | left out |
| slave EDS | OpenPLC / bridge | as above | shown |
| slave EDS | CODESYS | canworks reads a corrected copy, because its CANopen stack cannot read these values: | shown |

If REAL is the only correction under CODESYS, no correction block is shown, and the "readable" line is shown when there is nothing else to report.

The target is the draft's (`projectTarget()`), read when the banner is built. A later target switch does not rewrite an old banner; banners are short-lived.

## Layout

The report is a short block: the lead sentence with the file name in `code`, then a `ul` with one `li` per correction. The `data-report="corrections"` hook stays on the block for tests.
