"""Before/after preview sheets (model look, attack smoothing, recall, VFX budget/fades)."""
import sys, os, math
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import numpy as np, UnityPy
from PIL import Image, ImageDraw, ImageFont
from fk import Rig, clip_overrides
import toon_preview as tp
import filmstrip as fsm

orig_root, new_root, out = sys.argv[1], sys.argv[2], sys.argv[3]
os.makedirs(out, exist_ok=True)
MB = 'Art/Android/h/hero_argus_skin.unity3d'
MAT_OLD = dict(ToonDir=(0, 1, 0), T1=0.45, T2=0.0, V1=0.5, V2=0.6, V3=1.0)
MAT_NEW = dict(ToonDir=(0, 1, 0), T1=0.12, T2=0.45, V1=0.66, V2=0.86, V3=1.0)
try:
    FONT = ImageFont.truetype('/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf', 20)
    SMALL = ImageFont.truetype('/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf', 14)
except Exception:
    FONT = SMALL = ImageFont.load_default()

def tex_of(path):
    env = UnityPy.load(path)
    for o in env.objects:
        if o.type.name == 'Texture2D' and o.read().m_Name == '777daa':
            return np.asarray(o.read().image.convert('RGB'), np.float32) / 255.0

def label(img, text, sub=None):
    im = Image.fromarray(img) if isinstance(img, np.ndarray) else img
    d = ImageDraw.Draw(im)
    d.rectangle([0, 0, im.width, 30], fill=(15, 15, 18))
    d.text((8, 4), text, fill=(255, 220, 220), font=FONT)
    if sub:
        d.text((8, im.height - 22), sub, fill=(230, 230, 230), font=SMALL)
    return im

# ---------------- 1. model look
rig_o, rig_n = Rig(os.path.join(orig_root, MB)), Rig(os.path.join(new_root, MB))
to, tn = tex_of(os.path.join(orig_root, MB)), tex_of(os.path.join(new_root, MB))
cams = [('fight_idle', 1.0, dict(pitch=math.radians(50), yaw=math.radians(200), extent=1.05)),
        ('skill3', 1.3, dict(pitch=math.radians(50), yaw=math.radians(200), extent=1.05)),
        ('fight_idle', 1.0, dict(pitch=math.radians(5), yaw=math.radians(195), extent=0.30, center=(0, 1.52, 0.02)))]
rows = []
for tag, rig, tex, mat in (('SEBELUM', rig_o, to, MAT_OLD), ('SESUDAH', rig_n, tn, MAT_NEW)):
    tiles = []
    for clip, t, cam in cams:
        P, N, UV, T = tp.posed(rig, clip, t)
        tiles.append(np.asarray(tp.render(P, N, UV, T, tex, mat, size=380, **cam)))
    rows.append(np.asarray(label(np.concatenate(tiles, 1), tag)))
Image.fromarray(np.concatenate(rows, 0)).save(os.path.join(out, '1_model_sebelum_sesudah.png'))
print('model preview done')

# ---------------- 2. attack4 spin smoothing
def strip(path, clip, times, extent=1.6, size=200):
    rig = Rig(path)
    tt = [o for o in rig.env.objects if o.type.name == 'AnimationClip' and o.read_typetree()['m_Name'] == clip][0].read_typetree()
    ovs, acts = clip_overrides(rig, tt, times)
    tex = tex_of(path)
    tiles = []
    for t, ov, act in zip(times, ovs, acts):
        W = rig.pose(ov)
        Vs, Ts, Fs, off = [], [], [], 0
        for smr in rig.smrs:
            if not act.get(smr['go']['m_Name'], smr['go']['m_IsActive']):
                continue
            V = rig.skin(smr, W); d = smr['d']; tri = d['index'].reshape(-1, 3)
            Vs.append(V); Ts.append(d['uv0'].astype(np.float64)); Fs += [[(a + off, a + off), (b + off, b + off), (c + off, c + off)] for a, b, c in tri]; off += len(V)
        im = Image.fromarray(fsm.render_world(np.vstack(Vs), np.vstack(Ts), Fs, tex, size, extent=extent))
        ImageDraw.Draw(im).text((4, size - 18), f't={t:.3f}s', fill=(255, 255, 0), font=SMALL)
        tiles.append(np.asarray(im))
    return np.concatenate(tiles, 1)
times = list(np.linspace(0.33, 0.48, 7))
a = label(strip(os.path.join(orig_root, MB), 'attack4', times), 'SEBELUM  attack4: badan berputar ~180 derajat dalam 1-2 frame (loncat)')
b = label(strip(os.path.join(new_root, MB), 'attack4', times), 'SESUDAH  putaran disebar jadi sapuan halus (ease in/out)')
Image.fromarray(np.concatenate([np.asarray(a), np.asarray(b)], 0)).save(os.path.join(out, '2_attack_snap_dihaluskan.png'))
print('attack preview done')

# ---------------- 3. recall loop seam
ot = [2.85, 2.95, 3.04]
o_strip = strip(os.path.join(orig_root, MB), 'recall', ot + [0.0, 0.1], extent=1.4)
n_strip = strip(os.path.join(new_root, MB), 'recall', [2.85, 2.95, 3.04, 3.15, 3.25], extent=1.4)
a = label(o_strip, 'SEBELUM  recall looping 3.05 dtk: pose akhir -> LONCAT ke pose awal')
b = label(n_strip, 'SESUDAH  recall 6.5 dtk tanpa loop: kuda-kuda + napas halus, tanpa loncat')
Image.fromarray(np.concatenate([np.asarray(a), np.asarray(b)], 0)).save(os.path.join(out, '3_recall_tanpa_loncat.png'))
print('recall preview done')
