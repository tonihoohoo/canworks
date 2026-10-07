(*
 * config/cia402-drive/drive_cyclic_demo.st against the drive model, with
 * the cyclic blocks of the packaged openplc_canopen library. Run by
 * test/cia402/run.sh. The demo counts its times in task cycles, so one loop
 * pass is one 10 ms cycle and one SYNC.
 *)
TEST 'the cyclic demo powers on, homes, moves in CSP, runs in CSV and steps in CST'
	VAR
		m : main;
		bus : DriveLink;
		f : BOOL;
		i : INT;
		last : DINT;
		jump : DINT;
		maxStep : DINT;
		peak : DINT;
		seen30 : BOOL;
		seen40 : BOOL;
	END_VAR
	FOR i := 1 TO 3000 DO
		last := m.drive_Target_position;
		m();
		bus(ControlWord := m.drive_Controlword, Modes := m.drive_Modes_of_operation,
		    TargetPosition := m.drive_Target_position, TargetVelocity := m.drive_Target_velocity,
		    TargetTorque := m.drive_Target_torque, Fault := f);
		m.drive_Statusword := bus.StatusWord;
		m.drive_Modes_of_operation_display := bus.ModesDisplay;
		m.drive_Position_actual_value := bus.Position;
		m.drive_Velocity_actual_value := bus.Velocity;
		m.drive_Torque_actual_value := bus.Torque;
		m.drive_ok := bus.Online;
		IF m.step = 20 AND m.drive_Modes_of_operation = 8 THEN
			jump := ABS(m.drive_Target_position - last);
			IF jump > maxStep THEN maxStep := jump; END_IF
		END_IF
		IF m.step = 30 THEN
			seen30 := TRUE;
			ASSERT_EQ(bus.Drive.Position >= 999, TRUE);
		END_IF
		IF m.step = 40 THEN
			seen40 := TRUE;
			IF ABS(bus.Velocity) > peak THEN peak := ABS(bus.Velocity); END_IF
		END_IF
		IF m.step = 50 THEN EXIT; END_IF
	END_FOR
	ASSERT_EQ(m.step, 50);
	ASSERT_EQ(m.errors, 0);
	ASSERT_TRUE(seen30 AND seen40);
	(* 500 u/s at 10 ms: at most 5 units per SYNC *)
	ASSERT_TRUE(maxStep > 0 AND maxStep <= 6, 'CSP steps within the velocity');
	(* 0.3 s at 20 per mille x gain 10: 60 u/s *)
	ASSERT_TRUE(peak >= 50 AND peak <= 70, 'CST torque step');
	FOR i := 1 TO 20 DO
		m();
		bus(ControlWord := m.drive_Controlword, Modes := m.drive_Modes_of_operation,
		    TargetPosition := m.drive_Target_position, TargetVelocity := m.drive_Target_velocity,
		    TargetTorque := m.drive_Target_torque, Fault := f);
		m.drive_Statusword := bus.StatusWord;
		m.drive_Modes_of_operation_display := bus.ModesDisplay;
		m.drive_Position_actual_value := bus.Position;
		m.drive_Velocity_actual_value := bus.Velocity;
		m.drive_Torque_actual_value := bus.Torque;
		m.drive_ok := bus.Online;
	END_FOR
	ASSERT_EQ(bus.ModesDisplay, 9);
	ASSERT_EQ(m.drive_Target_velocity, 0);
	ASSERT_TRUE(m.csv.InSync);
END_TEST

TEST 'a fault during the cyclic demo is reset and the sequence starts again'
	VAR
		m : main;
		bus : DriveLink;
		f : BOOL;
		i : INT;
	END_VAR
	FOR i := 1 TO 3000 DO
		f := FALSE;
		IF m.step = 30 AND m.errors = 0 THEN f := TRUE; END_IF
		m();
		bus(ControlWord := m.drive_Controlword, Modes := m.drive_Modes_of_operation,
		    TargetPosition := m.drive_Target_position, TargetVelocity := m.drive_Target_velocity,
		    TargetTorque := m.drive_Target_torque, Fault := f);
		m.drive_Statusword := bus.StatusWord;
		m.drive_Modes_of_operation_display := bus.ModesDisplay;
		m.drive_Position_actual_value := bus.Position;
		m.drive_Velocity_actual_value := bus.Velocity;
		m.drive_Torque_actual_value := bus.Torque;
		m.drive_ok := bus.Online;
		IF m.step = 50 THEN EXIT; END_IF
	END_FOR
	ASSERT_EQ(m.errors, 1);
	ASSERT_EQ(m.step, 50);
	ASSERT_FALSE(m.csv.Error);
END_TEST
