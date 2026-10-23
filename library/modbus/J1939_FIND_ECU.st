(*
 * J1939_FIND_ECU: while ENABLE, looks again and again on J1939 network
 * NETWORK for an ECU whose NAME matches NAME in the bits set in MASK
 * (FIND_ECU through a request mailbox; each look takes its turn): VALID
 * after the first answer, FOUND with its ADDRESS (254 when not found) and
 * FOUND_NAME, COUNT ECUs that match. ERROR_ID
 * (docs/plc-library.md#j1939-blocks): 1 the network is not running, 2 no
 * such network, 10 not a J1939 network, 20 the bridge is not reachable,
 * 22 the config has no request mailbox.
 *)
(*
 * LINK is the generated `canworks.link` (ARRAY[0..1279] OF WORD); the block uses a request mailbox of the bridge (`mailboxes` in the config); instances share
 * them in the order they started (see
 * CW_LINK_SERVICE for the words).
 *)
FUNCTION_BLOCK J1939_FIND_ECU
VAR_INPUT
  ENABLE : BOOL;
  NETWORK : USINT;
  NAME : LWORD;
  MASK : LWORD;
END_VAR
VAR_IN_OUT
  LINK : ARRAY[0..1279] OF WORD;
END_VAR
VAR_OUTPUT
  VALID : BOOL;
  FOUND : BOOL;
  ADDRESS : USINT;
  FOUND_NAME : LWORD;
  COUNT : UINT;
  ERROR : BOOL;
  ERROR_ID : UINT;
END_VAR
VAR
  x : CW_REQUEST;
  buf : ARRAY[0..1784] OF BYTE;
  run : BOOL;
  i : INT;
END_VAR
  IF NOT ENABLE THEN
    VALID := FALSE;
    FOUND := FALSE;
    ERROR := FALSE;
    ERROR_ID := 0;
    run := FALSE;
    x(EXECUTE := FALSE, LINK := LINK, DATA := buf);
    RETURN;
  END_IF;
  IF NOT x.BUSY THEN
    FOR i := 0 TO 7 DO
      buf[i] := LWORD_TO_BYTE(SHR(NAME, 56 - 8 * i));
      buf[8 + i] := LWORD_TO_BYTE(SHR(MASK, 56 - 8 * i));
    END_FOR;
  END_IF;
  (* One look per EXECUTE edge: the call after an answer drops it. *)
  run := NOT (x.DONE OR x.ERROR);
  x(EXECUTE := run, OP := 15, NET := NETWORK, A0 := WORD#0, A1 := WORD#0, A2 := WORD#0, A3 := WORD#0, A4 := WORD#0, A5 := WORD#0, LENGTH := 16,
    FETCH_MAX := 8, LINK := LINK, DATA := buf);
  IF x.DONE THEN
    VALID := TRUE;
    FOUND := x.R0 <> WORD#0;
    ADDRESS := SEL(FOUND, USINT#254, WORD_TO_USINT(x.R1));
    COUNT := WORD_TO_UINT(x.R2);
    FOUND_NAME := LWORD#0;
    FOR i := 0 TO 7 DO
      FOUND_NAME := SHL(FOUND_NAME, 8) OR BYTE_TO_LWORD(buf[i]);
    END_FOR;
    ERROR := FALSE;
    ERROR_ID := 0;
  ELSIF x.ERROR THEN
    VALID := FALSE;
    ERROR := TRUE;
    ERROR_ID := x.ERROR_ID;
  END_IF;
END_FUNCTION_BLOCK
