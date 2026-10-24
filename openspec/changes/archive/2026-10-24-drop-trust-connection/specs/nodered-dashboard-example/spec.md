## MODIFIED Requirements

### Requirement: Shared plant logic
The example's flow SHALL do the shared plant logic of the CODESYS example (`PLANT_LOGIC`) in one function node. The alarm SHALL come on when `rtd.temp1`/10 is above the limit (default 25.0 °C, set on the Plant page) and stay on until Ack is pressed while the temperature is at or below the limit. Bit 0 of `dio_out0` SHALL follow the alarm. While the Plant page's **Running light** (`RUN`, on at start) is on, one bit SHALL move along `dio_out1` every 500 ms and `LIGHT_OK` SHALL be shown true when, at a step, `dio_in1` equals the value written to `dio_out1`; while it is off, `LIGHT_OK` is false.

#### Scenario: Alarm and Ack
- **WHEN** the limit is 25.0 °C and the simulated temperature 1 rises past 25.0 °C and later falls back below it
- **THEN** the alarm lamp and bit 0 of `dio_out0` come on, stay on after the temperature falls, and go off when Ack is pressed

#### Scenario: Ack while too hot
- **WHEN** Ack is pressed while temperature 1 is above the limit
- **THEN** the alarm stays on
