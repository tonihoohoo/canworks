(*
 * J1939_REQUEST: requests PGN from DESTINATION (255: every ECU, the first
 * answer counts) on J1939 network NETWORK and returns the answer: SOURCE,
 * LENGTH bytes in DATA (up to 1785), ACK_CODE of an acknowledgement. A rising edge of EXECUTE starts it; BUSY until the bridge has
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
FUNCTION_BLOCK J1939_REQUEST
VAR_INPUT
  EXECUTE : BOOL;
  NETWORK : USINT;
  PGN : UDINT;
  DESTINATION : USINT;
  TIMEOUT : TIME;
END_VAR
VAR_IN_OUT
  DATA : ARRAY[0..1784] OF BYTE;
  LINK : ARRAY[0..1279] OF WORD;
END_VAR
VAR_OUTPUT
  BUSY : BOOL;
  DONE : BOOL;
  ERROR : BOOL;
  ERROR_ID : UINT;
  SOURCE : USINT;
  LENGTH : UINT;
  ACK_CODE : USINT;
END_VAR
VAR
  x : CW_REQUEST;
  prev : BOOL;
  refused : UINT;
  ms : UDINT;
  was : BOOL;
END_VAR
  ms := DWORD_TO_UDINT(TIME_TO_DWORD(TIMEOUT));
  IF ms > 65535 THEN
    ms := 65535;
  END_IF;
  IF EXECUTE AND NOT prev AND NOT x.BUSY THEN
    refused := 0;
    ACK_CODE := 0;
  ELSIF NOT EXECUTE THEN
    refused := 0;
  END_IF;
  prev := EXECUTE;
  x(EXECUTE := EXECUTE AND refused = 0, OP := 12, NET := NETWORK, A0 := DWORD_TO_WORD(SHR(UDINT_TO_DWORD(PGN), 16)),
    A1 := UDINT_TO_WORD(PGN), A2 := USINT_TO_WORD(DESTINATION), A3 := UDINT_TO_WORD(ms), A4 := WORD#0, A5 := WORD#0,
    LENGTH := 0, RLEN_AT := 1, FETCH_MAX := 1785, LINK := LINK, DATA := DATA);
  BUSY := x.BUSY;
  DONE := x.DONE;
  ERROR := x.ERROR OR refused <> 0;
  ERROR_ID := SEL(refused <> 0, x.ERROR_ID, refused);
  IF (x.DONE OR x.ERROR) AND NOT was THEN
    ACK_CODE := WORD_TO_USINT(x.R2);
    IF x.DONE THEN
      SOURCE := WORD_TO_USINT(x.R0);
      LENGTH := WORD_TO_UINT(x.R1);
    END_IF;
  END_IF;
  was := x.DONE OR x.ERROR;
END_FUNCTION_BLOCK
