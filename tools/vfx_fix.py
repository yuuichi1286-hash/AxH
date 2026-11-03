"""VFX pass for every effect bundle of the Hidan mod.

Per ParticleSystem
  * fade envelope: alpha over lifetime starts at 0 and ends at 0 (fade-in / fade-out), existing keys kept
  * definition: spark-like particles get a hotter (whiter) head, every gradient cools to a deeper crimson
    before it disappears -> clearer read of each burst instead of a flat red smear
  * optimisation: Noise module -> Low quality (1D), emitters that spawn far more particles than a mobile
    MOBA effect needs are compressed (sub-linear) with a small size compensation, maxParticles capped
Per legacy effect clip
  * material alpha curves that pop in at full opacity get a short fade-in
Oversized textures (1254x1254 ETC2 RGBA8) -> 1024x1024 ASTC 5x5
"""
import math
import colorsys
import numpy as np

PARTICLE_BUDGET = 32.0       # particles alive at once per emitter before compression kicks in
EMIT_EXPONENT = 0.55
MIN_EMIT_FACTOR = 0.3
SPARK_WORDS = ('spark', 'glint', 'lizi', 'ember', 'star', 'ci_', 'shine', 'flash', 'dian')


# ------------------------------------------------------------------ gradient helpers
def get_alpha(g):
    return [(g[f'atime{i}'] / 65535.0, g[f'key{i}']['a']) for i in range(g['m_NumAlphaKeys'])]


def set_alpha(g, keys):
    keys = sorted(keys)
    for i in range(8):
        if i < len(keys):
            g[f'atime{i}'] = int(round(min(max(keys[i][0], 0.0), 1.0) * 65535))
            g[f'key{i}']['a'] = float(min(max(keys[i][1], 0.0), 1.0))
        else:
            g[f'atime{i}'] = 0
    g['m_NumAlphaKeys'] = len(keys)


def get_colors(g):
    return [(g[f'ctime{i}'] / 65535.0, (g[f'key{i}']['r'], g[f'key{i}']['g'], g[f'key{i}']['b'])) for i in range(g['m_NumColorKeys'])]


def set_colors(g, keys):
    keys = sorted(keys, key=lambda k: k[0])
    for i in range(8):
        if i < len(keys):
            g[f'ctime{i}'] = int(round(min(max(keys[i][0], 0.0), 1.0) * 65535))
            r, gg, b = keys[i][1]
            g[f'key{i}']['r'], g[f'key{i}']['g'], g[f'key{i}']['b'] = float(r), float(gg), float(b)
        else:
            g[f'ctime{i}'] = 0
    g['m_NumColorKeys'] = len(keys)


def interp(keys, t):
    if not keys:
        return 1.0
    if t <= keys[0][0]:
        return keys[0][1]
    for (t0, a0), (t1, a1) in zip(keys, keys[1:]):
        if t0 <= t <= t1:
            return a0 if t1 - t0 < 1e-6 else a0 + (a1 - a0) * (t - t0) / (t1 - t0)
    return keys[-1][1]


def interp_col(keys, t):
    if t <= keys[0][0]:
        return np.array(keys[0][1])
    for (t0, c0), (t1, c1) in zip(keys, keys[1:]):
        if t0 <= t <= t1:
            u = 0 if t1 - t0 < 1e-6 else (t - t0) / (t1 - t0)
            return np.array(c0) * (1 - u) + np.array(c1) * u
    return np.array(keys[-1][1])


def simplify(keys, maxn=8, f=interp):
    keys = list(keys)
    grid = np.linspace(0, 1, 97)
    ref = [f(keys, t) for t in grid]
    while len(keys) > maxn:
        best, best_err = None, 1e9
        for i in range(1, len(keys) - 1):
            cand = keys[:i] + keys[i + 1:]
            err = max(np.max(np.abs(np.array(f(cand, t)) - np.array(r))) for t, r in zip(grid, ref))
            if err < best_err:
                best, best_err = i, err
        keys.pop(best)
    return keys


