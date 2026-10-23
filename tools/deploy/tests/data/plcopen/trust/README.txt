canworks for truST (canworks-deploy VERSION)

canworks.xml holds the canworks list (canworks.ok, the typed values, canworks.link and the channel arrays canworks.in_w and canworks.out_w), the programs canworks_in and canworks_out and the canworks library. The bridge listens on port 1502, unit 1; the PLC reaches it at 127.0.0.1.

The bridge takes writes only from 192.168.10.20: the PLC's address must be one of them.

1. Import the file into the truST project:
     trust-runtime plcopen import --input canworks.xml --project <project folder>
   (or in VS Code: truST: Import PLCopen XML).
2. Copy canworks_io.st into the project's src folder (truST's import drops AT addresses, so the I/O image comes as its own file).
3. Replace the [io] tables of the project's io.toml with io.toml.part, and set the [resource] name in runtime.toml to canworks_res (the imported configuration's resource).
4. Add your program to canworks_task between canworks_in and canworks_out in the imported configuration.
5. trust-runtime build --project <project folder>, then run it.

The task runs every 200 ms. The project's %I and %Q image belongs to the bridge: don't locate other variables there.

Export again after any config change: a program built for another map leaves the bridge's outputs off (canworks.ok stays FALSE).
