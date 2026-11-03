"""v4: cinematic fade-in / fade-out for the basic attack and passive (empowered) effects, plus fade coverage
fixes for every effect.

Basic attack  : 45_argus_Attack_01/02/03 (+ skin03 overlays), Hit_01 (+ overlays)
Passive       : Attack_04_x empowered attacks, Hit_05, Keep_daoguang sword glow (+ xiaosan dissipate),
                Keep_tuodi sword drag (+ overlays)

Per particle role
  slash   (mesh)      whip-in (86 % -> 100 % size), hot flash on red slashes, expands 12 % while it dissolves,
                      cools to deep crimson, S-curve fade-out from mid-life, lives 18 % longer
  ghost   (echo/ghost afterimage copies) dimmer, long S-tail from 1/3 of life, expands 18 %, almost black-red
  ember   (ember/wisp/drip) lives 45 % longer and rises (upward force) -> floating blood embers after the hit
  smoke   (smoke/mist)  grows 25 % and turns black-red while fading
  droplet (frag/splash/stones) falls with gravity
  spark                 slightly longer decay
  flash   (bloom/glow)  blooms outward (+12 %) as it fades
  mark    (ground mark) lingers 50 % longer and burns out slowly
The effect manager's DelayTime is extended so every new tail finishes before the effect is recycled.
"""
import math
import numpy as np
from vfx_fix import (get_alpha, set_alpha, get_colors, set_colors, interp, interp_col, simplify, mm_max, mm_scale,
                     scale_bursts, hot_head)

BASIC_KEYS = ('45_argus_attack_01', '45_argus_attack_02', '45_argus_attack_03', '45_argus_hit_01')
PASSIVE_KEYS = ('45_argus_attack_04', '45_argus_hit_05', '45_argus_keep_daoguang', '45_argus_keep_tuodi')


def bundle_kind(filename):
    f = filename.lower()
    if any(k in f for k in PASSIVE_KEYS):
        return 'passive'
    if any(k in f for k in BASIC_KEYS):
        return 'basic'
    return None


def role(name, render_mode):
    n = name.lower()
    if 'echo' in n or 'ghost' in n:
        return 'ghost'
    if render_mode == 4:
        return 'slash'
    if any(w in n for w in ('ember', 'wisp')):
        return 'ember'
    if any(w in n for w in ('smoke', 'mist', 'yan', 'fog')):
        return 'smoke'
    if any(w in n for w in ('frag', 'splash', 'blood', 'ston', 'shuidi', 'drip')):
        return 'droplet'
    if any(w in n for w in ('spark', 'glint', 'star', 'lizi')):
        return 'spark'
    if any(w in n for w in ('mark', 'burst', 'ring', 'circle')):
        return 'mark'
    if any(w in n for w in ('bloom', 'glow', 'flash', 'logo', 'ang', 'light')):
        return 'flash'
    if 'trail' in n:
        return 'trail'
    return 'other'


PROFILE = {
    #           life   whip   expand  peak   fade_out_start  end_rgb               emit
    'slash':   (1.18, 0.86,  1.12,  1.00,  0.50,           (0.72, 0.30, 0.32),  1.0),
    'ghost':   (1.35, 0.92,  1.18,  0.78,  0.32,           (0.55, 0.20, 0.22),  1.0),
    'ember':   (1.45, 1.00,  1.00,  1.00,  0.45,           (0.70, 0.30, 0.30),  0.85),
    'smoke':   (1.30, 1.00,  1.25,  0.85,  0.40,           (0.45, 0.15, 0.17),  1.0),
    'droplet': (1.15, 1.00,  1.00,  1.00,  0.55,           (0.70, 0.30, 0.30),  1.0),
    'spark':   (1.10, 1.00,  1.00,  1.00,  0.55,           None,                1.0),
    'flash':   (1.00, 1.00,  1.12,  1.00,  0.45,           (0.75, 0.35, 0.35),  1.0),
    'mark':    (1.50, 1.00,  1.06,  1.00,  0.40,           (0.60, 0.20, 0.22),  1.0),
    'trail':   (1.20, 1.00,  1.00,  1.00,  0.50,           None,                0.85),
    # passive ends (sword glow dissipates): hot flare that blooms 35 % wider and melts into blood red
    'flare':   (1.25, 0.90,  1.35,  1.00,  0.35,           (0.55, 0.15, 0.17),  1.0),
}


