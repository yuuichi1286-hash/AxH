"""Smooth Mecanim generic clips of the Hidan rig and rebuild them as clean dense clips.

What it does per clip
  * samples the clip exactly like Unity evaluates it (streamed Hermite / dense lerp / constant)
  * quaternion hemisphere continuity (no sign flips)
  * looping clips: removes the pose jump at the loop seam (error spread over the cycle) + periodic smoothing
  * despin: extreme sustained spins (e.g. 9 turns in 0.6 s, strobing at 30 fps) lose whole turns only,
    start/end orientation unchanged
  * despike: isolated snaps (a bone jumping 100-180 deg in 1-2 frames) are re-tweened with an eased slerp
    so they read as a fast swing instead of a teleport
  * light Gaussian smoothing everywhere (kills linear-key kinks / jitter), capped by angular speed so fast
    intentional spins are never averaged away
  * GameObject.m_IsActive (mesh swap) curves are kept as exact step functions
  * recall: rebuilt as a longer non-looping clip: smoothed gesture -> stance with subtle breathing -> rest
  * re-encoded as a dense 60 fps clip; m_MuscleClipSize recomputed with the formula verified on all clips
"""
import math
import numpy as np
from clipio import decode_clip, binding_layout, sample_clip

HI = 240.0      # analysis rate
OUT = 60.0      # output dense sample rate

# ---------------------------------------------------------------- quaternion helpers (x, y, z, w)
def qnorm(q):
    return q / np.linalg.norm(q, axis=-1, keepdims=True)

def qmul(a, b):
    ax, ay, az, aw = np.moveaxis(a, -1, 0)
    bx, by, bz, bw = np.moveaxis(b, -1, 0)
    return np.stack([aw * bx + ax * bw + ay * bz - az * by,
                     aw * by - ax * bz + ay * bw + az * bx,
                     aw * bz + ax * by - ay * bx + az * bw,
                     aw * bw - ax * bx - ay * by - az * bz], -1)

def qinv(q):
    return q * np.array([-1.0, -1.0, -1.0, 1.0])

def qaxis(axis, ang):
    axis = np.asarray(axis, float)
    axis = axis / (np.linalg.norm(axis) + 1e-12)
    ang = np.asarray(ang, float)
    s = np.sin(ang / 2.0)[..., None]
    return np.concatenate([axis * s, np.cos(ang / 2.0)[..., None]], -1)

def qpow(q, w):
    """q^w for unit q (w may be an array)."""
    q = q if q[3] >= 0 else -q
    ang = 2.0 * math.acos(min(1.0, max(-1.0, q[3])))
    if ang < 1e-9:
        return np.tile(np.array([0, 0, 0, 1.0]), (np.size(w), 1))
    axis = q[:3] / math.sin(ang / 2.0)
    return qaxis(axis, ang * np.asarray(w, float))

def continuity(q):
    q = qnorm(q.copy())
    for i in range(1, len(q)):
        if np.dot(q[i], q[i - 1]) < 0:
            q[i] = -q[i]
    return q

def ang_speed(q, rate):
    d = np.abs(np.sum(q[1:] * q[:-1], 1))
    a = np.degrees(2 * np.arccos(np.clip(d, 0, 1))) * rate
    return np.concatenate([a[:1], a])

def smoothstep(e0, e1, x):
    t = np.clip((np.asarray(x, float) - e0) / (e1 - e0), 0, 1)
    return t * t * (3 - 2 * t)

def maxfilter(x, r):
    out = x.copy()
    for k in range(1, r + 1):
        out[k:] = np.maximum(out[k:], x[:-k])
        out[:-k] = np.maximum(out[:-k], x[k:])
    return out

def adaptive_gauss(X, sigma, dt, periodic):
    """X (N,k), sigma (N,) seconds. periodic: sample N-1 == sample 0 (period N-1)."""
    N = len(X)
    out = np.empty_like(X)
    period = N - 1
    for i in range(N - 1 if periodic else N):
        s = max(float(sigma[i]), 1e-4)
        r = int(math.ceil(3.0 * s / dt))
        off = np.arange(-r, r + 1)
        w = np.exp(-0.5 * (off * dt / s) ** 2)
        idx = i + off
        idx = idx % period if periodic else np.clip(idx, 0, N - 1)
        out[i] = (w[:, None] * X[idx]).sum(0) / w.sum()
    if periodic:
        out[N - 1] = out[0]
    return out