def fade_keys(keys, life):
    t_in = float(np.clip(0.07 / max(life, 1e-3), 0.05, 0.18))
    t_out = 1.0 - float(np.clip(0.16 / max(life, 1e-3), 0.2, 0.45))
    k = sorted(keys)
    changed = False
    orig = list(k)
    if interp(orig, 0.0) > 0.02:
        k = [(0.0, 0.0), (t_in, interp(orig, t_in))] + [kk for kk in k if kk[0] > t_in + 1e-3]
        changed = True
    if interp(orig, 1.0) > 0.02:
        k = [kk for kk in k if kk[0] < t_out - 1e-3] + [(t_out, interp(orig, t_out)), (1.0, 0.0)]
        changed = True
    return (simplify(k) if changed else keys), changed


def polish_colors(g, hot_head):
    """Cool to a deeper crimson at the end of life; optional hotter (whiter) head for spark-like particles."""
    keys = get_colors(g)
    if not keys:
        return False

    def red_or_neutral(c):
        h, sat, v = colorsys.rgb_to_hsv(*[min(max(x, 0.0), 1.0) for x in c])
        return sat < 0.25 or h < 0.06 or h > 0.92

    if not all(red_or_neutral(c) for _, c in keys):
        return False
    orig = list(keys)
    new = list(keys)
    if new[-1][0] < 0.999:
        new.append((1.0, tuple(interp_col(orig, 1.0))))
    new[-1] = (1.0, tuple(np.array(new[-1][1]) * np.array([0.78, 0.62, 0.62])))
    set_colors(g, simplify(new, 8, interp_col))
    return True


def _is_red(h, sat):
    return sat > 0.35 and (h < 0.06 or h > 0.92)


def hot_head(im, grads, head_t=0.18, accept=_is_red, lift=0.4):
    """Spark-like particles: brighter, whiter birth that settles to the original blood red after head_t.
    Colour over lifetime multiplies the start colour, so the start colour is lifted and the gradient
    divides it back out after the head. accept(h, sat) selects which start colours get the hot head."""
    sc = im['startColor']
    if sc['minMaxState'] not in (0, 2):
        return False
    cols = [sc['maxColor']] + ([sc['minColor']] if sc['minMaxState'] == 2 else [])
    rgb = np.mean([[c['r'], c['g'], c['b']] for c in cols], 0)
    if rgb.max() <= 1e-3:
        return False
    h, sat, v = colorsys.rgb_to_hsv(*np.clip(rgb / max(rgb.max(), 1.0), 0, 1))
    if not accept(h, sat):
        return False                      # only red particles get the hot head (Hidan)
    for c in cols:
        for ch in 'rgb':
            c[ch] = float(min(1.0, c[ch] * (1 - lift) + lift * max(rgb.max(), 1e-3)))
    hot = np.mean([[c['r'], c['g'], c['b']] for c in cols], 0)
    ratio = rgb / np.maximum(hot, 1e-4)
    for g in grads:
        keys = get_colors(g)
        times = sorted(set([k[0] for k in keys] + [head_t]))
        new = []
        for t in times:
            u = min(1.0, t / head_t)
            u = u * u * (3 - 2 * u)
            r = 1.0 + (ratio - 1.0) * u
            new.append((t, tuple(interp_col(keys, t) * r)))
        set_colors(g, simplify(new, 8, interp_col))
    return True


# ------------------------------------------------------------------ MinMaxCurve helpers
def mm_max(c):
    st = c['minMaxState']
    if st == 0:
        return c['scalar']
    if st == 3:
        return max(c['scalar'], c['minScalar'])
    curves = [c['maxCurve']['m_Curve']] + ([c['minCurve']['m_Curve']] if st == 2 else [])
    vals = [k['value'] for cv in curves for k in cv] or [1.0]
    return c['scalar'] * max(vals)


def mm_scale(c, f):
    c['scalar'] = float(c['scalar'] * f)
    c['minScalar'] = float(c['minScalar'] * f)


def burst_alive(b, life):
    cnt = mm_max(b['countCurve']) if 'countCurve' in b else b.get('maxCount', 0)
    cycles = b.get('cycleCount', 1)
    interval = max(b.get('repeatInterval', 0.01), 0.01)
    alive_cycles = math.ceil(life / interval) if cycles == 0 else min(cycles, math.ceil(life / interval) + 1)
    return cnt * max(1, alive_cycles)


def scale_bursts(em, f):
    for b in em['m_Bursts']:
        if 'countCurve' in b:
            c = b['countCurve']
            c['scalar'] = float(max(1, round(c['scalar'] * f)))
            c['minScalar'] = float(max(1, round(c['minScalar'] * f)))
        else:
            b['minCount'] = max(1, int(round(b['minCount'] * f)))
            b['maxCount'] = max(1, int(round(b['maxCount'] * f)))


