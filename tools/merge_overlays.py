"""Hidan's effects look the same on every graphics setting (Low ... Ultra).

MLBB splits an effect into a base bundle (always loaded) and up to two "split node" bundles, named in the effect's
ParticleSysMgr (FilterInfo.strSpliteNode1 / strSpliteNode2, mostly zzp1_* / zzp2_*), which the game only loads on
higher graphics settings. On Low those layers are simply missing. This pass:

* merges every split node that ships in the mod into its base effect: all of the split node's objects (game objects,
  particle systems, renderers, meshes, materials, textures, clips ...) are copied into the base bundle and its root
  is parented under the effect root, the way the game attaches a split node at run time. Textures / meshes streamed
  from the split node's .resS are stored inline; a texture the effect already holds (same pixels and sampling) is
  shared instead of stored twice. Split nodes of split nodes are merged the same way.
  The split node's own ParticleSysMgr is not copied: its lists (particle systems, renderers, trails, transforms,
  ParSysInfo ...) are appended to the base effect's ParticleSysMgr, as if the effect had been authored as one prefab.
  Part of the bundles were built with Unity 2017.4, part with 2019.4: a copied object keeps the exact type tree it was
  written with (the type is added to the base bundle when the base has no identical one), so nothing is converted.
* clears every split-node reference, also the ones pointing at bundles the mod does not ship (layers of other skins
  that only the higher settings would add), so no setting shows more or less than another;
* sets every ParSysInfo fGatherNum to fDefaultNum, so no setting runs a reduced particle count.

usage: python merge_overlays.py <HIDAN dir, modified in place> <report.json>
"""
import sys, os, copy, json, collections
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import UnityPy

SKIP_PREFIX = ('hero', 'Hero', 'Atlas')
BUILTIN = ('library/unity default resources', 'resources/unity_builtin_extra')
REFS = ('strSpliteNode1', 'strSpliteNode2')


_TT = {}          # (file, path id) -> typetree saved in this run (UnityPy re-reads the original bytes otherwise)


def _read(o):
    k = (id(o.assets_file), o.path_id)
    return copy.deepcopy(_TT[k]) if k in _TT else o.read_typetree()


def _save(o, tt):
    _TT[(id(o.assets_file), o.path_id)] = copy.deepcopy(tt)
    o.save_typetree(tt)


def _sf(env):
    bf = env.file
    return bf, next(f for f in bf.files.values() if hasattr(f, 'objects'))


def _manager(env):
    for o in env.objects:
        if o.type.name == 'MonoBehaviour':
            try:
                tt = o.read_typetree()
            except Exception:
                continue
            if 'FilterInfo' in tt and 'DelayTime' in tt:
                return o, tt
    return None, None


def _root(env):
    ab = next(o for o in env.objects if o.type.name == 'AssetBundle').read_typetree()
    pid = ab['m_Container'][0][1]['asset']['m_PathID']
    _, sf = _sf(env)
    go = sf.objects[pid].read_typetree()
    tr = next(c['component']['m_PathID'] for c in go['m_Component']
              if sf.objects[c['component']['m_PathID']].type.name == 'Transform')
    return pid, tr


def _walk_pptrs(v, fn):
    if isinstance(v, dict):
        if set(v.keys()) == {'m_FileID', 'm_PathID'}:
            return fn(v)
        return {k: _walk_pptrs(x, fn) for k, x in v.items()}
    if isinstance(v, list):
        return [_walk_pptrs(x, fn) for x in v]
    if isinstance(v, tuple):
        return tuple(_walk_pptrs(x, fn) for x in v)
    return v


def _nodes(n):
    yield n
    for c in (n.m_Children or []):
        yield from _nodes(c)


def _sig(t):
    """type identity: class, script hash and the whole type tree"""
    return (t.class_id, t.script_id, tuple((n.m_Level, n.m_Type, n.m_Name, n.m_ByteSize, n.m_Version, n.m_MetaFlag,
                                            getattr(n, 'm_TypeFlags', 0)) for n in _nodes(t.node)))


