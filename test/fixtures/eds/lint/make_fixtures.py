"""Writes the EDS lint fixtures: ../cpp-slave.eds with one defect class each,
reduced from the 41 vendor files of the add-scoped-eds-lint research (see
expected.json for what each must give). Run after changing a fixture:

  python3 test/fixtures/eds/lint/make_fixtures.py
"""

import json
import os
import re

HERE = os.path.dirname(os.path.abspath(__file__))
BASE = os.path.join(HERE, "..", "cpp-slave.eds")


def add_objects(text, objects):
    """Appends object sections and lists them in Optional/ManufacturerObjects."""
    for index, body in objects:
        listing = "ManufacturerObjects" if 0x2000 <= index < 0x6000 else "OptionalObjects"
        m = re.search(r"\[%s\]\r?\nSupportedObjects=(\d+)" % listing, text)
        n = int(m.group(1)) + 1
        text = text[:m.start(1)] + str(n) + text[m.end(1):]
        end = text.index("\n", text.index("SupportedObjects=%d" % n, m.start())) + 1
        # The list entries follow SupportedObjects; append after the last one.
        pos = end
        while True:
            line_end = text.index("\n", pos) + 1 if "\n" in text[pos:] else len(text)
            if not re.match(r"\d+=", text[pos:line_end]):
                break
            pos = line_end
        text = text[:pos] + "%d=0x%04X\n" % (n, index) + text[pos:]
        text = text.rstrip("\n") + "\n\n" + body.strip("\n") + "\n"
    return text


def set_key(text, section, key, value):
    m = re.search(r"^\[%s\]\n((?:(?!\[).*\n)*)" % re.escape(section), text, re.M)
    block = m.group(1)
    if re.search(r"^%s=" % key, block, re.M):
        block = re.sub(r"^%s=.*$" % key, "%s=%s" % (key, value), block, flags=re.M)
    else:
        block = block.rstrip("\n") + "\n%s=%s\n\n" % (key, value)
    return text[:m.start(1)] + block + text[m.end(1):]


VAR = "[{idx:04X}]\nParameterName={name}\nObjectType=0x7\nDataType={dt}\nAccessType={acc}\n{extra}PDOMapping={pdo}\n"


def var(idx, name, dt, acc="rw", pdo=0, **keys):
    extra = "".join("%s=%s\n" % (k, v) for k, v in keys.items())
    return idx, VAR.format(idx=idx, name=name, dt=dt, acc=acc, extra=extra, pdo=pdo)


FIXTURES = {
    # Signed values as two's-complement hex (common in drive EDS files).
    "signed-hex.eds": lambda t: add_objects(t, [
        var(0x6061, "Modes of operation display", "0x0002", "ro", 1, LowLimit="0x00", HighLimit="0xFF",
            DefaultValue="1"),
        var(0x60C0, "Interpolation sub mode", "0x0003", LowLimit="0xFFFF", HighLimit="0xFFFF",
            DefaultValue="0xFFFF")]),
    # Limits that contradict the data type.
    "type-limits.eds": lambda t: add_objects(t, [
        var(0x2100, "Fan on temperature", "0x0005", LowLimit="-30", HighLimit="127", DefaultValue="50"),
        var(0x2101, "Capacitor temperature", "0x0003", "ro", LowLimit="0", HighLimit="65535")]),
    # Defaults outside the file's own limits.
    "out-of-limits.eds": lambda t: add_objects(t, [
        var(0x6060, "Modes of operation", "0x0002", LowLimit="1", HighLimit="4", DefaultValue="0")]),
    # Structure errors.
    "structure.eds": lambda t: add_objects(t, [
        (0x200B, "[200B]\nParameterName=error_details\nObjectType=0x9\nSubNumber=3\nAccessType=ro\n\n"
                 "[200Bsub0]\nParameterName=Highest sub-index\nObjectType=0x7\nDataType=0x0005\nAccessType=ro\n"
                 "DefaultValue=2\nPDOMapping=0\n\n"
                 "[200Bsub1]\nParameterName=code\nObjectType=0x7\nDataType=0x0007\nAccessType=ro\n"
                 "DefaultValue=0\nPDOMapping=0\n"),
        (0x6064, "[6064]\nParameterName=Position actual value\nObjectType=0x8\nSubNumber=2\n\n"
                 "[6064sub0]\nParameterName=HighestSubIndex\nObjectType=0x7\nDataType=0x0006\nAccessType=ro\n"
                 "DefaultValue=1\nPDOMapping=0\n\n"
                 "[6064sub1]\nParameterName=Axis 1\nObjectType=0x7\nDataType=0x0004\nAccessType=ro\n"
                 "DefaultValue=0\nPDOMapping=1\n")]),
    # A leading zero (CiA 306 octal; Python's int(x, 0) refuses it).
    "octal-limit.eds": lambda t: add_objects(t, [
        var(0x605B, "Shutdown option code", "0x0003", LowLimit="00", HighLimit="01", DefaultValue="1")]),
    # REAL32 written as a decimal number.
    "real-decimal.eds": lambda t: add_objects(t, [
        var(0x2120, "R32", "0x0008", pdo=1, DefaultValue="12.345")]),
    # A CP1252 byte in [Comments].
    "cp1252.eds": lambda t: t,  # the byte is put in by main()
    # An OCTET_STRING default Lely cannot read.
    "octet-string.eds": lambda t: add_objects(t, [
        var(0x2051, "Customer name", "0x000a", "ro", DefaultValue="----")]),
    # A limit typo in a communication object (limit-only).
    "comm-limit.eds": lambda t: set_key(set_key(t, "1800sub1", "LowLimit", "0x181"), "1800sub1", "HighLimit",
                                        "0x18F"),
    # A communication object dcfgen reads with the wrong type: blocking.
    "comm-broken.eds": lambda t: set_key(t, "1A00sub0", "DataType", "0x0006"),
}


def main():
    with open(BASE, encoding="utf-8") as f:
        base = f.read().replace("\r\n", "\n")
    for name, make in FIXTURES.items():
        text = make(base)
        text = re.sub(r"^FileName=.*$", "FileName=" + name, text, count=1, flags=re.M)
        data = text.encode("utf-8")
        if name == "cp1252.eds":
            data = re.sub(rb"\[Comments\]\nLines=\d+\n", b"[Comments]\nLines=1\nLine1=Range 0-100 \x94C\n", data,
                          count=1)
        with open(os.path.join(HERE, name), "wb") as f:
            f.write(data)
    print("wrote", ", ".join(sorted(FIXTURES)))


if __name__ == "__main__":
    main()
