"""Renderer bounds of the Hidan model that cover every animation frame (+ crimson fresnel on the last blue layer).

The model's SkinnedMeshRenderers ('noraml', 'ulti') keep their bounds relative to the root bone (hidan_00) and do not
update them off screen. The stored boxes were too small for the animations: attacks swing the scythe 1-1.4 m
outside them, the scythe throw of skill 1 flies 6 m outside, the ritual form ('ulti') has the tightest box. Unity
culls a renderer whose bounds leave the screen, so a Hidan just outside the screen lost the scythe that was still
flying into it. New bounds: every vertex of every clip (sampled at 30 fps, plus the bind pose) in root-bone space,
plus 5 cm. Both model bundles get the same boxes.

The one effect layer that still had a blue rim (fresnel '_Fr_color' of FX_M_126_skin02_ZXD_201, a layer of another
skin merged into skill 2 since v5) gets Hidan's crimson at the same intensity.

usage: python skin_bounds.py <HIDAN dir, modified in place>
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import numpy as np
import UnityPy
from fk import Rig, clip_overrides

BUNDLES = ('hero_argus_skin.unity3d', 'hero_argus_skin_high_add.unity3d')
MARGIN = 0.05
FPS = 30
CRIMSON = (1.0, 0.10, 0.14)


def frames(rig):
    yield {}
    for o in rig.env.objects:
        if o.type.name != 'AnimationClip':
            continue
        tt = o.read_typetree()
        mc = tt.get('m_MuscleClip', {})
        dur = max(mc.get('m_StopTime', 1.0) - mc.get('m_StartTime', 0.0), 0.0)
        n = max(2, int(np.ceil(dur * FPS)) + 1)
        ovs, _ = clip_overrides(rig, tt, np.linspace(0.0, dur, n))
        yield from ovs


def anim_bounds(path):
    rig = Rig(path)
    smr = {}
    for o in rig.env.objects:
        if o.type.name == 'SkinnedMeshRenderer':
            st = o.read_typetree()
            if st['m_Mesh']['m_PathID']:
                smr[rig.objs[st['m_Mesh']['m_PathID']].read_typetree()['m_Name']] = (o, st)
    lo = {k: np.full(3, np.inf) for k in smr}
    hi = {k: np.full(3, -np.inf) for k in smr}
    for ov in frames(rig):
        W = rig.pose(ov)
        for s in rig.smrs:
            o, st = smr[s['name']]
            P = rig.skin(s, W)
            rb = st['m_RootBone']['m_PathID']
            L = (np.c_[P, np.ones(len(P))] @ np.linalg.inv(W[rb]).T)[:, :3] if rb else P
            lo[s['name']] = np.minimum(lo[s['name']], L.min(0))
            hi[s['name']] = np.maximum(hi[s['name']], L.max(0))
    return {k: (lo[k] - MARGIN, hi[k] + MARGIN) for k in smr}


def fix_fresnel(root):
    n = 0
    for dp, dn, fn in os.walk(os.path.join(root, 'Art')):
        for f in fn:
            if not f.endswith('.unity3d') or f.startswith(('hero_', 'heroshow', 'Hero45')) or 'Atlas' in f:
                continue
            path = os.path.join(dp, f)
            env = UnityPy.load(path)
            changed = False
            for o in env.objects:
                if o.type.name != 'Material':
                    continue
                tt = o.read_typetree()
                for k, c in tt['m_SavedProperties']['m_Colors']:
                    if k == '_Fr_color' and c['b'] > 0.5 and c['r'] < 0.2:
                        m = max(c['r'], c['g'], c['b'])
                        c['r'], c['g'], c['b'] = (m * x for x in CRIMSON)
                        changed = True
                        n += 1
                if changed:
                    o.save_typetree(tt)
            if changed:
                with open(path, 'wb') as fh:
                    fh.write(env.file.save(packer='original'))
    return n


def main():
    root = sys.argv[1]
    hdir = os.path.join(root, 'Art', 'Android', 'h')
    boxes = anim_bounds(os.path.join(hdir, BUNDLES[0]))
    for b in BUNDLES:
        path = os.path.join(hdir, b)
        env = UnityPy.load(path)
        objs = {o.path_id: o for o in env.objects}
        for o in env.objects:
            if o.type.name != 'SkinnedMeshRenderer':
                continue
            st = o.read_typetree()
            if not st['m_Mesh']['m_PathID']:
                continue
            name = objs[st['m_Mesh']['m_PathID']].read_typetree()['m_Name']
            lo, hi = boxes[name]
            old = st['m_AABB']
            c, e = (lo + hi) / 2, (hi - lo) / 2
            st['m_AABB'] = {'m_Center': dict(zip('xyz', map(float, c))), 'm_Extent': dict(zip('xyz', map(float, e)))}
            o.save_typetree(st)
            print(f'{b} {name}: extent {[round(old["m_Extent"][k], 2) for k in "xyz"]} -> {np.round(e, 2).tolist()}')
        with open(path, 'wb') as fh:
            fh.write(env.file.save(packer='original'))
    print('blue fresnel colours made crimson:', fix_fresnel(root))


if __name__ == '__main__':
    main()