# ---------------------------------------------------------------- per-clip profiles
PROFILES = {
    # name: base Gaussian sigma (s) - removes linear-key kinks / jitter
    'fight_idle': 0.030,
    'run': 0.011,
    'run2': 0.011,
    'recall': 0.026,
    'dead': 0.016,
    'landing': 0.018,
}
DEFAULT_PROFILE = 0.015
SIGMA_CAP_DEG = 45.0   # never average over more rotation than this per sigma (keeps fast spins intact)

# isolated snaps (teleport-like jumps) are re-tweened with an eased slerp
SNAP_ROT = 1500.0      # deg/s  (= 25 deg per frame @60fps)
SNAP_POS = 6.0         # m/s
SNAP_MAX_DUR = 0.075   # s, longer fast segments are intentional spins/swings -> left alone
TWEEN_ROT = 1100.0     # deg/s average speed of the replacement tween
TWEEN_POS = 4.0        # m/s
H_MIN, H_MAX = 0.03, 0.10


def smootherstep(u):
    u = np.clip(u, 0, 1)
    return u * u * u * (u * (u * 6 - 15) + 10)


def qslerp(a, b, u):
    d = float(np.dot(a, b))
    if d < 0:
        b, d = -b, -d
    u = np.asarray(u, float)[:, None]
    if d > 0.9995:
        return qnorm(a + (b - a) * u)
    th = math.acos(d)
    return (np.sin((1 - u) * th) * a + np.sin(u * th) * b) / math.sin(th)


def _runs(mask):
    runs = []
    i = 0
    n = len(mask)
    while i < n:
        if mask[i]:
            j = i
            while j + 1 < n and mask[j + 1]:
                j += 1
            runs.append((i, j))
            i = j + 1
        else:
            i += 1
    return runs


def despike(X, kind, rate):
    """Replace isolated snaps by an eased tween so they read as fast motion instead of a pop."""
    X = X.copy()
    n = len(X)
    for _ in range(2):
        if kind == 'rot':
            sp = ang_speed(X, rate)
            hot = sp > SNAP_ROT
        else:
            sp = np.concatenate([[0.0], np.linalg.norm(np.diff(X, axis=0), axis=1) * rate])
            hot = sp > SNAP_POS
        changed = False
        for a, b in _runs(hot):
            if (b - a + 1) / rate > SNAP_MAX_DUR:
                continue
            i0, i1 = max(a - 1, 0), b
            if kind == 'rot':
                d = abs(float(np.dot(X[i0], X[i1])))
                total = math.degrees(2 * math.acos(min(1.0, d)))
                if total < 20.0:
                    continue
                path = float(sp[a:b + 1].sum() / rate)
                at_start = a / rate < 0.08     # wild whip in the first frames (hidden by nothing but a crossfade)
                if path > 2.0 * total + 20.0 and not at_start:
                    continue          # strongly curved / multi-turn swing: a shortest-path tween would change it
                h = total / (2 * TWEEN_ROT)
            else:
                total = float(np.linalg.norm(X[i1] - X[i0]))
                if total < 0.05:
                    continue
                h = total / (2 * TWEEN_POS)
            h = min(max(h, H_MIN, (b - a + 1) / rate / 2 + 0.012), H_MAX)
            c = 0.5 * (i0 + i1)
            s = max(int(math.floor(c - h * rate)), 0)
            e = min(int(math.ceil(c + h * rate)), n - 1)
            if e - s < 2:
                continue
            u = smootherstep((np.arange(s, e + 1) - s) / (e - s))
            if kind == 'rot':
                X[s:e + 1] = qslerp(X[s], X[e], u)
                X = continuity(X)
            else:
                X[s:e + 1] = X[s][None, :] + (X[e] - X[s])[None, :] * u[:, None]
            changed = True
        if not changed:
            break
    return X


