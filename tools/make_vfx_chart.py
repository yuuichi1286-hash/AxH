import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import numpy as np, UnityPy
import matplotlib; matplotlib.use('Agg')
import matplotlib.pyplot as plt
from vfx_fix import mm_max, burst_alive, get_alpha, get_colors, interp, interp_col
orig_root, new_root, out = sys.argv[1:4]
def budget(path):
    env = UnityPy.load(path); tot = 0
    for o in env.objects:
        if o.type.name == 'ParticleSystem':
            tt = o.read_typetree(); im, em = tt['InitialModule'], tt['EmissionModule']
            life = max(mm_max(im['startLifetime']), 0.02)
            if em['enabled']:
                tot += min(im['maxNumParticles'], mm_max(em['rateOverTime']) * life + sum(burst_alive(b, life) for b in em['m_Bursts']))
    return tot
items = [('Basic attack', '111/45_argus_Attack_01'), ('Hit', '111/45_argus_Hit_01'), ('Skill 1', '111/45_argus_skill01_Fire_01'),
         ('Skill 2', '111/45_argus_skill02_Fire_01'), ('Ult cast', '111/45_argus_skill03_Fire_01'), ('Ult cast 2', '111/45_argus_skill03_Fire_02'),
         ('Ult ground', '111/45_argus_skill3_dilie'), ('Ult aura', '111/45_argus_skill03_Keep_01_skin01_add')]
b0 = [budget(os.path.join(orig_root, 'Art/Android', p + '.unity3d')) for _, p in items]
b1 = [budget(os.path.join(new_root, 'Art/Android', p + '.unity3d')) for _, p in items]
fig, axes = plt.subplots(1, 2, figsize=(15, 5.2))
x = np.arange(len(items))
ax = axes[0]
ax.bar(x - 0.2, b0, 0.4, label='Sebelum', color='#8a8f98')
ax.bar(x + 0.2, b1, 0.4, label='Sesudah', color='#c0152a')
ax.set_xticks(x); ax.set_xticklabels([n for n, _ in items], rotation=25, ha='right')
ax.set_ylabel('perkiraan partikel hidup bersamaan'); ax.set_title('Optimasi: jumlah partikel per efek'); ax.legend()
for i, (a, b) in enumerate(zip(b0, b1)):
    ax.text(i + 0.2, b + 8, f'-{100 * (1 - b / a):.0f}%' if a > 0 and b < a else '', ha='center', fontsize=9, color='#c0152a')
# fade envelope example
def ps(path, name):
    env = UnityPy.load(path); objs = {o.path_id: o for o in env.objects}
    for o in env.objects:
        if o.type.name == 'ParticleSystem':
            tt = o.read_typetree()
            if objs[tt['m_GameObject']['m_PathID']].read_typetree()['m_Name'] == name: return tt
p = 'Art/Android/111/45_argus_Attack_01.unity3d'
ax = axes[1]
t = np.linspace(0, 1, 200)
for tag, root, ls in (('Sebelum', orig_root, '--'), ('Sesudah', new_root, '-')):
    tt = ps(os.path.join(root, p), 'HIDAN_spark_s_3')
    g = tt['ColorModule']['gradient']['maxGradient']
    sc = tt['InitialModule']['startColor']
    cols = [sc['maxColor']] + ([sc['minColor']] if sc['minMaxState'] == 2 else [])
    start = np.mean([[c['r'], c['g'], c['b']] for c in cols], 0)
    al = [interp(get_alpha(g), u) for u in t]
    ax.plot(t, al, ls, color='k', label=f'alpha ({tag})')
    if tag == 'Sesudah':
        rgb = np.array([np.clip(start * interp_col(get_colors(g), u), 0, 1) for u in t])
        for i in range(len(t) - 1):
            ax.axvspan(t[i], t[i + 1], ymin=0, ymax=0.06, color=rgb[i], lw=0)
ax.set_xlabel('umur partikel (0 = lahir, 1 = hilang)'); ax.set_ylim(0, 1.08)
ax.set_title('Contoh percikan darah: fade-in + fade-out, kepala panas -> merah darah')
ax.legend(loc='center right')
plt.tight_layout(); plt.savefig(os.path.join(out, '4_vfx_optimasi_dan_fade.png'), dpi=90)
print(list(zip([n for n, _ in items], b0, b1)))
