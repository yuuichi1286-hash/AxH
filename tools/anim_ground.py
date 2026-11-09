"""Feet never sink deeper into the ground than in the original animations (fix of a v3 smoothing side effect).

The v3 smoothing (anim_fix) changed leg poses slightly, and in a few clips the planted foot ended up far below the
ground: attack4 / attack5 24 cm, skill2 16 cm, skill4_2 15 cm (the original clips: 6-9 cm). Per 60 fps frame the
lowest vertex of each foot is compared with the original clip at the same time (and with the sole of the bind
pose). A foot that is deeper is lifted by two-bone IK on its leg: the hip stays, the knee bends in its own plane,
the foot keeps its world orientation. The lift follows a smooth envelope over time (no new jitter); only the leg
rotation curves of the affected frames change.

usage: python anim_ground.py <original HIDAN dir> <HIDAN dir, modified in place> [report.json]
"""
import sys, os, json
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import numpy as np
import UnityPy
from fk import Rig
from clipio import decode_clip, binding_layout, sample_clip

BUNDLES = ('hero_argus_skin.unity3d', 'hero_argus_skin_high_add.unity3d')
TOL = 0.005          # 5 mm below the allowed depth is fine
SIDES = ('L', 'R')


def mat2quat(m):
    tr = m[0, 0] + m[1, 1] + m[2, 2]
    if tr > 0:
        s = np.sqrt(tr + 1.0) * 2
        q = [(m[2, 1] - m[1, 2]) / s, (m[0, 2] - m[2, 0]) / s, (m[1, 0] - m[0, 1]) / s, 0.25 * s]
    elif m[0, 0] > m[1, 1] and m[0, 0] > m[2, 2]:
        s = np.sqrt(1.0 + m[0, 0] - m[1, 1] - m[2, 2]) * 2
        q = [0.25 * s, (m[0, 1] + m[1, 0]) / s, (m[0, 2] + m[2, 0]) / s, (m[2, 1] - m[1, 2]) / s]
    elif m[1, 1] > m[2, 2]:
        s = np.sqrt(1.0 + m[1, 1] - m[0, 0] - m[2, 2]) * 2
        q = [(m[0, 1] + m[1, 0]) / s, 0.25 * s, (m[1, 2] + m[2, 1]) / s, (m[0, 2] - m[2, 0]) / s]
    else:
        s = np.sqrt(1.0 + m[2, 2] - m[0, 0] - m[1, 1]) * 2
        q = [(m[0, 2] + m[2, 0]) / s, (m[1, 2] + m[2, 1]) / s, 0.25 * s, (m[1, 0] - m[0, 1]) / s]
    q = np.array(q)
    return q / np.linalg.norm(q)


def rot_between(u, v):
    u = u / np.linalg.norm(u)
    v = v / np.linalg.norm(v)
    ax = np.cross(u, v)
    s = np.linalg.norm(ax)
    if s < 1e-12:
        return np.eye(3)
    ax /= s
    K = np.array([[0, -ax[2], ax[1]], [ax[2], 0, -ax[0]], [-ax[1], ax[0], 0]])
    ang = np.arctan2(s, np.dot(u, v))
    return np.eye(3) + np.sin(ang) * K + (1 - np.cos(ang)) * K @ K


def rot(M):
    R = M[:3, :3]
    return R / np.linalg.norm(R, axis=0, keepdims=True)


def overrides(rig, lay, row):
    ov = {}
    for ph, attr, nc, c0, tid in lay:
        pid = rig.hash_to_pid.get(ph)
        key = {1: 't', 2: 'q', 3: 's'}.get(attr)
        if pid is not None and tid == 4 and key:
            ov.setdefault(pid, {})[key] = list(row[c0:c0 + nc])
    return ov


def envelope(need, r=4):
    """smooth curve >= need: dilate, then Hann-smooth, then never below need"""
    n = len(need)
    d = np.array([need[max(0, i - r):i + r + 1].max() for i in range(n)])
    k = np.hanning(2 * r + 3)[1:-1]
    k /= k.sum()
    sm = np.convolve(np.pad(d, r, mode='edge'), k, mode='valid')
    return np.maximum(sm, need)


class Feet:
    def __init__(self, rig):
        self.rig = rig
        self.smr = [s for s in rig.smrs if s['name'] == 'noraml'][0]
        names = [rig.goname[b] for b in self.smr['bones']]
        d = self.smr['d']
        dom = d['indices'][np.arange(len(d['pos'])), d['weights'].argmax(1)]
        self.mask = {S: dom == names.index(f'{S}_Foot') for S in SIDES}
        self.pid = {n: p for p, n in rig.goname.items()}

    def lowest(self, W):
        P = self.rig.skin(self.smr, W)
        return {S: P[self.mask[S]][:, 1].min() for S in SIDES}


