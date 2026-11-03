"""v3 preview sheets: model detail, sharper FX textures, smoother animation, S-curve fades.
usage: make_previews_v3.py <orig HIDAN> <v2 HIDAN> <v3 HIDAN> <out dir>"""
import sys, os, math
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import numpy as np, UnityPy
from PIL import Image, ImageDraw, ImageFont
import matplotlib; matplotlib.use('Agg')
import matplotlib.pyplot as plt
from fk import Rig
import toon_preview as tp
from jerk_metrics import metrics
from vfx_fix import get_alpha, interp
orig, v2, v3, out = sys.argv[1:5]
os.makedirs(out, exist_ok=True)
try:
    FONT = ImageFont.truetype('/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf', 19)
    SMALL = ImageFont.truetype('/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf', 13)
except Exception:
    FONT = SMALL = ImageFont.load_default()
MB = 'Art/Android/h/hero_argus_skin.unity3d'; MBH = 'Art/Android/h/hero_argus_skin_high_add.unity3d'
MAT = dict(ToonDir=(0, 1, 0), T1=0.12, T2=0.45, V1=0.66, V2=0.86, V3=1.0)

def tex_of(path):
    env = UnityPy.load(path)
    for o in env.objects:
        if o.type.name == 'Texture2D':
            return np.asarray(o.read().image.convert('RGB'), np.float32) / 255.0

def wire(P, T, pitch, yaw, size, extent, center):
    cy, sy = math.cos(yaw), math.sin(yaw); Ry = np.array([[cy, 0, -sy], [0, 1, 0], [sy, 0, cy]])
    cp, s_ = math.cos(pitch), math.sin(pitch); Rx = np.array([[1, 0, 0], [0, cp, s_], [0, -s_, cp]])
    Pc = (P - np.array(center)) @ (Rx @ Ry).T
    sc = size / (2 * extent); X = Pc[:, 0] * sc + size / 2; Y = -Pc[:, 1] * sc + size / 2
    im = Image.new('RGB', (size, size), (18, 18, 22)); d = ImageDraw.Draw(im)
    for t in T:
        pts = [(X[i], Y[i]) for i in t]; d.line(pts + [pts[0]], fill=(205, 55, 60), width=1)
    return np.asarray(im)

# ---------------- 5: model detail
rows = []
for tag, path in (('v2', os.path.join(v2, MB)), ('v3 Normal (1024)', os.path.join(v3, MB)), ('v3 High (2048)', os.path.join(v3, MBH))):
    rig = Rig(path); tex = tex_of(path)
    P, N, UV, T = tp.posed(rig, 'fight_idle', 1.0)
    tiles = [tp.render(P, N, UV, T, tex, MAT, size=330, pitch=math.radians(50), yaw=math.radians(200), extent=1.05),
             tp.render(P, N, UV, T, tex, MAT, size=330, pitch=math.radians(5), yaw=math.radians(195), extent=0.26, center=(0, 1.56, 0.02)),
             tp.render(P, N, UV, T, tex, MAT, size=330, pitch=math.radians(12), yaw=math.radians(165), extent=0.42, center=(0.02, 1.25, 0.0)),
             wire(P, T, math.radians(5), math.radians(195), 330, 0.26, (0, 1.56, 0.02))]
    row = Image.fromarray(np.concatenate(tiles, 1)); d = ImageDraw.Draw(row)
    d.rectangle([0, 0, row.width, 26], fill=(15, 15, 18)); d.text((8, 3), tag, fill=(255, 220, 220), font=FONT)
    rows.append(np.asarray(row))
Image.fromarray(np.concatenate(rows, 0)).save(os.path.join(out, '5_model_v3_lebih_detail.png'))
print('5 done')

# ---------------- 6: FX textures before/after (zoomed crops)
pairs = [('111/45_argus_Attack_01.unity3d', 'Blade_SD_58_Skin06_LX_003', (60, 120, 316, 376)),
         ('111/45_argus_Hit_05.unity3d', 'Special_SD_wmd_0623', (20, 20, 236, 236)),
         ('111/45_argus_Hit_05.unity3d', 'jasinWhite', (0, 0, 256, 256)),
         ('111/45_argus_Attack_01.unity3d', '07_09', (0, 0, 128, 128))]
