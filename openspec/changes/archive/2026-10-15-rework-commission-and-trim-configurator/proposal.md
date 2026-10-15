## Why

A bench session on 2026-10-11 used "Commission a CANopen device" with a gs_usb (candleLight) adapter on macOS and the configurator on a real bus at 500 kbit/s. It found these problems:

- Bit rate detection with "Only this device is on the bus" never found 500 kbit/s. It failed with "cannot set adapter gs_usb:0 to 50 kbit/s: No suitable bit timings found", then "... to 800 kbit/s: [Errno 32] Pipe error", and the next try with "cannot open adapter gs_usb:0: [Errno 32] Pipe error" until the adapter was plugged in again.
- Connect accepted 1000 kbit/s and other wrong rates on a 500 kbit/s bus and showed the connection as working.
- There is no Disconnect button.
- Changing the connection settings (Allow changes) brought "Another master is active on this bus (SDO request to node 23 ...)" when no other master was on the bus.
- A scan with the adapter in that bad state took 138 s and could not be cancelled.
- The Scan page has a second bit rate detection that works differently from the one in the connect form.
- Trace recording did not work at all: it asked for "the runtime host and token in Online", which commissioning has none of.
- The page layout mixes connecting, the node list, the Steps panel and node work on one Online page.

In the configurator (config editing), Toni wants less: no USB adapter target in Online, no Scan the bus page, no commissioning log carried over from commissioning, no CiA 402 axis switch on a device that cannot be one, and no program (firmware) download.

