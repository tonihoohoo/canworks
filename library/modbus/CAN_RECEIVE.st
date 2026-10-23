(*
 * CAN_RECEIVE: receives the CAN frames of network NETWORK whose identifier
 * matches ID under MASK (MASK 0: ID exactly; ALL_IDS: every frame of that
 * format), standard or EXTENDED, through a receiver of the bridge with a
 * queue of DEPTH frames (0: 32, at most 256). ENABLE opens it. Each call
 * gives at most one frame, oldest first: RECEIVED with RX_ID, RX_EXTENDED,
 * RX_RTR, RX_DLC, RX_DATA and TIMESTAMP (UTC microseconds); call it again in
 * the same scan to read more (`WHILE rx.RECEIVED DO ... rx(...); END_WHILE`).
 * QUEUED frames still wait in the bridge, OVERFLOW the queue was full,
 * DROPPED frames lost. ERROR_ID (docs/plc-library.md#frame-blocks): 1 the
 * network is not running, 2 no such network, 3 invalid input, 5 no free
 * receiver, 8 the bridge closed the receiver (it opens again), 20 the
 * bridge is not reachable, 22 the config has no receive or request mailbox.
 * After 1, 8 and 20 it opens again by itself.
 *)
(*
 * LINK is the generated `canworks.link` (ARRAY[0..1279] OF WORD); the block uses the bridge's receive mailbox and, to open and close its receiver, a
 * request mailbox (see
 * CW_LINK_SERVICE for the words).
 *)
FUNCTION_BLOCK CAN_RECEIVE
VAR_INPUT
  ENABLE : BOOL;
  NETWORK : USINT;
  ID : UDINT;
  MASK : UDINT;
  ALL_IDS : BOOL;
  EXTENDED : BOOL;
  DEPTH : UINT;
END_VAR
VAR_IN_OUT
  RX_DATA : ARRAY[0..7] OF BYTE;
  LINK : ARRAY[0..1279] OF WORD;
END_VAR
VAR_OUTPUT
  ACTIVE : BOOL;
  RECEIVED : BOOL;
  RX_ID : UDINT;
  RX_EXTENDED : BOOL;
  RX_RTR : BOOL;
  RX_DLC : USINT;
  TIMESTAMP : ULINT;
  QUEUED : UINT;
  OVERFLOW : BOOL;
  DROPPED : UDINT;
  ERROR : BOOL;
  ERROR_ID : UINT;
END_VAR
VAR
  rx : CW_RX;
  prev : BOOL;
  was_active : BOOL;
  last_drop : WORD;
  id_mask : UDINT;
  rec : INT;
  i : INT;
END_VAR
  IF ENABLE AND NOT prev THEN
    QUEUED := 0;
    OVERFLOW := FALSE;
    DROPPED := 0;
  END_IF;
  prev := ENABLE;
  IF ALL_IDS THEN
    id_mask := 0;
  ELSIF MASK <> 0 THEN
    id_mask := MASK;
  ELSIF EXTENDED THEN
    id_mask := 16#1FFFFFFF;
  ELSE
    id_mask := 16#7FF;
  END_IF;
  rx(ENABLE := ENABLE, CHANGED := FALSE, NEXT := TRUE, KIND := 1, NETWORK := NETWORK,
     FLAGS := SEL(EXTENDED, USINT#0, USINT#1), DEPTH := DEPTH, ID := ID, MASK := id_mask, RETRY := DWORD#16#00100102,
     LINK := LINK);
  IF rx.ACTIVE AND NOT was_active THEN
    last_drop := WORD#0;
  END_IF;
  was_active := rx.ACTIVE;
  RECEIVED := rx.RECEIVED;
  IF RECEIVED THEN
    rec := rx.REC;
    QUEUED := WORD_TO_UINT(LINK[rec + 1]);
    DROPPED := DROPPED + WORD_TO_UDINT(DINT_TO_WORD(WORD_TO_DINT(LINK[rec + 2]) - WORD_TO_DINT(last_drop)));
    last_drop := LINK[rec + 2];
    OVERFLOW := (LINK[rec] AND WORD#16#0004) <> WORD#0;
    TIMESTAMP := LWORD_TO_ULINT(SHL(WORD_TO_LWORD(LINK[rec + 3]), 48) OR SHL(WORD_TO_LWORD(LINK[rec + 4]), 32) OR
                 SHL(WORD_TO_LWORD(LINK[rec + 5]), 16) OR WORD_TO_LWORD(LINK[rec + 6]));
    RX_ID := WORD_TO_UDINT(LINK[rec + 7]) * 65536 + WORD_TO_UDINT(LINK[rec + 8]);
    RX_EXTENDED := (LINK[rec + 9] AND WORD#16#0100) <> WORD#0;
    RX_RTR := (LINK[rec + 9] AND WORD#16#0200) <> WORD#0;
    RX_DLC := WORD_TO_USINT(LINK[rec + 9] AND WORD#16#00FF);
    FOR i := 0 TO 3 DO
      RX_DATA[2 * i] := WORD_TO_BYTE(SHR(LINK[rec + 10 + i], 8));
      RX_DATA[2 * i + 1] := WORD_TO_BYTE(LINK[rec + 10 + i]);
    END_FOR;
  END_IF;
  ACTIVE := rx.ACTIVE;
  ERROR := rx.ERROR;
  ERROR_ID := rx.ERROR_ID;
END_FUNCTION_BLOCK
