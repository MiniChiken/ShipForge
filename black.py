"""Reader for CCP's FSD ".black" container (SpaceObjectFactory / SOF data).

Header layout - verified byte-exact against aliastra.black (3.9 KB),
generic.black (23 KB) and the full data.black (180 MB); the embedded string
count matches the parsed table exactly in all three:

    0   magic u32        0xb1acf11e
    4   version u32      1
    8   dataOffset u32   RELATIVE TO OFFSET 12, not to 0
    12  stringCount u16
    14  .. 12+dataOffset   NUL-terminated string table
    12+dataOffset ..       binary data

Like Granny, this format is effectively self-describing: the string table holds
both type names ("EveSOFDataFaction", "EveSOFDataArea") and field names
("name", "areaTypes", "material1"), so the schema can be recovered from the
file rather than guessed.

The data region encodes a typed object tree as u16 indices into the string
table - runs of (fieldNameIndex, valueIndex) pairs - with values above
stringCount being counts/offsets rather than string references. That layer is
NOT fully decoded yet; only the container is.
"""
import struct

MAGIC = 0xB1ACF11E


class BlackFile:
    def __init__(self, data):
        self.raw = data
        magic, self.version, data_offset = struct.unpack_from("<IiI", data, 0)
        if magic != MAGIC:
            raise ValueError("not a .black file (magic %08x)" % magic)
        self.string_count = struct.unpack_from("<H", data, 12)[0]
        self.data_start = 12 + data_offset
        table = data[14:self.data_start]
        self.strings = [s.decode("utf-8", "replace")
                        for s in table.split(b"\0") if s != b""]
        if len(self.strings) != self.string_count:
            raise ValueError("string table mismatch: parsed %d, header says %d"
                             % (len(self.strings), self.string_count))
        self.data = data[self.data_start:]

    def name(self, idx):
        return self.strings[idx] if 0 <= idx < len(self.strings) else None

    def types(self):
        """String-table entries that look like SOF type names."""
        return [s for s in self.strings if s.startswith("EveSOFData")]

    def u16s(self, offset=0, count=32):
        return struct.unpack_from("<%dH" % count, self.data, offset)

    def describe(self):
        return ("version=%d strings=%d data_start=%d data_bytes=%d types=%d"
                % (self.version, self.string_count, self.data_start,
                   len(self.data), len(self.types())))
