(*
 * J1939_RECEIVE: receives the messages of PGN (ALL_PGNS: every PGN) on J1939
 * network NETWORK, from SOURCE when FILTER_SOURCE, sent to the canworks ECU
 * or broadcast (ALL_DESTINATIONS: to any address), through a receiver of
 * the bridge with a queue of DEPTH messages (0: 4, at most 32). ENABLE
 * opens it; changed filter inputs open it again. Each call gives at most one
 * message, oldest first: RECEIVED with RX_PGN, RX_SOURCE, RX_DESTINATION,
 * RX_PRIORITY, RX_LENGTH bytes in RX_DATA and TIMESTAMP (UTC microseconds).
 * A message longer than 8 bytes is read whole (RX_FETCH through a request
 * mailbox) before RECEIVED. QUEUED messages still wait in the bridge, OVERFLOW
 * the queue was full, DROPPED messages lost. ERROR_ID
 * (docs/plc-library.md#j1939-blocks): 1 the network is not running, 2 no
 * such network, 3 invalid input, 8 the bridge closed the receiver (it opens
 * again), 9 no free receiver, 10 not a J1939 network, 20 the bridge is not
 * reachable, 22 the config has no receive or request mailbox. After 1, 8,
 * 9 and 20 it opens again by itself.
 *)
(*
 * LINK is the generated `canworks.link` (ARRAY[0..1279] OF WORD); the block uses the bridge's receive mailbox and a request mailbox (see
 * CW_LINK_SERVICE for the words).
 *)
FUNCTION_BLOCK J1939_RECEIVE
VAR_INPUT
  ENABLE : BOOL;
  NETWORK : USINT;
  PGN : UDINT;
  ALL_PGNS : BOOL;
  SOURCE : USINT;
  FILTER_SOURCE : BOOL;
  ALL_DESTINATIONS : BOOL;
  DEPTH : UINT;
END_VAR
VAR_IN_OUT
  RX_DATA : ARRAY[0..1784] OF BYTE;
  LINK : ARRAY[0..1279] OF WORD;
END_VAR
VAR_OUTPUT
  ACTIVE : BOOL;
  RECEIVED : BOOL;
  RX_PGN : UDINT;
  RX_SOURCE : USINT;
  RX_DESTINATION : USINT;
  RX_PRIORITY : USINT;
  RX_LENGTH : UINT;
  TIMESTAMP : ULINT;
  QUEUED : UINT;
  OVERFLOW : BOOL;
  DROPPED : UDINT;
  ERROR : BOOL;
  ERROR_ID : UINT;
END_VAR
VAR
  rx : CW_RX;
  fetch : CW_REQUEST;
  prev : BOOL;
  was_active : BOOL;
  fetching : BOOL;
  last_drop : WORD;
  src : USINT;
  flags : USINT;
  o_pgn : UDINT;
  o_source : USINT;
  o_flags : USINT;
  o_depth : UINT;
  changed : BOOL;
  rec : INT;
  i : INT;
  ferr : UINT;