tiles = []
for rel, name, box in pairs:
    imgs = []
    for root in (orig, v3):
        env = UnityPy.load(os.path.join(root, 'Art/Android', rel))
        t = [o.read() for o in env.objects if o.type.name == 'Texture2D' and o.read().m_Name == name][0]
        im = t.image.convert('RGBA').crop(box)
        bg = Image.new('RGBA', im.size, (26, 26, 32, 255))
        imgs.append(Image.alpha_composite(bg, im).convert('RGB').resize((300, 300), Image.NEAREST))
    tile = Image.new('RGB', (610, 330), (0, 0, 0)); tile.paste(imgs[0], (0, 28)); tile.paste(imgs[1], (310, 28))
    d = ImageDraw.Draw(tile); d.text((4, 4), f'{name}   sebelum | sesudah', fill=(255, 230, 120), font=SMALL)
    tiles.append(tile)
sheet = Image.new('RGB', (1220, 660), (0, 0, 0))
for i, t in enumerate(tiles): sheet.paste(t, ((i % 2) * 610, (i // 2) * 330))
sheet.save(os.path.join(out, '6_vfx_tekstur_tajam.png'))
print('6 done')

# ---------------- 7: animation smoothness
mo, m2, m3 = metrics(os.path.join(orig, MB)), metrics(os.path.join(v2, MB)), metrics(os.path.join(v3, MB))
clips = [c for c in ['attack1', 'attack2', 'attack3', 'attack4', 'skill1_1', 'skill1_2', 'skill1_3', 'skill2', 'skill3', 'skill4_2', 'run', 'landing'] if c in mo]
x = np.arange(len(clips))
fig, ax = plt.subplots(figsize=(14, 4.8))
ax.bar(x - 0.27, [mo[c][1] for c in clips], 0.27, label='Asli', color='#8a8f98')
ax.bar(x, [m2[c][1] for c in clips], 0.27, label='v2', color='#e07a7a')
ax.bar(x + 0.27, [m3[c][1] for c in clips], 0.27, label='v3', color='#b0101f')
ax.set_xticks(x); ax.set_xticklabels(clips, rotation=20)
ax.set_ylabel('sentakan (percentil-99, derajat/frame²)')
ax.set_title('Animasi makin halus: perubahan kecepatan mendadak per klip (lebih rendah = lebih halus)')
ax.legend(); plt.tight_layout(); plt.savefig(os.path.join(out, '7_animasi_lebih_halus.png'), dpi=90); plt.close()
print('7 done')

# ---------------- 8: S-curve fades
def ps(root, rel, name):
    env = UnityPy.load(os.path.join(root, 'Art/Android', rel)); objs = {o.path_id: o for o in env.objects}
    for o in env.objects:
        if o.type.name == 'ParticleSystem':
            tt = o.read_typetree()
            if objs[tt['m_GameObject']['m_PathID']].read_typetree()['m_Name'] == name: return tt
t = np.linspace(0, 1, 300)
fig, ax = plt.subplots(figsize=(9, 4.2))
for tag, root, style in (('Asli', orig, ':'), ('v2 (ramp linear)', v2, '--'), ('v3 (S-curve)', v3, '-')):
    g = ps(root, '111/45_argus_Attack_01.unity3d', 'HIDAN_splash_s_5')['ColorModule']['gradient']['maxGradient']
    ax.plot(t, [interp(get_alpha(g), u) for u in t], style, lw=2, label=tag)
ax.set_xlabel('umur partikel'); ax.set_ylabel('alpha'); ax.set_ylim(0, 1.05)
ax.set_title('Fade partikel: muncul & hilang dengan kurva S yang halus'); ax.legend()
plt.tight_layout(); plt.savefig(os.path.join(out, '8_fade_s_curve.png'), dpi=90); plt.close()
print('8 done')
