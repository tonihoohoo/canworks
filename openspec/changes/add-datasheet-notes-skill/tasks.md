## 1. Notes commands

- [ ] 1.1 `notes.py`: skeleton entries with `x-type` and `x-access` for the CLI (configurator's first-save skeleton unchanged)
- [ ] 1.2 `cli.py`: `notes` subcommand (`skeleton`, `builtin`, `check`) dispatched like `library` and `slave-eds`; JSON to stdout or `--output FILE`; non-zero exit with the reason for an unreadable EDS or notes file
- [ ] 1.3 Tests on a synthetic EDS from the fixtures: skeleton keys, types and access; built-in notes by profile (301 only, 402); check with no findings (exit 0) and with a missing object, bits on a non-integer and a bit past the size (exit 1); unreadable files

## 2. Skill

- [ ] 2.1 `.claude/skills/canworks-datasheet-notes/SKILL.md`: inputs, formats (text copy to search, PDF pages read directly, pandoc Markdown for DOCX/ODT/HTML, tables for XLSX/CSV), fields and keys, standard objects only where they differ, `manual` on every entry, questions on each EDS/datasheet difference with "same for the rest of this kind", no overwrite (`.datasheet.notes.json`), `notes check` until clean, report
- [ ] 2.2 Test: the skill's frontmatter has `name` and `description`, and every `canworks-deploy` command it names exists
- [ ] 2.3 Try the skill by hand on a synthetic datasheet (PDF and DOCX made for the test, no real device) and a synthetic EDS with one deliberate difference; import the result with **Import notes…**; note the outcome in the PR

## 3. Docs

- [ ] 3.1 `docs/configurator.md` Device notes: "Notes from a datasheet" (the skill, what it asks, the `.datasheet.notes.json` file, copying the skill folder into `~/.claude/skills/` for use outside a checkout)
- [ ] 3.2 Deploy command docs: `canworks-deploy notes skeleton | builtin | check`
- [ ] 3.3 README: one line on notes from a datasheet
- [ ] 3.4 Bump the PC tools version

## 4. CI time

- [ ] 4.1 Compare the PR's CI wall and summed job time with the baseline (median of the last 5 green `main` runs) and state both in the PR
