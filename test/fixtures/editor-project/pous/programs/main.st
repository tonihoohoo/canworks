PROGRAM main
  VAR
    door_ok AT %IX10.1 : BOOL;
    counter : INT;
  END_VAR

  IF door_ok THEN
    counter := counter + 1;
  END_IF;
END_PROGRAM
