canworks for a PLC that imports PLCopen XML (canworks-deploy VERSION)

canworks.xml holds the canworks list (canworks.ok, the typed values, canworks.link and the channel arrays canworks.in_w and canworks.out_w), the programs canworks_in and canworks_out and the canworks library. The bridge listens on port 1502, unit 1; the PLC reaches it at <the bridge's address>.

The bridge takes writes only from 192.168.10.20: the PLC's address must be one of them.

1. Import canworks.xml into the PLC project (PLCopen XML import).
2. Set up the PLC's Modbus TCP client with the channels below, at a cycle of 200 ms or less.
3. Run canworks_in first and canworks_out last in the task that uses the values (the file's canworks_task does that). Your program goes between them.

Channels (canworks-modbus-map.csv has every register):
  function 4  registers 0..104 -> canworks.in_w[0..104]
  function 4  registers 105..224 -> canworks.in_w[105..224]
  function 4  registers 225..259 -> canworks.in_w[225..259]
  function 16 registers 0..94 -> canworks.out_w[0..94]

Export again after any config change: a program built for another map leaves the bridge's outputs off (canworks.ok stays FALSE).
