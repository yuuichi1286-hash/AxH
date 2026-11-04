"""Sanctum Island (PVP_049 High) texture remaster (v5).

AI 2x super-resolution (denoising mix) -> Kuwahara painterly clean-up (grain / blotches / compression noise
flattened, edges kept razor sharp) -> natural palette (naturalize: one cohesive earthy palette, referenced on the
user's Dota 2 screenshots) -> grass ramp -> glowing gold / rune ornaments -> edge-only sharpening -> grade.
Nothing adds synthetic grain or noise.

grade(): dehaze levels, mild clarity, mid-tone S-curve, moderate vibrance (protects saturated colours), warm-sunlight
/ neutral-cool-shade split tone.
"""
import numpy as np


def _ss(a, b, x):
    t = np.clip((x - a) / (b - a), 0, 1)
    return t * t * (3 - 2 * t)


def lum(x):
    return x[..., 0] * 0.299 + x[..., 1] * 0.587 + x[..., 2] * 0.114


def rgb_hsv(x):
    mx = x.max(-1); mn = x.min(-1); d = mx - mn
    s = np.where(mx > 1e-6, d / np.maximum(mx, 1e-6), 0)
    r, g, b = x[..., 0], x[..., 1], x[..., 2]
    dd = np.maximum(d, 1e-6)
    h = np.where(mx == r, (g - b) / dd % 6, np.where(mx == g, (b - r) / dd + 2, (r - g) / dd + 4))
    h = np.where(d > 1e-6, h * 60.0, 0.0)
    return h, s, mx


PRESETS = {
    # natural palette (v5): moderate vibrance, no extra green / water push, warm sun, neutral-cool shade
    #            levels  contrast vibrance greens water  split  clarity gamma  exposure
    'ground':   (0.030,  0.20,    0.18,    0.04,  0.10,  1.0,   0.08,   1.00,  1.00),
    'prop':     (0.020,  0.15,    0.14,    0.03,  0.06,  0.8,   0.06,   1.02,  0.98),
    'sky':      (0.015,  0.08,    0.12,    0.00,  0.06,  0.6,   0.06,   1.02,  0.97),
    'lightmap': (0.000,  0.06,    0.00,    0.00,  0.00,  1.0,   0.00,   1.00,  1.00),
}


def grade(rgb, kind='ground'):
    import cv2
    lv, con, vib, grn, wat, split, cla, gam, exp_ = PRESETS[kind]
    x = rgb.astype(np.float32)
    # 1. levels / dehaze, then darker mid-tones (gamma > 1) and a lower exposure: a deeper, moodier map
    if lv:
        x = np.clip((x - lv) / (1 - lv - lv * 0.4), 0, 1)
    if gam != 1.0:
        x = x ** gam
    x = x * exp_
    L = lum(x)
    # 2. clarity (local contrast on luminance, ~1.2 % of the image size)
    if cla:
        r = max(4.0, 0.012 * max(x.shape[:2]))
        Lb = cv2.GaussianBlur(L, (0, 0), r)
        Lc = np.clip(L + (L - Lb) * cla, 0, 1)
        x = x * (Lc / np.maximum(L, 1e-4))[..., None]
        L = Lc
    # 3. mid-tone S-curve
    if con:
        Ls = L + (L - 0.5) * con * (1 - np.abs(2 * L - 1)) * 2
        x = x * (np.clip(Ls, 0, 1) / np.maximum(L, 1e-4))[..., None]
        L = lum(np.clip(x, 0, 1))
    x = np.clip(x, 0, 1)
    # 4. vibrance + lusher greens + clearer water
    h, s, v = rgb_hsv(x)
    boost = vib * (1 - s) * _ss(0.05, 0.25, v)
    boost += grn * _ss(55, 75, h) * (1 - _ss(150, 170, h))
    boost += wat * _ss(160, 175, h) * (1 - _ss(205, 220, h))
    x = L[..., None] + (x - L[..., None]) * (1 + boost)[..., None]
    # 5. split tone: cool shadows, warm highlights
    if split:
        t = _ss(0.2, 0.85, L)[..., None]
        cool = np.array([0.985, 1.0, 1.018], np.float32)        # neutral-cool shade (no teal cast)
        warm = np.array([1.042, 1.016, 0.955], np.float32)      # warm sunlight
        tint = cool + (warm - cool) * t
        x = x * (1 + (tint - 1) * split)
    return np.clip(x, 0, 1).astype(np.float32)