SPIN_SPEED = 2400.0    # deg/s -> candidate spin segment
SPIN_MIN_DUR = 0.10
SPIN_MIN_AVG = 3000.0  # only spins faster than this on average are slowed (body spins ~2000 deg/s are kept)
SPIN_TARGET = 2200.0   # deg/s average after removing whole turns (readable at 30 and 60 fps)
SPIN_MIN_CONS = 0.6    # axis consistency (|sum axis*angle| / sum angle)


def _qlog_axis_angle(d):
    d = d if d[3] >= 0 else -d
    s = np.linalg.norm(d[:3])
    ang = 2 * math.atan2(s, d[3])
    axis = d[:3] / s if s > 1e-9 else np.array([1.0, 0, 0])
    return axis, ang


def despin(X, rate):
    """Very fast sustained spins (e.g. 9 turns in 0.6 s) strobe at 30 fps. Remove whole turns about the
    spin axis so the spin reads clearly; start/end orientation of the segment are preserved exactly."""
    X = X.copy()
    sp = ang_speed(X, rate)
    for a, b in _runs(maxfilter((sp > SPIN_SPEED).astype(float), int(0.02 * rate)) > 0):
        if (b - a + 1) / rate < SPIN_MIN_DUR:
            continue
        s, e = max(a - 1, 0), b
        axes, angs = [], []
        for i in range(s + 1, e + 1):
            d = qmul(qinv(X[i - 1]), X[i])          # rotation in the bone's own (local) frame
            ax, an = _qlog_axis_angle(d)
            axes.append(ax); angs.append(an)
        axes = np.array(axes); angs = np.array(angs)
        mean = (axes * angs[:, None]).sum(0)
        if np.linalg.norm(mean) < SPIN_MIN_CONS * angs.sum():
            continue                                 # not a clean spin about one axis
        axis = mean / np.linalg.norm(mean)
        theta = np.concatenate([[0.0], np.cumsum(angs * np.sign(axes @ axis))])
        total = theta[-1]
        dur = (e - s) / rate
        if math.degrees(angs.sum()) / dur < SPIN_MIN_AVG:
            continue
        turns = int(math.ceil((abs(total) - math.radians(SPIN_TARGET) * dur) / (2 * math.pi)))
        if turns <= 0:
            continue
        new_total = total - math.copysign(2 * math.pi * turns, total)
        k = new_total / total
        base = qmul(X[s:e + 1], qaxis(axis, -theta))   # spin removed
        X[s:e + 1] = qnorm(qmul(base, qaxis(axis, theta * k)))
        X = continuity(X)
    return X


def _smooth_group(X, kind, rate, profile, periodic):
    base = profile
    if kind == 'rot' and not periodic:
        X = despin(X, rate)
    if not periodic:
        X = despike(X, kind, rate)
    if kind == 'rot':
        sp = ang_speed(X, rate)
        sp = maxfilter(sp, int(0.03 * rate))
        sigma = np.minimum(base, SIGMA_CAP_DEG / np.maximum(sp, 1e-3))
        sigma = np.maximum(sigma, 0.25 / rate)
    else:
        sigma = np.full(len(X), base)
    Y = adaptive_gauss(X, sigma, 1.0 / rate, periodic)
    return qnorm(Y) if kind == 'rot' else Y


def _loop_fix(X, kind, times):
    """Spread the start/end mismatch over the whole cycle so the loop is seamless."""
    T = times[-1] - times[0]
    w = (times - times[0]) / T
    if kind == 'rot':
        dq = qmul(X[0], qinv(X[-1]))
        dq = qnorm(dq)
        corr = qpow(dq, w)
        Y = qnorm(qmul(corr, X))
        return continuity(Y)
    return X + w[:, None] * (X[0] - X[-1])[None, :]


def muscle_clip_size(n_dense_floats, n_const, n_index, n_vad, n_varp=0, n_streamed_words=0):
    # verified against every Mecanim clip in this mod (and the official ones):
    #   empty streamed clip -> base 1984, otherwise base 1728 (+4 bytes per streamed word)
    base = 1728 if n_streamed_words else 1984
    return base + 4 * (n_streamed_words + n_dense_floats + n_const + n_index) + 8 * n_vad + 4 * n_varp


