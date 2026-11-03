"""Hidan look pass for the low-poly model atlas (777daa).

v2: violet irises, fairer skin, Jashin pendant, ETC2 RGB + full mips
v3: everything is resolution independent (1024 for Normal, 2048 for High) and adds
    * colour grade: richer crimson clouds/blades, blue-black cloak, cool silver hair/metal, gentle S-curve
    * clean line art: edge-preserving (bilateral) cleanup of the painterly upscale noise in flat areas,
      sharpening applied only on edges (no noise / block amplification)
    * UV-island padding: colours are pushed 16+ texels into the unused black background so mip levels no
      longer bleed dark seams into island borders
"""
import math
import numpy as np
from PIL import Image, ImageDraw

# all coordinates below are texels of the original 1024x1024 atlas; they are scaled for other sizes
EYE_BOXES = [(40, 80, 140, 152), (290, 80, 420, 162)]          # normal face eye, ritual (skull) face eye
IRIS = [(80.0, 122.0, 27.0, 24.0), (335.0, 122.0, 24.0, 22.0)]  # (cx, cy, rx, ry)
SKIN_BOXES = [(0, 0, 216, 252), (0, 765, 512, 1024), (512, 255, 770, 382)]
SEAM_U = 173.8
PENDANTS = [(874.0, 2), (874.0 - 512.0, 0)]   # (centre v, bleed texels) normal chest, ritual chest
PX_U, PX_V = 0.00238, 0.00194                 # metres per texel (1024 atlas) at the sternum


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


def box_mask(shape, boxes, k):
    m = np.zeros(shape, bool)
    for x0, y0, x1, y1 in boxes:
        m[int(y0 * k):int(y1 * k), int(x0 * k):int(x1 * k)] = True
    return m


def smoothstep(a, b, x):
    t = np.clip((x - a) / (b - a), 0, 1)
    return t * t * (3 - 2 * t)


# ---------------------------------------------------------------------------------------------- pendant
def draw_pendant(rgb, cv, bleed, k):
    S = 8
    r_world = 0.028
    px_u, px_v = PX_U / k, PX_V / k
    seam = SEAM_U * k
    cv = cv * k
    ru, rv = r_world / px_u, r_world / px_v
    x0 = int(math.floor(seam)) - 4 * k; x1 = int(math.ceil(seam + ru + 6 * k))
    y0 = int(math.floor(cv - rv - 40 * k)); y1 = int(math.ceil(cv + rv + 6 * k))
    W, H = (x1 - x0) * S, (y1 - y0) * S
    col = Image.new('RGBA', (W, H), (0, 0, 0, 0))
    dr = ImageDraw.Draw(col)
    cx, cy = (seam - x0) * S, (cv - y0) * S
    RU, RV = ru * S, rv * S
    dark = (24, 22, 28, 255); silver = (216, 220, 228, 255); shine = (252, 252, 255, 255)
    top = (cx + 0.035 / px_u * S, cy - (0.085 / px_v) * S)
    end = (cx + 0.004 / px_u * S, cy - RV * 0.98)
    dr.line([top, end], fill=dark, width=int(2.4 * k * S))
    dr.line([top, end], fill=(156, 158, 168, 255), width=int(1.1 * k * S))
    ring_t = 0.24
    dr.ellipse([cx - RU * 1.08, cy - RV * 1.08, cx + RU * 1.08, cy + RV * 1.08], fill=dark)
    dr.ellipse([cx - RU, cy - RV, cx + RU, cy + RV], fill=silver)
    dr.ellipse([cx - RU * (1 - ring_t), cy - RV * (1 - ring_t), cx + RU * (1 - ring_t), cy + RV * (1 - ring_t)], fill=dark)
    inner = (1 - ring_t) * 0.86
    dr.ellipse([cx - RU * inner, cy - RV * inner, cx + RU * inner, cy + RV * inner], fill=(0, 0, 0, 0))
    tri_r = 1 - ring_t
    pts = [(cx + RU * tri_r * math.cos(math.radians(a)), cy - RV * tri_r * math.sin(math.radians(a))) for a in (150, 30, 270)]
    dr.line(pts + [pts[0]], fill=dark, width=int(2.6 * k * S), joint='curve')
    dr.line(pts + [pts[0]], fill=silver, width=int(1.3 * k * S), joint='curve')
    dr.arc([cx - RU * 0.93, cy - RV * 0.93, cx + RU * 0.93, cy + RV * 0.93], 300, 340, fill=shine, width=int(0.9 * k * S))
    small = col.resize((x1 - x0, y1 - y0), Image.LANCZOS)
    a = np.asarray(small).astype(np.float32) / 255.0
    patch = rgb[y0:y1, x0:x1]
    us = np.arange(x0, x1) + 0.5
    right = (us >= seam)[None, :, None]
    alpha = a[..., 3:4] * right
    patch[:] = patch * (1 - alpha) + a[..., :3] * alpha
    for j in range(1, bleed * k + 1):
        u_left = int(math.floor(seam)) - j
        u_mirror = int(math.floor(2 * seam - (u_left + 0.5)))
        if x0 <= u_left < x1 and x0 <= u_mirror < x1:
            am = a[:, u_mirror - x0, 3:4]
            patch[:, u_left - x0] = patch[:, u_left - x0] * (1 - am) + patch[:, u_mirror - x0] * am


