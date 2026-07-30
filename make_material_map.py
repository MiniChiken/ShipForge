"""Build EVE's material map (_m) from the baked metallic map.

_m selects among the faction's four material slots. For amarrbase these are:
    material1 white_ivory_matt        material3 black_gunmetal_metallic
    material2 grey_steel_brushed      material4 gold_true_polished

A FLAT value makes the entire hull one material and kills every specular
variation - which is why the Venator read as uniformly matte next to a stock
ship. Driving it from the source model's own metallic map restores the
distinction between painted plating and bare metal.

Stock ab2_t1 has mean 118.5 over the full 0-255 range, so variation is normal.
"""
import numpy as np
from PIL import Image

# slot centres, assuming the 0-255 range is split evenly across four slots
SLOT1, SLOT2, SLOT3 = 0, 85, 170


def build(metal_png, out_png, albedo_png=None):
    m = np.array(Image.open(metal_png).convert("RGBA"))
    metal = m[..., :3].mean(axis=2).astype(np.float32) / 255.0
    covered = m[..., :3].sum(axis=2) > 10

    # Base the whole hull on brushed steel, not matt. Leaving 93% of the hull on
    # slot1 reproduces the flat, dead look next to a stock ship - stock's mean is
    # 118.5, i.e. the higher slots dominate. Metal areas step up from there.
    # Slot choice is a BRIGHTNESS decision, not just a material one. slot3 is
    # literally black_gunmetal_metallic - sending 9% of the hull there produced
    # the black panels. A Venator is a light grey ship, so keep the hull on the
    # light matt slot and use brushed steel (still light, but with specular
    # response) for the metal detail. Nothing goes to gunmetal or gold.
    #
    # Threshold: the model's metallic map peaks at 110/255 (0.43), so any cutoff
    # >= 0.43 selects nothing. p90 is 53, 9% exceed 64, so 0.25 is where the
    # real metal detail lives.
    # Measured against stock: ours came out at mean 7.7 with 90.9% on slot1,
    # against stock ab2_t1's 118.5. slot1 is white_ivory_MATT - it has almost no
    # specular response, so the hull caught no light and read as black whenever
    # it was not lit head-on. The fix is not a brighter albedo (that was already
    # at the stock 198 mean); it is putting the surface on a material that
    # reflects.
    #
    # So the hull body goes to grey_steel_BRUSHED - still a light grey, but with
    # a specular response - and the model's own metal detail steps up to
    # gunmetal_metallic. slot3 is dark, so it stays a minority: 9% of the surface
    # here, which is what produced visible panel variation rather than the black
    # panels a larger share caused previously.
    # The base covers the WHOLE atlas. `covered` marks where the metallic map is
    # non-zero, which is only ~12% of it - masking the base by that sent 88% of
    # the surface back to matt. Atlas cells no geometry samples are irrelevant,
    # so there is nothing to preserve for them.
    out = np.full(metal.shape, SLOT2, np.uint8)               # grey_steel_brushed hull
    out[covered & (metal >= 0.25)] = SLOT3                    # gunmetal_metallic detail

    img = np.stack([out, out, out, np.full_like(out, 255)], axis=2)
    Image.fromarray(img, "RGBA").save(out_png)
    tot = out.size
    print("%s: slot1(matt)=%.1f%%  slot2(brushed)=%.1f%%  slot3(gunmetal)=%.1f%%  mean=%.1f"
          % (out_png, 100 * (out == SLOT1).sum() / tot, 100 * (out == SLOT2).sum() / tot,
             100 * (out == SLOT3).sum() / tot, out.mean()))


if __name__ == "__main__":
    build("venator_metal.png", "venator_m_fix.png")