def masks(rgb):
    """soft masks: grass (green vegetation), water (teal / blue), rest = soil, stone, paths"""
    h, s, v = rgb_hsv(rgb)
    grass = _ss(50, 70, h) * (1 - _ss(160, 178, h)) * _ss(0.16, 0.32, s) * _ss(0.05, 0.12, v)
    water = _ss(165, 180, h) * (1 - _ss(235, 250, h)) * _ss(0.12, 0.25, s)
    soil = np.clip(1 - grass - water, 0, 1)
    return grass.astype(np.float32), water.astype(np.float32), soil.astype(np.float32)


# ================================================================== v4: "clean premium"
def box(x, r):
    import cv2
    return cv2.boxFilter(x, -1, (2 * r + 1, 2 * r + 1), borderType=cv2.BORDER_REFLECT)


def guided_filter(I, p, r, eps):
    """He et al. guided filter (grey guide I, input p), box filters only."""
    mI, mp = box(I, r), box(p, r)
    cov = box(I * p, r) - mI * mp
    var = box(I * I, r) - mI * mI
    a = cov / (var + eps)
    b = mp - a * mI
    return box(a, r) * I + box(b, r)


def clean_surface(rgb, r=4, eps=0.0025):
    """Edge-preserving clean-up: blotches, compression blocks and grain in flat areas are smoothed away, edges and
    painted lines (variance above eps) stay crisp."""
    I = lum(rgb).astype(np.float32)
    out = np.stack([guided_filter(I, rgb[..., c].astype(np.float32), r, eps) for c in range(3)], -1)
    return np.clip(out, 0, 1).astype(np.float32)


def edge_mask(rgb, lo=0.03, hi=0.12, sigma=1.0):
    import cv2
    L = cv2.GaussianBlur(lum(rgb).astype(np.float32), (0, 0), sigma)
    gx = cv2.Sobel(L, cv2.CV_32F, 1, 0, ksize=3); gy = cv2.Sobel(L, cv2.CV_32F, 0, 1, ksize=3)
    return _ss(lo, hi, np.sqrt(gx * gx + gy * gy)).astype(np.float32)


def structure_sharpen(rgb, amount=0.45, sigma=1.4):
    """Sharpen only where there is real structure (edges / painted lines), never flat areas -> crisp, no grain."""
    import cv2
    m = edge_mask(rgb)
    d = rgb - cv2.GaussianBlur(rgb, (0, 0), sigma)
    return np.clip(rgb + d * amount * m[..., None], 0, 1).astype(np.float32)


def _ramp(t, stops):
    """t (H,W) 0..1 -> colour through gradient stops [(pos, (r,g,b)), ...]"""
    t = np.clip(t, 0, 1)
    pos = np.array([p for p, _ in stops], np.float32)
    cols = np.array([c for _, c in stops], np.float32)
    out = np.empty(t.shape + (3,), np.float32)
    for k in range(3):
        out[..., k] = np.interp(t, pos, cols[:, k])
    return out


GRASS_RAMP = [(0.0, (0.035, 0.085, 0.05)), (0.35, (0.10, 0.24, 0.10)), (0.65, (0.24, 0.45, 0.16)), (1.0, (0.62, 0.78, 0.36))]
SOIL_RAMP = [(0.0, (0.07, 0.05, 0.04)), (0.4, (0.22, 0.16, 0.10)), (0.75, (0.45, 0.36, 0.24)), (1.0, (0.78, 0.70, 0.55))]
WATER_RAMP = [(0.0, (0.02, 0.12, 0.14)), (0.4, (0.06, 0.34, 0.38)), (0.75, (0.22, 0.62, 0.62)), (1.0, (0.66, 0.92, 0.88))]