FLT_MAX = 3.4028234663852886e+38


def _step_streamed(step_vals, t_hi, start, stop):
    """Encode step curves (list of (N_hi, nc) arrays) as a Unity streamed clip with constant segments."""
    from clipio import build_streamed
    if not step_vals:
        return [], 0
    curves = np.concatenate(step_vals, 1)
    nc = curves.shape[1]
    init = [(ci, 0.0, 0.0, 0.0, float(curves[0, ci])) for ci in range(nc)]
    frames = [(-FLT_MAX, init), (float(start), list(init))]
    raw = []
    for ci in range(nc):
        v = curves[:, ci]
        for j in np.nonzero(np.abs(np.diff(v)) > 1e-7)[0] + 1:
            t = 0.5 * (t_hi[j - 1] + t_hi[j])
            if start < t < stop:
                raw.append((float(t), (ci, 0.0, 0.0, 0.0, float(v[j]))))
    raw.sort()
    # toggles that belong together (mesh A off / mesh B on) switch on the very same frame
    clusters = []
    for t, key in raw:
        if clusters and t - clusters[-1][-1][0] < 0.012:
            clusters[-1].append((t, key))
        else:
            clusters.append([(t, key)])
    for cl in clusters:
        tc = round(float(np.mean([t for t, _ in cl])), 6)
        frames.append((tc, sorted(k for _, k in cl)))
    frames.append((float(stop), [(ci, 0.0, 0.0, 0.0, float(curves[-1, ci])) for ci in range(nc)]))
    frames.append((float('inf'), []))
    return build_streamed(frames), nc


