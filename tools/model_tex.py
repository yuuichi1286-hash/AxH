"""Hidan look pass for the low-poly model atlas (777daa, 1024x1024).

* iris: red (Sharingan-like) -> Hidan's violet-magenta (sampled from the detailed extlow model, hue ~322)
* skin: fairer, less orange (Hidan has a fair complexion)
* Jashin pendant (circle + inverted triangle) painted on the sternum of both the normal and the ritual body
  (chest UVs are mirrored at u=173.8, so half the symbol is painted and the mirror completes it)
* mild unsharp mask for crisper line art
* full mip chain encoded as ETC2_RGB (alpha was unused) -> smaller, no distance shimmer
"""
import math
import numpy as np
from PIL import Image, ImageDraw, ImageFilter

EYE_BOXES = [(40, 80, 140, 152), (290, 80, 420, 162)]          # normal face eye, ritual (skull) face eye
IRIS = [(80.0, 122.0, 27.0, 24.0), (335.0, 122.0, 24.0, 22.0)]  # (cx, cy, rx, ry) texels
SKIN_BOXES = [(0, 0, 216, 252), (0, 765, 512, 1024), (512, 255, 770, 382)]
SEAM_U = 173.8
PENDANTS = [  # (center v of normal chest, allowed bleed px left of seam)
    (874.0, 2),
    (874.0 - 512.0, 0),   # ritual body region is the same layout shifted up by 512 px
]
PX_U, PX_V = 0.00238, 0.00194  # metres per texel at the sternum


def rgb_to_hsv(rgb):
    r, g, b = rgb[..., 0], rgb[..., 1], rgb[..., 2]
    mx = rgb.max(-1); mn = rgb.min(-1); d = mx - mn
    h = np.zeros_like(mx)
    m = d > 1e-6
    rm = m & (mx == r); gm = m & (mx == g) & ~rm; bm = m & ~rm & ~gm
    h[rm] = ((g - b)[rm] / d[rm]) % 6
    h[gm] = (b - r)[gm] / d[gm] + 2
    h[bm] = (r - g)[bm] / d[bm] + 4
    h = h / 6.0
    s = np.where(mx > 1e-6, d / np.maximum(mx, 1e-6), 0)
    return h, s, mx


def hsv_to_rgb(h, s, v):
    h = (h % 1.0) * 6
    i = np.floor(h).astype(int) % 6
    f = h - np.floor(h)
    p = v * (1 - s); q = v * (1 - s * f); t = v * (1 - s * (1 - f))
    r = np.choose(i, [v, q, p, p, t, v]); g = np.choose(i, [t, v, v, q, p, p]); b = np.choose(i, [p, p, t, v, v, q])
    return np.stack([r, g, b], -1)


def box_mask(shape, boxes):
    m = np.zeros(shape, bool)
    for x0, y0, x1, y1 in boxes:
        m[y0:y1, x0:x1] = True
    return m


def draw_pendant(rgb, cv, bleed):
    """Paint the right half of the Jashin pendant at (SEAM_U, cv); mirror `bleed` px across the seam."""
    S = 8                                    # supersampling
    r_world = 0.028
    ru, rv = r_world / PX_U, r_world / PX_V   # ellipse radii in texels (circle on the model)
    x0 = int(math.floor(SEAM_U)) - 4; x1 = int(math.ceil(SEAM_U + ru + 6))
    y0 = int(math.floor(cv - rv - 40)); y1 = int(math.ceil(cv + rv + 6))
    W, H = (x1 - x0) * S, (y1 - y0) * S
    col = Image.new('RGBA', (W, H), (0, 0, 0, 0))
    dr = ImageDraw.Draw(col)
    cx, cy = (SEAM_U - x0) * S, (cv - y0) * S
    RU, RV = ru * S, rv * S
    dark = (28, 26, 30, 255); silver = (214, 216, 222, 255); shine = (250, 250, 255, 255)
    # chain (cord) from the upper chest to the top of the ring
    top = (cx + 0.035 / PX_U * S, cy - (0.085 / PX_V) * S)
    end = (cx + 0.004 / PX_U * S, cy - RV * 0.98)
    dr.line([top, end], fill=dark, width=int(2.4 * S))
    dr.line([top, end], fill=(150, 150, 158, 255), width=int(1.1 * S))
    # ring: dark outline, silver body
    ring_t = 0.24
    dr.ellipse([cx - RU * 1.08, cy - RV * 1.08, cx + RU * 1.08, cy + RV * 1.08], fill=dark)
    dr.ellipse([cx - RU, cy - RV, cx + RU, cy + RV], fill=silver)
    dr.ellipse([cx - RU * (1 - ring_t), cy - RV * (1 - ring_t), cx + RU * (1 - ring_t), cy + RV * (1 - ring_t)], fill=dark)
    inner = (1 - ring_t) * 0.86
    dr.ellipse([cx - RU * inner, cy - RV * inner, cx + RU * inner, cy + RV * inner], fill=(0, 0, 0, 0))
    # inverted triangle inscribed in the inner circle
    tri_r = 1 - ring_t
    pts = [(cx + RU * tri_r * math.cos(math.radians(a)), cy - RV * tri_r * math.sin(math.radians(a))) for a in (150, 30, 270)]
    dr.line(pts + [pts[0]], fill=dark, width=int(2.6 * S), joint='curve')
    dr.line(pts + [pts[0]], fill=silver, width=int(1.3 * S), joint='curve')
    # small highlight on the ring
    dr.arc([cx - RU * 0.93, cy - RV * 0.93, cx + RU * 0.93, cy + RV * 0.93], 300, 340, fill=shine, width=int(0.9 * S))
    small = col.resize((x1 - x0, y1 - y0), Image.LANCZOS)
    a = np.asarray(small).astype(np.float32) / 255.0
    patch = rgb[y0:y1, x0:x1]
    us = np.arange(x0, x1) + 0.5
    right = (us >= SEAM_U)[None, :, None]
    alpha = a[..., 3:4] * right
    patch[:] = patch * (1 - alpha) + a[..., :3] * alpha
    # bleed: mirror the painted columns into the unused gutter left of the seam (bilinear seam safety)
    for k in range(1, bleed + 1):
        u_left = int(math.floor(SEAM_U)) - k          # texel left of seam
        u_mirror = int(math.floor(2 * SEAM_U - (u_left + 0.5)))
        if x0 <= u_left < x1 and x0 <= u_mirror < x1:
            am = a[:, u_mirror - x0, 3:4]
            patch[:, u_left - x0] = patch[:, u_left - x0] * (1 - am) + patch[:, u_mirror - x0] * am