def ik_leg(rig, pid, W, S, lift):
    """local rotations (thigh, shin, foot) that raise the ankle by `lift` (world up), foot orientation kept"""
    th, sh, ft = pid[f'{S}_UpLeg'], pid[f'{S}_Leg'], pid[f'{S}_Foot']
    H, K, A = W[th][:3, 3], W[sh][:3, 3], W[ft][:3, 3]
    l1, l2 = np.linalg.norm(K - H), np.linalg.norm(A - K)
    A2 = A + np.array([0.0, lift, 0.0])
    d = min(np.linalg.norm(A2 - H), (l1 + l2) * 0.999)
    u = (A2 - H) / np.linalg.norm(A2 - H)
    A2 = H + u * d
    u0 = (A - H) / np.linalg.norm(A - H)
    p = (K - H) - ((K - H) @ u0) * u0
    p = p - (p @ u) * u
    p /= np.linalg.norm(p)
    ca = np.clip((l1 * l1 + d * d - l2 * l2) / (2 * l1 * d), -1, 1)
    K2 = H + l1 * (ca * u + np.sqrt(1 - ca * ca) * p)
    Rt, Rs, Rf = rot(W[th]), rot(W[sh]), rot(W[ft])
    D1 = rot_between(K - H, K2 - H)
    Rt2 = D1 @ Rt
    D2 = rot_between(D1 @ (A - K), A2 - K2)
    Rs2 = D2 @ D1 @ Rs
    Rp = rot(W[rig.parent[th]])
    return {th: Rp.T @ Rt2, sh: Rt2.T @ Rs2, ft: Rs2.T @ Rf}


def fix_clip(tt, rig, feet, orig_rig, orig_feet, orig_clip, sole):
    mc = tt['m_MuscleClip']
    dc = mc['m_Clip']['data']['m_DenseClip']
    if not dc['m_CurveCount']:
        return None
    dec = decode_clip(tt)
    lay, _ = binding_layout(tt)
    ns, nd = dec['ns'], dec['nd']
    times = dc['m_BeginTime'] + np.arange(dc['m_FrameCount']) / dc['m_SampleRate']
    M = sample_clip(dec, times)
    if orig_clip is not None:
        od = decode_clip(orig_clip)
        olay, _ = binding_layout(orig_clip)
        OM = sample_clip(od, np.clip(times, od['start'], od['stop']))
    lows, allowed = [], []
    for i in range(len(times)):
        lows.append(feet.lowest(rig.pose(overrides(rig, lay, M[i]))))
        o = orig_feet.lowest(orig_rig.pose(overrides(orig_rig, olay, OM[i]))) if orig_clip is not None else {S: sole for S in SIDES}
        allowed.append({S: min(o[S], sole) - TOL for S in SIDES})
    rot_col = {rig.hash_to_pid.get(ph): c0 for ph, attr, nc, c0, tid in lay if tid == 4 and attr == 2}
    before = min(min(l.values()) for l in lows)
    changed = False
    for S in SIDES:
        need = np.array([max(0.0, allowed[i][S] - lows[i][S]) for i in range(len(times))])
        if need.max() <= 0:
            continue
        lift = envelope(need)
        for i in np.nonzero(lift > 1e-4)[0]:
            W = rig.pose(overrides(rig, lay, M[i]))
            for bone, R in ik_leg(rig, feet.pid, W, S, lift[i]).items():
                c0 = rot_col[bone]
                if not ns <= c0 < ns + nd:
                    raise ValueError(f'{tt["m_Name"]}: leg rotation of {rig.goname[bone]} is not a dense curve')
                q = mat2quat(R)
                if q @ M[i, c0:c0 + 4] < 0:
                    q = -q
                M[i, c0:c0 + 4] = q
        changed = True
    if not changed:
        return dict(before=round(before, 3), after=round(before, 3))
    D = M[:, ns:ns + nd]
    dc['m_SampleArray'] = [float(x) for x in D.astype(np.float32).ravel()]
    vad = mc['m_ValueArrayDelta']
    for k in range(nd):
        vad[ns + k] = {'m_Start': float(np.float32(D[0, k])), 'm_Stop': float(np.float32(D[-1, k]))}
    after = min(min(feet.lowest(rig.pose(overrides(rig, lay, M[i]))).values()) for i in range(len(times)))
    return dict(before=round(before, 3), after=round(after, 3))


def main():
    orig_root, root = sys.argv[1], sys.argv[2]
    report = {}
    orig_rig = Rig(os.path.join(orig_root, 'Art', 'Android', 'h', BUNDLES[0]))
    orig_feet = Feet(orig_rig)
    orig_clips = {o.read_typetree()['m_Name']: o.read_typetree() for o in orig_rig.env.objects if o.type.name == 'AnimationClip'}
    for b in BUNDLES:
        path = os.path.join(root, 'Art', 'Android', 'h', b)
        rig = Rig(path)
        feet = Feet(rig)
        sole = min(feet.lowest(rig.pose({})).values())
        for o in rig.env.objects:
            if o.type.name != 'AnimationClip':
                continue
            tt = o.read_typetree()
            name = tt['m_Name']
            res = fix_clip(tt, rig, feet, orig_rig, orig_feet, None if name == 'recall' else orig_clips.get(name), sole)
            if res and res['after'] != res['before']:
                o.save_typetree(tt)
                report[f'{b}:{name}'] = res
        with open(path, 'wb') as fh:
            fh.write(rig.env.file.save(packer='original'))
    for k, v in report.items():
        print(k, v)
    if len(sys.argv) > 3:
        with open(sys.argv[3], 'w') as fh:
            json.dump(report, fh, indent=1)


if __name__ == '__main__':
    main()
