"""Match the baked atlas to the levels EVE's shader expects.

Measured from the stock ab2_t1 maps:
    _a  mean 198.7  (bright near-white base; colour comes from the SOF
                     material system tinting this, not from the albedo itself)
    _m  mean 118.5  (selects among the area's material slots)
    _p3 mean ~0     (paint mask, essentially unused on this hull)
    _r  mean 219    (matte)

The bake produced a much darker albedo (112.9 where covered) over an atlas that
is 58% empty, so unmapped gaps read as black and bleed dark seams into island
edges. Gaps are filled with the neutral target and covered pixels are scaled to
the expected mean.
"""
import numpy as np
from PIL import Image

TARGET_ALBEDO = 199.0
TARGET_ROUGH = 219.0
NEUTRAL_NORMAL = (128, 128, 255, 255)


def coverage(a):
    """True where the bake actually wrote something.

    Alpha is only a reliable mask when it actually varies - some bake passes
    (roughness) write alpha=255 across the whole atlas, so unmapped gaps would
    count as covered, drag the mean down and make the rescale blow out and clip
    the real content. Fall back to luminance in that case.
    """
    if a.shape[2] == 4 and a[..., 3].min() < 250:
        return a[..., 3] > 8
    return a[..., :3].sum(axis=2) > 10


def level(path, out, target_mean, fill, clip=(0, 255)):
    a = np.array(Image.open(path).convert("RGBA")).astype(np.float32)
    m = coverage(a)
    if m.any():
        cur = a[..., :3][m].mean()
        if cur > 1.0:
            a[..., :3] *= (target_mean / cur)
    a[..., :3] = np.clip(a[..., :3], clip[0], clip[1])
    for c in range(3):
        ch = a[..., c]
        ch[~m] = fill[c]
    a[..., 3] = 255
    Image.fromarray(a.astype(np.uint8), "RGBA").save(out)
    res = np.array(Image.open(out).convert("RGBA"))
    print("%-18s -> mean %.1f (target %.1f)" % (out, res[..., :3].mean(), target_mean))


def fill_normal(path, out):
    a = np.array(Image.open(path).convert("RGBA"))
    m = coverage(a)
    for c in range(4):
        ch = a[..., c]
        ch[~m] = NEUTRAL_NORMAL[c]
    Image.fromarray(a, "RGBA").save(out)
    print("%-18s -> gaps filled with neutral normal" % out)


if __name__ == "__main__":
    level("venator_a.png", "venator_a_fix.png", TARGET_ALBEDO, (190, 190, 190))
    level("venator_r.png", "venator_r_fix.png", TARGET_ROUGH, (219, 219, 219))
    fill_normal("venator_n.png", "venator_n_fix.png")
    # glow must stay dark outside the emissive bits - do not brighten it
    a = np.array(Image.open("venator_g.png").convert("RGBA"))
    m = coverage(a)
    for c in range(3):
        a[..., c][~m] = 0
    a[..., 3] = 255
    Image.fromarray(a, "RGBA").save("venator_g_fix.png")
    print("venator_g_fix.png   -> gaps forced black")
