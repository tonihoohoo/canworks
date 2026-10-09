# Editor project fixture

A small OpenPLC Editor 4.3.x project for the configurator's tests. It is written by hand to the
editor's on-disk shapes (openplc-editor 37cdb6a, `src/backend/shared/types/PLC/open-plc.ts`) and holds
one of each place a project uses IEC locations:

| Where | Location |
|---|---|
| Modbus remote device `io-rack` (`devices/remote/io-rack.json`) | `%IW200`, `%IW201`, `%QX20.0` |
| EtherCAT device `drive1` on bus `ecat-bus` (`devices/remote/ecat-bus.json`) | `%ID100`, `%QD100` |
| Pin mapping (`devices/pin-mapping.json`) | `%IX0.0`, `%QX0.0` |
| Global variable `ai_spare` (`project.json`) | `%IW120` |
| Global variable `run_lamp`, bound to the alias `lamp` (`project.json`) | none (an alias, not a location) |
| Program variable `door_ok` (`pous/programs/main.st`) | `%IX10.1` |

There is no `canworks/` folder: tests copy the fixture and create it.
