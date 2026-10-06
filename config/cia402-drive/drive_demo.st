(* CiA 402 demo for config/cia402-drive (axis "drive", node 4).
   The VAR block and the first lines of the body are what the project
   generator writes into main for this config (openplc-canopen-deploy
   --new-project, or the configurator's New editor project); the rest is the
   demo. Paste the demo variables and body into that main. *)
PROGRAM main
  VAR
    drive_ok                         : BOOL AT %IX10.0; (* node drive (4): operational *)
    drive_Statusword                 : UINT AT %IW100; (* node drive (4) TPDO1 0x6041:0 Statusword *)
    drive_Modes_of_operation_display : SINT AT %IB100; (* node drive (4) TPDO1 0x6061:0 Modes of operation display *)
    drive_Position_actual_value      : DINT AT %ID100; (* node drive (4) TPDO2 0x6064:0 Position actual value *)
    drive_Velocity_actual_value      : DINT AT %ID101; (* node drive (4) TPDO3 0x606C:0 Velocity actual value *)
    drive_Controlword                : UINT AT %QW100; (* node drive (4) RPDO1 0x6040:0 Controlword *)
    drive_Modes_of_operation         : SINT AT %QB100; (* node drive (4) RPDO1 0x6060:0 Modes of operation *)
    drive_Target_position            : DINT AT %QD100; (* node drive (4) RPDO2 0x607A:0 Target position *)
    drive_Profile_velocity           : UDINT AT %QD101; (* node drive (4) RPDO2 0x6081:0 Profile velocity *)
    drive_Target_velocity            : DINT AT %QD102; (* node drive (4) RPDO3 0x60FF:0 Target velocity *)
    drive                            : AXIS_REF_SM3; (* node drive (4): CiA 402 axis *)
    drive_bridge                     : SM_Drive_GenericDS402; (* node drive (4): drive bridge of axis drive *)

    (* The demo sequence *)
    power   : MC_Power;
    home    : MC_Home;
    moveAbs : MC_MoveAbsolute;
    moveVel : MC_MoveVelocity;
    halt    : MC_Halt;
    reset   : MC_Reset;
    status  : MC_ReadStatus;
    run     : TON;
    start   : BOOL := TRUE; (* set FALSE to stop the sequence at the next step *)
    busy    : BOOL;
    tries   : INT;
    step    : INT;          (* 0 power on, 5 homing mode, 10 home, 20 move to 1000, 30 run at 200/s for 2 s, 40 halt, 50 done, 90 fault reset *)
  END_VAR

(* CiA 402 axes from canopen/canopen.json: keep these lines first *)
drive.iRatioTechUnitsNum := DINT#1;
drive.dwRatioTechUnitsDenom := DWORD#1;
drive.fScalefactor := LREAL#1.0;
drive_bridge(Axis := drive,
             wStatusWord := drive_Statusword,
             siModesDisplay := drive_Modes_of_operation_display,
             diActualPosition := drive_Position_actual_value,
             diActualVelocity := drive_Velocity_actual_value,
             bOnline := drive_ok,
             wControlWord => drive_Controlword,
             siModes => drive_Modes_of_operation,
             diTargetPosition => drive_Target_position,
             udiProfileVelocity => drive_Profile_velocity,
             diTargetVelocity => drive_Target_velocity);

(* Demo: power on, home, move to position 1000, run at 200 units/s for
   2 s, halt. A fault anywhere goes to a fault reset and starts again.
   The editor's motion blocks act while Execute is TRUE, so each step
   holds Execute until the block reports Done and then releases it. A block
   is only called in its own step: an idle block still writes its
   controlword bits. Two steps work around how
   the library behaves on a bus with a delay (docs/cia402.md): homing mode
   is selected before MC_Home, and MC_MoveAbsolute's Done counts only after
   Busy. *)
power(Axis := drive, Enable := step <> 90);
status(Axis := drive, Enable := TRUE);
IF status.Errorstop AND step <> 90 THEN
  step := 90;
END_IF

CASE step OF
  0:
    IF power.Status AND start THEN step := 5; END_IF
  5:
    drive.Drive.Modes_of_operation := 6;
    IF drive.byRealControllerMode = 6 THEN step := 10; END_IF
  10:
    home(Axis := drive, Execute := TRUE, Position := 0.0);
    IF home.Done THEN home(Axis := drive, Execute := FALSE); step := 20; END_IF
  20:
    moveAbs(Axis := drive, Execute := TRUE, Position := 1000.0, Velocity := 500.0);
    IF moveAbs.Busy THEN busy := TRUE; END_IF
    IF busy AND moveAbs.Done THEN
      moveAbs(Axis := drive, Execute := FALSE);
      busy := FALSE;
      step := 30;
    END_IF
  30:
    moveVel(Axis := drive, Execute := TRUE, Velocity := 200.0);
    run(IN := moveVel.InVelocity, PT := T#2s);
    IF run.Q THEN
      moveVel(Axis := drive, Execute := FALSE);
      run(IN := FALSE);
      step := 40;
    END_IF
  40:
    halt(Axis := drive, Execute := TRUE);
    IF halt.Done THEN halt(Axis := drive, Execute := FALSE); step := 50; END_IF
  90:
    (* Release whatever was running, then reset the fault. *)
    home(Axis := drive, Execute := FALSE);
    moveAbs(Axis := drive, Execute := FALSE);
    moveVel(Axis := drive, Execute := FALSE);
    halt(Axis := drive, Execute := FALSE);
    run(IN := FALSE);
    busy := FALSE;
    (* The drive takes a fault reset on a rising edge, so retry every 50
       scans while the fault is still there. *)
    tries := tries + 1;
    reset(Axis := drive, Execute := tries < 50);
    IF tries >= 50 THEN tries := 0; END_IF
    (* A lost drive stays here until it is back on the bus. *)
    IF reset.Done AND drive.bCommunication THEN
      reset(Axis := drive, Execute := FALSE);
      tries := 0;
      step := 0;
    END_IF
END_CASE

END_PROGRAM
