canworks for CODESYS (canworks-deploy VERSION)

canworks.xml holds the canworks list (canworks.ok, the typed values, canworks.link and the channel arrays canworks.in_w and canworks.out_w), the programs canworks_in and canworks_out and the canworks library. The bridge listens on port 1502, unit 1; the PLC reaches it at 192.168.10.5.

The bridge takes writes only from 192.168.10.20: the PLC's address must be one of them.

CODESYS is a Modbus TCP client of canworks-bridge here; canworks-bridge still runs the CAN networks. To let CODESYS run the CANopen master itself, use canworks-deploy --export-codesys.

1. Open the PLC project in CODESYS.
2. Tools > Scripting > Execute Script File..., pick import_canworks_modbus.py in this folder.
   It imports canworks.xml, adds the Modbus TCP client devices for the bridge, puts canworks_in first and canworks_out last in the task, and writes import_report.txt here.
3. Read import_report.txt: what it lists as 'by hand' is for you to do in CODESYS.
4. Use canworks.ok and canworks.<value> in your program; the canworks blocks take LINK := canworks.link.

Export again after any config change: a program built for another map leaves the bridge's outputs off (canworks.ok stays FALSE).
