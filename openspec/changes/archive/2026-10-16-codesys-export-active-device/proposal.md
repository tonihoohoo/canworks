## Why

The CODESYS export (`codesys-export`) puts the canworks bus on "the project's PLC": the only top-level device, or the one named with `--codesys-plc NAME` (`"plc"` in the plan). Real CODESYS projects often hold several devices, for example a controller and a display, or the same machine for two hardware variants. Today such a project stops the script with "the project has several devices" unless the user names one, and the configurator's Export > CODESYS download has no way to name one at all, so it never works on those projects.

CODESYS already has a way to say which device the user is working on: the **active application** (Set Active Application in the device tree), which is also what Build, Login and Download use. The script already builds `proj.active_application`, so today a named device and the built application can even be two different devices.

A second problem showed up on a real display project: its device brings its own CAN interface object under **Communication > CAN**, not a CANbus. The script found no CANbus, tried to add one directly under the device and CODESYS refused ("The device cannot be added or inserted here"), so nothing was imported. Device packages from PLC and display vendors often put their CAN ports under such a connector object.

## What Changes

- **The bus goes to the active device.** When the plan names no device, the script uses the device that holds the project's active application, whether the project has one device or several, in the IDE and from the command line.
- **Order of choice:** the device the plan names (`--codesys-plc NAME`), else the active application's device, else the only top-level device, else stop with the list of devices and a message to set an active application or name one. A project with one device and no application still works as today.
- **Report** says which device got the bus and why (named, active application, only device). When a named device is not the active application's device, the report warns that the build checked the other device's application.
- **Re-runs** follow the active device: switching the active application and running again puts the bus on the new device and leaves the old device's objects as they are; the report says so when the old device holds a canworks-managed manager for the same network number.
- **The device's own CAN interface.** When the chosen device has no CANbus with the network's number, the script looks for the device's CAN interface objects (any object in the device's tree, for example under Communication, that accepts a CANbus or a CANopen Manager) and adds the bus there instead of directly under the device. With one interface it is used; with several, the one whose name ends in the network number, else the run stops for that network and lists them. `--codesys-can NETWORK=OBJECT` names it explicitly. If the interface takes a CANopen Manager directly, the manager goes under it and the interface's own bit rate and number settings are used where CODESYS has them.
- **Clear failure.** If no place in the device accepts a CANbus or manager, the report names the objects it tried instead of a bare CODESYS exception.
- **Configurator** export needs no device field: the downloaded script uses the active device. The README.txt and the export banner say so.
- `docs/codesys.md`, `deploy.md`, the CLI help and README updated.

## Capabilities

### Modified Capabilities
- `codesys-export`: "Uses the project's PLC" becomes the active-device rule; the report names the chosen device and the reason. "Reuses the device's CAN interfaces" also finds the device's own CAN interface objects and adds the bus under them.
- `canopen-deploy`: `--codesys-plc NAME` overrides the active device instead of being required for projects with several devices; new `--codesys-can NETWORK=OBJECT`.
