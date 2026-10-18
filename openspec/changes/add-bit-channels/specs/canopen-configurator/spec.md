## ADDED Requirements

### Requirement: Bit channels in the PDOs tab
An integer entry in a PDO mapping table SHALL have **Bits…**, which unfolds a table of the entry's bits: bit number, the device note's bit name, a tick that maps the bit, the name (placeholder: the default name) and, on the OpenPLC target, the location with **Suggest**. **Bits…** SHALL show how many bits are mapped. **Map all bits** SHALL map every bit, placing them on consecutive free `%IX` (input) or `%QX` (output) bytes, bit n at bit n mod 8 of the (n div 8)-th byte; **Unmap all** SHALL remove them. Mapping the first bit of an RPDO entry that has a whole-value location SHALL ask before removing that location. A newly mapped bit SHALL take its name from the device note's bit name, turned into an identifier, when there is one; renaming or removing a note SHALL NOT change a mapped bit's name. Unticked bits of an RPDO entry SHALL read "sent as 0". Each change SHALL be one undo step, and problems SHALL name the node, the PDO, the object and the bit. In a CODESYS config the location column SHALL be hidden; in a Modbus bridge config it SHALL show the bit's coil or discrete input number, read-only.

#### Scenario: Names from the statusword note
- **WHEN** the user opens **Bits…** on a drive's 0x6041 entry and presses **Map all bits**
- **THEN** 16 bits are mapped on two free input bytes, bit 0 named `ready_to_switch_on` from the built-in CiA 402 note

#### Scenario: Rename a button
- **WHEN** the user maps bit 3 of node `panel`'s 0x6000:1 and types `jog_x_plus` as its name
- **THEN** the draft's entry has `{"bit": 3, "name": "jog_x_plus", "iec_location": ...}` and the located declarations show `panel_jog_x_plus`

#### Scenario: Output entry
- **WHEN** an RPDO entry 0x6200:1 has `%QB40` and the user ticks its bit 0
- **THEN** the page asks before removing `%QB40`, and after the answer bits 1 to 7 read "sent as 0"

### Requirement: Online bit values
With online access, a node's **Object dictionary** SHALL show, under the read value of an object that a PDO entry with bit channels maps, each mapped bit with its name and its state.

#### Scenario: Button state
- **WHEN** the panel's 0x6000:1 is 0x08 and bit 3 is named `jog_x_plus`
- **THEN** `jog_x_plus` shows as on and the other mapped bits as off
