(*
 * CAN_SEND_CYCLIC: the bridge sends one CAN frame (ID, EXTENDED, DLC bytes
 * of DATA) on network NETWORK every PERIOD (1 ms .. 60 s) while ENABLE is
 * TRUE. Changed DATA, DLC or PERIOD go to the bridge when they change; the
 * block must be called at least every second (its keepalive), or the bridge
 * stops the frame. ACTIVE while the job runs, COUNT frames sent. ERROR_ID
 * (docs/plc-library.md#frame-blocks): 1 the network is not running, 2 no
 * such network, 3 invalid input, 5 no free cyclic job, 7 the bus is off
 * (the job stays), 8 cancelled (the bridge stopped the job; it starts
 * again), 20 the bridge is not reachable, 22 the config has no request
 * mailbox or no cyclic jobs. After 1, 7, 8 and 20 it starts again by itself.
 *)
(*
 * LINK is the generated `canworks.link` (ARRAY[0..1279] OF WORD); the block uses a request mailbox of the bridge (`mailboxes` in the config); instances share
 * them in the order they started, and a cyclic job of the bridge's table (see
 * CW_LINK_SERVICE for the words).
 *)
FUNCTION_BLOCK CAN_SEND_CYCLIC
VAR_INPUT
  ENABLE : BOOL;
  NETWORK : USINT;
  ID : UDINT;
  EXTENDED : BOOL;
  DLC : USINT;
  PERIOD : TIME;
END_VAR
VAR_IN_OUT
  DATA : ARRAY[0..7] OF BYTE;
  LINK : ARRAY[0..1279] OF WORD;
END_VAR
VAR_OUTPUT
  ACTIVE : BOOL;
  COUNT : UDINT;
  ERROR : BOOL;
  ERROR_ID : UINT;
END_VAR
VAR
  mb : CW_MB_CALL;
  prev : BOOL;
  phase : USINT;           (* 0 off, 1 starting, 2 running, 3 updating, 4 stopping *)
  job : INT;
  gen : WORD;
  tick0 : WORD;
  sent : ARRAY[0..7] OF BYTE;
  sent_dlc : USINT;
  sent_ms : UDINT;
  ms : UDINT;
  changed : BOOL;
  t : INT;
  i : INT;
  err : UINT;
  fresh : BOOL;
