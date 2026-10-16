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

### 4. Re-runs after switching devices
The managed devices are found per CANopen Manager under the chosen device, so a re-run on another device does not touch the first device. To avoid two controllers silently driving the same bus, the script looks for a CANopen Manager on the same network number under other top-level devices and adds a warning naming them. It does not remove anything.

### 5. Plan format
No plan change: `plc` stays optional and `format` stays the same, so an exported folder from the previous version keeps working with the new script and vice versa (the old script just keeps its old rule).

## Risks / Trade-offs

- The CODESYS scripting docs describe `active_application` and `parent`, but the parent walk across device types was not tried with several devices in the spike. Task 3.1 checks it in CODESYS on the Windows PC before the PR is ready; the stand-in API gets `parent` links.
- A user who forgot to switch the active application gets the bus on the wrong device. The report's device line and the docs make the choice visible; Undo in the IDE (not saved) reverts it.

## Testing

Stand-in API (`tests/fake_codesys.py`): `parent` links and an active application per project. Tests: two devices with the second active; named device differs from active (warning); several devices and no active application (stop, nothing changed); nested active device; re-run after switching the active device (warning, first device untouched); one device without an application (as today).
