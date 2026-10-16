# Tasks: no-start-for-held-nodes

## 1. Tests first
- [x] 1.1 Simulator test: `CO_NETWORK_STOP` with `NODE_COMMAND := 2`, a node power-cycles; check the CAN frames: no NMT START (0x000 `01 id` or `01 00`) between its boot-up and its STOP, and its state byte never reads 5.
- [x] 1.2 Same with a `CO_NMT` hold (STOP and ENTER PRE-OPERATIONAL) and with the command byte at 2.
- [x] 1.3 `start_all_nodes` with one node held: the master's start-all sends no START that reaches the held node; the other nodes are started.
- [x] 1.4 Release: `CO_NMT` START and `CO_NETWORK_START` start the node again; a node that boots after the release is started by the master.
- [x] 1.5 Bus session restart (link down/up) with a held node: as 1.1.

## 2. Plugin
- [x] 2.1 Drop Lely's NMT START to a held node at the send hook; a START to all nodes goes to each node that is not held (design.md: 0x1F81 bit 2 also gates the boot itself).
- [x] 2.2 `HandleBoot`: a held node is not counted as started; its state is the hold's.

## 3. Docs
- [x] 3.1 NMT block docs: a held node gets no START when it boots; README sentence.

## 4. Hardware
- [ ] 4.1 On the Pi with node 23: `CO_NETWORK_STOP` with `NODE_COMMAND := 2`, take the CAN interface down and up; the candump shows no `000 [2] 01 17` before `02 17`. Clean PLC start afterwards.

## 5. CI time
- [ ] 5.1 PR body: CI wall and summed job time vs the main baseline.
