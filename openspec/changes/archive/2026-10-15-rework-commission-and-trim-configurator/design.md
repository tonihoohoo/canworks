## Context

"Commission a CANopen device" is the configurator in a mode with no config (`S.state.commission`). It talks to the bus through the local backend (`canworks.localbus`) over python-can. The same backend served the configurator's "USB adapter on this PC" Online target. Bit rate detection exists three times:
- the plugin's runtime sweep (`detect_bitrate`), used by the Scan page;
- the local listen-only sweep (`localbus/sweep.py`);
- the local lone-device sweep, which joins the bus in normal mode at each rate and sends LSS or SDO probes.

On macOS a gs_usb adapter is reached through libusb (python-can `gs_usb` interface plus the `gs_usb` package). Earlier fixes (tools 0.40.x) skip the kernel driver detach, open by USB bus and address, and retune on the same handle, because a USB reset per open can leave the adapter deaf.

Toni's direction for this change: no automatic bit rate detection, and a connection that does not work at a wrong bit rate. The configurator edits configs and talks to runtimes. USB adapter work belongs to commissioning.

## Goals / Non-Goals

**Goals:**
- A wrong bit rate is refused at Connect, and bus errors later end the connection, on gs_usb, slcan and SocketCAN.
- gs_usb on macOS no longer wedges from the toolkit's own actions, and says what to do when it is wedged anyway.
- Commissioning has a clear layout: a connection tab, a nodes tab, Trace, Frame lab.
- Smaller configurator: runtime-only Online, no scan, no firmware download, no CiA 402 switch for non-drives.

**Non-Goals:**
- Making a wedged adapter recover without a replug in every case. That is adapter firmware behaviour; the toolkit only stops causing it and says so.
- A bit rate check in the plugin on the runtime. The plugin's bus comes from the config, and its error counters already show in Online.
- Changing the runtime Online view, LSS or Parameters in config mode beyond removing the adapter target.

## Decisions

### 1. Remove all bit rate detection (clean cut)
Toni: "No need for bit rate automatic detection. Connection should not work if bitrate is incorrect." Once the commissioning detects and the Scan page go away, the plugin's `detect_bitrate` has no page left, only `canworks-diag detect-bitrate`. Keeping an unused, hard-to-test sweep (listen-only link reconfiguration, slcan serial takeover) costs code and CI time. All of it is removed: plugin ops, the local sweep, the lone-device sweep, the CLI command, `bitrate.decide` where nothing else uses it, and the parity fixture.
*Alternative:* keep the plugin sweep for the CLI. It was rejected as unused, and it is easy to restore from history if wanted.

### 2. Bit rate check on connect
Connect runs a check before the session counts as connected:

1. **Listen** for 1 s, the guest window that already exists (`LISTEN_S`), in listen-only mode where the adapter has one: gs_usb via `GS_CAN_MODE_LISTEN_ONLY` when the device reports it, slcan via `m1`, SocketCAN via the listen-only control mode when the tools may set the link. Otherwise the adapter receives in normal mode.
   - Confirmed: at least one valid frame and no error frame.
   - Wrong: any error frame, error warning or passive state, or a rise in the receive error counter with no valid frame. The message is "the bus does not run at N kbit/s (errors, no valid frames)".
2. **Silent bus** (no frame, no error): the adapter is set to normal mode and sends one probe in one-shot mode (gs_usb `GS_CAN_MODE_ONE_SHOT`, SocketCAN `CAN_CTRLMODE_ONE_SHOT` where it may be set; otherwise the tools wait for one confirmation and then reset the channel). The probe is LSS "inquire node ID" (0x7E5, cs 0x5E). Only a device in LSS configuration mode answers it, and none should be, so it changes nothing.
   - Confirmed: the adapter reports the frame sent (gs_usb echo; SocketCAN TX confirmation with no error frame within 100 ms).
   - Wrong: an ACK error alone means "no device acknowledged at N kbit/s: wrong bit rate, or the device is not powered or connected". Bit, stuff or form errors mean "the bus does not run at N kbit/s".
3. **Adapters that cannot report a sent frame** (slcan, untested python-can types): on a silent bus the check asks for a node ID (configurator: a field in the connect form, "Device's node ID, to check the bit rate"; CLI: `--check-node N`) and reads 0x1000 sub 0 by SDO. Any answer, including an abort, confirms the rate. No answer refuses the connection with the same reason as an ACK error. Without a node ID the connection is refused with a message that names this option.

The check result goes into `hello` and `status` (`bitrate_check: {result, how}`). The CLI runs the same check on every `--adapter` command. A refused check exits 1 and sends nothing more.

This replaces the "Connect sends nothing" guest rule with "Connect sends at most one probe, and only on a silent bus". The probe is the smallest change that makes a silent single device checkable without guessing a rate.

*Alternative:* trust the user's rate and only warn. Rejected by Toni's ask.

### 3. Bus errors end the connection
The receive thread watches error frames and the adapter's bus state. On bus-off, error passive, or 10 error frames within 1 s with no valid frame, the core stores the reason and closes the adapter. Every handle then gets "connection ended: <reason>" and the page shows it in Bus and master. The thresholds are module constants, tested on the virtual bus with injected error frames.

