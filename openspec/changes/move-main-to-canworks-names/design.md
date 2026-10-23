## Context

Change 1 made OpenPLC a Modbus target. A plugin project switched to it keeps `main` as the plugin version wrote it: one `VAR` block of located variables (`editorproject.main_st`), followed by user code. The new `canworks` global list (`openplcmodbus.global_list`) has one member per located value with the same name, so every old declaration has a one-to-one replacement.

## Goals / Non-Goals

**Goals:** a user who switched sees that `main` reads stale locations, and can fix it with one click that keeps their code working.

**Non-Goals:** rewriting other POUs; CiA 402 axis code (leaves with `remove-openplc-plugin`); a general ST refactoring tool; doing it automatically on Save.

## Decisions

1. **Which declarations are canworks'.** A declaration in a `VAR` block of `main` of the form `name : TYPE AT %…;` whose `name` is a member of the `canworks` list. Name match, not location match: locations were repacked by the switch, while names are kept, and the user's own hardware I/O (`%IX0.0` pins) never has a canworks value's name. Alternative rejected: match on the plugin's address range, which fails after a repack and could hit user I/O.
2. **Uses become `canworks.<name>`.** A small ST scanner walks the body and skips `(* *)` and `//` comments and `'…'`/`"…"` strings; it replaces a whole identifier (case-insensitive, as IEC 61131-3 is) that is not preceded by `.`. A name also declared without a location in `main` is a clash: it is neither removed nor replaced and is named in the message.
3. **Types.** The member's type can differ from the old declaration (for example `WORD` before, `INT` now, from the value's CANopen type). The move does not cast; a type the code cannot take shows up as an editor Build error on that line, which the message mentions once.
4. **Explicit button, backup.** The move changes the user's POU, so it runs only on the button and writes `canworks/main-before-move.st` first (overwritten by a later move). The write uses the same atomic replace as Save. No config change, so Undo in the configurator does not apply; the copy is the way back.
5. **Where it shows.** The Project page notice (warning bar with the button), a Problems warning (`main declares N canworks values at plugin locations`) that opens the Project page, and one sentence in the banner after **Switch to OpenPLC through Modbus**. The scan runs with the project scan the page already does, so no extra request per check.

## Risks / Trade-offs

- [The editor has `main` open and writes its own copy back] → same "reopen the project before Build" message as Save; the backup keeps the earlier text.
- [A user's own variable has a canworks value's name by chance] → it would be moved; the message lists moved names and the backup restores them.