# ---------------------------------------------------------------------------------------------- passes
def recolor_eyes_skin(rgb, k):
    H, W = rgb.shape[:2]
    h, s, v = rgb_to_hsv(rgb)
    yy, xx = np.mgrid[0:H, 0:W]
    iris_area = np.zeros((H, W), bool)
    for (cx, cy, rx, ry) in IRIS:
        iris_area |= ((xx - cx * k) / (rx * k)) ** 2 + ((yy - cy * k) / (ry * k)) ** 2 <= 1.0
    red = ((h < 0.045) | (h > 0.94)) & (s > 0.42) & (v < 0.72) & (v > 0.04)
    w_eye = (iris_area & red) * np.clip((s - 0.42) / 0.2, 0, 1)
    eye_rgb = hsv_to_rgb(np.full_like(h, 300 / 360.0), np.clip(s * 0.78, 0, 1), np.clip(v * 1.15 + 0.03, 0, 1))
    rgb = rgb * (1 - w_eye[..., None]) + eye_rgb * w_eye[..., None]
    skin = box_mask((H, W), SKIN_BOXES, k) & (h > 0.015) & (h < 0.11) & (s > 0.16) & (s < 0.82) & (v > 0.22)
    w_skin = skin * np.clip((v - 0.22) / 0.1, 0, 1) * (1 - w_eye)
    skin_rgb = hsv_to_rgb(h + 0.011, s * 0.74, np.clip(v * 0.985 + 0.012, 0, 1))
    rgb = rgb * (1 - w_skin[..., None]) + skin_rgb * w_skin[..., None]
    return rgb, (w_eye > 0) | (w_skin > 0)


def grade(rgb, protect):
    """Colour grade toward a crisp anime Akatsuki palette. `protect`: pixels already recoloured (eyes/skin)."""
    h, s, v = rgb_to_hsv(rgb)
    out = rgb.copy()
    # crimson: clouds, blades, cloak lining -> deeper, richer, less pink/orange
    red = ((h < 0.035) | (h > 0.955)) & (s > 0.45) & (v > 0.18) & ~protect
    wr = red * smoothstep(0.45, 0.65, s)
    hr = np.where(h > 0.5, h - 1.0, h)                  # wrap to [-0.045, 0.035]
    hr = hr * 0.5 - 0.006                                 # pull toward ~358 deg crimson
    red_rgb = hsv_to_rgb(hr % 1.0, np.clip(s * 1.08 + 0.04, 0, 1), np.clip(0.06 + v * 0.94, 0, 1))
    out = out * (1 - wr[..., None]) + red_rgb * wr[..., None]
    # cloak: very dark, neutral or bluish -> blue-black with a cool lift in the shading
    dark = (v < 0.30) & ((s < 0.45) | ((h > 0.5) & (h < 0.75))) & ~protect
    wd = dark * (1 - smoothstep(0.18, 0.30, v))
    cool = hsv_to_rgb(np.full_like(h, 0.62), np.clip(0.38 + s * 0.2, 0, 0.6), v * 0.92)
    out = out * (1 - wd[..., None] * 0.65) + cool * (wd[..., None] * 0.65)
    # silver / white: hair, metal plate, cloud outlines, sclera -> cool silver
    light = (s < 0.22) & (v > 0.42) & ~protect
    wl = light * smoothstep(0.42, 0.6, v)
    silver = hsv_to_rgb(np.full_like(h, 0.6), np.clip(s * 0.5 + 0.05, 0, 0.12), np.clip(v * 1.02, 0, 1))
    out = out * (1 - wl[..., None] * 0.7) + silver * (wl[..., None] * 0.7)
    # gentle filmic S-curve on luminance (deeper darks, cleaner highlights)
    lum = out @ np.array([0.299, 0.587, 0.114])
    lum2 = lum + 0.10 * (lum - 0.5) * (1 - np.abs(2 * lum - 1))
    ratio = np.where(lum > 1e-4, lum2 / np.maximum(lum, 1e-4), 1.0)
    out = np.clip(out * ratio[..., None], 0, 1)
    return out


