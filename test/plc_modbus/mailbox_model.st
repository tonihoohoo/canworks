(*
 * The bridge's mailboxes for the block tests (test/plc_modbus/run.sh),
 * working on the blocks' LINK words directly (the places CW_LINK_SERVICE
 * describes): one call is one Modbus poll round of the bridge. Mirrors
 * plugin/src/bridge/mailboxes.cpp: a request runs when its counter changes
 * (an operation answers busy for one round, then done), the response echoes
 * the counter; STAGE and FETCH move data in 128-byte parts; receivers get
 * records in batches the program acknowledges; info and the cyclic table
 * are refreshed every round. Networks 0 and 1 exist. The bus is a set of
 * fixed answers:
 *   SDO node 98 aborts with 16#06020000, node 99 times out (2); 0x1008 the
 *   text "Valve block 24 V", 0x2000 600 bytes (byte i = i MOD 251), 0x2001
 *   300 bytes 'A' without a NUL, 0x6000 REAL32 1.5, 0x6001 REAL64 -2.25,
 *   0x6002 5 bytes, any other 16#12345600 + node (4 bytes);
 *   J1939 requests: PGN 65282 answers 40 bytes (i + 1), 65000 300 bytes
 *   (i MOD 256), 59999 a NACK (12, ACK_CODE 1), others 8 bytes (i);
 *   DM1/DM2 of any source but 77 (13): lamps 16#44, flash 16#04, codes
 *   16#00012304 and 16#0005A1FF, age 1500 ms;
 *   FIND_ECU knows one ECU, NAME 16#A00000000000ABCD at 16#33.
 * Messages come in with INJ_CAN, INJ_J1939, INJ_EMCY (INJ_RESTART: a new
 * CANopen session record); HOLD keeps them waiting for one batch; CLOSE_SLOT
 * closes a receiver as a stall would.
 * STruC++'s test runner does not copy a source block's in-out back, so a
 * test writes `link := bridge.LINK;` after each call.
 *)
