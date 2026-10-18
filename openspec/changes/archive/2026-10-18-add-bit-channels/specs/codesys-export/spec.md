## ADDED Requirements

### Requirement: Bit channels in the CODESYS export
The plan SHALL list each channel's bit channels with bit number and variable name, named as the editor declarations would name them. The script SHALL map each to the bit sub-channel of the channel's I/O mapping; if the CODESYS project gives no access to a channel's bit sub-channels, the script SHALL map the channel only and its report SHALL name the bits left to map by hand.

#### Scenario: Named bit in the plan
- **WHEN** a CODESYS config's node `panel` maps 0x6000:1 with bit 3 named `jog_x_plus`
- **THEN** the plan's channel for input 0x6000 sub 1 of `panel` lists bit 3 with variable `panel_jog_x_plus`
