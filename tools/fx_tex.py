"""Sharper, better-graded effect textures.

* edge-aware unsharp mask on colour and alpha: crisp slash / splash / spark edges, flat gradients (glows)
  are left alone so block artefacts are not amplified
* tiny alpha haze trim (texels below ~2 % opacity are dropped) -> cleaner silhouettes when stacked
* coloured textures (blood splatter, red flipbooks) are graded to a richer crimson
* noise / distortion / flow maps are not touched (they drive dissolves and UV warps, not colour)
* re-encoded in the original format, size and mip count; ASTC uses the THOROUGH preset (UnityPy's default
  EXHAUSTIVE preset is ~100x slower for no visible gain)
"""
import hashlib
import numpy as np
from PIL import Image

SKIP_WORDS = ('noise', 'niose', 'distort', 'flow', 'normal', 'dissolve', 'raodong', 'rd_')
ASTC_BLOCKS = {48: (4, 4), 49: (5, 5), 50: (6, 6), 51: (8, 8), 52: (10, 10), 53: (12, 12),
               54: (4, 4), 55: (5, 5), 56: (6, 6), 57: (8, 8), 58: (10, 10), 59: (12, 12)}


def smoothstep(a, b, x):
    t = np.clip((x - a) / (b - a), 0, 1)
    return t * t * (3 - 2 * t)


def should_touch(name):
    n = name.lower()
    return not any(w in n for w in SKIP_WORDS)


def enhance(img, name):
    """img: PIL RGBA (top-down). Returns enhanced PIL RGBA or None if the texture should stay as is."""
    import cv2
    if not should_touch(name):
        return None
    a = np.asarray(img.convert('RGBA')).astype(np.float32) / 255.0
    rgb, al = a[..., :3], a[..., 3]
    H, W = al.shape
    k = max(1.0, min(H, W) / 256.0)                 # radius scale (256 -> 1, 512 -> 2)
    # ---- edge weight from luminance and alpha structure
    lum = rgb @ np.array([0.299, 0.587, 0.114], np.float32)
    def grad(x):
        gx = cv2.Sobel(x, cv2.CV_32F, 1, 0, ksize=3); gy = cv2.Sobel(x, cv2.CV_32F, 0, 1, ksize=3)
        return np.sqrt(gx * gx + gy * gy)
    edge = np.maximum(grad(lum), grad(al))
    edge = cv2.GaussianBlur(edge, (0, 0), 0.7 * k)
    w = smoothstep(0.05, 0.3, edge)
    sig = 0.9 * k
    blur_rgb = cv2.GaussianBlur(rgb, (0, 0), sig)
    blur_al = cv2.GaussianBlur(al, (0, 0), sig)
    rgb2 = np.clip(rgb + (rgb - blur_rgb) * 0.95 * w[..., None], 0, 1)
    al2 = np.clip(al + (al - blur_al) * 0.75 * w, 0, 1)
    # ---- haze trim
    al2 = np.clip((al2 - 0.02) / 0.98, 0, 1)
    # ---- crimson grade for coloured texels
    mx = rgb2.max(-1); mn = rgb2.min(-1)
    sat = np.where(mx > 1e-4, (mx - mn) / np.maximum(mx, 1e-4), 0)
    vis = al2 > 0.1
    if vis.any() and float(sat[vis].mean()) > 0.2:
        r, g, b = rgb2[..., 0], rgb2[..., 1], rgb2[..., 2]
        reddish = (r >= g) & (r >= b) & (sat > 0.2)
        wr = reddish * smoothstep(0.2, 0.45, sat)
        # pull green/blue down relative to red (richer crimson), keep the brightest highlights
        rich = np.stack([np.clip(r * 1.02, 0, 1), g * 0.5, b * 0.56], -1)   # blood crimson, not pink
        hi = smoothstep(0.88, 1.0, lum)[..., None]
        rich = rich * (1 - hi * 0.45) + rgb2 * (hi * 0.45)
        rgb2 = rgb2 * (1 - wr[..., None]) + rich * wr[..., None]
    out = np.concatenate([rgb2, al2[..., None]], -1)
    return Image.fromarray((out * 255 + 0.5).astype(np.uint8), 'RGBA')


def _mips(img, count):
    levels = [img]
    w, h = img.size
    for _ in range(count - 1):
        w, h = max(1, w // 2), max(1, h // 2)
        levels.append(levels[-1].resize((w, h), Image.LANCZOS))
    return levels


def _astc(level, block):
    import astc_encoder
    w, h = level.size
    cfg = astc_encoder.ASTCConfig(astc_encoder.ASTCProfile.LDR, block[0], block[1], block_z=1,
                                  quality=astc_encoder.ASTCQualityPreset.THOROUGH,
                                  flags=astc_encoder.ASTCConfigFlags.USE_DECODE_UNORM8)
    ctx = astc_encoder.ASTCContext(cfg)
    im = astc_encoder.ASTCImage(astc_encoder.ASTCType.U8, w, h, 1, level.convert('RGBA').tobytes())
    return ctx.compress(im, astc_encoder.ASTCSwizzle.from_str('RGBA'))


def _etc2_rgba(level):
    import etcpak
    w, h = level.size
    pw, ph = max(4, (w + 3) // 4 * 4), max(4, (h + 3) // 4 * 4)
    if (pw, ph) != (w, h):
        level = level.resize((pw, ph), Image.NEAREST)
    return etcpak.compress_etc2_rgba(level.convert('RGBA').tobytes(), pw, ph)


def encode(img, fmt, mip_count):
    """img: PIL RGBA top-down -> Unity image data (bottom-up rows) in the given format with mip_count levels."""
    flipped = img.transpose(Image.FLIP_TOP_BOTTOM)
    data = b''
    for lv in _mips(flipped, mip_count):
        if fmt in ASTC_BLOCKS:
            data += _astc(lv, ASTC_BLOCKS[fmt])
        elif fmt == 47:
            data += _etc2_rgba(lv)
        else:
            raise ValueError(f'unsupported format {fmt}')
    return data


def key_of(img, fmt, mips, name):
    h = hashlib.sha1(img.tobytes()); h.update(f'{img.size}{fmt}{mips}{should_touch(name)}'.encode())
    return h.hexdigest()


def process_texture_job(job):
    """job: (key, rgba_bytes, size, fmt, mips, name, force) -> (key, data or None)
    force: the texture was resized / changed format, so it must be re-encoded even if not enhanced."""
    key, raw, size, fmt, mips, name, force = job
    img = Image.frombytes('RGBA', size, raw)
    new = enhance(img, name)
    if new is None:
        if not force:
            return key, None
        new = img
    return key, encode(new, fmt, mips)
