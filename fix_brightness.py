"""Lift the hull's texture levels to match a stock EVE hull, and write the DDS.

Measured against stock ab2_t1, the Venator's maps were off in three ways that all
push the same direction - a hull that reads far too dark:

    map            ours     stock    effect
    _a albedo      131.3    198.7    the darkness itself
    _g glow          0.0      --     nothing on the hull emits at all
    _r roughness   247.9    219.0    almost fully matte, so no specular response

EVE tints a LIGHT base through its material system, which is why stock albedo sits
near-white; a mid-grey albedo comes out muddy. The albedo is lifted with a gamma
curve rather than a gain so highlights are not clipped flat, and the exponent is
solved numerically for the target mean instead of guessed.

    python fix_brightness.py            # write PNG + DDS
    python fix_brightness.py --dry-run   # report the numbers only
"""
import struct
import sys

import numpy as np
from PIL import Image

import dds

ALBEDO_TARGET = 198.7          # stock ab2_t1 _a mean
ALBEDO_STD_TARGET = 33.0       # composited source albedo std, preserved
ROUGHNESS_TARGET = 219.0       # stock ab2_t1 _r mean

Image.MAX_IMAGE_PIXELS = None


def stats(name, a):
    rgb = a[..., :3]
    return "%-8s mean=%6.1f std=%5.1f p05=%3d p95=%3d" % (
        name, rgb.mean(), rgb.std(),
        int(np.percentile(rgb, 5)), int(np.percentile(rgb, 95)))


def solve_gamma(rgb, target):
    """Exponent g with mean(255 * (x/255)**g) == target. Monotonic in g, so bisect."""
    x = rgb.astype(np.float32) / 255.0
    lo, hi = 0.05, 4.0
    for _ in range(60):
        mid = 0.5 * (lo + hi)
        got = float((x ** mid).mean() * 255.0)
        if got < target:        # too dark -> smaller exponent brightens
            hi = mid
        else:
            lo = mid
    return 0.5 * (lo + hi)


def dds_size(path):
    """Width from an existing DDS header, so re-writes keep the same dimensions."""
    try:
        with open(path, "rb") as fh:
            head = fh.read(20)
        if head[:4] != b"DDS ":
            return None
        return struct.unpack_from("<I", head, 16)[0]      # width at offset 16
    except OSError:
        return None


def to_image(a):
    return Image.fromarray(a, "RGBA")


def main(dry_run):
    size = dds_size("venator_a.dds") or 1024
    print("existing DDS is %dpx square; keeping that\n" % size)

    # ---- albedo -----------------------------------------------------------
    a = np.load("venator_a.npy")
    print(stats("_a before", a))
    gamma = solve_gamma(a[..., :3], ALBEDO_TARGET)
    lit = (a[..., :3].astype(np.float32) / 255.0) ** gamma * 255.0

    # A gamma strong enough to hit the stock mean also compresses contrast
    # (std 42 -> 25 here), which reads as washed-out plastic. Re-expand about the
    # mean to put the variation back, then re-centre: clipping at 255 pulls the
    # mean down, so the offset is solved rather than assumed.
    mean = float(lit.mean())
    k = ALBEDO_STD_TARGET / max(1e-6, float(lit.std()))
    lit = mean + (lit - mean) * k
    lo, hi = -60.0, 60.0
    for _ in range(40):
        mid = 0.5 * (lo + hi)
        if float(np.clip(lit + mid, 0, 255).mean()) < ALBEDO_TARGET:
            lo = mid
        else:
            hi = mid
    lifted = a.copy()
    lifted[..., :3] = np.clip(lit + 0.5 * (lo + hi), 0, 255).astype(np.uint8)
    print(stats("_a after", lifted)
          + "   (gamma %.4f, contrast x%.2f, target %.1f/%.1f)"
          % (gamma, k, ALBEDO_TARGET, ALBEDO_STD_TARGET))

    # ---- roughness --------------------------------------------------------
    r = np.load("venator_r.npy")
    print(stats("_r before", r))
    scale = ROUGHNESS_TARGET / max(1.0, float(r[..., :3].mean()))
    rough = r.copy()
    rough[..., :3] = np.clip(
        r[..., :3].astype(np.float32) * scale, 0, 255).astype(np.uint8)
    print(stats("_r after", rough) + "   (scale %.4f, target %.1f)" % (scale, ROUGHNESS_TARGET))

    # ---- glow -------------------------------------------------------------
    g = np.load("venator_g_lit.npy")
    print(stats("_g new", g) + "   (was mean 0.0 - fully black)")

    if dry_run:
        print("\ndry run - nothing written")
        return

    for suffix, arr, single in (("a", lifted, False), ("r", rough, True),
                                ("g", g, True)):
        png = "venator_%s_lit.png" % suffix
        out = "venator_%s.dds" % suffix
        to_image(arr).save(png)
        dds.write(out, Image.open(png), size=size, single_channel=single)
        print("wrote %s and %s" % (png, out))


if __name__ == "__main__":
    main("--dry-run" in sys.argv)
