# CANopen networks in CODESYS

A canworks config can be built into a CODESYS project, so a CODESYS controller or display with a CAN interface runs the same bus with CODESYS's own CANopen Manager: the nodes, their PDOs, COB-IDs, transmission types and timers, heartbeat, startup SDOs and a variable name on every mapped I/O channel. canworks keeps doing what it does around the bus: the configurator, checks, simulated devices, bus trace and commissioning.

## How it works

The export is a folder:

| File | What it is |
|---|---|
| `<network>/node_<id>.dcf` | Each node as a CiA 306 DCF, the same files `--export-dcf` writes ([deploy.md](deploy.md#export-the-nodes-as-dcf-files)). CODESYS's device repository takes a DCF like an EDS and reads its `ParameterValue` entries, so the device arrives with the configured PDO communication and mapping parameters, heartbeat time and startup SDOs. |
| `canworks-codesys.json` | The plan: every network's CODESYS network number, bit rate and CANopen Manager settings, every node's settings and I/O channel names, and the settings that have no CODESYS counterpart. |
| `import_canworks.py` | The script CODESYS runs. It is the same file for every config. |
| `README.txt` | How to run it. |

The script uses the project's active device (the one whose application is the active application), finds or adds a CANbus with the network's number and a CANopen Manager under it, installs each node's DCF into the device repository and adds the node straight away, sets the settings, names each I/O channel and builds the project. It writes `import_report.txt` next to itself and prints the same report in CODESYS's message view.

Numbers in the config are read as the checks read them, so a node ID or PDO number written as a string (`"node_id": "0x02"`, `"number": "1"`) gives the same export as the plain number. When the I/O channels cannot be named, the export stops with an error (naming the field of the node and PDO when the config is at fault) rather than leaving the channels out.

Get the folder from the configurator (**Export > CODESYS**, a zip) or from the command line:

```sh
canworks-deploy --config canworks.json --export-codesys codesys/
```

## Run it in CODESYS

1. Open your project in CODESYS. It needs the PLC or display device that has the CAN interface; the script adds nothing else to the project tree. With several devices in the project, make the one that gets the bus active first (**Set Active Application** on its application, the same choice Build and Login use).
2. **Tools > Scripting > Execute Script File...** and pick `import_canworks.py` in the export folder.
3. Read the report, check the project and save it. The script does not save a project you have open.

## Run it from the command line

```sh
canworks-deploy --config canworks.json --codesys-import "C:\Projects\Line 2\cell.project"
```

writes the export into a temporary folder, runs CODESYS headless on the project, prints the report and saves the project when nothing failed. The exit status is 1 when the report has an error. `--codesys-dir DIR` keeps the export in DIR. `--codesys-new TYPE:ID:VERSION` creates the project with that PLC device from CODESYS's device repository (for example `"4096:0000 0004:3.5.22.40"`, CODESYS Control Win V3 x64), where `--codesys-import` names a project that does not exist yet.

The tool uses the newest CODESYS in the program folders and its newest profile; `--codesys-exe` and `--codesys-profile` pick another one, for example a device vendor's own CODESYS installation. Without the deploy tool, set `"project"` in `canworks-codesys.json` to the project's path and run:

```sh
CODESYS.exe --profile="CODESYS V3.5 SP22 Patch 4" --noUI --runscript="C:\path\to\codesys\import_canworks.py"
```

## Network numbers and the device's CAN interfaces

## Which device gets the bus

The bus goes to one device of the project, chosen in this order:

1. The device named with `--codesys-plc NAME` (`"plc"` in `canworks-codesys.json`).
2. The device that holds the project's active application, at any depth in the device tree.
3. The only device of the project.

The report's `device` line names the device and the reason. A project with several devices and no active application stops with the list of devices and changes nothing. When the named device is not the active one, the report warns that the build checked the active application on the other device. If you switch the active device and run the script again, the bus goes to the new device; the old one keeps its manager and nodes, and the report warns when it has a manager on the same network number, since two controllers would then drive the same bus.

## Network numbers and the device's CAN interfaces

CODESYS picks a CAN interface by the CANbus object's **Network** number. The export takes it from the interface's number (`can1` gives 1); `--codesys-net NAME=N` sets it for network NAME. Devices count their CAN interfaces in their own way, some from 0 and some from 1, so look at your device's CANbus objects or its manual first. When the device already has a CANbus with that number (many device descriptions bring theirs), the script uses it and its CANopen Manager; otherwise it adds both, in the newest version installed in that CODESYS, or in the version of a CANbus the device already has.

Many controllers and displays bring their CAN ports as objects of their own, for example **Communication > CAN**, and refuse a CANbus directly under the device. When the device has no CANbus with the network's number, the script adds the new one under the device's CAN interface object: the one `--codesys-can NETWORK=OBJECT` names (`"interface"` on the network in the plan), else the device's only object whose name is CAN or has CAN as a word (`CAN`, `CAN1`, `Port CAN 2`), else the one of those whose name ends in the network number, else the device itself. If the interface does not take a CANbus, the CANopen Manager goes directly under it. With several CAN interfaces and none matching the number, or when nothing takes the bus, that network stops with an error that lists the device's objects.

## What carries over

| canworks | CODESYS |
|---|---|
| bit rate, interface number | CANbus bit rate and network number |
| master `node_id`, `heartbeat_ms`, `sync_period_us`, `sync_window_us`, `start`, `start_nodes`, `start_all_nodes`, `nmt_inhibit_time_us`, `sdo_timeout_ms`, `time_cob_id`/`time_period_ms` | CANopen Manager settings |
| node ID, `mandatory` (CODESYS: optional device when not mandatory), `boot: false` (do not initialize), `restore_configuration` where the device offers it | device General settings |
| PDO communication and mapping, `heartbeat_ms`, node guarding, `heartbeat_consumer`, `heartbeat_watch`, `time_cob_id`, `error_behavior`, PDO links, startup SDOs | from the DCF: the device's PDOs and SDO list |
| the editor's declaration names of mapped entries (`dio_Read_input_8_bit_1`) | variable names on the I/O channels; CODESYS assigns the `%I`/`%Q` addresses itself |

Every other setting is listed in the report under `not set` with the reason, for example the plugin's status and diagnostic locations (use the CANopen Manager's diagnostics or the CiA 405 blocks in CODESYS), SDO variables, the CiA 402 axis bridge (SoftMotion), LSS settings, the configuration check, and the TPDO receive timeouts. SYNC from the PLC cycle (`"sync_source": "plc_cycle"`) is a bus cycle task setting in CODESYS. Identity checks at boot (vendor ID, product code, revision) are ticked on each device in CODESYS; the script cannot set them. Slave, J1939 and plain CAN networks, raw messages, the Modbus bridge and the gateway stay with canworks. A canworks slave works under a CODESYS master through its EDS ([slave.md](slave.md)).

## Running it again

Running the script again on the same project replaces the devices it manages, the ones under that CANopen Manager with a node ID from the config, and keeps devices with other node IDs (the report lists them). Changes made by hand on a replaced device are gone, so change the canworks config and import again rather than editing the device in CODESYS.

A DCF installs in the device repository under the product's vendor ID, product code and revision, so after an import the repository holds the last node's DCF of each product. The project's devices keep their own settings; only CODESYS's **Update Device** would bring the repository's version back.

## canworks next to a CODESYS master

- **Bus trace and commissioning:** the PC tools join a CODESYS-run bus through a USB adapter, read-only until changes are allowed ([pc-adapter.md](pc-adapter.md)). SDO, NMT and LSS from canworks talk to the same nodes as CODESYS's manager, so keep them to commissioning.
- **Simulated devices:** `canworks-sim` runs simulated nodes on a SocketCAN interface for any master, so a CODESYS controller on Linux can run against them ([simulator.md](simulator.md#canworks-sim)).

## Requirements and limits

- CODESYS V3.5 with CANopen support on Windows for the import; tested with V3.5 SP22. Older service packs are expected to work but are not tested. Settings an older or vendor build lacks are reported and skipped; the nodes and their PDOs still come from the DCFs.
- The script runs CODESYS's IronPython 2.7, uses only CODESYS's scripting API and needs no add-ons.
- The CODESYS runtime's CANopen licence is not part of this: the CODESYS Store lists which runtimes include the CANopen Manager.
