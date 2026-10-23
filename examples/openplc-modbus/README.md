# OpenPLC

The [Modbus bridge example](../modbus-bridge/canworks.json) with an OpenPLC connection: `bridge.connections` names OpenPLC, and with the PLC link canworks-bridge serves the two simulated CANopen nodes (an 8-channel temperature module and a 16-bit digital I/O module) to OpenPLC's own Modbus master on 127.0.0.1:1502, polled every 10 ms ([docs/modbus-bridge.md](../../docs/modbus-bridge.md#openplc)). It has the control block, the SDO registers, a live list and the function block mailboxes, so the program can use every block of the library ([docs/plc-library.md](../../docs/plc-library.md)); [main.st](main.st) reads the temperature module's device name with `CO_SDO_READ_STRING`, receives its TPDO frames with `CAN_RECEIVE`, every EMCY with `CO_RECV_EMCY`, the bus state with `CAN_BUS_INFO`, and sends a frame every 100 ms with `CAN_SEND_CYCLIC`. The nodes are simulated inside the bridge, so no CAN interface is needed.

To try it:

1. In the configurator, **New config…** with **Modbus bridge**, then on the **Modbus bridge** page **Add connection…** → **OpenPLC** → **New editor project…**; copy this folder's files into the new project's `canworks/` folder and open the project again. Or open an editor project and put them there.
2. **Save**: the configurator writes `devices/remote/canworks.json`, the `canworks_in` and `canworks_out` programs and the `canworks` variable list. Use the values in `main` by name, such as `canworks.dio_Write_output_8_bit_1`, and the blocks with `LINK := canworks.link` (paste [main.st](main.st) for a start).
3. Install the OpenPLC Runtime on a Linux device with [upstream's installer](https://github.com/Autonomy-Logic/openplc-runtime), then on the **Devices** page **Install and start this project's bridge** there, then the editor's **Build and upload**.

`canworks.ok` is TRUE once the bridge answers with the map the program was built for.
