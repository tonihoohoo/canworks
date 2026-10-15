## ADDED Requirements

### Requirement: README tool descriptions
The README SHALL keep its PC tools command table to one or two sentences per command, each linking that command's doc, and SHALL describe the configurator in its own section with one bullet per area (Configure, Connect, Commission, Commission a CANopen device, Trace, Exports, Device notes, keyboard and icons), using the labels the page shows.

#### Scenario: New reader looks for the trace
- **WHEN** a reader opens the README and looks for how to decode a bus trace
- **THEN** the Configurator section has a Trace bullet that links `docs/trace.md`, outside the command table

### Requirement: README adapters, skills and export limits
The README SHALL name the USB adapter types the PC tools drive and what each needs per operating system, SHALL name every user-facing Claude skill under `.claude/skills/` (not the OpenSpec workflow skills) with a link to its file, and SHALL list the limits of every export to another vendor's tool under Requirements and limits.

#### Scenario: Claude skill
- **WHEN** a reader looks for how to write device notes from a datasheet
- **THEN** the README has a section naming the `canworks-datasheet-notes` skill with a link to its `SKILL.md`

#### Scenario: Adapter on Windows
- **WHEN** a Windows user reads which USB adapters work
- **THEN** the README says gs_usb adapters need nothing else installed on Windows
