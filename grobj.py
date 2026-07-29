"""Typed object reader for Granny files - walks data using the embedded type tree.

Granny member sizes for the 64-bit variant (pointers are 8 bytes and the
structs are packed, matching the 44-byte DataTypeDefinition seen in granny.py):

    Reference               ptr                              8
    ReferenceToArray        {int32 count; T* items}          12
    ArrayOfReferences       {int32 count; T** items}         12
    VariantReference        {type*; obj*}                    16
    String                  char*                             8
    Transform               {uint32; float[3]; float[4]; float[9]}  68
    Real32/Int32/UInt32     4   Int16/UInt16/Real16  2   Int8/UInt8  1

Array width multiplies the scalar types (Real32[3] -> 12 bytes).
"""
import struct

import granny

SCALARS = {
    "Real32": ("<f", 4), "Int32": ("<i", 4), "UInt32": ("<I", 4),
    "Int16": ("<h", 2), "UInt16": ("<H", 2),
    "BinormalInt16": ("<h", 2), "NormalUInt16": ("<H", 2),
    "Int8": ("<b", 1), "UInt8": ("<B", 1),
    "BinormalInt8": ("<b", 1), "NormalUInt8": ("<B", 1),
    "Real16": ("<H", 2),
}

FIXED = {
    "Reference": 8, "String": 8, "EmptyReference": 8,
    "ReferenceToArray": 12, "ArrayOfReferences": 12,
    # {type* 8; count u32 4; obj* 8} packed = 20, verified from the pointer map
    # (type ptr at +0, count at +8, data ptr at +12).
    "ReferenceToVariantArray": 20, "VariantReference": 16,
    "Transform": 68,
}


def member_size(m):
    t = m["type"]
    if t in FIXED:
        return FIXED[t]
    if t in SCALARS:
        return SCALARS[t][1] * max(1, m["array"])
    if t == "Inline":
        return struct_size(m.get("children") or [])
    raise ValueError("unsized member type %s" % t)


def struct_size(members):
    return sum(member_size(m) for m in members)


class ObjectReader:
    def __init__(self, gf):
        self.gf = gf

    def read_struct(self, members, sec, off, depth=0):
        out = {}
        cur = off
        data = self.gf.section_data(sec)
        ptrs = self.gf.pointers(sec)
        for m in members:
            name, t = m["name"], m["type"]
            try:
                out[name] = self._read_member(m, sec, cur, data, ptrs, depth)
            except Exception as e:
                out[name] = "<%s: %s>" % (type(e).__name__, e)
            cur += member_size(m)
        return out

    def _read_member(self, m, sec, cur, data, ptrs, depth):
        t = m["type"]
        if t in SCALARS:
            fmt, sz = SCALARS[t]
            n = max(1, m["array"])
            vals = [struct.unpack_from(fmt, data, cur + i * sz)[0] for i in range(n)]
            return vals[0] if n == 1 else vals
        if t == "String":
            p = ptrs.get(cur)
            return self.gf.cstring(p[0], p[1]) if p else None
        if t == "Transform":
            return struct.unpack_from("<I16f", data, cur)
        if t in ("Reference", "EmptyReference"):
            p = ptrs.get(cur)
            if not p or depth > 4:
                return None
            return self.read_struct(m.get("children") or [], p[0], p[1], depth + 1)
        if t in ("ReferenceToArray", "ArrayOfReferences"):
            count = struct.unpack_from("<i", data, cur)[0]
            p = ptrs.get(cur + 4)
            if not p or depth > 4:
                return {"count": count, "items": None}
            kids = m.get("children") or []
            items = []
            limit = min(count, 64)  # keep dumps readable
            if t == "ReferenceToArray":
                esz = struct_size(kids) if kids else 0
                for i in range(limit):
                    if esz == 0:
                        break
                    items.append(self.read_struct(kids, p[0], p[1] + i * esz, depth + 1))
            else:
                eptrs = self.gf.pointers(p[0])
                for i in range(limit):
                    q = eptrs.get(p[1] + i * 8)
                    if q:
                        items.append(self.read_struct(kids, q[0], q[1], depth + 1))
            return {"count": count, "items": items}
        if t in ("VariantReference", "ReferenceToVariantArray"):
            return "<variant>"
        if t == "Inline":
            return self.read_struct(m.get("children") or [], sec, cur, depth + 1)
        return "<%s>" % t

    def root(self, depth=0):
        tree = self.gf.type_tree()
        return self.read_struct(tree, self.gf.root_obj_section,
                                self.gf.root_obj_offset, depth)
