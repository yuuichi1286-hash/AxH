"""Reload every output bundle, re-read every object, compare against the original bundle."""
import sys, os, collections, hashlib
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import UnityPy
from validate_clips import check as check_clips
orig_root, new_root = sys.argv[1], sys.argv[2]
problems = 0; changed = 0; same = 0
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
        if co != cn:
            print('OBJECT SET DIFFERS', rel); problems += 1
        mo = {o.path_id: o for o in eo.objects}
        nchg = collections.Counter()
        for o in en.objects:
            try:
                tn = o.read_typetree()
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
print(f'\nunchanged files: {same}, changed: {changed}, problems: {problems}')

# --- model checks: texture orientation/content and tessellated meshes
import numpy as np
import model_tex
from meshio import decode
SIZES = {'Art/Android/h/hero_argus_skin.unity3d': 1024, 'Art/Android/h/hero_argus_skin_high_add.unity3d': 2048}
for mb, size in SIZES.items():
    eo, en = UnityPy.load(os.path.join(orig_root, mb)), UnityPy.load(os.path.join(new_root, mb))
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
    err = np.abs(want - have).mean(); flip_err = np.abs(want[::-1] - have).mean()
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
