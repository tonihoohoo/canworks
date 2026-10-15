## Why

The hardware test round of 2026-10-15 (a Windows PC with a gs_usb adapter, the Pi runtime, the local simulator runtime) found these bugs:
- On Windows the PC tools do not install pyusb, the gs_usb driver or a libusb DLL, so `canworks-diag adapters` finds no gs_usb adapter and `gs_usb:0` cannot open.
- A gs_usb adapter hands the next connection what it still held from the last one: a refused bit rate's error frames refuse the right rate once, a fresh connection counts thousands of old frames, and with the PLC running about one connection in three ended with "adapter stopped sending" while the backlog delayed the echo.
- After a connection at a wrong rate the adapter's error counters are still up, and the reports of them going down (error warning, then error active) count as bus errors in the bit rate check.
- With a slave network in the config, the Commission workspace says the runtime runs a different configuration right after an upload of the same config: the fingerprint the configurator computes does not rewrite the slave's EDS path the way the deploy tool and the editor hook do.
- The connect panel shows "null" (runtime) or "nullnull" (adapter) where the recent connections and the target choice go when there are none.
- With two configurators open on Windows, saving `online.json` fails with "cannot use the folder …: access is denied" and leaves a `.tmp` file behind: Windows refuses the rename while the other process reads the file.
- The trace labels a PDO layout it learned from SDO reads "set on the bus", though nothing set it.
- The Commission log records a node reset but not the boot after it when both fall between two status answers.

## What Changes

- The tools package depends on python-can's gs_usb extra on Windows too, and on the `libusb` package there; the tools put its DLL on their own PATH before looking for gs_usb adapters.
- Opening a gs_usb adapter reads and drops what it holds before its channel starts.
- Error frames that only report the controller's state (error warning, back to error active) no longer count as bus errors; error frames from the wire, error passive and bus-off still do.
- The configurator's config fingerprint rewrites node and slave EDS paths like the deploy tool.
- The connect panel leaves out the parts it has nothing for.
- Settings files on the PC are renamed into place again for about a second while Windows refuses, and the temporary file is removed when it still fails.
- SDO read answers seen in a trace give a layout "read from the device"; only confirmed SDO writes give "set on the bus".
- The plugin's status gives each node's boot count (`boots`); the Commission log adds "Booted" when it goes up.

## Impact

- Specs: `canopen-pc-install`, `canopen-local-bus`, `canopen-bus-trace`, `canopen-configurator`, `canopen-online-diagnostics`.
- Code: `tools/deploy/pyproject.toml`, `canworks/localbus/adapter.py` and `core.py`, `canworks/configurator/online.py`, `server.py`, `static/connection.js`, `static/nodes.js`, `canworks/userdirs.py`, `canworks/bustrace/layouts.py` and `decode.py`, `plugin/src/canopen/network.h`, `network.cpp`, `network_diag.cpp`.
- Docs: `docs/pc-adapter.md`, `docs/install-pc.md`, `docs/diagnostics.md`, `docs/trace.md`, README.
