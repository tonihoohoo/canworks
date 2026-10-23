## Why

The bridge's mailboxes cost every poll, whether or not the program calls a mailbox block. In `examples/openplc-modbus` they take 7 Modbus requests per poll instead of 5. They also mean 355 polled registers instead of 49, and 349 copy assignments per PLC scan instead of 41. The PLCopen export (truST, other PLCs) and the Node-RED flow poll and copy the same words. Yet a normal PLC program needs none of it: its values, `CO_NMT`, `CO_NODE_LIVE` and `CO_SDO_READ`/`WRITE` (up to 4 bytes) work without mailboxes. Only things the program decides at run time need them: SDOs over 4 bytes, every EMCY, CAN ids that are not in the config, J1939 requests and DM2/DM3/DM11, and bus load and error counters.

Today an OpenPLC config turns them on by itself, and the configurator never says whether the program uses them. With the switch off, the Function blocks section shows no cost and does not say what still works. A program that calls a mailbox block while its part is off builds fine and fails at run time with `ERROR_ID` 22. The New editor project checkbox "Enable the canworks function blocks" installs the library, which has nothing to do with this section.

Toni (2026-10-23): "is it clear to user when mailboxes are used and when not?", "is there a setting to disable it and go native way", "why should they be on by default?", "this applies only to OpenPLC, what about the others?", then "propose". Explore report: `research/mailbox-clarity-2026-10-23.md`.

## What Changes

- **Off by default.** New configs, adding an OpenPLC connection and every other connection start without `bridge.mailboxes`. `examples/openplc-modbus` keeps them, because its program uses the blocks.
- **The OpenPLC program decides (Problems).** For a config with an OpenPLC connection, Check and Save scan the editor project's POUs for mailbox block calls. If a called block's part is off, that is an error naming the POU and block, with **Turn on what the program uses**: one undo step that turns on only the needed parts and places the areas. If the mailboxes are on and no POU calls a mailbox block, an info says what turning them off saves, with **Turn off the mailboxes**.
- **The other connections say what their program uses.** truST, Other PLC and Node-RED connections get a **canworks blocks** choice:
  - **None**;
  - **SDO and send** (1 request mailbox);
  - **SDO, send and receive** (+ the receive mailbox);
  - **All** (+ cyclic jobs and network info).

  The config's mailboxes follow the choice, in the same undo step. Only one program can own the mailboxes, so at most one connection picks something other than None, and none next to an OpenPLC connection. truST offers only None and SDO and send, which fit its one request each way. HMI connections have no choice.
- **Function blocks section: a clear choice with numbers both ways.** These show whether the switch is on or off:
  - a **Works without mailboxes** list;
  - a **Needs mailboxes** table, with each block's config-only alternative (for example an `rx` message for `CAN_RECEIVE`);
  - the cost as a difference: "+227 input / +79 holding registers, 7 instead of 5 Modbus requests per poll".

  With connections, the section says which connections need which parts.
- **Connection rows show the mailbox state**, for example "canworks blocks: SDO and send (1 request mailbox)".
- **Mailbox use in the bridge status.** The bridge reports how many mailbox operations ran and how many receivers were opened since it started. `canworks-deploy diag` prints it, with a hint when the mailboxes are on and nothing has used them.
- **New editor project checkbox** becomes "Install the canworks library in the project". Its hint says the mailbox blocks also need the mailboxes, which Problems offers once the program calls them.
- **Docs and README.** `docs/plc-library.md` gets a "With or without the mailboxes" section: what works without them, what each part costs, what cannot be done without them, and the config-only alternatives. `modbus-bridge.md` and `configurator.md` link to it, and the README says it in one sentence.

Not in real use, so this is a clean cut: no migration of configs that have mailboxes.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `canopen-configurator`: Function blocks section (default off, always-visible lists and cost, connection needs), New editor project in standalone mode (checkbox wording), and new requirements "Mailbox blocks the OpenPLC program declares", "Turn on what the program uses" and "Mailboxes nobody needs".
- `modbus-connections`: OpenPLC connection bridge settings (no mailboxes), Connection kinds (`blocks` on trust, plc and nodered), and new requirements "Canworks blocks choice of a connection", "Mailboxes follow the connections" and "One program owns the mailboxes".
- `modbus-bridge-mailboxes`: new requirements "Mailbox use in the status" and "Mailbox use in diag".
- `plc-library`: Library documentation (the "With or without the mailboxes" section).

## Impact

- **PC tools:**
  - configurator `bridge.js` (Function blocks section, connection rows and the blocks choice);
  - `app.js` (Problems, the New editor project wording);
  - `server.py` (the POU scan in check);
  - a new `mailboxuse.py` that finds mailbox block calls in ST POUs, and its tests;
  - `modbusmap.py` / `bridgecheck.py` (`blocks` on connections);
  - `diag.py`;
  - a version bump (minor).
- **Bridge:** `bridge_host.cpp` status JSON gets `mailboxes` (operations, receivers opened); C++ test.
- **Schema:** `blocks` on `trust`, `plc` and `nodered` connections.
- **Docs:** `plc-library.md`, `modbus-bridge.md`, `configurator.md`, README.
- **Tests:** page tests for the section, the blocks choice and the Problems fix; examples checked (the virtual plant has no mailboxes and its program calls no mailbox block; `examples/openplc-modbus` keeps them and passes the scan).
- **Order:** after `modbus-connections`, `faster-mailboxes` and `add-nodered-blocks`. The Node-RED connection's blocks choice needs the block nodes of `add-nodered-blocks`.
