"""Signal packing as DBC files number bits (spec can-raw-messages, "Raw
signals"): bit 0 is the least significant bit of byte 0; a little-endian
(Intel) signal starts at its least significant bit, a big-endian (Motorola)
signal at its most significant bit. Values are raw integers; the plugin
(plugin/src/can/signals.*) and the library's CAN_GET_BITS / CAN_SET_BITS
pack the same way, checked against test/fixtures/can_signals.json."""


def bit_positions(start_bit, length, big_endian):
    """Frame bit positions of the signal's bits, most significant first for
    big-endian and least significant first for little-endian."""
    pos = start_bit
    out = []
    for _ in range(length):
        out.append(pos)
        if big_endian:
            pos = pos + 15 if pos % 8 == 0 else pos - 1
        else:
            pos += 1
    return out


def last_byte(start_bit, length, big_endian):
    """Index of the highest data byte the signal touches (-1: none)."""
    if length <= 0:
        return -1
    return max(p // 8 for p in bit_positions(start_bit, length, big_endian))


def fits(start_bit, length, big_endian, dlc):
    """True when every bit of the signal lies in the first `dlc` bytes."""
    return all(0 <= p < 8 * dlc for p in bit_positions(start_bit, length, big_endian))


def unpack(data, start_bit, length, big_endian=False, signed=False):
    v = 0
    for i, p in enumerate(bit_positions(start_bit, length, big_endian)):
        bit = (data[p // 8] >> (p % 8)) & 1 if 0 <= p < 8 * len(data) else 0
        if big_endian:
            v = (v << 1) | bit
        else:
            v |= bit << i
    if signed and 0 < length and v >> (length - 1) & 1:
        v -= 1 << length
    return v


def pack(data, start_bit, length, value, big_endian=False):
    """Writes `value` (two's complement for negatives) into bytearray `data`."""
    value &= (1 << length) - 1
    for i, p in enumerate(bit_positions(start_bit, length, big_endian)):
        shift = length - 1 - i if big_endian else i
        if (value >> shift) & 1:
            data[p // 8] |= 1 << (p % 8)
        else:
            data[p // 8] &= ~(1 << (p % 8)) & 0xFF
    return data
