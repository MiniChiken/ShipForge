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

NEUTRALISE = ("Hangar Door", "Hangar Door.001")
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

    if dry_run:
        print("\ndry run - nothing written")
        return
    np.save("venator_a.npy", a)
    print("\nwrote venator_a.npy - now re-run fix_brightness.py to rebuild the DDS")


if __name__ == "__main__":
    main("--dry-run" in sys.argv)