def stylize(rgb, grass, water, soil_brown, amount=0.5):
    """Cohesive premium palette: luminance of grass / brown soil / water mapped through curated gradients and
    blended with the painted colours (keeps their variety, removes muddy off-tones)."""
    import cv2
    L = cv2.GaussianBlur(lum(rgb).astype(np.float32), (0, 0), 0.8)
    out = rgb.copy()
    for mask, ramp, lo, hi in ((grass, GRASS_RAMP, 0.04, 0.62), (soil_brown, SOIL_RAMP, 0.05, 0.70), (water, WATER_RAMP, 0.03, 0.75)):
        t = (L - lo) / (hi - lo)
        target = _ramp(t, ramp)
        w = (mask * amount)[..., None]
        out = out * (1 - w) + target * w
    return np.clip(out, 0, 1).astype(np.float32)


def soil_mask(rgb):
    h, s, v = rgb_hsv(rgb)
    return (_ss(12, 22, h) * (1 - _ss(45, 58, h)) * _ss(0.2, 0.35, s) * _ss(0.05, 0.12, v)).astype(np.float32)


def ornament_glow(rgb, amount=1.0):
    """Gold trims and blue / cyan runes (floor engravings, buildings, statues, crystals): richer, brighter, with a
    soft baked halo. amount scales both the boost and the halo (1.0 ground, 0.6 props)."""
    import cv2
    h, s, v = rgb_hsv(rgb)
    gold = _ss(32, 40, h) * (1 - _ss(55, 63, h)) * _ss(0.3, 0.5, s) * _ss(0.35, 0.55, v)
    rune = _ss(180, 190, h) * (1 - _ss(235, 245, h)) * _ss(0.3, 0.5, s) * _ss(0.45, 0.7, v)
    out = rgb.copy()
    gold_col = np.array([1.0, 0.80, 0.38], np.float32)
    rune_col = np.array([0.45, 0.92, 1.0], np.float32)
    for m, col, boost in ((gold, gold_col, 0.35), (rune, rune_col, 0.40)):
        m = m.astype(np.float32) * amount
        halo = cv2.GaussianBlur(m, (0, 0), 3.0) * 0.5
        out = out * (1 + boost * m[..., None]) + (halo[..., None] * col * 0.18)
    return np.clip(out, 0, 1).astype(np.float32)


def palette(rgb):
    """Curated palette for the ground: pure greens are nudged toward the natural grass ramp (olive / brown dirt is
    left alone, so lanes keep their warm earth tones), brown soil toward the warm soil ramp, water toward teal."""
    grass, water, _ = masks(rgb)
    h, _, _ = rgb_hsv(rgb)
    return stylize(rgb, grass * _ss(68, 82, h) * 0.5, water * 0.45, soil_mask(rgb) * 0.9, amount=0.45)


def stone_mask(rgb):
    """Everything that is not grass or water (lane stone, paving, engravings, soil), soft edged."""
    import cv2
    grass, water, _ = masks(rgb)
    return cv2.GaussianBlur(np.clip(1 - grass - water, 0, 1).astype(np.float32), (0, 0), 2.0)


def hsv_rgb(h, s, v):
    """inverse of rgb_hsv (h in degrees)"""
    h = (h % 360.0) / 60.0
    i = np.floor(h)
    f = h - i
    p, q, t = v * (1 - s), v * (1 - s * f), v * (1 - s * (1 - f))
    i = i.astype(np.int32) % 6
    r = np.choose(i, [v, q, p, p, t, v])
    g = np.choose(i, [t, v, v, q, p, p])
    b = np.choose(i, [p, p, t, v, v, q])
    return np.stack([r, g, b], -1).astype(np.float32)


