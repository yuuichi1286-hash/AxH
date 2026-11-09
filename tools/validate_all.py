"""Reload every output bundle, re-read every object, compare against the original bundle."""
import sys, os, collections, hashlib
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import UnityPy
from validate_clips import check as check_clips
orig_root, new_root = sys.argv[1], sys.argv[2]
problems = 0; changed = 0; same = 0; added_total = 0


def _pptrs(v, out):
    if isinstance(v, dict):
        if set(v) == {'m_FileID', 'm_PathID'}:
            out.append((v['m_FileID'], v['m_PathID'])); return
        for x in v.values():
            _pptrs(x, out)
    elif isinstance(v, (list, tuple)):
        for x in v:
            _pptrs(x, out)


for dp, dn, fn in os.walk(orig_root):
    for f in sorted(fn):
        po = os.path.join(dp, f); rel = os.path.relpath(po, orig_root); pn = os.path.join(new_root, rel)
        if not os.path.exists(pn):
            print('MISSING', rel); problems += 1; continue
        bo, bn = open(po, 'rb').read(), open(pn, 'rb').read()
        if bo == bn:
            same += 1; continue
        changed += 1
        if not f.endswith('.unity3d'):
            print('non-bundle changed?!', rel); problems += 1; continue
        eo, en = UnityPy.load(po), UnityPy.load(pn)
        fo = list(eo.files.values())[0]; fnn = list(en.files.values())[0]
        if (int(fo.dataflags), fo._block_info_flags, fo.version, fo.version_engine) != (int(fnn.dataflags), fnn._block_info_flags, fnn.version, fnn.version_engine):
            print('HEADER FLAGS DIFFER', rel); problems += 1
        if list(fo.files.keys()) != list(fnn.files.keys()):
            print('INTERNAL NAMES DIFFER', rel); problems += 1
        co = collections.Counter((o.type.name, o.path_id) for o in eo.objects)
        cn = collections.Counter((o.type.name, o.path_id) for o in en.objects)
        if co - cn:                                 # objects may only be added (v5: Ultra layers merged in)
            print('OBJECT SET DIFFERS', rel); problems += 1
        added_here = sum((cn - co).values()); added_total += added_here
        mo = {o.path_id: o for o in eo.objects}
        ids = {o.path_id for o in en.objects}
        nchg = collections.Counter()
        for o in en.objects:
            try:
                tn = o.read_typetree()
                if o.path_id not in mo:             # added object: readable, and every in-file reference resolves
                    refs = []; _pptrs(tn, refs)
                    bad = [p for f_, p in refs if f_ == 0 and p and p not in ids]
                    if bad:
                        print('DANGLING', rel, o.type.name, bad[:3]); problems += 1
                    nchg['added ' + o.type.name] += 1
                    continue
                to = mo[o.path_id].read_typetree()
            except Exception as e:
                print('READ FAIL', rel, o.type.name, e); problems += 1; continue
            if tn != to:
                nchg[o.type.name] += 1
                # structural check: same keys at top level
                if set(tn.keys()) != set(to.keys()):
                    print('KEYSET DIFF', rel, o.type.name); problems += 1
        errs = check_clips(pn, verbose=False) if f.startswith('hero_argus_skin') else []
        for e in errs:
            print('CLIP', rel, e); problems += 1
        print(f'{rel:70s} {len(bo):>9d} -> {len(bn):>9d}  changed objs: {dict(nchg)}')
print(f'\nunchanged files: {same}, changed: {changed}, objects added: {added_total}, problems: {problems}')

