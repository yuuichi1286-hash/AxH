"""HD effect textures for Shisui x Suyou: 2x upscale + edge-aware sharpening + dark-green recolour.

* textures up to 256 px are upscaled 2x (premultiplied Lanczos, no dark fringes on alpha edges), 512 px
  textures keep their size; everything is sharpened with an edge-aware unsharp mask (colour and alpha)
* coloured texels are recoloured to the dark-green palette (green.recolor_rgba); whites/greys stay so hot
  cores remain white-mint; 'keep' textures (Sharingan, character art, wood log...) are only sharpened
* data textures (noise / dissolve / mask / clamp) are left untouched
* re-encoded in the original format: ETC2 RGBA8 (47), ETC1 (34), ASTC (48-59), RGB24 (3), RGBA32 (4)
"""
import hashlib
import numpy as np
from PIL import Image
import green
from fx_tex import ASTC_BLOCKS, _astc, _etc2_rgba, _mips

UPSCALE_MAX = 256


def _etc1(level):
    import etcpak
    w, h = level.size
    pw, ph = max(4, (w + 3) // 4 * 4), max(4, (h + 3) // 4 * 4)
    if (pw, ph) != (w, h):
        level = level.resize((pw, ph), Image.NEAREST)
    return etcpak.compress_etc1_rgb(level.convert('RGBA').tobytes(), pw, ph)


def encode(img, fmt, mip_count):
    flipped = img.transpose(Image.FLIP_TOP_BOTTOM)
    data = b''
    for lv in _mips(flipped, mip_count):
        if fmt in ASTC_BLOCKS:
            data += _astc(lv, ASTC_BLOCKS[fmt])
        elif fmt == 47:
            data += _etc2_rgba(lv)
        elif fmt == 34:
            data += _etc1(lv)
        elif fmt == 4:
            data += lv.convert('RGBA').tobytes()
        elif fmt == 3:
            data += lv.convert('RGB').tobytes()
        else:
            raise ValueError(f'unsupported format {fmt}')
    return data


def full_chain(w, h):
    return int(np.floor(np.log2(max(w, h)))) + 1


def _smooth(a, b, x):
    t = np.clip((x - a) / (b - a), 0, 1)
    return t * t * (3 - 2 * t)


def upscale(a, scale):
    import cv2
    if scale == 1:
        return a
    H, W = a.shape[:2]
    al = a[..., 3:4]
    pm = np.concatenate([a[..., :3] * al, al], -1)
    big = cv2.resize(pm, (W * scale, H * scale), interpolation=cv2.INTER_LANCZOS4)
    big = np.clip(big, 0, 1)
    al2 = big[..., 3:4]
    rgb = np.where(al2 > 1e-3, big[..., :3] / np.maximum(al2, 1e-3), 0)
    return np.concatenate([np.clip(rgb, 0, 1), al2], -1).astype(np.float32)


def sharpen(a, opaque):
    import cv2
    rgb, al = a[..., :3], a[..., 3]
    H, W = al.shape
    k = max(1.0, min(H, W) / 256.0)
    lum = rgb @ np.array([0.299, 0.587, 0.114], np.float32)

    def grad(x):
        gx = cv2.Sobel(x, cv2.CV_32F, 1, 0, ksize=3); gy = cv2.Sobel(x, cv2.CV_32F, 0, 1, ksize=3)
        return np.sqrt(gx * gx + gy * gy)
    edge = grad(lum) if opaque else np.maximum(grad(lum), grad(al))
    edge = cv2.GaussianBlur(edge, (0, 0), 0.7 * k)
    w = _smooth(0.04, 0.28, edge)
    sig = 0.9 * k
    rgb2 = np.clip(rgb + (rgb - cv2.GaussianBlur(rgb, (0, 0), sig)) * 1.05 * w[..., None], 0, 1)
    if opaque:
        al2 = al
    else:
        al2 = np.clip(al + (al - cv2.GaussianBlur(al, (0, 0), sig)) * 0.8 * w, 0, 1)
        al2 = np.clip((al2 - 0.02) / 0.98, 0, 1)          # haze trim: cleaner silhouettes when stacked
    return np.concatenate([rgb2, al2[..., None]], -1)


def process(img, fmt, mips, recolor, hue_window, scale):
    a = np.asarray(img.convert('RGBA')).astype(np.float32) / 255.0
    opaque = fmt in (34, 3) or float(a[..., 3].min()) > 0.99
    cov = 0.0
    if recolor:
        a, cov = green.recolor_rgba(a, hue_window)
        a = a.astype(np.float32)
    a = upscale(a, scale)
    a = sharpen(a, opaque)
    out = Image.fromarray((np.clip(a, 0, 1) * 255 + 0.5).astype(np.uint8), 'RGBA')
    return out, cov


def key_of(img, fmt, mips, plan):
    h = hashlib.sha1(img.tobytes()); h.update(f'{img.size}{fmt}{mips}{plan}'.encode())
    return h.hexdigest()


def slot_kind(slot):
    """material texture slot -> 'diffuse' (shown colour), 'ramp' (colour lookup), 'data' (mask / noise /
    dissolve / displacement, never recoloured) or 'other' (other colour textures, e.g. flowing-light)."""
    s = slot.lower()
    if 'ramp' in s:
        return 'ramp'
    if s in ('_diffuse', '_maintex', '_diff', '_flu_tex', '_basemap', '_maintexture'):
        return 'diffuse'
    if any(w in s for w in ('mask', 'dissolve', 'noise', 'displacement', 'distort', 'normal', 'bump', 'flowmap')):
        return 'data'
    return 'other'


def plan_for(name, w, h, fmt, slots, keep):
    """-> (recolor, hue_window, scale) or None for untouched data textures."""
    n = name.lower()
    kinds = {slot_kind(s) for s in slots} or {'diffuse'}
    data_name = any(w_ in n for w_ in ('noise', 'niose', 'distort', 'dissolve', 'raodong', 'rd_')) or \
        n.startswith(('mask', 'clamp'))
    if kinds == {'data'}:
        return None
    if data_name and 'diffuse' not in kinds:
        return None
    recolor = not keep and 'data' not in kinds
    hue_window = HUE_WINDOWS.get(name)
    raw = fmt in (3, 4)
    ramp = 'ramp' in kinds or 'ramp' in n
    scale = 2 if (max(w, h) <= UPSCALE_MAX and min(w, h) >= 16 and not raw and not ramp) else 1
    return recolor, hue_window, scale


# textures that mix character art with effect colour: only the given hue range (deg lo, hi, min sat) is recoloured
HUE_WINDOWS = {'Special_FHD_ZXD_0013': (250, 320, 0.45)}


def process_texture_job(job):
    """job: (key, rgba_bytes, size, fmt, mips, name, plan) -> (key, data, new_size, new_mips, coverage)"""
    key, raw, size, fmt, mips, name, plan = job
    recolor, hue_window, scale = plan
    img = Image.frombytes('RGBA', size, raw)
    out, cov = process(img, fmt, mips, recolor, hue_window, scale)
    w, h = out.size
    if mips > 1 and mips >= full_chain(*size):
        new_mips = full_chain(w, h)
    else:
        new_mips = mips
    return key, encode(out, fmt, new_mips), (w, h), new_mips, cov