def _ss(u):
    u = min(max(u, 0.0), 1.0)
    return u * u * (3 - 2 * u)


# ------------------------------------------------------------------ Unity AnimationCurve helpers
def eval_curve(keys, t):
    if not keys:
        return 1.0
    ks = sorted(keys, key=lambda k: k['time'])
    if t <= ks[0]['time']:
        return ks[0]['value']
    if t >= ks[-1]['time']:
        return ks[-1]['value']
    for a, b in zip(ks, ks[1:]):
        if a['time'] <= t <= b['time']:
            dt = b['time'] - a['time']
            if dt < 1e-6:
                return b['value']
            if not (math.isfinite(a['outSlope']) and math.isfinite(b['inSlope'])):
                return a['value']                       # stepped
            u = (t - a['time']) / dt
            h00 = 2 * u ** 3 - 3 * u ** 2 + 1; h10 = u ** 3 - 2 * u ** 2 + u
            h01 = -2 * u ** 3 + 3 * u ** 2; h11 = u ** 3 - u ** 2
            return h00 * a['value'] + h10 * dt * a['outSlope'] + h01 * b['value'] + h11 * dt * b['inSlope']
    return ks[-1]['value']


def keys_from_samples(ts, vs):
    out = []
    for i, (t, v) in enumerate(zip(ts, vs)):
        if 0 < i < len(ts) - 1:
            s = (vs[i + 1] - vs[i - 1]) / (ts[i + 1] - ts[i - 1])
            if (v - vs[i - 1]) * (vs[i + 1] - v) <= 0:
                s = 0.0
        elif i == 0:
            s = (vs[1] - vs[0]) / (ts[1] - ts[0])
        else:
            s = (vs[-1] - vs[-2]) / (ts[-1] - ts[-2])
        out.append({'time': float(t), 'value': float(v), 'inSlope': float(s), 'outSlope': float(s),
                    'weightedMode': 0, 'inWeight': 0.3333333432674408, 'outWeight': 0.3333333432674408})
    return out


def reshape_size(sm, whip, expand):
    """size(t) := size(t) * whip-in(t) * expand-out(t)"""
    if whip >= 0.999 and expand <= 1.001:
        return False
    curves = [sm['curve']] + ([sm['y'], sm['z']] if sm.get('separateAxes') else [])
    if any(c['minMaxState'] not in (0, 1) for c in curves):
        return False
    ts = [0.0, 0.07, 0.14, 0.3, 0.55, 0.75, 0.9, 1.0]
    for c in curves:
        if not sm['enabled'] or c['minMaxState'] == 0:
            base = [1.0 if not sm['enabled'] else 1.0] * len(ts)
            scal = c['scalar'] if (sm['enabled'] and c['minMaxState'] == 0) else 1.0
            c['minMaxState'] = 1
            c['scalar'] = float(scal)
            c['minScalar'] = float(scal)
        else:
            base = [eval_curve(c['maxCurve']['m_Curve'], t) for t in ts]
        vs = [b * (whip + (1 - whip) * _ss(t / 0.14)) * (1 + (expand - 1) * _ss((t - 0.5) / 0.5)) for b, t in zip(base, ts)]
        c['maxCurve']['m_Curve'] = keys_from_samples(ts, vs)
    sm['enabled'] = True
    return True


def is_flicker(keys):
    vals = [v for _, v in sorted(keys)]
    peaks = sum(1 for i in range(1, len(vals) - 1) if vals[i] > vals[i - 1] + 0.05 and vals[i] > vals[i + 1] + 0.05)
    return peaks > 1


def reshape_alpha(g, peak, t_out):
    """Keep the fade-in, scale the plateau, rebuild the fade-out as a long S-curve starting at t_out.
    Deliberately flickering curves are left as they are (their ends are already at 0)."""
    keys = get_alpha(g)
    if is_flicker(keys):
        return False
    a = lambda t: interp(keys, t)
    # fade-in end = first time the curve reaches 90 % of its max before t_out
    mx = max(v for _, v in keys) or 1.0
    t_in = next((t for t, v in keys if v >= 0.9 * mx), 0.1)
    t_in = min(t_in, t_out - 0.05)
    head = [(t, v * peak) for t, v in keys if t <= t_in + 1e-6]
    if not head or head[0][0] > 0:
        head = [(0.0, 0.0)] + head
    v_out = a(t_out) * peak
    span = 1.0 - t_out
    tail = [(t_out, v_out), (t_out + span * 0.3, v_out * (1 - _ss(0.3))), (t_out + span * 0.7, v_out * (1 - _ss(0.7))), (1.0, 0.0)]
    mid = [(t, v * peak) for t, v in keys if t_in + 1e-6 < t < t_out - 1e-3]
    new = sorted(set((round(t, 5), float(v)) for t, v in head + mid + tail))
    set_alpha(g, simplify(new, 8))
    return True


