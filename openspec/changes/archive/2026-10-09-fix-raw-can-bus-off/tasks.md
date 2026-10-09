## 1. Fixes

- [x] 1.1 `CAN_SEND_CYCLIC` and `CAN_RECEIVE` report `ERROR_ID` 7 while the bus is off and stay active (block test, regenerated library)
- [x] 1.2 Bus state log on plain CAN networks (raw I/O test)
- [x] 1.3 Bus-off wording in the CANopen log line, docs/config.md and docs/raw-can.md

## 2. Hardware

- [x] 2.1 Repeat the bus-off test on the bench (plain network at the wrong bit rate): cyclic and receive blocks show `ERROR_ID` 7 while bus-off and recover by themselves; the runtime log has the bus-off lines and summaries
  - 2026-10-09 on the bench (USB adapter that leaves bus-off by itself about 2000 times a second): cyclic and receive blocks stayed `ACTIVE` and showed `ERROR_ID` 7 whenever the sampled state was bus-off, `COUNT` held; at the right bit rate `ERROR` stayed FALSE and `COUNT` rose. Log wording as specified; a reading with both a state change and a hidden bus-off wrote two lines, past the 5-a-second limit (now one line, task 1.4).
- [x] 1.4 One log line per reading, so a hidden bus-off counts toward the limit (raw I/O test)
