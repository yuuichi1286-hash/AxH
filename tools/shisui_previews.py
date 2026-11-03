"""Shisui x Suyou previews: textures before/after and effect colour/fade timelines.

usage: python shisui_previews.py <orig fx root> <new fx root> <out dir>
"""
import sys, os, collections
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import numpy as np
import UnityPy
from UnityPy.files import BundleFile
from PIL import Image, ImageDraw, ImageFont
from vfx_fix import mm_max, get_alpha, get_colors, interp, interp_col
import green

o_root, n_root, out_dir = sys.argv[1:4]
os.makedirs(out_dir, exist_ok=True)
A = 'Art/android'


def font(sz):
    for p in ('/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf', '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf'):
        if os.path.exists(p):
            return ImageFont.truetype(p, sz)
    return ImageFont.load_default()


F, FS, FB = font(15), font(12), font(22)


def textures(path):
    env = UnityPy.load(path)
    if not isinstance(env.files[list(env.files)[0]], BundleFile):
        return {}
    return {o.read().m_Name: o.read() for o in env.objects if o.type.name == 'Texture2D'}


# ------------------------------------------------------------------ 1. textures before / after
PICK = [('k/Kaijiacike_attack01', 'Trail_SD_ZXD_0107'), ('zzp1_k/zzp1_Kaijiacike_attack01_skin02_add', 'Trail_SD_ZXD_0116'),
        ('zzp2_k/zzp2_Kaijiacike_Henshin_skill02_attack01_skin02_add', 'Fire_HD_ZXD_0001'),
        ('zzp2_k/zzp2_Kaijiacike_Henshin_skill02_attack01_skin02_add', 'Trail_HD_ZXD_0039'),
        ('zzp2_k/zzp2_Kaijiacike_Henshin_born_skin02_add', 'Special_HD_CJQ_0311'),
        ('k/Kaijiacike_Henshin_skill01_hold', 'Special_HD_CJQ_0310'),
        ('zzp2_k/zzp2_Kaijiacike_skill03_attack01_NEW_skin02_add', 'Lightning_SD_LYQ_003_cnnew'),
        ('k/Kaijiacike_skill03_attack01_NEW', 'Special_HD_ZXD_0095'),
        ('zzp2_k/zzp2_Kaijiacike_skill02_fire_NEW_skin02_add', 'Fire_HD_ZXD_0002'),
        ('zzp2_k/zzp2_Kaijiacike_skill02_fire_NEW_skin02_add', 'Trail_HD_ZXD_0053'),
        ('zzp2_k/zzp2_Kaijiacike_skill01_bullet_skin02_add', 'Lightning_HD_ZXD_0001'),
        ('k/Kaijiacikeshoubi_atk_hit', 'Special_HD_CJQ_0307'),
        ('zzp2_k/zzp2_Kaijiacike_atk_hit_skin02_add', 'Glow_SD_CJQ_0013'),
        ('zzp2_k/zzp2_Kaijiacike_skill03_attack02_NEW_skin02_add', 'Decal_SD_WHM_0004'),
        ('zzp2_k/zzp2_Kaijiacike_skill03_ui_skin02_add', 'Trail_SD_ZXD_0122'),
        ('kaijiacike_CityAction_cam_add', 'Special_FHD_CJQ_0084')]
