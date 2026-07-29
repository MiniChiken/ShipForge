"""Pull readable names and string constants out of a client .pyj module.

.pyj is a zlib-compressed Python 2.7 .pyc. Python 3 cannot unmarshal 2.7 code
objects, but the names and docstrings sit in the marshalled blob as length-
prefixed ASCII, which is enough to read the shape of a function - what it calls
and which attributes it touches - without a full decompile.

    python peek_pyj.py <code.ccp> <entry path> [more entries...]
"""
import re
import sys
import zlib
import zipfile

PRINTABLE = re.compile(rb"[ -~]{3,}")


def dump(archive, entry):
    with zipfile.ZipFile(archive) as z:
        raw = z.read(entry)
    body = zlib.decompress(raw)
    print("=" * 78)
    print("%s  (%d bytes compressed -> %d)" % (entry, len(raw), len(body)))
    print("=" * 78)
    seen = []
    for m in PRINTABLE.finditer(body):
        s = m.group().decode("ascii")
        if s not in seen:
            seen.append(s)
    for s in seen:
        print("   %s" % s)


if __name__ == "__main__":
    for e in sys.argv[2:]:
        dump(sys.argv[1], e)