def clean_and_sharpen(rgb, k):
    import cv2
    img = (np.clip(rgb, 0, 1) * 255).astype(np.uint8)
    # edge-preserving cleanup of the painterly upscale noise
    smooth = cv2.bilateralFilter(img, d=5 + 2 * (k - 1), sigmaColor=16, sigmaSpace=2.5 * k)
    lum = cv2.cvtColor(smooth, cv2.COLOR_RGB2GRAY).astype(np.float32) / 255
    gx = cv2.Sobel(lum, cv2.CV_32F, 1, 0, ksize=3); gy = cv2.Sobel(lum, cv2.CV_32F, 0, 1, ksize=3)
    edge = np.sqrt(gx * gx + gy * gy)
    edge = cv2.GaussianBlur(edge, (0, 0), 0.8 * k)
    w_edge = smoothstep(0.06, 0.35, edge)[..., None]
    f = smooth.astype(np.float32) / 255
    blur = cv2.GaussianBlur(f, (0, 0), 1.0 * k)
    sharp = np.clip(f + (f - blur) * (0.9 + 0.3 * (k - 1)) * w_edge, 0, 1)
    # line art: darken already-dark strokes a little for crisp ink
    l2 = sharp @ np.array([0.299, 0.587, 0.114])
    ink = (l2 < 0.16)[..., None] * w_edge
    sharp = sharp * (1 - 0.25 * ink)
    return sharp


def pad_islands(rgb, used, k):
    """Push island colours into unused texels (16 px @1024) so mips do not bleed the black background."""
    import cv2
    img = rgb.astype(np.float32).copy()
    mask = used.astype(np.float32)
    for _ in range(16 * k):
        num = cv2.blur(img * mask[..., None], (3, 3))
        den = cv2.blur(mask, (3, 3))
        grow = (mask == 0) & (den > 0)
        if not grow.any():
            break
        img[grow] = num[grow] / den[grow][:, None]
        mask[grow] = 1.0
    return img


def uv_used_mask(uv_tris, size):
    """uv_tris: list of (T,3,2) arrays in UV space -> bool mask of texels covered (+1 px)."""
    import cv2
    m = np.zeros((size, size), np.uint8)
    sh = 4
    for tris in uv_tris:
        pts = np.empty_like(tris)
        pts[..., 0] = tris[..., 0] * size
        pts[..., 1] = (1 - tris[..., 1]) * size
        pts = np.round(pts * (1 << sh)).astype(np.int32)
        for tri in pts:     # one by one: mirrored UVs overlap and fillPoly(even-odd) would punch holes
            cv2.fillConvexPoly(m, tri, 255, lineType=cv2.LINE_8, shift=sh)
    m = cv2.dilate(m, np.ones((3, 3), np.uint8), iterations=1)
    return m > 0


def revamp(img, size=1024, uv_tris=None):
    """img: original PIL atlas (1024). Returns the revamped PIL RGB image at `size` (1024 or 2048)."""
    import cv2
    k = size // 1024
    src = np.asarray(img.convert('RGB')).astype(np.float32) / 255.0
    if k != 1:
        src = cv2.resize(src, (size, size), interpolation=cv2.INTER_LANCZOS4)
        src = np.clip(src, 0, 1)
    rgb, protect = recolor_eyes_skin(src, k)
    rgb = grade(rgb, protect)
    for cv_, bleed in PENDANTS:
        draw_pendant(rgb, cv_, bleed, k)
    rgb = clean_and_sharpen(rgb, k)
    if uv_tris is not None:
        rgb = pad_islands(rgb, uv_used_mask(uv_tris, size), k)
    return Image.fromarray((np.clip(rgb, 0, 1) * 255 + 0.5).astype(np.uint8), 'RGB')


# ---------------------------------------------------------------------------------------------- encoding
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
            lv = lv.resize((pw, ph), Image.NEAREST)
        data += etcpak.compress_etc2_rgb(lv.convert('RGBA').tobytes(), pw, ph)
    return data, len(levels)


def apply_to_texture_object(obj, new_img):
    """Write ETC2_RGB4 (format 45) + full mip chain into a Texture2D object via its typetree."""
    tt = obj.read_typetree()
    data, nmip = encode_etc2_rgb_mips(new_img)
    tt['m_Width'], tt['m_Height'] = new_img.size
    tt['m_TextureFormat'] = 45
    tt['m_MipCount'] = nmip
    tt['m_CompleteImageSize'] = len(data)
    tt['image data'] = data
    tt['m_StreamData'] = {'offset': 0, 'size': 0, 'path': ''}
    tt['m_TextureSettings']['m_MipBias'] = -0.3
    obj.save_typetree(tt)
    return len(data), nmip