def darken_end(g, rgb_mul):
    keys = get_colors(g)
    if not keys:
        return
    if keys[-1][0] < 0.999:
        keys.append((1.0, tuple(interp_col(keys, 1.0))))
    t_mid = 0.6
    mid = tuple(interp_col(keys, t_mid))
    new = [k for k in keys if k[0] < t_mid - 1e-3] + [(t_mid, mid), (1.0, tuple(np.array(keys[-1][1]) * np.array(rgb_mul)))]
    set_colors(g, simplify(new, 8, interp_col))


def add_rise(tt, up=1.5):
    fm = tt['ForceModule']
    if fm['enabled']:
        y = fm['y']
        if y['minMaxState'] == 0:
            y['scalar'] = float(y['scalar'] + up); y['minScalar'] = float(y['minScalar'] + up)
            return True
        return False
    fm['enabled'] = True
    for ax in ('x', 'y', 'z'):
        c = fm[ax]
        c['minMaxState'] = 0
        c['scalar'] = c['minScalar'] = float(up if ax == 'y' else 0.0)
    fm['inWorldSpace'] = True
    if 'randomizePerFrame' in fm:
        fm['randomizePerFrame'] = False
    return True


def add_gravity(tt, g=0.9):
    gm = tt['InitialModule'].get('gravityModifier')
    if not isinstance(gm, dict):
        return False
    if mm_max(gm) > 0.05:
        return False
    gm['minMaxState'] = 0
    gm['scalar'] = gm['minScalar'] = float(g)
    return True


def apply_cinematic(tt, go_name, render_mode, bundle=''):
    r = role(go_name, render_mode)
    if 'xiaosan' in bundle.lower():          # the passive's own fade-out effect
        r = {'flash': 'flare', 'spark': 'ember'}.get(r, r)
    if r not in PROFILE:
        return r, {}
    life_mul, whip, expand, peak, t_out, end_rgb, emit = PROFILE[r]
    im = tt['InitialModule']
    done = {}
    looping = bool(tt['looping'])
    if life_mul != 1.0:
        mm_scale(im['startLifetime'], life_mul)
        done['life'] = life_mul
        if looping:
            emit = emit / life_mul             # keep the same density on loops
    if emit != 1.0:
        em = tt['EmissionModule']
        mm_scale(em['rateOverTime'], emit)
        scale_bursts(em, emit)
        done['emit'] = round(emit, 2)
    if reshape_size(tt['SizeModule'], whip, expand):
        done['size'] = (whip, expand)
    gr = tt['ColorModule']['gradient']
    grads = [gr['maxGradient']] + ([gr['minGradient']] if gr['minMaxState'] == 3 else [])
    for g in grads:
        reshape_alpha(g, peak, t_out)
        if end_rgb is not None:
            darken_end(g, end_rgb)
    done['fade'] = (peak, t_out)
    if r in ('slash', 'flare') and hot_head(im, grads):   # embers already got their hot head in the v2 pass
        done['hot'] = True
    if r == 'ember' and add_rise(tt):
        done['rise'] = True
    if r == 'droplet' and add_gravity(tt):
        done['gravity'] = True
    return r, done


# ------------------------------------------------------------------ fade coverage fixes for mesh effects
def _val(ks, t):
    ks = sorted(ks, key=lambda k: k['time'])
    if t <= ks[0]['time']:
        return ks[0]['value']
    for a, b in zip(ks, ks[1:]):
        if a['time'] <= t <= b['time']:
            u = (t - a['time']) / max(b['time'] - a['time'], 1e-6)
            return a['value'] + (b['value'] - a['value']) * u
    return ks[-1]['value']


def _key(t, v):
    return {'time': float(t), 'value': float(v), 'inSlope': 0.0, 'outSlope': 0.0, 'weightedMode': 0,
            'inWeight': 0.3333333432674408, 'outWeight': 0.3333333432674408}


