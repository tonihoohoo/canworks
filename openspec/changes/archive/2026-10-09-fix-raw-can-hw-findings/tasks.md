## 1. Fixes

- [x] 1.1 Echo expiry: no wrap when the given time predates the write (unit test)
- [x] 1.2 `CAN_SEND_CYCLIC` and `CAN_RECEIVE` retry a refused start while `ENABLE` stays TRUE (block tests, regenerated library)
- [x] 1.3 No CANopen master on a plain CAN network (plugin lifecycle test)
- [x] 1.4 Echo support from sysfs flags
- [x] 1.5 Host frames reach program receivers on plain CAN networks (unit test)
- [x] 1.6 docs/raw-can.md

## 2. Hardware

- [x] 2.1 Repeat add-raw-can task 9.2 on the bench: `CAN_SEND` ends with `DONE`, blocks enabled from the first scan start, the diagnostics status shows `confirm: echo` on the USB adapter, `cansend` frames reach `CAN_RECEIVE` on a plain network