class ClipFixer:
    def __init__(self, rig=None):
        self.rig = rig   # fk.Rig, needed for recall breathing axes

    def process(self, tt, recall_len=6.5):
        name = tt['m_Name']
        mc = tt['m_MuscleClip']
        dec = decode_clip(tt)
        lay, ncurves = binding_layout(tt)
        start, stop = dec['start'], dec['stop']
        loop = bool(mc['m_LoopTime'])
        is_recall = name == 'recall'
        profile = PROFILES.get(name, DEFAULT_PROFILE)

        new_stop = stop
        if is_recall:
            new_stop = round(max(stop, recall_len) * OUT) / OUT
        n_hi = int(round((new_stop - start) * HI)) + 1
        t_hi = start + np.arange(n_hi) / HI
        t_eval = np.minimum(t_hi, stop)              # recall: hold last original pose after its end
        M = sample_clip(dec, t_eval)
        # step curves: left limit at the very end (avoid stray keys exactly at stop)
        t_left = np.minimum(t_hi, stop - 1e-4)
        M_left = sample_clip(dec, t_left)

        n_out = int(round((new_stop - start) * OUT)) + 1
        t_out = start + np.arange(n_out) / OUT
        hi_idx = np.round((t_out - start) * HI).astype(int)

        periodic = loop and not is_recall
        groups = []   # (binding index, values (n_out, nc))
        step_hi = {}  # binding index -> hi-rate step values (exact toggle times)
        report = {}
        for bi, (ph, attr, nc, c0, tid) in enumerate(lay):
            X = M[:, c0:c0 + nc].copy()
            if tid == 4 and attr == 2:
                X = continuity(X)
                if periodic:
                    X = _loop_fix(X, 'rot', t_hi)
                Y = _smooth_group(X, 'rot', HI, profile, periodic)
                Y = continuity(Y)
                before = ang_speed(X[hi_idx], OUT).max() / OUT
                after = ang_speed(Y[hi_idx], OUT).max() / OUT
                report[bi] = (before, after)
                vals = Y[hi_idx]
            elif tid == 4 and attr in (1, 3):
                if periodic:
                    X = _loop_fix(X, 'pos', t_hi)
                Y = _smooth_group(X, 'pos', HI, profile, periodic) if attr == 1 else X
                vals = Y[hi_idx]
            else:
                # m_IsActive and other float bindings: exact step, sampled left-continuous
                Xl = M_left[:, c0:c0 + nc]
                if tid == 1:
                    Xl = (Xl > 0.5).astype(float)
                step_hi[bi] = Xl
                vals = Xl[hi_idx]
            groups.append(vals)

        if is_recall:
            groups = self._recall_breathing(lay, groups, t_out, stop, new_stop)

        # partition bindings into animated / constant
        bindings = tt['m_ClipBindingConstant']['genericBindings']
        step_b, anim_b, const_b = [], [], []
        for bi, vals in enumerate(groups):
            if bi in step_hi and np.max(np.abs(step_hi[bi] - step_hi[bi][0:1])) > 1e-7:
                step_b.append(bi)          # exact step (mesh swap) -> streamed clip
            elif np.max(np.abs(vals - vals[0:1])) > 1e-7:
                anim_b.append(bi)
            else:
                const_b.append(bi)
        order = step_b + anim_b + const_b
        streamed_words, n_streamed = _step_streamed([step_hi[b] for b in step_b], t_hi, start, new_stop)
        dense = np.concatenate([groups[b] for b in anim_b], 1) if anim_b else np.zeros((n_out, 0))
        const = np.concatenate([groups[b][0] for b in const_b]) if const_b else np.zeros(0)
        vad = []
        for b in order:
            v = groups[b]
            for k in range(v.shape[1]):
                vad.append({'m_Start': float(v[0, k]), 'm_Stop': float(v[-1, k])})

        data = mc['m_Clip']['data']
        data['m_StreamedClip'] = {'data': streamed_words, 'curveCount': n_streamed}
        data['m_DenseClip'] = {'m_FrameCount': n_out, 'm_CurveCount': int(dense.shape[1]),
                               'm_SampleRate': float(OUT), 'm_BeginTime': float(start),
                               'm_SampleArray': [float(x) for x in dense.astype(np.float32).ravel()]}
        data['m_ConstantClip'] = {'data': [float(x) for x in const.astype(np.float32)]}
        mc['m_ValueArrayDelta'] = vad
        mc['m_StopTime'] = float(new_stop)
        if is_recall:
            mc['m_LoopTime'] = False
        tt['m_ClipBindingConstant']['genericBindings'] = [bindings[b] for b in order]
        tt['m_SampleRate'] = float(OUT)
        tt['m_MuscleClipSize'] = muscle_clip_size(dense.size, const.size, len(mc['m_IndexArray']), len(vad),
                                                  len(mc.get('m_ValueArrayReferencePose', [])),
                                                  n_streamed_words=len(streamed_words))
        worst_before = max((b for b, a in report.values()), default=0)
        worst_after = max((a for b, a in report.values()), default=0)
        return dict(name=name, frames=n_out, dense_curves=int(dense.shape[1]), const=int(const.size),
                    loop=bool(mc['m_LoopTime']), dur=new_stop - start,
                    worst_deg_per_frame_before=round(float(worst_before), 1),
                    worst_deg_per_frame_after=round(float(worst_after), 1))

    # ---------------------------------------------------------------- recall: breathing stance
    def _recall_breathing(self, lay, groups, t_out, orig_stop, new_stop):
        rig = self.rig
        if rig is None:
            return groups
        # pose at the stance (last original frame) -> world matrices
        fi = int(np.searchsorted(t_out, orig_stop - 1e-6))
        fi = min(fi, len(t_out) - 1)
        ov = {}
        rot_slot = {}
        pos_slot = {}
        for bi, (ph, attr, nc, c0, tid) in enumerate(lay):
            pid = rig.hash_to_pid.get(ph)
            if pid is None or tid != 4:
                continue
            key = {1: 't', 2: 'q', 3: 's'}[attr]
            ov.setdefault(pid, {})[key] = list(groups[bi][fi])
            if attr == 2:
                rot_slot[rig.goname[pid]] = (bi, pid)
            if attr == 1:
                pos_slot[rig.goname[pid]] = (bi, pid)
        W = rig.pose(ov)

        def wpos(n):
            pid = [p for p, g in rig.goname.items() if g == n and p in W][0]
            return W[pid][:3, 3]

        def parent_rot(pid):
            R = W[rig.parent[pid]][:3, :3]
            return R / np.linalg.norm(R, axis=0, keepdims=True)

        up = np.array([0.0, 1.0, 0.0])
        lateral = wpos('L_Shoulder') - wpos('R_Shoulder')
        lateral -= up * lateral.dot(up)
        lateral /= np.linalg.norm(lateral)

        period = 2.7
        w = 2 * math.pi / period
        t0 = orig_stop - 0.75
        env = smoothstep(t0 - 0.25, t0 + 0.9, t_out) * (1.0 - smoothstep(new_stop - 1.5, new_stop - 0.2, t_out))
        breath = np.sin(w * (t_out - t0))

        def add_rot(bone, axis_world, amp_deg, phase, signal=None):
            if bone not in rot_slot:
                return
            bi, pid = rot_slot[bone]
            Rp = parent_rot(pid)
            axis_local = Rp.T @ axis_world
            sig = signal if signal is not None else np.sin(w * (t_out - t0) + phase)
            ang = np.radians(amp_deg) * env * sig
            groups[bi] = qnorm(qmul(qaxis(axis_local, ang), groups[bi]))

        # chest rises / falls (pitch about the body's lateral axis), head counters a little
        add_rot('Spine', lateral, 0.9, 0.0)
        add_rot('Spine1', lateral, 1.5, -0.35)
        add_rot('Neck', lateral, -0.6, -0.7)
        add_rot('Head', lateral, -0.5, -0.9)
        # very slow head scan (yaw) - alive, menacing
        add_rot('Head', up, 1.6, 0.0, np.sin(0.5 * w * (t_out - t0) + 0.4))
        # shoulders/arms lift slightly on inhale
        for side in ('L', 'R'):
            for bone, amp in ((f'{side}_Shoulder', 0.9), (f'{side}_Arm', 0.8)):
                if bone not in rot_slot:
                    continue
                pid = rot_slot[bone][1]
                kids = [c['m_PathID'] for c in rig.tf[pid]['m_Children']]
                if not kids:
                    continue
                d = W[kids[0]][:3, 3] - W[pid][:3, 3]
                ax = np.cross(d, up)
                if np.linalg.norm(ax) < 1e-6:
                    continue
                add_rot(bone, ax / np.linalg.norm(ax), amp, -0.5)
        # tiny vertical bob of the hips
        if 'Hip' in pos_slot:
            bi, pid = pos_slot['Hip']
            Rp = parent_rot(pid)
            groups[bi] = groups[bi] + (Rp.T @ up)[None, :] * (0.004 * env * breath)[:, None]
        return groups


