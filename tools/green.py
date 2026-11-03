"""Dark-green palette for the Shisui x Suyou effects (purple / blue / orange originals -> emerald family).

Colour model (HSV, hue in turns)
  * hue      : emerald 146 deg for mid tones, deeper teal-emerald 152 deg for dark tones, mint-lime 138 deg for
               the hottest highlights -> the effect reads "dark green" with luminous mint cores
  * value    : kept (HDR colours keep their intensity); alpha-blended layers (smoke, dark slashes, dark
               under-layers) are 16 % darker so they read as deep forest green, not neon
  * saturation: coloured inputs become strongly saturated green; neutral inputs depend on the chain:
               - if nothing else in the render chain carries colour, whites become mint and greys emerald
               - if the texture / material already carries the green ("tint" chains) whites stay near-white
                 so stacked tints do not drift to flat pure green
  * brightness: purple -> green would raise perceived brightness (green is the brightest primary); it is
               pulled back (sqrt of the luminance ratio, at most -38 %) so the whole skin stays dark and rich
"""
import colorsys
import numpy as np

H_MID, H_HI, H_DARK = 146 / 360.0, 138 / 360.0, 152 / 360.0
NEUTRAL_SAT = 0.12

# vectors stored in m_Colors that are not colours
NOT_COLOR_WORDS = ('channel', 'speed', 'tiling', 'pos', 'plan', 'size', 'min', 'offset', 'para', 'info', 'rect',
                   'dir', 'hsv', 'xyzw', 'fix', 'intensity', 'cartoon', 'volume', 'fog', '_st', 'node_')


def _ss(a, b, x):
    t = np.clip((np.asarray(x, dtype=np.float64) - a) / (b - a), 0.0, 1.0)
    return t * t * (3 - 2 * t)


def lum(c):
    return 0.299 * c[0] + 0.587 * c[1] + 0.114 * c[2]


def sat_val(rgb):
    c = np.clip(np.asarray(rgb, dtype=np.float64), 0, None)
    v = c.max()
    return ((v - c.min()) / v if v > 1e-6 else 0.0), v


def is_colored(rgb):
    s, v = sat_val(rgb)
    return s >= NEUTRAL_SAT and v > 0.02


def to_green(rgb, mode='add', tint=False):
    """rgb (may be HDR) -> dark-green palette colour (same HDR scale)."""
    rgb = np.asarray(rgb, dtype=np.float64)
    hdr = max(float(rgb.max()), 1.0)
    c = np.clip(rgb / hdr, 0.0, 1.0)
    v = float(c.max())
    if v < 1e-4:
        return tuple(float(x) for x in rgb)
    s = (v - float(c.min())) / v
    hi = float(_ss(0.72, 1.0, v))
    dark = 1.0 - float(_ss(0.15, 0.5, v))
    if tint:
        s_neu = 0.10 + 0.20 * (1 - hi)
    else:
        s_neu = 0.82 * (1 - hi) + 0.42 * hi
    s_out = s_neu + (0.95 - s_neu) * float(_ss(0.1, 0.9, s))
    h = H_MID + (H_HI - H_MID) * hi + (H_DARK - H_MID) * dark
    k = 0.84 if mode == 'blend' else 1.0
    out = np.array(colorsys.hsv_to_rgb(h, s_out, v * k))
    li, lo = lum(c) * k, lum(out)
    if lo > li > 0:
        out *= max(0.62, (li / lo) ** 0.5)
    return tuple(float(x) for x in out * hdr)


# ------------------------------------------------------------------ typetree colour helpers
def _dict_rgb(d):
    return (d['r'], d['g'], d['b'])


def _set_rgb(d, rgb):
    d['r'], d['g'], d['b'] = (float(x) for x in rgb)


def _grad_keys(g):
    return [g[f'key{i}'] for i in range(g['m_NumColorKeys'])]


def map_dict(d, mode, tint, neutral_too):
    rgb = _dict_rgb(d)
    if not neutral_too and not is_colored(rgb):
        return False
    new = to_green(rgb, mode, tint)
    if np.allclose(new, rgb, atol=1e-6):
        return False
    _set_rgb(d, new)
    return True


