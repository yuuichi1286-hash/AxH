"""Sanctum Island (PVP_049 High) texture remaster: AI 2x super-resolution, detail restore, cinematic grade.

grade(): dehaze levels, mid-tone S-curve, vibrance (protects saturated colours), lusher greens, clearer turquoise
water, warm-highlight / cool-shadow split tone, clarity (large-radius local contrast).
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
    #            levels  contrast vibrance greens water  split  clarity gamma  exposure
    'ground':   (0.030,  0.15,    0.36,    0.14,  0.22,  1.0,   0.28,   1.08,  0.92),
    'prop':     (0.020,  0.10,    0.26,    0.10,  0.14,  0.8,   0.18,   1.08,  0.93),
    'sky':      (0.015,  0.07,    0.24,    0.05,  0.16,  0.6,   0.10,   1.05,  0.95),
    'lightmap': (0.000,  0.06,    0.00,    0.00,  0.00,  1.2,   0.00,   1.06,  0.95),
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
        cool = np.array([0.975, 0.995, 1.035], np.float32)
        warm = np.array([1.03, 1.012, 0.972], np.float32)
        tint = cool + (warm - cool) * t
        x = x * (1 + (tint - 1) * split)
    return np.clip(x, 0, 1).astype(np.float32)


def detail_restore(sr, lz, amount=0.35, sigma=1.2):
    """Add back the fine texture (grass grain, stone speckle) that the SR network smooths away."""
    import cv2
    hp = lz - cv2.GaussianBlur(lz, (0, 0), sigma)
    return np.clip(sr + hp * amount, 0, 1)


def sharpen(x, amount=0.35, sigma=0.8):
    import cv2
    return np.clip(x + (x - cv2.GaussianBlur(x, (0, 0), sigma)) * amount, 0, 1)


def masks(rgb):
    """soft masks: grass (green vegetation), water (teal / blue), rest = soil, stone, paths"""
    h, s, v = rgb_hsv(rgb)
    grass = _ss(50, 70, h) * (1 - _ss(160, 178, h)) * _ss(0.16, 0.32, s) * _ss(0.05, 0.12, v)
    water = _ss(165, 180, h) * (1 - _ss(235, 250, h)) * _ss(0.12, 0.25, s)
    soil = np.clip(1 - grass - water, 0, 1)
    return grass.astype(np.float32), water.astype(np.float32), soil.astype(np.float32)


def _unit(n):
    n = n - n.mean()
    return n / max(float(n.std()), 1e-6)


def detail_synth(rgb, seed=0, grass_amt=0.085, soil_amt=0.035):
    """Procedural micro-detail at the 2x texel scale (~1.3 cm / texel on the ground):
    * grass: short blade strokes (noise smeared along a slowly turning direction field) with darker clumps
      and lighter, slightly warmer tips
    * soil / stone / paths: fine grain plus small pebble mottling
    * water: untouched (stays smooth and clean)"""
    import cv2
    H, W = rgb.shape[:2]
    rng = np.random.RandomState(seed)
    grass, water, soil = masks(rgb)
    # --- grass blades
    n0 = rng.rand(H, W).astype(np.float32)
    k = 7
    strokes = []
    for ang in (0, 45, 90, 135):
        ker = np.zeros((k, k), np.float32)
        c = k // 2
        dx, dy = np.cos(np.radians(ang)), np.sin(np.radians(ang))
        for t in np.linspace(-c, c, 4 * k):
            ker[int(round(c + dy * t)), int(round(c + dx * t))] = 1.0
        ker /= ker.sum()
        strokes.append(cv2.filter2D(n0, -1, ker, borderType=cv2.BORDER_REFLECT))
    field = cv2.GaussianBlur(rng.rand(H // 32 + 2, W // 32 + 2).astype(np.float32), (0, 0), 1.0)
    field = cv2.resize(field, (W, H), interpolation=cv2.INTER_CUBIC) * 4.0
    wts = [np.clip(1 - np.abs(((field - i) + 2) % 4 - 2), 0, 1) for i in range(4)]
    blades = sum(w * s_ for w, s_ in zip(wts, strokes)) / np.maximum(sum(wts), 1e-4)
    blades = _unit(blades - cv2.GaussianBlur(blades, (0, 0), 2.0))
    clumps = _unit(cv2.GaussianBlur(rng.rand(H, W).astype(np.float32), (0, 0), 6.0))
    g = np.clip(blades * 0.85 + clumps * 0.3, -2.5, 2.5)
    # --- soil / stone grain and pebbles
    fine = _unit(cv2.GaussianBlur(rng.rand(H, W).astype(np.float32), (0, 0), 0.7))
    pebble = _unit(cv2.GaussianBlur(rng.rand(H, W).astype(np.float32), (0, 0), 2.5))
    sgrain = np.clip(fine * 0.6 + pebble * 0.5, -3, 3)
    lum_mul = 1 + grass * grass_amt * g + soil * soil_amt * sgrain
    x = rgb * lum_mul[..., None]
    # warmer tips / cooler roots on grass
    tint = np.array([0.018, 0.012, -0.012], np.float32)
    x = x + (grass * np.clip(g, -2, 2) * 0.5)[..., None] * tint
    return np.clip(x, 0, 1).astype(np.float32)


def local_detail(x, mask, small=0.35, mid=0.18):
    """Two-scale local contrast where the mask is 1 (existing painted detail pops more)."""
    import cv2
    d = (x - cv2.GaussianBlur(x, (0, 0), 1.3)) * small + (x - cv2.GaussianBlur(x, (0, 0), 4.0)) * mid
    return np.clip(x + d * mask[..., None], 0, 1).astype(np.float32)
