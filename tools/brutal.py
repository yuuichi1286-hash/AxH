"""Shisui x Suyou: bigger, brutal, thunderous effects with cinematic fades (dark-green palette).

Roles come from the particle GameObject names (pinyin): dg = slash (dao guang), shandian = lightning,
lizi = sparks, shitou / sui = debris, heiyan / andi / an = dark under-layers, yan / smoke = smoke,
huo / fire = flames, dilie = ground cracks, quan / huan / ring = shock rings, glow / guang = flashes,
qiliu / juan / flow = air flow, trail / guiji / xian = trails.

Per role (combat effects only; showcase, screen-space UI and skill-area indicators are never scaled)
  size    start size multiplier (bigger, heavier hits)
  speed   start speed multiplier (debris / sparks fly further and faster)
  burst   more particles for sparks, debris, lightning and flames (single-mesh bursts are never duplicated)
  life    longer, cinematic decay
  whip    starts at this fraction of the size and snaps to full size in the first 14 % of life
  expand  grows by this factor while it fades (shockwave / bloom feel)
  peak    alpha plateau multiplier
  t_out   start of the long S-curve fade-out (fraction of life)
  end     colour multiplier at the end of life: everything cools down into deep, dark green
  hot     white-mint flash at birth (lift towards white) that settles into the green after 16 % of life
"""
import math
import re
from vfx_fix import mm_max, mm_scale, scale_bursts, burst_alive, hot_head
from cinematic import reshape_size, reshape_alpha, darken_end, add_rise, add_gravity

KEEP_WORDS = ('xielunyan', 'wanhuatong', 'xue', 'mutou', 'feibiao', 'ink', 'zifu')

#              size  speed burst  life  whip  expand peak  t_out end_rgb               hot
PROFILE = {
    'slash':      (1.15, 1.00, 1.00, 1.15, 0.86, 1.12, 1.00, 0.50, (0.40, 0.80, 0.55), 0.35),
    'slash_dark': (1.15, 1.00, 1.00, 1.20, 0.90, 1.15, 1.00, 0.45, (0.30, 0.60, 0.42), 0.00),
    'lightning':  (1.30, 1.00, 1.25, 1.00, 1.00, 1.00, 1.00, 0.55, None,               0.50),
    'flash':      (1.30, 1.00, 1.00, 1.05, 0.85, 1.18, 1.00, 0.45, (0.45, 0.80, 0.58), 0.45),
    'spark':      (1.15, 1.25, 1.40, 1.10, 1.00, 1.00, 1.00, 0.55, (0.55, 0.85, 0.62), 0.40),
    'debris':     (1.20, 1.20, 1.35, 1.10, 1.00, 1.00, 1.00, 0.60, None,               0.00),
    'dark':       (1.20, 1.00, 1.00, 1.20, 1.00, 1.12, 0.95, 0.40, (0.30, 0.55, 0.40), 0.00),
    'smoke':      (1.25, 1.00, 1.00, 1.25, 1.00, 1.25, 0.90, 0.40, (0.25, 0.50, 0.35), 0.00),
    'flame':      (1.20, 1.10, 1.15, 1.10, 1.00, 1.10, 1.00, 0.45, (0.35, 0.70, 0.48), 0.30),
    'crack':      (1.25, 1.00, 1.00, 1.35, 1.00, 1.04, 1.00, 0.40, (0.35, 0.65, 0.45), 0.00),
    'ring':       (1.30, 1.00, 1.00, 1.10, 0.90, 1.15, 1.00, 0.45, (0.40, 0.75, 0.52), 0.30),
    'flow':       (1.15, 1.00, 1.00, 1.10, 1.00, 1.08, 1.00, 0.45, None,               0.00),
    'trail':      (1.00, 1.00, 1.00, 1.15, 1.00, 1.00, 1.00, 0.50, None,               0.00),
    'mesh':       (1.12, 1.00, 1.00, 1.10, 0.92, 1.08, 1.00, 0.50, (0.40, 0.78, 0.55), 0.00),
    'other':      (1.12, 1.00, 1.00, 1.05, 1.00, 1.00, 1.00, 0.50, None,               0.00),
}
MAX_ALIVE_AFTER_BURST = 60


def tokens(name):
    return [t for t in re.split(r'[^a-z0-9]+', (name or '').lower()) if t]


