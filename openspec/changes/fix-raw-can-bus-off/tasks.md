## 1. Fixes

- [x] 1.1 `CAN_SEND_CYCLIC` and `CAN_RECEIVE` report `ERROR_ID` 7 while the bus is off and stay active (block test, regenerated library)
- [x] 1.2 Bus state log on plain CAN networks (raw I/O test)
- [x] 1.3 Bus-off wording in the CANopen log line, docs/config.md and docs/raw-can.md

## 2. Hardware

- [ ] 2.1 Repeat the bus-off test on the bench (plain network at the wrong bit rate): cyclic and receive blocks show `ERROR_ID` 7 while bus-off and recover by themselves; the runtime log has the bus-off lines and summaries
