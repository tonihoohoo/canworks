(*
 * J1939_DM_READ: the active trouble codes (DM1, PREVIOUS FALSE: the
 * bridge's latest DM1 from SOURCE, no bus traffic) or the previously active
 * ones (DM2, PREVIOUS TRUE: requested from SOURCE) of ECU SOURCE on J1939
 * network NETWORK: LAMPS and FLASH, COUNT codes in DTCS (up to 32), AGE of
 * the DM1. A rising edge of EXECUTE starts it; BUSY until the bridge has
 * an answer, then DONE or ERROR with ERROR_ID (docs/plc-library.md#j1939-blocks):
 * 1 the network is not running, 2 no such network, 3 invalid input,
 * 4 the network sends that PGN itself, 5 another DM2 read or clear for that
 * address is pending, 6 no answer within TIMEOUT, 7 the bus is off,
 * 8 cancelled, 9 no free job or receiver, 10 not a J1939 network, 11 the
 * network holds no address, 12 the destination answered NACK, 13 no DM1
 * from that source, 14 the transfer was aborted, 20 the bridge is not
 * reachable, 22 the config has no request mailbox.
 *)
(*
 * LINK is the generated `canworks.link` (ARRAY[0..1279] OF WORD); the block uses a request mailbox of the bridge (`mailboxes` in the config); instances share
 * them in the order they started (see
 * CW_LINK_SERVICE for the words).
 *)
FUNCTION_BLOCK J1939_DM_READ
VAR_INPUT
  EXECUTE : BOOL;
  NETWORK : USINT;
  SOURCE : USINT;
  PREVIOUS : BOOL;
  TIMEOUT : TIME;
END_VAR
VAR_IN_OUT
  DTCS : ARRAY[0..31] OF UDINT;
  LINK : ARRAY[0..1279] OF WORD;
END_VAR
VAR_OUTPUT
  BUSY : BOOL;
  DONE : BOOL;
  ERROR : BOOL;
  ERROR_ID : UINT;
  LAMPS : BYTE;
  FLASH : BYTE;
  COUNT : UINT;
  AGE : TIME;
END_VAR
VAR
  x : CW_REQUEST;
  prev : BOOL;
  refused : UINT;
  ms : UDINT;
  buf : ARRAY[0..1784] OF BYTE;
  was : BOOL;
  i : INT;
END_VAR
  ms := TIME_TO_UDINT(TIMEOUT);
  IF ms > 65535 THEN
    ms := 65535;
  END_IF;
  IF EXECUTE AND NOT prev AND NOT x.BUSY THEN
    refused := 0;
    IF SOURCE > 253 THEN
      refused := 3;
    END_IF;
  ELSIF NOT EXECUTE THEN
    refused := 0;
  END_IF;
  prev := EXECUTE;
  x(EXECUTE := EXECUTE AND refused = 0, OP := 13, NET := NETWORK, A0 := USINT_TO_WORD(SOURCE),
    A1 := SEL(PREVIOUS, WORD#0, WORD#1), A2 := UDINT_TO_WORD(ms), A3 := 0, A4 := 0, A5 := 0, LENGTH := 0,
    FETCH_MAX := 128, LINK := LINK, DATA := buf);
  BUSY := x.BUSY;
  DONE := x.DONE;
  ERROR := x.ERROR OR refused <> 0;
  ERROR_ID := SEL(refused <> 0, x.ERROR_ID, refused);
  IF x.DONE AND NOT was THEN
    LAMPS := WORD_TO_BYTE(SHR(x.R0, 8));
    FLASH := WORD_TO_BYTE(x.R0);
    COUNT := WORD_TO_UINT(x.R1);
    AGE := UDINT_TO_TIME(WORD_TO_UDINT(x.R2) * 65536 + WORD_TO_UDINT(x.R3));
    FOR i := 0 TO 31 DO
      DTCS[i] := SHL(BYTE_TO_UDINT(buf[4 * i]), 24) OR SHL(BYTE_TO_UDINT(buf[4 * i + 1]), 16) OR
                 SHL(BYTE_TO_UDINT(buf[4 * i + 2]), 8) OR BYTE_TO_UDINT(buf[4 * i + 3]);
    END_FOR;
  END_IF;
  was := x.DONE;
END_FUNCTION_BLOCK
