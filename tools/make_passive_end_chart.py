import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import numpy as np, UnityPy
import matplotlib; matplotlib.use('Agg')
import matplotlib.pyplot as plt
from cinematic import eval_curve
from vfx_fix import get_alpha, get_colors, interp, interp_col
v3, v4, out = sys.argv[1:4]
A = 'Art/Android/111/'
def mesh_curves(root):
    env = UnityPy.load(os.path.join(root, A, '45_argus_Keep_daoguang_xiaosan_skin03_add.unity3d'))
    for o in env.objects:
        if o.type.name == 'AnimationClip':
            tt = o.read_typetree(); c = {}
            for fc in tt['m_FloatCurves']:
                if fc['path'].endswith('dao02') and fc['attribute'].startswith('material._Color.'):
                    c[fc['attribute'][-1]] = fc['curve']['m_Curve']
                if fc['path'].endswith('dao01') and fc['attribute'] == 'material._Color.a':
                    c['inner_a'] = fc['curve']['m_Curve']
            return c
def glow(root):
    env = UnityPy.load(os.path.join(root, A, '45_argus_Keep_daoguang_xiaosan.unity3d'))
    for o in env.objects:
        if o.type.name == 'ParticleSystem':
            tt = o.read_typetree(); g = tt['ColorModule']['gradient']['maxGradient']
            sc = tt['InitialModule']['startColor']['maxColor']
            life = tt['InitialModule']['startLifetime']['scalar']
            return life, np.array([sc['r'], sc['g'], sc['b']]), get_alpha(g), get_colors(g), tt['SizeModule']['curve']['maxCurve']['m_Curve']
fig, axes = plt.subplots(1, 2, figsize=(15, 4.6))
t = np.linspace(0, 0.75, 300)
for tag, root, ls in (('sebelum', v3, '--'), ('sesudah', v4, '-')):
    c = mesh_curves(root)
    rgb = np.array([[eval_curve(c[ch], x) for ch in 'rgb'] for x in t])
    a = np.array([eval_curve(c['a'], x) for x in t])
    axes[0].plot(t, a, ls, color='k', label=f'alpha glow pedang ({tag})')
    axes[0].plot(t, [eval_curve(c['inner_a'], x) for x in t], ls, color='gray', label=f'alpha inti gelap ({tag})')
    if tag == 'sesudah':
        for i in range(len(t) - 1):
            axes[0].axvspan(t[i], t[i + 1], ymin=0, ymax=0.08, color=np.clip(rgb[i], 0, 1), lw=0)
axes[0].set_title('Pasif selesai (mesh glow pedang): kilatan merah-putih lalu padam halus'); axes[0].set_xlabel('detik'); axes[0].legend(fontsize=8); axes[0].set_ylim(0, 1.1)
for tag, root, ls in (('sebelum', v3, '--'), ('sesudah', v4, '-')):
    life, start, ak, ck, sk = glow(root)
    u = np.linspace(0, 1, 200); tt = u * life
    axes[1].plot(tt, [eval_curve(sk, x) for x in u], ls, color='#b0101f', label=f'ukuran bloom ({tag})')
    axes[1].plot(tt, [interp(ak, x) for x in u], ls, color='k', label=f'alpha ({tag})')
    if tag == 'sesudah':
        cols = np.array([np.clip(start * interp_col(ck, x), 0, 1) for x in u])
        for i in range(len(u) - 1):
            axes[1].axvspan(tt[i], tt[i + 1], ymin=0, ymax=0.06, color=cols[i], lw=0)
axes[1].set_title('Glow dissipate: kilatan panas, mekar 35% lebih lebar, larut ke merah darah'); axes[1].set_xlabel('detik sejak partikel muncul'); axes[1].legend(fontsize=8)
plt.tight_layout(); plt.savefig(out, dpi=85)
