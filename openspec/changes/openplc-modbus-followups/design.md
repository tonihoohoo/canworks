## Context

The hardware run of `add-openplc-modbus-target` (runtime v4.3.1, tools 0.116.0, real CANopen node) passed tasks 7.1-7.4 and found the items in the proposal. Each is small. They share one route and one bench check, so they go in one change.

## Decisions

1. **Restart baseline, not persisted counters.** On start the bridge does not know the client's last counter. Storing counters on disk would still replay after a crash between run and store.
   - So the first control block and the first SDO request after a start are only remembered: echoed with "not run" and not executed.
   - A request the PLC really meant at that moment ends with ERROR_ID 8 instead of running twice. The program can retry; a repeated NMT reset or SDO write cannot be undone.
   - Only for configs with `bridge.openplc`. OpenPLC's Modbus master rewrites the whole output image every poll, so its last request is still there after a restart. Other Modbus clients (Node-RED, HMIs, SCADA) usually write the block only when they send a command, so their first write is a real request and must run. A client that rewrites its outputs cyclically without the link header can avoid a replay by putting counter 0 back after its command ended.
   - "First" means the first write that carries the block (tracked per output byte). With OpenPLC that is the first accepted write, after the PLC link header matched.
   - Alternative rejected: compare with a zero image. The PLC's request block is never zero after its first job.
2. **Result codes.**
   - Control result 6 is new. SDO uses its existing status 3 (aborted) with abort code 0x08000021 ("data cannot be transferred because of local control"; 0x08000022 already means the SDO queue is busy).
   - The blocks map both to the existing ERROR_ID 8 (cancelled), which programs already treat as "start again". `add-bridge-mailboxes` ends a replayed mailbox request the same way, so every bridge block reports a restart with one code; a new code would make programs check two.
3. **Which declarations in `main` are canworks'.** A declaration `name : TYPE AT %…;` in a `VAR` block of `main` whose name is a member of the `canworks` list.
   - Matching is by name, not location: the switch repacks locations but keeps names, and the user's own hardware I/O never has a canworks value's name.
   - A name also declared without a location is a clash. It is neither removed nor replaced, and the message names it.
4. **The rewrite.** A small ST scanner skips `(* *)` and `//` comments and `'…'`/`"…"` strings. It replaces a whole identifier, case-insensitive as in IEC 61131-3, when it does not follow a `.`.
   - Types can differ from the old declaration (for example `WORD` before, `INT` now). The move does not cast; an editor Build error points at the line, and the message says so once.
   - The button writes `canworks/main-before-move.st` first and uses the same atomic replace as Save.
5. **Library on Save.** Save uses `plclibrary.enable_in_project` and the editor install that New editor project already uses. It runs only when the project does not have the library enabled already, so a normal Save does not touch `project.json` twice.
6. **Live lists for unnamed networks.** A network without a `name` already goes by its adapter's interface in the checks and in the bridge, so the switch uses that name for its live list and renames nothing.
7. **Pre-operational per node.** NMT node 0 would also stop devices canworks does not manage, such as another master's nodes on a shared bus. The bridge already loops the configured nodes, so only the spec text and scenario change.

## Risks / Trade-offs

- **A PLC that writes a fresh request exactly at a bridge restart gets ERROR_ID 8.** The library doc tells programs to start again on 8.
- **The editor has `main` open and writes its own copy back.** The move shows the same "reopen the project before Build" message as Save, and the backup keeps the earlier text.
- **A user's variable has a canworks value's name by chance.** It would be moved. The message lists the moved names, and the backup restores them.