def minmax_gradient_colors(mg):
    """MinMaxGradient -> list of colour dicts that are actually used."""
    st = mg['minMaxState']
    if st == 0:
        return [mg['maxColor']]
    if st == 2:
        return [mg['minColor'], mg['maxColor']]
    if st in (1, 4):
        return _grad_keys(mg['maxGradient'])
    if st == 3:
        return _grad_keys(mg['minGradient']) + _grad_keys(mg['maxGradient'])
    return []


def recolor_particle_system(tt, mode, chain_tint):
    """Start colour + colour over lifetime (+ by speed, trails, custom colour data).
    Neutral keys of the colour-over-lifetime gradient are intensity modulators and stay neutral; the start
    colour carries the green when nothing else does."""
    n = 0
    im = tt['InitialModule']
    start = minmax_gradient_colors(im['startColor'])
    cm = tt['ColorModule']
    over = minmax_gradient_colors(cm['gradient']) if cm['enabled'] else []
    start_col = any(is_colored(_dict_rgb(c)) for c in start)
    over_col = any(is_colored(_dict_rgb(c)) for c in over)
    carry = start_col or not over_col
    for c in start:
        n += map_dict(c, mode, chain_tint, neutral_too=carry)
    for c in over:
        n += map_dict(c, mode, chain_tint, neutral_too=False)
    for mod, keys in (('ColorBySpeedModule', ('gradient',)), ('TrailModule', ('colorOverLifetime', 'colorOverTrail'))):
        m = tt.get(mod)
        if not m or not m.get('enabled'):
            continue
        for k in keys:
            if k in m:
                for c in minmax_gradient_colors(m[k]):
                    n += map_dict(c, mode, chain_tint, neutral_too=False)
    cd = tt.get('CustomDataModule')
    if cd and cd.get('enabled'):
        for i in (0, 1):
            if cd.get(f'mode{i}') == 2 and f'color{i}' in cd:          # 2 = Color mode
                for c in minmax_gradient_colors(cd[f'color{i}']):
                    n += map_dict(c, mode, chain_tint, neutral_too=False)
    return n


def is_color_prop(name):
    n = name.lower()
    if any(w in n for w in NOT_COLOR_WORDS):
        return False
    return 'color' in n or n.endswith('_c') or n == '_light_c'


def recolor_material(tt, mode):
    """Coloured material colours -> green (white / grey / black stay: they are pass-through or intensity)."""
    n = 0
    sp = tt['m_SavedProperties']
    for k, v in sp['m_Colors']:
        if is_color_prop(k) and is_colored(_dict_rgb(v)):
            new = to_green(_dict_rgb(v), mode, tint=False)
            _set_rgb(v, new)
            n += 1
    fl = sp['m_Floats']
    for i, (k, v) in enumerate(fl):
        if k == '_Hue' and abs(v) > 1e-6:          # textures are already green: no shader hue rotation
            fl[i] = (k, 0.0)
            n += 1
    return n


def material_tints(tt):
    """Does the material itself carry colour (diffuse / tint colour or a coloured gradient map)?"""
    sp = tt['m_SavedProperties']
    cols = dict(sp['m_Colors'])
    kw = (tt.get('m_ShaderKeywords') or '').split()
    for k in ('_DiffuseColor', '_TintColor', '_MainColor', '_Color'):
        if k in cols and is_colored(_dict_rgb(cols[k])):
            return True
    if '_GRADIENT_ON' in kw:
        for k in ('_LeftColor', '_RightColor'):
            if k in cols and is_colored(_dict_rgb(cols[k])):
                return True
    return False


