"""Per clip: max / 99th percentile angular acceleration (deg per frame^2 @60 fps) over all animated bones."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import numpy as np, UnityPy
from clipio import decode_clip, binding_layout, sample_clip
from anim_fix import continuity, ang_accel
def metrics(path):
    env = UnityPy.load(path); out = {}
    for o in env.objects:
        if o.type.name != 'AnimationClip': continue
        tt = o.read_typetree()
        if tt['m_Legacy']: continue
        dec = decode_clip(tt); lay, n = binding_layout(tt)
        t = np.arange(dec['start'], dec['stop'] + 1e-6, 1 / 60.0)
        M = sample_clip(dec, t)
        accs = []
        for (ph, attr, nc, c0, tid) in lay:
            if tid == 4 and attr == 2:
                q = continuity(M[:, c0:c0 + 4])
                if np.ptp(q, axis=0).max() < 1e-6: continue
                accs.append(ang_accel(q, 60.0) / 3600.0)
        a = np.concatenate(accs) if accs else np.zeros(1)
        out[tt['m_Name']] = (a.max(), np.percentile(a, 99), a.mean())
    return out
if __name__ == '__main__':
    A, B = metrics(sys.argv[1]), metrics(sys.argv[2])
    print(f"{'clip':12s} {'max A':>8s} {'max B':>8s} {'p99 A':>8s} {'p99 B':>8s} {'mean A':>7s} {'mean B':>7s}")
    for k in A:
        print(f'{k:12s} {A[k][0]:8.1f} {B[k][0]:8.1f} {A[k][1]:8.2f} {B[k][1]:8.2f} {A[k][2]:7.3f} {B[k][2]:7.3f}')
