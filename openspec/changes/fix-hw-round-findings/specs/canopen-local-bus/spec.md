## MODIFIED Requirements

### Requirement: Bit rate check on connect
Opening a local adapter session SHALL check that the bus runs at the given bit rate before any operation runs. The check SHALL listen for one second, in listen-only mode when the adapter has one.
- At least one valid frame and no error frame SHALL confirm the rate.
- Any error frame from the wire (bit, stuff, form, CRC or acknowledge error, transceiver error, bus error), error passive or bus-off state, or a receive error count above zero with no valid frame, SHALL refuse the session with "the bus does not run at N kbit/s" and what was seen. An error frame that only reports the controller's state going down (error warning, back to error active) SHALL NOT count: an adapter's error counters can still be up from an earlier connection at another rate.
- When nothing was heard, the backend SHALL send one LSS "inquire node ID" frame (0x7E5, command 0x5E) once, without automatic retransmission where the adapter can turn that off. The rate SHALL be confirmed when the adapter reports the frame sent with no error frame within 100 ms. An acknowledge error alone SHALL refuse the session with "no device acknowledged at N kbit/s: the bit rate is wrong, or no device is powered and connected". Bit, stuff or form errors SHALL refuse it with "the bus does not run at N kbit/s".
- On an adapter that cannot report a sent frame (slcan and untested types), a silent bus SHALL need a node ID (`check_node`, CLI `--check-node N`). An SDO read of 0x1000 sub 0 from that node SHALL confirm the rate when it gets any answer, including an abort. Without a node ID, or with no answer, the session SHALL be refused, naming `--check-node`.
- A bit rate the adapter cannot be set to SHALL be refused before anything is sent to the adapter, naming the rate.

A refused check SHALL close the adapter. `hello` and `status` SHALL report `bitrate_check` with `result` (`confirmed`) and `how` (`traffic`, `probe acknowledged` or `node N answered`).

#### Scenario: Wrong rate refused
- **WHEN** devices send heartbeats at 500 kbit/s and the user connects at 1000 kbit/s
- **THEN** the session is refused with "the bus does not run at 1000 kbit/s", the adapter is closed, and no operation runs

#### Scenario: Busy bus confirmed
- **WHEN** a device sends heartbeats at 500 kbit/s and the user connects at 500 kbit/s
- **THEN** the session opens with `bitrate_check` `confirmed` by `traffic`, and the PC sent nothing

#### Scenario: Right rate right after a wrong one
- **WHEN** a gs_usb adapter was refused at 250 kbit/s on a 500 kbit/s bus and the user connects again at once at 500 kbit/s
- **THEN** the session opens, confirmed, though the adapter reports its error counters going down during the check

#### Scenario: Silent single device
- **WHEN** one device in PRE-OPERATIONAL without heartbeat is on the bus at 250 kbit/s and the user connects a gs_usb adapter at 250 kbit/s
- **THEN** the backend sends one LSS inquire node ID frame, the adapter reports it acknowledged, and the session opens `confirmed` by `probe acknowledged`

#### Scenario: Silent single device at a wrong rate
- **WHEN** the same device runs at 250 kbit/s and the user connects at 500 kbit/s
- **THEN** the probe is not acknowledged, it is not retransmitted, and the session is refused saying the bit rate is wrong or no device is connected

#### Scenario: slcan on a silent bus
- **WHEN** an slcan adapter connects to a silent bus without `--check-node`
- **THEN** the command exits 1 saying the bit rate could not be checked and to give `--check-node N`, and with `--check-node 5` it opens when node 5 answers

### Requirement: gs_usb adapters
On gs_usb adapters, the backend SHALL handle the following:
- **Echo frames:** it SHALL never treat the adapter's echo of a sent frame as a received frame. Echoes SHALL NOT count as another master, heartbeat or answer. They SHALL confirm the send, and the trace SHALL list each sent frame once with its Tx flag.
- **Stopped sending:** a send whose echo does not arrive within 0.5 s SHALL end the session with "adapter stopped sending".
- **Bit timings:** they SHALL come from the device's own timing limits, trying the sample points 87.5, 85, 80 and 75 %.
- **An earlier connection's frames:** before its channel starts, the backend SHALL read and drop the frames and error frames the adapter still holds, so none of them reaches the bit rate check, the frame counts, the trace or the echo wait.
- **Failed set or start:** a failure to set or start the channel SHALL leave it in reset mode.
- **USB stall on open:** the backend SHALL reset the USB device and retry once. If the retry fails, it SHALL refuse with "adapter gs_usb:N does not answer (USB stall): unplug it and plug it in again".
- **Close:** closing SHALL reset the channel before releasing the USB interface.

#### Scenario: Own SDO request is not another master
- **WHEN** the configurator reads 0x1018 from node 23 through a gs_usb adapter and no other master is on the bus
- **THEN** `status` reports no other master, and the trace lists the request once, as sent

#### Scenario: Rate without timing
- **WHEN** the adapter's clock and limits give no timing for the chosen rate
- **THEN** the connection is refused naming the adapter and the rate, and the adapter can be opened at another rate at once without a replug

#### Scenario: Busy bus, one connection after another
- **WHEN** a PLC master runs SYNC and PDOs on the bus and `canworks-diag --adapter gs_usb:0` reads an object ten times in a row, each a new connection
- **THEN** every read answers, and no connection ends with "adapter stopped sending"