# ------------------------------------------------------------------ main per-system pass
def process_particle_system(tt, go_name, palette='crimson', budget=PARTICLE_BUDGET):
    """palette 'crimson' (Hidan): crimson tails + red hot heads; any other palette: fades/optimisation only."""
    rep = {'fade_in': 0, 'fade_out': 0, 'polish': 0, 'hot_head': 0, 'noise_low': 0, 'emit_scaled': 0, 'max_capped': 0}
    im, em, cm = tt['InitialModule'], tt['EmissionModule'], tt['ColorModule']
    life = max(mm_max(im['startLifetime']), 0.02)

    # ---- fades (colour over lifetime)
    if not cm['enabled']:
        cm['enabled'] = True
        gr = cm['gradient']
        gr['minMaxState'] = 1
        g = gr['maxGradient']
        set_colors(g, [(0.0, (1.0, 1.0, 1.0)), (1.0, (1.0, 1.0, 1.0))])
        set_alpha(g, [(0.0, 1.0), (1.0, 1.0)])
    gr = cm['gradient']
    grads = [gr['maxGradient']] + ([gr['minGradient']] if gr['minMaxState'] == 3 else [])
    if gr['minMaxState'] in (0, 2):
        # constant / two constants -> equivalent gradient(s) so an envelope can be applied
        cols = [gr['maxColor']] + ([gr['minColor']] if gr['minMaxState'] == 2 else [])
        gr['minMaxState'] = 1 if len(cols) == 1 else 3
        targets = [gr['maxGradient']] + ([gr['minGradient']] if len(cols) == 2 else [])
        for g, c in zip(targets, cols):
            set_colors(g, [(0.0, (c['r'], c['g'], c['b'])), (1.0, (c['r'], c['g'], c['b']))])
            set_alpha(g, [(0.0, c['a']), (1.0, c['a'])])
        grads = targets
    hot = any(w in go_name.lower() for w in SPARK_WORDS) and life < 1.2
    for g in grads:
        before = get_alpha(g)
        new, ch = fade_keys(before, life)
        if ch:
            rep['fade_in'] += interp(before, 0.0) > 0.02
            rep['fade_out'] += interp(before, 1.0) > 0.02
            set_alpha(g, new)
        if palette == 'crimson' and polish_colors(g, hot):
            rep['polish'] += 1
    if palette == 'crimson' and hot and hot_head(im, grads):
        rep['hot_head'] = 1

    # ---- noise: medium/high (2D/3D) -> low (1D) quality
    nm = tt['NoiseModule']
    if nm['enabled'] and nm.get('quality', 0) != 0:
        nm['quality'] = 0
        rep['noise_low'] = 1

    # ---- particle budget
    if em['enabled']:
        rate = mm_max(em['rateOverTime'])
        alive = rate * life + sum(burst_alive(b, life) for b in em['m_Bursts'])
        if alive > budget:
            f = max(MIN_EMIT_FACTOR, (budget / alive) ** EMIT_EXPONENT)
            mm_scale(em['rateOverTime'], f)
            mm_scale(em['rateOverDistance'], f)
            scale_bursts(em, f)
            comp = min(1.22, f ** -0.18)
            for k in ('startSize', 'startSizeY', 'startSizeZ'):
                if k in im:
                    mm_scale(im[k], comp)
            rep['emit_scaled'] = 1
            alive *= f
        cap = int(math.ceil(alive * 1.4)) + 6
        if im['maxNumParticles'] > cap:
            im['maxNumParticles'] = cap
            rep['max_capped'] = 1
    return rep


# ------------------------------------------------------------------ legacy effect clips: alpha pop-in
ALPHA_ATTRS = ('._TintColor.a', '._Color.a', '._DiffuseColor.a', '._MainColor.a')


def _key(t, v):
    return {'time': float(t), 'value': float(v), 'inSlope': 0.0, 'outSlope': 0.0, 'weightedMode': 0,
            'inWeight': 0.3333333432674408, 'outWeight': 0.3333333432674408}


