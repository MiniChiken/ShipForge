"""Decompile a client .pyj module back to readable Python 2.7 source.

    python decompile_pyj.py <code.ccp> <entry> <out.py>
"""
import io
import sys
import zlib
import zipfile

import uncompyle6


def main(archive, entry, out):
    with zipfile.ZipFile(archive) as z:
        raw = z.read(entry)
    pyc = zlib.decompress(raw)
    tmp = out + ".pyc"
    with open(tmp, "wb") as fh:
        fh.write(pyc)
    buf = io.StringIO()
    uncompyle6.decompile_file(tmp, buf)
    with open(out, "w", encoding="utf-8") as fh:
        fh.write(buf.getvalue())
    print("wrote %s (%d chars)" % (out, len(buf.getvalue())))


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2], sys.argv[3])
