(*
 * CW_LINK_SERVICE: the start of every scan for the blocks that use the
 * bridge's mailboxes (bridge-plc-blocks). The generated canworks_in calls it
 * once, after it copied the input words into LINK and before any user code:
 * it counts the scan, moves the lowest waiting mailbox ticket of the last
 * scan into place, frees a request mailbox whose owner was not called for
 * 100 scans and marks the receivers of a new receive batch pending. While
 * the bridge is not reachable it clears the requests and the
 * acknowledgement, so that a restarted bridge never runs an old request.
 *)
(*
 * The mailbox words of LINK (ARRAY[0..1279] OF WORD), after change 1's 0-88:
 * 89 flags (bits 0-2 request mailboxes, 4 receive mailbox, 5 network info,
 * 8-12 cyclic jobs), 90 scan counter, 91 last ticket, 92 lowest ticket
 * waiting in this scan, 93 the same of the last scan, 94-97 mailbox owners,
 * 98-101 owner stamps (scan counter), 102 receive batch seen, 103-104 the
 * receivers still pending (word 103 bits 31-16), 105 last batch taken,
 * 128 + j keepalive of cyclic job j, 144 + 144m request mailbox m (72
 * request words, then 72 response words), 720 the receive mailbox (120
 * words per receive block, 2 at most), 960 + 18n the info of network n, 1104
 * the cyclic job table.
 *)
FUNCTION_BLOCK CW_LINK_SERVICE
VAR_IN_OUT
  LINK : ARRAY[0..1279] OF WORD;
END_VAR
VAR
  m : INT;
END_VAR
  LINK[90] := UDINT_TO_WORD(WORD_TO_UDINT(LINK[90]) + 1);
  LINK[93] := LINK[92];
  LINK[92] := WORD#0;
  IF (LINK[21] AND WORD#16#0001) = WORD#0 THEN
    FOR m := 0 TO 3 DO
      LINK[144 + 144 * m + 1] := WORD#0;
      LINK[94 + m] := WORD#0;
    END_FOR;
    LINK[102] := WORD#0;
    LINK[103] := WORD#0;
    LINK[104] := WORD#0;
    LINK[105] := WORD#0;
    RETURN;
  END_IF;
  FOR m := 0 TO 3 DO
    IF LINK[94 + m] <> WORD#0 AND DINT_TO_WORD(WORD_TO_DINT(LINK[90]) - WORD_TO_DINT(LINK[98 + m])) > WORD#100 THEN
      LINK[94 + m] := WORD#0;
    END_IF;
  END_FOR;
  IF (LINK[89] AND WORD#16#0010) <> WORD#0 AND LINK[720] <> LINK[105] THEN
    LINK[105] := LINK[720];
    LINK[102] := LINK[720];
    LINK[103] := LINK[721];
    LINK[104] := LINK[722];
  END_IF;
END_FUNCTION_BLOCK
