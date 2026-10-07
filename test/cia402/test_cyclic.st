(*
 * The cyclic synchronous blocks (CO402_Cyclic*, library/openplc_canopen) on
 * the program the project generator writes for
 * config/cia402-drive/canopen_config_cyclic.json (task interval T#10ms, so
 * fCycleTime 0.01), against the drive model. Run by test/cia402/run.sh.
 * Each cycle: the program's scan (bridge), MC_Power and the block under
 * test, one bus cycle (one SYNC: the drive applies this cycle's set-point).
 *)
TEST 'generated lines set the cycle time'
	VAR
		m : main;
	END_VAR
	m();
	ASSERT_NEAR(m.drive.fCycleTime, 0.01, 0.0000001);
END_TEST

TEST 'CO402_CyclicVelocity selects mode 9, follows, and sends 0 when disabled'
	VAR
		m : main;
		bus : DriveLink;
		power : MC_Power;
		fault : BOOL;
		i : INT;
		csv : CO402_CyclicVelocity;
		bit3 : BOOL := TRUE;
	END_VAR
	FOR i := 1 TO 40 DO
		m();
		power(Axis := m.drive, Enable := TRUE);
		bus(ControlWord := m.drive_Controlword, Modes := m.drive_Modes_of_operation,
		    TargetPosition := m.drive_Target_position, TargetVelocity := m.drive_Target_velocity,
		    TargetTorque := m.drive_Target_torque, Fault := fault);
		m.drive_Statusword := bus.StatusWord;
		m.drive_Modes_of_operation_display := bus.ModesDisplay;
		m.drive_Position_actual_value := bus.Position;
		m.drive_Velocity_actual_value := bus.Velocity;
		m.drive_Torque_actual_value := bus.Torque;
		m.drive_ok := bus.Online;
	END_FOR
	ASSERT_TRUE(power.Status, 'powered');
	FOR i := 1 TO 30 DO
		m();
		power(Axis := m.drive, Enable := TRUE);
		csv(Axis := m.drive, Enable := TRUE, Velocity := 1000.0);
		IF (m.drive_Controlword AND 16#08) = 0 THEN bit3 := FALSE; END_IF
		bus(ControlWord := m.drive_Controlword, Modes := m.drive_Modes_of_operation,
		    TargetPosition := m.drive_Target_position, TargetVelocity := m.drive_Target_velocity,
		    TargetTorque := m.drive_Target_torque, Fault := fault);
		m.drive_Statusword := bus.StatusWord;
		m.drive_Modes_of_operation_display := bus.ModesDisplay;
		m.drive_Position_actual_value := bus.Position;
		m.drive_Velocity_actual_value := bus.Velocity;
		m.drive_Torque_actual_value := bus.Torque;
		m.drive_ok := bus.Online;
	END_FOR
	ASSERT_TRUE(bit3, 'enable operation kept while changing the mode');
	ASSERT_TRUE(csv.InSync);
	ASSERT_FALSE(csv.Error);
	ASSERT_EQ(bus.ModesDisplay, 9);
	ASSERT_EQ(m.drive_Target_velocity, 1000);
	ASSERT_EQ(bus.Velocity, 1000);
	m();
	power(Axis := m.drive, Enable := TRUE);
	csv(Axis := m.drive, Enable := FALSE, Velocity := 1000.0);
	ASSERT_EQ(m.drive.Drive.Target_Velocity, 0, 'velocity 0 in the scan Enable goes FALSE');
	ASSERT_FALSE(csv.Busy);
END_TEST

TEST 'CO402_CyclicPosition starts without a jump from the actual position'
	VAR
		m : main;
		bus : DriveLink;
		power : MC_Power;
		fault : BOOL;
		i : INT;
		csv : CO402_CyclicVelocity;
		csp : CO402_CyclicPosition;
		start : DINT;
		jump : BOOL;
		bit3 : BOOL := TRUE;
	END_VAR
	FOR i := 1 TO 40 DO
		m();
		power(Axis := m.drive, Enable := TRUE);
		bus(ControlWord := m.drive_Controlword, Modes := m.drive_Modes_of_operation,
		    TargetPosition := m.drive_Target_position, TargetVelocity := m.drive_Target_velocity,
		    TargetTorque := m.drive_Target_torque, Fault := fault);
		m.drive_Statusword := bus.StatusWord;
		m.drive_Modes_of_operation_display := bus.ModesDisplay;
		m.drive_Position_actual_value := bus.Position;
		m.drive_Velocity_actual_value := bus.Velocity;
		m.drive_Torque_actual_value := bus.Torque;
		m.drive_ok := bus.Online;
	END_FOR
	ASSERT_TRUE(power.Status, 'powered');
	(* move away from 0 in CSV first *)
	FOR i := 1 TO 50 DO
		m();
		power(Axis := m.drive, Enable := TRUE);
		csv(Axis := m.drive, Enable := TRUE, Velocity := 1000.0);
		bus(ControlWord := m.drive_Controlword, Modes := m.drive_Modes_of_operation,
		    TargetPosition := m.drive_Target_position, TargetVelocity := m.drive_Target_velocity,
		    TargetTorque := m.drive_Target_torque, Fault := fault);
		m.drive_Statusword := bus.StatusWord;
		m.drive_Modes_of_operation_display := bus.ModesDisplay;
		m.drive_Position_actual_value := bus.Position;
		m.drive_Velocity_actual_value := bus.Velocity;
		m.drive_Torque_actual_value := bus.Torque;
		m.drive_ok := bus.Online;
	END_FOR
	m();
	power(Axis := m.drive, Enable := TRUE);
	csv(Axis := m.drive, Enable := FALSE);
		bus(ControlWord := m.drive_Controlword, Modes := m.drive_Modes_of_operation,
		    TargetPosition := m.drive_Target_position, TargetVelocity := m.drive_Target_velocity,
		    TargetTorque := m.drive_Target_torque, Fault := fault);
		m.drive_Statusword := bus.StatusWord;
		m.drive_Modes_of_operation_display := bus.ModesDisplay;
		m.drive_Position_actual_value := bus.Position;
		m.drive_Velocity_actual_value := bus.Velocity;
		m.drive_Torque_actual_value := bus.Torque;
		m.drive_ok := bus.Online;
	start := bus.Position;
	ASSERT_GT(start, 400, 'the axis moved in CSV');
	FOR i := 1 TO 30 DO
		m();
		power(Axis := m.drive, Enable := TRUE);
		csp(Axis := m.drive, Enable := TRUE, Position := DINT_TO_LREAL(start), MaxVelocity := 1000.0);
		(* the outputs the bus sees are the previous scan's: count mode 8 only *)
		IF m.drive_Modes_of_operation = 8 AND ABS(m.drive_Target_position - start) > 10 THEN jump := TRUE; END_IF
		IF (m.drive_Controlword AND 16#08) = 0 THEN bit3 := FALSE; END_IF
		bus(ControlWord := m.drive_Controlword, Modes := m.drive_Modes_of_operation,
		    TargetPosition := m.drive_Target_position, TargetVelocity := m.drive_Target_velocity,
		    TargetTorque := m.drive_Target_torque, Fault := fault);
		m.drive_Statusword := bus.StatusWord;
		m.drive_Modes_of_operation_display := bus.ModesDisplay;
		m.drive_Position_actual_value := bus.Position;
		m.drive_Velocity_actual_value := bus.Velocity;
		m.drive_Torque_actual_value := bus.Torque;
		m.drive_ok := bus.Online;
	END_FOR
	ASSERT_FALSE(jump, 'no set-point away from the actual position');
	ASSERT_TRUE(bit3, 'enable operation kept while changing the mode');
	ASSERT_TRUE(csp.InSync);
	ASSERT_FALSE(csp.Error);
	ASSERT_EQ(bus.ModesDisplay, 8);
	ASSERT_EQ(m.drive_Target_position, start);
	(* follow a ramp of 5 increments per cycle, within the limit of 10 *)
	FOR i := 1 TO 20 DO
		m();
		power(Axis := m.drive, Enable := TRUE);
		csp(Axis := m.drive, Enable := TRUE, Position := DINT_TO_LREAL(start + 5 * i), MaxVelocity := 1000.0);
		bus(ControlWord := m.drive_Controlword, Modes := m.drive_Modes_of_operation,
		    TargetPosition := m.drive_Target_position, TargetVelocity := m.drive_Target_velocity,
		    TargetTorque := m.drive_Target_torque, Fault := fault);
		m.drive_Statusword := bus.StatusWord;
		m.drive_Modes_of_operation_display := bus.ModesDisplay;
		m.drive_Position_actual_value := bus.Position;
		m.drive_Velocity_actual_value := bus.Velocity;
		m.drive_Torque_actual_value := bus.Torque;
		m.drive_ok := bus.Online;
	END_FOR
	ASSERT_FALSE(csp.Error);
	ASSERT_EQ(m.drive.Drive.Target_Position, start + 100);
	ASSERT_EQ(bus.Position, start + 95, 'the drive is one scan behind (outputs go out with the next scan)');
END_TEST

TEST 'CO402_CyclicPosition refuses a step above its limit and holds the set-point'
	VAR
		m : main;
		bus : DriveLink;
		power : MC_Power;
		fault : BOOL;
		i : INT;
		csp : CO402_CyclicPosition;
	END_VAR
	FOR i := 1 TO 40 DO
		m();
		power(Axis := m.drive, Enable := TRUE);
		bus(ControlWord := m.drive_Controlword, Modes := m.drive_Modes_of_operation,
		    TargetPosition := m.drive_Target_position, TargetVelocity := m.drive_Target_velocity,
		    TargetTorque := m.drive_Target_torque, Fault := fault);
		m.drive_Statusword := bus.StatusWord;
		m.drive_Modes_of_operation_display := bus.ModesDisplay;
		m.drive_Position_actual_value := bus.Position;
		m.drive_Velocity_actual_value := bus.Velocity;
		m.drive_Torque_actual_value := bus.Torque;
		m.drive_ok := bus.Online;
	END_FOR
	ASSERT_TRUE(power.Status, 'powered');
	FOR i := 1 TO 20 DO
		m();
		power(Axis := m.drive, Enable := TRUE);
		csp(Axis := m.drive, Enable := TRUE, Position := 0.0, MaxVelocity := 1000.0);
		bus(ControlWord := m.drive_Controlword, Modes := m.drive_Modes_of_operation,
		    TargetPosition := m.drive_Target_position, TargetVelocity := m.drive_Target_velocity,
		    TargetTorque := m.drive_Target_torque, Fault := fault);
		m.drive_Statusword := bus.StatusWord;
		m.drive_Modes_of_operation_display := bus.ModesDisplay;
		m.drive_Position_actual_value := bus.Position;
		m.drive_Velocity_actual_value := bus.Velocity;
		m.drive_Torque_actual_value := bus.Torque;
		m.drive_ok := bus.Online;
	END_FOR
	ASSERT_TRUE(csp.InSync);
	m();
	power(Axis := m.drive, Enable := TRUE);
	csp(Axis := m.drive, Enable := TRUE, Position := 50.0, MaxVelocity := 1000.0);
		bus(ControlWord := m.drive_Controlword, Modes := m.drive_Modes_of_operation,
		    TargetPosition := m.drive_Target_position, TargetVelocity := m.drive_Target_velocity,
		    TargetTorque := m.drive_Target_torque, Fault := fault);
		m.drive_Statusword := bus.StatusWord;
		m.drive_Modes_of_operation_display := bus.ModesDisplay;
		m.drive_Position_actual_value := bus.Position;
		m.drive_Velocity_actual_value := bus.Velocity;
		m.drive_Torque_actual_value := bus.Torque;
		m.drive_ok := bus.Online;
	ASSERT_TRUE(csp.Error);
	ASSERT_EQ(csp.ErrorID, 3);
	ASSERT_EQ(m.drive_Target_position, 0, 'the last set-point is held');
	m();
	csp(Axis := m.drive, Enable := FALSE);
	ASSERT_FALSE(csp.Error, 'Enable FALSE clears the error');
END_TEST

TEST 'CO402_CyclicPosition reports a mode the drive does not take'
	VAR
		m : main;
		bus : DriveLink;
		power : MC_Power;
		fault : BOOL;
		i : INT;
		csp : CO402_CyclicPosition;
	END_VAR
	bus.Drive.ModesSupported := DWORD#16#00000025;  (* profile modes only *)
	FOR i := 1 TO 40 DO
		m();
		power(Axis := m.drive, Enable := TRUE);
		bus(ControlWord := m.drive_Controlword, Modes := m.drive_Modes_of_operation,
		    TargetPosition := m.drive_Target_position, TargetVelocity := m.drive_Target_velocity,
		    TargetTorque := m.drive_Target_torque, Fault := fault);
		m.drive_Statusword := bus.StatusWord;
		m.drive_Modes_of_operation_display := bus.ModesDisplay;
		m.drive_Position_actual_value := bus.Position;
		m.drive_Velocity_actual_value := bus.Velocity;
		m.drive_Torque_actual_value := bus.Torque;
		m.drive_ok := bus.Online;
	END_FOR
	ASSERT_TRUE(power.Status, 'powered');
	FOR i := 1 TO 3 DO
		m();
		power(Axis := m.drive, Enable := TRUE);
		csp(Axis := m.drive, Enable := TRUE, Position := 0.0, ModeTimeout := T#50ms);
		bus(ControlWord := m.drive_Controlword, Modes := m.drive_Modes_of_operation,
		    TargetPosition := m.drive_Target_position, TargetVelocity := m.drive_Target_velocity,
		    TargetTorque := m.drive_Target_torque, Fault := fault);
		m.drive_Statusword := bus.StatusWord;
		m.drive_Modes_of_operation_display := bus.ModesDisplay;
		m.drive_Position_actual_value := bus.Position;
		m.drive_Velocity_actual_value := bus.Velocity;
		m.drive_Torque_actual_value := bus.Torque;
		m.drive_ok := bus.Online;
	END_FOR
	ASSERT_FALSE(csp.Error, 'still waiting for the mode');
	ADVANCE_TIME(T#100ms);
	FOR i := 1 TO 3 DO
		m();
		power(Axis := m.drive, Enable := TRUE);
		csp(Axis := m.drive, Enable := TRUE, Position := 0.0, ModeTimeout := T#50ms);
		bus(ControlWord := m.drive_Controlword, Modes := m.drive_Modes_of_operation,
		    TargetPosition := m.drive_Target_position, TargetVelocity := m.drive_Target_velocity,
		    TargetTorque := m.drive_Target_torque, Fault := fault);
		m.drive_Statusword := bus.StatusWord;
		m.drive_Modes_of_operation_display := bus.ModesDisplay;
		m.drive_Position_actual_value := bus.Position;
		m.drive_Velocity_actual_value := bus.Velocity;
		m.drive_Torque_actual_value := bus.Torque;
		m.drive_ok := bus.Online;
	END_FOR
	ASSERT_TRUE(csp.Error);
	ASSERT_EQ(csp.ErrorID, 2);
END_TEST

TEST 'CO402_CyclicMoveAbsolute plans an S-curve move in CSP'
	VAR
		m : main;
		bus : DriveLink;
		power : MC_Power;
		fault : BOOL;
		i : INT;
		move : CO402_CyclicMoveAbsolute;
		last : DINT;
		step : DINT;
		maxStep : DINT;
		n : INT;
	END_VAR
	FOR i := 1 TO 40 DO
		m();
		power(Axis := m.drive, Enable := TRUE);
		bus(ControlWord := m.drive_Controlword, Modes := m.drive_Modes_of_operation,
		    TargetPosition := m.drive_Target_position, TargetVelocity := m.drive_Target_velocity,
		    TargetTorque := m.drive_Target_torque, Fault := fault);
		m.drive_Statusword := bus.StatusWord;
		m.drive_Modes_of_operation_display := bus.ModesDisplay;
		m.drive_Position_actual_value := bus.Position;
		m.drive_Velocity_actual_value := bus.Velocity;
		m.drive_Torque_actual_value := bus.Torque;
		m.drive_ok := bus.Online;
	END_FOR
	ASSERT_TRUE(power.Status, 'powered');
	FOR i := 1 TO 1000 DO
		m();
		power(Axis := m.drive, Enable := TRUE);
		move(Axis := m.drive, Execute := TRUE, Position := 10000.0, Velocity := 2000.0, Acceleration := 10000.0,
		     Jerk := 100000.0);
		step := ABS(m.drive_Target_position - last);
		IF step > maxStep THEN maxStep := step; END_IF
		last := m.drive_Target_position;
		bus(ControlWord := m.drive_Controlword, Modes := m.drive_Modes_of_operation,
		    TargetPosition := m.drive_Target_position, TargetVelocity := m.drive_Target_velocity,
		    TargetTorque := m.drive_Target_torque, Fault := fault);
		m.drive_Statusword := bus.StatusWord;
		m.drive_Modes_of_operation_display := bus.ModesDisplay;
		m.drive_Position_actual_value := bus.Position;
		m.drive_Velocity_actual_value := bus.Velocity;
		m.drive_Torque_actual_value := bus.Torque;
		m.drive_ok := bus.Online;
		IF move.Done AND n = 0 THEN n := i; END_IF
	END_FOR
	ASSERT_FALSE(move.Error);
	ASSERT_TRUE(move.Done);
	ASSERT_EQ(bus.ModesDisplay, 8);
	ASSERT_EQ(bus.Position, 10000);
	ASSERT_LE(maxStep, 21, 'no step above velocity times cycle time (20) plus rounding');
	ASSERT_GT(n, 500, 'a 10000 move at 2000/s takes over 5 s');
END_TEST

TEST 'CO402_CyclicTorque selects mode 10 and accelerates the axis'
	VAR
		m : main;
		bus : DriveLink;
		power : MC_Power;
		fault : BOOL;
		i : INT;
		cst : CO402_CyclicTorque;
	END_VAR
	FOR i := 1 TO 40 DO
		m();
		power(Axis := m.drive, Enable := TRUE);
		bus(ControlWord := m.drive_Controlword, Modes := m.drive_Modes_of_operation,
		    TargetPosition := m.drive_Target_position, TargetVelocity := m.drive_Target_velocity,
		    TargetTorque := m.drive_Target_torque, Fault := fault);
		m.drive_Statusword := bus.StatusWord;
		m.drive_Modes_of_operation_display := bus.ModesDisplay;
		m.drive_Position_actual_value := bus.Position;
		m.drive_Velocity_actual_value := bus.Velocity;
		m.drive_Torque_actual_value := bus.Torque;
		m.drive_ok := bus.Online;
	END_FOR
	ASSERT_TRUE(power.Status, 'powered');
	FOR i := 1 TO 30 DO
		m();
		power(Axis := m.drive, Enable := TRUE);
		cst(Axis := m.drive, Enable := TRUE, Torque := 100.0);
		bus(ControlWord := m.drive_Controlword, Modes := m.drive_Modes_of_operation,
		    TargetPosition := m.drive_Target_position, TargetVelocity := m.drive_Target_velocity,
		    TargetTorque := m.drive_Target_torque, Fault := fault);
		m.drive_Statusword := bus.StatusWord;
		m.drive_Modes_of_operation_display := bus.ModesDisplay;
		m.drive_Position_actual_value := bus.Position;
		m.drive_Velocity_actual_value := bus.Velocity;
		m.drive_Torque_actual_value := bus.Torque;
		m.drive_ok := bus.Online;
	END_FOR
	ASSERT_TRUE(cst.InSync);
	ASSERT_EQ(bus.ModesDisplay, 10);
	ASSERT_EQ(m.drive_Target_torque, 100);
	ASSERT_EQ(bus.Torque, 100);
	ASSERT_GT(bus.Velocity, 100, 'torque 100 at gain 10 accelerates by 1000/s2');
	m();
	cst(Axis := m.drive, Enable := FALSE);
	ASSERT_EQ(m.drive.Drive.Target_torque, 0);
END_TEST

TEST 'a drive fault stops the cyclic block with error stop'
	VAR
		m : main;
		bus : DriveLink;
		power : MC_Power;
		fault : BOOL;
		i : INT;
		csv : CO402_CyclicVelocity;
	END_VAR
	FOR i := 1 TO 40 DO
		m();
		power(Axis := m.drive, Enable := TRUE);
		bus(ControlWord := m.drive_Controlword, Modes := m.drive_Modes_of_operation,
		    TargetPosition := m.drive_Target_position, TargetVelocity := m.drive_Target_velocity,
		    TargetTorque := m.drive_Target_torque, Fault := fault);
		m.drive_Statusword := bus.StatusWord;
		m.drive_Modes_of_operation_display := bus.ModesDisplay;
		m.drive_Position_actual_value := bus.Position;
		m.drive_Velocity_actual_value := bus.Velocity;
		m.drive_Torque_actual_value := bus.Torque;
		m.drive_ok := bus.Online;
	END_FOR
	ASSERT_TRUE(power.Status, 'powered');
	FOR i := 1 TO 20 DO
		m();
		power(Axis := m.drive, Enable := TRUE);
		csv(Axis := m.drive, Enable := TRUE, Velocity := 500.0);
		bus(ControlWord := m.drive_Controlword, Modes := m.drive_Modes_of_operation,
		    TargetPosition := m.drive_Target_position, TargetVelocity := m.drive_Target_velocity,
		    TargetTorque := m.drive_Target_torque, Fault := fault);
		m.drive_Statusword := bus.StatusWord;
		m.drive_Modes_of_operation_display := bus.ModesDisplay;
		m.drive_Position_actual_value := bus.Position;
		m.drive_Velocity_actual_value := bus.Velocity;
		m.drive_Torque_actual_value := bus.Torque;
		m.drive_ok := bus.Online;
	END_FOR
	ASSERT_TRUE(csv.InSync);
	fault := TRUE;
	FOR i := 1 TO 3 DO
		m();
		power(Axis := m.drive, Enable := TRUE);
		csv(Axis := m.drive, Enable := TRUE, Velocity := 500.0);
		bus(ControlWord := m.drive_Controlword, Modes := m.drive_Modes_of_operation,
		    TargetPosition := m.drive_Target_position, TargetVelocity := m.drive_Target_velocity,
		    TargetTorque := m.drive_Target_torque, Fault := fault);
		m.drive_Statusword := bus.StatusWord;
		m.drive_Modes_of_operation_display := bus.ModesDisplay;
		m.drive_Position_actual_value := bus.Position;
		m.drive_Velocity_actual_value := bus.Velocity;
		m.drive_Torque_actual_value := bus.Torque;
		m.drive_ok := bus.Online;
	END_FOR
	ASSERT_TRUE(csv.Error);
	ASSERT_EQ(csv.ErrorID, 4);
END_TEST

TEST 'a lost drive stops the cyclic block with error stop'
	VAR
		m : main;
		bus : DriveLink;
		power : MC_Power;
		fault : BOOL;
		i : INT;
		csp : CO402_CyclicPosition;
	END_VAR
	FOR i := 1 TO 40 DO
		m();
		power(Axis := m.drive, Enable := TRUE);
		bus(ControlWord := m.drive_Controlword, Modes := m.drive_Modes_of_operation,
		    TargetPosition := m.drive_Target_position, TargetVelocity := m.drive_Target_velocity,
		    TargetTorque := m.drive_Target_torque, Fault := fault);
		m.drive_Statusword := bus.StatusWord;
		m.drive_Modes_of_operation_display := bus.ModesDisplay;
		m.drive_Position_actual_value := bus.Position;
		m.drive_Velocity_actual_value := bus.Velocity;
		m.drive_Torque_actual_value := bus.Torque;
		m.drive_ok := bus.Online;
	END_FOR
	ASSERT_TRUE(power.Status, 'powered');
	FOR i := 1 TO 20 DO
		m();
		power(Axis := m.drive, Enable := TRUE);
		csp(Axis := m.drive, Enable := TRUE, Position := 0.0);
		bus(ControlWord := m.drive_Controlword, Modes := m.drive_Modes_of_operation,
		    TargetPosition := m.drive_Target_position, TargetVelocity := m.drive_Target_velocity,
		    TargetTorque := m.drive_Target_torque, Fault := fault);
		m.drive_Statusword := bus.StatusWord;
		m.drive_Modes_of_operation_display := bus.ModesDisplay;
		m.drive_Position_actual_value := bus.Position;
		m.drive_Velocity_actual_value := bus.Velocity;
		m.drive_Torque_actual_value := bus.Torque;
		m.drive_ok := bus.Online;
	END_FOR
	ASSERT_TRUE(csp.InSync);
	m.drive_ok := FALSE;
	m();
	power(Axis := m.drive, Enable := TRUE);
	csp(Axis := m.drive, Enable := TRUE, Position := 0.0);
	ASSERT_TRUE(csp.Error);
	ASSERT_EQ(csp.ErrorID, 4);
END_TEST
