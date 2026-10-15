## Context

Notes are documentation on the PC (spec `canopen-device-notes`). The format, built-in notes, merge rules, checks and import already exist in `tools/deploy/canworks/notes.py` and are used only by `canworks-config`. The repository already ships Claude skills under `.claude/skills/` (the OpenSpec ones), which Claude Code loads when it runs in a canworks checkout.

## Goals / Non-Goals

**Goals:** a notes file from a datasheet that imports cleanly and is only as confident as its source; tools a script or Claude can use to anchor and check notes without the configurator.

**Non-Goals:** reading datasheets inside canworks itself (no PDF parsing in the tools, no Claude API call from canworks); changing the EDS from the datasheet; XDD import; a configurator button for the skill.

## Decisions

1. **EDS is a required input.** Keys must be objects the EDS has (import skips the rest), and the EDS gives names, types and sizes the datasheet often leaves implicit. Without an EDS the skill asks for one instead of guessing keys.
2. **Thin CLI over `notes.py`, not a new module.** `skeleton` extends `notes.skeleton` with `x-type` and `x-access` per entry (unknown `x-` fields are allowed by the schema and kept on save; the skill drops them in its output). `builtin` returns `{"format", "eds", "objects": notes.builtin(eds)}`. `check` prints `notes.check` findings. Output is JSON on stdout (`-o FILE` writes a file) so the skill can read it without parsing text. Alternative considered: a Python snippet in the skill importing `canworks.notes`; rejected because it ties the skill to internal function names and fails on the PyInstaller-built PC tools, which have no importable package.
3. **No mandatory Markdown step.** Converting a PDF to Markdown loses bit tables, merged cells and the page numbers `manual` needs. The skill extracts text only to search for indices (`2000h`, `0x2000`, `Index 2000`, `2000 sub 1`), then reads the found PDF pages directly (as images when scanned). DOCX, ODT and HTML keep their structure through `pandoc -t gfm`, so that Markdown copy is what it reads; sections stand in for page numbers. XLSX and CSV are read as tables.
4. **Differences are the user's call, one at a time.** Notes cannot change the EDS, and which source is right depends on the device revision in hand. The skill collects differences while reading and asks before writing, one question per difference with what each source says and the page, three answers (follow the EDS / use the datasheet's description, difference in `details` / skip) and "same for the rest of this kind", so a manual with many shifted sub-indices does not mean many questions. Not asked: objects the datasheet simply does not describe (left out, listed in the report).
5. **Never overwrite.** If `<eds>.notes.json` exists, the skill writes `<eds>.datasheet.notes.json`; **Import notes…** then previews new / changed / same and can be undone. The skill does not merge into the existing file itself, so the user's own notes are never lost to a Claude edit.
6. **Built-in notes are not repeated.** The skill reads `notes builtin` and writes standard objects (0x1000-0x1FFF, 0x6000-0x9FFF) only where the datasheet says the device differs: its own scaling, extra or missing values, manufacturer bits. Import would drop equal fields anyway, but reworded built-in text would show as "Built-in, changed".
7. **Skill lives in the repository.** It versions with the commands it calls; outside a checkout, copying the folder into `~/.claude/skills/` makes it available, which the docs say.

## Risks / Trade-offs

- **Wrong facts from a misread table** → every entry carries `manual` so the user can check it; uncertain items are left out, not guessed; import preview shows everything before it lands.
- **Skill behaviour is not tested in CI** → CI tests the commands and that the skill names only existing commands; the skill itself is tried by hand on a synthetic datasheet (task).
- **Copyright of long datasheet text** → the skill writes short summaries, not copied passages.
