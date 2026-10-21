## Why

On a real display project the CODESYS script added nothing. The active device's **Communication > CAN** interface had no CANbus yet, so the script added CODESYS's stock CANbus (type 15, id 181015) there. The display's CAN interface only accepts the display vendor's own CANbus (also type 15, another id), so CODESYS refused it ("The device cannot be added or inserted here") and refused a manager directly under CAN as well. The network stopped before any node was added. The 22 other devices in the same project all had the vendor's CANbus, so the script could have known which one fits.

The same report also had 22 near-identical warnings ("device X also has a CANopen Manager on network number 0"), one per other device. Projects that keep one device per hardware variant are normal, and the line that mattered (the error) was buried at the bottom.

## What Changes

- **A new CANbus that fits the interface.** When the chosen device has no CANbus with the network's number, the script tries CANbus devices (type 15) under the interface in this order and keeps the first one CODESYS accepts:
  1. CANbus devices already used in the project under a CAN interface of the same device type as this one (same identification as the chosen interface), newest version first;
  2. other CANbus devices used anywhere in the project;
  3. the CANbus devices installed in CODESYS (highest version per id), the stock CANbus first among them so a plain PLC keeps getting it.
  A refusal adds nothing, so trying the next one is safe. Only when every CANbus is refused does it fall back to a manager directly under the interface, as today.
- **The manager matches the bus.** A manager added under a vendor CANbus uses the manager version that bus's siblings in the project use, else the one matching the bus version, else the highest installed (as today).
- **Report** says which CANbus it added and why ("CANbus <id> <version>, as used by device X"), and when nothing fits, the error lists every CANbus it tried with CODESYS's message.
- **One warning for other devices.** "Same network on another device" becomes one warning per network that names the devices (first few, then "and N more").
- **Build dialog** in the configurator leads with the device the bus went to (from the report's `device` line), for example "CODESYS built the bus into ExampleApp (active application)."
- `docs/codesys.md` and README.md updated; PC tools version bump.

## Capabilities

### Modified Capabilities
- `codesys-export`: "Reuses the device's CAN interfaces" picks the new CANbus from those the project uses and those installed, keeping the first one CODESYS accepts; "Nowhere to add the bus" lists the CANbus devices tried; "Same network on another device" is one warning per network.
- `canopen-configurator`: "CODESYS actions" build dialog names the device the bus went to.

## Impact

- `tools/deploy/canworks/codesys/script/import_canworks.py` (bus choice, manager version, warnings), `tests/fake_codesys.py` (interfaces that accept only some CANbus ids), `tests/test_codesys.py`.
- `configurator/static/target.js` build dialog text.
- `docs/codesys.md`, README.md, PC tools version.
- No plan format change; no config change.
