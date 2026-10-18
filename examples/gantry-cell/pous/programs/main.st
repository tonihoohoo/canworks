(* Gantry cell demo for examples/gantry-cell/canworks/canworks.json (network
   motion: axes x, y, z on nodes 4, 5, 6 in cyclic synchronous position mode,
   the I/O module on node 10, the operator panel on node 11; SYNC from the PLC
   cycle, task interval T#10ms).
   The VAR block down to the demo's variables and the first lines of the body
   are what canworks-deploy --new-project --task-interval T#10ms writes
   for this config, with x_online, y_online and z_online in place of the
   generated x_ok_2, y_ok and z_ok; the rest is the demo. *)
PROGRAM main
  VAR
    can_master_state             : USINT AT %IB20; (* CANopen master state *)
    x_online                     : BOOL AT %IX10.0; (* node x (4): operational *)
    x_emcy                       : WORD AT %IW105; (* node x (4): last EMCY code *)
    x_Statusword                 : UINT AT %IW100; (* node x (4) TPDO1 0x6041:0 Statusword *)
    x_Modes_of_operation_display : SINT AT %IB100; (* node x (4) TPDO1 0x6061:0 Modes of operation display *)
    x_Position_actual_value      : DINT AT %ID100; (* node x (4) TPDO1 0x6064:0 Position actual value *)
    x_Velocity_actual_value      : DINT AT %ID101; (* node x (4) TPDO2 0x606C:0 Velocity actual value *)
    x_Torque_actual_value        : INT AT %IW101; (* node x (4) TPDO2 0x6077:0 Torque actual value *)
    x_Controlword                : UINT AT %QW100; (* node x (4) RPDO1 0x6040:0 Controlword *)
    x_Modes_of_operation         : SINT AT %QB100; (* node x (4) RPDO1 0x6060:0 Modes of operation *)
    x_Target_position            : DINT AT %QD100; (* node x (4) RPDO1 0x607A:0 Target position *)
    x_Target_velocity            : DINT AT %QD101; (* node x (4) RPDO2 0x60FF:0 Target velocity *)
    x_Target_torque              : INT AT %QW101; (* node x (4) RPDO2 0x6071:0 Target torque *)
    x                            : AXIS_REF_SM3; (* node x (4): CiA 402 axis *)
    x_bridge                     : SM_Drive_GenericDS402; (* node x (4): drive bridge of axis x *)
    y_online                     : BOOL AT %IX10.1; (* node y (5): operational *)
    y_emcy                       : WORD AT %IW115; (* node y (5): last EMCY code *)
    y_Statusword                 : UINT AT %IW110; (* node y (5) TPDO1 0x6041:0 Statusword *)
    y_Modes_of_operation_display : SINT AT %IB110; (* node y (5) TPDO1 0x6061:0 Modes of operation display *)
    y_Position_actual_value      : DINT AT %ID110; (* node y (5) TPDO1 0x6064:0 Position actual value *)
    y_Velocity_actual_value      : DINT AT %ID111; (* node y (5) TPDO2 0x606C:0 Velocity actual value *)
    y_Torque_actual_value        : INT AT %IW111; (* node y (5) TPDO2 0x6077:0 Torque actual value *)
    y_Controlword                : UINT AT %QW110; (* node y (5) RPDO1 0x6040:0 Controlword *)
    y_Modes_of_operation         : SINT AT %QB110; (* node y (5) RPDO1 0x6060:0 Modes of operation *)
    y_Target_position            : DINT AT %QD110; (* node y (5) RPDO1 0x607A:0 Target position *)
    y_Target_velocity            : DINT AT %QD111; (* node y (5) RPDO2 0x60FF:0 Target velocity *)
    y_Target_torque              : INT AT %QW111; (* node y (5) RPDO2 0x6071:0 Target torque *)
    y                            : AXIS_REF_SM3; (* node y (5): CiA 402 axis *)
    y_bridge                     : SM_Drive_GenericDS402; (* node y (5): drive bridge of axis y *)
    z_online                     : BOOL AT %IX10.2; (* node z (6): operational *)
    z_emcy                       : WORD AT %IW125; (* node z (6): last EMCY code *)
    z_Statusword                 : UINT AT %IW120; (* node z (6) TPDO1 0x6041:0 Statusword *)
    z_Modes_of_operation_display : SINT AT %IB120; (* node z (6) TPDO1 0x6061:0 Modes of operation display *)
    z_Position_actual_value      : DINT AT %ID120; (* node z (6) TPDO1 0x6064:0 Position actual value *)
    z_Velocity_actual_value      : DINT AT %ID121; (* node z (6) TPDO2 0x606C:0 Velocity actual value *)
    z_Torque_actual_value        : INT AT %IW121; (* node z (6) TPDO2 0x6077:0 Torque actual value *)
    z_Controlword                : UINT AT %QW120; (* node z (6) RPDO1 0x6040:0 Controlword *)
    z_Modes_of_operation         : SINT AT %QB120; (* node z (6) RPDO1 0x6060:0 Modes of operation *)
    z_Target_position            : DINT AT %QD120; (* node z (6) RPDO1 0x607A:0 Target position *)
    z_Target_velocity            : DINT AT %QD121; (* node z (6) RPDO2 0x60FF:0 Target velocity *)
    z_Target_torque              : INT AT %QW121; (* node z (6) RPDO2 0x6071:0 Target torque *)
    z                            : AXIS_REF_SM3; (* node z (6): CiA 402 axis *)
    z_bridge                     : SM_Drive_GenericDS402; (* node z (6): drive bridge of axis z *)
    io_ok                        : BOOL AT %IX10.3; (* node io (10): operational *)
    io_Read_input_8_bit_1        : USINT AT %IB130; (* node io (10) TPDO1 0x6000:1 Read input 8-bit 1 *)
    io_Write_output_8_bit_1      : USINT AT %QB130; (* node io (10) RPDO1 0x6200:1 Write output 8-bit 1 *)
    panel_ok                     : BOOL AT %IX10.4; (* node panel (11): operational *)
    panel_Read_input_8_bit_1     : USINT AT %IB131; (* node panel (11) TPDO1 0x6000:1 Read input 8-bit 1 *)
    panel_Read_input_8_bit_2     : USINT AT %IB132; (* node panel (11) TPDO1 0x6000:2 Read input 8-bit 2 *)
    panel_Write_output_8_bit_1   : USINT AT %QB131; (* node panel (11) RPDO1 0x6200:1 Write output 8-bit 1 *)

    (* The demo: pick parts at the end of the conveyor, place them on the 3 x 3 pallet, change the pallet *)
    powerX, powerY, powerZ    : MC_Power;
    homeX, homeY, homeZ       : MC_Home;
    moveX, moveY, moveZ       : CO402_CyclicMoveAbsolute;
    resetX, resetY, resetZ    : MC_Reset;
    statusX, statusY, statusZ : MC_ReadStatus;
    start      : BOOL := TRUE;   (* set FALSE to stop after the part in hand *)
    conveyor   : BOOL;           (* io output 0: run the infeed conveyor *)
    grip       : BOOL;           (* io output 1: close the gripper *)
    change     : BOOL;           (* io output 2: change the pallet *)
    partAtPick : BOOL;           (* io input 3: a part waits at the pick position *)
    gripped    : BOOL;           (* io input 4: the gripper holds a part *)
    palletReady : BOOL;          (* io input 5: an empty or part-full pallet is in place *)
    slot       : INT;            (* next pallet slot, 0-8 *)
    placed     : INT;            (* parts placed since the start *)
    tx, ty     : LREAL;          (* target of the XY move [mm] *)
    dx, dy, d  : LREAL;
    vel        : LREAL := 600.0;   (* XY path velocity [mm/s] *)
    acc        : LREAL := 4000.0;  (* [mm/s2] *)
    jerk       : LREAL := 40000.0; (* [mm/s3] *)
    elapsed    : LREAL;          (* time in the step [s], counted in task cycles *)
    tries      : INT;
    errors     : INT;            (* faults seen after the start *)
    homed      : BOOL;           (* the three axes are homed *)
    speed      : LREAL;          (* vel, cut to a quarter while someone is in the scanner's warning field *)
    step       : INT;            (* 0 power on, 5 homing mode, 10 home Z, 12 home X and Y, 20 wait for a part,
                                    30 XY to the pick position, 40 Z down, 45 grip, 50 Z up and XY to the slot,
                                    60 Z down, 65 release, 70 Z up, 80 pallet change, 85 wait for the empty pallet,
                                    90 fault reset, 95 recover *)

    (* Manual mode and safety: the operator panel (node 11) and the safety relay's feedback (io input 6) *)
    jogX, jogY, jogZ : CO402_CyclicPosition;
    manual     : BOOL;           (* panel 0x6000:1 bit 0: the mode switch on MANUAL *)
    jogXp, jogXm, jogYp, jogYm, jogZup, jogZdown, fast : BOOL;  (* panel 0x6000:1 bits 1-7 *)
    bGrip, bConveyor, bHome, bStart, bStop, bReset, bEnable, estop : BOOL;  (* panel 0x6000:2 bits 0-7 *)
    safetyOk   : BOOL;           (* io input 6: the safety relay is closed *)
    scannerWarning : BOOL;       (* io input 7: someone in the scanner's warning field *)
    autoRun    : BOOL := TRUE;   (* the sequence may run: cleared by MANUAL and a safety stop, set by Start *)
    hold       : BOOL;           (* the sequence is held and the axes are the jog's *)
    wasHold, wasSafetyOk, wasManual : BOOL;
    pGrip, pConveyor, pHome, pStart, pReset : BOOL;  (* the buttons in the last scan, for edges *)
    needEnable : BOOL := FALSE;  (* TRUE: jog only while Enable is held as well *)
    manualConveyor : BOOL;
    mstep      : INT;            (* manual homing: 0 none, 1 homing mode, 2 home Z, 3 home X and Y *)
    jx, jy, jz : LREAL;          (* jog set-points [mm] *)
    vx, vy, vz : LREAL;          (* jog velocities [mm/s] *)
    jEnX, jEnY, jEnZ : BOOL;     (* the jog blocks' Enable in the last scan *)
    jogV, jogA, jt : LREAL;
    jogSlow    : LREAL := 20.0;    (* [mm/s] *)
    jogFast    : LREAL := 150.0;   (* [mm/s] *)
    jogAcc     : LREAL := 1000.0;  (* [mm/s2] *)
    stopDec    : LREAL := 4000.0;  (* the safety stop's ramp [mm/s2]: 600 mm/s stop in 150 ms *)
    blink      : LREAL;
    stopT      : LREAL := 1.0;   (* [s] since the safety relay tripped *)
    powerOn    : BOOL;           (* the drives stay powered for the controlled stop *)
  END_VAR

(* CiA 402 axes from canworks/canworks.json: keep these lines first *)
x.iRatioTechUnitsNum := DINT#1000;
x.dwRatioTechUnitsDenom := DWORD#1;
x.fScalefactor := LREAL#1.0;
x.fCycleTime := LREAL#0.01; (* the task interval: change it with the interval *)
x_bridge(Axis := x,
         wStatusWord := x_Statusword,
         siModesDisplay := x_Modes_of_operation_display,
         diActualPosition := x_Position_actual_value,
         diActualVelocity := x_Velocity_actual_value,
         iActualTorque := x_Torque_actual_value,
         bOnline := x_online,
         wControlWord => x_Controlword,
         siModes => x_Modes_of_operation,
         diTargetPosition => x_Target_position,
         diTargetVelocity => x_Target_velocity,
         iTargetTorque => x_Target_torque);
y.iRatioTechUnitsNum := DINT#1000;
y.dwRatioTechUnitsDenom := DWORD#1;
y.fScalefactor := LREAL#1.0;
y.fCycleTime := LREAL#0.01; (* the task interval: change it with the interval *)
y_bridge(Axis := y,
         wStatusWord := y_Statusword,
         siModesDisplay := y_Modes_of_operation_display,
         diActualPosition := y_Position_actual_value,
         diActualVelocity := y_Velocity_actual_value,
         iActualTorque := y_Torque_actual_value,
         bOnline := y_online,
         wControlWord => y_Controlword,
         siModes => y_Modes_of_operation,
         diTargetPosition => y_Target_position,
         diTargetVelocity => y_Target_velocity,
         iTargetTorque => y_Target_torque);
z.iRatioTechUnitsNum := DINT#1000;
z.dwRatioTechUnitsDenom := DWORD#1;
z.fScalefactor := LREAL#1.0;
z.fCycleTime := LREAL#0.01; (* the task interval: change it with the interval *)
z_bridge(Axis := z,
         wStatusWord := z_Statusword,
         siModesDisplay := z_Modes_of_operation_display,
         diActualPosition := z_Position_actual_value,
         diActualVelocity := z_Velocity_actual_value,
         iActualTorque := z_Torque_actual_value,
         bOnline := z_online,
         wControlWord => z_Controlword,
         siModes => z_Modes_of_operation,
         diTargetPosition => z_Target_position,
         diTargetVelocity => z_Target_velocity,
         iTargetTorque => z_Target_torque);

(* Demo: home the three axes (Z first), then pick each part the conveyor
   brings to its end stop and place it in the next slot of the 3 x 3 pallet;
   with the pallet full, change it. XY moves are straight lines: both axes
   get the same S-curve scaled to their share of the distance, so they start
   and arrive together. Z starts down when XY is near its target and XY
   starts as soon as Z is clear of the parts. A drive fault (a jam, a hard
   stop) resets the axes after 2 s and recovers: Z up, then on with
   the part in hand or back to the conveyor. *)
partAtPick := (io_Read_input_8_bit_1 AND USINT#16#08) <> 0;
gripped := (io_Read_input_8_bit_1 AND USINT#16#10) <> 0;
palletReady := (io_Read_input_8_bit_1 AND USINT#16#20) <> 0;

manual := (panel_Read_input_8_bit_1 AND USINT#16#01) <> 0;
jogXp := (panel_Read_input_8_bit_1 AND USINT#16#02) <> 0;
jogXm := (panel_Read_input_8_bit_1 AND USINT#16#04) <> 0;
jogYp := (panel_Read_input_8_bit_1 AND USINT#16#08) <> 0;
jogYm := (panel_Read_input_8_bit_1 AND USINT#16#10) <> 0;
jogZup := (panel_Read_input_8_bit_1 AND USINT#16#20) <> 0;
jogZdown := (panel_Read_input_8_bit_1 AND USINT#16#40) <> 0;
fast := (panel_Read_input_8_bit_1 AND USINT#16#80) <> 0;
bGrip := (panel_Read_input_8_bit_2 AND USINT#16#01) <> 0;
bConveyor := (panel_Read_input_8_bit_2 AND USINT#16#02) <> 0;
bHome := (panel_Read_input_8_bit_2 AND USINT#16#04) <> 0;
bStart := (panel_Read_input_8_bit_2 AND USINT#16#08) <> 0;
bStop := (panel_Read_input_8_bit_2 AND USINT#16#10) <> 0;
bReset := (panel_Read_input_8_bit_2 AND USINT#16#20) <> 0;
bEnable := (panel_Read_input_8_bit_2 AND USINT#16#40) <> 0;
estop := (panel_Read_input_8_bit_2 AND USINT#16#80) <> 0;
safetyOk := (io_Read_input_8_bit_1 AND USINT#16#40) <> 0;
scannerWarning := (io_Read_input_8_bit_1 AND USINT#16#80) <> 0;

(* MANUAL or a safety stop holds the sequence, and only Start lets it go on.
   Before the I/O module is up the relay's feedback reads off: that is no stop. *)
IF (manual AND NOT wasManual) OR (wasSafetyOk AND NOT safetyOk) THEN autoRun := FALSE; END_IF
IF bStart AND NOT pStart AND NOT manual AND safetyOk THEN autoRun := TRUE; start := TRUE; END_IF
IF bStop THEN start := FALSE; END_IF
hold := manual OR NOT safetyOk OR NOT autoRun;
IF scannerWarning THEN speed := vel * 0.25; ELSE speed := vel; END_IF

(* A tripped relay gives the drives 300 ms to stop before it takes their power
   stage away: the program ramps the axes down within 250 ms, then disables
   them, and powers them again once the relay is closed *)
IF safetyOk THEN stopT := 0.0; ELSE stopT := stopT + x.fCycleTime; END_IF
powerOn := safetyOk OR stopT < 0.25;
powerX(Axis := x, Enable := powerOn AND (step <> 90 OR hold));
powerY(Axis := y, Enable := powerOn AND (step <> 90 OR hold));
powerZ(Axis := z, Enable := powerOn AND (step <> 90 OR hold));
statusX(Axis := x, Enable := TRUE);
statusY(Axis := y, Enable := TRUE);
statusZ(Axis := z, Enable := TRUE);
IF (statusX.Errorstop OR statusY.Errorstop OR statusZ.Errorstop OR moveX.Error OR moveY.Error OR moveZ.Error)
   AND step > 0 AND step <> 90 AND NOT hold THEN
  errors := errors + 1;
  elapsed := 0.0;
  tries := 0;
  step := 90;
END_IF
elapsed := elapsed + x.fCycleTime;

(* Held: the moves of the sequence stop writing and the jog takes the axes,
   starting from where they are at the speed they have, so a running move
   ramps down. The jog ramps to its speed while exactly one button of an axis
   is held: slow, or fast with Fast; slow and without soft limits before
   homing. A safety stop ramps everything down at stopDec. *)
IF hold THEN
  IF NOT wasHold THEN
    moveX(Axis := x, Execute := FALSE);
    moveY(Axis := y, Execute := FALSE);
    moveZ(Axis := z, Execute := FALSE);
    homeX(Axis := x, Execute := FALSE);
    homeY(Axis := y, Execute := FALSE);
    homeZ(Axis := z, Execute := FALSE);
    manualConveyor := FALSE;
    mstep := 0;
  END_IF
  IF NOT manual OR NOT safetyOk THEN
    IF mstep <> 0 THEN
      homeX(Axis := x, Execute := FALSE);
      homeY(Axis := y, Execute := FALSE);
      homeZ(Axis := z, Execute := FALSE);
      mstep := 0;
    END_IF
    manualConveyor := FALSE;
  END_IF
  IF manual AND safetyOk THEN
    IF bGrip AND NOT pGrip THEN grip := NOT grip; END_IF
    IF bConveyor AND NOT pConveyor THEN manualConveyor := NOT manualConveyor; END_IF
    IF bHome AND NOT pHome AND mstep = 0 THEN homed := FALSE; mstep := 1; END_IF
  END_IF
  resetX(Axis := x, Execute := bReset AND statusX.Errorstop);
  resetY(Axis := y, Execute := bReset AND statusY.Errorstop);
  resetZ(Axis := z, Execute := bReset AND statusZ.Errorstop);

  (* Homing from the panel: Z first, then X and Y *)
  CASE mstep OF
    1:
      x.Drive.Modes_of_operation := 6;
      y.Drive.Modes_of_operation := 6;
      z.Drive.Modes_of_operation := 6;
      IF x.byRealControllerMode = 6 AND y.byRealControllerMode = 6 AND z.byRealControllerMode = 6 THEN mstep := 2; END_IF
    2:
      homeZ(Axis := z, Execute := TRUE, Position := 0.0);
      IF homeZ.Done THEN homeZ(Axis := z, Execute := FALSE); mstep := 3; END_IF
    3:
      homeX(Axis := x, Execute := TRUE, Position := 0.0);
      homeY(Axis := y, Execute := TRUE, Position := 0.0);
      IF homeX.Done AND homeY.Done THEN
        homeX(Axis := x, Execute := FALSE);
        homeY(Axis := y, Execute := FALSE);
        homed := TRUE;
        mstep := 0;
      END_IF
  END_CASE
END_IF

(* The jog, one axis after the other: target velocity, ramp, soft limits, set-point *)
IF homed THEN jogV := SEL(fast, jogSlow, jogFast); ELSE jogV := jogSlow; END_IF
IF NOT manual OR NOT safetyOk OR (needEnable AND NOT bEnable) THEN jogV := 0.0; END_IF
IF safetyOk THEN jogA := jogAcc; ELSE jogA := stopDec; END_IF

jogX.Enable := hold AND mstep = 0 AND powerX.Status;
IF jogX.Enable AND NOT jEnX THEN
  jx := DINT_TO_LREAL(x_Position_actual_value) / 1000.0;
  vx := DINT_TO_LREAL(x_Velocity_actual_value) / 1000.0;
END_IF
jt := 0.0;
IF jogXp AND NOT jogXm THEN jt := jogV; ELSIF jogXm AND NOT jogXp THEN jt := -jogV; END_IF
IF homed THEN
  jt := MIN(jt, SQRT(MAX(2.0 * jogA * (900.0 - jx), 0.0)));
  jt := MAX(jt, -SQRT(MAX(2.0 * jogA * jx, 0.0)));
END_IF
IF vx < jt THEN vx := MIN(jt, vx + jogA * x.fCycleTime); ELSE vx := MAX(jt, vx - jogA * x.fCycleTime); END_IF
jx := jx + vx * x.fCycleTime;
IF homed THEN jx := LIMIT(0.0, jx, 900.0); END_IF
jogX(Axis := x, Enable := jogX.Enable, Position := jx, MaxVelocity := 700.0);
jEnX := jogX.Enable;

jogY.Enable := hold AND mstep = 0 AND powerY.Status;
IF jogY.Enable AND NOT jEnY THEN
  jy := DINT_TO_LREAL(y_Position_actual_value) / 1000.0;
  vy := DINT_TO_LREAL(y_Velocity_actual_value) / 1000.0;
END_IF
jt := 0.0;
IF jogYp AND NOT jogYm THEN jt := jogV; ELSIF jogYm AND NOT jogYp THEN jt := -jogV; END_IF
IF homed THEN
  jt := MIN(jt, SQRT(MAX(2.0 * jogA * (600.0 - jy), 0.0)));
  jt := MAX(jt, -SQRT(MAX(2.0 * jogA * jy, 0.0)));
END_IF
IF vy < jt THEN vy := MIN(jt, vy + jogA * y.fCycleTime); ELSE vy := MAX(jt, vy - jogA * y.fCycleTime); END_IF
jy := jy + vy * y.fCycleTime;
IF homed THEN jy := LIMIT(0.0, jy, 600.0); END_IF
jogY(Axis := y, Enable := jogY.Enable, Position := jy, MaxVelocity := 700.0);
jEnY := jogY.Enable;

(* Z: positive is down *)
jogZ.Enable := hold AND mstep = 0 AND powerZ.Status;
IF jogZ.Enable AND NOT jEnZ THEN
  jz := DINT_TO_LREAL(z_Position_actual_value) / 1000.0;
  vz := DINT_TO_LREAL(z_Velocity_actual_value) / 1000.0;
END_IF
jt := 0.0;
IF jogZdown AND NOT jogZup THEN jt := jogV; ELSIF jogZup AND NOT jogZdown THEN jt := -jogV; END_IF
IF homed THEN
  jt := MIN(jt, SQRT(MAX(2.0 * jogA * (300.0 - jz), 0.0)));
  jt := MAX(jt, -SQRT(MAX(2.0 * jogA * jz, 0.0)));
END_IF
IF vz < jt THEN vz := MIN(jt, vz + jogA * z.fCycleTime); ELSE vz := MAX(jt, vz - jogA * z.fCycleTime); END_IF
jz := jz + vz * z.fCycleTime;
IF homed THEN jz := LIMIT(0.0, jz, 300.0); END_IF
jogZ(Axis := z, Enable := jogZ.Enable, Position := jz, MaxVelocity := 700.0);
jEnZ := jogZ.Enable;

(* Let go: Z up and on with the part in hand (step 95), a part release or a
   pallet change where it was, or homing first when the axes are not homed *)
IF wasHold AND NOT hold THEN
  elapsed := 0.0;
  IF NOT homed THEN
    step := 0;
  ELSIF step <> 65 AND step <> 80 AND step <> 85 THEN
    step := 95;
  END_IF
END_IF

IF NOT hold THEN
CASE step OF
  0:
    IF powerX.Status AND powerY.Status AND powerZ.Status AND start THEN step := 5; END_IF
  5:
    x.Drive.Modes_of_operation := 6;
    y.Drive.Modes_of_operation := 6;
    z.Drive.Modes_of_operation := 6;
    IF x.byRealControllerMode = 6 AND y.byRealControllerMode = 6 AND z.byRealControllerMode = 6 THEN step := 10; END_IF
  10:
    homeZ(Axis := z, Execute := TRUE, Position := 0.0);
    IF homeZ.Done THEN homeZ(Axis := z, Execute := FALSE); step := 12; END_IF
  12:
    homeX(Axis := x, Execute := TRUE, Position := 0.0);
    homeY(Axis := y, Execute := TRUE, Position := 0.0);
    IF homeX.Done AND homeY.Done THEN
      homeX(Axis := x, Execute := FALSE);
      homeY(Axis := y, Execute := FALSE);
      homed := TRUE;
      step := 20;
    END_IF
  20:
    IF partAtPick AND palletReady AND start THEN
      tx := 80.0; ty := 480.0;
      step := 30;
    END_IF
  30:
    IF moveX.Done AND moveY.Done THEN
      moveX(Axis := x, Execute := FALSE);
      moveY(Axis := y, Execute := FALSE);
      step := 40;
    END_IF
  40:
    moveZ(Axis := z, Execute := TRUE, Position := 268.0, Velocity := speed, Acceleration := acc, Jerk := jerk, Window := 0.05);
    IF moveZ.Done THEN moveZ(Axis := z, Execute := FALSE); elapsed := 0.0; step := 45; END_IF
  45:
    grip := TRUE;
    IF gripped THEN
      tx := 500.0 + 120.0 * INT_TO_LREAL(slot MOD 3);
      ty := 120.0 + 120.0 * INT_TO_LREAL(slot / 3);
      step := 50;
    ELSIF elapsed > 1.0 THEN
      grip := FALSE;  (* missed: try the next part *)
      step := 70;
    END_IF
  50:
    (* Z up; XY leaves as soon as the part is clear of the conveyor and its neighbours *)
    moveZ(Axis := z, Execute := TRUE, Position := 0.0, Velocity := speed, Acceleration := acc, Jerk := jerk, Window := 0.05);
    IF moveZ.Done THEN moveZ(Axis := z, Execute := FALSE); END_IF
    IF DINT_TO_LREAL(z_Position_actual_value) / 1000.0 < 180.0 AND step = 50 THEN step := 55; END_IF
  55:
    moveZ(Axis := z, Execute := NOT moveZ.Done AND moveZ.Busy, Position := 0.0, Velocity := speed, Acceleration := acc,
          Jerk := jerk, Window := 0.05);
    IF moveX.Done AND moveY.Done AND NOT moveZ.Busy THEN
      moveX(Axis := x, Execute := FALSE);
      moveY(Axis := y, Execute := FALSE);
      step := 60;
    END_IF
  60:
    moveZ(Axis := z, Execute := TRUE, Position := 287.0, Velocity := speed, Acceleration := acc, Jerk := jerk, Window := 0.05);
    IF moveZ.Done THEN moveZ(Axis := z, Execute := FALSE); elapsed := 0.0; step := 65; END_IF
  65:
    grip := FALSE;
    IF elapsed > 0.2 THEN
      placed := placed + 1;
      slot := slot + 1;
      step := 70;
    END_IF
  70:
    moveZ(Axis := z, Execute := TRUE, Position := 0.0, Velocity := speed, Acceleration := acc, Jerk := jerk, Window := 0.05);
    IF moveZ.Done THEN
      moveZ(Axis := z, Execute := FALSE);
      IF slot >= 9 THEN step := 80; ELSE step := 20; END_IF
    END_IF
  80:
    change := TRUE;
    IF NOT palletReady THEN step := 85; END_IF  (* the full pallet leaves *)
  85:
    IF palletReady THEN  (* an empty pallet is in place *)
      change := FALSE;
      slot := 0;
      step := 20;
    END_IF
  90:
    (* Release whatever was running, then reset the faults. *)
    homeX(Axis := x, Execute := FALSE);
    homeY(Axis := y, Execute := FALSE);
    homeZ(Axis := z, Execute := FALSE);
    moveX(Axis := x, Execute := FALSE);
    moveY(Axis := y, Execute := FALSE);
    moveZ(Axis := z, Execute := FALSE);
    change := FALSE;
    (* Wait 2 s in the fault first, so a jam that is still there shows as a fault
       and not as a reset every half second. A drive takes a fault reset on a
       rising edge, so then retry every 50 scans while the fault is still there. *)
    IF elapsed > 2.0 THEN
      tries := tries + 1;
    END_IF
    resetX(Axis := x, Execute := tries > 0 AND tries < 50);
    resetY(Axis := y, Execute := tries > 0 AND tries < 50);
    resetZ(Axis := z, Execute := tries > 0 AND tries < 50);
    IF tries >= 50 THEN tries := 1; END_IF
    IF resetX.Done AND resetY.Done AND resetZ.Done AND x.bCommunication AND y.bCommunication AND z.bCommunication THEN
      resetX(Axis := x, Execute := FALSE);
      resetY(Axis := y, Execute := FALSE);
      resetZ(Axis := z, Execute := FALSE);
      tries := 0;
      elapsed := 0.0;
      step := 95;
    END_IF
  95:
    (* Powered again: Z up, then on with the part in hand, or back to the conveyor;
       not homed yet: home again *)
    IF NOT homed THEN
      step := 0;
    ELSIF elapsed > 5.0 THEN
      (* Z did not get up: a jam closer to the target than the following
         error window (0x6065) does not fault the drive. Power off and retry. *)
      moveZ(Axis := z, Execute := FALSE);
      errors := errors + 1;
      elapsed := 0.0;
      step := 90;
    ELSIF powerX.Status AND powerY.Status AND powerZ.Status THEN
      moveZ(Axis := z, Execute := TRUE, Position := 0.0, Velocity := 200.0, Acceleration := acc, Jerk := jerk, Window := 0.05);
      IF moveZ.Done THEN
        moveZ(Axis := z, Execute := FALSE);
        IF gripped THEN
          tx := 500.0 + 120.0 * INT_TO_LREAL(slot MOD 3);
          ty := 120.0 + 120.0 * INT_TO_LREAL(slot / 3);
          step := 55;
        ELSE
          grip := FALSE;
          step := 20;
        END_IF
      END_IF
    END_IF
END_CASE
END_IF

(* The XY move of steps 30 and 55: one S-curve scaled per axis, so the path is a straight line *)
IF (step = 30 OR step = 55) AND NOT hold THEN
  dx := tx - DINT_TO_LREAL(x_Position_actual_value) / 1000.0;
  dy := ty - DINT_TO_LREAL(y_Position_actual_value) / 1000.0;
  IF NOT moveX.Busy AND NOT moveY.Busy AND NOT moveX.Done AND NOT moveY.Done THEN
    d := SQRT(dx * dx + dy * dy);
  END_IF
  IF d < 0.1 THEN d := 0.1; END_IF
  moveX(Axis := x, Execute := TRUE, Position := tx, Velocity := MAX(speed * ABS(dx) / d, 1.0),
        Acceleration := MAX(acc * ABS(dx) / d, 10.0), Jerk := MAX(jerk * ABS(dx) / d, 100.0), Window := 0.05);
  moveY(Axis := y, Execute := TRUE, Position := ty, Velocity := MAX(speed * ABS(dy) / d, 1.0),
        Acceleration := MAX(acc * ABS(dy) / d, 10.0), Jerk := MAX(jerk * ABS(dy) / d, 100.0), Window := 0.05);
END_IF

IF hold THEN conveyor := manualConveyor; ELSE conveyor := start AND step <> 90; END_IF
io_Write_output_8_bit_1 := SEL(conveyor, USINT#0, USINT#1) OR SEL(grip, USINT#0, USINT#2) OR SEL(change, USINT#0, USINT#4);

(* Panel lamps: MANUAL, homed, fault (blinking while the safety relay is open), auto running *)
blink := blink + x.fCycleTime;
IF blink >= 1.0 THEN blink := 0.0; END_IF
panel_Write_output_8_bit_1 := SEL(manual, USINT#0, USINT#1) OR SEL(homed, USINT#0, USINT#2)
  OR SEL((statusX.Errorstop OR statusY.Errorstop OR statusZ.Errorstop) OR (NOT safetyOk AND blink < 0.5), USINT#0, USINT#4)
  OR SEL(NOT hold, USINT#0, USINT#8);

wasHold := hold;
wasManual := manual;
wasSafetyOk := safetyOk;
pGrip := bGrip;
pConveyor := bConveyor;
pHome := bHome;
pStart := bStart;
pReset := bReset;

END_PROGRAM
