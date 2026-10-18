# Design: remove-gantry-cell-demo

## What goes with the demo

The rule was: remove what exists only for the demo, keep generic infrastructure that something else uses.

| Piece | Other users | Decision |
|---|---|---|
| `examples/gantry-cell` | none | remove |
| Machine model (`sim_machine.*`), machine file, `canworks-sim-machine.v1` schema | none: `gantry_xyz` is the only kind and only the gantry example names a machine file | remove |
| Machine tab, `machine_view.js`, `machine_scene.js`, vendored three.js | three.js is imported by the two machine files only | remove |
| Operator panel, virtual safety relay, scanner, `sim_panel`, `sim_person` | machine only | remove |
| Drive model safe torque off input | set only by the relay | remove |
| Drive model load torque and machine-set inputs | machine only; user-set inputs through faults stay | remove the machine half |
| Machine faults and machine conditions in scenarios | machine only | remove |
| Bit channels, device notes, `panel` as a spec example name | generic, used by any config | keep |
| `servo402.eds`, `dio16.eds` | `examples/virtual-plant` has its own copies | keep there |
| STruC++ test build | `sim_cia402_demo`, `sim_cia402_cyclic` | keep, drop only the gantry program target |

## Tests that borrowed the example

Several tests used the gantry files only as a convenient config with drives and I/O. They switch to `examples/virtual-plant` (one CiA 402 drive, DIO-16, RTD) or a small fixture where they need something the example lacks: the CODESYS motion override tests need more than one drive, so they get a fixture config under `tools/deploy/tests/data/`. The rename test is a pure path mapping; its sample path becomes a virtual-plant path.

## Clean cut

A simulation file section with `machine` fails the schema's `additionalProperties` check like any unknown key. No warning-and-ignore path, no migration note beyond the change itself.

## Specs

`canopen-machine-model` and `canopen-machine-view` lose every requirement. If the archive leaves an empty spec file, the archive commit deletes both spec folders.
