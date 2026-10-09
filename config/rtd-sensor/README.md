# RTD temperature module

A test setup with a measuring device instead of the Lely tutorial slave: **RTD-8**, a made-up 8-channel RTD temperature input module with a CiA 404 object dictionary, described the way vendor EDS files usually are (four TPDOs with a default mapping, writable sensor settings, manufacturer objects). On the bus it is played by `sensor_slave` (`test/sensor/`), a Lely slave that loads the same EDS and moves the measured values.

| File | What it is |
|---|---|
| `rtd8.eds` | The module's EDS, written by `make_eds.py` (`python3 config/rtd-sensor/make_eds.py > config/rtd-sensor/rtd8.eds`). |
| `canopen_config.json` | The master's config: node 5, the PDO map, startup SDOs. |
| `rtd_monitor.st` | Starter PLC program: scales the temperatures and raises an alarm. |

## The device

| Object | Meaning | Type |
|---|---|---|
| 0x7130:1-8 | AI input process value, channel 0-7 (0.1 degC) | INTEGER16, ro, PDO-mappable |
| 0x6150:1-8 | AI status, channel 0-7 (0 = OK) | UNSIGNED8, ro, PDO-mappable |
| 0x6110:1-8 | Sensor type (30 = Pt100, range 30-33) | UNSIGNED16, rw |
| 0x1800-0x1803 / 0x1A00-0x1A03 | 4 TPDOs, mapping writable | |

The device has no RPDOs: it only produces inputs.

## The PDO map comes from the config

The EDS maps channel value and status pairs into TPDOs 1-4 by default. The config ignores that and builds its own map:

| PDO | Entries | PLC |
|---|---|---|
| TPDO 1 (0x185) | 0x7130:1-4 (AI0-AI3 temperatures) | `%IW100`-`%IW103` |
| TPDO 2 (0x285) | 0x6150:1-4 (AI0-AI3 status) | `%IB100`-`%IB103` |
| TPDO 3, 4 | not in the config, switched off by the master | |

To prove that, the simulated device starts with `--blank-pdos`: every PDO mapping parameter (`0x1600`-`0x17FF`, `0x1A00`-`0x1BFF`, sub-index 0) defaults to zero mapped objects, as on a device whose mapping was never configured. The only way the temperatures reach the PLC is the master writing the map over SDO at boot. The startup SDOs then set channels 0-3 to Pt100 (0x6110 := 30).

## Run it

On the vcan0 test bus (CI does this on every push):

```sh
cmake --build build
test/sensor/run.sh                 # 10 s, blank device mapping
test/sensor/run.sh --keep-vendor-pdos
```

`run.sh` starts the simulated module as node 5 with AI0-AI3 moving between 20.0-26.0, 30.0-36.0, 40.0-46.0 and -10.0 to -4.0 degC, loads the real plugin with a stand-in PLC scan, and checks the values in `%IW100`-`%IW103` and the PDO frames on the bus.

On the Pi with the runtime (stock install, see [docs/install-stock.md](../../docs/install-stock.md)), start the simulated module and leave it running:

```sh
build/test/sensor_slave vcan0 config/rtd-sensor/rtd8.eds 5 --blank-pdos \
    --signal 0x7130:1=200..260 --signal 0x7130:2=300..360 \
    --signal 0x7130:3=400..460 --signal 0x7130:4=-100..-40
```

Then build `rtd_monitor.st` in the editor (Build only) and deploy it with this config:

```sh
canworks-deploy --bundle "<project>/build/OpenPLC Runtime v4/src" \
    --config config/rtd-sensor/canopen_config.json --runtime plc.local --fingerprint <runtime cert SHA-256>
```

([docs/deploy.md](../../docs/deploy.md) covers the login and the certificate fingerprint.)

`high_alarm` (`%QX100.0`) switches on while AI0 is above 25.0 degC, a few seconds of every 12 s triangle.

`sensor_slave` works with any EDS: give it the device's file and one `--signal IDX:SUB=MIN..MAX[/STEP]` per value to move. Each signal is written with the object's own data type every `--period-ms` (default 100).
