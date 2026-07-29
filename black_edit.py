"""Rewrite a .black file's string table, leaving the data region untouched.

The data region is schema-driven and - proven by search - references strings
NEITHER by table index NOR by byte offset, so the reader must consume them
positionally. That means string CONTENT (and length) can be changed freely as
long as the ORDER and COUNT are preserved and the header's dataOffset is
corrected.

This is what makes a genuinely new hull possible without a .black writer: take
a hull definition already known to work with our geometry (ab2_t1 - stride 20,
quad/quadv5.fx, 2 opaque areas), rename it to a hull name some existing
graphicID already points at, and repoint its geometry and textures.
"""
import struct

MAGIC = 0xB1ACF11E


def load(raw):
    magic, version, data_offset = struct.unpack_from("<IiI", raw, 0)
    if magic != MAGIC:
        raise ValueError("not a .black file")
    count = struct.unpack_from("<H", raw, 12)[0]
    start = 12 + data_offset
    strings = [s.decode("utf-8") for s in raw[14:start].split(b"\0") if s != b""]
    if len(strings) != count:
        raise ValueError("string count mismatch %d != %d" % (len(strings), count))
    return version, strings, raw[start:]


def build(version, strings, data):
    table = b"".join(s.encode("utf-8") + b"\0" for s in strings)
    # dataOffset is measured from offset 12, and the table starts at 14
    data_offset = len(table) + 2
    out = bytearray()
    out += struct.pack("<IiI", MAGIC, version, data_offset)
    out += struct.pack("<H", len(strings))
    out += table
    out += data
    return bytes(out)


def rewrite(raw, replacements):
    """replacements: {old_string: new_string}. Order and count are preserved."""
    version, strings, data = load(raw)
    hits = 0
    out = []
    for s in strings:
        if s in replacements:
            out.append(replacements[s])
            hits += 1
        else:
            out.append(s)
    return build(version, out, data), hits, len(strings)
