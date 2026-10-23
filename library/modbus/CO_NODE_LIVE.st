(*
 * CO_NODE_LIVE: TRUE while node NODE of CANopen master network NETWORK is
 * OPERATIONAL, from the bridge's live list of that network. FALSE without a
 * live list for the network or while the bridge is not reachable.
 *)
(*
 * LINK is the generated `canworks.link` (ARRAY[0..1279] OF WORD): the
 * bridge's blocks as canworks_in and canworks_out copy them from and to the
 * Modbus registers every scan, one word per register (high byte = the
 * bridge's even byte). Words: 0-3 status block, 4-6 control block, 7-13 SDO
 * request, 14-20 SDO response, 21 flags (bit 0 the bridge answers with this
 * program's map, 1 a control block, 2 SDO registers, 8 + n a live list for
 * network n), 22 control block owner, 23 SDO owner, 24 last instance number,
 * 25 + 8n .. 32 + 8n the live list of network n (n 0..7).
 *)
FUNCTION_BLOCK CO_NODE_LIVE
VAR_INPUT
  NETWORK : USINT;
  NODE : USINT;
END_VAR
VAR_OUTPUT
  LIVE : BOOL;
END_VAR
VAR_IN_OUT
  LINK : ARRAY[0..1279] OF WORD;
END_VAR
VAR
  byte_no : INT;
  word : WORD;
  bit_no : INT;
END_VAR
  LIVE := FALSE;
  IF (LINK[21] AND 16#0001) <> 0 AND NETWORK < 8 AND NODE >= 1 AND NODE <= 127 THEN
    IF (SHR(LINK[21], USINT_TO_UINT(NETWORK) + 8) AND 16#0001) <> 0 THEN
      byte_no := USINT_TO_INT(NODE) / 8;
      word := LINK[25 + USINT_TO_INT(NETWORK) * 8 + byte_no / 2];
      bit_no := USINT_TO_INT(NODE) MOD 8;
      IF byte_no MOD 2 = 0 THEN
        bit_no := bit_no + 8;
      END_IF;
      LIVE := (SHR(word, INT_TO_UINT(bit_no)) AND 16#0001) <> 0;
    END_IF;
  END_IF;
END_FUNCTION_BLOCK