def _type_for(sfb, ot, cache):
    """index of the base type with exactly the split node's type tree, else the split node's type is appended"""
    if id(ot) in cache:
        return cache[id(ot)]
    s = _sig(ot)
    hit = [i for i, t in enumerate(sfb.types) if t.node is not None and _sig(t) == s]
    if hit:
        cache[id(ot)] = hit[0]
        return hit[0]
    nt = ot                     # the split node is loaded fresh for every merge: its type object moves over as is
    v = sfb.header.version
    if v >= 19:                                 # 2017 tree into a 2019 file: per-node ref hash field
        for n in _nodes(nt.node):
            if getattr(n, 'm_RefTypeHash', None) is None:
                n.m_RefTypeHash = 0
    if v >= 21 and nt.type_dependencies is None:
        nt.type_dependencies = ()
    if nt.is_stripped_type is None:
        nt.is_stripped_type = False
    sfb.types.append(nt)
    cache[id(ot)] = len(sfb.types) - 1
    return cache[id(ot)]


def _new_object(sf, path_id, stype, type_index, tree):
    from UnityPy.files.ObjectReader import ObjectReader
    from UnityPy.enums import ClassIDType
    obj = ObjectReader(sf, sf.reader, path_id, type_index, stype, stype.class_id, ClassIDType(stype.class_id),
                       0, 0, None, None)
    obj.save_typetree(tree, nodes=stype.node)
    sf.objects[path_id] = obj
    return obj


def _inline_stream(o, tt):
    """texture / mesh data streamed from the split node's .resS -> stored inline in the copied object"""
    sd = tt.get('m_StreamData')
    if not sd or not sd.get('path'):
        return tt
    from UnityPy.helpers.ResourceReader import get_resource_data
    data = get_resource_data(sd['path'], o.assets_file, sd['offset'], sd['size'])
    if o.type.name == 'Texture2D':
        tt['image data'] = bytes(data)
    elif o.type.name == 'Mesh':
        tt['m_VertexData']['m_DataSize'] = bytes(data)
    else:
        raise ValueError(f'streamed {o.type.name} not supported')
    tt['m_StreamData'] = {'offset': 0, 'size': 0, 'path': ''}
    return tt


_TEXIDX = {}      # id(base file) -> {texture key: path id}


def _tex_key(tt):
    """same pixels, size, format, mips, colour space and sampling -> the same texture"""
    import hashlib
    ts = tt.get('m_TextureSettings') or {}
    return (tt['m_Width'], tt['m_Height'], tt['m_TextureFormat'], tt.get('m_MipCount'), tt.get('m_ColorSpace'),
            tuple(sorted(ts.items())), hashlib.sha1(bytes(tt.get('image data') or b'')).hexdigest())


def _tex_index(sfb):
    if id(sfb) not in _TEXIDX:
        idx = {}
        for pid, o in sfb.objects.items():
            if o.type.name == 'Texture2D':
                idx.setdefault(_tex_key(_inline_stream(o, o.read_typetree())), pid)
        _TEXIDX[id(sfb)] = idx
    return _TEXIDX[id(sfb)]