def fix_controller(tt, recall_state='recall'):
    """Smoother cross-fades: no hard cut into the ultimate, softer recall in/out, 0.1 -> 0.15 s elsewhere."""
    tos = {}
    for e in tt['m_TOS']:
        k, v = (e[0], e[1]) if isinstance(e, (list, tuple)) else (e['first'], e['second'])
        tos[k] = v
    sm = tt['m_Controller']['m_StateMachineArray'][0]
    sm = sm['data'] if 'data' in sm else sm
    states = [s['data'] if 'data' in s else s for s in sm['m_StateConstantArray']]
    names = [tos.get(s['m_NameID'], str(s['m_NameID'])) for s in states]
    changes = []
    for si, st in enumerate(states):
        src = names[si]
        if src == recall_state:
            st['m_Loop'] = False
        for tr in st['m_TransitionConstantArray']:
            tr = tr['data'] if 'data' in tr else tr
            dst = names[tr['m_DestinationState']] if tr['m_DestinationState'] < len(names) else '?'
            old = tr['m_TransitionDuration']
            new = old
            if src == 'dead':
                continue                          # respawn stays instant
            if dst == 'skill3' and old == 0.0:
                new = 0.08                        # was a hard cut into the ultimate
            elif dst == recall_state and abs(old - 0.1) < 1e-6:
                new = 0.25
            elif src == recall_state and abs(old - 0.1) < 1e-6:
                new = 0.2
            elif abs(old - 0.1) < 1e-6 and tr['m_HasFixedDuration']:
                new = 0.15
            if new != old:
                tr['m_TransitionDuration'] = float(new)
                changes.append((src, dst, old, new))
    return changes
