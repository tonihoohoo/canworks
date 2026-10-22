(*
 * CO_NMT: sends the NMT command COMMAND (CiA 301 codes: 1 START, 2 STOP,
 * 128 ENTER PRE-OPERATIONAL, 129 RESET NODE, 130 RESET COMMUNICATION) to
 * node NODE (0: every node) of CANopen master network NETWORK, through the
 * bridge's control block. A rising edge of EXECUTE starts it; BUSY until the
 * bridge has handled it, then DONE or ERROR with ERROR_ID (docs/plc-nmt.md):
 * 2 no answer within TIMEOUT (T#0s: 5 s), 5 refused (the bus is down or 16
 * commands wait), 6 invalid input, 20 the bridge is not reachable, 22 the
 * config has no control block. Instances share the control block: one waits
 * while another uses it.
 *)
(*
 * LINK is the generated `canworks.link` (ARRAY[0..88] OF WORD): the
 * bridge's blocks as canworks_in and canworks_out copy them from and to the
 * Modbus registers every scan, one word per register (high byte = the
 * bridge's even byte). Words: 0-3 status block, 4-6 control block, 7-13 SDO
 * request, 14-20 SDO response, 21 flags (bit 0 the bridge answers with this
 * program's map, 1 a control block, 2 SDO registers, 8 + n a live list for
 * network n), 22 control block owner, 23 SDO owner, 24 last instance number,
 * 25 + 8n .. 32 + 8n the live list of network n (n 0..7).
 *)
FUNCTION_BLOCK CO_NMT
VAR_INPUT
  EXECUTE : BOOL;
  NETWORK : USINT;
  NODE : USINT;
  COMMAND : USINT;
  TIMEOUT : TIME;
END_VAR
VAR_OUTPUT
  BUSY : BOOL;
  DONE : BOOL;
  ERROR : BOOL;
  ERROR_ID : UINT;
END_VAR
VAR_IN_OUT
  LINK : ARRAY[0..88] OF WORD;
END_VAR
VAR
  me : WORD;
  prev : BOOL;
  phase : USINT;           (* 0 idle, 1 waiting for the control block, 2 sent, 3 ended *)
  cmd : WORD;
  counter : WORD;
  timer : TON;
  result : WORD;
  err : UINT;
  fin : BOOL;
END_VAR
  IF me = 0 THEN
    LINK[24] := LINK[24] + 1;
    me := LINK[24];
  END_IF;
  IF phase = 3 AND NOT EXECUTE THEN
    phase := 0;
    DONE := FALSE;
    ERROR := FALSE;
  END_IF;
  err := 0;
  fin := FALSE;
  IF phase = 0 AND EXECUTE AND NOT prev THEN
    DONE := FALSE;
    ERROR := FALSE;
    ERROR_ID := 0;
    timer(IN := FALSE);
    CASE COMMAND OF
      1: cmd := 3;
      2: cmd := 4;
      128: cmd := 5;
      129: cmd := 6;
      130: cmd := 7;
    ELSE
      cmd := 0;
    END_CASE;
    IF (LINK[21] AND 16#0001) = 0 THEN
      err := 20;
    ELSIF (LINK[21] AND 16#0002) = 0 THEN
      err := 22;
    ELSIF cmd = 0 OR NODE > 127 THEN
      err := 6;
    ELSE
      phase := 1;
    END_IF;
  END_IF;
  IF phase = 1 OR phase = 2 THEN
    timer(IN := TRUE, PT := SEL(TIMEOUT = T#0s, TIMEOUT, T#5s));
    IF (LINK[21] AND 16#0001) = 0 THEN
      err := 20;
    ELSIF timer.Q THEN
      err := 2;
    ELSIF phase = 1 AND (LINK[22] = 0 OR LINK[22] = me) THEN
      LINK[22] := me;
      counter := LINK[2] + 1;
      LINK[4] := counter;
      LINK[5] := SHL(cmd, 8) OR USINT_TO_WORD(NETWORK);
      LINK[6] := SHL(USINT_TO_WORD(NODE), 8);
      phase := 2;
    ELSIF phase = 2 AND LINK[2] = counter THEN
      result := SHR(LINK[3], 8);
      IF result = 0 THEN
        fin := TRUE;
      ELSIF result = 5 THEN
        err := 5;
      ELSE
        err := 6;
      END_IF;
    END_IF;
  END_IF;
  IF err <> 0 OR fin THEN
    phase := 3;
    DONE := fin;
    ERROR := err <> 0;
    ERROR_ID := err;
    timer(IN := FALSE);
    IF LINK[22] = me THEN
      LINK[22] := 0;
    END_IF;
  END_IF;
  BUSY := phase = 1 OR phase = 2;
  prev := EXECUTE;
END_FUNCTION_BLOCK