What the code shows (tools 0.56.1):
- **False "another master".** python-can's gs_usb driver returns the adapter's echo of every frame the PC sends as a received message (`is_rx` False). `localbus/core.py` `_handle` does not skip echoes, so the PC's own SDO request to node 23 counts as a foreign SDO request. The trace also lists each sent frame twice on gs_usb.
- **Wrong bit rate accepted.** `adapter.open` and `core.acquire` only open the adapter. Nothing checks that the bus runs at the chosen rate, and with "listen 1 s, send nothing" a wrong rate goes unnoticed until the first request times out.
- **Pipe errors and the wedged adapter.** The sweep retunes gs_usb on the same USB handle (`_gs_usb_retune`): it stops the channel, then computes timings with `can.BitTiming.from_sample_point(..., 87.5)`. When that finds no timing (50 kbit/s on this adapter's clock), the channel is left stopped with no timing set, and the next control request is stalled (EPIPE). In the lone-device sweep the adapter is also in normal mode at wrong rates and retransmits its probe frames without end. The 2026-10-09 bench run already found that unacknowledged transmits leave a gs_usb adapter on macOS deaf until replugged.
- **Slow scan.** python-can's gs_usb `send` ignores its timeout, so with a wedged adapter every SDO request of the scan blocks. The scan keeps going through all 127 node IDs and has no stop operation.
- **Trace.** `trace.js` `onlineReady()` only checks for a runtime host and token. The server already records from a USB adapter (`tracing.connector` takes an adapter target), so the page refuses for no reason.

## What Changes

**Commission a CANopen device**

- **BREAKING: no bit rate detection anywhere.** The user picks the bit rate and the connection checks it. Removed: Detect and "Only this device is on the bus" in the connect form, Detect bit rate on the Scan page, the local backend's `detect_bitrate` / `detect_bitrate_status` (normal and lone-device sweep), the plugin's `detect_bitrate`, `detect_bitrate_status` and `detect_bitrate_stop`, and `canworks-diag detect-bitrate`. **Default chosen:** the plugin's runtime sweep goes too, because no page uses it any more and the project is not in real use (clean cut).
- **Connect checks the bit rate and refuses a wrong one.** The adapter first listens at the chosen rate, listen-only where it has that mode. Valid frames with no error frames confirm the rate. Error frames or bus errors refuse the connection ("the bus does not run at 1000 kbit/s ...") and close the adapter. A silent bus is checked with one harmless frame sent once, with no retransmit: an LSS "inquire node ID", which only devices in LSS configuration mode answer. The frame must be acknowledged with no error. Where the adapter cannot report that a frame was acknowledged (slcan), the page asks for the device's node ID and reads 0x1000 from it instead. A rate the adapter cannot be set to is refused up front with that reason.
- **Bus errors end the connection.** After connect, error passive, bus-off or a run of error frames on the adapter ends the connection with the reason, instead of leaving a connection that only times out.
- **gs_usb fixes.** Echo frames are never taken as received frames, but they confirm sends. Bit timings come from the adapter's own timing limits, trying several sample points before giving up. A failed open or set leaves the channel reset, never half-configured. A USB stall ("Pipe error") resets the USB device once and retries once, then says to unplug and plug the adapter in again. A send blocked longer than 0.5 s ends the connection as "adapter stopped sending".
- **Disconnect.** The connection tab has Disconnect, which closes the adapter, so another tool can use it and the user can reconnect at another rate. Allow changes can be switched on an open connection without reconnecting.
- **Scan can be cancelled and stops on a broken adapter.** A new `scan_stop` operation and a Cancel button. The scan also ends at once with the adapter's error when a send fails or the connection ends.
- **Trace records through the adapter connection.** Recording and sending in the Trace view work in commissioning once connected, with no runtime host or token.
- **New layout.** The side bar has:
  - **Bus and master:** adapter, bit rate, Allow changes, Connect/Disconnect, the bit rate check result, bus state and error counters, another master, and Save log.
  - **Nodes:** the devices heard, scanned or added, with their state. It has Scan the bus (with Cancel), **Add node from EDS…** (a device by node ID with its EDS, for this session only), devices without a node ID (LSS find, Set node ID, Set bit rate), and each node's page (object dictionary, Parameters, PDO test, notes, "Add to a config…").
  - **Trace** and **Frame lab** as today.

  The Online and Scan the bus pages go away in this mode.
- **BREAKING: the Steps panel is removed.** "Add to a config…" moves to the node's page, and the commissioning log stays.

**Configurator (editing a config)**

- **BREAKING: Online connects to a runtime only.** The "USB adapter on this PC" target is removed, and with it the adapter connect form, the PDO test tab and the commissioning log bar in config mode. USB adapter work is done in Commission a CANopen device.
- **BREAKING: no Scan the bus page.** "Add as node" and "Use for node…" from a scan go with it. Nodes are added from an EDS. LSS find and Set node ID in the runtime's Online view stay.
- **The commissioning log stays in commissioning.** It is kept per commissioning session. Leaving commissioning (Close, "Add to a config…") with unsaved log entries asks whether to save the log first. The log is then cleared and is never shown in config mode.
- **CiA 402 axis only for a CiA 402 EDS.** "Use as a CiA 402 axis" is disabled with the reason unless the node's EDS has the controlword 0x6040 and the statusword 0x6041. It stays enabled to switch off on a config that already has `axis` on such a node, and the check shows the error.
- **BREAKING: no program (firmware) download.** `software_file` and `software_version` are removed from the config schema (v1 and v2), the plugin, dcfgen input, the deploy tool's bundle, the editor hook's snapshot, the DCF and HTML exports and the configurator's node page. A config that still has them is rejected as having an unknown field.

## Capabilities

### New Capabilities
None.

### Modified Capabilities
- `canopen-local-bus`: bit rate check on connect, bus errors end the connection, gs_usb echo and timing handling, `scan_stop`, sweep removed.
- `canopen-online-diagnostics`: plugin bit rate detection and `detect-bitrate` removed.
- `canopen-configurator`: commissioning layout (Bus and master, Nodes), Disconnect, no Steps panel, Trace on an adapter, config mode without USB adapter target or scan, log kept in commissioning, CiA 402 switch gated by the EDS.
- `canopen-master-bringup`: firmware download removed.
- `canopen-dcf-export`: no `software_file` comment.

## Impact

- PC tools:
  - `tools/deploy/canworks/localbus/` (`adapter.py`, `core.py`, `client.py`, `sweep.py` removed)
  - `bitrate.py` (sweep verdicts, removed unless still needed by tests of other code)
  - `diag.py` (`detect-bitrate`, connect check options)
  - `configurator/online.py`, `server.py`, `scan.py`, `tracing.py`
  - `configurator/static/app.js`, `commission.js`, `trace.js`, `index.html`, `style.css`
  - `contract.py`, `project.py`, `bundle.py`, `dcfexport.py`, `docexport.py`, `commissioning.py`, `cli.py`
  - `_lely_dcf/dcfgen_cli.py`
  - the schemas
  - `tools/editor-hook/canworks_hook/snapshot.py`
  - `tools/canopen_check.cpp`
- Plugin:
  - `plugin/src/can/config.{h,cpp}` (`software_*` removed)
  - `plugin/src/canopen/dcf_gen.cpp`
  - the bit rate sweep in the diagnostics channel and its slcan/SocketCAN listen-only helpers, where nothing else uses them
- Tests:
  - local bus tests (echo, bit rate check, bus errors, scan stop)
  - removed sweep tests and the `test/fixtures/sweep_verdicts.json` parity file
  - `test/fixtures/config/cases.json` (`software_file` cases become unknown-field rejections)
  - unit and sim tests that use `software_file`
  - configurator browser tests (layout, Disconnect, Trace on an adapter, no scan or adapter target in config mode, CiA 402 switch)
- Docs:
  - `docs/pc-adapter.md`, `docs/configurator.md` (new layout, no detection, connect check)
  - `docs/diagnostics.md` (ops removed)
  - `docs/config.md`, `docs/deploy.md`, `docs/tour.md` (no `software_file`)
  - `README.md`
- Version: PC tools and plugin minor bump. The Pi needs the new plugin redeployed (bench task).
