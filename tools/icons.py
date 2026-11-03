"""Suyou (Shisui x Suyou) skill icons in the shared Atlas_SkillIconAdd35_add atlas -> cooler dark-green grade.

Only the four Suyou sprites (S12610 passive, S12620 skill 1, S12630 skill 2, S12640 ultimate) are changed:
  * purple / blue / magenta energy -> deep emerald (reds = Sharingan, skin, yellows stay)
  * greens deepened towards dark emerald, cinematic S-curve contrast and clarity
  * soft vignette towards the circle edge + a thin mint inner rim glow
  * light sharpening
The atlas is ETC1: only the 4x4 blocks that overlap the four sprites are re-encoded, every other hero's icon
keeps its exact original bytes.
"""
import numpy as np
from PIL import Image
import green

SPRITES = ('S12610', 'S12620', 'S12630', 'S12640')
MAIN = 'Atlas_SkillIconAdd35_add_main'
MASK = 'Atlas_SkillIconAdd35_add_mask'


def _ss(a, b, x):
    t = np.clip((x - a) / (b - a), 0, 1)
    return t * t * (3 - 2 * t)


def grade_icon(rgb, alpha):
    """rgb float HxWx3 0..1 (top-down), alpha HxW (circle mask). Returns graded rgb."""
    import cv2
    H, W = alpha.shape
    h, s, v = green.rgb_to_hsv_np(rgb.astype(np.float64))
    deg = h * 360
    # 1. purple / blue / cyan / magenta energy -> emerald (not the dark hair, not reds/skin/yellow)
    w_cool = _ss(0.25, 0.45, s) * _ss(0.18, 0.32, v) * _ss(165, 185, deg) * (1 - _ss(330, 345, deg))
    # 2. existing greens / teals -> richer, deeper emerald
    w_green = _ss(0.15, 0.3, s) * _ss(70, 90, deg) * (1 - _ss(165, 185, deg))
    hi = _ss(0.75, 1.0, v)
    ht = (146 - 8 * hi) / 360.0
    st_cool = np.clip(s * 1.05, 0, 0.95)
    vt_cool = 0.92 * v ** 1.3                     # deeper: purple glow -> dark emerald, highlights keep detail
    cool = green.hsv_to_rgb_np(ht, st_cool, vt_cool)
    hg = h + (ht - h) * 0.55
    deep = green.hsv_to_rgb_np(hg, np.clip(s * 1.12, 0, 0.95), v * (0.9 + 0.1 * hi))
    out = rgb * (1 - w_cool[..., None]) + cool * w_cool[..., None]
    out = out * (1 - w_green[..., None]) + deep * w_green[..., None]
    # 3. cinematic contrast (S-curve around 0.45) + clarity (local contrast, large radius)
    out = np.clip(out, 0, 1)
    sc = out + (out - 0.45) * 0.18 * (1 - np.abs(out - 0.45) * 1.6).clip(0, 1)
    blur = cv2.GaussianBlur(sc.astype(np.float32), (0, 0), 6)
    out = np.clip(sc + (sc - blur) * 0.35, 0, 1)
    # 4. vignette + 5. thin mint inner rim inside the circle mask
    yy, xx = np.mgrid[0:H, 0:W].astype(np.float32)
    cy, cx = (H - 1) / 2.0, (W - 1) / 2.0
    r = np.sqrt((yy - cy) ** 2 + (xx - cx) ** 2) / (min(H, W) / 2.0)
    vig = 1 - 0.32 * _ss(0.55, 1.0, r)
    out = out * vig[..., None]
    rim = np.exp(-((r - 0.955) / 0.035) ** 2) * alpha
    mint = np.array([0.42, 1.0, 0.66])
    out = out + rim[..., None] * mint * 0.38
    # 6. light sharpening
    blur = cv2.GaussianBlur(out.astype(np.float32), (0, 0), 0.8)
    out = np.clip(out + (out - blur) * 0.45, 0, 1)
    return out


def _decode_etc1(data, w, h):
    import texture2ddecoder
    bgra = np.frombuffer(texture2ddecoder.decode_etc1(bytes(data), w, h), np.uint8).reshape(h, w, 4)
    return bgra[..., [2, 1, 0]].copy()               # bottom-up rows, RGB


def splice_etc1(data, w, h, img_bu, rects_bu):
    """Re-encode only the 4x4 blocks overlapping rects (x0, y0, x1, y1 in bottom-up pixel coords)."""
    import etcpak
    out = bytearray(data)
    bw = w // 4
    blocks = 0
    for x0, y0, x1, y1 in rects_bu:
        bx0, by0 = x0 // 4, y0 // 4
        bx1, by1 = (x1 + 3) // 4, (y1 + 3) // 4
        crop = img_bu[by0 * 4:by1 * 4, bx0 * 4:bx1 * 4]
        rgba = np.concatenate([crop, np.full(crop.shape[:2] + (1,), 255, np.uint8)], -1)
        enc = etcpak.compress_etc1_rgb(np.ascontiguousarray(rgba).tobytes(), crop.shape[1], crop.shape[0])
        cw = bx1 - bx0
        for j in range(by1 - by0):
            for i in range(cw):
                src = (j * cw + i) * 8
                dst = ((by0 + j) * bw + (bx0 + i)) * 8
                out[dst:dst + 8] = enc[src:src + 8]
                blocks += 1
    return bytes(out), blocks


def process_atlas(env, preview=None):
    objs = {o.path_id: o for o in env.objects}
    tex = {}
    for o in env.objects:
        if o.type.name == 'Texture2D':
            tex[o.read_typetree()['m_Name']] = o
    sprites = {}
    for o in env.objects:
        if o.type.name == 'MonoBehaviour':
            try:
                tt = o.read_typetree()
            except Exception:
                continue
            for s in tt.get('mSprites', []):
                if s['name'] in SPRITES:
                    sprites[s['name']] = (s['x'], s['y'], s['width'], s['height'])
    mo = tex[MAIN]
    tt = mo.read_typetree()
    assert tt['m_TextureFormat'] == 34 and tt['m_MipCount'] == 1 and tt['m_StreamData']['size'] == 0
    W, H = tt['m_Width'], tt['m_Height']
    data = tt['image data']
    bu = _decode_etc1(data, W, H)                         # bottom-up
    td = bu[::-1].astype(np.float32) / 255.0             # top-down
    mask_td = np.asarray(tex[MASK].read().image.convert('L')).astype(np.float32) / 255.0
    before, after = {}, {}
    rects = []
    new_td = td.copy()
    for name, (x, y, w, h) in sorted(sprites.items()):
        region = td[y:y + h, x:x + w]
        a = mask_td[y:y + h, x:x + w]
        g = grade_icon(region, a)
        new_td[y:y + h, x:x + w] = g
        before[name], after[name] = region, g
        rects.append((x, H - (y + h), x + w, H - y))       # bottom-up
    new_bu = (np.clip(new_td[::-1], 0, 1) * 255 + 0.5).astype(np.uint8)
    new_data, blocks = splice_etc1(data, W, H, new_bu, rects)
    tt['image data'] = new_data
    tt['m_CompleteImageSize'] = len(new_data)
    mo.save_typetree(tt)
    if preview is not None:
        preview['before'], preview['after'], preview['sprites'], preview['mask'] = before, after, sprites, mask_td
    return {'sprites': sorted(sprites), 'blocks_reencoded': blocks, 'blocks_total': (W // 4) * (H // 4)}
