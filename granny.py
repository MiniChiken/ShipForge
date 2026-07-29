"""Granny2 v7 64-bit reader for EVE .gr2 files.

Container layout (verified byte-exact against the client's own files):
    0    magic[16]           E5 9B 49 5E 6F 63 1F 14 1E 13 EB A9 90 BE ED C4
    16   headerSize u32      456
    20   headerFormat u32    0
    24   reserved[2] u32
    32   <file header begins; sectionArrayOffset is relative to HERE>
    32   version u32         7
    36   totalSize u32
    40   crc u32
    44   sectionArrayOffset u32   72  -> file offset 104
    48   sectionArrayCount u32    8
    52   rootTypeSection u32, rootTypeOffset u32
    60   rootObjSection u32, rootObjOffset u32
    68   typeTag u32
    104  section[8] x 44 bytes  -> ends exactly at headerSize
Relocation entry = 12 bytes {u32 fromOffset, u32 toSection, u32 toOffset}.
Mixed-marshalling entry = 16 bytes.
"""
import struct

# Two GUIDs appear in EVE, but the header behind them is byte-identical Granny v7
# (headerSize 456, version 7, 8 sections, typeTag 0x80000039). The first is the
# stock RAD 64-bit LE magic; the second is a CCP variant used by the majority
# (10,132 of 14,113 files), including all modern hulls.
MAGIC = bytes.fromhex("e59b495e6f631f141e13eba990beedc4")
MAGIC_CCP = bytes.fromhex("29de6cc0baa4532b25f5b7a5f666e2ee")
MAGICS = (MAGIC, MAGIC_CCP)

NONE, OODLE0, OODLE1, BITKNIT1, BITKNIT2 = 0, 1, 2, 3, 4

MEMBER_TYPES = {
    0: "End", 1: "Inline", 2: "Reference", 3: "ReferenceToArray",
    4: "ArrayOfReferences", 5: "VariantReference", 6: "Unsupported",
    7: "ReferenceToVariantArray", 8: "String", 9: "Transform",
    10: "Real32", 11: "Int8", 12: "UInt8", 13: "BinormalInt8",
    14: "NormalUInt8", 15: "Int16", 16: "UInt16", 17: "BinormalInt16",
    18: "NormalUInt16", 19: "Int32", 20: "UInt32", 21: "Real16",
    22: "EmptyReference",
}

SECTION_FIELDS = ("compression", "data_offset", "data_size", "expanded_size",
                  "alignment", "stop0", "stop1", "reloc_offset", "reloc_count",
                  "marshal_offset", "marshal_count")

# 64-bit GrannyDataTypeDefinition is PACKED - 44 bytes, pointers unaligned:
#   0 u32 memberType | 4 ptr64 name | 12 ptr64 referenceType
#   20 u32 arrayWidth | 24 u32 extra[3] | 36 u64 ignored
TYPEDEF_SIZE = 44
NAME_PTR_OFF = 4
REF_PTR_OFF = 12
ARRAY_OFF = 20


class UnsupportedCompression(Exception):
    pass


class GrannyFile:
    def __init__(self, data):
        if data[:16] not in MAGICS:
            raise ValueError("not Granny v7 64-bit LE (magic %s)" % data[:16].hex())
        self.magic = data[:16]
        self.raw = data
        self.header_size, self.header_format = struct.unpack_from("<II", data, 16)
        (self.version, self.total_size, self.crc,
         self.sec_array_offset, self.sec_array_count) = struct.unpack_from("<5I", data, 32)
        (self.root_type_section, self.root_type_offset,
         self.root_obj_section, self.root_obj_offset,
         self.type_tag) = struct.unpack_from("<5I", data, 52)
        self.sections = []
        base = 32 + self.sec_array_offset
        for i in range(self.sec_array_count):
            vals = struct.unpack_from("<11I", data, base + i * 44)
            s = dict(zip(SECTION_FIELDS, vals))
            s["index"] = i
            self.sections.append(s)
        self._data = {}
        self._ptr = {}

    # -- section payloads -------------------------------------------------
    def section_data(self, i):
        if i in self._data:
            return self._data[i]
        s = self.sections[i]
        blob = self.raw[s["data_offset"]:s["data_offset"] + s["data_size"]]
        if s["compression"] == OODLE1:
            import oodle1
            blob = oodle1.decompress_section(
                blob, s["expanded_size"], s["stop0"], s["stop1"])
        elif s["compression"] != NONE:
            raise UnsupportedCompression(
                "section %d uses compression %d (proprietary RAD codec)" % (i, s["compression"]))
        self._data[i] = blob
        return blob

    def pointers(self, i):
        """{offset_in_section: (target_section, target_offset)} from relocations."""
        if i in self._ptr:
            return self._ptr[i]
        s = self.sections[i]
        out = {}
        off = s["reloc_offset"]
        for _ in range(s["reloc_count"]):
            frm, tsec, toff = struct.unpack_from("<3I", self.raw, off)
            out[frm] = (tsec, toff)
            off += 12
        self._ptr[i] = out
        return out

    # -- typed access -----------------------------------------------------
    def cstring(self, sec, off):
        d = self.section_data(sec)
        end = d.index(b"\0", off)
        return d[off:end].decode("utf-8", "replace")

    def type_tree(self, sec=None, off=None, depth=0, seen=None):
        """Walk a GrannyDataTypeDefinition array into a list of members.

        Identical structs legitimately share one typedef (writers intern them),
        so a revisit must return the CACHED members, not an empty list - doing
        the latter silently drops children and makes arrays unreadable.
        """
        sec = self.root_type_section if sec is None else sec
        off = self.root_type_offset if off is None else off
        seen = seen if seen is not None else {}
        if depth > 6:
            return []
        if (sec, off) in seen:
            return seen[(sec, off)]
        data = self.section_data(sec)
        ptrs = self.pointers(sec)
        members = []
        seen[(sec, off)] = members   # placeholder guards self-referential types
        cur = off
        while cur + TYPEDEF_SIZE <= len(data):
            mtype = struct.unpack_from("<I", data, cur)[0]
            if mtype == 0:
                break
            name = None
            if cur + NAME_PTR_OFF in ptrs:
                ns, no = ptrs[cur + NAME_PTR_OFF]
                name = self.cstring(ns, no)
            ref = ptrs.get(cur + REF_PTR_OFF)
            arr = struct.unpack_from("<I", data, cur + ARRAY_OFF)[0]
            members.append({
                "type": MEMBER_TYPES.get(mtype, "?%d" % mtype),
                "name": name, "array": arr, "ref": ref, "depth": depth,
            })
            if ref and mtype in (1, 2, 3, 4):
                members[-1]["children"] = self.type_tree(ref[0], ref[1], depth + 1, seen)
            cur += TYPEDEF_SIZE
        return members


def render(members, indent=0, out=None):
    out = [] if out is None else out
    for m in members:
        arr = "[%d]" % m["array"] if m["array"] else ""
        out.append("%s%-22s %s%s" % ("  " * indent, m["name"], m["type"], arr))
        if m.get("children"):
            render(m["children"], indent + 1, out)
    return out
