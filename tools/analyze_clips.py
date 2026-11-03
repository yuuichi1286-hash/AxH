import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import numpy as np, UnityPy
from clipio import *
p = sys.argv[1]
env = UnityPy.load(p)
objs = list(env.objects)
anim = [o for o in objs if o.type.name == 'Animator'][0].read_typetree()
go = [o for o in objs if o.path_id == anim['m_GameObject']['m_PathID']][0].read_typetree()
tfpid = [c['component']['m_PathID'] for c in go['m_Component'] if [o for o in objs if o.path_id == c['component']['m_PathID']][0].type.name == 'Transform'][0]
paths = transform_paths(objs, tfpid)
only = sys.argv[2] if len(sys.argv) > 2 else None
for o in objs:
    if o.type.name != 'AnimationClip': continue
    tt = o.read_typetree()
    if only and tt['m_Name'] != only: continue
    dec = decode_clip(tt)
    lay, ntot = binding_layout(tt)
    fps = 60.0
    times = np.arange(dec['start'], dec['stop'] + 1e-6, 1.0 / fps)
    M = sample_clip(dec, times)
    # Choppiness metrics on rotation curves: fraction of frames with zero motion followed by big jumps
    worst = []
    unknown = 0
    for (ph, attr, n, c0, tid) in lay:
        name = paths.get(ph)
        if name is None: unknown += 1
        if tid != 4 or attr != 2: continue
        q = M[:, c0:c0 + 4]
        # angular speed per frame (deg)
        dots = np.abs(np.sum(q[1:] * q[:-1], 1) / (np.linalg.norm(q[1:], axis=1) * np.linalg.norm(q[:-1], axis=1) + 1e-12))
        ang = np.degrees(2 * np.arccos(np.clip(dots, -1, 1)))
        if len(ang) < 3: continue
        still = ang < 0.05
        jumps = ang > 4.0
        accel = np.abs(np.diff(ang))
        worst.append((accel.max() if len(accel) else 0, ang.max(), still.mean(), jumps.sum(), (name or hex(ph)).split('/')[-1]))
    worst.sort(reverse=True)
    print(f"== {tt['m_Name']} dur={dec['stop']-dec['start']:.2f}s streamed={dec['ns']} dense={dec['nd']}@{dec['dense_rate']} const={dec['nc']} bindings={len(lay)} curves={ntot} unknownPaths={unknown}")
    for w in worst[:6]:
        print(f"    max dAng/frame={w[1]:6.2f}deg  maxAccel={w[0]:6.2f}  still%={w[2]*100:5.1f}  bigJumps={w[3]:3d}  {w[4]}")
