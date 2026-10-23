(*
 * CO_SDO_READ: reads object INDEX:SUBINDEX (up to 4 bytes) of node NODE
 * (1..127) of CANopen master network NETWORK into DATA, through the bridge's
 * SDO registers.
 * A rising edge of EXECUTE starts it; BUSY until the bridge has an answer,
 * then DONE or ERROR with ERROR_ID (docs/plc-library.md): 1 the node aborted
 * (ABORT_CODE), 2 no answer within TIMEOUT (T#0s: 5 s), 6 invalid input,
 * 20 the bridge is not reachable, 21 SDO writes are not allowed by the
 * config (ABORT_CODE 16#08000020), 22 the config has no SDO registers,
 * 8 cancelled: the bridge restarted and did not send it (start it again).
 * Instances share the SDO registers: one waits while another uses them.
 *)
(*
 * LINK is the generated `canworks.link` (ARRAY[0..1279] OF WORD): the
 * bridge's blocks as canworks_in and canworks_out copy them from and to the
 * Modbus registers every scan, one word per register (high byte = the
 * bridge's even byte). Words: 0-3 status block, 4-6 control block, 7-13 SDO
 * request, 14-20 SDO response, 21 flags (bit 0 the bridge answers with this
 * program's map, 1 a control block, 2 SDO registers, 8 + n a live list for
 * network n), 22 control block owner, 23 SDO owner, 24 last instance number,
 * 25 + 8n .. 32 + 8n the live list of network n (n 0..7).
 *)
FUNCTION_BLOCK CO_SDO_READ
VAR_INPUT
  EXECUTE : BOOL;
  NETWORK : USINT;
  NODE : USINT;
  INDEX : UINT;
  SUBINDEX : USINT;
  TIMEOUT : TIME;
END_VAR
VAR_OUTPUT
  BUSY : BOOL;
  DONE : BOOL;
  ERROR : BOOL;
  ERROR_ID : UINT;
  ABORT_CODE : UDINT;
  DATA : UDINT;
END_VAR
VAR_IN_OUT
  LINK : ARRAY[0..1279] OF WORD;
END_VAR
VAR
  me : WORD;
  prev : BOOL;
  phase : USINT;           (* 0 idle, 1 waiting for the SDO registers, 2 sent, 3 ended *)
  counter : WORD;
  timer : TON;
  state : WORD;
  err : UINT;
  fin : BOOL;
END_VAR
  IF me = WORD#0 THEN
    LINK[24] := UINT_TO_WORD(WORD_TO_UINT(LINK[24]) + 1);
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
    ABORT_CODE := 0;
    DATA := 0;
    timer(IN := FALSE);
    IF (LINK[21] AND WORD#16#0001) = WORD#0 THEN
      err := 20;
    ELSIF (LINK[21] AND WORD#16#0004) = WORD#0 THEN
      err := 22;
    ELSIF NODE < 1 OR NODE > 127 THEN
      err := 6;
    ELSE
      phase := 1;
    END_IF;
  END_IF;
  IF phase = 1 OR phase = 2 THEN
    timer(IN := TRUE, PT := SEL(TIMEOUT = T#0s, TIMEOUT, T#5s));
    IF (LINK[21] AND WORD#16#0001) = WORD#0 THEN
      err := 20;
    ELSIF timer.Q THEN
      err := 2;
      ABORT_CODE := 16#05040000;
    ELSIF phase = 1 AND (LINK[23] = WORD#0 OR LINK[23] = me) THEN
      LINK[23] := me;
      counter := UINT_TO_WORD(WORD_TO_UINT(LINK[14]) + 1);
      LINK[7] := counter;
      LINK[8] := SHL(WORD#1, 8) OR USINT_TO_WORD(NETWORK);
      LINK[9] := SHL(USINT_TO_WORD(NODE), 8) OR USINT_TO_WORD(SUBINDEX);
      LINK[10] := UINT_TO_WORD(INDEX);
      LINK[11] := WORD#0;
      LINK[12] := WORD#0;
      LINK[13] := WORD#0;
      phase := 2;
    ELSIF phase = 2 AND LINK[14] = counter THEN
      state := SHR(LINK[15], 8);
      IF state = WORD#2 THEN
        DATA := DWORD_TO_UDINT(SHL(WORD_TO_DWORD(LINK[18]), 16) OR WORD_TO_DWORD(LINK[19]));
        fin := TRUE;
      ELSIF state = WORD#3 THEN
        ABORT_CODE := DWORD_TO_UDINT(SHL(WORD_TO_DWORD(LINK[16]), 16) OR WORD_TO_DWORD(LINK[17]));
        IF ABORT_CODE = 16#08000020 THEN
          err := 21;
        ELSIF ABORT_CODE = 16#08000021 THEN
          err := 8;            (* the bridge restarted and did not send it *)
        ELSE
          err := 1;
        END_IF;
      END_IF;
    END_IF;
  END_IF;
  IF err <> 0 OR fin THEN
    phase := 3;
    DONE := fin;
    ERROR := err <> 0;
    ERROR_ID := err;
    timer(IN := FALSE);
    IF LINK[23] = me THEN
      LINK[23] := WORD#0;
    END_IF;
  END_IF;
  BUSY := phase = 1 OR phase = 2;
  prev := EXECUTE;
END_FUNCTION_BLOCK
