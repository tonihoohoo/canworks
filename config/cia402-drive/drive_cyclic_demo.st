(* Cyclic synchronous CiA 402 demo for config/cia402-drive/canopen_config_cyclic.json
   (axis "drive", node 4, SYNC from the PLC cycle, task interval T#10ms).
   The VAR block and the first lines of the body are what the project
   generator writes into main for this config (canworks-deploy
   --new-project --task-interval T#10ms, or the configurator's New editor
   project); the rest is the demo. Paste the demo variables and body into
   that main. The CO402_Cyclic* blocks come from the canworks library,
   which the generated project enables. *)
PROGRAM main
  VAR
    drive_ok                         : BOOL AT %IX10.0; (* node drive (4): operational *)
    drive_Statusword                 : UINT AT %IW100; (* node drive (4) TPDO1 0x6041:0 Statusword *)
    drive_Modes_of_operation_display : SINT AT %IB100; (* node drive (4) TPDO1 0x6061:0 Modes of operation display *)
    drive_Position_actual_value      : DINT AT %ID100; (* node drive (4) TPDO1 0x6064:0 Position actual value *)
    drive_Velocity_actual_value      : DINT AT %ID101; (* node drive (4) TPDO2 0x606C:0 Velocity actual value *)
    drive_Torque_actual_value        : INT AT %IW101; (* node drive (4) TPDO2 0x6077:0 Torque actual value *)
    drive_Controlword                : UINT AT %QW100; (* node drive (4) RPDO1 0x6040:0 Controlword *)
    drive_Modes_of_operation         : SINT AT %QB100; (* node drive (4) RPDO1 0x6060:0 Modes of operation *)
    drive_Target_position            : DINT AT %QD100; (* node drive (4) RPDO1 0x607A:0 Target position *)
    drive_Target_velocity            : DINT AT %QD101; (* node drive (4) RPDO2 0x60FF:0 Target velocity *)
    drive_Target_torque              : INT AT %QW101; (* node drive (4) RPDO2 0x6071:0 Target torque *)
    drive                            : AXIS_REF_SM3; (* node drive (4): CiA 402 axis *)
    drive_bridge                     : SM_Drive_GenericDS402; (* node drive (4): drive bridge of axis drive *)

    (* The demo sequence *)
    power   : MC_Power;
    home    : MC_Home;
    moveCsp : CO402_CyclicMoveAbsolute;
    csv     : CO402_CyclicVelocity;
    cst     : CO402_CyclicTorque;
    reset   : MC_Reset;
    status  : MC_ReadStatus;
    start   : BOOL := TRUE;  (* set FALSE to stop the sequence at the next step *)
    vel     : LREAL;         (* the program's own velocity ramp in the CSV steps [u/s] *)
    elapsed : LREAL;         (* time in the step [s], counted in task cycles *)
    tries   : INT;
    errors  : INT;           (* faults and block errors seen after step 0 *)
    step    : INT;           (* 0 power on, 5 homing mode, 10 home, 20 CSP move to 1000, 30 CSV run at 200/s for 2 s,
                                35 CSV ramp down, 40 CST torque step, 50 done (CSV standstill), 90 fault reset *)
  END_VAR

(* CiA 402 axes from canworks/canworks.json: keep these lines first *)
drive.iRatioTechUnitsNum := DINT#1;
drive.dwRatioTechUnitsDenom := DWORD#1;
drive.fScalefactor := LREAL#1.0;
drive.fCycleTime := LREAL#0.01; (* the task interval: change it with the interval *)
drive_bridge(Axis := drive,
             wStatusWord := drive_Statusword,
             siModesDisplay := drive_Modes_of_operation_display,
             diActualPosition := drive_Position_actual_value,
             diActualVelocity := drive_Velocity_actual_value,
             iActualTorque := drive_Torque_actual_value,
             bOnline := drive_ok,
             wControlWord => drive_Controlword,
             siModes => drive_Modes_of_operation,
             diTargetPosition => drive_Target_position,
             diTargetVelocity => drive_Target_velocity,
             iTargetTorque => drive_Target_torque);

(* Demo: power on, home, move to position 1000 in CSP with a jerk-limited
   profile, run at 200 units/s for 2 s in CSV with the program's own ramp,
   ramp down, a short torque step in CST, and stand still in CSV. A fault
   (the drive faults when the PLC stops, as the SYNC stops with it) or a
   block error goes to a fault reset and starts again.
   Times are counted in task cycles (drive.fCycleTime). A cyclic block is
   only called in its own step, and once more with Enable FALSE when the
   step ends, so that it hands the drive over cleanly. *)
power(Axis := drive, Enable := step <> 90);
status(Axis := drive, Enable := TRUE);
IF (status.Errorstop OR moveCsp.Error OR csv.Error OR cst.Error) AND step <> 90 THEN
  IF step > 0 THEN errors := errors + 1; END_IF
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
    moveCsp(Axis := drive, Execute := TRUE, Position := 1000.0, Velocity := 500.0, Acceleration := 2000.0,
         Jerk := 20000.0);
    IF moveCsp.Done THEN
      moveCsp(Axis := drive, Execute := FALSE);
      vel := 0.0;
      elapsed := 0.0;
      step := 30;
    END_IF
  30:
    (* The ramp starts once the drive runs in CSV: the block holds 0 until then. *)
    IF csv.InSync THEN vel := MIN(200.0, vel + 1000.0 * drive.fCycleTime); END_IF
    csv(Axis := drive, Enable := TRUE, Velocity := vel, MaxAcceleration := 1500.0);
    IF vel >= 200.0 THEN elapsed := elapsed + drive.fCycleTime; END_IF
    IF elapsed >= 2.0 THEN step := 35; END_IF
  35:
    vel := MAX(0.0, vel - 1000.0 * drive.fCycleTime);
    csv(Axis := drive, Enable := TRUE, Velocity := vel, MaxAcceleration := 1500.0);
    IF vel = 0.0 AND ABS(drive_Velocity_actual_value) < 2 THEN
      csv(Axis := drive, Enable := FALSE);
      elapsed := 0.0;
      step := 40;
    END_IF
  40:
    (* 0.3 s of +20 per mille, 0.3 s of -20, then 0 *)
    elapsed := elapsed + drive.fCycleTime;
    IF elapsed < 0.3 THEN
      cst(Axis := drive, Enable := TRUE, Torque := 20.0);
    ELSIF elapsed < 0.6 THEN
      cst(Axis := drive, Enable := TRUE, Torque := -20.0);
    ELSE
      cst(Axis := drive, Enable := FALSE);
      vel := 0.0;
      step := 50;
    END_IF
  50:
    (* Stand still in CSV until start goes FALSE. *)
    csv(Axis := drive, Enable := start, Velocity := 0.0);
  90:
    (* Release whatever was running, then reset the fault. *)
    home(Axis := drive, Execute := FALSE);
    moveCsp(Axis := drive, Execute := FALSE);
    csv(Axis := drive, Enable := FALSE);
    cst(Axis := drive, Enable := FALSE);
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
