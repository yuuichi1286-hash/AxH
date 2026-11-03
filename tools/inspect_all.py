import sys, os, collections
import UnityPy
root = sys.argv[1]
for dp, dn, fn in sorted(os.walk(root)):
    for f in sorted(fn):
        p = os.path.join(dp, f)
        try:
            env = UnityPy.load(p)
        except Exception as e:
            print("ERR", p, e); continue
        cnt = collections.Counter()
        names = collections.defaultdict(list)
        ver = None; tt = None; comp=None
        for k, fobj in env.files.items():
            comp = getattr(fobj, 'signature', None)
            try:
                for kk, ff in fobj.files.items():
                    if hasattr(ff, 'unity_version'):
                        ver = ff.unity_version
                        tt = getattr(ff, '_enable_type_tree', None)
            except Exception: pass
        for obj in env.objects:
            t = obj.type.name
            cnt[t] += 1
            if t in ("Texture2D","Mesh","AnimationClip","GameObject","Material","Shader","AnimatorController","Sprite","AudioClip"):
                try:
                    d = obj.peek_name() if hasattr(obj,'peek_name') else None
                except Exception:
                    d = None
                names[t].append(d)
        rel = os.path.relpath(p, root)
        print(f"== {rel} [{os.path.getsize(p)}] ver={ver} sig={comp} tt={tt}")
        print("   ", dict(cnt))
        for t in ("Mesh","Texture2D","AnimationClip","Shader","AnimatorController","AudioClip"):
            if names.get(t):
                print(f"    {t}: {names[t][:40]}")
