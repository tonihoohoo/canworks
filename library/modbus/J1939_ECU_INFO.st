(*
 * J1939_ECU_INFO: while ENABLE, the canworks ECU of J1939 network NETWORK
 * (one of the first 8) from the bridge's network info block, without a
 * request: VALID, STATE (0 claiming, 1 claimed, 2 cannot claim, 3 off),
 * ADDRESS, NAME, ECU_COUNT (ECUs seen on the bus). ERROR_ID
 * (docs/plc-library.md#j1939-blocks): 1 the network is not running, 2 no
 * such network, 10 not a J1939 network, 20 the bridge is not reachable,
 * 22 the config has no network info (or NETWORK is past the first 8).
 *)
(*
 * LINK is the generated `canworks.link` (ARRAY[0..1279] OF WORD); the block reads the bridge's network info block (see
 * CW_LINK_SERVICE for the words).
 *)
FUNCTION_BLOCK J1939_ECU_INFO
VAR_INPUT
  ENABLE : BOOL;
  NETWORK : USINT;
END_VAR
VAR_IN_OUT
  LINK : ARRAY[0..1279] OF WORD;
END_VAR
VAR_OUTPUT
  VALID : BOOL;
  STATE : USINT;
  ADDRESS : USINT;
  NAME : LWORD;
  ECU_COUNT : UINT;
  ERROR : BOOL;
  ERROR_ID : UINT;
END_VAR
VAR
  p : INT;
END_VAR
  ERROR_ID := 0;
  VALID := FALSE;
  IF NOT ENABLE THEN
    ERROR := FALSE;
    RETURN;
  END_IF;
  IF (LINK[21] AND WORD#16#0001) = WORD#0 THEN
    ERROR_ID := 20;
  ELSIF (LINK[89] AND WORD#16#0020) = WORD#0 OR NETWORK > 7 THEN
    ERROR_ID := 22;
  ELSE
    p := 960 + 18 * USINT_TO_INT(NETWORK);
    IF LINK[p + 17] = WORD#0 THEN
      ERROR_ID := 2;
    ELSIF SHR(LINK[p + 11], 8) = WORD#16#FF THEN
      ERROR_ID := WORD_TO_UINT(LINK[p + 11] AND WORD#16#00FF);
    END_IF;
  END_IF;
  ERROR := ERROR_ID <> 0;
  IF ERROR THEN
    STATE := 3;
    ADDRESS := 254;
    RETURN;
  END_IF;
  VALID := TRUE;
  STATE := WORD_TO_USINT(SHR(LINK[p + 11], 8));
  ADDRESS := WORD_TO_USINT(LINK[p + 11] AND WORD#16#00FF);
  NAME := SHL(WORD_TO_LWORD(LINK[p + 12]), 48) OR SHL(WORD_TO_LWORD(LINK[p + 13]), 32) OR
          SHL(WORD_TO_LWORD(LINK[p + 14]), 16) OR WORD_TO_LWORD(LINK[p + 15]);
  ECU_COUNT := WORD_TO_UINT(LINK[p + 16]);
END_FUNCTION_BLOCK
