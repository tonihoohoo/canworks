(*
 * config/cia402-drive/drive_demo.st against the drive model. Run by
 * test/cia402/run.sh. Time stands still inside a loop (the test runner
 * advances it only between statements), so the 2 s run step is crossed with
 * ADVANCE_TIME between two loops.
 *)
TEST 'the demo powers on, homes, moves, runs and halts'
	VAR
		m : main;
		bus : DriveLink;
		i : INT;
	END_VAR
	FOR i := 1 TO 400 DO
		m();
		bus(ControlWord := m.drive_Controlword, Modes := m.drive_Modes_of_operation,
		    TargetPosition := m.drive_Target_position, ProfileVelocity := m.drive_Profile_velocity,
		    TargetVelocity := m.drive_Target_velocity);
		m.drive_Statusword := bus.StatusWord;
		m.drive_Modes_of_operation_display := bus.ModesDisplay;
		m.drive_Position_actual_value := bus.Position;
		m.drive_Velocity_actual_value := bus.Velocity;
		m.drive_ok := bus.Online;
		IF m.step = 30 THEN EXIT; END_IF
	END_FOR
	ASSERT_EQ(m.step, 30);
	ASSERT_TRUE(m.home.Done OR m.moveAbs.Done);
	ASSERT_EQ(bus.Drive.Position, 1000);
	FOR i := 1 TO 50 DO
		m();
		bus(ControlWord := m.drive_Controlword, Modes := m.drive_Modes_of_operation,
		    TargetPosition := m.drive_Target_position, ProfileVelocity := m.drive_Profile_velocity,
		    TargetVelocity := m.drive_Target_velocity);
		m.drive_Statusword := bus.StatusWord;
		m.drive_Modes_of_operation_display := bus.ModesDisplay;
		m.drive_Position_actual_value := bus.Position;
		m.drive_Velocity_actual_value := bus.Velocity;
		m.drive_ok := bus.Online;
	END_FOR
	ASSERT_EQ(m.drive_Modes_of_operation, 3);
	ASSERT_EQ(bus.Velocity, 200);
	ADVANCE_TIME(2100000000);
	FOR i := 1 TO 100 DO
		m();
		bus(ControlWord := m.drive_Controlword, Modes := m.drive_Modes_of_operation,
		    TargetPosition := m.drive_Target_position, ProfileVelocity := m.drive_Profile_velocity,
		    TargetVelocity := m.drive_Target_velocity);
		m.drive_Statusword := bus.StatusWord;
		m.drive_Modes_of_operation_display := bus.ModesDisplay;
		m.drive_Position_actual_value := bus.Position;
		m.drive_Velocity_actual_value := bus.Velocity;
		m.drive_ok := bus.Online;
		IF m.step = 50 THEN EXIT; END_IF
	END_FOR
	ASSERT_EQ(m.step, 50);
	ASSERT_EQ(bus.Velocity, 0);
	ASSERT_TRUE(m.status.StandStill);
END_TEST

TEST 'a fault during the demo is reset and the sequence starts again'
	VAR
		m : main;
		bus : DriveLink;
		i : INT;
	END_VAR
	VAR
		f : BOOL;
	END_VAR
	FOR i := 1 TO 600 DO
		f := i >= 60 AND i < 70;
		m();
		bus(ControlWord := m.drive_Controlword, Modes := m.drive_Modes_of_operation,
		    TargetPosition := m.drive_Target_position, ProfileVelocity := m.drive_Profile_velocity,
		    TargetVelocity := m.drive_Target_velocity, Fault := f);
		m.drive_Statusword := bus.StatusWord;
		m.drive_Modes_of_operation_display := bus.ModesDisplay;
		m.drive_Position_actual_value := bus.Position;
		m.drive_Velocity_actual_value := bus.Velocity;
		m.drive_ok := bus.Online;
		IF i = 65 THEN
			ASSERT_EQ(m.step, 90);
		END_IF
		IF i > 70 AND m.step = 30 THEN EXIT; END_IF
	END_FOR
	ASSERT_EQ(m.step, 30);
	ASSERT_EQ(bus.Drive.Position, 1000);
END_TEST
