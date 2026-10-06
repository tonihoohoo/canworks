(*
 * The program generated from config/cia402-drive with "scale_numerator": 10
 * (10 increments per technical unit), against the drive model. Run by
 * test/cia402/run.sh.
 *)
TEST 'scaling from the config converts technical units to increments'
	VAR
		m : main;
		bus : DriveLink;
		power : MC_Power;
		status : MC_ReadStatus;
		i : INT;
		move : MC_MoveVelocity;
	END_VAR
	FOR i := 1 TO 80 DO
		m();
		power(Axis := m.drive, Enable := TRUE);
		move(Axis := m.drive, Execute := power.Status, Velocity := 25.0);
		bus(ControlWord := m.drive_Controlword, Modes := m.drive_Modes_of_operation,
		    TargetPosition := m.drive_Target_position, ProfileVelocity := m.drive_Profile_velocity,
		    TargetVelocity := m.drive_Target_velocity);
		m.drive_Statusword := bus.StatusWord;
		m.drive_Modes_of_operation_display := bus.ModesDisplay;
		m.drive_Position_actual_value := bus.Position;
		m.drive_Velocity_actual_value := bus.Velocity;
		m.drive_ok := bus.Online;
	END_FOR
	ASSERT_EQ(m.drive_Target_velocity, 250);
	ASSERT_NEAR(m.drive.fActVelocity, 25.0, 0.01);
END_TEST
