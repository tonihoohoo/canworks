(*
 * CO402_CyclicMoveAbsolute: a point-to-point move in cyclic synchronous
 * position mode (CiA 402 mode 8) on an axis of the editor's PLCopen motion
 * library (spec canopen-cia402-axis). The set-points come from the editor
 * library's S-curve trajectory planner (FB_S7RTT_Plan), one
 * per PLC cycle (Axis.fCycleTime), so the program plans the move instead of
 * the drive.
 *
 * Call it every scan while it is in use, after the axis's drive bridge and
 * with MC_Power enabled. On a rising Execute it sets the target position to
 * the actual position, selects mode 8 (operation stays enabled), plans the
 * move from the actual position at standstill once 0x6061 shows 8, and sends
 * the trajectory's positions. Done: the trajectory has ended and the actual
 * position is within Window of Position (Window 0: one drive increment).
 * Execute FALSE stops writing (the drive holds the last set-point): drop it
 * at standstill or hand the axis to MC_Halt.
 *
 * ErrorID: 1 drive not enabled, 2 mode not reached within ModeTimeout (or
 * left), 4 axis in error stop (fault or drive lost), 5 Velocity,
 * Acceleration or Jerk not above 0, or no trajectory.
 *)
FUNCTION_BLOCK CO402_CyclicMoveAbsolute
VAR_IN_OUT
  Axis : AXIS_REF_SM3;
END_VAR
VAR_INPUT
  Execute : BOOL;
  Position : LREAL;      (* target [u] *)
  Velocity : LREAL;      (* [u/s], above 0 *)
  Acceleration : LREAL;  (* [u/s2], above 0 *)
  Jerk : LREAL;          (* [u/s3], above 0 *)
  Window : LREAL := 0.0; (* in-position window [u], 0 = one increment *)
  ModeTimeout : TIME := T#500ms;
END_VAR
VAR_OUTPUT
  Done : BOOL;
  Busy : BOOL;
  InSync : BOOL;
  Error : BOOL;
  ErrorID : UINT;
END_VAR
VAR
  iState : INT;  (* 0 idle, 10 selecting the mode, 20 moving, 30 done, 99 error *)
  plan : FB_S7RTT_Plan;
  start : ST_MotionState;
  limits : ST_MotionLimits;
  fSet : LREAL;
  fT : LREAL;
  fElapsed : LREAL;
  fDuration : LREAL;
  fWindow : LREAL;
  fActual : LREAL;
  i : INT;
  tMode : TON;
END_VAR
  IF NOT Execute THEN
    iState := 0;
  ELSIF iState = 0 THEN
    ErrorID := 0;
    IF Axis.bError OR NOT Axis.bCommunication THEN
      ErrorID := 4;
    ELSIF (Axis.Drive.StatusWord AND UINT#16#006F) <> UINT#16#0027 THEN
      ErrorID := 1;
    ELSIF Velocity <= 0.0 OR Acceleration <= 0.0 OR Jerk <= 0.0 THEN
      ErrorID := 5;
    ELSE
      Axis.Drive.Target_Position := Axis.Drive.Position_Actual_Value;
      Axis.Drive.Modes_of_operation := SINT#8;
      iState := 10;
    END_IF
    IF ErrorID <> 0 THEN iState := 99; END_IF
  END_IF

  IF iState = 10 OR iState = 20 OR iState = 30 THEN
    IF Axis.bError OR NOT Axis.bCommunication THEN
      ErrorID := 4; iState := 99;
    ELSIF (Axis.Drive.StatusWord AND UINT#16#006F) <> UINT#16#0027 THEN
      ErrorID := 1; iState := 99;
    ELSIF iState <> 10 AND Axis.Drive.Modes_of_operation_display <> SINT#8 THEN
      ErrorID := 2; iState := 99;
    END_IF
  END_IF
  tMode(IN := iState = 10, PT := ModeTimeout);
  fActual := DINT_TO_LREAL(Axis.Drive.Position_Actual_Value) / Axis.fIncPerUnit;
  IF iState = 10 THEN
    Axis.Drive.Modes_of_operation := SINT#8;
    Axis.Drive.Target_Position := Axis.Drive.Position_Actual_Value;
    IF Axis.Drive.Modes_of_operation_display = SINT#8 THEN
      start.fPos := fActual;
      start.fVel := 0.0;
      start.fAcc := 0.0;
      start.fDuration := 0.0;
      limits.fVelMax := Velocity;
      limits.fAccMax := Acceleration;
      limits.fJerkMax := Jerk;
      plan(Execute := FALSE);
      plan(Execute := TRUE, ModeVelocity := FALSE, StartState := start, TargetPos := Position, TargetVel := 0.0,
           Limits := limits);
      fDuration := 0.0;
      FOR i := 1 TO plan.SegmentCount DO
        fDuration := fDuration + plan.Trajectory[i].fDuration;
      END_FOR
      fElapsed := 0.0;
      IF plan.Error THEN
        ErrorID := 5; iState := 99;
      ELSE
        iState := 20;
      END_IF
    ELSIF tMode.Q THEN
      ErrorID := 2; iState := 99;
    END_IF
  END_IF
  IF iState = 20 THEN
    fElapsed := fElapsed + Axis.fCycleTime;
    IF fElapsed >= fDuration OR plan.SegmentCount <= 0 THEN
      Axis.Drive.Target_Position := LREAL_TO_DINT(Position * Axis.fIncPerUnit);
      iState := 30;
    ELSE
      (* the planner's segment at fElapsed: p = p0 + v0 t + a0 t^2/2 + j t^3/6 *)
      fT := fElapsed;
      fSet := Position;
      FOR i := 1 TO plan.SegmentCount DO
        IF fT <= plan.Trajectory[i].fDuration THEN
          fSet := plan.Trajectory[i].fPos + plan.Trajectory[i].fVel * fT + 0.5 * plan.Trajectory[i].fAcc * fT * fT
                  + plan.Trajectory[i].fJerk * fT * fT * fT / 6.0;
          EXIT;
        END_IF
        fT := fT - plan.Trajectory[i].fDuration;
      END_FOR
      Axis.Drive.Target_Position := LREAL_TO_DINT(fSet * Axis.fIncPerUnit);
    END_IF
  END_IF
  IF iState = 30 THEN
    Axis.Drive.Target_Position := LREAL_TO_DINT(Position * Axis.fIncPerUnit);
  END_IF

  fWindow := Window;
  IF fWindow <= 0.0 THEN fWindow := 1.0 / ABS(Axis.fIncPerUnit); END_IF
  Done := iState = 30 AND ABS(fActual - Position) <= fWindow;
  InSync := iState = 20 OR iState = 30;
  Busy := (iState = 10 OR iState = 20 OR iState = 30) AND NOT Done;
  Error := iState = 99;
  IF iState = 0 THEN ErrorID := 0; END_IF
END_FUNCTION_BLOCK
