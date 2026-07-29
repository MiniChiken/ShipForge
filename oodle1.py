"""Oodle1 (Granny section compression type 2) support.

Granny stores an Oodle1 section as up to THREE concatenated Oodle1 streams.
The section header's stop0/stop1 are boundaries in the *decompressed* output:

    stream 0 -> output[0        : stop0]
    stream 1 -> output[stop0    : stop1]
    stream 2 -> output[stop1    : expanded_size]

A stream is empty when its span is zero, so a section with
stop0 == stop1 == expanded_size is a single-stream section - the easiest
validation target. Each stream carries its own 12-byte header and the
decompressor is re-initialised per stream; there is no EOF symbol, so the
expected output length must be supplied out of band.

The codec itself lives in `_oodle1_codec`; this module owns the Granny-side
framing, which is independent of how the codec is obtained.
"""

import os
import subprocess
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
CLI = os.path.join(HERE, "oodle1_cli.exe")


class CodecUnavailable(RuntimeError):
    pass


def stream_spans(expanded_size, stop0, stop1):
    """[(out_start, out_end), ...] for the up-to-3 streams, empties dropped."""
    bounds = [0, stop0, stop1, expanded_size]
    spans = []
    for a, b in zip(bounds, bounds[1:]):
        if b > a:
            spans.append((a, b))
    return spans


def decompress_section(blob, expanded_size, stop0, stop1):
    """Decompress one Granny Oodle1 section into exactly expanded_size bytes.

    The whole payload goes to the codec in one piece: the three 12-byte stream
    headers live at offsets 0/12/24 and a single shared bitstream starts at 36,
    so the streams cannot be sliced apart and fed in separately.
    """
    if not os.path.exists(CLI):
        raise CodecUnavailable("oodle1_cli.exe not built - run build.bat")
    tmp = tempfile.mkdtemp(prefix="oodle1_")
    src, dst = os.path.join(tmp, "in.bin"), os.path.join(tmp, "out.bin")
    try:
        with open(src, "wb") as fh:
            fh.write(blob)
        r = subprocess.run([CLI, src, dst, str(expanded_size), str(stop0), str(stop1)],
                           capture_output=True, text=True)
        if r.returncode != 0:
            raise ValueError("oodle1 decode failed: %s" % r.stderr.strip())
        with open(dst, "rb") as fh:
            out = fh.read()
        if len(out) != expanded_size:
            raise ValueError("section produced %d bytes, expected %d"
                             % (len(out), expanded_size))
        return out
    finally:
        for p in (src, dst):
            if os.path.exists(p):
                os.remove(p)
        os.rmdir(tmp)


def describe_section(sec):
    """Human-readable framing summary for one section dict from granny.py."""
    spans = stream_spans(sec["expanded_size"], sec["stop0"], sec["stop1"])
    return "comp=%d %d->%d bytes in %d stream(s): %s" % (
        sec["compression"], sec["data_size"], sec["expanded_size"],
        len(spans), spans)