# ------------------------------------------------------------------ legacy clip colour curves
def recolor_legacy_clip(tt, mode_of_path, keep_path):
    """material.<Color>.r/g/b float curves of mesh effects -> green, sampled at the union of key times."""
    from cinematic import eval_curve, keys_from_samples
    groups = {}
    for fc in tt['m_FloatCurves']:
        a = fc['attribute']
        if a.startswith('material.') and a[-2:] in ('.r', '.g', '.b') and is_color_prop(a[len('material.'):-2]):
            groups.setdefault((fc['path'], a[:-2]), {})[a[-1]] = fc
    n = 0
    for (path, prop), ch in groups.items():
        if keep_path(path) or not all(c in ch for c in 'rgb'):
            continue
        ks = {c: sorted(ch[c]['curve']['m_Curve'], key=lambda k: k['time']) for c in 'rgb'}
        times = sorted(set(round(k['time'], 5) for c in 'rgb' for k in ks[c]))
        samples = [tuple(eval_curve(ks[c], t) for c in 'rgb') for t in times]
        if not any(is_colored(s) for s in samples):
            continue
        mode = mode_of_path(path)
        new = [to_green(s, mode, tint=False) if is_colored(s) else s for s in samples]
        for i, c in enumerate('rgb'):
            vs = [x[i] for x in new]
            if len(times) == 1:
                k = dict(ks[c][0]); k['value'] = float(vs[0]); ch[c]['curve']['m_Curve'] = [k]
            else:
                ch[c]['curve']['m_Curve'] = keys_from_samples(times, vs)
        n += 1
    return n


# ------------------------------------------------------------------ textures
def rgb_to_hsv_np(rgb):
    r, g, b = rgb[..., 0], rgb[..., 1], rgb[..., 2]
    mx = rgb.max(-1); mn = rgb.min(-1); d = mx - mn
    s = np.where(mx > 1e-6, d / np.maximum(mx, 1e-6), 0)
    h = np.zeros_like(mx)
    m = d > 1e-6
    rc = np.where(m, (mx - r) / np.maximum(d, 1e-6), 0)
    gc = np.where(m, (mx - g) / np.maximum(d, 1e-6), 0)
    bc = np.where(m, (mx - b) / np.maximum(d, 1e-6), 0)
    h = np.where(r == mx, bc - gc, np.where(g == mx, 2.0 + rc - bc, 4.0 + gc - rc))
    h = np.where(m, (h / 6.0) % 1.0, 0)
    return h, s, mx


def hsv_to_rgb_np(h, s, v):
    i = np.floor(h * 6.0)
    f = h * 6.0 - i
    p = v * (1 - s); q = v * (1 - s * f); t = v * (1 - s * (1 - f))
    i = i.astype(np.int32) % 6
    r = np.choose(i, [v, q, p, p, t, v]); g = np.choose(i, [t, v, v, q, p, p]); b = np.choose(i, [p, p, t, v, v, q])
    return np.stack([r, g, b], -1)


def recolor_rgba(a, hue_window=None):
    """a: float32 HxWx4 (0..1, straight alpha). Coloured texels -> green family, whites / greys untouched."""
    rgb = a[..., :3].astype(np.float64)
    h, s, v = rgb_to_hsv_np(rgb)
    w = _ss(0.10, 0.35, s) * _ss(0.03, 0.12, v)
    if hue_window is not None:
        lo, hi_ = hue_window[0] / 360.0, hue_window[1] / 360.0
        inside = _ss(lo - 0.03, lo, h) * (1 - _ss(hi_, hi_ + 0.03, h))
        w = w * inside * _ss(hue_window[2], hue_window[2] + 0.1, s)
    hi = _ss(0.72, 1.0, v)
    dark = 1 - _ss(0.15, 0.5, v)
    ht = H_MID + (H_HI - H_MID) * hi + (H_DARK - H_MID) * dark
    st = np.clip(s * 1.04, 0, 0.97)
    out = hsv_to_rgb_np(ht, st, v)
    li = rgb @ np.array([0.299, 0.587, 0.114]); lo = out @ np.array([0.299, 0.587, 0.114])
    k = np.where(lo > li, np.maximum(0.62, np.sqrt(np.clip(li, 0, None) / np.maximum(lo, 1e-6))), 1.0)
    out = out * k[..., None]
    res = rgb * (1 - w[..., None]) + out * w[..., None]
    b = a.copy()
    b[..., :3] = np.clip(res, 0, 1)
    return b, float(w.mean())
