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
    #            levels  contrast vibrance greens water  split  clarity gamma
    'ground':   (0.030,  0.12,    0.42,    0.16,  0.24,  1.0,   0.26,   0.93),
    'prop':     (0.020,  0.08,    0.28,    0.10,  0.14,  0.8,   0.16,   0.96),
    'sky':      (0.015,  0.06,    0.26,    0.05,  0.16,  0.6,   0.10,   0.97),
    'lightmap': (0.000,  0.05,    0.00,    0.00,  0.00,  1.2,   0.00,   1.00),
}


def grade(rgb, kind='ground'):
    import cv2
    lv, con, vib, grn, wat, split, cla, gam = PRESETS[kind]
    x = rgb.astype(np.float32)
    # 1. levels / dehaze, then a gentle mid-tone lift (gamma < 1) so the extra contrast does not darken the map
    if lv:
        x = np.clip((x - lv) / (1 - lv - lv * 0.4), 0, 1)
    if gam != 1.0:
        x = x ** gam
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