def role(name, render_mode):
    tk = tokens(name)

    def sub(*roots):
        return any(r in t for t in tk for r in roots)

    def pre(*roots):
        return any(t.startswith(r) for t in tk for r in roots)

    if pre(*KEEP_WORDS):
        return 'keep'
    if sub('shandian', 'lightning', 'leidian'):
        return 'lightning'
    if tk and tk[0] in ('dg', 'daoguang'):
        return 'slash_dark' if (pre('an', 'blend', 'bl', 'hei')) else 'slash'
    if pre('shitou', 'sui', 'stone'):
        return 'debris'
    if sub('lizi', 'lzii', 'spark') or pre('xing', 'star', 'ci', 'dian'):
        return 'spark'
    if sub('heiyan', 'heici', 'andi', 'anse', 'yingzi') or 'an' in tk:
        return 'dark'
    if sub('fire', 'flame', 'penyan', 'jianhuo') or pre('huo'):
        return 'flame'
    if sub('smoke', 'kuwu', 'yanwu') or pre('yan', 'wu'):
        return 'smoke'
    if sub('dilie', 'crack'):
        return 'crack'
    if sub('ring') or pre('quan', 'huan', 'wave'):
        return 'ring'
    if sub('glow', 'guang', 'baodian', 'flash', 'light', 'liang') or pre('shan', 'qiu', 'hit'):
        return 'flash'
    if sub('qiliu', 'flow', 'niuqu', 'zhuanchang') or pre('juan'):
        return 'flow'
    if sub('trail', 'guiji', 'xian') or pre('tuo'):
        return 'trail'
    return 'mesh' if render_mode == 4 else 'other'


def bundle_class(filename):
    f = filename.lower()
    if 'cityaction' in f or 'skill03_ui' in f or '_egg' in f:
        return 'show'          # lobby showcase, screen-space ultimate cut-in, easter egg: colour + fades only
    if 'warning' in f:
        return 'indicator'     # shows the real skill area: colour + fades, never scaled
    return 'combat'


def _alive(tt):
    em = tt['EmissionModule']
    if not em['enabled']:
        return 0.0
    life = max(mm_max(tt['InitialModule']['startLifetime']), 0.02)
    return mm_max(em['rateOverTime']) * life + sum(burst_alive(b, life) for b in em['m_Bursts'])


def _always(h, s):
    return True


def apply(tt, go_name, render_mode, cls, profile=None, role_fn=None):
    """-> (role, {what was done}); profile / role_fn replace PROFILE / role() (Hidan uses a crimson profile)"""
    r = (role_fn or role)(go_name, render_mode)
    if r == 'keep' or cls != 'combat':
        return r, {}
    size, speed, burst, life_mul, whip, expand, peak, t_out, end_rgb, hot = (profile or PROFILE)[r]
    im, em = tt['InitialModule'], tt['EmissionModule']
    done = {}
    # ---- bigger / heavier
    if size != 1.0:
        for k in ('startSize', 'startSizeY', 'startSizeZ'):
            if k in im and isinstance(im[k], dict):
                mm_scale(im[k], size)
        done['size'] = size
    if speed != 1.0 and mm_max(im['startSpeed']) > 0.05:
        mm_scale(im['startSpeed'], speed)
        done['speed'] = speed
    if burst != 1.0 and em['enabled']:
        alive = _alive(tt)
        f = burst if alive * burst <= MAX_ALIVE_AFTER_BURST else max(1.0, MAX_ALIVE_AFTER_BURST / max(alive, 1e-3))
        if f > 1.01:
            mm_scale(em['rateOverTime'], f)
            if any(mm_max(b['countCurve']) >= 2 for b in em['m_Bursts'] if 'countCurve' in b):
                scale_bursts_multi(em, f)
            done['burst'] = round(f, 2)
    # ---- cinematic life / size / alpha / colour shaping
    looping = bool(tt['looping'])
    if life_mul != 1.0:
        mm_scale(im['startLifetime'], life_mul)
        if looping:
            mm_scale(em['rateOverTime'], 1.0 / life_mul)
        done['life'] = life_mul
    if reshape_size(tt['SizeModule'], whip, expand):
        done['shape'] = (whip, expand)
    gr = tt['ColorModule']['gradient']
    grads = [gr['maxGradient']] + ([gr['minGradient']] if gr['minMaxState'] == 3 else [])
    if tt['ColorModule']['enabled'] and gr['minMaxState'] in (1, 3):
        for g in grads:
            reshape_alpha(g, peak, t_out)
            if end_rgb is not None:
                darken_end(g, end_rgb)
        done['fade'] = (peak, t_out)
        if hot > 0 and hot_head(im, grads, head_t=0.16, accept=_always, lift=hot):
            done['hot'] = hot
    if r == 'debris' and add_gravity(tt, 0.9):
        done['gravity'] = True
    if r == 'flame' and render_mode in (0, 1) and add_rise(tt, 1.2):
        done['rise'] = True
    # ---- particle capacity for the extra particles / longer lives
    need = int(math.ceil(_alive(tt) * 1.3)) + 2
    if im['maxNumParticles'] < need:
        im['maxNumParticles'] = need
        done['maxp'] = need
    return r, done


def scale_bursts_multi(em, f):
    """Only bursts that already emit 2+ particles get more (single-mesh bursts stay single)."""
    for b in em['m_Bursts']:
        c = b.get('countCurve')
        if c is None or mm_max(c) < 2:
            continue
        c['scalar'] = float(max(1, round(c['scalar'] * f)))
        c['minScalar'] = float(max(1, round(c['minScalar'] * f)))