S = 220
cols = 4
rows = (len(PICK) + cols - 1) // cols
sheet = Image.new('RGB', (cols * (2 * S + 30) + 10, rows * (S + 44) + 50), (14, 16, 18))
dr = ImageDraw.Draw(sheet)
dr.text((12, 10), 'Tekstur efek: kiri = asli (resolusi asli), kanan = Shisui hijau gelap HD (2x, tajam)', font=FB, fill=(235, 235, 235))
for i, (b, name) in enumerate(PICK):
    rel = b if '/' in b else 'k/' + b
    to = textures(os.path.join(o_root, A, rel + '.unity3d')).get(name)
    tn = textures(os.path.join(n_root, A, rel + '.unity3d')).get(name)
    if to is None or tn is None:
        print('missing', b, name); continue
    x0 = 10 + (i % cols) * (2 * S + 30); y0 = 50 + (i // cols) * (S + 44)
    for j, t in enumerate((to, tn)):
        im = t.image.convert('RGBA')
        a = np.asarray(im).astype(np.float32) / 255
        rgb = a[..., :3] * a[..., 3:4]                          # how it looks additively on black
        im = Image.fromarray((rgb * 255).astype(np.uint8)).resize((S, S), Image.NEAREST if j == 0 else Image.LANCZOS)
        sheet.paste(im, (x0 + j * (S + 6), y0))
        dr.text((x0 + j * (S + 6), y0 + S + 3), f'{t.m_Width}x{t.m_Height}', font=FS, fill=(200, 200, 200))
    dr.text((x0, y0 + S + 18), name[:34], font=FS, fill=(140, 220, 170))
sheet.save(os.path.join(out_dir, '2_tekstur_hijau_hd.png'))


# ------------------------------------------------------------------ 2. effect timelines (colour x alpha x size over time)
def systems(path):
    env = UnityPy.load(path)
    if not isinstance(env.files[list(env.files)[0]], BundleFile):
        return []
    gos = {o.path_id: o.read_typetree()['m_Name'] for o in env.objects if o.type.name == 'GameObject'}
    out = []
    for o in env.objects:
        if o.type.name != 'ParticleSystem':
            continue
        tt = o.read_typetree()
        im = tt['InitialModule']
        d = mm_max(tt['startDelay']) if isinstance(tt['startDelay'], dict) else 0.0
        life = max(mm_max(im['startLifetime']), 0.02)
        size = mm_max(im['startSize'])
        cols = green.minmax_gradient_colors(im['startColor'])
        start = np.mean([[c['r'], c['g'], c['b']] for c in cols], 0) if cols else np.ones(3)
        sa = np.mean([c['a'] for c in cols]) if cols else 1.0
        cm = tt['ColorModule']
        g = cm['gradient']['maxGradient'] if cm['enabled'] and cm['gradient']['minMaxState'] in (1, 3) else None
        out.append((d, life, size, start, sa, g, gos.get(tt['m_GameObject']['m_PathID'], '')))
    return out


def effect_systems(root, stem):
    res = []
    for sub, pre in (('k', ''), ('zzp1_k', 'zzp1_'), ('zzp2_k', 'zzp2_')):
        p = os.path.join(root, A, sub, (pre + stem + ('_skin02_add' if pre else '')) + '.unity3d')
        if os.path.exists(p):
            res += systems(p)
    return sorted(res, key=lambda x: (x[0], -x[2]))


EFFECTS = [('Basic attack 1', 'Kaijiacike_attack01'), ('Basic hit', 'Kaijiacike_atk_hit'),
           ('Skill 1 (lempar)', 'Kaijiacike_skill01_attack'), ('Skill 1 hit', 'Kaijiacike_skill01_hit'),
           ('Skill 2 api', 'Kaijiacike_skill02_fire_NEW'), ('Ultimate serang', 'Kaijiacike_skill03_attack01_NEW'),
           ('Mode Susanoo: tebasan', 'Kaijiacike_Henshin_skill02_attack01'), ('Mode Susanoo: lemparan', 'Kaijiacike_Henshin_skill03_fire')]
W, ROWH = 560, 15
T_MAX = 2.2
panel_h = []
data = []
for title, stem in EFFECTS:
    a, b = effect_systems(o_root, stem), effect_systems(n_root, stem)
    data.append((title, a, b))
    panel_h.append(max(len(a), len(b)) * ROWH + 40)
H = sum(panel_h) + 70
img = Image.new('RGB', (2 * W + 240, H), (12, 13, 15))
dr = ImageDraw.Draw(img)
dr.text((12, 10), 'Timeline partikel per efek (warna x alpha; tebal = ukuran)  |  kiri: asli   kanan: Shisui hijau gelap', font=F, fill=(235, 235, 235))
dr.text((12, 30), f'sumbu-x: waktu 0 - {T_MAX:.1f} detik', font=FS, fill=(170, 170, 170))
y = 60
for (title, a, b), ph in zip(data, panel_h):
    dr.text((12, y + 4), title, font=F, fill=(140, 230, 170))
    for k, rows_ in enumerate((a, b)):
        x0 = 230 + k * (W + 10)
        dr.rectangle([x0, y + 22, x0 + W, y + ph - 10], outline=(40, 44, 48))
        for r, (d, life, size, start, sa, g, go) in enumerate(rows_):
            yy = y + 26 + r * ROWH
            th = int(np.clip(3 + 4 * np.log2(1 + size * 2), 2, ROWH - 2))
            n = 120
            for i in range(n):
                u = (i + 0.5) / n
                t = d + u * life
                if t > T_MAX:
                    break
                al = (interp(get_alpha(g), u) if g else 1.0) * sa
                col = np.clip(start * (interp_col(get_colors(g), u) if g else 1.0), 0, 1)
                c = tuple(int(255 * x * al + 14 * (1 - al)) for x in col)
                xa = x0 + int(W * (d + (i / n) * life) / T_MAX); xb = x0 + int(W * (d + ((i + 1) / n) * life) / T_MAX)
                dr.rectangle([xa, yy + (ROWH - th) // 2, max(xa, xb), yy + (ROWH - th) // 2 + th], fill=c)
    y += ph
img.save(os.path.join(out_dir, '3_timeline_efek.png'))
print('ok')
