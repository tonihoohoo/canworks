# Virtual plant: every feature without hardware

An OpenPLC Editor project that runs on the [local simulator runtime](../../docs/local-runtime.md) with no CAN adapter and no devices. Every network is simulated (`adapter.simulate`), and every device is made up. [docs/tour.md](../../docs/tour.md) walks through it.

## The networks

| Network | Bus | What it shows |
|---|---|---|
| `io` | `sim0`, 250 kbit/s | The master with SYNC from a timer (20 ms) and the TIME producer. Node 5 `rtd` (RTD-8, CiA 404): mandatory, a PDO receive timeout, startup SDOs. Node 6 `dio` (DIO-16, CiA 401): the PDO mapping written from the config (the module maps nothing by default), configuration check (0x1020) with opt-in store (0x1010), TIME consumer, NMT command byte, two SDO variables. Node 7 `new_io` (DIO-16): no node ID until the master gives it one with LSS by its serial number. An extra device `spare_io` waits for LSS without being in the config. |
| `motion` | `sim1`, 500 kbit/s | SYNC from the PLC cycle and node 4 `drive` (SD-402, CiA 402) as a PLCopen axis in cyclic synchronous position mode. |
| `cell` | `sim2`, 250 kbit/s | OpenPLC as slave node 20 and gateway: its EDS is generated from `cell_eds.json`, two routes (RTD channel 0 up, DIO-16 analogue output 1 down), field node status, EMCY forwarding, the SDO bridge, outputs to 0 when the upper master is lost. |
| `host` | `sim2`, 250 kbit/s | A master network on the cell's bus that stands in for the machine controller above the cell ([gateway.md](../../docs/gateway.md#trying-it-without-an-upper-master)). |

The diagnostics channel is on with changes allowed. Its token is `virtual-plant-demo`; that is fine on your own PC, but set a token of your own (the configurator's **Online access**) before the config goes anywhere else.

## The program

`pous/programs/main.st` starts with what `canworks-deploy --new-project --blocks --task-interval T#10ms` declares for this config, then:

- scales RTD channel 0 to °C and switches DIO-16 output 0.0 on above the limit the host sets (25.0 °C), which also goes to the host as the cell's `alarm` with an EMCY;
- runs a light along DIO-16 output byte 2 and checks it comes back on input byte 2 (the simulated CiA 401 module loops outputs to inputs);
- switches `new_io` output 0.0 on when a node is lost, the RTD's PDO times out or an EMCY is active, and output 0.1 when the host sees a field node missing in the gateway status;
- resets node 6 when you set `restart_dio` in the debugger (NMT command byte);
- reads node 5's product code, node 4's supported drive modes (on network `motion`) and writes node 6's 0x6423 with the SDO function blocks;
- as the host: starts the line, sets the alarm limit and sends the temperature it gets from the gateway back down to DIO-16 analogue output 1;
- powers the drive, homes it and moves it between 0 and 1000 in CSP while the host runs the line.

## Files

| File | What it is |
|---|---|
| `project.json`, `devices/`, `pous/` | The editor project (Editor 4.3.2 layout, OpenPLC Runtime v4 target, the `canworks` library enabled). |
| `canworks/canworks.json` | The CANopen config (`schema_version` 2). |
| `canworks/simulation.json` | The simulation file, version 2 with sections `io` and `motion`: value sources on the RTD (sine, random walk, ramp, a formula), the drive model's settings, the extra device, an autostart wire-break every 60 s, and four test scenarios. |
| `canworks/dio16.eds` | DIO-16, written by `make_dio16_eds.py` (run it from this folder: `python3 make_dio16_eds.py > canworks/dio16.eds`). |
| `canworks/rtd8.eds`, `canworks/servo402.eds` | Copies from [`config/rtd-sensor`](../../config/rtd-sensor/README.md) and [`config/cia402-drive`](../../config/cia402-drive/README.md). |
| `canworks/cell_eds.json`, `canworks/cell.eds` | The cell slave's description and its EDS: `canworks-deploy slave-eds canworks/cell_eds.json -o canworks/cell.eds --gateway canworks/canworks.json`. |

CI deploys the example to the local simulator runtime image and runs its test scenarios ([`test/virtual-example/run.sh`](../../test/virtual-example/run.sh)).
