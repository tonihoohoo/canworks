## Context

`build_network` adds a CANbus only when `find_canbus` finds none with the network's number under the chosen device. It then takes `like = _ident(buses[0]) if buses else _highest(repo, 15, "181015")`: the first CANbus of *this device*, else the stock CANbus. On the display project the active device had no CANbus, so the stock one was used and refused. CODESYS refuses a child that the parent's device description does not allow, and a refused `add` leaves nothing behind (the existing `_add` already checks for a new child).

## Decisions

### 1. Candidate list, first accepted wins
Build an ordered, de-duplicated list of `(type, id, version)` for type 15:
1. For every type-15 device in the project (`proj.get_children(True)`), if its parent's identification equals the chosen interface's identification: that bus's identification. These fit by construction (same interface type already holds one).
2. Every other type-15 device's identification in the project.
3. `repo.get_all_devices()` type 15, highest version per id, stock id last.
De-duplicate by (id, version); within 1 and 2 newest version first.

Try `_add` with each until one succeeds; collect `(identification, message)` for the refusals. The cost is one `add` attempt per candidate; projects and repositories hold few CANbus types (typically 1 to 5).

Alternatives: reading the interface's allowed children from its device description (not exposed by the script API documented for SP22); asking the user to name the CANbus id (extra config field nobody knows the value of). Rejected.

### 2. Manager version
Today the manager uses the version equal to the bus version, else the highest. Vendor CANbus versions differ from the stock manager's, so first use the manager identification that sits under another CANbus with the same identification in the project, then today's rule.

### 3. Report
- `created  network can0: CANbus <name> (<id> <version>, as on device X) under <path>, network number 0`.
- On total refusal the existing `_refused` error gets a `tried:` list of `<id> <version>: <message>` (messages shortened to the first sentence).
- `warn_other_devices` collects names per network and writes one warning: `network can0: 22 other devices also have a CANopen Manager on network number 0 and were left as they are: A, B, C, D, E and 17 more`.

### 4. Build dialog
`codesysBuild` reads the `device` line from the report (`device  <name> (<reason>)`) and uses it in the dialog's first sentence; with no such line the text stays as today.

## Risks

- A CANbus the interface accepts but that is the wrong one (two vendor CANbus kinds both allowed). Order 1 makes this unlikely; the report names the one used, and an existing bus is always reused instead.
- The probe of real behaviour (refusal leaves no child, error text) is from Toni's report; task 0.1 checks it on the real project before relying on it.