def fade_legacy_clip(tt, fade=0.06):
    """Material alpha curves that start fully visible get a short ramp from the moment the object shows."""
    changed = 0
    if 'off' in tt['m_Name'].lower():
        return 0                      # turn-off clips start from an already visible state
    active_at = {}
    for fc in tt['m_FloatCurves']:
        if fc['attribute'] == 'm_IsActive':
            ks = fc['curve']['m_Curve']
            on = [k['time'] for k in ks if k['value'] > 0.5]
            if on:
                active_at[fc['path']] = on[0]
    for fc in tt['m_FloatCurves']:
        if not fc['attribute'].startswith('material.') or not fc['attribute'].endswith(ALPHA_ATTRS):
            continue
        ks = sorted(fc['curve']['m_Curve'], key=lambda k: k['time'])
        if not ks:
            continue
        t_show = active_at.get(fc['path'], ks[0]['time'])
        def val(t):
            if t <= ks[0]['time']:
                return ks[0]['value']
            for a, b in zip(ks, ks[1:]):
                if a['time'] <= t <= b['time']:
                    u = (t - a['time']) / max(b['time'] - a['time'], 1e-6)
                    return a['value'] + (b['value'] - a['value']) * u
            return ks[-1]['value']
        v0 = val(t_show)
        if v0 <= 0.05:
            continue
        t1 = t_show + fade
        v1 = val(t1)
        new = [_key(k['time'], 0.0) for k in ks if k['time'] < t_show - 1e-4]
        new.append(_key(t_show, 0.0))
        new.append(_key(t1, v1))
        new += [k for k in ks if k['time'] > t1 + 1e-4]
        # linear-ish tangents for the inserted ramp
        new_sorted = sorted(new, key=lambda k: k['time'])
        for i, k in enumerate(new_sorted):
            if abs(k['time'] - t_show) < 1e-6 or abs(k['time'] - t1) < 1e-6:
                slope_out = (new_sorted[i + 1]['value'] - k['value']) / max(new_sorted[i + 1]['time'] - k['time'], 1e-6) if i + 1 < len(new_sorted) else 0.0
                slope_in = (k['value'] - new_sorted[i - 1]['value']) / max(k['time'] - new_sorted[i - 1]['time'], 1e-6) if i > 0 else 0.0
                k['inSlope'], k['outSlope'] = float(slope_in), float(slope_out)
        fc['curve']['m_Curve'] = new_sorted
        changed += 1
    return changed


# ================================================================== v3: smoother particles
def _ss(u):
    return u * u * (3 - 2 * u)


def ease_ramps(keys):
    """Turn the linear fade-in (first ramp) and fade-out (last ramp) into smooth S-curves."""
    k = sorted(keys)
    out = list(k)
    if len(k) >= 2 and k[0][0] <= 1e-4 and k[0][1] <= 0.02 and k[1][1] > k[0][1] + 0.05 and k[1][0] > 0.04:
        t1, a1 = k[1]
        out += [(t1 * 0.3, a1 * _ss(0.3)), (t1 * 0.7, a1 * _ss(0.7))]
    if len(k) >= 2 and k[-1][0] >= 0.9999 and k[-1][1] <= 0.02 and k[-2][1] > k[-1][1] + 0.05 and 1 - k[-2][0] > 0.04:
        t0, a0 = k[-2]
        span = 1 - t0
        out += [(t0 + span * 0.3, a0 * (1 - _ss(0.3))), (t0 + span * 0.7, a0 * (1 - _ss(0.7)))]
    out = sorted(set((round(t, 5), a) for t, a in out))
    return simplify(out, 8)


def _curve_key(t, v, s_in=0.0, s_out=0.0):
    return {'time': float(t), 'value': float(v), 'inSlope': float(s_in), 'outSlope': float(s_out),
            'weightedMode': 0, 'inWeight': 0.3333333432674408, 'outWeight': 0.3333333432674408}


def taper_size(sm):
    """Spark-like particles: size eases down to ~45 % at death (clean, defined tails)."""
    curves = [sm['curve']] + ([sm['y'], sm['z']] if sm.get('separateAxes') else [])
    if not sm['enabled']:
        sm['enabled'] = True
        for c in curves:
            c['minMaxState'] = 1
            c['scalar'] = 1.0
            c['maxCurve']['m_Curve'] = [_curve_key(0.0, 0.75, 0, 2.2), _curve_key(0.15, 1.0, 0.0, 0.0),
                                        _curve_key(1.0, 0.45, -0.9, -0.9)]
        return True
    changed = False
    for c in curves:
        if c['minMaxState'] != 1:
            continue
        ks = c['maxCurve']['m_Curve']
        if len(ks) < 2:
            continue
        peak = max(k['value'] for k in ks)
        if ks[-1]['time'] >= 0.999 and ks[-1]['value'] > 0.55 * peak:
            ks[-1]['value'] = float(0.5 * ks[-1]['value'])
            prev = ks[-2]
            slope = (ks[-1]['value'] - prev['value']) / max(ks[-1]['time'] - prev['time'], 1e-3)
            ks[-1]['inSlope'] = float(slope); ks[-1]['outSlope'] = float(slope)
            changed = True
    return changed


