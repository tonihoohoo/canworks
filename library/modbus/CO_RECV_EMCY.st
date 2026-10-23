(*
 * CO_RECV_EMCY: receives the EMCY messages of node NODE (0: every node) of
 * CANopen master network NETWORK from the bridge's EMCY history, from the
 * oldest kept message or, with SKIP_OLD, from the next one. ENABLE starts
 * it. Each call gives at most one message, oldest first: NEW with
 * EMCY_NODE, ERROR_CODE, ERROR_REGISTER, MSEF (5 manufacturer bytes) and
 * TIMESTAMP (UTC microseconds). QUEUED messages still wait, LOST messages
 * the history dropped before they were read (OVERFLOW then TRUE).
 * ERROR_ID (docs/plc-library.md#sdo-blocks): 4 the network is not running
 * (tried again), 5 no free receiver, 6 invalid input, 8 a new CANopen
 * session (shown for one call, reading goes on with the new session's
 * messages) or the bridge closed the receiver (it starts again), 20 the
 * bridge is not reachable, 22 the config has no receive or request mailbox.
 *)
(*
 * LINK is the generated `canworks.link` (ARRAY[0..1279] OF WORD); the block uses the bridge's receive mailbox and a request mailbox (see
 * CW_LINK_SERVICE for the words).
 *)
FUNCTION_BLOCK CO_RECV_EMCY
VAR_INPUT
  ENABLE : BOOL;
  NETWORK : USINT;
  NODE : USINT;
  SKIP_OLD : BOOL;
END_VAR
VAR_IN_OUT
  MSEF : ARRAY[0..4] OF BYTE;
  LINK : ARRAY[0..1279] OF WORD;
END_VAR
VAR_OUTPUT
  ACTIVE : BOOL;
  NEW : BOOL;
  EMCY_NODE : USINT;
  ERROR_CODE : WORD;
  ERROR_REGISTER : BYTE;
  TIMESTAMP : ULINT;
  QUEUED : UINT;
  OVERFLOW : BOOL;
  LOST : UDINT;
  ERROR : BOOL;
  ERROR_ID : UINT;
END_VAR
VAR
  rx : CW_RX;
  prev : BOOL;
  was_active : BOOL;
  last_drop : WORD;
  lost_now : UDINT;
  restart : BOOL;
  r : INT;
END_VAR
  NEW := FALSE;
  restart := FALSE;
  IF ENABLE AND NOT prev THEN
    QUEUED := 0;
    OVERFLOW := FALSE;
    LOST := 0;
  ELSIF NOT ENABLE AND prev THEN
    QUEUED := 0;
    OVERFLOW := FALSE;
  END_IF;
  prev := ENABLE;
  rx(ENABLE := ENABLE, CHANGED := FALSE, NEXT := TRUE, KIND := 3, NETWORK := NETWORK,
     FLAGS := SEL(SKIP_OLD, USINT#0, USINT#1), DEPTH := 0, ID := 0, MASK := USINT_TO_UDINT(NODE),
     RETRY := 16#00100110, LINK := LINK);
  IF rx.ACTIVE AND NOT was_active THEN
    last_drop := 0;
  END_IF;
  was_active := rx.ACTIVE;
  IF rx.NEW THEN
    r := rx.REC;
    QUEUED := WORD_TO_UINT(LINK[r + 1]);
    lost_now := WORD_TO_UDINT((LINK[r + 2] - last_drop) AND 16#FFFF);
    last_drop := LINK[r + 2];
    LOST := LOST + lost_now;
    IF lost_now <> 0 THEN
      OVERFLOW := TRUE;
    END_IF;
    IF (LINK[r] AND 16#0002) <> 0 THEN
      restart := TRUE;
    ELSE
      NEW := TRUE;
      TIMESTAMP := SHL(WORD_TO_ULINT(LINK[r + 3]), 48) OR SHL(WORD_TO_ULINT(LINK[r + 4]), 32) OR
                   SHL(WORD_TO_ULINT(LINK[r + 5]), 16) OR WORD_TO_ULINT(LINK[r + 6]);
      EMCY_NODE := WORD_TO_USINT(SHR(LINK[r + 7], 8));
      ERROR_REGISTER := WORD_TO_BYTE(LINK[r + 7]);
      ERROR_CODE := LINK[r + 8];
      MSEF[0] := WORD_TO_BYTE(SHR(LINK[r + 9], 8));
      MSEF[1] := WORD_TO_BYTE(LINK[r + 9]);
      MSEF[2] := WORD_TO_BYTE(SHR(LINK[r + 10], 8));
      MSEF[3] := WORD_TO_BYTE(LINK[r + 10]);
      MSEF[4] := WORD_TO_BYTE(SHR(LINK[r + 11], 8));
    END_IF;
  END_IF;
  ACTIVE := rx.ACTIVE;
  ERROR := rx.ERROR OR restart;
  ERROR_ID := SEL(restart, rx.ERROR_ID, UINT#8);
END_FUNCTION_BLOCK
