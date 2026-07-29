"""Granny v7 64-bit writer - emits uncompressed .gr2 files EVE's trinity can load.

Writing is much easier than reading: the Granny runtime accepts compression 0,
so no Oodle1/BitKnit compressor is needed. What must be exact is the type tree
(packed 44-byte DataTypeDefinition records) and the relocation tables, because
every pointer in the file is stored as zero and patched at load time from the
relocation entries.

Layout produced:
    header 456 bytes  (8 section descriptors at 104, 44 bytes each)
    section 0 data    objects + strings
    section 6 data    type definitions
    relocations       12 bytes each {fromOffset, toSection, toOffset}

Schema is described with Member tuples; see venator_gr2.py for a real use.
"""
import struct

import granny

# member type codes, mirroring granny.MEMBER_TYPES
END, INLINE, REFERENCE, REF_TO_ARRAY, ARRAY_OF_REFS = 0, 1, 2, 3, 4
VARIANT_REF, REF_TO_VARIANT_ARRAY, STRING, TRANSFORM = 5, 7, 8, 9
REAL32, INT8, UINT8, BINORMAL_INT8, NORMAL_UINT8 = 10, 11, 12, 13, 14
INT16, UINT16, BINORMAL_INT16, NORMAL_UINT16 = 15, 16, 17, 18
INT32, UINT32, REAL16 = 19, 20, 21

TYPEDEF_SIZE = 44
DATA_SEC = 0
TYPE_SEC = 6
SECTION_COUNT = 8
HEADER_SIZE = 456
SECTION_ARRAY_OFFSET = 72          # relative to +32
SECTION_ARRAY_FILE_OFFSET = 104    # 32 + 72


class Member:
    """One field in a struct definition."""

    def __init__(self, name, mtype, children=None, array=0):
        self.name = name
        self.mtype = mtype
        self.children = children or []
        self.array = array

    def size(self):
        if self.mtype in (REFERENCE, STRING):
            return 8
        if self.mtype in (REF_TO_ARRAY, ARRAY_OF_REFS):
            return 12
        if self.mtype == REF_TO_VARIANT_ARRAY:
            return 20
        if self.mtype == VARIANT_REF:
            return 16
        if self.mtype == TRANSFORM:
            return 68
        if self.mtype == INLINE:
            return sum(m.size() for m in self.children)
        n = max(1, self.array)
        if self.mtype in (REAL32, INT32, UINT32):
            return 4 * n
        if self.mtype in (INT16, UINT16, BINORMAL_INT16, NORMAL_UINT16, REAL16):
            return 2 * n
        if self.mtype in (INT8, UINT8, BINORMAL_INT8, NORMAL_UINT8):
            return 1 * n
        raise ValueError("unsized member type %d" % self.mtype)


def struct_size(members):
    return sum(m.size() for m in members)


class Section:
    def __init__(self, index):
        self.index = index
        self.buf = bytearray()

    def alloc(self, size, align=4):
        while len(self.buf) % align:
            self.buf += b"\0"
        off = len(self.buf)
        self.buf += b"\0" * size
        return off

    def write(self, off, data):
        self.buf[off:off + len(data)] = data

    def append(self, data, align=4):
        off = self.alloc(len(data), align)
        self.write(off, data)
        return off


