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

# --- model texture orientation/content check: decoded (via UnityPy, which un-flips) must match revamp(original)
import numpy as np
import model_tex
for mb in ('Art/Android/h/hero_argus_skin.unity3d', 'Art/Android/h/hero_argus_skin_high_add.unity3d'):
    eo, en = UnityPy.load(os.path.join(orig_root, mb)), UnityPy.load(os.path.join(new_root, mb))
    src = [o.read().image for o in eo.objects if o.type.name == 'Texture2D'][0]
    got = [o.read().image for o in en.objects if o.type.name == 'Texture2D'][0]
    want = np.asarray(model_tex.revamp(src).convert('RGB'), np.float32)
    have = np.asarray(got.convert('RGB'), np.float32)
    err = np.abs(want - have).mean()
    flip_err = np.abs(want[::-1] - have).mean()
    print(f'TEXTURE {mb}: mean abs err {err:.2f} (flipped {flip_err:.2f})', 'OK' if err < 6 and err < flip_err else 'BAD')