FUNCTION_BLOCK MailboxModel
VAR_INPUT
  INJ_CAN : BOOL;
  INJ_J1939 : BOOL;
  INJ_EMCY : BOOL;
  INJ_RESTART : BOOL;
  INJ_ID : UDINT;
  INJ_EXT : BOOL;
  INJ_DLC : USINT := 8;
  INJ_LEN : UINT := 8;
  INJ_SRC : USINT;
  INJ_NODE : USINT;
  INJ_CODE : WORD;
  INJ_B0 : BYTE;
  CLOSE_SLOT : INT := -1;
  NO_J1939 : BOOL;
  HOLD : BOOL;           (* no new batch this round *)
  SKIP_MS : WORD;        (* extra milliseconds on the bridge's clock this round *)
  RX_BLOCKS : INT := 1;  (* receive_blocks: 95 record words, 215 with 2 *)
END_VAR
VAR_OUTPUT
  TX_COUNT : INT;
  TX_ID : UDINT;
  TX_DLC : WORD;
  TX_FLAGS : WORD;
  TX_B0 : BYTE;
  STAGES : INT;
  FETCHES : INT;
  REQUESTS : INT;
  W_LEN : UINT;
  W_KIND : WORD;
  W_SIZE : WORD;
  W_INDEX : WORD;
  J_PGN : UDINT;
  J_DEST : WORD;
  J_PRIO : WORD;
  J_LEN : UINT;
  J_COUNT : INT;
  DM_CLEARED : WORD;
  CYC_SETS : INT;
  CYC_STOPS : INT;
  STALLS : INT;
  OPEN_RX : INT;
END_VAR
VAR_IN_OUT
  LINK : ARRAY[0..1279] OF WORD;
END_VAR
VAR
  tick : WORD := 16#1000;
  seen : ARRAY[0..3] OF WORD;
  busy : ARRAY[0..3] OF INT;      (* rounds left before a running operation ends *)
  staged : ARRAY[0..7139] OF BYTE;
  staged_len : ARRAY[0..3] OF UINT;
  result : ARRAY[0..7139] OF BYTE;
  result_len : ARRAY[0..3] OF UINT;
  w_data : ARRAY[0..1784] OF BYTE;
  j_data : ARRAY[0..1784] OF BYTE;
  r : ARRAY[0..23] OF WORD;          (* results of the 4 mailboxes, 6 each *)
  st : ARRAY[0..3] OF WORD;          (* state << 8 | error *)
  rx_on : ARRAY[0..31] OF BOOL;
  rx_kind : ARRAY[0..31] OF WORD;
  rx_id : ARRAY[0..31] OF UDINT;
  rx_mask : ARRAY[0..31] OF UDINT;
  rx_flags : ARRAY[0..31] OF WORD;
  rx_gen : ARRAY[0..31] OF WORD;
  rx_drop : ARRAY[0..31] OF WORD;
  next_gen : WORD := 1;
  held : ARRAY[0..1784] OF BYTE;
  held_len : UINT;
  held_slot : INT := -1;
  (* Waiting records: receiver, kind, id/PGN/node, length, first byte, source, code, flags. *)
  q_n : INT;
  q_slot : ARRAY[0..63] OF INT;
  q_kind : ARRAY[0..63] OF WORD;
  q_id : ARRAY[0..63] OF UDINT;
  q_len : ARRAY[0..63] OF UINT;
  q_b0 : ARRAY[0..63] OF BYTE;
  q_src : ARRAY[0..63] OF WORD;
  q_code : ARRAY[0..63] OF WORD;
  q_flags : ARRAY[0..63] OF WORD;
  q_ext : ARRAY[0..63] OF BOOL;
  seq : WORD := 16#4000;
  present : DWORD;
  used : INT;
  acked : BOOL := TRUE;
  shown_rounds : INT;
  words : ARRAY[0..214] OF WORD;
  job_on : ARRAY[0..15] OF BOOL;
  job_gen : ARRAY[0..15] OF WORD;
  job_count : ARRAY[0..15] OF UDINT;
  job_keep : ARRAY[0..15] OF WORD;
  job_idle : ARRAY[0..15] OF INT;
  job_data : ARRAY[0..15] OF WORD;
  info_count : WORD;
  m : INT;
  n : INT;
  i : INT;
  k : INT;
  b : INT;
  op : WORD;
  net : WORD;
  len : UINT;
  slot : INT;
  jobs : INT;
  pending : DWORD;
  taken_long : DWORD;
  size : INT;
  room : BOOL;
  batch_tick : WORD;     (* the batch time's low word *)
  bits : DWORD;
END_VAR
  tick := tick + 10 + SKIP_MS;
  n := WORD_TO_INT(LINK[89] AND 16#0007);
  jobs := WORD_TO_INT(SHR(LINK[89], 8) AND 16#001F);
  (* ---- messages arriving on the bus ---- *)
  FOR slot := 0 TO 31 DO
    IF rx_on[slot] AND q_n < 64 THEN
      room := FALSE;
      IF INJ_CAN AND rx_kind[slot] = 1 AND (INJ_ID AND rx_mask[slot]) = (rx_id[slot] AND rx_mask[slot])
         AND INJ_EXT = ((rx_flags[slot] AND 16#0001) <> 0) THEN
        room := TRUE;
        q_kind[q_n] := 1;
        q_id[q_n] := INJ_ID;
        q_len[q_n] := USINT_TO_UINT(INJ_DLC);
      ELSIF INJ_J1939 AND rx_kind[slot] = 2 AND ((rx_flags[slot] AND 16#0001) <> 0 OR INJ_ID = rx_id[slot])
            AND (rx_mask[slot] = 255 OR USINT_TO_UDINT(INJ_SRC) = rx_mask[slot]) THEN
        room := TRUE;
        q_kind[q_n] := 2;
        q_id[q_n] := INJ_ID;
        q_len[q_n] := INJ_LEN;
      ELSIF (INJ_EMCY OR INJ_RESTART) AND rx_kind[slot] = 3 AND (rx_mask[slot] = 0 OR USINT_TO_UDINT(INJ_NODE) = rx_mask[slot]) THEN
        room := TRUE;
        q_kind[q_n] := 3;
        q_id[q_n] := USINT_TO_UDINT(INJ_NODE);
        q_len[q_n] := 5;
      END_IF;
      IF room THEN
        q_slot[q_n] := slot;
        q_b0[q_n] := INJ_B0;
        q_src[q_n] := USINT_TO_WORD(INJ_SRC);
        q_code[q_n] := INJ_CODE;
        q_ext[q_n] := INJ_EXT;
        q_flags[q_n] := SEL(INJ_RESTART, WORD#0, WORD#2);
        q_n := q_n + 1;
      END_IF;
    END_IF;
  END_FOR;
  IF CLOSE_SLOT >= 0 AND CLOSE_SLOT < 32 THEN
    rx_on[CLOSE_SLOT] := FALSE;
    present := present AND NOT SHL(DWORD#1, CLOSE_SLOT);
  END_IF;
  (* One message per call that asks for it: the inputs keep their values. *)
  INJ_CAN := FALSE;
  INJ_J1939 := FALSE;
  INJ_EMCY := FALSE;
  INJ_RESTART := FALSE;
  CLOSE_SLOT := -1;
  (* ---- request mailboxes ---- *)
  FOR m := 0 TO n - 1 DO
    b := 144 + 144 * m;
    IF busy[m] > 0 THEN
      busy[m] := busy[m] - 1;
      IF busy[m] = 0 THEN
        st[m] := SHL(WORD#2, 8) OR (st[m] AND 16#00FF);
        IF (st[m] AND 16#00FF) <> 0 THEN
          st[m] := SHL(WORD#3, 8) OR (st[m] AND 16#00FF);
        END_IF;
      END_IF;
    ELSIF LINK[b] <> seen[m] THEN
      seen[m] := LINK[b];
      REQUESTS := REQUESTS + 1;
      op := SHR(LINK[b + 1], 8);
      net := LINK[b + 1] AND 16#00FF;
      FOR i := 0 TO 5 DO
        r[6 * m + i] := 0;
      END_FOR;
      st[m] := SHL(WORD#2, 8);
      IF op = 0 THEN
        st[m] := 0;
      ELSIF op = 1 THEN
        (* STAGE *)
        STAGES := STAGES + 1;
        k := WORD_TO_INT(LINK[b + 2]);
        len := WORD_TO_UINT(LINK[b + 3]);
        FOR i := 0 TO UINT_TO_INT(len) - 1 DO
          staged[1785 * m + k + i] := WORD_TO_BYTE(SHR(LINK[b + 8 + i / 2], 8 * (1 - i MOD 2)));
        END_FOR;
        IF UINT_TO_INT(staged_len[m]) < k + UINT_TO_INT(len) THEN
          staged_len[m] := INT_TO_UINT(k + UINT_TO_INT(len));
        END_IF;
      ELSIF op = 2 THEN
        (* FETCH *)
        FETCHES := FETCHES + 1;
        k := WORD_TO_INT(LINK[b + 2]);
        r[6 * m] := UINT_TO_WORD(result_len[m]);
        FOR i := 0 TO 127 DO
          IF k + i < UINT_TO_INT(result_len[m]) THEN
            bits := BYTE_TO_DWORD(result[1785 * m + k + i]);
          ELSE
            bits := 0;
          END_IF;
          IF i MOD 2 = 0 THEN
            LINK[b + 80 + i / 2] := SHL(DWORD_TO_WORD(bits), 8);
          ELSE
            LINK[b + 80 + i / 2] := LINK[b + 80 + i / 2] OR DWORD_TO_WORD(bits);
          END_IF;
        END_FOR;
      ELSIF net > 1 AND op <> 9 AND op <> 7 THEN
        st[m] := SHL(WORD#3, 8) OR SEL(op = 3 OR op = 4, WORD#2, WORD#6);
      ELSE
        result_len[m] := 0;
        CASE WORD_TO_INT(op) OF
          3: (* SDO_READ *)
            k := WORD_TO_INT(SHR(LINK[b + 2], 8));
            busy[m] := 1;
            IF k = 98 THEN
              st[m] := 1;
              r[6 * m + 2] := 16#0602;
            ELSIF k = 99 THEN
              st[m] := 2;
              r[6 * m + 2] := 16#0504;
              busy[m] := 3;
            ELSIF LINK[b + 3] = 16#1008 THEN
              len := 16;
              FOR i := 0 TO 15 DO
                result[1785 * m + i] := 32;
              END_FOR;
              result[1785 * m] := 86;  result[1785 * m + 1] := 97;  result[1785 * m + 2] := 108;
              result[1785 * m + 3] := 118; result[1785 * m + 4] := 101; result[1785 * m + 6] := 98;
              result[1785 * m + 7] := 108; result[1785 * m + 8] := 111; result[1785 * m + 9] := 99;
              result[1785 * m + 10] := 107; result[1785 * m + 12] := 50; result[1785 * m + 13] := 52;
              result[1785 * m + 15] := 86;
            ELSIF LINK[b + 3] = 16#2000 THEN
              len := 600;
              FOR i := 0 TO 599 DO
                result[1785 * m + i] := INT_TO_BYTE(i MOD 251);
              END_FOR;
            ELSIF LINK[b + 3] = 16#2001 THEN
              len := 300;
              FOR i := 0 TO 299 DO
                result[1785 * m + i] := 65;
              END_FOR;
            ELSIF LINK[b + 3] = 16#6000 THEN
              len := 4;
              result[1785 * m] := 0; result[1785 * m + 1] := 0;
              result[1785 * m + 2] := 16#C0; result[1785 * m + 3] := 16#3F;
            ELSIF LINK[b + 3] = 16#6001 THEN
              len := 8;
              FOR i := 0 TO 5 DO
                result[1785 * m + i] := 0;
              END_FOR;
              result[1785 * m + 6] := 16#02; result[1785 * m + 7] := 16#C0;
            ELSIF LINK[b + 3] = 16#6002 THEN
              len := 5;
            ELSE
              len := 4;
              result[1785 * m] := INT_TO_BYTE(k);
              result[1785 * m + 1] := 16#56;
              result[1785 * m + 2] := 16#34;
              result[1785 * m + 3] := 16#12;
            END_IF;
            IF (st[m] AND 16#00FF) = 0 THEN
              result_len[m] := len;
              r[6 * m + 1] := UINT_TO_WORD(len);
            END_IF;
          4: (* SDO_WRITE *)
            len := WORD_TO_UINT(LINK[b + 6]);
            IF len > 128 AND staged_len[m] < len THEN
              st[m] := 6;
            ELSE
              W_LEN := len;
              W_KIND := SHR(LINK[b + 4], 8);
              W_SIZE := LINK[b + 4] AND 16#00FF;
              W_INDEX := LINK[b + 3];
              FOR i := 0 TO UINT_TO_INT(len) - 1 DO
                IF len > 128 THEN
                  w_data[i] := staged[1785 * m + i];
                ELSE
                  w_data[i] := WORD_TO_BYTE(SHR(LINK[b + 8 + i / 2], 8 * (1 - i MOD 2)));
                END_IF;
              END_FOR;
              busy[m] := 1;
            END_IF;
            staged_len[m] := 0;
          5: (* CAN_SEND *)
            TX_COUNT := TX_COUNT + 1;
            TX_ID := WORD_TO_UDINT(LINK[b + 2]) * 65536 + WORD_TO_UDINT(LINK[b + 3]);
            TX_FLAGS := SHR(LINK[b + 4], 8);
            TX_DLC := LINK[b + 4] AND 16#00FF;
            TX_B0 := WORD_TO_BYTE(SHR(LINK[b + 8], 8));
            busy[m] := 1;
          6: (* CYCLIC_SET *)
            k := WORD_TO_INT(LINK[b + 2]);
            IF jobs = 0 THEN
              st[m] := 5;
            ELSIF LINK[b + 6] = 0 OR WORD_TO_UINT(LINK[b + 6]) > 60000 THEN
              st[m] := 3;
            ELSIF LINK[b + 2] = 16#FFFF THEN
              k := -1;
              FOR i := jobs - 1 TO 0 BY -1 DO
                IF NOT job_on[i] THEN
                  k := i;
                END_IF;
              END_FOR;
              IF k < 0 THEN
                st[m] := 5;
              ELSE
                job_on[k] := TRUE;
                job_gen[k] := next_gen;
                next_gen := next_gen + 1;
                job_count[k] := 0;
                job_keep[k] := LINK[128 + k];
                job_idle[k] := 0;
                job_data[k] := LINK[b + 8];
                CYC_SETS := CYC_SETS + 1;
                r[6 * m] := INT_TO_WORD(k);
                r[6 * m + 1] := job_gen[k];
                r[6 * m + 2] := tick;
              END_IF;
            ELSIF k >= jobs OR NOT job_on[k] THEN
              st[m] := 8;
            ELSE
              job_data[k] := LINK[b + 8];
              CYC_SETS := CYC_SETS + 1;
              r[6 * m] := INT_TO_WORD(k);
              r[6 * m + 1] := job_gen[k];
              r[6 * m + 2] := tick;
            END_IF;
          7: (* CYCLIC_STOP *)
            k := WORD_TO_INT(LINK[b + 2]);
            IF k < jobs THEN
              job_on[k] := FALSE;
            END_IF;
            CYC_STOPS := CYC_STOPS + 1;
          8: (* RX_OPEN *)
            IF (LINK[89] AND 16#0010) = 0 THEN
              st[m] := 3;
            ELSE
              k := -1;
              FOR i := 31 TO 0 BY -1 DO
                IF NOT rx_on[i] THEN
                  k := i;
                END_IF;
              END_FOR;
              IF k < 0 THEN
                st[m] := 5;
              ELSE
                rx_on[k] := TRUE;
                rx_kind[k] := SHR(LINK[b + 2], 8);
                rx_flags[k] := LINK[b + 2] AND 16#00FF;
                rx_id[k] := WORD_TO_UDINT(LINK[b + 4]) * 65536 + WORD_TO_UDINT(LINK[b + 5]);
                rx_mask[k] := WORD_TO_UDINT(LINK[b + 6]) * 65536 + WORD_TO_UDINT(LINK[b + 7]);
                rx_gen[k] := next_gen;
                rx_drop[k] := 0;
                next_gen := next_gen + 1;
                r[6 * m] := INT_TO_WORD(k);
                r[6 * m + 1] := rx_gen[k];
                r[6 * m + 2] := tick;
              END_IF;
            END_IF;
          9: (* RX_CLOSE *)
            k := WORD_TO_INT(LINK[b + 2]);
            IF k < 32 THEN
              rx_on[k] := FALSE;
              present := present AND NOT SHL(DWORD#1, k);
            END_IF;
          10: (* RX_FETCH *)
            k := WORD_TO_INT(LINK[b + 2]);
            IF k <> held_slot OR NOT rx_on[k] THEN
              st[m] := 8;
            ELSE
              result_len[m] := held_len;
              FOR i := 0 TO UINT_TO_INT(held_len) - 1 DO
                result[1785 * m + i] := held[i];
              END_FOR;
              r[6 * m] := UINT_TO_WORD(held_len);
            END_IF;
          11: (* J1939_SEND *)
            len := WORD_TO_UINT(LINK[b + 5]);
            IF len > 128 AND staged_len[m] < len THEN
              st[m] := 3;
            ELSE
              J_PGN := WORD_TO_UDINT(LINK[b + 2]) * 65536 + WORD_TO_UDINT(LINK[b + 3]);
              J_DEST := SHR(LINK[b + 4], 8);
              J_PRIO := LINK[b + 4] AND 16#00FF;
              J_LEN := len;
              J_COUNT := J_COUNT + 1;
              FOR i := 0 TO UINT_TO_INT(len) - 1 DO
                IF len > 128 THEN
                  j_data[i] := staged[1785 * m + i];
                ELSE
                  j_data[i] := WORD_TO_BYTE(SHR(LINK[b + 8 + i / 2], 8 * (1 - i MOD 2)));
                END_IF;
              END_FOR;
              busy[m] := 1;
            END_IF;
            staged_len[m] := 0;
          12: (* J1939_REQUEST *)
            bits := WORD_TO_DWORD(LINK[b + 2]) * 65536 + WORD_TO_DWORD(LINK[b + 3]);
            busy[m] := 1;
            IF bits = 59999 THEN
              st[m] := 12;
              r[6 * m + 2] := 1;
            ELSE
              IF bits = 65282 THEN
                len := 40;
              ELSIF bits = 65000 THEN
                len := 300;
              ELSE
                len := 8;
              END_IF;
              FOR i := 0 TO UINT_TO_INT(len) - 1 DO
                IF bits = 65282 THEN
                  result[1785 * m + i] := INT_TO_BYTE(i + 1);
                ELSE
                  result[1785 * m + i] := INT_TO_BYTE(i MOD 256);
                END_IF;
              END_FOR;
              result_len[m] := len;
              r[6 * m] := SEL(LINK[b + 4] < 254, WORD#16#21, LINK[b + 4]);
              r[6 * m + 1] := UINT_TO_WORD(len);
            END_IF;
          13: (* DM_READ *)
            busy[m] := 1;
            IF LINK[b + 2] = 77 THEN
              st[m] := 13;
            ELSE
              r[6 * m] := 16#4404;
              r[6 * m + 1] := 2;
              r[6 * m + 3] := 1500;
              result_len[m] := 128;
              FOR i := 0 TO 127 DO
                result[1785 * m + i] := 0;
              END_FOR;
              result[1785 * m + 1] := 16#01; result[1785 * m + 2] := 16#23; result[1785 * m + 3] := 16#04;
              result[1785 * m + 5] := 16#05; result[1785 * m + 6] := 16#A1; result[1785 * m + 7] := 16#FF;
            END_IF;
          14: (* DM_CLEAR *)
            DM_CLEARED := LINK[b + 2];
            busy[m] := 1;
          15: (* FIND_ECU: NAME 16#A00000000000ABCD at 16#33 *)
            bits := 0;
            FOR i := 0 TO 3 DO
              (* (NAME xor known) and MASK, word by word *)
              bits := bits OR WORD_TO_DWORD((LINK[b + 8 + i] XOR SEL(i = 0, SEL(i = 3, WORD#0, WORD#16#ABCD), WORD#16#A000))
                                            AND LINK[b + 12 + i]);
            END_FOR;
            IF bits = 0 THEN
              r[6 * m] := 1;
              r[6 * m + 1] := 16#33;
              r[6 * m + 2] := 1;
              result_len[m] := 8;
              result[1785 * m] := 16#A0;
              FOR i := 1 TO 5 DO
                result[1785 * m + i] := 0;
              END_FOR;
              result[1785 * m + 6] := 16#AB;
              result[1785 * m + 7] := 16#CD;
            END_IF;
        ELSE
          st[m] := 3;
        END_CASE;
        IF busy[m] > 0 THEN
          (* busy now, the answer (st) shows when busy runs out *)
          st[m] := SHL(WORD#1, 8) OR (st[m] AND 16#00FF);
        ELSIF (st[m] AND 16#00FF) <> 0 THEN
          st[m] := SHL(WORD#3, 8) OR (st[m] AND 16#00FF);
        END_IF;
        IF op <> 10 THEN
          FOR i := 0 TO 127 DO
            IF i < UINT_TO_INT(result_len[m]) THEN
              bits := BYTE_TO_DWORD(result[1785 * m + i]);
            ELSE
              bits := 0;
            END_IF;
            IF i MOD 2 = 0 THEN
              LINK[b + 80 + i / 2] := SHL(DWORD_TO_WORD(bits), 8);
            ELSE
              LINK[b + 80 + i / 2] := LINK[b + 80 + i / 2] OR DWORD_TO_WORD(bits);
            END_IF;
          END_FOR;
        ELSE
          FOR i := 0 TO 127 DO
            IF i < UINT_TO_INT(held_len) THEN
              bits := BYTE_TO_DWORD(held[i]);
            ELSE
              bits := 0;
            END_IF;
            IF i MOD 2 = 0 THEN
              LINK[b + 80 + i / 2] := SHL(DWORD_TO_WORD(bits), 8);
            ELSE
              LINK[b + 80 + i / 2] := LINK[b + 80 + i / 2] OR DWORD_TO_WORD(bits);
            END_IF;
          END_FOR;
        END_IF;
      END_IF;
    END_IF;
    (* the response *)
    LINK[b + 72] := seen[m];
    LINK[b + 73] := st[m];
    IF SHR(st[m], 8) = 1 THEN
      FOR i := 0 TO 5 DO
        LINK[b + 74 + i] := 0;
      END_FOR;
    ELSE
      FOR i := 0 TO 5 DO
        LINK[b + 74 + i] := r[6 * m + i];
      END_FOR;
    END_IF;
  END_FOR;
  (* ---- receive mailbox ---- *)
  IF (LINK[89] AND 16#0010) <> 0 THEN
    IF NOT acked THEN
      pending := SHL(WORD_TO_DWORD(LINK[103]), 16) OR WORD_TO_DWORD(LINK[104]);
      IF LINK[102] = seq AND (pending AND present) = 0 THEN
        acked := TRUE;
      ELSE
        shown_rounds := shown_rounds + 1;
        IF shown_rounds >= 100 THEN
          (* the stall rule: close the receivers that kept the batch *)
          FOR i := 0 TO 31 DO
            IF (SHR(present, i) AND 1) <> 0 AND (LINK[102] <> seq OR (SHR(pending, i) AND 1) <> 0) THEN
              rx_on[i] := FALSE;
            END_IF;
          END_FOR;
          STALLS := STALLS + 1;
          acked := TRUE;
        END_IF;
      END_IF;
    END_IF;
    IF acked AND q_n > 0 AND NOT HOLD THEN
      used := 0;
      present := 0;
      taken_long := 0;
      k := 0;
      (* records in arrival order while they fit; one long J1939 per receiver *)
      WHILE k < q_n DO
        slot := q_slot[k];
        size := 7;
        IF q_kind[k] = 1 THEN
          size := 10;
        ELSIF q_kind[k] = 2 THEN
          size := 12;
        ELSIF q_kind[k] = 3 THEN
          size := 12;
        END_IF;
        IF NOT rx_on[slot] THEN
          (* closed: its records go *)
          FOR i := k TO q_n - 2 DO
            q_slot[i] := q_slot[i + 1]; q_kind[i] := q_kind[i + 1]; q_id[i] := q_id[i + 1];
            q_len[i] := q_len[i + 1]; q_b0[i] := q_b0[i + 1]; q_src[i] := q_src[i + 1];
            q_code[i] := q_code[i + 1]; q_flags[i] := q_flags[i + 1]; q_ext[i] := q_ext[i + 1];
          END_FOR;
          q_n := q_n - 1;
        ELSIF used + size > SEL(RX_BLOCKS = 2, 95, 215) OR (SHR(taken_long, slot) AND 1) <> 0 THEN
          k := q_n;
        ELSE
          words[used] := SHL(INT_TO_WORD(slot), 8) OR SHL(q_kind[k], 4) OR q_flags[k];
          words[used + 1] := 0;
          FOR i := k + 1 TO q_n - 1 DO
            IF q_slot[i] = slot THEN
              words[used + 1] := words[used + 1] + 1;
            END_IF;
          END_FOR;
          words[used + 2] := rx_drop[slot];
          IF q_kind[k] = 1 THEN
            words[used + 3] := UDINT_TO_WORD(SHR(q_id[k], 16));
            words[used + 4] := UDINT_TO_WORD(q_id[k]);
            words[used + 5] := SEL(q_ext[k], WORD#0, WORD#16#0100) OR UINT_TO_WORD(q_len[k]);
            FOR i := 0 TO 3 DO
              words[used + 6 + i] := SHL(BYTE_TO_WORD(q_b0[k]) + INT_TO_WORD(2 * i), 8) OR
                                      ((BYTE_TO_WORD(q_b0[k]) + INT_TO_WORD(2 * i + 1)) AND 16#00FF);
            END_FOR;
          ELSIF q_kind[k] = 2 THEN
            words[used + 3] := UDINT_TO_WORD(SHR(q_id[k], 16));
            words[used + 4] := UDINT_TO_WORD(q_id[k]);
            words[used + 5] := SHL(q_src[k], 8) OR 16#00FF;
            words[used + 6] := 6;
            words[used + 7] := UINT_TO_WORD(q_len[k]);
            FOR i := 0 TO 3 DO
              words[used + 8 + i] := SHL(BYTE_TO_WORD(q_b0[k]) + INT_TO_WORD(2 * i), 8) OR
                                      ((BYTE_TO_WORD(q_b0[k]) + INT_TO_WORD(2 * i + 1)) AND 16#00FF);
            END_FOR;
            IF q_len[k] > 8 THEN
              words[used] := words[used] OR 16#0001;
              taken_long := taken_long OR SHL(DWORD#1, slot);
              held_slot := slot;
              held_len := q_len[k];
              FOR i := 0 TO UINT_TO_INT(q_len[k]) - 1 DO
                held[i] := INT_TO_BYTE((BYTE_TO_INT(q_b0[k]) + i) MOD 256);
              END_FOR;
            END_IF;
          ELSE
            words[used + 3] := 0;
            words[used + 4] := 16#0006;
            words[used + 5] := 16#0000;
            words[used + 6] := tick;
            words[used + 7] := SHL(UDINT_TO_WORD(q_id[k]), 8) OR 16#0081;
            words[used + 8] := q_code[k];
            words[used + 9] := 16#0102;
            words[used + 10] := 16#0304;
            words[used + 11] := 16#0500;
          END_IF;
          used := used + size;
          present := present OR SHL(DWORD#1, slot);
          FOR i := k TO q_n - 2 DO
            q_slot[i] := q_slot[i + 1]; q_kind[i] := q_kind[i + 1]; q_id[i] := q_id[i + 1];
            q_len[i] := q_len[i + 1]; q_b0[i] := q_b0[i + 1]; q_src[i] := q_src[i + 1];
            q_code[i] := q_code[i + 1]; q_flags[i] := q_flags[i + 1]; q_ext[i] := q_ext[i + 1];
          END_FOR;
          q_n := q_n - 1;
        END_IF;
      END_WHILE;
      IF present <> 0 THEN
        seq := seq + 1;
        batch_tick := tick;
        acked := FALSE;
        shown_rounds := 0;
      END_IF;
    END_IF;
    LINK[720] := seq;
    LINK[721] := DWORD_TO_WORD(SHR(present, 16));
    LINK[722] := DWORD_TO_WORD(present);
    LINK[723] := INT_TO_WORD(used);
    LINK[724] := tick;
    LINK[741] := 0;
    LINK[742] := 16#0006;
    LINK[743] := 16#0000;
    LINK[744] := batch_tick;
    OPEN_RX := 0;
    FOR i := 0 TO 15 DO
      LINK[725 + i] := SHL(SEL(rx_on[2 * i], WORD#0, rx_gen[2 * i] AND 16#00FF), 8) OR
                       SEL(rx_on[2 * i + 1], WORD#0, rx_gen[2 * i + 1] AND 16#00FF);
    END_FOR;
    FOR i := 0 TO 31 DO
      IF rx_on[i] THEN
        OPEN_RX := OPEN_RX + 1;
      END_IF;
    END_FOR;
    FOR i := 0 TO SEL(RX_BLOCKS = 2, 94, 214) DO
      LINK[745 + i] := words[i];
    END_FOR;
  END_IF;
  (* ---- network info: network 0 a J1939 network, network 1 not ---- *)
  IF (LINK[89] AND 16#0020) <> 0 THEN
    info_count := info_count + 1;
    FOR k := 0 TO 1 DO
      b := 960 + 18 * k;
      LINK[b] := 16#000C;
      LINK[b + 1] := 1;
      LINK[b + 2] := 2;
      LINK[b + 3] := 0;
      LINK[b + 4] := 3;
      LINK[b + 5] := 0;
      LINK[b + 6] := 1000;
      LINK[b + 7] := 1;
      LINK[b + 8] := 0;
      LINK[b + 9] := 0;
      LINK[b + 10] := 5;
      IF k = 0 AND NOT NO_J1939 THEN
        LINK[b + 11] := 16#0180;
        LINK[b + 12] := 16#A000;
        LINK[b + 13] := 0;
        LINK[b + 14] := 0;
        LINK[b + 15] := 16#ABCD;
        LINK[b + 16] := 4;
      ELSE
        LINK[b + 11] := 16#FF0A;
        LINK[b + 12] := 0;
        LINK[b + 13] := 0;
        LINK[b + 14] := 0;
        LINK[b + 15] := 0;
        LINK[b + 16] := 0;
      END_IF;
      LINK[b + 17] := info_count;
    END_FOR;
  END_IF;
  (* ---- cyclic job table and keepalives ---- *)
  IF jobs > 0 THEN
    LINK[1104] := tick;
    FOR k := 0 TO jobs - 1 DO
      b := 1105 + 4 * k;
      IF job_on[k] THEN
        IF LINK[128 + k] = job_keep[k] THEN
          job_idle[k] := job_idle[k] + 1;
          IF job_idle[k] >= 100 THEN
            job_on[k] := FALSE;
          END_IF;
        ELSE
          job_keep[k] := LINK[128 + k];
          job_idle[k] := 0;
        END_IF;
      END_IF;
      IF job_on[k] THEN
        job_count[k] := job_count[k] + 1;
        LINK[b] := 16#0100;
        LINK[b + 1] := job_gen[k];
        LINK[b + 2] := UDINT_TO_WORD(SHR(job_count[k], 16));
        LINK[b + 3] := UDINT_TO_WORD(job_count[k]);
      ELSE
        LINK[b] := 0;
        LINK[b + 1] := 0;
        LINK[b + 2] := 0;
        LINK[b + 3] := 0;
      END_IF;
    END_FOR;
  END_IF;
END_FUNCTION_BLOCK