# --- model checks: texture orientation/content and tessellated meshes
import numpy as np
import model_tex
from meshio import decode
HIGH = 'Art/Android/h/hero_argus_skin_high_add.unity3d'
# v5: the base model shows the Ultra texture too, so it is checked against the High source
SIZES = {'Art/Android/h/hero_argus_skin.unity3d': (2048, HIGH), HIGH: (2048, HIGH)}
for mb, (size, src_mb) in SIZES.items():
    eo, en = UnityPy.load(os.path.join(orig_root, src_mb)), UnityPy.load(os.path.join(new_root, mb))
    uv_tris = []
    for o in eo.objects:
        if o.type.name == 'Mesh':
            d = decode(o.read_typetree())
            uv_tris.append(d['uv0'].astype(np.float64)[d['index'].reshape(-1, 3)])
    # same order as build: SkinnedMeshRenderer order (ulti, noraml) -> mask is order independent anyway
    src = [o.read().image for o in eo.objects if o.type.name == 'Texture2D'][0]
    got = [o.read() for o in en.objects if o.type.name == 'Texture2D'][0]
    want = np.asarray(model_tex.revamp(src, size, uv_tris).convert('RGB'), np.float32)
    have = np.asarray(got.image.convert('RGB'), np.float32)
    # v5.1: the detailed scythe (rigid on L_Weapon) has its own square of the atlas -> compared elsewhere
    keep = np.ones(have.shape[:2], bool)
    for o in en.objects:
        if o.type.name == 'Mesh':
            d = decode(o.read_typetree())
            names_ok = d['weights'][:, 0] > 0.999
            uv = d['uv0'][names_ok & (d['indices'][:, 0] == np.bincount(d['indices'][names_ok, 0]).argmax())][:, :2]
            if len(uv) > 500:
                x0, x1 = int(uv[:, 0].min() * size) - 24, int(np.ceil(uv[:, 0].max() * size)) + 24
                y0, y1 = int((1 - uv[:, 1].max()) * size) - 24, int(np.ceil((1 - uv[:, 1].min()) * size)) + 24
                keep[max(y0, 0):y1, max(x0, 0):x1] = False
    err = np.abs(want - have)[keep].mean(); flip_err = np.abs(want[::-1] - have)[keep].mean()
    ok = err < 6 and err < flip_err and got.m_Width == size
    print(f'TEXTURE {mb}: {got.m_Width}x{got.m_Height} mips {got.m_MipCount} mean abs err {err:.2f} (flipped {flip_err:.2f})', 'OK' if ok else 'BAD')
    for o in en.objects:
        if o.type.name != 'Mesh':
            continue
        tt = o.read_typetree(); d = decode(tt)
        nv = len(d['pos']); idx = d['index']
        good = idx.max() < nv and len(idx) % 3 == 0 and tt['m_SubMeshes'][0]['vertexCount'] == nv \
            and tt['m_SubMeshes'][0]['indexCount'] == len(idx) and np.isfinite(d['pos']).all() \
            and abs(d['weights'].sum(1) - 1).max() < 1e-3 and np.abs(np.linalg.norm(d['normal'], axis=1) - 1).max() < 1e-2
        print(f"MESH {mb} {tt['m_Name']}: verts {nv} tris {len(idx)//3}", 'OK' if good else 'BAD')

# --- effect timing: no effect may be recycled before its last particle (incl. overlays) has faded out
from effect_timing import analyse as timing_analyse
paths = {}
for dp, dn, fn in os.walk(new_root):
    for f in fn:
        if f.endswith('.unity3d'):
            paths[f[:-len('.unity3d')]] = os.path.join(dp, f)
cut = 0; checked = 0; parity_bad = 0
cache = {}
def tend(stem):
    if stem not in cache:
        mgr, e, loops = timing_analyse(paths[stem]); cache[stem] = (mgr, e[0][0] if e else 0.0)
    return cache[stem]
for stem in sorted(paths):
    if stem.startswith(('hero_', 'heroshow', 'Hero45')) or 'Atlas' in stem:
        continue
    mgr, own = tend(stem)
    if mgr:                                         # v5: same effect on Low ... Ultra
        left = [mgr['FilterInfo'][k] for k in ('strSpliteNode1', 'strSpliteNode2') if mgr['FilterInfo'].get(k)]
        low = sum(1 for e in mgr.get('ParSysInfo', []) if e['fGatherNum'] != e['fDefaultNum'])
        parity_bad += bool(left or low)
        if left or low:
            print(f'PARITY {stem}: split nodes {left}, reduced gather counts {low}')
    if not mgr or mgr['DelayTime'] >= 7000:
        continue
    last = own
    for k in ('strSpliteNode1', 'strSpliteNode2'):
        sub = mgr.get('FilterInfo', {}).get(k)
        if sub and sub in paths:
            last = max(last, tend(sub)[1])
    checked += 1
    if last > mgr['DelayTime'] + 1e-3:
        cut += 1; print(f'TIMING CUT {stem}: last fade {last:.2f} > DelayTime {mgr["DelayTime"]:.2f}')
print(f'TIMING effects checked {checked}, cut before fade end: {cut}', 'OK' if cut == 0 else 'BAD')
print(f'PARITY effects that differ between Low and Ultra: {parity_bad}', 'OK' if parity_bad == 0 else 'BAD')

# --- every particle system starts and ends invisible (fade-in + fade-out)
from vfx_fix import get_alpha, interp
n_ps = bad_ps = 0
for stem, path in sorted(paths.items()):
    if stem.startswith(('hero_', 'heroshow', 'Hero45')) or 'Atlas' in stem:
        continue
    for o in UnityPy.load(path).objects:
        if o.type.name != 'ParticleSystem':
            continue
        tt = o.read_typetree(); n_ps += 1
        gr = tt['ColorModule']['gradient']
        grads = [gr['maxGradient']] + ([gr['minGradient']] if gr['minMaxState'] == 3 else [])
        ok = tt['ColorModule']['enabled'] and gr['minMaxState'] in (1, 3) and all(
            interp(get_alpha(g), 0.0) <= 0.02 and interp(get_alpha(g), 1.0) <= 0.02 for g in grads)
        if not ok:
            bad_ps += 1; print('NO FADE', stem, o.path_id)
print(f'FADES particle systems {n_ps}, without fade-in/out: {bad_ps}', 'OK' if bad_ps == 0 else 'BAD')
