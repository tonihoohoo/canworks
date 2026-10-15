## Why

Device notes (`<eds file name>.notes.json`, format `canworks-notes.v1`) explain the objects an EDS only names: a one-line text, details, unit, scale, value meanings, bit names and a manual reference. The configurator shows them over the EDS and **Import notes…** brings a notes file in. Writing them is the slow part: the facts are in the device's datasheet or manual, tens of pages of object tables, and today every note is typed by hand on the Notes tab.

Claude can read a datasheet and write that file, but nothing in canworks helps it do so correctly:

- **No way to see the objects outside the configurator.** The skeleton of manufacturer objects, the built-in CiA 301/401/402 notes that already apply, and the notes checks (`notes.skeleton`, `notes.builtin`, `notes.check`) only run inside `canworks-config`. A script or Claude cannot ask which keys exist, which notes would only repeat built-in text, or whether a file it wrote is valid against the EDS.
- **No instructions.** Without a skill, the result depends on how the request is worded: guessed keys that **Import notes…** then skips, invented units, built-in text copied in, or an existing notes file overwritten.

## What Changes

- **`canworks-deploy notes` commands**, on the same code the configurator uses:
  - `canworks-deploy notes skeleton <eds>`: a notes document with the EDS identity and an entry per manufacturer object and sub-object (0x2000-0x5FFF), each with its EDS name, data type and access, to fill in.
  - `canworks-deploy notes builtin <eds>`: the built-in notes that apply to that EDS (CiA 301, plus 401 or 402 by its 0x1000 device type), as a notes document.
  - `canworks-deploy notes check <eds> <notes file>`: the schema and EDS findings the configurator's Problems pane would show, one per line; exit status 1 when there is any, 0 when there is none.
- **A Claude skill in the repository**, `.claude/skills/canworks-datasheet-notes/SKILL.md`, that writes a notes file for one EDS from the device's datasheet:
  - takes the EDS (required) and the datasheet in any common format: PDF (also scanned), DOCX, ODT, HTML or a web page, XLSX or CSV object lists, text or Markdown. No conversion to Markdown is required: a text copy is used only to find the object dictionary chapter, PDF pages are then read as laid out, and DOCX, ODT and HTML are read through a Markdown copy;
  - fills only what the datasheet states, with a `manual` page or section on every entry, and leaves out what only repeats a built-in note;
  - asks the user about each difference between the EDS and the datasheet (an object or sub-index only in one, another type, size, access, range or default) before writing: follow the EDS, use the datasheet's description anyway with the difference in `details`, or skip the object, each with "same for the rest of this kind";
  - never overwrites an existing notes file: it then writes `<eds file name>.datasheet.notes.json` for **Import notes…**;
  - runs `notes check` until it has no findings, and reports what it wrote, what it left out and why, and the differences with the choice made for each (a "datasheet is right" answer names an EDS to fix).
- Docs: `docs/configurator.md` Device notes gets "Notes from a datasheet" (the skill, the commands, how to use the skill outside a canworks checkout by copying its folder into `~/.claude/skills/`); `docs/deploy.md` (or where the deploy commands are listed) gets the `notes` commands; README gets a line.

No change to the notes format, the configurator page, the plugin or the config.

## Capabilities

### New Capabilities
None.

### Modified Capabilities
- `canopen-device-notes`: notes from a datasheet with the Claude skill.
- `canopen-deploy`: `canworks-deploy notes skeleton | builtin | check`.

## Impact

- `tools/deploy/canworks/cli.py`: `notes` subcommand dispatch, like `library` and `slave-eds`.
- `tools/deploy/canworks/notes.py`: a skeleton variant with type and access per entry; reuse of `builtin`, `check`, `identity`, `dumps`.
- `.claude/skills/canworks-datasheet-notes/SKILL.md` (new).
- Tests: `tools/deploy/tests/test_notes.py` (or a new `test_notes_cli.py`) for the three commands on a synthetic EDS from the test fixtures; a check that the skill file has valid frontmatter and names only commands that exist.
- Docs and README. PC tools version bump.
- Public repository: no real datasheet, vendor or device name in tests, docs or the skill; examples use synthetic objects.
- No hardware tasks: notes never reach the PLC.
