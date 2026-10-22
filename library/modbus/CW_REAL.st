FUNCTION CW_DWORD_TO_REAL : REAL
(* The REAL whose IEEE 754 bit pattern is IN (a 32-bit value read from two
   Modbus registers). Infinities come back as +/-3.4E38, NaN as 0.0. *)
VAR_INPUT
  IN : DWORD;
END_VAR
VAR
  e : INT;
  m : LREAL;
  x : LREAL;
END_VAR
e := DWORD_TO_INT(SHR(IN, 23) AND 16#FF);
m := DWORD_TO_LREAL(IN AND 16#7FFFFF);
IF e = 255 THEN
  IF m <> 0.0 THEN
    x := 0.0;
  ELSE
    x := 3.4028234663852886E38;
  END_IF;
ELSIF e = 0 THEN
  x := m * EXPT(2.0, -149);
ELSE
  x := (m + 8388608.0) * EXPT(2.0, e - 150);
END_IF;
IF (IN AND 16#80000000) <> 0 THEN
  x := -x;
END_IF;
CW_DWORD_TO_REAL := LREAL_TO_REAL(x);
END_FUNCTION

FUNCTION CW_REAL_TO_DWORD : DWORD
(* The IEEE 754 bit pattern of IN, to send a REAL in two Modbus registers. *)
VAR_INPUT
  IN : REAL;
END_VAR
VAR
  a : LREAL;
  e : INT;
  sign : DWORD;
END_VAR
a := REAL_TO_LREAL(IN);
sign := 0;
IF a < 0.0 THEN
  sign := 16#80000000;
  a := -a;
END_IF;
IF a <> a THEN
  CW_REAL_TO_DWORD := 16#7FC00000;
  RETURN;
END_IF;
IF a = 0.0 THEN
  CW_REAL_TO_DWORD := sign;
  RETURN;
END_IF;
IF a > 3.4028234663852886E38 THEN
  CW_REAL_TO_DWORD := sign OR 16#7F800000;
  RETURN;
END_IF;
e := LREAL_TO_INT(TRUNC(LN(a) / LN(2.0)));
WHILE a / EXPT(2.0, e) >= 2.0 DO
  e := e + 1;
END_WHILE;
WHILE a / EXPT(2.0, e) < 1.0 DO
  e := e - 1;
END_WHILE;
IF e < -126 THEN
  CW_REAL_TO_DWORD := sign OR LREAL_TO_DWORD(a * EXPT(2.0, 149));
ELSE
  CW_REAL_TO_DWORD := sign OR SHL(INT_TO_DWORD(e + 127), 23) OR LREAL_TO_DWORD((a / EXPT(2.0, e) - 1.0) * 8388608.0);
END_IF;
END_FUNCTION

FUNCTION CW_LWORD_TO_LREAL : LREAL
(* The LREAL whose IEEE 754 bit pattern is IN (a 64-bit value read from four
   Modbus registers). Infinities come back as +/-1.79E308, NaN as 0.0. *)
VAR_INPUT
  IN : LWORD;
END_VAR
VAR
  e : INT;
  m : LREAL;
  x : LREAL;
END_VAR
e := LWORD_TO_INT(SHR(IN, 52) AND 16#7FF);
m := LWORD_TO_LREAL(IN AND 16#FFFFFFFFFFFFF);
IF e = 2047 THEN
  IF m <> 0.0 THEN
    x := 0.0;
  ELSE
    x := 1.7976931348623157E308;
  END_IF;
ELSIF e = 0 THEN
  x := m * EXPT(2.0, -1074);
ELSE
  x := (m + 4503599627370496.0) * EXPT(2.0, e - 1075);
END_IF;
IF (IN AND 16#8000000000000000) <> 0 THEN
  x := -x;
END_IF;
CW_LWORD_TO_LREAL := x;
END_FUNCTION

FUNCTION CW_LREAL_TO_LWORD : LWORD
(* The IEEE 754 bit pattern of IN, to send an LREAL in four Modbus registers. *)
VAR_INPUT
  IN : LREAL;
END_VAR
VAR
  a : LREAL;
  e : INT;
  sign : LWORD;
END_VAR
a := IN;
sign := 0;
IF a < 0.0 THEN
  sign := 16#8000000000000000;
  a := -a;
END_IF;
IF a <> a THEN
  CW_LREAL_TO_LWORD := 16#7FF8000000000000;
  RETURN;
END_IF;
IF a = 0.0 THEN
  CW_LREAL_TO_LWORD := sign;
  RETURN;
END_IF;
IF a > 1.7976931348623157E308 THEN
  CW_LREAL_TO_LWORD := sign OR 16#7FF0000000000000;
  RETURN;
END_IF;
e := LREAL_TO_INT(TRUNC(LN(a) / LN(2.0)));
WHILE a / EXPT(2.0, e) >= 2.0 DO
  e := e + 1;
END_WHILE;
WHILE a / EXPT(2.0, e) < 1.0 DO
  e := e - 1;
END_WHILE;
IF e < -1022 THEN
  CW_LREAL_TO_LWORD := sign OR LREAL_TO_LWORD(a * EXPT(2.0, 537) * EXPT(2.0, 537));
ELSE
  CW_LREAL_TO_LWORD := sign OR SHL(INT_TO_LWORD(e + 1023), 52) OR LREAL_TO_LWORD((a / EXPT(2.0, e) - 1.0) * 4503599627370496.0);
END_IF;
END_FUNCTION