def fix_legacy_popouts(tt, fade=0.18):
    """Mesh effects that get switched off (m_IsActive) while still visible get a fade that ends just before
    the switch-off; this also covers children of a switched-off parent. Dissolves that would finish after the
    switch-off are moved earlier; dissolves that never finish are completed."""
    if 'off' in tt['m_Name'].lower():
        return 0
    fixes = 0
    curves = tt['m_FloatCurves']
    offs = {}
    for fc in curves:
        if fc['attribute'] == 'm_IsActive':
            ks = sorted(fc['curve']['m_Curve'], key=lambda k: k['time'])
            for i in range(1, len(ks)):
                if ks[i]['value'] < 0.5 <= ks[i - 1]['value']:
                    offs.setdefault(fc['path'], []).append(ks[i]['time'])
    for fc in curves:
        a = fc['attribute']
        is_alpha = a.startswith('material.') and 'Color' in a and a.endswith('.a')
        is_diss = a == 'material._DissolveStep'
        if not (is_alpha or is_diss):
            continue
        p = fc['path']
        cands = [t for q, ts in offs.items() for t in ts if p == q or p.startswith(q + '/')]
        ks = sorted(fc['curve']['m_Curve'], key=lambda k: k['time'])
        if not ks:
            continue
        if cands:
            t_off = min(cands)
            t_end = t_off - 0.02
            if is_alpha and _val(ks, t_end) > 0.05:
                t0 = max(t_end - fade, ks[0]['time'])
                v0 = _val(ks, t0)
                new = [k for k in ks if k['time'] < t0 - 1e-4] + [_key(t0, v0), _key(t_end, 0.0)]
                fc['curve']['m_Curve'] = new
                fixes += 1
            elif is_diss and ks[-1]['time'] > t_off and ks[-1]['value'] > _val(ks, t_end) + 0.05:
                last = ks[-1]['value']
                t0 = max(t_end - fade, ks[0]['time'])
                new = [k for k in ks if k['time'] < t0 - 1e-4] + [_key(t0, _val(ks, t0)), _key(t_end, last)]
                fc['curve']['m_Curve'] = new
                fixes += 1
        elif is_diss and 0.05 < ks[-1]['value'] < 0.95 and ks[-1]['value'] > ks[0]['value']:
            fc['curve']['m_Curve'] = ks + [_key(ks[-1]['time'] + 0.08, 1.0)]
            fixes += 1
    return fixes


def flare_off_clip(tt):
    """'...weaponfx_off' style clips (the passive sword glow switching off): the red glow flares white-hot for
    a moment before it fades, and abrupt alpha drops become S-curve dissolves."""
    if 'off' not in tt['m_Name'].lower():
        return 0
    by_path = {}
    for fc in tt['m_FloatCurves']:
        a = fc['attribute']
        if a.startswith('material._Color.'):
            by_path.setdefault(fc['path'], {})[a[-1]] = fc
    n = 0
    for path, ch in by_path.items():
        if not all(c in ch for c in 'rgba'):
            continue
        ks = {c: sorted(ch[c]['curve']['m_Curve'], key=lambda k: k['time']) for c in 'rgba'}
        T = max(k['time'] for c in 'rgba' for k in ks[c])
        if T <= 0.2:
            continue
        r0, g0, b0 = ks['r'][0]['value'], ks['g'][0]['value'], ks['b'][0]['value']
        if r0 >= 0.9 and g0 <= 0.1 and b0 <= 0.1:          # bright red glow -> white-hot flare first
            ch['g']['curve']['m_Curve'] = [_key(0.0, g0), _key(0.1, 0.5), _key(0.3, g0), _key(T, g0)]
            ch['b']['curve']['m_Curve'] = [_key(0.0, b0), _key(0.1, 0.42), _key(0.3, b0), _key(T, b0)]
            n += 1
        a = ks['a']
        if len(a) >= 2 and a[-1]['value'] < 0.05 and a[-2]['value'] > 0.5 and a[-1]['time'] - a[-2]['time'] < 0.15:
            a0 = a[0]['value']
            ch['a']['curve']['m_Curve'] = [_key(0.0, a0), _key(T * 0.45, a0), _key(T, 0.0)]
            n += 1
    return n
