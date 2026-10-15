## Context

Trials of the skill on three and then 11 more real EDS and datasheet pairs, 2026-10-15 (findings in the project's research folder and the PC's trial folder). The notes format and merge rules are unchanged: a device note's field replaces the built-in field (`notes.note`), which is what the skill must now explain.

## Decisions

1. **One table, defaults filled in.** The table shows every difference with the answer the skill will use (Follow EDS), so the user changes only the rows they disagree with. Groups of one kind (for example all sub 0 defaults of the CiA 402 arrays) are one row listing their objects; the user can still split a group by naming objects. The skill does not write until the user answered. Alternative kept out: asking per row (the original rule), which gave 13-15 questions per real manual.
2. **`--all` on `skeleton`, not a new command.** The skeleton already carries `x-type` and `x-access`; adding standard objects and `x-default`, `x-low`, `x-high`, `x-pdo` behind a flag keeps one command and leaves the default output and its tests unchanged. Values are the EDS text as written (`$NODEID+0x180` stays as is), since the skill compares them with the datasheet's text.
3. **"Follow EDS" defined as "nothing the EDS contradicts".** It keeps information the datasheet adds when the EDS does not forbid it, and drops what conflicts. The difference stays visible in `details`, so nothing is silently lost.
4. **Other EDS problems are reported, not asked.** An object that gets no note needs no answer; the report lists what was seen so the user can fix the EDS.
5. **Printed page first.** It is what a reader finds in the document's footer and index; the PDF page helps in a viewer. A document prefix only when there are several documents, so the common case stays short.
6. **Stop on an EDS that does not load.** The configurator refuses the same EDS, so notes written against a patched copy would not match what the project uses. The fix is the error naming the line (configparser has it; the reader drops it today) and the skill reporting it. Alternative kept out: a tolerant reader for the notes commands only.
7. **Name the missing profile, do not add it here.** Built-in 404/406/410 notes are content work of their own. `builtin` saying which sets applied lets the skill switch to the rule for profiles without notes instead of guessing.
8. **Format limits go to `details`.** Multi-bit fields, ranges and write signatures came up in 4 of 11 runs; a format change touches the configurator and the import. `details` keeps them readable until a format change is worth it.
9. **Object keys in the skeleton only with `--all`.** The project-save skeleton (`Notes file created with the project`) keeps its keys; the comparison view gets the ARRAY/RECORD names it needs.

## Risks / Trade-offs

- **A large table** for a manual with many differences → grouped rows; the trials had 13-15 groups covering 25-30 differences.
- **Skill wording is not tested by CI** → the skill test checks commands and flags it names; a repeat run on the trial pairs (by hand, not in CI) checks the table and rules.
- **More rules make the skill longer** → the new rules are one line each, grouped under values, references and sources.
