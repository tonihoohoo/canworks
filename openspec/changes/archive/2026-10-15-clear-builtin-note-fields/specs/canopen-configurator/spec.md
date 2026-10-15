## MODIFIED Requirements

### Requirement: Note editor
The Notes tab SHALL be the only place in a project that opens the Note editor: each row's **Note** button and **Add note…**. The editor SHALL edit one object or sub-object with text, details, unit, scale, a values table, a bits table and manual. For an object with a built-in note the editor SHALL start from the built-in fields and SHALL save only the fields the user changed into the device notes file. Emptying a field that shows a built-in or inherited value SHALL save that field as `null` (cleared); such a field SHALL show the built-in value greyed and marked hidden, with **Use built-in** to bring it back. The object dictionary view, the startup SDO editor and picker and the PDO entry picker SHALL show notes and SHALL NOT offer a Note button.

#### Scenario: Write a note while commissioning
- **WHEN** the user opens the Note editor of 0x2010 of node 7 from its Notes tab, types "Opening ramp of the valve", unit ms, and saves the project
- **THEN** `0x2010` in the EDS's notes file has that text and unit, and the object dictionary view shows them

#### Scenario: Override a built-in note
- **WHEN** the user adds the value -1 "vendor jog mode" to the values of 0x6060 in the Note editor and saves
- **THEN** the device notes file has only a `values` entry for 0x6060 and the built-in text is not copied

#### Scenario: No Note button in the PDO picker
- **WHEN** the user opens Add entry… on a TPDO of a node whose 0x2010 has a note
- **THEN** the picker shows the note's text under 0x2010's name and has no Note button

#### Scenario: Hide an inherited unit
- **WHEN** the user opens the Note editor of 0x6071 sub 0, which shows the built-in unit ‰, empties the unit and keeps the note
- **THEN** the device notes file has `"0x6071:0": {"unit": null}`, the object dictionary shows sub 0 without a unit, and reopening the editor shows ‰ greyed as hidden with **Use built-in**

#### Scenario: Bring the built-in value back
- **WHEN** the user presses **Use built-in** on that unit and keeps the note
- **THEN** the `null` is removed and sub 0 shows ‰ again