def _mm_const(v):
    return {'minMaxState': 0, 'scalar': float(v), 'minScalar': float(v),
            'maxCurve': {'m_Curve': [], 'm_PreInfinity': 2, 'm_PostInfinity': 2, 'm_RotationOrder': 4},
            'minCurve': {'m_Curve': [], 'm_PreInfinity': 2, 'm_PostInfinity': 2, 'm_RotationOrder': 4}}


def spark_drag(tt):
    """Fast spark-like particles decelerate smoothly (drag) instead of flying at constant speed."""
    cv = tt['ClampVelocityModule']
    if cv['enabled']:
        return False
    im = tt['InitialModule']
    if mm_max(im['startSpeed']) < 2.5:
        return False
    cv['enabled'] = True
    cv['separateAxis'] = False
    cv['inWorldSpace'] = False
    for key in ('magnitude', 'x', 'y', 'z'):
        if key in cv and isinstance(cv[key], dict):
            cv[key]['minMaxState'] = 0
            cv[key]['scalar'] = 1000.0
            cv[key]['minScalar'] = 1000.0
    cv['dampen'] = 0.0
    keep = cv['drag']['maxCurve'], cv['drag']['minCurve']
    cv['drag'] = _mm_const(1.6)
    cv['drag']['maxCurve'], cv['drag']['minCurve'] = keep
    cv['multiplyDragByParticleSize'] = False
    cv['multiplyDragByParticleVelocity'] = False
    mm_scale(im['startSpeed'], 1.22)      # same reach, faster burst, smooth slow-down
    return True


def process_particle_system_v3(tt, go_name, render_mode=None, palette='crimson', budget=PARTICLE_BUDGET):
    rep = process_particle_system(tt, go_name, palette, budget)
    rep.update({'s_curve': 0, 'size_taper': 0, 'drag': 0})
    cm = tt['ColorModule']
    gr = cm['gradient']
    grads = [gr['maxGradient']] + ([gr['minGradient']] if gr['minMaxState'] == 3 else [])
    for g in grads:
        before = get_alpha(g)
        after = ease_ramps(before)
        if after != before:
            set_alpha(g, after)
            rep['s_curve'] += 1
    life = max(mm_max(tt['InitialModule']['startLifetime']), 0.02)
    spark = any(w in go_name.lower() for w in SPARK_WORDS) and life < 1.2
    billboard = render_mode in (0, 1)        # 0 billboard, 1 stretched; never mesh/horizontal decals
    if spark and billboard:
        rep['size_taper'] = int(taper_size(tt['SizeModule']))
        rep['drag'] = int(spark_drag(tt))
    return rep


# ================================================================== v3: smooth legacy effect curves
def smooth_legacy_tangents(tt):
    """Material colour/alpha curves of mesh effects get clamped-auto tangents (no linear corners)."""
    n = 0
    for fc in tt['m_FloatCurves']:
        a = fc['attribute']
        if not (a.startswith('material.') and a[-2:] in ('.r', '.g', '.b', '.a')):
            continue
        ks = sorted(fc['curve']['m_Curve'], key=lambda k: k['time'])
        if len(ks) < 3:
            continue
        for i in range(1, len(ks) - 1):
            p, c, nx = ks[i - 1], ks[i], ks[i + 1]
            if (c['value'] - p['value']) * (nx['value'] - c['value']) <= 0:
                s = 0.0                          # local extreme or plateau: flat tangent, no overshoot
            else:
                s = (nx['value'] - p['value']) / max(nx['time'] - p['time'], 1e-6)
            c['inSlope'] = c['outSlope'] = float(s)
        ks[0]['outSlope'] = ks[0]['inSlope'] = 0.0
        ks[-1]['inSlope'] = ks[-1]['outSlope'] = 0.0
        fc['curve']['m_Curve'] = ks
        n += 1
    return n