# Natural palette (reference: the user's Dota 2 screenshots, measured): grass hue ~76 deg in sunlight -> ~100 deg in
# shade at saturation ~0.35-0.5, dirt a warm ochre ~40 deg, stone almost neutral (saturation ~0.12), river a dark
# teal-green. One cohesive earthy palette instead of the map's blue / teal cast: not colourful, but rich.
def naturalize(rgb, kind='ground'):
    h, s, v = rgb_hsv(rgb)
    hn, sn = h.copy(), s.copy()
    if kind == 'foliage':
        # bushes / leaves (pale teal in the original): every green-teal texel -> a deeper, richer natural green
        band = _ss(40, 60, h) * (1 - _ss(205, 220, h))
        hn = hn + (108.0 - 18.0 * _ss(0.15, 0.6, v) - hn) * band * 0.85
        sn = sn + (np.clip(sn, 0.42, 0.62) - sn) * band * 0.8
        return np.clip(hsv_rgb(hn, np.clip(sn, 0, 1), v), 0, 1)
    vivid = _ss(0.16, 0.26, s)                  # a real colour (grass, moss, water) vs greyish stone
    # 1. greens and teals (grass, moss) -> natural grass green, yellower where lit, deeper green in shade
    band = _ss(48, 66, h) * (1 - _ss(176, 192, h)) * vivid
    hn = hn + (96.0 - 22.0 * _ss(0.12, 0.55, v) - hn) * band * 0.85
    sn = sn + (np.clip(sn, 0.34, 0.52) - sn) * band * 0.75
    # 2. river water (saturated teal / blue, ground only) -> dark teal-green, a little less saturated
    if kind == 'ground':
        water = _ss(176, 190, h) * (1 - _ss(240, 255, h)) * _ss(0.3, 0.45, s)
        hn = hn + (178.0 - hn) * water * 0.7
        sn = sn * (1 - 0.2 * water)
    # 3. greyish stone of any cool hue (lanes, paving, walls) -> near-neutral grey
    grey = (1 - vivid) * _ss(50, 70, h) * (1 - _ss(262, 275, h))
    sn = sn * (1 - 0.55 * grey)
    # 4. props: the blue-grey stone of buildings / statues calmer; glowing runes and crystals (very saturated) kept
    if kind == 'prop':
        blue = _ss(176, 192, h) * (1 - _ss(250, 265, h)) * vivid * (1 - _ss(0.45, 0.62, s))
        sn = sn * (1 - 0.45 * blue)
    # 5. dirt / bark -> warm ochre
    dirt = _ss(8, 18, h) * (1 - _ss(52, 62, h)) * _ss(0.1, 0.22, s)
    hn = hn + (38.0 - hn) * dirt * 0.5
    sn = sn + (np.clip(sn, 0.25, 0.45) - sn) * dirt * 0.5
    return np.clip(hsv_rgb(hn, np.clip(sn, 0, 1), v), 0, 1)


def kuwahara(rgb, r=4, q=8.0, sectors=8):
    """Generalized Kuwahara filter (Papari et al. 2007): per pixel, the mean of the most uniform of 8 Gaussian-
    weighted angular sectors wins. Grain, blotches and compression noise flatten into clean painted shapes while
    every edge stays razor sharp (it never averages across an edge) -> the clean 'hand-painted premium' look."""
    import cv2
    sigma = r / 2.0
    yy, xx = np.mgrid[-r:r + 1, -r:r + 1].astype(np.float32)
    ang = np.arctan2(yy, xx)
    gauss = np.exp(-(xx * xx + yy * yy) / (2 * sigma * sigma))
    gauss[(xx * xx + yy * yy) > (r + 0.5) ** 2] = 0
    x = rgb.astype(np.float32)
    x2 = x * x
    num = np.zeros_like(x); den = np.zeros(x.shape[:2], np.float32)
    for i in range(sectors):
        c = (i + 0.5) * 2 * np.pi / sectors
        d = np.angle(np.exp(1j * (ang - c)))                      # wrapped angular distance to sector centre
        w = np.clip(1.0 - np.abs(d) / (np.pi / sectors * 1.5), 0, 1) ** 2   # smooth, overlapping wedges
        w[r, r] = 1.0 / sectors
        ker = (w * gauss).astype(np.float32); ker /= ker.sum()
        m = cv2.filter2D(x, -1, ker, borderType=cv2.BORDER_REFLECT)
        v = cv2.filter2D(x2, -1, ker, borderType=cv2.BORDER_REFLECT) - m * m
        s = np.sqrt(np.maximum(v, 0).sum(-1)) * 255.0 / 8.0       # spread in ~8-level units (scale for q)
        a = 1.0 / (1.0 + s) ** q
        num += m * a[..., None]; den += a
    return np.clip(num / np.maximum(den, 1e-30)[..., None], 0, 1).astype(np.float32)
