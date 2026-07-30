"""Neutralise the red centreline stripe in the albedo atlas.

The Venator's flight-deck doors run down the middle of the dorsal surface, and
their source texture is strongly red: the `Hangar Door` and `Hangar Door.001`
atlas cells measure a mean of [89.9, 42.2, 42.2], saturation 0.53, against a hull
that sits around [140, 138, 134] at saturation 0.05. That is the stripe.

They are also DARK - luminance 52 against the hull's ~142 - so desaturating alone
would swap a red stripe for a black one. Each cell is therefore converted to
neutral grey by luminance and then rescaled to the hull's brightness, which keeps
the panel detail while removing both the tint and the darkness.

Operates on the composited atlas (venator_a.npy), so the existing brightness lift
in fix_brightness.py still runs afterwards and stays the single place that
decides final levels. The .npy is regenerable with composite_atlas.py.

    python fix_centreline.py [--dry-run]
"""
import math
import sys

import numpy as np

# Slot order of the JOINED atlas mesh - not alphabetical. composite_atlas.py packs
# material mi at cell (mi % GRID, mi // GRID) with atlas row 0 at the top.
MATS = ["Thruster Glow", "Engines", "Engine Folds", "Tail", "Back Half",
        "Attached Armor Plates", "Side Hangar Door", "Command Area",
        "Lower Command Area", "Front Half", "Hangar Bay", "Lower Trench",
        "Side Greeble", "Aux Hangar Door", "Turbolaser Body", "Turbolaser Barrell",
        "Hangar Door", "Large Side Turbolaser", "Windows", "Turbolaser Body.001",
        "Turbolaser Barrell.001", "Aux Hangar Door.001", "Hangar Door.001",
        "Lower Trench.001"]

# Everything that makes the centreline read differently from the hull around it.
# Measured cell luminances against a hull reference of ~140:
#
#   Hangar Door / .001    52   strongly red, [89.9 42.2 42.2] saturation 0.53
#   Lower Trench / .001  111   the trench itself, a fifth darker than the hull
#   Side Hangar Door     191   exactly the atlas FILL colour - never textured
#   Attached Armor Plates191   likewise: composite_atlas found no Base Color for it
#
# The last two are not a tint at all: composite_atlas.py leaves a cell at its fill
# (190,190,190) when a material has no image feeding Principled Base Color, so
# those surfaces render as flat bright grey and stand out against the hull.
NEUTRALISE = ("Hangar Door", "Hangar Door.001",
              "Lower Trench", "Lower Trench.001",
              "Side Hangar Door", "Attached Armor Plates")
# the surrounding hull materials, whose brightness the stripe should match
REFERENCE = ("Front Half", "Back Half", "Command Area", "Hangar Bay", "Tail")
LUMA = np.array([0.2126, 0.7152, 0.0722], dtype=np.float32)


def cell_bounds(mi, size, grid, cell):
    col, row = mi % grid, mi // grid
    return size - (row + 1) * cell, col * cell, cell


def describe(a, mi, size, grid, cell):
    y0, x0, c = cell_bounds(mi, size, grid, cell)
    m = a[y0:y0 + c, x0:x0 + c, :3].astype(np.float32).reshape(-1, 3).mean(axis=0)
    sat = 0.0 if m.max() == 0 else (m.max() - m.min()) / m.max()
    return m, sat, float(m @ LUMA)


# Per-pixel red removal. A whole-cell pass cannot reach the remaining stripes,
# because they are painted INSIDE the two biggest hull materials rather than in a
# cell of their own:
#
#   Back Half    1.66% of pixels reddish, mean [104.6 59.0 53.2]
#   Front Half   0.79%                         [111.7 64.6 63.5]
#   Aux Hangar Door(.001) 0.18%                [144.8 58.5 48.0]
#
# Those cells ARE the hull, so neutralising them wholesale would grey the entire
# ship. Averaged over a cell a thin stripe barely moves the mean either - Back
# Half reads saturation 0.055 - which is why measuring cell means said the atlas
# was already clean. Mask on colour instead, and only where it actually fires.
SAT_LO, SAT_HI = 0.12, 0.28      # feathered so the stripe edge does not band
MIN_VALUE = 40                   # ignore near-black pixels, where hue is noise


