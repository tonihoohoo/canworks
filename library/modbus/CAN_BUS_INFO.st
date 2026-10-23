(*
 * CAN_BUS_INFO: the state of network NETWORK (one of the first 8) from the
 * bridge's network info block, updated every 100 ms, without a request:
 * STATE (0 error active, 1 warning, 2 error passive, 3 bus off, 4 unknown),
 * TX_ERRORS and RX_ERRORS (error counters), BUS_OFF_COUNT, BUS_LOAD (%),
 * RX_COUNT and TX_COUNT (frames), ERROR_FRAMES. ERROR_ID
 * (docs/plc-library.md#frame-blocks): 2 no such network, 20 the bridge is
 * not reachable, 22 the config has no network info (or NETWORK is past the
 * first 8).
 *)
(*
 * LINK is the generated `canworks.link` (ARRAY[0..1279] OF WORD); the block reads the bridge's network info block (see
 * CW_LINK_SERVICE for the words).
 *)
FUNCTION_BLOCK CAN_BUS_INFO
VAR_INPUT
  NETWORK : USINT;
END_VAR
VAR_IN_OUT
  LINK : ARRAY[0..1279] OF WORD;
END_VAR
VAR_OUTPUT
  STATE : USINT;
  TX_ERRORS : UINT;
  RX_ERRORS : UINT;
  BUS_OFF_COUNT : UDINT;
  BUS_LOAD : USINT;
  RX_COUNT : UDINT;
  TX_COUNT : UDINT;
  ERROR_FRAMES : UDINT;
  ERROR : BOOL;
  ERROR_ID : UINT;
END_VAR
VAR
  p : INT;
END_VAR
  ERROR_ID := 0;
  IF (LINK[21] AND 16#0001) = 0 THEN
    ERROR_ID := 20;
  ELSIF (LINK[89] AND 16#0020) = 0 OR NETWORK > 7 THEN
    ERROR_ID := 22;
  ELSE
    p := 840 + 18 * USINT_TO_INT(NETWORK);
    IF LINK[p + 17] = 0 THEN
      ERROR_ID := 2;
    END_IF;
  END_IF;
  ERROR := ERROR_ID <> 0;
  IF ERROR THEN
    STATE := 4;
    TX_ERRORS := 0;
    RX_ERRORS := 0;
    BUS_OFF_COUNT := 0;
    BUS_LOAD := 0;
    RX_COUNT := 0;
    TX_COUNT := 0;
    ERROR_FRAMES := 0;
    RETURN;
  END_IF;
  STATE := WORD_TO_USINT(SHR(LINK[p], 8));
  BUS_LOAD := WORD_TO_USINT(LINK[p] AND 16#00FF);
  TX_ERRORS := WORD_TO_UINT(LINK[p + 1]);
  RX_ERRORS := WORD_TO_UINT(LINK[p + 2]);
  BUS_OFF_COUNT := WORD_TO_UDINT(LINK[p + 3]) * 65536 + WORD_TO_UDINT(LINK[p + 4]);
  RX_COUNT := WORD_TO_UDINT(LINK[p + 5]) * 65536 + WORD_TO_UDINT(LINK[p + 6]);
  TX_COUNT := WORD_TO_UDINT(LINK[p + 7]) * 65536 + WORD_TO_UDINT(LINK[p + 8]);
  ERROR_FRAMES := WORD_TO_UDINT(LINK[p + 9]) * 65536 + WORD_TO_UDINT(LINK[p + 10]);
END_FUNCTION_BLOCK
