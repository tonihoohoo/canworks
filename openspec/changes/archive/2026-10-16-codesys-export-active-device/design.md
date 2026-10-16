## Context

`import_canworks.py` `choose_plc(proj, plan)` returns the plan's `plc` device, else the only top-level device, else stops. `build_project` builds `proj.active_application`, independent of that choice. The configurator's Export > CODESYS writes a plan without `plc`, so a multi-device project always stops there.

## Goals / Non-Goals

- Goal: with no name given, the bus lands on the device the user is working on in CODESYS, the same one CODESYS builds and downloads.
- Goal: keep `--codesys-plc NAME` as an explicit override.
- Non-goal: putting different canworks networks on different devices in one run. One run targets one device; a user with two devices runs the export twice with different configs or `--network` and switches the active application between runs.
- Non-goal: setting the active application from the script.

## Decisions

### 1. Finding the active device
`proj.active_application` is an application object; its owner device is found by walking `.parent` from the application until the first object for which `is_device` is true (the application sits under "Plc Logic", which is not a device; child applications sit one level deeper). The walk stops at the project. If the property is missing, raises, or yields no device, the script treats the project as having no active application. No device type or id is checked, so any PLC or display device works.

### 2. Order of choice
1. Plan `plc` (from `--codesys-plc NAME`): the device of that name anywhere in the project, as today. If it differs from the active device, the report warns that the build checked the active application on the other device.
2. Active application's device.
3. The only top-level device.
4. Stop and change nothing: "the project has several devices (A, B) and no active application: set one in CODESYS (Set Active Application) or name the device with --codesys-plc NAME".

The report's `device` line gets the reason: `PLC (active application)`, `HMI (named in the plan)`, `PLC (only device)`.

### 3. Nested devices
The active device can be below the top level (a controller inside a gateway device or a vendor composite). The CANbus search already runs anywhere under the chosen device, so nothing else changes.

### 4. Where the bus goes in the device
Today: an existing CANbus (type 15) with the network's number anywhere under the device, else a new CANbus directly under the device. Device packages that ship a CAN connector object (for example `Communication > CAN`) refuse a CANbus at the device root. New order for each network:
1. An existing CANbus anywhere under the device with the network's number (as today).
2. `--codesys-can NETWORK=OBJECT` (plan `networks[].interface`): that object.
3. Interface candidates: device objects in the device's tree that are not CANopen objects (types 15, 16, 17 and remote devices), not applications and not the device itself, whose name contains "CAN" (case-insensitive). One candidate is used; with several, the one whose name ends in the network number; otherwise the network stops and the report lists them with the option to name one.
4. No candidate: the device itself (as today).

On the chosen parent the script first adds a CANbus; if CODESYS refuses it, it adds the CANopen Manager directly (the interface object is then the bus: its bit rate parameter is set when it has one named like CODESYS's `Baudrate`, and the network number is reported as the interface's own). If both are refused, the network stops with the parent's name, its type and CODESYS's message. Adding is tried, not predicted, because the scripting API has no documented "allowed children" call; a refused `add` leaves the tree unchanged.

The first apply task probes the real display project's CAN object headless on a copy (what it accepts, its parameters, whether a CANopen Manager or a CANbus goes under it) and the design is adjusted to that before coding. No vendor or device name goes into the repo.

### 5. Re-runs after switching devices
The managed devices are found per CANopen Manager under the chosen device, so a re-run on another device does not touch the first device. To avoid two controllers silently driving the same bus, the script looks for a CANopen Manager on the same network number under other top-level devices and adds a warning naming them. It does not remove anything.

### 6. Plan format
`plc` stays optional; networks get an optional `interface` (from `--codesys-can`). `format` stays the same, so an exported folder from the previous version keeps working with the new script and vice versa (the old script just keeps its old rule).

## Risks / Trade-offs

- The CODESYS scripting docs describe `active_application` and `parent`, but the parent walk across device types was not tried with several devices in the spike. Task 3.1 checks it in CODESYS on the Windows PC before the PR is ready; the stand-in API gets `parent` links.
- The "name contains CAN" heuristic can miss an interface named otherwise; `--codesys-can` covers that and the failure report lists the device's objects.
- A user who forgot to switch the active application gets the bus on the wrong device. The report's device line and the docs make the choice visible; Undo in the IDE (not saved) reverts it.

## Testing

Stand-in API (`tests/fake_codesys.py`): `parent` links and an active application per project. Tests: two devices with the second active; named device differs from active (warning); several devices and no active application (stop, nothing changed); nested active device; re-run after switching the active device (warning, first device untouched); one device without an application (as today); a device that refuses a CANbus at its root but takes it under `Communication/CAN`; an interface that takes the manager directly; two CAN interfaces matched by number; `--codesys-can`; nothing accepts (error lists objects).