def neutralise_red(a, size, grid, cell, dry_run):
    """Grey out reddish pixels wherever they appear, matching local brightness."""
    total = 0
    for mi in range(grid * grid):
        y0, x0, c = cell_bounds(mi, size, grid, cell)
        block = a[y0:y0 + c, x0:x0 + c, :3].astype(np.float32)
        hi = block.max(axis=2)
        lo = block.min(axis=2)
        sat = np.where(hi > 0, (hi - lo) / np.maximum(hi, 1e-6), 0.0)

        # red = the R channel is the strongest one, not merely present
        is_red = (block[..., 0] >= block[..., 1]) & (block[..., 0] >= block[..., 2])
        weight = np.clip((sat - SAT_LO) / (SAT_HI - SAT_LO), 0.0, 1.0)
        weight = np.where(is_red & (hi > MIN_VALUE), weight, 0.0)
        touched = weight > 0.01
        if not touched.any():
            continue

        grey = block @ LUMA
        # Match the surrounding hull's brightness, or a red stripe simply becomes
        # a dark grey one - the stripes measure ~70 luma against a ~140 hull.
        surround = grey[(weight == 0.0) & (grey > MIN_VALUE)]
        if surround.size < 64:
            continue
        scale = float(surround.mean()) / max(1e-6, float(grey[touched].mean()))
        fixed = np.clip(grey * scale, 0, 255)

        w = weight[..., None]
        out = block * (1.0 - w) + np.repeat(fixed[:, :, None], 3, axis=2) * w
        if not dry_run:
            a[y0:y0 + c, x0:x0 + c, :3] = np.clip(out, 0, 255).astype(np.uint8)
        count = int(touched.sum())
        total += count
        print("  cell %2d  %6d px (%.2f%%)  red mean [%5.1f %5.1f %5.1f] "
              "lum %5.1f -> %5.1f  (x%.2f)"
              % (mi, count, 100.0 * count / touched.size,
                 block[touched][:, 0].mean(), block[touched][:, 1].mean(),
                 block[touched][:, 2].mean(),
                 grey[touched].mean(), fixed[touched].mean(), scale))
    print("  %d pixels neutralised" % total)


def main(dry_run):
    a = np.load("venator_a.npy")
    size = a.shape[0]
    grid = int(math.ceil(math.sqrt(len(MATS))))
    cell = size // grid

    target = float(np.mean([describe(a, MATS.index(n), size, grid, cell)[2]
                            for n in REFERENCE]))
    print("hull reference luminance: %.1f" % target)

    for name in NEUTRALISE:
        mi = MATS.index(name)
        y0, x0, c = cell_bounds(mi, size, grid, cell)
        before, sat, lum = describe(a, mi, size, grid, cell)
        block = a[y0:y0 + c, x0:x0 + c, :3].astype(np.float32)

        grey = block @ LUMA                      # keep the detail, drop the hue
        scale = target / max(1e-6, float(grey.mean()))
        grey = np.clip(grey * scale, 0, 255)
        if not dry_run:
            a[y0:y0 + c, x0:x0 + c, :3] = np.repeat(
                grey[:, :, None], 3, axis=2).astype(np.uint8)

        after, sat_a, lum_a = describe(a, mi, size, grid, cell)
        print("%-18s cell %2d  [%5.1f %5.1f %5.1f] sat %.3f lum %5.1f"
              "   ->  [%5.1f %5.1f %5.1f] sat %.3f lum %5.1f  (x%.2f)"
              % (name, mi, before[0], before[1], before[2], sat, lum,
                 after[0], after[1], after[2], sat_a, lum_a, scale))

    print("\nper-pixel red removal:")
    neutralise_red(a, size, grid, cell, dry_run)

    if dry_run:
        print("\ndry run - nothing written")
        return
    np.save("venator_a.npy", a)
    print("\nwrote venator_a.npy - now re-run fix_brightness.py to rebuild the DDS")


if __name__ == "__main__":
    main("--dry-run" in sys.argv)
