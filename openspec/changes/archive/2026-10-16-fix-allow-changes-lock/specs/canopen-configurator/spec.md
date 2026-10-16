## MODIFIED Requirements

### Requirement: Allow changes in the connection bar
On an adapter connection, the connection bar SHALL show the lock's state with one button: "🔒 Read-only" with **Unlock…**, or "🔓 Changes allowed" with **Lock**. It SHALL NOT be a checkbox, and no label SHALL name the opposite of what its click does. Changes SHALL be off for every new connection. **Unlock…** SHALL ask before allowing changes; **Lock** SHALL go back to read-only without asking. Both SHALL apply to the open connection without reconnecting and keep focus on the bar's button. On a runtime connection, the bar SHALL show the runtime's own setting as read-only text with a lock and SHALL say that it is set in Configure → Online access and takes effect after an upload, with a link that opens that entry.

#### Scenario: Switch on an open adapter connection
- **WHEN** the user is connected read-only to an adapter, presses Unlock… in the connection bar and confirms
- **THEN** the bar shows "Changes allowed" with Lock, write controls on every page are enabled without reconnecting, and no "another master" message appears

#### Scenario: Read-only adapter bar
- **WHEN** the user is connected read-only to an adapter
- **THEN** the bar shows "Read-only" with an Unlock… button and no checkbox, and pressing Unlock… asks "Allow changes on this adapter connection?"; Cancel leaves it read-only

#### Scenario: Lock again
- **WHEN** changes are allowed on an adapter connection and the user presses Lock
- **THEN** the bar shows "Read-only" with Unlock… without asking, write controls show "Locked" with Unlock…, and the connection stays open

#### Scenario: Runtime decides
- **WHEN** the user is connected to a runtime whose config has allow changes off
- **THEN** the bar shows "Read-only (runtime setting)" with no button, and its link opens Online access in Configure

### Requirement: Unlock from a locked control
A write control disabled because changes are not allowed SHALL say "Locked. Changes are not allowed on this connection." and offer **Unlock…**. On an adapter, Unlock SHALL ask the same question as **Unlock…** in the connection bar and, when confirmed, allow changes on the open connection without reconnecting, with focus kept on the control. On a runtime, Unlock SHALL explain that Allow changes is set in Configure → Bus and master → Online access and takes effect after an upload. Controls disabled for another reason SHALL keep their own reason.

#### Scenario: Unlock in place
- **WHEN** the user is connected read-only to an adapter, presses Unlock… beside node 5's Start button and confirms
- **THEN** the connection bar shows "Changes allowed" with Lock, Start is enabled and focused, and no "another master" message appears