### 4. gs_usb details
- **Echo frames.** `Core._handle` skips messages whose `is_rx` is False: they are not foreign traffic and not heartbeats. The transmit path uses them as send confirmation. `transmit` waits up to 0.5 s for the echo of the frame it sent (when the device has echo, which candleLight does), and no echo means "adapter stopped sending". The echo replaces the separate Tx record in the trace, so each sent frame is listed once with the Tx flag.
- **Timings.** A helper computes timings from the device's `bt_const` limits (tseg1, tseg2, sjw, brp ranges) for sample points 87.5, 85, 80 and 75 %, in that order. When none fits, the open is refused before any request goes to the adapter: "adapter gs_usb:0 cannot run at 50 kbit/s".
- **Never half-configured.** Timing is computed first. Then the tools stop, set, and start, and a failure in set or start puts the channel in reset mode before the error is raised. With the sweep gone, only connect and the check's mode switches (listen-only to normal) change modes.
- **Stalls.** A `usb.core.USBError` with errno 32 (EPIPE) on open triggers one USB reset and one retry. If that fails too, the open is refused with "adapter gs_usb:0 does not answer (USB stall): unplug it and plug it in again".
- **Close.** Close always resets the channel (`GS_CAN_MODE_RESET`) before releasing the interface, so the next open starts clean.

### 5. Scan stop
`scan_stop` sets the running scan's stop flag. Workers finish their current probe and stop, and the job ends with `stopped: true` and the entries found so far. A transmit error, or the connection ending, stops the scan the same way with `error`. The Cancel button sends `scan_stop`. The plugin's runtime scan is unchanged; there is no runtime scan page any more.

### 6. Commissioning layout
The side bar in commissioning has four items:
- **Bus and master:** connect form or connection state, the check result, bus state and counters, another master, Allow changes (live toggle), Disconnect, commissioning log count and Save log.
- **Nodes:** a node table merged from heartbeats heard, scan results and nodes added with **Add node from EDS…** (node ID and an EDS file; kept in this page only). The page also has Scan the bus with progress and Cancel, and devices without a node ID (LSS find, Set node ID, Set bit rate). Clicking a node opens its page with tabs Object dictionary, Parameters, PDO test, Notes, and "Add to a config…".
- **Trace**
- **Frame lab**

The Online and Scan the bus views are not shown in commissioning. Their code is split, so config mode keeps the runtime Online view and commissioning gets the two new views.

Allow changes on an open connection sends `allow_changes` to the server, which updates the open adapter target in place (`AdapterTarget` keyed without `allow_changes`). The core is not reopened, so the listen window and other-master state are not reset.

### 7. Configurator trims
- `targetChoice()` and the adapter form leave config mode. The online settings drop `target`/`adapter`/`adapter_bitrate` for projects. Commissioning keeps its own adapter settings on this PC (`commission.json` in the config dir).
- `nav-scan`, `renderScan`, `scanAction` and the "Use for node…" and "Add as node" paths for config mode are removed. `addScannedNode` stays for "Add to a config…".
- The log (`S.commLog`) belongs to the commissioning session. `closeCommission()` asks to save when it has entries, then clears it. `logBar()` is removed.
- CiA 402 switch: enabled when the EDS has 0x6040 and 0x6041, or when `axis` is already set (so it can be switched off). Otherwise it is disabled with "This device's EDS has no controlword (0x6040) and statusword (0x6041), so it cannot be a CiA 402 axis."

### 8. Firmware download removed
`software_file` / `software_version` go from both schemas, `contract.py`, the plugin config reader and dcfgen input, the deploy bundle (`software_files`), the editor hook snapshot, `canopen_check`, the DCF and HTML exports, `commissioning.py`'s skip note, and the node page. Old configs fail on the unknown key, as the project is not in real use.

## Risks / Trade-offs

- [The probe sends one frame on a silent bus] → It is an LSS inquire that no device in normal operation answers, sent once in one-shot mode, and only when nothing was heard. The page says so next to Connect.
- [slcan cannot confirm a send] → On a silent bus the user gives a node ID. Users of commissioning usually know it, or find it by LSS once connected at the confirmed rate of a busier bus.
- [Strict error thresholds end connections on a noisy bench] → Thresholds are constants, and the message names what was seen, so they can be tuned on the bench.
- [Removing the plugin sweep] → A runtime can no longer tell its own bus rate. Online shows error counters and bus state, and the CLI can still connect from a PC with the check.
- [Hardware behaviour of gs_usb on macOS is not fully known] → Bench tasks run the check, wrong rates, Disconnect and replug cases on the Mac with the candleLight adapter.

## Migration Plan

None for users (not in real use). Bench: redeploy the plugin on the Pi after merge, and update the PC tools on the Mac and the Windows PC.

## Open Questions

None blocking. If Toni wants to keep the runtime sweep for the CLI, Decision 1 shrinks to the PC side only.
