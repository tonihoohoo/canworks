## 1. Bridge

- [x] 1.1 `modbus_trace.{h,cpp}`: `set_ignored(holding, input)` with sorted register lists; the data hash skips them for functions 3, 4, 6, 16 and 23 (the key is unchanged, except functions 5 and 6, whose kind is now their address only)
- [x] 1.2 `bridge_host.cpp`: hand the trace the keepalive registers and the receive and cyclic table clock words from `MailboxLayout` at start (none when the mailboxes are off)
- [x] 1.3 C++ tests (`bridge_tests` modbus_trace_changes_only_leaves_out_mailbox_words, modbus_trace_changes_only): a function 6 write of 7, 8, 7 records all three; a write of HR 3-94 where only a keepalive changes is counted, not recorded; a read of the receive block where only the clock changes is counted; a change of another value beside them is recorded with all bytes; `changes_only` false records every request

## 2. Docs and version

- [x] 2.1 `docs/modbus-bridge.md` "Seeing the Modbus traffic" and `docs/trace.md`: the words the comparison leaves out, and that turning Only changes off records every request
- [x] 2.2 Tools version bump (pyproject, `__init__`, uv.lock, tests/data/doc, tests/data/nodered)
- [x] 2.3 `openspec archive trace-skips-mailbox-counters --yes` on the branch; one PR with spec, code and archive; squash auto-merge

## 3. Hardware check

- [ ] 3.1 Pi with node 23 and the OpenPLC program with cyclic jobs: 60 s Modbus trace with Only changes; the writes of the mailbox group are counted, not recorded, while nothing changes, and a forced valve output is still recorded each time it changes