def revamp(img):
    rgba = np.asarray(img.convert('RGBA')).astype(np.float32) / 255.0
    rgb = rgba[..., :3].copy()
    H, W = rgb.shape[:2]
    h, s, v = rgb_to_hsv(rgb)
    eye_box = box_mask((H, W), EYE_BOXES)

    # ---- iris -> violet / magenta (elliptical masks around each iris, only saturated dark reds)
    yy, xx = np.mgrid[0:H, 0:W]
    iris_area = np.zeros((H, W), bool)
    for (cx, cy, rx, ry) in IRIS:
        iris_area |= ((xx - cx) / rx) ** 2 + ((yy - cy) / ry) ** 2 <= 1.0
    red = ((h < 0.045) | (h > 0.94)) & (s > 0.42) & (v < 0.72) & (v > 0.04)
    w_eye = (iris_area & red) * np.clip((s - 0.42) / 0.2, 0, 1)
    eye_rgb = hsv_to_rgb(np.full_like(h, 300 / 360.0), np.clip(s * 0.78, 0, 1), np.clip(v * 1.15 + 0.03, 0, 1))
    rgb = rgb * (1 - w_eye[..., None]) + eye_rgb * w_eye[..., None]

    # ---- fairer skin
    skin = box_mask((H, W), SKIN_BOXES) & (h > 0.015) & (h < 0.11) & (s > 0.16) & (s < 0.82) & (v > 0.22)
    w_skin = skin * np.clip((v - 0.22) / 0.1, 0, 1) * (1 - w_eye)
    skin_rgb = hsv_to_rgb(h + 0.011, s * 0.74, np.clip(v * 0.985 + 0.012, 0, 1))
    rgb = rgb * (1 - w_skin[..., None]) + skin_rgb * w_skin[..., None]

    # ---- Jashin pendant on normal + ritual chest
    for cv, bleed in PENDANTS:
        draw_pendant(rgb, cv, bleed)

    out = Image.fromarray((np.clip(rgb, 0, 1) * 255 + 0.5).astype(np.uint8), 'RGB')
    out = out.filter(ImageFilter.UnsharpMask(radius=1.1, percent=55, threshold=2))
    return out


def mip_chain(img):
    levels = [img]
    w, h = img.size
    while w > 1 or h > 1:
        w, h = max(1, w // 2), max(1, h // 2)
        levels.append(levels[-1].resize((w, h), Image.LANCZOS) if min(w, h) >= 4 else img.resize((w, h), Image.BOX))
    return levels


def encode_etc2_rgb_mips(img):
    import etcpak
    data = b''
    # Unity stores texture rows bottom-up (v=0 first); PIL images are top-down
    levels = mip_chain(img.convert('RGB').transpose(Image.FLIP_TOP_BOTTOM))
    for lv in levels:
        w, h = lv.size
        pw, ph = max(4, (w + 3) // 4 * 4), max(4, (h + 3) // 4 * 4)
        if (pw, ph) != (w, h):
            canvas = Image.new('RGB', (pw, ph))
            canvas.paste(lv, (0, 0))
            # replicate edge so padded texels don't bleed black into the tiny mips
            canvas = lv.resize((pw, ph), Image.NEAREST)
            lv = canvas
        rgba = lv.convert('RGBA').tobytes()
        data += etcpak.compress_etc2_rgb(rgba, pw, ph)
    return data, len(levels)


def apply_to_texture_object(obj, new_img):
    """Write ETC2_RGB4 (format 45) + full mip chain into a Texture2D object via its typetree."""
    tt = obj.read_typetree()
    data, nmip = encode_etc2_rgb_mips(new_img)
    tt['m_TextureFormat'] = 45
    tt['m_MipCount'] = nmip
    tt['m_CompleteImageSize'] = len(data)
    tt['image data'] = data
    tt['m_StreamData'] = {'offset': 0, 'size': 0, 'path': ''}
    tt['m_TextureSettings']['m_MipBias'] = -0.3
    obj.save_typetree(tt)
    return len(data), nmip
