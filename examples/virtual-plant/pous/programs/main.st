PROGRAM main
  VAR
    (* The demo (docs/tour.md). The CANopen values are in the `canworks`
       variable list, which canworks_in fills from the bridge before main and
       canworks_out sends after it (the configurator writes all three). *)
    temp_c          : REAL;   (* RTD channel 0 in degC (the module sends 0.1 degC) *)
    limit           : INT;    (* alarm limit in 0.1 degC, from the cell's upper master *)
    alarm           : BOOL;   (* channel 0 above the limit: DIO-16 output 0.0 and the cell's alarm *)
    fault           : BOOL;   (* a node lost, a PDO timed out or an EMCY active: new_io output 0.0 *)
    pattern         : USINT := 1;  (* running light on DIO-16 output byte 2, read back on input byte 2 *)
    tick            : INT;
    loop_errors     : UDINT;  (* times the read-back input did not follow the output *)
    loop_ok         : BOOL;
    cycles          : UDINT;
    restart_dio     : BOOL;   (* set it in the debugger: NMT reset of node dio (6) *)
    started         : BOOL;
    rd_product      : CO_SDO_READ;   (* network io (0), node 5: 0x1018:2 product code *)
    rd_conveyor     : CO_SDO_READ;   (* network motion (1), node 4: 0x1018:2 product code *)
    wr_ai_interrupt : CO_SDO_WRITE;  (* network io (0), node 6: 0x6423 analogue input global interrupt enable *)
    reset_dio       : CO_NMT;        (* network io (0), node 6: RESET NODE when restart_dio is set *)
    rtd_product     : UDINT;
    conveyor_product : UDINT;
    sdo_errors      : INT;
    (* The host network plays the cell's machine controller (the upper master). *)
    host_field_ok   : BOOL;   (* the gateway reports io nodes 5, 6, 7 and motion node 4 operational *)
    speed           : INT := 1000;  (* conveyor speed while the upper master runs the line *)
  END_VAR

(* Temperature, alarm and the I/O loopback on network io *)
cycles := cycles + 1;
canworks.cell_cycle_count := cycles;
temp_c := INT_TO_REAL(canworks.io_rtd_AI0_Input_PV) / 10.0;
limit := canworks.cell_temp_limit;
IF limit = 0 THEN limit := 250; END_IF  (* no upper master: 25.0 degC *)
alarm := canworks.io_rtd_ok AND canworks.io_rtd_AI0_Input_PV > limit;
canworks.cell_alarm := alarm;
IF alarm THEN
  canworks.cell_emcy := 16#4210;  (* temperature too high: the cell slave sends it once *)
  canworks.cell_errreg := 16#09;  (* generic + temperature *)
ELSE
  canworks.cell_emcy := 0;
  canworks.cell_errreg := 0;
END_IF
canworks.io_dio_Write_output_8_bit_1 := BOOL_TO_USINT(alarm);

(* DIO-16 loops its outputs back to its inputs: a running light on byte 2,
   checked a few PDO round trips later. *)
tick := tick + 1;
IF tick >= 25 THEN
  tick := 0;
  IF canworks.io_dio_ok THEN
    loop_ok := canworks.io_dio_Read_input_8_bit_2 = pattern;
    IF NOT loop_ok THEN loop_errors := loop_errors + 1; END_IF
  END_IF
  pattern := ROL(pattern, 1);
END_IF
canworks.io_dio_Write_output_8_bit_2 := pattern;
canworks.io_dio_Write_analogue_output_2 := canworks.io_rtd_AI1_Input_PV;  (* AO 2 follows RTD channel 1 *)

(* Reactions: lost nodes, the RTD PDO's receive timeout, EMCYs *)
fault := NOT canworks.io_rtd_ok OR NOT canworks.io_dio_ok OR NOT canworks.motion_conveyor_ok
         OR canworks.io_rtd_tpdo1_timeout
         OR canworks.io_rtd_emcy <> 0 OR canworks.io_dio_emcy <> 0 OR canworks.motion_conveyor_emcy <> 0;
canworks.io_new_io_Write_output_8_bit_1 := BOOL_TO_USINT(fault) OR SHL(BOOL_TO_USINT(NOT host_field_ok), 1);

(* NMT: restart_dio resets node 6 once (set it again for another reset). *)
reset_dio(EXECUTE := restart_dio, NETWORK := 0, NODE := 6, COMMAND := 129, LINK := canworks.link);
IF reset_dio.DONE OR reset_dio.ERROR THEN restart_dio := FALSE; END_IF

(* SDO: read and write once after the nodes are up (again after a node comes
   back). *)
started := canworks.ok AND canworks.io_rtd_ok AND canworks.io_dio_ok AND canworks.motion_conveyor_ok;
rd_product(EXECUTE := started, NETWORK := 0, NODE := 5, INDEX := 16#1018, SUBINDEX := 2, LINK := canworks.link);
IF rd_product.DONE THEN rtd_product := rd_product.DATA; END_IF
rd_conveyor(EXECUTE := started, NETWORK := 1, NODE := 4, INDEX := 16#1018, SUBINDEX := 2, LINK := canworks.link);
IF rd_conveyor.DONE THEN conveyor_product := rd_conveyor.DATA; END_IF
wr_ai_interrupt(EXECUTE := started, NETWORK := 0, NODE := 6, INDEX := 16#6423, SUBINDEX := 0,
                DATA := 1, SIZE := 1, LINK := canworks.link);
IF rd_product.ERROR OR rd_conveyor.ERROR OR wr_ai_interrupt.ERROR THEN sdo_errors := sdo_errors + 1; END_IF

(* The host network: the cell's machine controller. It runs the line, sets
   the alarm limit and sends the temperature it gets through the gateway
   back down to DIO-16's analogue output 1. *)
canworks.host_cell_line_run := canworks.host_cell_ok;
canworks.host_cell_temp_limit := 250;
canworks.host_cell_analog_out := canworks.host_cell_temperature;
host_field_ok := canworks.host_cell_ok AND (canworks.host_cell_Nodes_0_31 AND 16#E0) = 16#E0
                 AND (canworks.host_cell_Nodes_0_31_2 AND 16#10) = 16#10;

(* The conveyor runs while the upper master runs the line; its belt position
   goes up to the host. *)
IF canworks.cell_line_run AND canworks.motion_conveyor_ok THEN
  canworks.motion_conveyor_speed_setpoint := speed;
ELSE
  canworks.motion_conveyor_speed_setpoint := 0;
END_IF
canworks.cell_belt_position := canworks.motion_conveyor_belt_position;

END_PROGRAM
