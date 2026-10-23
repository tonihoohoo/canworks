(*
 * CW_SDO_XFER: one SDO transfer through a request mailbox of the bridge,
 * for the SDO blocks of this library (CO_SDO_READ_BYTES and the others).
 * A rising edge of EXECUTE starts it. A write sends LENGTH bytes of DATA
 * (more than 128 go to the bridge first with STAGE requests); a read
 * answers RSIZE, the object's size, and fetches its first
 * MIN(RSIZE, FETCH_MAX, 1024) bytes into DATA (FETCH requests after the
 * first 128). KIND: 1 REAL, 2 STRING, 3 bytes; SIZE the REAL write's size.
 * ERROR_IDs as the bridge gives them (docs/plc-library.md#sdo-blocks) and
 * 6 invalid input, 7 a reply longer than MAX_SIZE, 20 the bridge is not
 * reachable, 22 the config has no request mailbox.
 *)
FUNCTION_BLOCK CW_SDO_XFER
VAR_INPUT
  EXECUTE : BOOL;
  WRITE : BOOL;
  NETWORK : USINT;
  NODE : USINT;
  INDEX : UINT;
  SUBINDEX : USINT;
  TIMEOUT : TIME;
  KIND : USINT;
  SIZE : USINT;
  LENGTH : UINT;
  MAX_SIZE : UDINT := 1024;
  FETCH_MAX : UINT := 1024;
END_VAR
VAR_OUTPUT
  BUSY : BOOL;
  DONE : BOOL;
  ERROR : BOOL;
  ERROR_ID : UINT;
  ABORT_CODE : UDINT;
  RSIZE : UDINT;
  GOT : UINT;
END_VAR
VAR_IN_OUT
  LINK : ARRAY[0..1279] OF WORD;
  DATA : ARRAY[0..1023] OF BYTE;
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
  ms : UDINT;
  err : UINT;
  fin : BOOL;
  op : USINT;
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
    ABORT_CODE := 0;
    RSIZE := 0;
    GOT := 0;
    offset := 0;
    IF (LINK[21] AND WORD#16#0001) = WORD#0 THEN
      err := 20;
    ELSIF (LINK[89] AND WORD#16#0007) = WORD#0 THEN
      err := 22;
    ELSIF NODE < 1 OR NODE > 127 OR (WRITE AND LENGTH > 1024) THEN
      err := 6;
    ELSIF WRITE AND LENGTH > 128 THEN
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
        ABORT_CODE := WORD_TO_UDINT(LINK[b + 76]) * 65536 + WORD_TO_UDINT(LINK[b + 77]);
      END_IF;
    ELSIF mb.ANSWERED AND phase = 1 THEN
      offset := offset + 128;
      IF offset >= LENGTH THEN
        phase := 2;
      END_IF;
    ELSIF mb.ANSWERED AND phase = 2 AND WRITE THEN
      fin := TRUE;
    ELSIF mb.ANSWERED THEN
      IF phase = 2 THEN
        RSIZE := WORD_TO_UDINT(LINK[b + 74]) * 65536 + WORD_TO_UDINT(LINK[b + 75]);
        want := FETCH_MAX;
        IF want > 1024 THEN
          want := 1024;
        END_IF;
        IF RSIZE < UINT_TO_UDINT(want) THEN
          want := UDINT_TO_UINT(RSIZE);
        END_IF;
      END_IF;
      IF phase = 2 AND RSIZE > MAX_SIZE THEN
        err := 7;
      ELSE
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
    END_IF;
    IF err = 0 AND NOT fin AND mb.OWNED AND NOT mb.WAITING THEN
      IF phase = 1 THEN
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
        mb(RUN := TRUE, SEND := TRUE, OP := 1, NET := 0, A0 := UINT_TO_WORD(offset), A1 := INT_TO_WORD(cnt),
           A2 := WORD#0, A3 := WORD#0, A4 := WORD#0, A5 := WORD#0, LINK := LINK);
      ELSIF phase = 2 THEN
        IF WRITE AND LENGTH <= 128 THEN
          FOR k := 0 TO 63 DO
            LINK[b + 8 + k] := WORD#0;
          END_FOR;
          FOR k := 0 TO UINT_TO_INT(LENGTH) - 1 DO
            IF (k MOD 2) = 0 THEN
              LINK[b + 8 + k / 2] := SHL(BYTE_TO_WORD(DATA[k]), 8);
            ELSE
              LINK[b + 8 + k / 2] := LINK[b + 8 + k / 2] OR BYTE_TO_WORD(DATA[k]);
            END_IF;
          END_FOR;
        END_IF;
        ms := DWORD_TO_UDINT(TIME_TO_DWORD(TIMEOUT));
        IF ms > 65535 THEN
          ms := 65535;
        END_IF;
        op := SEL(WRITE, USINT#3, USINT#4);
        mb(RUN := TRUE, SEND := TRUE, OP := op, NET := NETWORK,
           A0 := SHL(USINT_TO_WORD(NODE), 8) OR USINT_TO_WORD(SUBINDEX), A1 := UINT_TO_WORD(INDEX),
           A2 := SHL(USINT_TO_WORD(KIND), 8) OR USINT_TO_WORD(SIZE), A3 := UDINT_TO_WORD(ms),
           A4 := UINT_TO_WORD(LENGTH), A5 := WORD#0, LINK := LINK);
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
