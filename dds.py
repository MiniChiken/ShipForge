"""Write uncompressed DDS files the EVE client can load.

The stock maps are BC7 (_a), BC5/ATI2 (_n) and BC4/ATI1 (_g/_m/_r/_p3/_d).
Implementing those encoders is a project in itself, so these are written
uncompressed with a DX10 header and an explicit dxgiFormat - DX11 samples
R8G8B8A8 natively, and the channel semantics still line up:

  * BC5 normals are sampled .rg, and an RGBA normal keeps x in R and y in G
  * BC4 single-channel maps are sampled .r, so the value goes in R (replicated)

A full mip chain is generated; the stock textures ship one.
"""
import struct

import numpy as np
from PIL import Image

DXGI_R8G8B8A8_UNORM = 28
DXGI_R8G8B8A8_UNORM_SRGB = 29

DDSD = 0x1 | 0x2 | 0x4 | 0x1000 | 0x20000   # CAPS HEIGHT WIDTH PIXELFORMAT MIPMAPCOUNT
DDPF_FOURCC = 0x4
DDSCAPS = 0x1000 | 0x8 | 0x400000           # TEXTURE COMPLEX MIPMAP


def _header(w, h, mips, dxgi):
    out = bytearray(b"DDS ")
    hdr = bytearray(124)
    struct.pack_into("<I", hdr, 0, 124)
    struct.pack_into("<I", hdr, 4, DDSD)
    struct.pack_into("<I", hdr, 8, h)
    struct.pack_into("<I", hdr, 12, w)
    struct.pack_into("<I", hdr, 16, w * 4)      # pitch, bytes per scanline
    struct.pack_into("<I", hdr, 20, 0)          # depth
    struct.pack_into("<I", hdr, 24, mips)
    # pixel format at offset 72 within the 124-byte header
    struct.pack_into("<I", hdr, 72, 32)
    struct.pack_into("<I", hdr, 76, DDPF_FOURCC)
    hdr[80:84] = b"DX10"
    struct.pack_into("<I", hdr, 104, DDSCAPS)
    out += hdr
    out += struct.pack("<5I", dxgi, 3, 0, 1, 0)  # DX10: fmt, TEXTURE2D, misc, array, misc2
    return bytes(out)


def write(path, img, dxgi=DXGI_R8G8B8A8_UNORM, size=None, single_channel=False):
    """img: PIL Image. Writes an uncompressed DDS with a full mip chain."""
    img = img.convert("RGBA")
    if size:
        img = img.resize((size, size), Image.LANCZOS)
    w, h = img.size
    levels = []
    cur = img
    while True:
        a = np.array(cur, dtype=np.uint8)
        if single_channel:
            # replicate red so a .r sample matches BC4 behaviour
            a[..., 1] = a[..., 0]
            a[..., 2] = a[..., 0]
            a[..., 3] = 255
        levels.append(a.tobytes())
        if cur.size[0] == 1 and cur.size[1] == 1:
            break
        cur = cur.resize((max(1, cur.size[0] // 2), max(1, cur.size[1] // 2)),
                         Image.LANCZOS)
    with open(path, "wb") as fh:
        fh.write(_header(w, h, len(levels), dxgi))
        for lv in levels:
            fh.write(lv)
    return w, h, len(levels)


def flat(path, rgba, size=512, dxgi=DXGI_R8G8B8A8_UNORM):
    """A constant-colour map, for slots we have nothing baked for."""
    img = Image.new("RGBA", (size, size), rgba)
    return write(path, img, dxgi=dxgi)
