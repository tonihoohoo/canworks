"""IEC 61131-3 located addresses (%IX10.0, %QW100, %MD5) and CANopen types.

Mirrors plugin/src/iec_location.{h,cpp}. Each size letter is its own table in
the OpenPLC image (bool_input, byte_input, int_input, dint_input, lint_input,
and the output and memory equivalents), so locations of different sizes never
overlap: %IW100 and %ID100 are different variables.
"""

import re

_LOCATION = re.compile(r"^%([IQM])([XBWDL])([0-9]+)(?:\.([0-9]+))?$", re.IGNORECASE)

SIZE_BITS = {"X": 1, "B": 8, "W": 16, "D": 32, "L": 64}

CO_TYPES = {
    "BOOLEAN": (0x0001, 1),
    "INTEGER8": (0x0002, 8),
    "INTEGER16": (0x0003, 16),
    "INTEGER32": (0x0004, 32),
    "UNSIGNED8": (0x0005, 8),
    "UNSIGNED16": (0x0006, 16),
    "UNSIGNED32": (0x0007, 32),
    "REAL32": (0x0008, 32),
    "REAL64": (0x0011, 64),
    "INTEGER64": (0x0015, 64),
    "UNSIGNED64": (0x001B, 64),
}
CO_TYPE_BY_CODE = {code: name for name, (code, _) in CO_TYPES.items()}

# Which location sizes each type fits (plugin: co_type_fits).
_FITS = {
    "BOOLEAN": "X",
    "INTEGER8": "B", "UNSIGNED8": "B",
    "INTEGER16": "W", "UNSIGNED16": "W",
    "INTEGER32": "D", "UNSIGNED32": "D", "REAL32": "D",
    "INTEGER64": "L", "UNSIGNED64": "L", "REAL64": "L",
}


class Location:
    """A parsed location. `element` is the index into its table; for bits it
    counts bits (byte * 8 + bit) so consecutive bits are consecutive elements."""

    def __init__(self, area, size, index, bit=None):
        self.area = area
        self.size = size
        self.index = index
        self.bit = bit

    @property
    def element(self):
        return self.index * 8 + self.bit if self.size == "X" else self.index

    def __str__(self):
        if self.size == "X":
            return "%%%sX%d.%d" % (self.area, self.index, self.bit)
        return "%%%s%s%d" % (self.area, self.size, self.index)


def parse_location(text):
    """Returns a Location, or None if `text` is not a located address."""
    if not isinstance(text, str):
        return None
    m = _LOCATION.match(text.strip())
    if not m:
        return None
    area, size, index, bit = m.group(1).upper(), m.group(2).upper(), int(m.group(3)), m.group(4)
    if size == "X":
        if bit is None or int(bit) > 7:
            return None
        return Location(area, size, index, int(bit))
    if bit is not None:
        return None
    return Location(area, size, index)


def element_str(area, size, element):
    """The location of one table element (inverse of Location.element)."""
    if size == "X":
        return str(Location(area, size, element // 8, element % 8))
    return str(Location(area, size, element))


def type_fits(type_name, size):
    return _FITS.get(type_name) == size
