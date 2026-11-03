import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import UnityPy
from vfx_fix import mm_max, get_alpha
from effect_timing import ps_end
RM = {0: 'bill', 1: 'stretch', 2: 'horiz', 3: 'vert', 4: 'MESH', 5: 'none'}
def dump(path):
    env = UnityPy.load(path); objs = {o.path_id: o for o in env.objects}
    rmode = {}
    for o in env.objects:
        if o.type.name == 'ParticleSystemRenderer':
            t = o.read_typetree(); rmode[t['m_GameObject']['m_PathID']] = t['m_RenderMode']
    for o in env.objects:
        if o.type.name == 'MonoBehaviour':
            try:
                tt = o.read_typetree()
                if 'DelayTime' in tt: print('  DelayTime', round(tt['DelayTime'], 3))
            except Exception: pass
    rows = []
    for o in env.objects:
        if o.type.name != 'ParticleSystem': continue
        tt = o.read_typetree(); gid = tt['m_GameObject']['m_PathID']; go = objs[gid].read_typetree()
        im = tt['InitialModule']; sm = tt['SizeModule']
        size_curve = [(round(k['time'], 2), round(k['value'], 2)) for k in sm['curve']['maxCurve']['m_Curve']] if sm['enabled'] and sm['curve']['minMaxState'] == 1 else ('-' if not sm['enabled'] else 'state%d' % sm['curve']['minMaxState'])
        delay = mm_max(tt['startDelay']) if isinstance(tt['startDelay'], dict) else tt['startDelay']
        rows.append((round(delay, 2), go['m_Name'][:30], RM.get(rmode.get(gid), '?'), go['m_IsActive'], tt['looping'], round(tt['lengthInSec'], 2),
                     round(mm_max(im['startLifetime']), 2), round(mm_max(im['startSize']), 2), round(mm_max(im['startSpeed']), 1),
                     round(ps_end(tt) or -1, 2), [(round(a, 2), round(b, 2)) for a, b in get_alpha(tt['ColorModule']['gradient']['maxGradient'])], size_curve,
                     'VOL' if tt['VelocityModule']['enabled'] else '', 'LIM' if tt['ClampVelocityModule']['enabled'] else '', 'NOISE' if tt['NoiseModule']['enabled'] else '', 'FORCE' if tt['ForceModule']['enabled'] else ''))
    for r in sorted(rows):
        print('  delay=%s %-30s %-7s act=%s loop=%s dur=%s life=%s size=%s speed=%s end=%s' % r[:10])
        print('        alpha=%s size=%s %s %s %s %s' % r[10:])
for p in sys.argv[1:]:
    print('==', os.path.basename(p)); dump(p)
