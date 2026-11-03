import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import numpy as np, UnityPy
import matplotlib; matplotlib.use('Agg')
import matplotlib.pyplot as plt
from clipio import *
p, clipname, bones, out = sys.argv[1], sys.argv[2], sys.argv[3].split(','), sys.argv[4]
env = UnityPy.load(p); objs = list(env.objects)
anim = [o for o in objs if o.type.name == 'Animator'][0].read_typetree()
go = [o for o in objs if o.path_id == anim['m_GameObject']['m_PathID']][0].read_typetree()
tfpid = [c['component']['m_PathID'] for c in go['m_Component'] if [o for o in objs if o.path_id == c['component']['m_PathID']][0].type.name == 'Transform'][0]
paths = transform_paths(objs, tfpid)
for o in objs:
    if o.type.name != 'AnimationClip': continue
    tt = o.read_typetree()
    if tt['m_Name'] != clipname: continue
    dec = decode_clip(tt); lay, ntot = binding_layout(tt)
    times = np.arange(dec['start'], dec['stop'] + 1e-6, 1 / 240.0)
    M = sample_clip(dec, times)
    fig, axes = plt.subplots(len(bones), 1, figsize=(14, 3 * len(bones)))
    if len(bones) == 1: axes = [axes]
    for ax, b in zip(axes, bones):
        for (ph, attr, n, c0, tid) in lay:
            nm = paths.get(ph, '?').split('/')[-1]
            if nm == b and attr == 2:
                q = M[:, c0:c0 + 4]
                for k, lab in enumerate('xyzw'):
                    ax.plot(times, q[:, k], label=lab, lw=1)
                # mark streamed key times / dense frames
                kind = 'streamed' if c0 < dec['ns'] else ('dense' if c0 < dec['ns'] + dec['nd'] else 'const')
                if kind == 'streamed':
                    per = streamed_keys_per_curve(dec['frames'], dec['ns'])
                    kt = [k[0] for k in per[c0] if np.isfinite(k[0]) and abs(k[0]) < 1e20]
                    for t in kt: ax.axvline(t, color='gray', lw=0.3)
                ax.set_title(f'{clipname} {b} rotation ({kind})'); ax.legend(loc='right')
    plt.tight_layout(); plt.savefig(out, dpi=70)