END_VAR
  err := 0;
  ms := DWORD_TO_UDINT(TIME_TO_DWORD(PERIOD));
  IF ms > 65535 THEN
    ms := 65535;
  END_IF;
  IF ENABLE AND NOT prev THEN
    COUNT := 0;
    ERROR := FALSE;
    ERROR_ID := 0;
  END_IF;
  IF (LINK[21] AND WORD#16#0001) = WORD#0 AND phase <> 0 THEN
    mb(RUN := FALSE, LINK := LINK);
    phase := 0;
    IF ENABLE THEN
      err := 20;
    END_IF;
  END_IF;
  IF phase = 2 OR phase = 3 THEN
    LINK[128 + job] := UDINT_TO_WORD(WORD_TO_UDINT(LINK[128 + job]) + 1);
    t := 985 + 4 * job;
    fresh := (DINT_TO_WORD(WORD_TO_DINT(LINK[984]) - WORD_TO_DINT(tick0)) AND WORD#16#8000) = WORD#0;
    IF fresh AND LINK[t + 1] <> gen THEN
      mb(RUN := FALSE, LINK := LINK);
      phase := 0;
      err := 8;
    ELSIF fresh THEN
      COUNT := WORD_TO_UDINT(LINK[t + 2]) * 65536 + WORD_TO_UDINT(LINK[t + 3]);
      IF SHR(LINK[t], 8) = WORD#2 THEN
        ERROR := TRUE;
        ERROR_ID := WORD_TO_UINT(LINK[t] AND WORD#16#00FF);
      ELSIF ERROR AND ERROR_ID = 7 THEN
        ERROR := FALSE;
        ERROR_ID := 0;
      END_IF;
    END_IF;
  END_IF;
  IF (phase = 2 OR phase = 3) AND NOT ENABLE THEN
    phase := 4;
  END_IF;
  changed := DLC <> sent_dlc OR ms <> sent_ms;
  FOR i := 0 TO 7 DO
    IF DATA[i] <> sent[i] THEN
      changed := TRUE;
    END_IF;
  END_FOR;
  IF phase = 2 AND changed THEN
    phase := 3;
  END_IF;
  IF phase = 0 AND ENABLE AND err = 0 AND
     NOT (ERROR AND ERROR_ID <> 1 AND ERROR_ID <> 7 AND ERROR_ID <> 8 AND ERROR_ID <> 20) THEN
    ERROR := FALSE;
    ERROR_ID := 0;
    IF (LINK[21] AND WORD#16#0001) = WORD#0 THEN
      err := 20;
    ELSIF (LINK[89] AND WORD#16#0007) = WORD#0 OR (LINK[89] AND WORD#16#1F00) = WORD#0 THEN
      err := 22;
    ELSIF DLC > 8 THEN
      err := 3;
    ELSE
      phase := 1;
    END_IF;
  END_IF;
  IF phase = 1 OR phase = 3 OR phase = 4 THEN
    mb(RUN := TRUE, SEND := FALSE, LINK := LINK);
    IF mb.LOST THEN
      phase := 0;
      err := SEL(ENABLE, UINT#0, UINT#20);
    ELSIF mb.ANSWERED THEN
      IF phase = 4 THEN
        phase := 0;
      ELSIF mb.ERR <> 0 THEN
        err := mb.ERR;
        IF phase = 1 OR mb.ERR = 8 THEN
          phase := 0;
        ELSE
          phase := 2;
        END_IF;
      ELSE
        IF phase = 1 THEN
          job := WORD_TO_INT(LINK[mb.BASE + 74]);
          gen := LINK[mb.BASE + 75];
          tick0 := LINK[mb.BASE + 76];
          COUNT := 0;
        END_IF;
        phase := 2;
      END_IF;
      mb(RUN := FALSE, LINK := LINK);
    ELSIF mb.OWNED AND NOT mb.WAITING THEN
      IF phase = 4 THEN
        mb(RUN := TRUE, SEND := TRUE, OP := 7, NET := NETWORK, A0 := INT_TO_WORD(job), A1 := WORD#0, A2 := WORD#0, A3 := WORD#0,
           A4 := WORD#0, A5 := WORD#0, LINK := LINK);
      ELSE
        FOR i := 0 TO 3 DO
          LINK[mb.BASE + 8 + i] := SHL(BYTE_TO_WORD(DATA[2 * i]), 8) OR BYTE_TO_WORD(DATA[2 * i + 1]);
          sent[2 * i] := DATA[2 * i];
          sent[2 * i + 1] := DATA[2 * i + 1];
        END_FOR;
        sent_dlc := DLC;
        sent_ms := ms;
        mb(RUN := TRUE, SEND := TRUE, OP := 6, NET := NETWORK, A0 := SEL(phase = 1, INT_TO_WORD(job), WORD#16#FFFF),
           A1 := DWORD_TO_WORD(SHR(UDINT_TO_DWORD(ID), 16)), A2 := UDINT_TO_WORD(ID),
           A3 := SHL(SEL(EXTENDED, WORD#0, WORD#1), 8) OR USINT_TO_WORD(DLC), A4 := UDINT_TO_WORD(ms), A5 := WORD#0,
           LINK := LINK);
      END_IF;
    END_IF;
  END_IF;
  IF err <> 0 THEN
    ERROR := TRUE;
    ERROR_ID := err;
  END_IF;
  ACTIVE := phase = 2 OR phase = 3;
  prev := ENABLE;
END_FUNCTION_BLOCK
