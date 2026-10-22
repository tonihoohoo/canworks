## Context

Four things carry "sim" today:

| Today | What it is | Protocols | Runs on |
|---|---|---|---|
| simulated devices (`adapter.simulate`, `simulate`) | C++/Lely devices inside the plugin | CANopen, plain CAN | any runtime, Docker too |
| `canworks-sim` | the same engine as its own program, control port 7532, `test` mode | CANopen, plain CAN | Linux runtime host, SocketCAN |
| `canworks-sim-runtime` | OpenPLC runtime + plugin in a container, every network forced simulated | everything but J1939 | PC with a container engine |
| `canworks-j1939-sim` | Python ECU from a DBC (can-j1939) | J1939 | PC, SocketCAN or USB adapter |

The CANopen and J1939 simulators are separate for real reasons. They read different descriptions (EDS against DBC). The CANopen engine lives in the plugin, on its in-process virtual bus. The plugin runs J1939 on the kernel's `CAN_J1939` sockets, which can't run on that bus. And the two ship in different packages (the plugin install against the PC tools wheel). Only the names and the docs make this hard to follow.

## Goals / Non-Goals

**Goals:**
- Each command name says what it is: the protocol for a simulator, and no "sim" for something that isn't one.
- One docs page answers "how do I simulate X" for every X, including why J1939 differs.
- The configurator doesn't silently hide Simulation on J1939 networks.

**Non-Goals:**
- Merging the engines or one `canworks-sim` front end that dispatches to both. They live in different packages on different platforms, so one command would lack half its modes on each machine.
- J1939 ECUs on the plugin's virtual bus, which would let J1939 run in the local runtime. That's a feature of its own and would need its own explore.
- Renaming the simulation file schemas (`canworks-sim.v1/v2`) or the `simulation.json` file. They describe the simulation file, which both the plugin and the CANopen simulator read, so "sim" is accurate there.
- Renaming the requirement headings in specs ("Standalone simulator on a SocketCAN interface"). Headings are identifiers, and only their text changes.

## Decisions

1. **`canworks-local-runtime`, not `canworks-runtime`.** "Local" says it runs on this PC, and matches the docs' existing "local runtime" and the `local-runtime.md` / `canopen-local-runtime` names. A plain `canworks-runtime` could be read as the plugin's runtime on the Pi.
2. **`canworks-canopen-sim`, not `canworks-device-sim`.** It sits next to `canworks-j1939-sim` and says what's left out. "Device sim" would suggest it also plays J1939 ECUs. Its help text and the docs say it also plays plain CAN devices from the simulation file.
3. **Clean cut** (the project is not in real use yet): no aliases, no image re-tags. `install-stock.sh` removes the old binary and link only so the bench Pi keeps no dangling link. The local runtime doesn't look for an old container: the bench PCs remove one by hand.
4. **Retired names in the name check.** `scripts/rename_to_canworks.py --check` already fails CI on pre-canworks names. It gets a second list of retired names, `canworks-sim-runtime` and bare `canworks-sim`, matched with a pattern that skips `canworks-sim.v1`/`.v2` and anything under `openspec/changes/archive/`. Its old mapping `openplc-canopen-sim-runtime` moves to `canworks-local-runtime`.
5. **J1939 Simulation tab.** It stays visible on J1939 networks and shows one line with a copyable `canworks-j1939-sim --dbc <network dbc> --node NAME --interface IF` and a link. The Simulated device tab and the Simulation file page stay hidden, because they have nothing to show there.
6. **Docs structure.** `docs/simulator.md` keeps its file name, so links don't break. It gets the title "Simulation", an overview table and a "Why two simulators" paragraph, followed by today's CANopen content under "CANopen and plain CAN devices", with `canworks-canopen-sim` as a subsection. The J1939 simulator stays in j1939.md and the table links it. The README command table lists `canworks-canopen-sim` (runtime host) and `canworks-j1939-sim` next to each other, and drops the separate "On the runtime host" sentence for the simulator.

## Risks / Trade-offs

- **The rename touches many files (~60), so it could conflict with in-flight PRs.** Mitigation: land it when no other PR is open, as rename-to-canworks did, and make the replacement a script run (`sed`-style with the same pattern as the check) so a rebase can re-run it.
- **Old ghcr image `canworks-sim-runtime`.** No user pulls it. Release retention removes old tags, and the package itself can be deleted by Toni later.
- **Stale scripts on the bench (fwtest helpers, guides in project files) still say `canworks-sim`.** These are outside the repo. The tasks list updating the Windows real-devices guide.
