## ADDED Requirements

### Requirement: Old located variables in an OpenPLC project's main
For an OpenPLC project (target OpenPLC through Modbus, inside an editor project) the configurator SHALL find, in `pous/programs/main.st`, the located declarations whose names are members of the `canworks` variable list. When there are any, the Project page SHALL show a warning that `main` still declares that many canworks values at their old plugin locations, which read nothing now, naming the first locations, with the button **Use canworks.\* in main**; Problems SHALL list the same as a warning that opens the Project page; and the message after **Switch to OpenPLC through Modbus** SHALL mention it.

The button SHALL first copy `main.st` to `canworks/main-before-move.st`, then remove those declarations and the generated comment `(* CANopen I/O declared from canworks/canworks.json *)`, drop a `VAR` block left empty, and replace each use of a removed name in the program's code with `canworks.<name>`, matching names without regard to case, and leaving comments, strings and names after a `.` unchanged. A name that `main` also declares without a location SHALL be neither removed nor replaced. The message SHALL give the number of declarations and uses moved, name any names left, say where the copy is, and say that an OpenPLC Editor with the project open must reopen it before Build. Located declarations of other names, other POUs and the config SHALL NOT change.

#### Scenario: Switched plugin project
- **WHEN** a plugin project whose `main` declares `rtd_ok : BOOL AT %IX10.0;` and uses `IF rtd_ok THEN` is switched to OpenPLC through Modbus and saved
- **THEN** the Project page warns that `main` declares 1 canworks value at its old plugin location `%IX10.0`, and Problems lists the warning

#### Scenario: Move
- **WHEN** the user presses **Use canworks.\* in main** on that project
- **THEN** `main.st` has no `rtd_ok` declaration, its code reads `IF canworks.rtd_ok THEN`, `canworks/main-before-move.st` holds the old text, and the warning is gone

#### Scenario: User's own I/O and comments kept
- **WHEN** `main` also declares `start_button : BOOL AT %IX0.0;` and has the comment `(* rtd_ok is the sensor *)`
- **THEN** after the move `start_button` is still declared at `%IX0.0` and the comment still reads `rtd_ok`
