## Context

Trial of the skill on three real EDS and datasheet pairs, 2026-10-15 (findings in the project's research folder). The notes format and merge rules are unchanged: a device note's field replaces the built-in field (`notes.note`), which is what the skill must now explain.

## Decisions

1. **One table, defaults filled in.** The table shows every difference with the answer the skill will use (Follow EDS), so the user changes only the rows they disagree with. Groups of one kind (for example all sub 0 defaults of the CiA 402 arrays) are one row listing their objects; the user can still split a group by naming objects. The skill does not write until the user answered. Alternative kept out: asking per row (the original rule), which gave 13-15 questions per real manual.
2. **`--all` on `skeleton`, not a new command.** The skeleton already carries `x-type` and `x-access`; adding standard objects and `x-default`, `x-low`, `x-high`, `x-pdo` behind a flag keeps one command and leaves the default output and its tests unchanged. Values are the EDS text as written (`$NODEID+0x180` stays as is), since the skill compares them with the datasheet's text.
3. **"Follow EDS" defined as "nothing the EDS contradicts".** It keeps information the datasheet adds when the EDS does not forbid it, and drops what conflicts. The difference stays visible in `details`, so nothing is silently lost.
4. **Other EDS problems are reported, not asked.** An object that gets no note needs no answer; the report lists what was seen so the user can fix the EDS.
5. **Printed page first.** It is what a reader finds in the document's footer and index; the PDF page helps in a viewer.

## Risks / Trade-offs

- **A large table** for a manual with many differences → grouped rows; the trials had 13-15 groups covering 25-30 differences.
- **Skill wording is not tested by CI** → the skill test checks commands and flags it names; a repeat run on the trial pairs (by hand, not in CI) checks the table and rules.
