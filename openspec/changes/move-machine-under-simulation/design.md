## Context

The rename to canworks (PR #44) lands first; this change is planned on top of it, so every path here is a canworks path. The project is not in real use, so renames are clean cuts with no aliases or redirects.

## Goals / Non-Goals

**Goals:** a user finds the machine where the simulator is, in the configurator and in the docs, and every name says it is simulated.

**Non-Goals:** changing the machine model, the file format, the diagnostics ops or the plugin layout; renaming OpenSpec capabilities (they are not user-facing, and a rename would mean removing and re-adding every requirement).

## Decisions

1. **A tab of Simulation, using the whole content area.** The Simulation view already has tabs (Live values, Simulation file, Scenarios). Machine becomes the fourth, shown only when the open network's section names a machine file, like the sidebar item today. The 3D scene needs room, so when the Machine tab is selected the view takes the whole content area as the Machine view does now, instead of the Problems pane's room. The URL state and the remembered tab follow the existing Simulation tab state (`SIM.tab = "machine"`). Alternative: keep a sidebar item, renamed "Simulated machine". Rejected: it still sits beside Simulation instead of in it, which is what Toni asked about.
2. **One simulator document with two parts.** `docs/simulator.md` (343 lines) plus `machine.md` (98 lines) is about 440 lines, the size of other docs here. Its title becomes "Simulator"; "Simulated devices" and "Simulated machine" are its two top-level parts, with today's `##` sections below them as `###`. Anchors change; every link in the repository is updated in the same change, checked once with a link script while doing it (no new CI test, so CI time does not grow).
3. **`simmachine.py`** matches `simfile.py`, `simcli.py` and `simclient.py`.
4. **`canworks-sim-machine.v1.schema.json`** matches `canworks-sim.v1/v2`. The `$id` inside changes with it; `canworks-sim.v2.schema.json` refers to the new name.

## Risks / Trade-offs

- [Page test shards drift when test classes are renamed] → rename the keys in `.github/ci/page-test-times.json` in the same commit; unknown classes would otherwise count as the median.
- [Links to `docs/machine.md` from outside the repository break] → accepted: nothing outside links to it yet.
- [A long Simulation view in the narrow layout] → the tab list wraps as it does now; the Machine tab keeps its own toolbar.

## Migration Plan

None for projects. On the bench, the next deploy of the gantry example uses the new schema copy shipped with the tools; nothing on the Pi refers to the schema file.
