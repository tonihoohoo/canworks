(* An example program for this config: the function blocks over the
   bridge's mailboxes (docs/plc-library.md). Paste it into the editor
   project's main program. The rtd module is node 5, the I/O module node 6,
   both on network 0. *)
PROGRAM main
  VAR
    rd_name : CO_SDO_READ_STRING;   (* the rtd module's device name *)
    device_name : STRING;
    rx_rtd : CAN_RECEIVE;            (* every TPDO 1 frame of the rtd module *)
    rtd_frame : ARRAY[0..7] OF BYTE;
    rtd_frames : UDINT;
    channel_0 : INT;
    emcy : CO_RECV_EMCY;             (* every EMCY of both nodes, in order *)
    msef : ARRAY[0..4] OF BYTE;
    last_emcy : WORD;
    bus : CAN_BUS_INFO;
    blink : CAN_SEND_CYCLIC;          (* a heartbeat-like frame every 100 ms *)
    blink_data : ARRAY[0..7] OF BYTE;
  END_VAR

  (* Once the bridge answers: read the name (a rising edge of EXECUTE). *)
  rd_name(EXECUTE := canworks.ok, NETWORK := 0, NODE := 5, INDEX := 16#1008, SUBINDEX := 0, LINK := canworks.link);
  IF rd_name.DONE THEN
    device_name := rd_name.VALUE;
  END_IF;

  (* Read every frame of the current batch in this scan. *)
  rx_rtd(ENABLE := TRUE, NETWORK := 0, ID := 16#185, RX_DATA := rtd_frame, LINK := canworks.link);
  WHILE rx_rtd.RECEIVED DO
    rtd_frames := rtd_frames + 1;
    channel_0 := LINT_TO_INT(CAN_GET_BITS(DATA := rtd_frame, START_BIT := 0, BIT_LENGTH := 16, MOTOROLA := FALSE, SIGNED := TRUE));
    rx_rtd(ENABLE := TRUE, NETWORK := 0, ID := 16#185, RX_DATA := rtd_frame, LINK := canworks.link);
  END_WHILE;

  emcy(ENABLE := TRUE, NETWORK := 0, NODE := 0, MSEF := msef, LINK := canworks.link);
  WHILE emcy.RECEIVED DO
    last_emcy := emcy.ERROR_CODE;
    emcy(ENABLE := TRUE, NETWORK := 0, NODE := 0, MSEF := msef, LINK := canworks.link);
  END_WHILE;

  bus(NETWORK := 0, LINK := canworks.link);   (* bus.STATE, bus.BUS_LOAD, ... *)

  blink_data[0] := BOOL_TO_BYTE(canworks.dio_ok);
  blink(ENABLE := canworks.ok, NETWORK := 0, ID := 16#7F0, DLC := 1, PERIOD := T#100ms, DATA := blink_data, LINK := canworks.link);
END_PROGRAM