def merge_into(env_b, env_o, tag):
    """copy split node env_o into base env_b under the effect root
    -> (objects added per type, the split node's ParticleSysMgr typetree with ids remapped into the base, or None)"""
    _, sfb = _sf(env_b)
    _, sfo = _sf(env_o)
    b_root_go, b_root_tr = _root(env_b)
    o_root_go, o_root_tr = _root(env_o)
    mgr_o, mgr_tt = _manager(env_o)
    drop = {mgr_o.path_id} if mgr_o else set()
    drop |= {pid for pid, o in sfo.objects.items() if o.type.name in ('AssetBundle', 'MonoScript')}
    copy_ids = [pid for pid in sorted(sfo.objects) if pid not in drop]
    for pid in copy_ids:
        if sfo.objects[pid].type.name == 'MonoBehaviour':
            raise ValueError(f'{tag}: split node has a MonoBehaviour besides its ParticleSysMgr')
    # a texture the effect already has (same pixels and sampling) is shared, not stored twice
    tex_idx = _tex_index(sfb)
    tex_tt, reuse = {}, {}
    for pid in copy_ids:
        o = sfo.objects[pid]
        if o.type.name == 'Texture2D':
            tex_tt[pid] = _inline_stream(o, o.read_typetree())
            hit = tex_idx.get(_tex_key(tex_tt[pid]))
            if hit is not None:
                reuse[pid] = hit
    copy_ids = [pid for pid in copy_ids if pid not in reuse]
    nxt = max(sfb.objects) + 1
    id_map = {pid: nxt + k for k, pid in enumerate(copy_ids)}
    id_map.update(reuse)
    ext_map = {}
    b_ext = {e.path.lower(): i + 1 for i, e in enumerate(sfb.externals)}
    for i, e in enumerate(sfo.externals):
        p = e.path.lower()
        if p not in b_ext:
            if p not in BUILTIN:
                raise ValueError(f'{tag}: split node needs {e.path}, which the base effect does not load')
            sfb.externals.append(copy.copy(e))
            b_ext[p] = len(sfb.externals)
        ext_map[i + 1] = b_ext[p]
    ext_refs = []

    def remap(p):
        fid, pid = p['m_FileID'], p['m_PathID']
        if fid == 0:
            return {'m_FileID': 0, 'm_PathID': id_map.get(pid, 0) if pid else 0}
        q = {'m_FileID': ext_map[fid], 'm_PathID': pid}
        ext_refs.append((q['m_FileID'], pid))
        return q
    cache = {}
    added = collections.Counter()
    for pid in copy_ids:
        o = sfo.objects[pid]
        tt = tex_tt[pid] if pid in tex_tt else _inline_stream(o, o.read_typetree())
        if pid in tex_tt:
            tex_idx.setdefault(_tex_key(tt), id_map[pid])
        tt = _walk_pptrs(tt, remap)
        if pid == o_root_go:                                   # its ParticleSysMgr is not copied
            tt['m_Component'] = [c for c in tt['m_Component'] if c['component']['m_PathID'] != 0]
        if pid == o_root_tr:
            tt['m_Father'] = {'m_FileID': 0, 'm_PathID': b_root_tr}
        i = _type_for(sfb, o.serialized_type, cache)
        _new_object(sfb, id_map[pid], sfb.types[i], i, tt)
        added[o.type.name] += 1
    mgr = _walk_pptrs(mgr_tt, remap) if mgr_tt else None
    # parent the split node under the effect root
    rt = sfb.objects[b_root_tr]
    t = _read(rt)
    t['m_Children'].append({'m_FileID': 0, 'm_PathID': id_map[o_root_tr]})
    _save(rt, t)
    # the prefab's preload range also lists the merged objects (and what they reference outside the file)
    abo = next(o for o in env_b.objects if o.type.name == 'AssetBundle')
    ab = _read(abo)
    name, entry = ab['m_Container'][0]
    start, size = entry['preloadIndex'], entry['preloadSize']
    have = {(p['m_FileID'], p['m_PathID']) for p in ab['m_PreloadTable'][start:start + size]}
    extra = [{'m_FileID': 0, 'm_PathID': id_map[pid]} for pid in copy_ids]
    for f, p in ext_refs:
        if (f, p) not in have and p:
            have.add((f, p))
            extra.append({'m_FileID': f, 'm_PathID': p})
    pos = start + size
    ab['m_PreloadTable'][pos:pos] = extra
    for k, e in ab['m_Container'][1:]:
        if e['preloadIndex'] >= pos:
            e['preloadIndex'] += len(extra)
    entry['preloadSize'] = size + len(extra)
    _save(abo, ab)
    return added, mgr, len(reuse)


def _default(node):
    kids = node.m_Children or []
    t = node.m_Type
    if t == 'string':
        return ''
    if t.startswith('PPtr<'):
        return {'m_FileID': 0, 'm_PathID': 0}
    if kids and kids[0].m_Type == 'Array':
        return []
    if kids:
        return {c.m_Name: _default(c) for c in kids}
    return False if t == 'bool' else (0.0 if t in ('float', 'double') else 0)


