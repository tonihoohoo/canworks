(*
 * CW_RX: one receiver of the bridge's receive mailbox, for the receiving
 * blocks of this library (CAN_RECEIVE, J1939_RECEIVE, CO_RECV_EMCY).
 * While ENABLE is TRUE it keeps a receiver of KIND (1 CAN, 2 J1939, 3 EMCY)
 * open with FLAGS, DEPTH, ID and MASK (RX_OPEN through a request mailbox);
 * CHANGED closes it and opens it again. A call with NEXT delivers the next
 * record of this receiver in the current batch: NEW, its first word at
 * LINK[REC]. When the batch has no more of them the receiver's pending mark
 * is cleared, so the bridge can show the next batch. After an error whose
 * bit is set in RETRY (bit n for ERROR_ID n) it opens the receiver again on
 * the next call; 8 means the bridge closed it (link stop, stall, network
 * restart). ENABLE FALSE closes it (RX_CLOSE).
 *)
FUNCTION_BLOCK CW_RX
VAR_INPUT
  ENABLE : BOOL;
  CHANGED : BOOL;
  NEXT : BOOL;
  KIND : USINT;
  NETWORK : USINT;
  FLAGS : USINT;
  DEPTH : UINT;
  ID : UDINT;
  MASK : UDINT;
  RETRY : DWORD;
END_VAR
VAR_OUTPUT
  ACTIVE : BOOL;
  NEW : BOOL;
  REC : INT;
  ERROR : BOOL;
  ERROR_ID : UINT;
  SLOT : INT;
END_VAR
VAR_IN_OUT
  LINK : ARRAY[0..1279] OF WORD;
END_VAR
VAR
  mb : CW_MB_CALL;
  prev : BOOL;
  phase : USINT;           (* 0 closed, 1 opening, 2 open, 3 closing *)
  gen : WORD;
  tick0 : WORD;
  seq : WORD;
  pos : INT;
  pw : INT;
  bit : WORD;
  shown : WORD;
  hdr : WORD;
  size : INT;
  synced : BOOL;          (* the batch on show was built after the open *)
  fresh : BOOL;
  found : BOOL;
  err : UINT;
END_VAR
  NEW := FALSE;
  err := 0;
  IF ENABLE AND NOT prev THEN
    ERROR := FALSE;
    ERROR_ID := 0;
  END_IF;
  IF (LINK[21] AND 16#0001) = 0 AND phase <> 0 THEN
    (* The bridge ended every receiver when the link stopped. *)
    mb(RUN := FALSE, LINK := LINK);
    phase := 0;
    IF ENABLE THEN
      err := 20;
    END_IF;
  END_IF;
  IF phase = 2 THEN
    IF NOT synced THEN
      synced := ((LINK[724] - tick0) AND 16#8000) = 0;
    END_IF;
    fresh := synced;
    shown := SHR(LINK[725 + SLOT / 2], 8 * (1 - SLOT MOD 2)) AND 16#00FF;
    IF fresh AND shown <> gen THEN
      phase := 0;
      err := 8;
    ELSIF NOT ENABLE OR CHANGED THEN
      phase := 3;
    END_IF;
  END_IF;
  IF phase = 2 OR phase = 3 THEN
    pw := 104 - SLOT / 16;
    bit := SHL(WORD#1, SLOT MOD 16);
  END_IF;
  IF phase = 3 THEN
    LINK[pw] := LINK[pw] AND NOT bit;
  END_IF;
  IF phase = 0 AND ENABLE AND err = 0 AND
     NOT (ERROR AND (SHR(RETRY, UINT_TO_INT(ERROR_ID)) AND 16#00000001) = 0) THEN
    ERROR := FALSE;
    ERROR_ID := 0;
    IF (LINK[21] AND 16#0001) = 0 THEN
      err := 20;
    ELSIF (LINK[89] AND 16#0007) = 0 OR (LINK[89] AND 16#0010) = 0 THEN
      err := 22;
    ELSE
      phase := 1;
    END_IF;
  END_IF;
  IF phase = 1 OR phase = 3 THEN
    mb(RUN := TRUE, SEND := FALSE, LINK := LINK);
    IF mb.LOST THEN
      phase := 0;
      err := SEL(ENABLE, UINT#0, UINT#20);
    ELSIF mb.ANSWERED AND phase = 1 THEN
      IF mb.ERR <> 0 THEN
        err := mb.ERR;
        phase := 0;
      ELSE
        SLOT := WORD_TO_INT(LINK[mb.BASE + 74]);
        gen := LINK[mb.BASE + 75];
        tick0 := LINK[mb.BASE + 76];
        synced := FALSE;
        seq := 0;
        pos := 0;
        phase := 2;
      END_IF;
      mb(RUN := FALSE, LINK := LINK);
    ELSIF mb.ANSWERED THEN
      phase := 0;
      mb(RUN := FALSE, LINK := LINK);
    ELSIF mb.OWNED AND NOT mb.WAITING THEN
      IF phase = 1 THEN
        mb(RUN := TRUE, SEND := TRUE, OP := 8, NET := NETWORK,
           A0 := SHL(USINT_TO_WORD(KIND), 8) OR USINT_TO_WORD(FLAGS), A1 := UINT_TO_WORD(DEPTH),
           A2 := UDINT_TO_WORD(SHR(ID, 16)), A3 := UDINT_TO_WORD(ID),
           A4 := UDINT_TO_WORD(SHR(MASK, 16)), A5 := UDINT_TO_WORD(MASK), LINK := LINK);
      ELSE
        mb(RUN := TRUE, SEND := TRUE, OP := 9, NET := NETWORK, A0 := INT_TO_WORD(SLOT), A1 := 0, A2 := 0, A3 := 0,
           A4 := 0, A5 := 0, LINK := LINK);
      END_IF;
    END_IF;
  END_IF;
  IF phase = 2 AND NEXT THEN
    (* My records of the batch on show: only in a batch built after the open
       (its present bit set while the block is newer than the open) and while
       still pending. *)
    pw := 104 - SLOT / 16;
    bit := SHL(WORD#1, SLOT MOD 16);
    IF LINK[720] <> seq THEN
      seq := LINK[720];
      pos := 741;
    END_IF;
    IF NOT synced THEN
      synced := ((LINK[724] - tick0) AND 16#8000) = 0;
    END_IF;
    fresh := synced;
    IF fresh AND (LINK[722 - SLOT / 16] AND bit) <> 0 AND (LINK[pw] AND bit) <> 0 THEN
      found := FALSE;
      WHILE NOT found AND pos < 741 + WORD_TO_INT(LINK[723]) AND pos < 840 DO
        hdr := LINK[pos];
        size := 7;
        CASE WORD_TO_INT(SHR(hdr, 4) AND 16#000F) OF
          1: size := 14;
          2: size := 16;
          3: size := 12;
        END_CASE;
        IF WORD_TO_INT(SHR(hdr, 8)) = SLOT THEN
          found := TRUE;
          REC := pos;
          NEW := TRUE;
        END_IF;
        pos := pos + size;
      END_WHILE;
      IF NOT found THEN
        LINK[pw] := LINK[pw] AND NOT bit;
      END_IF;
    END_IF;
  END_IF;
  IF err <> 0 THEN
    ERROR := TRUE;
    ERROR_ID := err;
  END_IF;
  ACTIVE := phase = 2;
  prev := ENABLE;
END_FUNCTION_BLOCK
