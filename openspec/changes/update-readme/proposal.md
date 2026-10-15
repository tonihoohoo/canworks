## Why

The README has kept up with every change, but by adding to sentences rather than restructuring. The PC tools table's `canworks-config` cell is now one paragraph of about 450 words, and `canworks-deploy`'s cell lists every export in one sentence, so the tools that changed most on 2026-10-15 (one Connect place, the Commission workspace, trace decoding without a config, the Notes tab, CODESYS export, gs_usb on Windows with nothing to install) are the hardest to find. The datasheet notes skill, the repository's first Claude skill, is a half sentence inside that cell.

## What Changes

The full proposed README is [`readme-draft.md`](readme-draft.md) in this change; on apply it replaces `README.md`. Everything above **PC tools** and from **Development** down stays word for word, logo included.

- **PC tools:** the adapters become a three-line list (slcan everywhere; gs_usb on Windows with nothing to install, on macOS with libusb; SocketCAN on Linux). Each command's table cell is one or two sentences that say what it is for and link its doc.
- **New section Configurator:** what used to be the `canworks-config` cell, as one bullet per area in the order a user meets them: Configure, Connect…, Commission, Commission a CANopen device, Trace, Exports, Device notes, keyboard and icons. Every label is the one the page shows. No feature is dropped.
- **New section Device notes from a datasheet with Claude:** the `canworks-datasheet-notes` skill (what it reads, that it asks where datasheet and EDS differ, that it checks its result with `canworks-deploy notes check`), linked to the skill file and to the configurator doc.
- **Requirements and limits:** a CODESYS export line (CANopen master networks only; CODESYS V3.5 on Windows, tested with SP22).
- **Documentation table:** a row for device notes.

Not changed: the intro, How it works, Quick start, the PLC feature sections, Development and License. No doc under `docs/` changes.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `toolkit-names`: adds a requirement on the README's layout (short command table, one section per larger tool, the Claude skill named), next to the existing logo requirement.

## Impact

- `README.md` only. No code, config, CI or package change; no version bump.
- The banned-words guard covers the README like any other file.