class GrannyWriter:
    def __init__(self, magic=None):
        self.magic = magic or granny.MAGIC
        self.sections = [Section(i) for i in range(SECTION_COUNT)]
        self.relocs = {i: [] for i in range(SECTION_COUNT)}
        self._strings = {}
        self._typedefs = {}

    # -- primitives -------------------------------------------------------
    def pointer(self, from_sec, from_off, to_sec, to_off):
        """Record a pointer; the slot itself stays zero in the file."""
        self.relocs[from_sec].append((from_off, to_sec, to_off))

    def string(self, s):
        """Intern a NUL-terminated string in the data section."""
        if s is None:
            return None
        if s in self._strings:
            return self._strings[s]
        off = self.sections[DATA_SEC].append(s.encode("utf-8") + b"\0", align=1)
        self._strings[s] = (DATA_SEC, off)
        return self._strings[s]

    # -- type tree --------------------------------------------------------
    def typedef(self, members, key=None):
        """Emit a DataTypeDefinition array; returns (section, offset)."""
        key = key or id(members)
        if key in self._typedefs:
            return self._typedefs[key]
        sec = self.sections[TYPE_SEC]
        off = sec.alloc(TYPEDEF_SIZE * (len(members) + 1))
        self._typedefs[key] = (TYPE_SEC, off)
        for i, m in enumerate(members):
            rec = off + i * TYPEDEF_SIZE
            struct.pack_into("<I", sec.buf, rec, m.mtype)
            struct.pack_into("<I", sec.buf, rec + 20, m.array)
            ns, no = self.string(m.name)
            self.pointer(TYPE_SEC, rec + 4, ns, no)
            if m.children:
                cs, co = self.typedef(m.children, key=m.name + "@" + str(len(m.children)))
                self.pointer(TYPE_SEC, rec + 12, cs, co)
        # trailing all-zero record terminates the array
        return self._typedefs[key]

    # -- object data ------------------------------------------------------
    def write_struct(self, members, values, sec=DATA_SEC, off=None):
        """Write one struct instance; returns (section, offset)."""
        s = self.sections[sec]
        if off is None:
            off = s.alloc(struct_size(members), align=8)
        cur = off
        for m in members:
            self._write_member(m, values.get(m.name), sec, cur)
            cur += m.size()
        return (sec, off)

    def _write_member(self, m, v, sec, cur):
        s = self.sections[sec]
        t = m.mtype
        if t == STRING:
            if v is not None:
                ss, so = self.string(v)
                self.pointer(sec, cur, ss, so)
            return
        if t == REFERENCE:
            if v is not None:
                if isinstance(v, tuple) and v and v[0] == "ptr":
                    self.pointer(sec, cur, v[1], v[2])
                else:
                    rs, ro = self.write_struct(m.children, v)
                    self.pointer(sec, cur, rs, ro)
            return
        if t == REF_TO_ARRAY:
            # ('raw', count, bytes) bypasses per-element struct writing, which
            # matters for index buffers with tens of thousands of entries.
            if isinstance(v, tuple) and v and v[0] == "raw":
                _, count, raw = v
                struct.pack_into("<i", s.buf, cur, count)
                if count:
                    base = self.sections[DATA_SEC].append(raw, align=8)
                    self.pointer(sec, cur + 4, DATA_SEC, base)
                return
            items = v or []
            struct.pack_into("<i", s.buf, cur, len(items))
            if items:
                esz = struct_size(m.children)
                base = self.sections[DATA_SEC].alloc(esz * len(items), align=8)
                for i, item in enumerate(items):
                    self.write_struct(m.children, item, DATA_SEC, base + i * esz)
                self.pointer(sec, cur + 4, DATA_SEC, base)
            return
        if t == ARRAY_OF_REFS:
            items = v or []
            struct.pack_into("<i", s.buf, cur, len(items))
            if items:
                base = self.sections[DATA_SEC].alloc(8 * len(items), align=8)
                for i, item in enumerate(items):
                    rs, ro = self.write_struct(m.children, item)
                    self.pointer(DATA_SEC, base + i * 8, rs, ro)
                self.pointer(sec, cur + 4, DATA_SEC, base)
            return
        if t == REF_TO_VARIANT_ARRAY:
            # {type* ; count u32 ; obj*} - v is (typeMembers, rawBytes, count)
            if v is not None:
                tmembers, raw, count = v
                ts, to = self.typedef(tmembers, key="variant@" + str(id(tmembers)))
                self.pointer(sec, cur, ts, to)
                struct.pack_into("<I", s.buf, cur + 8, count)
                base = self.sections[DATA_SEC].append(raw, align=8)
                self.pointer(sec, cur + 12, DATA_SEC, base)
            return
        if t == TRANSFORM:
            # {uint32 flags; float position[3]; float orientation[4];
            #  float scaleShear[9]} = 68 bytes
            vals = list(v) if v else [0] + [0.0] * 16
            struct.pack_into("<I16f", s.buf, cur, int(vals[0]), *[float(x) for x in vals[1:17]])
            return
        if t == VARIANT_REF:
            return  # left null
        if t == INLINE:
            self.write_struct(m.children, v or {}, sec, cur)
            return
        n = max(1, m.array)
        vals = v if isinstance(v, (list, tuple)) else ([v] * n if v is not None else [0] * n)
        vals = list(vals) + [0] * (n - len(vals))
        fmt = {REAL32: "<f", INT32: "<i", UINT32: "<I", INT16: "<h", UINT16: "<H",
               BINORMAL_INT16: "<h", NORMAL_UINT16: "<H", REAL16: "<H",
               INT8: "<b", UINT8: "<B", BINORMAL_INT8: "<b", NORMAL_UINT8: "<B"}[t]
        esz = {"<f": 4, "<i": 4, "<I": 4, "<h": 2, "<H": 2, "<b": 1, "<B": 1}[fmt]
        for i in range(n):
            struct.pack_into(fmt, s.buf, cur + i * esz, vals[i])

    # -- file assembly ----------------------------------------------------
    def build(self, root_members, root_values):
        root_sec, root_off = self.write_struct(root_members, root_values)
        type_sec, type_off = self.typedef(root_members, key="__root__")

        out = bytearray(b"\0" * HEADER_SIZE)
        descs = []
        for s in self.sections:
            while len(s.buf) % 4:
                s.buf += b"\0"
            data_off = len(out)
            out += s.buf
            descs.append({"data_offset": data_off, "data_size": len(s.buf)})
        for i, s in enumerate(self.sections):
            entries = self.relocs[i]
            descs[i]["reloc_offset"] = len(out)
            descs[i]["reloc_count"] = len(entries)
            for frm, tsec, toff in entries:
                out += struct.pack("<3I", frm, tsec, toff)
        for d in descs:
            d["marshal_offset"] = len(out)
            d["marshal_count"] = 0

        out[0:16] = self.magic
        struct.pack_into("<II", out, 16, HEADER_SIZE, 0)
        struct.pack_into("<5I", out, 32, 7, len(out), 0,
                         SECTION_ARRAY_OFFSET, SECTION_COUNT)
        struct.pack_into("<5I", out, 52, type_sec, type_off, root_sec, root_off,
                         0x80000039)
        for i, d in enumerate(descs):
            struct.pack_into(
                "<11I", out, SECTION_ARRAY_FILE_OFFSET + i * 44,
                0,                      # compression: none
                d["data_offset"], d["data_size"], d["data_size"],
                4, 0, 0,                # alignment, stop0, stop1
                d["reloc_offset"], d["reloc_count"],
                d["marshal_offset"], d["marshal_count"])
        struct.pack_into("<I", out, 36, len(out))
        return bytes(out)
