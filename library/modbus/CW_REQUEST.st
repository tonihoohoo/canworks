(*
 * CW_REQUEST: one operation through a request mailbox of the bridge, for
 * the CAN and J1939 blocks of this library. A rising edge of EXECUTE starts
 * it: the first LENGTH bytes of DATA go with it (more than 128 go to the
 * bridge first with STAGE requests), then OP on network NET with arguments
 * A0..A5. The answer's results are R0..R5; with RLEN_AT 0..5 that result is
 * the length of the answer's data, which is fetched into DATA (FETCH
 * requests after the first 128 bytes, at most FETCH_MAX); with RLEN_AT 6,
 * FETCH_MAX bytes of the first part are copied. ERROR_ID: the bridge's, or
 * 20 the bridge is not reachable, 22 the config has no request mailbox.
 *)
FUNCTION_BLOCK CW_REQUEST
VAR_INPUT
  EXECUTE : BOOL;
  OP : USINT;
  NET : USINT;
  A0 : WORD;
  A1 : WORD;
  A2 : WORD;
  A3 : WORD;
  A4 : WORD;
  A5 : WORD;
  LENGTH : UINT;
  RLEN_AT : INT := 6;
  FETCH_MAX : UINT;
END_VAR
VAR_OUTPUT
  BUSY : BOOL;
  DONE : BOOL;
  ERROR : BOOL;
  ERROR_ID : UINT;
  R0 : WORD;
  R1 : WORD;
  R2 : WORD;
  R3 : WORD;
  R4 : WORD;
  R5 : WORD;
  GOT : UINT;
END_VAR
VAR_IN_OUT
  LINK : ARRAY[0..1279] OF WORD;
  DATA : ARRAY[0..1784] OF BYTE;
END_VAR
VAR
  mb : CW_MB_CALL;
  prev : BOOL;
  phase : USINT;           (* 0 idle, 1 staging, 2 the operation, 3 fetching, 4 ended *)
  offset : UINT;
  want : UINT;
  cnt : INT;
  k : INT;
  b : INT;
  err : UINT;
  fin : BOOL;
  rlen : WORD;
END_VAR
  IF phase = 4 AND NOT EXECUTE THEN
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
    GOT := 0;
    offset := 0;
    IF (LINK[21] AND WORD#16#0001) = WORD#0 THEN
      err := 20;
    ELSIF (LINK[89] AND WORD#16#0007) = WORD#0 THEN
      err := 22;
    ELSIF LENGTH > 128 THEN
      phase := 1;
    ELSE
      phase := 2;
    END_IF;
  END_IF;
  IF phase >= 1 AND phase <= 3 THEN
    mb(RUN := TRUE, SEND := FALSE, LINK := LINK);
    b := mb.BASE;
    IF mb.LOST THEN
      err := 20;
    ELSIF mb.ANSWERED AND mb.ERR <> 0 THEN
      err := mb.ERR;
      IF phase = 2 THEN
        R0 := LINK[b + 74];
        R1 := LINK[b + 75];
        R2 := LINK[b + 76];
        R3 := LINK[b + 77];
        R4 := LINK[b + 78];
        R5 := LINK[b + 79];
      END_IF;
    ELSIF mb.ANSWERED AND phase = 1 THEN
      offset := offset + 128;
      IF offset >= LENGTH THEN
        phase := 2;
      END_IF;
    ELSIF mb.ANSWERED THEN
      IF phase = 2 THEN
        R0 := LINK[b + 74];
        R1 := LINK[b + 75];
        R2 := LINK[b + 76];
        R3 := LINK[b + 77];
        R4 := LINK[b + 78];
        R5 := LINK[b + 79];
        want := FETCH_MAX;
        IF RLEN_AT >= 0 AND RLEN_AT <= 5 THEN
          rlen := LINK[b + 74 + RLEN_AT];
          IF WORD_TO_UINT(rlen) < want THEN
            want := WORD_TO_UINT(rlen);
          END_IF;
        ELSIF want > 128 THEN
          want := 128;
        END_IF;
        IF want > 1785 THEN
          want := 1785;
        END_IF;
      END_IF;
      cnt := UINT_TO_INT(want - GOT);
      IF cnt > 128 THEN
        cnt := 128;
      END_IF;
      FOR k := 0 TO cnt - 1 DO
        IF (k MOD 2) = 0 THEN
          DATA[UINT_TO_INT(GOT) + k] := WORD_TO_BYTE(SHR(LINK[b + 80 + k / 2], 8));
        ELSE
          DATA[UINT_TO_INT(GOT) + k] := WORD_TO_BYTE(LINK[b + 80 + k / 2]);
        END_IF;
      END_FOR;
      GOT := GOT + INT_TO_UINT(cnt);
      IF GOT >= want THEN
        fin := TRUE;
      ELSE
        phase := 3;
      END_IF;
    END_IF;
    IF err = 0 AND NOT fin AND mb.OWNED AND NOT mb.WAITING THEN
      IF phase = 1 OR (phase = 2 AND LENGTH <= 128) THEN
        cnt := UINT_TO_INT(LENGTH - offset);
        IF cnt > 128 THEN
          cnt := 128;
        END_IF;
        FOR k := 0 TO 63 DO
          LINK[b + 8 + k] := WORD#0;
        END_FOR;
        FOR k := 0 TO cnt - 1 DO
          IF (k MOD 2) = 0 THEN
            LINK[b + 8 + k / 2] := SHL(BYTE_TO_WORD(DATA[UINT_TO_INT(offset) + k]), 8);
          ELSE
            LINK[b + 8 + k / 2] := LINK[b + 8 + k / 2] OR BYTE_TO_WORD(DATA[UINT_TO_INT(offset) + k]);
          END_IF;
        END_FOR;
      END_IF;
      IF phase = 1 THEN
        mb(RUN := TRUE, SEND := TRUE, OP := 1, NET := 0, A0 := UINT_TO_WORD(offset), A1 := INT_TO_WORD(cnt),
           A2 := WORD#0, A3 := WORD#0, A4 := WORD#0, A5 := WORD#0, LINK := LINK);
      ELSIF phase = 2 THEN
        mb(RUN := TRUE, SEND := TRUE, OP := OP, NET := NET, A0 := A0, A1 := A1, A2 := A2, A3 := A3, A4 := A4,
           A5 := A5, LINK := LINK);
      ELSE
        mb(RUN := TRUE, SEND := TRUE, OP := 2, NET := 0, A0 := UINT_TO_WORD(GOT), A1 := WORD#0, A2 := WORD#0, A3 := WORD#0,
           A4 := WORD#0, A5 := WORD#0, LINK := LINK);
      END_IF;
    END_IF;
  END_IF;
  IF err <> 0 OR fin THEN
    phase := 4;
    DONE := fin;
    ERROR := err <> 0;
    ERROR_ID := err;
    mb(RUN := FALSE, LINK := LINK);
  END_IF;
  BUSY := phase >= 1 AND phase <= 3;
  prev := EXECUTE;
END_FUNCTION_BLOCK
