## ADDED Requirements

### Requirement: Unnamed networks named on switch to OpenPLC
Switching a config to OpenPLC through Modbus SHALL give every CANopen master network without a `name` the name of its adapter's interface when that is a valid name not used by another network, else `net<k>` with k its place in `networks`, so that the switch adds a live list for every CANopen master network. One Undo SHALL restore the config as it was.

#### Scenario: One unnamed network
- **WHEN** a plugin config with one unnamed CANopen master network on `can1` is switched to OpenPLC through Modbus
- **THEN** the network is named `can1`, `bridge.live_lists` has an entry for it, and `CO_NODE_LIVE` on network 0 reads its nodes

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

## MODIFIED Requirements

### Requirement: OpenPLC editor files on save
Saving an OpenPLC project (target OpenPLC, inside an editor project) with no errors SHALL also write the editor files of `canopen-editor-project` (the remote device file, the `canworks_in` and `canworks_out` programs, the `canworks` variable list and the task instances) and SHALL touch no other editor file or POU, except that it SHALL enable the `canworks` library in the project when it is not enabled, and install the library into OpenPLC Editor when it is missing there or older, as New editor project does. A save with errors SHALL write none of them. When the remote device file or one of the two programs changed on disk since canworks last wrote it, Save SHALL ask before writing anything, naming those files; Cancel SHALL save nothing. After writing them the message SHALL say that an OpenPLC Editor with this project open must reopen it before Build. A standalone OpenPLC config folder SHALL write no editor files and SHALL say so on its Project page.

#### Scenario: Save writes the device
- **WHEN** the user adds a TPDO entry in an OpenPLC project and saves
- **THEN** `devices/remote/canworks.json` gains a read group for it, `canworks_in` reads it into a new `canworks` variable, and the user's `main` is unchanged

#### Scenario: Program edited in the editor
- **WHEN** the user changed `pous/programs/canworks_in.st` in OpenPLC Editor and then saves in the configurator
- **THEN** Save asks whether to write the files again, naming that file, and Cancel leaves the config and the editor files as they were

#### Scenario: Library enabled on save
- **WHEN** a switched plugin project without the `canworks` library is saved
- **THEN** the project lists the library as enabled and `canworks_in` builds without adding it by hand
