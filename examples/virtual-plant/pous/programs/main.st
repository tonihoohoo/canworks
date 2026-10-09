PROGRAM main
  VAR
    io_can_bus_state                        : USINT AT %IB11; (* network io: CAN bus state *)
    io_can_master_state                     : USINT AT %IB10; (* network io: CANopen master state *)
    motion_can_master_state                 : USINT AT %IB20; (* network motion: CANopen master state *)
    host_can_master_state                   : USINT AT %IB41; (* network host: CANopen master state *)
    io_rtd_ok                               : BOOL AT %IX12.0; (* network io: node rtd (5): operational *)
    io_rtd_state                            : USINT AT %IB13; (* network io: node rtd (5): NMT state *)
    io_rtd_emcy                             : WORD AT %IW14; (* network io: node rtd (5): last EMCY code *)
    io_rtd_tpdo1_timeout                    : BOOL AT %IX12.1; (* network io: node rtd (5): TPDO 1 receive timeout *)
    io_rtd_AI0_Input_PV                     : INT AT %IW100; (* network io: node rtd (5) TPDO1 0x7130:1 AI0_Input_PV *)
    io_rtd_AI1_Input_PV                     : INT AT %IW101; (* network io: node rtd (5) TPDO1 0x7130:2 AI1_Input_PV *)
    io_rtd_AI2_Input_PV                     : INT AT %IW102; (* network io: node rtd (5) TPDO1 0x7130:3 AI2_Input_PV *)
    io_rtd_AI3_Input_PV                     : INT AT %IW103; (* network io: node rtd (5) TPDO1 0x7130:4 AI3_Input_PV *)
    io_dio_ok                               : BOOL AT %IX12.2; (* network io: node dio (6): operational *)
    io_dio_state                            : USINT AT %IB15; (* network io: node dio (6): NMT state *)
    io_dio_emcy                             : WORD AT %IW16; (* network io: node dio (6): last EMCY code *)
    io_dio_Read_input_8_bit_1               : USINT AT %IB110; (* network io: node dio (6) TPDO1 0x6000:1 Read input 8-bit 1 *)
    io_dio_Read_input_8_bit_2               : USINT AT %IB111; (* network io: node dio (6) TPDO1 0x6000:2 Read input 8-bit 2 *)
    io_dio_Read_analogue_input_1            : INT AT %IW110; (* network io: node dio (6) TPDO1 0x6401:1 Read analogue input 1 *)
    io_dio_Read_analogue_input_2            : INT AT %IW111; (* network io: node dio (6) TPDO1 0x6401:2 Read analogue input 2 *)
    io_dio_operating_hours                  : UDINT AT %ID110; (* network io: node dio (6) SDO read 0x2001:0 Operating hours *)
    io_dio_operating_hours_status           : USINT AT %IB112; (* network io: node dio (6) SDO read 0x2001:0 Operating hours, status *)
    io_dio_filter_time_status               : USINT AT %IB113; (* network io: node dio (6) SDO write 0x2000:0 Input filter time, status *)
    io_dio_Write_output_8_bit_1             : USINT AT %QB110; (* network io: node dio (6) RPDO1 0x6200:1 Write output 8-bit 1 *)
    io_dio_Write_output_8_bit_2             : USINT AT %QB111; (* network io: node dio (6) RPDO1 0x6200:2 Write output 8-bit 2 *)
    io_dio_Write_analogue_output_2          : INT AT %QW110; (* network io: node dio (6) RPDO1 0x6411:2 Write analogue output 2 *)
    io_dio_filter_time                      : UINT AT %QW111; (* network io: node dio (6) SDO write 0x2000:0 Input filter time *)
    io_dio_filter_time_trig                 : BOOL AT %QX112.0; (* network io: node dio (6) SDO write 0x2000:0 Input filter time, trigger *)
    io_dio_nmt                              : USINT AT %QB10; (* network io: node dio (6): NMT command *)
    io_new_io_ok                            : BOOL AT %IX12.3; (* network io: node new_io (7): operational *)
    io_new_io_Read_input_8_bit_1            : USINT AT %IB120; (* network io: node new_io (7) TPDO1 0x6000:1 Read input 8-bit 1 *)
    io_new_io_Write_output_8_bit_1          : USINT AT %QB120; (* network io: node new_io (7) RPDO1 0x6200:1 Write output 8-bit 1 *)
    motion_drive_ok                         : BOOL AT %IX21.0; (* network motion: node drive (4): operational *)
    motion_drive_state                      : USINT AT %IB22; (* network motion: node drive (4): NMT state *)
    motion_drive_emcy                       : WORD AT %IW23; (* network motion: node drive (4): last EMCY code *)
    motion_drive_Statusword                 : UINT AT %IW200; (* network motion: node drive (4) TPDO1 0x6041:0 Statusword *)
    motion_drive_Modes_of_operation_display : SINT AT %IB200; (* network motion: node drive (4) TPDO1 0x6061:0 Modes of operation display *)
    motion_drive_Position_actual_value      : DINT AT %ID200; (* network motion: node drive (4) TPDO1 0x6064:0 Position actual value *)
    motion_drive_Velocity_actual_value      : DINT AT %ID201; (* network motion: node drive (4) TPDO2 0x606C:0 Velocity actual value *)
    motion_drive_Torque_actual_value        : INT AT %IW201; (* network motion: node drive (4) TPDO2 0x6077:0 Torque actual value *)
    motion_drive_Controlword                : UINT AT %QW200; (* network motion: node drive (4) RPDO1 0x6040:0 Controlword *)
    motion_drive_Modes_of_operation         : SINT AT %QB200; (* network motion: node drive (4) RPDO1 0x6060:0 Modes of operation *)
    motion_drive_Target_position            : DINT AT %QD200; (* network motion: node drive (4) RPDO1 0x607A:0 Target position *)
    motion_drive_Target_velocity            : DINT AT %QD201; (* network motion: node drive (4) RPDO2 0x60FF:0 Target velocity *)
    motion_drive_Target_torque              : INT AT %QW201; (* network motion: node drive (4) RPDO2 0x6071:0 Target torque *)
    motion_drive                            : AXIS_REF_SM3; (* network motion: node drive (4): CiA 402 axis *)
    motion_drive_bridge                     : SM_Drive_GenericDS402; (* network motion: node drive (4): drive bridge of axis motion_drive *)
    host_cell_ok                            : BOOL AT %IX40.0; (* network host: node cell (20): operational *)
    host_cell_state                         : USINT AT %IB42; (* network host: node cell (20): NMT state *)
    host_cell_emcy                          : WORD AT %IW41; (* network host: node cell (20): last EMCY code *)
    host_cell_alarm                         : BOOL AT %IX40.1; (* network host: node cell (20) TPDO1 0x2100:1 alarm *)
    host_cell_axis_position                 : DINT AT %ID40; (* network host: node cell (20) TPDO1 0x2101:1 axis_position *)
    host_cell_cycle_count                   : UDINT AT %ID41; (* network host: node cell (20) TPDO2 0x2102:1 cycle_count *)
    host_cell_temperature                   : INT AT %IW40; (* network host: node cell (20) TPDO2 0x2103:1 temperature *)
    host_cell_Nodes_0_31                    : UDINT AT %ID42; (* network host: node cell (20) TPDO3 0x5E10:1 Nodes 0-31 *)
    host_cell_Nodes_0_31_2                  : UDINT AT %ID43; (* network host: node cell (20) TPDO5 0x5E11:1 Nodes 0-31 *)
    host_cell_line_run                      : BOOL AT %QX40.0; (* network host: node cell (20) RPDO1 0x2000:1 line_run *)
    host_cell_temp_limit                    : INT AT %QW40; (* network host: node cell (20) RPDO1 0x2001:1 temp_limit *)
    host_cell_analog_out                    : INT AT %QW41; (* network host: node cell (20) RPDO1 0x2001:2 analog_out *)
    cell_line_run                           : BOOL AT %IX300.0; (* network cell: slave node 20 0x2000:1 line_run, from the master *)
    cell_temp_limit                         : INT AT %IW300; (* network cell: slave node 20 0x2001:1 temp_limit, from the master *)
    cell_state                              : USINT AT %IB301; (* network cell: slave node 20: own NMT state *)
    cell_comm_ok                            : BOOL AT %IX300.1; (* network cell: slave node 20: communication OK *)
    cell_alarm                              : BOOL AT %QX300.0; (* network cell: slave node 20 0x2100:1 alarm, to the master *)
    cell_axis_position                      : DINT AT %QD300; (* network cell: slave node 20 0x2101:1 axis_position, to the master *)
    cell_cycle_count                        : UDINT AT %QD301; (* network cell: slave node 20 0x2102:1 cycle_count, to the master *)
    cell_emcy                               : WORD AT %QW301; (* network cell: slave node 20: EMCY code to send *)
    cell_errreg                             : BYTE AT %QB300; (* network cell: slave node 20: error register to send *)

    (* The demo (docs/tour.md): everything below is the demo's own. *)
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
    (* SDO blocks begin *)
    rd_product      : CO_SDO_READ;   (* network io (0), node 5: 0x1018:2 product code *)
    rd_drive_modes  : CO_SDO_READ;   (* network motion (1), node 4: 0x6502 supported drive modes *)
    wr_ai_interrupt : CO_SDO_WRITE;  (* network io (0), node 6: 0x6423 analogue input global interrupt enable *)
    rtd_product     : UDINT;
    drive_modes     : UDINT;
    sdo_errors      : INT;
    (* SDO blocks end *)
    (* The host network plays the cell's machine controller (the upper master). *)
    host_field_ok   : BOOL;   (* the gateway reports io nodes 5, 6, 7 and motion node 4 operational *)
    (* The drive: power on, home, then back and forth between 0 and 1000
       while the upper master sets line_run. *)
    power           : MC_Power;
    home            : MC_Home;
    csp_move        : CO402_CyclicMoveAbsolute;
    reset           : MC_Reset;
    status          : MC_ReadStatus;
    target          : LREAL := 1000.0;
    dwell           : LREAL;
    moves           : UDINT;  (* moves finished *)
    tries           : INT;
    step            : INT;    (* 0 power on, 5 CSP mode, 10 home, 20 move, 30 dwell, 90 fault reset *)
  END_VAR

(* CiA 402 axes from canworks/canworks.json: keep these lines first *)
motion_drive.iRatioTechUnitsNum := DINT#1;
motion_drive.dwRatioTechUnitsDenom := DWORD#1;
motion_drive.fScalefactor := LREAL#1.0;
motion_drive.fCycleTime := LREAL#0.01; (* the task interval: change it with the interval *)
motion_drive_bridge(Axis := motion_drive,
                    wStatusWord := motion_drive_Statusword,
                    siModesDisplay := motion_drive_Modes_of_operation_display,
                    diActualPosition := motion_drive_Position_actual_value,
                    diActualVelocity := motion_drive_Velocity_actual_value,
                    iActualTorque := motion_drive_Torque_actual_value,
                    bOnline := motion_drive_ok,
                    wControlWord => motion_drive_Controlword,
                    siModes => motion_drive_Modes_of_operation,
                    diTargetPosition => motion_drive_Target_position,
                    diTargetVelocity => motion_drive_Target_velocity,
                    iTargetTorque => motion_drive_Target_torque);

(* CANopen I/O declared from canworks/canworks.json *)

(* Temperature, alarm and the I/O loopback on network io *)
cycles := cycles + 1;
cell_cycle_count := cycles;
temp_c := INT_TO_REAL(io_rtd_AI0_Input_PV) / 10.0;
limit := cell_temp_limit;
IF limit = 0 THEN limit := 250; END_IF  (* no upper master: 25.0 degC *)
alarm := io_rtd_ok AND io_rtd_AI0_Input_PV > limit;
cell_alarm := alarm;
IF alarm THEN
  cell_emcy := 16#4210;  (* temperature too high: the cell slave sends it once *)
  cell_errreg := 16#09;  (* generic + temperature *)
ELSE
  cell_emcy := 0;
  cell_errreg := 0;
END_IF
io_dio_Write_output_8_bit_1 := BOOL_TO_USINT(alarm);

(* DIO-16 loops its outputs back to its inputs: a running light on byte 2,
   checked a few PDO round trips later. *)
tick := tick + 1;
IF tick >= 25 THEN
  tick := 0;
  IF io_dio_ok THEN
    loop_ok := io_dio_Read_input_8_bit_2 = pattern;
    IF NOT loop_ok THEN loop_errors := loop_errors + 1; END_IF
  END_IF
  pattern := ROL(pattern, 1);
END_IF
io_dio_Write_output_8_bit_2 := pattern;
io_dio_Write_analogue_output_2 := io_rtd_AI1_Input_PV;  (* AO 2 follows RTD channel 1 *)

(* Reactions: lost nodes, the RTD PDO's receive timeout, EMCYs *)
fault := NOT io_rtd_ok OR NOT io_dio_ok OR NOT motion_drive_ok OR io_rtd_tpdo1_timeout
         OR io_rtd_emcy <> 0 OR io_dio_emcy <> 0 OR motion_drive_emcy <> 0;
io_new_io_Write_output_8_bit_1 := BOOL_TO_USINT(fault) OR SHL(BOOL_TO_USINT(NOT host_field_ok), 1);

(* NMT: restart_dio resets node 6 once; 0 lets the master run it normally. *)
IF restart_dio THEN io_dio_nmt := 129; ELSE io_dio_nmt := 0; END_IF

(* SDO blocks begin: read and write once after the nodes are up (again after a
   node comes back). *)
started := io_rtd_ok AND io_dio_ok AND motion_drive_ok;
rd_product(EXECUTE := started, NETWORK := 0, NODE := 5, INDEX := 16#1018, SUBINDEX := 2);
IF rd_product.DONE THEN rtd_product := LWORD_TO_UDINT(rd_product.DATA); END_IF
rd_drive_modes(EXECUTE := started, NETWORK := 1, NODE := 4, INDEX := 16#6502, SUBINDEX := 0);
IF rd_drive_modes.DONE THEN drive_modes := LWORD_TO_UDINT(rd_drive_modes.DATA); END_IF
wr_ai_interrupt(EXECUTE := started, NETWORK := 0, NODE := 6, INDEX := 16#6423, SUBINDEX := 0,
                DATA := BOOL_TO_LWORD(TRUE), SIZE := 0);
IF rd_product.ERROR OR rd_drive_modes.ERROR OR wr_ai_interrupt.ERROR THEN sdo_errors := sdo_errors + 1; END_IF
(* SDO blocks end *)

(* The host network: the cell's machine controller. It runs the line, sets
   the alarm limit and sends the temperature it gets through the gateway
   back down to DIO-16's analogue output 1. *)
host_cell_line_run := host_cell_ok;
host_cell_temp_limit := 250;
host_cell_analog_out := host_cell_temperature;
host_field_ok := host_cell_ok AND (host_cell_Nodes_0_31 AND 16#E0) = 16#E0
                 AND (host_cell_Nodes_0_31_2 AND 16#10) = 16#10;

(* The drive sequence, while the upper master runs the line *)
cell_axis_position := motion_drive_Position_actual_value;
power(Axis := motion_drive, Enable := step <> 90);
status(Axis := motion_drive, Enable := TRUE);
IF (status.Errorstop OR csp_move.Error) AND step <> 90 THEN step := 90; END_IF
CASE step OF
  0:
    IF power.Status AND cell_line_run THEN step := 5; END_IF
  5:
    motion_drive.Drive.Modes_of_operation := 6;
    IF motion_drive.byRealControllerMode = 6 THEN step := 10; END_IF
  10:
    home(Axis := motion_drive, Execute := TRUE, Position := 0.0);
    IF home.Done THEN home(Axis := motion_drive, Execute := FALSE); target := 1000.0; step := 20; END_IF
  20:
    csp_move(Axis := motion_drive, Execute := TRUE, Position := target, Velocity := 500.0, Acceleration := 2000.0,
         Jerk := 20000.0);
    IF csp_move.Done THEN
      csp_move(Axis := motion_drive, Execute := FALSE);
      moves := moves + 1;
      dwell := 0.0;
      step := 30;
    END_IF
  30:
    dwell := dwell + motion_drive.fCycleTime;
    IF dwell >= 1.0 AND cell_line_run THEN
      IF target = 0.0 THEN target := 1000.0; ELSE target := 0.0; END_IF
      step := 20;
    END_IF
  90:
    (* Release the move, then reset the fault; a lost drive waits here. *)
    home(Axis := motion_drive, Execute := FALSE);
    csp_move(Axis := motion_drive, Execute := FALSE);
    tries := tries + 1;
    reset(Axis := motion_drive, Execute := tries < 50);
    IF tries >= 50 THEN tries := 0; END_IF
    IF reset.Done AND motion_drive.bCommunication THEN
      reset(Axis := motion_drive, Execute := FALSE);
      tries := 0;
      step := 0;
    END_IF
END_CASE

END_PROGRAM
