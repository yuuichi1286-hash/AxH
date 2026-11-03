"""Fade timelines: every particle system of an effect as a strip (brightness x colour of one representative
particle over the effect's time line), before vs after; dashed line = the effect is recycled (DelayTime)."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import numpy as np, UnityPy
import matplotlib; matplotlib.use('Agg')
import matplotlib.pyplot as plt
from vfx_fix import get_alpha, get_colors, interp, interp_col, mm_max
from cinematic import eval_curve

def systems(path):
    env = UnityPy.load(path); objs = {o.path_id: o for o in env.objects}
    delay = None; rows = []
    for o in env.objects:
        if o.type.name == 'MonoBehaviour':
            try:
                tt = o.read_typetree()
                if 'DelayTime' in tt: delay = tt['DelayTime']
            except Exception: pass
    for o in env.objects:
        if o.type.name != 'ParticleSystem': continue
        tt = o.read_typetree(); go = objs[tt['m_GameObject']['m_PathID']].read_typetree()
        if not go['m_IsActive']: continue
        sd = tt['startDelay']; d0 = mm_max(sd) if isinstance(sd, dict) else float(sd)
        em = tt['EmissionModule']
        first = min([b['time'] for b in em['m_Bursts']] or [0.0])
        life = mm_max(tt['InitialModule']['startLifetime'])
        sc = tt['InitialModule']['startColor']
        cols = [sc['maxColor']] + ([sc['minColor']] if sc['minMaxState'] == 2 else [])
        start = np.mean([[c['r'], c['g'], c['b']] for c in cols], 0) if sc['minMaxState'] in (0, 2) else np.ones(3)
        g = tt['ColorModule']['gradient']['maxGradient']
        sm = tt['SizeModule']
        size = (lambda u, k=sm['curve']['maxCurve']['m_Curve']: eval_curve(k, u)) if sm['enabled'] and sm['curve']['minMaxState'] == 1 else (lambda u: 1.0)
        rows.append((d0 + first, go['m_Name'], life, start, get_alpha(g), get_colors(g), size))
    rows.sort(key=lambda r: (r[0], r[1]))
    return delay, rows

def strip(ax, delay, rows, T, title):
    W = 400
    img = np.ones((len(rows), W, 3)) * 0.1
    ts = np.linspace(0, T, W)
    for i, (b, name, life, start, ak, ck, size) in enumerate(rows):
        for j, t in enumerate(ts):
            u = (t - b) / max(life, 1e-3)
            if 0 <= u <= 1:
                a = interp(ak, u) * min(1.0, 0.35 + 0.65 * size(u) / max(size(0.5), 1e-3))
                img[i, j] = np.clip(start * interp_col(ck, u), 0, 1) * a + 0.1 * (1 - a)
    ax.imshow(img, aspect='auto', extent=[0, T, len(rows), 0], interpolation='nearest')
    ax.set_yticks(np.arange(len(rows)) + 0.5); ax.set_yticklabels([r[1][:26] for r in rows], fontsize=7)
    if delay and delay < 100: ax.axvline(delay, color='w', ls='--', lw=1)
    ax.set_title(title, fontsize=10); ax.set_xlabel('detik')

def sheet(pairs, out, T):
    fig, axes = plt.subplots(len(pairs), 2, figsize=(15, 3.6 * len(pairs)))
    axes = np.atleast_2d(axes)
    for i, (label, before, after) in enumerate(pairs):
        for j, (tag, path) in enumerate((('sebelum (v3)', before), ('sesudah (v4)', after))):
            d, rows = systems(path)
            strip(axes[i, j], d, rows, T, f'{label} - {tag}  (garis putus = efek dihapus, DelayTime {d:.2f}s)')
    plt.tight_layout(); plt.savefig(out, dpi=80); plt.close()

v3, v4, outdir = sys.argv[1:4]
A = 'Art/Android/'
sheet([('Basic attack 1', os.path.join(v3, A, '111/45_argus_Attack_01.unity3d'), os.path.join(v4, A, '111/45_argus_Attack_01.unity3d')),
       ('Hit basic attack', os.path.join(v3, A, '111/45_argus_Hit_01.unity3d'), os.path.join(v4, A, '111/45_argus_Hit_01.unity3d'))],
      os.path.join(outdir, '9_basic_attack_fade_timeline.png'), 1.25)
sheet([('Serangan pasif (Attack_04_1)', os.path.join(v3, A, '111/45_argus_Attack_04_1.unity3d'), os.path.join(v4, A, '111/45_argus_Attack_04_1.unity3d')),
       ('Hit pasif (Hit_05)', os.path.join(v3, A, '111/45_argus_Hit_05.unity3d'), os.path.join(v4, A, '111/45_argus_Hit_05.unity3d')),
       ('Pasif selesai (xiaosan)', os.path.join(v3, A, '111/45_argus_Keep_daoguang_xiaosan.unity3d'), os.path.join(v4, A, '111/45_argus_Keep_daoguang_xiaosan.unity3d'))],
      os.path.join(outdir, '10_pasif_fade_timeline.png'), 2.4)
print('done')