END_VAR
  RECEIVED := FALSE;
  ferr := 0;
  IF ENABLE AND NOT prev THEN
    QUEUED := 0;
    OVERFLOW := FALSE;
    DROPPED := 0;
  END_IF;
  prev := ENABLE;
  src := SEL(FILTER_SOURCE, USINT#255, SOURCE);
  flags := SEL(ALL_PGNS, USINT#0, USINT#1) + SEL(ALL_DESTINATIONS, USINT#0, USINT#2);
  changed := rx.ACTIVE AND (PGN <> o_pgn OR src <> o_source OR flags <> o_flags OR DEPTH <> o_depth);
  IF NOT rx.ACTIVE THEN
    o_pgn := PGN;
    o_source := src;
    o_flags := flags;
    o_depth := DEPTH;
  END_IF;
  IF fetching THEN
    fetch(EXECUTE := TRUE, OP := 10, NET := NETWORK, A0 := INT_TO_WORD(rx.SLOT), A1 := WORD#0, A2 := WORD#0, A3 := WORD#0, A4 := WORD#0,
          A5 := WORD#0, LENGTH := 0, RLEN_AT := 0, FETCH_MAX := 1785, LINK := LINK, DATA := RX_DATA);
    IF fetch.DONE THEN
      fetching := FALSE;
      RECEIVED := TRUE;
      RX_LENGTH := fetch.GOT;
    ELSIF fetch.ERROR THEN
      fetching := FALSE;
      ferr := fetch.ERROR_ID;
    END_IF;
    IF NOT fetching THEN
      fetch(EXECUTE := FALSE, LINK := LINK, DATA := RX_DATA);
    END_IF;
  END_IF;
  rx(ENABLE := ENABLE, CHANGED := changed, NEXT := NOT fetching AND NOT RECEIVED, KIND := 2, NETWORK := NETWORK,
     FLAGS := flags, DEPTH := DEPTH, ID := PGN, MASK := USINT_TO_UDINT(src), RETRY := DWORD#16#00100302,
     LINK := LINK);
  IF rx.ACTIVE AND NOT was_active THEN
    last_drop := WORD#0;
  END_IF;
  was_active := rx.ACTIVE;
  IF rx.RECEIVED THEN
    rec := rx.REC;
    QUEUED := WORD_TO_UINT(LINK[rec + 1]);
    DROPPED := DROPPED + WORD_TO_UDINT(DINT_TO_WORD(WORD_TO_DINT(LINK[rec + 2]) - WORD_TO_DINT(last_drop)));
    last_drop := LINK[rec + 2];
    OVERFLOW := (LINK[rec] AND WORD#16#0004) <> WORD#0;
    TIMESTAMP := LWORD_TO_ULINT(SHL(WORD_TO_LWORD(LINK[rec + 3]), 48) OR SHL(WORD_TO_LWORD(LINK[rec + 4]), 32) OR
                 SHL(WORD_TO_LWORD(LINK[rec + 5]), 16) OR WORD_TO_LWORD(LINK[rec + 6]));
    RX_PGN := WORD_TO_UDINT(LINK[rec + 7]) * 65536 + WORD_TO_UDINT(LINK[rec + 8]);
    RX_SOURCE := WORD_TO_USINT(SHR(LINK[rec + 9], 8));
    RX_DESTINATION := WORD_TO_USINT(LINK[rec + 9] AND WORD#16#00FF);
    RX_PRIORITY := WORD_TO_USINT(LINK[rec + 10]);
    RX_LENGTH := WORD_TO_UINT(LINK[rec + 11]);
    IF (LINK[rec] AND WORD#16#0001) <> WORD#0 THEN
      (* Longer than 8 bytes: read it whole first. *)
      fetching := TRUE;
      fetch(EXECUTE := TRUE, OP := 10, NET := NETWORK, A0 := INT_TO_WORD(rx.SLOT), A1 := WORD#0, A2 := WORD#0, A3 := WORD#0,
            A4 := WORD#0, A5 := WORD#0, LENGTH := 0, RLEN_AT := 0, FETCH_MAX := 1785, LINK := LINK, DATA := RX_DATA);
    ELSE
      RECEIVED := TRUE;
      FOR i := 0 TO 3 DO
        RX_DATA[2 * i] := WORD_TO_BYTE(SHR(LINK[rec + 12 + i], 8));
        RX_DATA[2 * i + 1] := WORD_TO_BYTE(LINK[rec + 12 + i]);
      END_FOR;
    END_IF;
  END_IF;
  IF NOT rx.ACTIVE AND fetching THEN
    fetching := FALSE;
    fetch(EXECUTE := FALSE, LINK := LINK, DATA := RX_DATA);
  END_IF;
  ACTIVE := rx.ACTIVE;
  ERROR := rx.ERROR OR ferr <> 0;
  ERROR_ID := SEL(ferr <> 0, rx.ERROR_ID, ferr);
END_FUNCTION_BLOCK
