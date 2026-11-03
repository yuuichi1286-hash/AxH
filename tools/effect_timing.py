"""Per effect bundle: EffComponent.ParticleSysMgr DelayTime vs when the last particle has fully faded."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import UnityPy
from vfx_fix import mm_max

def mm_min(c):
    st = c['minMaxState']
    if st == 0: return c['scalar']
    if st == 3: return min(c['scalar'], c['minScalar'])
    return 0.0

def ps_end(tt):
    """seconds after effect start when this system's last particle dies (non-looping); None if looping."""
    if tt['looping']:
        return None
    delay = mm_max(tt['startDelay']) if isinstance(tt['startDelay'], dict) else float(tt['startDelay'])
    life = mm_max(tt['InitialModule']['startLifetime'])
    em = tt['EmissionModule']
    last_emit = 0.0
    if em['enabled']:
        if mm_max(em['rateOverTime']) > 0:
            last_emit = tt['lengthInSec']
        for b in em['m_Bursts']:
            cyc = b.get('cycleCount', 1) or 1
            last_emit = max(last_emit, b['time'] + (cyc - 1) * b.get('repeatInterval', 0.0))
    return delay + min(last_emit, tt['lengthInSec']) + life

def legacy_clip_len(tt):
    t = 0.0
    for group in ('m_FloatCurves', 'm_PositionCurves', 'm_ScaleCurves', 'm_EulerCurves', 'm_RotationCurves'):
        for c in tt.get(group, []):
            ks = c['curve']['m_Curve']
            if ks: t = max(t, ks[-1]['time'])
    return t

def analyse(path):
    env = UnityPy.load(path)
    objs = {o.path_id: o for o in env.objects}
    mgr = None; ends = []; loops = 0
    for o in env.objects:
        n = o.type.name
        if n == 'MonoBehaviour':
            try:
                tt = o.read_typetree()
                if 'DelayTime' in tt: mgr = tt
            except Exception:
                pass
        elif n == 'ParticleSystem':
            tt = o.read_typetree()
            go = objs[tt['m_GameObject']['m_PathID']].read_typetree()
            e = ps_end(tt)
            if e is None: loops += 1
            elif go['m_IsActive']: ends.append((e, go['m_Name']))
        elif n == 'AnimationClip':
            tt = o.read_typetree()
            if tt['m_Legacy']: ends.append((legacy_clip_len(tt), 'clip:' + tt['m_Name']))
    ends.sort(reverse=True)
    return mgr, ends, loops

if __name__ == '__main__':
    root = sys.argv[1]
    for dp, dn, fn in sorted(os.walk(root)):
        for f in sorted(fn):
            if not f.endswith('.unity3d') or f.startswith('hero_') or f.startswith('heroshow') or 'Atlas' in f or f.startswith('Hero45'): continue
            mgr, ends, loops = analyse(os.path.join(dp, f))
            dt = mgr['DelayTime'] if mgr else None
            last = ends[0] if ends else (0, '-')
            flag = 'CUT' if (dt is not None and dt < 7000 and last[0] > dt + 1e-3) else ''
            print(f"{f[:58]:58s} Delay={dt if dt is None else round(dt, 2):>7} lastFade={last[0]:6.2f} ({last[1][:28]}) loops={loops} {flag}")
