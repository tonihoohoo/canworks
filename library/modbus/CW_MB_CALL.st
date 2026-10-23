(*
 * CW_MB_CALL: one block's use of a request mailbox of the bridge
 * (bridge-plc-blocks), for the blocks of this library.
 * While RUN is TRUE it waits for a free mailbox in ticket order (the
 * waiting instance with the lowest ticket of the last scan goes first),
 * then keeps it (OWNED, request words from LINK[BASE], response words from
 * LINK[BASE + 72]) and stamps it every call. A call with SEND while OWNED and
 * not WAITING writes the request: OP, NET, A0..A5; the caller puts the data
 * words at LINK[BASE + 8] first. ANSWERED is TRUE in the call that sees the
 * answer, with ERR its ERROR_ID (0: done); the results are at LINK[BASE + 74]
 * and the data at LINK[BASE + 80]. RUN FALSE frees the mailbox. LOST: the
 * bridge is not reachable (the block ends with ERROR_ID 20); the mailbox is
 * freed.
 *)
FUNCTION_BLOCK CW_MB_CALL
VAR_INPUT
  RUN : BOOL;
  SEND : BOOL;
  OP : USINT;
  NET : USINT;
  A0 : WORD;
  A1 : WORD;
  A2 : WORD;
  A3 : WORD;
  A4 : WORD;
  A5 : WORD;
END_VAR
VAR_OUTPUT
  OWNED : BOOL;
  BASE : INT;
  WAITING : BOOL;
  ANSWERED : BOOL;
  ERR : UINT;
  LOST : BOOL;
END_VAR
VAR_IN_OUT
  LINK : ARRAY[0..1279] OF WORD;
END_VAR
VAR
  me : WORD;
  ticket : WORD;
  m : INT;
  i : INT;
  n : INT;
  counter : WORD;
END_VAR
  IF me = 0 THEN
    LINK[24] := LINK[24] + 1;
    me := LINK[24];
  END_IF;
  ANSWERED := FALSE;
  LOST := (LINK[21] AND 16#0001) = 0;
  IF OWNED AND LINK[94 + m] <> me THEN
    LOST := TRUE;
    OWNED := FALSE;
  END_IF;
  IF NOT RUN OR LOST THEN
    IF OWNED AND LINK[94 + m] = me THEN
      LINK[94 + m] := 0;
    END_IF;
    OWNED := FALSE;
    WAITING := FALSE;
    ticket := 0;
    RETURN;
  END_IF;
  IF NOT OWNED THEN
    IF ticket = 0 THEN
      LINK[91] := LINK[91] + 1;
      IF LINK[91] = 0 THEN
        LINK[91] := 1;
      END_IF;
      ticket := LINK[91];
    END_IF;
    n := WORD_TO_INT(LINK[89] AND 16#0007);
    IF n > 4 THEN
      n := 4;
    END_IF;
    (* My turn: nobody waited in the last scan, or I was the lowest. *)
    IF LINK[93] = 0 OR ticket = LINK[93] OR ((ticket - LINK[93]) AND 16#8000) <> 0 THEN
      FOR i := 0 TO n - 1 DO
        IF NOT OWNED AND LINK[94 + i] = 0 THEN
          m := i;
          OWNED := TRUE;
        END_IF;
      END_FOR;
    END_IF;
    IF OWNED THEN
      LINK[94 + m] := me;
      BASE := 144 + 144 * m;
      WAITING := FALSE;
      ticket := 0;
    ELSIF LINK[92] = 0 OR ((ticket - LINK[92]) AND 16#8000) <> 0 THEN
      LINK[92] := ticket;
    END_IF;
  END_IF;
  IF NOT OWNED THEN
    RETURN;
  END_IF;
  LINK[98 + m] := LINK[90];
  IF SEND AND NOT WAITING THEN
    (* A counter the bridge has not seen: not the last request, not the echo. *)
    counter := LINK[BASE] + 1;
    IF counter = LINK[BASE + 72] THEN
      counter := counter + 1;
    END_IF;
    LINK[BASE] := counter;
    LINK[BASE + 1] := SHL(USINT_TO_WORD(OP), 8) OR USINT_TO_WORD(NET);
    LINK[BASE + 2] := A0;
    LINK[BASE + 3] := A1;
    LINK[BASE + 4] := A2;
    LINK[BASE + 5] := A3;
    LINK[BASE + 6] := A4;
    LINK[BASE + 7] := A5;
    WAITING := TRUE;
  ELSIF WAITING AND LINK[BASE + 72] = counter AND SHR(LINK[BASE + 73], 8) >= 2 THEN
    WAITING := FALSE;
    ANSWERED := TRUE;
    ERR := WORD_TO_UINT(LINK[BASE + 73] AND 16#00FF);
  END_IF;
END_FUNCTION_BLOCK