def _conform(v, node):
    """a value read with another version of the ParticleSysMgr script -> this version's layout
    (fields this version does not have are dropped, fields the other one did not have get defaults)"""
    kids = node.m_Children or []
    t = node.m_Type
    if t == 'string' or t.startswith('PPtr<') or not kids:
        return v
    if kids[0].m_Type == 'Array':
        elem = kids[0].m_Children[1]
        return [_conform(x, elem) for x in v]
    return {c.m_Name: (_conform(v[c.m_Name], c) if c.m_Name in v else _default(c)) for c in kids}


def _absorb(mt, sub, node):
    """split node's ParticleSysMgr lists -> base ParticleSysMgr (as one prefab); lifetime covers both"""
    fields = {c.m_Name: c for c in node.m_Children}
    for k, v in sub.items():
        if isinstance(v, list) and isinstance(mt.get(k), list) and k in fields:
            mt[k] = mt[k] + _conform(v, fields[k])
    fi = {c.m_Name: c for c in fields['FilterInfo'].m_Children}
    for k in ('Filter1', 'Filter2'):
        mt['FilterInfo'][k] = mt['FilterInfo'][k] + _conform(sub['FilterInfo'][k], fi[k])
    if 'm_bTrail' in mt:
        mt['m_bTrail'] = bool(mt['m_bTrail'] or sub.get('m_bTrail'))
    mt['DelayTime'] = max(mt['DelayTime'], sub['DelayTime'])


def main():
    root, report_path = sys.argv[1], sys.argv[2]
    paths = {}
    for dp, dn, fn in os.walk(os.path.join(root, 'Art')):
        for f in fn:
            if f.endswith('.unity3d'):
                paths[f[:-len('.unity3d')]] = os.path.join(dp, f)
    pristine = {s: open(p, 'rb').read() for s, p in paths.items()}       # split nodes are read as shipped
    report = {}
    for stem in sorted(paths):
        if stem.startswith(SKIP_PREFIX):
            continue
        _TT.clear()
        _TEXIDX.clear()
        env = UnityPy.load(pristine[stem])
        mo, mt = _manager(env)
        if mo is None:
            continue
        refs = [mt['FilterInfo'][k] for k in REFS]
        gather = sum(1 for e in mt['ParSysInfo'] if e['fGatherNum'] != e['fDefaultNum'])
        if not any(refs) and not gather:
            continue
        rep = {'merged': {}, 'cleared': [], 'gather_fixed': 0}
        subs = []
        queue, seen = list(refs), {stem}
        while queue:
            r = queue.pop(0)
            if not r or r in seen:
                continue
            seen.add(r)
            if r not in paths:
                rep['cleared'].append(r)
                continue
            added, sub, shared = merge_into(env, UnityPy.load(pristine[r]), f'{stem} <- {r}')
            rep['merged'][r] = dict(added)
            rep['textures_shared'] = rep.get('textures_shared', 0) + shared
            if sub:
                subs.append(sub)
                queue += [sub['FilterInfo'][k] for k in REFS]
        mo, mt = _manager(env)
        for sub in subs:
            _absorb(mt, sub, mo.serialized_type.node)
        for k in REFS:
            mt['FilterInfo'][k] = ''
        for e in mt['ParSysInfo']:
            if e['fGatherNum'] != e['fDefaultNum']:
                rep['gather_fixed'] += 1
                e['fGatherNum'] = e['fDefaultNum']
        mo.save_typetree(mt)
        with open(paths[stem], 'wb') as fh:
            fh.write(env.file.save(packer='original'))
        report[stem] = rep
    with open(report_path, 'w') as fh:
        json.dump(report, fh, indent=1)
    n_m = sum(len(r['merged']) for r in report.values())
    n_c = sum(len(r['cleared']) for r in report.values())
    print(f'effects changed {len(report)}, split nodes merged {n_m}, references to bundles not in the mod cleared '
          f'{n_c}, gather counts fixed {sum(r["gather_fixed"] for r in report.values())}, '
          f'duplicate textures shared {sum(r.get("textures_shared", 0) for r in report.values())}')


if __name__ == '__main__':
    main()
