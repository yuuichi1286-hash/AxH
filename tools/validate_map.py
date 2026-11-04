"""Validate the Sanctum Island High remaster against the original scene bundles.

usage: python validate_map.py <orig Scenes/android> <new Scenes/android>
"""
import sys, os, collections, math
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import numpy as np
import UnityPy
from PIL import Image
import map_fx
import map_bake
import map_trees

o_root, n_root = sys.argv[1:3]
problems = 0


def bad(*a):
    global problems
    problems += 1
    print('PROBLEM', *a)


HIGH = 'PVP_049_add.unity3d'
for f in sorted(os.listdir(o_root)):
    a = open(os.path.join(o_root, f), 'rb').read()
    pn = os.path.join(n_root, f)
    if not os.path.exists(pn):
        bad('missing', f); continue
    b = open(pn, 'rb').read()
    if f == HIGH:
        if a == b:
            bad('High scene not changed')
        print(f'{f}: {len(a)} -> {len(b)} bytes')
    elif a != b:
        bad('changed but must be untouched:', f)
    else:
        print(f'{f}: identical')

eo, en = UnityPy.load(os.path.join(o_root, HIGH)), UnityPy.load(os.path.join(n_root, HIGH))
fo, fn = list(eo.files.values())[0], list(en.files.values())[0]
if (int(fo.dataflags), fo._block_info_flags, fo.version, fo.version_engine) != (int(fn.dataflags), fn._block_info_flags, fn.version, fn.version_engine):
    bad('bundle header differs')
if list(fo.files.keys()) != list(fn.files.keys()):
    bad('internal file names differ')


def objmap(env):
    return {(o.assets_file.name, o.path_id): o for o in env.objects}


mo, mn = objmap(eo), objmap(en)
added = collections.Counter()
for k, o in mn.items():
    if k not in mo:
        added[(k[0].endswith('sharedAssets'), o.type.name)] += 1
        continue
    if mo[k].type.name != o.type.name:
        bad('type changed', k)
for k in mo:
    if k not in mn:
        bad('object removed', k)
print('added objects:', dict(added))
n_fx = len(map_fx.effects())
n_mat = len({(e['tex'], e['blend']) for e in map_fx.effects()})
n_parts = len(map_trees.groups()) * len(map_trees.SOURCE)
n_blossom = len({g[7] for g in map_trees.groups() if g[7]})
expected = {(False, 'GameObject'): n_fx + 1 + n_parts + 1, (False, 'Transform'): n_fx + 1 + n_parts + 1,
            (False, 'ParticleSystem'): n_fx, (False, 'ParticleSystemRenderer'): n_fx,
            (False, 'MeshFilter'): n_parts, (False, 'MeshRenderer'): n_parts,
            (True, 'Texture2D'): len(map_fx.TEXTURES) + n_blossom, (True, 'Material'): n_mat + n_blossom}
if dict(added) != expected:
    bad('unexpected added object set', dict(added))

# every object re-reads; untouched kinds keep their exact bytes
diffmap_new, diffmap_src = [], {}
reread = 0
water_changed = 0
for k, o in mn.items():
    try:
        o.read_typetree(); reread += 1
    except Exception as e:
        bad('read fail', k, o.type.name, e)
    if k in mo and o.type.name not in ('Texture2D', 'PreloadData', 'Cubemap'):
        if o.get_raw_data() != mo[k].get_raw_data():
            if o.type.name == 'MonoBehaviour':
                # only the baked-lighting (diffmap) table may change: original entries kept as they were, plus one
                # entry per cloned trunk with the same lighting as its source trunk
                a, b = mo[k].read_typetree(), o.read_typetree()
                ia, ib = a.get('rendererDiffmapInfos'), b.get('rendererDiffmapInfos')
                if ia is None or ib is None or ib[:len(ia)] != ia or \
                        {kk: v for kk, v in a.items() if kk != 'rendererDiffmapInfos'} != {kk: v for kk, v in b.items() if kk != 'rendererDiffmapInfos'}:
                    bad('MonoBehaviour changed beyond the diffmap entries of the new trees', k)
                diffmap_new = ib[len(ia):] if ia is not None and ib is not None else []
                diffmap_src = {e['renderer']['m_PathID']: e for e in ia or []}
                continue
            if o.type.name == 'Material':
                # only the water materials may change, and only their reflection strength
                a, b = mo[k].read_typetree(), o.read_typetree()
                fa, fb = dict(a['m_SavedProperties']['m_Floats']), dict(b['m_SavedProperties']['m_Floats'])
                diff = {x for x in fa if fa[x] != fb.get(x)}
                rest_a = dict(a); rest_b = dict(b)
                rest_a['m_SavedProperties'] = dict(a['m_SavedProperties'], m_Floats=None)
                rest_b['m_SavedProperties'] = dict(b['m_SavedProperties'], m_Floats=None)
                if diff - set(map_bake.WATER_TWEAKS) or rest_a != rest_b:
                    bad('material changed beyond the water reflection tweak', b['m_Name'], diff)
                water_changed += 1
                continue
            bad('object bytes changed', k, o.type.name)
print('objects re-read:', reread, '| water materials with stronger reflection:', water_changed)

# reflection cubemap: 6 faces (face-major), each with its full mip chain
for k, o in mn.items():
    if o.type.name != 'Cubemap':
        continue
    import texture2ddecoder
    tt = o.read_typetree()
    w, fmt, mips = tt['m_Width'], tt['m_TextureFormat'], tt['m_MipCount']
    blk = {48: 4, 49: 5, 50: 6, 51: 8}[fmt]
    per = sum(math.ceil(max(1, w >> i) / blk) ** 2 * 16 for i in range(mips))
    if tt['m_CompleteImageSize'] != per or len(tt['image data']) != 6 * per:
        bad('cubemap size fields', tt['m_Name'], tt['m_CompleteImageSize'], per, len(tt['image data']))
    ot = mo[k].read_typetree()
    ow, oblk = ot['m_Width'], {48: 4, 49: 5, 50: 6, 51: 8}[ot['m_TextureFormat']]
    oper = ot['m_CompleteImageSize']
    for f in range(6):
        raw = bytes(tt['image data'][f * per: f * per + math.ceil(w / blk) ** 2 * 16])
        face = np.frombuffer(texture2ddecoder.decode_astc(raw, w, w, blk, blk), np.uint8).reshape(w, w, 4)
        if face[..., :3].max() == 0:
            bad('cubemap face empty', f)
        oraw = bytes(ot['image data'][f * oper: f * oper + math.ceil(ow / oblk) ** 2 * 16])
        of = np.frombuffer(texture2ddecoder.decode_astc(oraw, ow, ow, oblk, oblk), np.uint8).reshape(ow, ow, 4)[..., :3].mean(-1)
        nf = np.asarray(Image.fromarray(face[..., :3]).resize((ow, ow), Image.BOX), np.float32).mean(-1)
        if of.std() > 1 and nf.std() > 1:
            c = np.corrcoef(nf.ravel(), of.ravel())[0, 1]
            cf = np.corrcoef(nf[::-1].ravel(), of.ravel())[0, 1]
            if c < 0.8 or cf > c:
                bad(f'cubemap face {f} orientation/content: corr {c:.3f} flipped {cf:.3f}')
    print(f'cubemap {tt["m_Name"]}: {w}px fmt {fmt} mips {mips} ok')

# textures
ASTC = {48: 4, 49: 5, 50: 6, 51: 8}


def expected_bytes(w, h, fmt, mips):
    total = 0
    for i in range(mips):
        lw, lh = max(1, w >> i), max(1, h >> i)
        if fmt in ASTC:
            bsz = ASTC[fmt]
            total += math.ceil(lw / bsz) * math.ceil(lh / bsz) * 16
        elif fmt == 47:
            total += max(1, math.ceil(lw / 4)) * max(1, math.ceil(lh / 4)) * 16
    return total


ntex = 0
for k, o in mn.items():
    if o.type.name != 'Texture2D':
        continue
    tt = o.read_typetree()
    d = o.read()
    try:
        img = d.image.convert('RGBA')
    except Exception as e:
        bad('texture decode', tt['m_Name'], e); continue
    if len(tt['image data']) != expected_bytes(tt['m_Width'], tt['m_Height'], tt['m_TextureFormat'], tt['m_MipCount']):
        bad('texture data size', tt['m_Name'], len(tt['image data']))
    if tt['m_CompleteImageSize'] != len(tt['image data']):
        bad('m_CompleteImageSize', tt['m_Name'])
    if k in mo:
        od = mo[k].read()
        oi = od.image.convert('RGBA')

        def vis(im):
            x = np.asarray(im, np.float32) / 255.0
            return x[..., :3].max(-1) * x[..., 3]
        a = vis(img.resize(oi.size, Image.BILINEAR)); b = vis(oi)
        if a.std() > 0.01 and b.std() > 0.01:
            c = np.corrcoef(a.ravel(), b.ravel())[0, 1]
            cf = np.corrcoef(a[::-1].ravel(), b.ravel())[0, 1]
            # content kept (a garbled / wrong texture correlates ~0) and not flipped; the painterly clean-up,
            # relief and ornament glow legitimately reshape fine facets (e.g. the crystals sit around 0.79)
            if c < 0.75 or cf > c:
                bad(f'texture content/orientation {tt["m_Name"]}: corr {c:.3f} flipped {cf:.3f}')
    ntex += 1
print('textures checked:', ntex)

# new effect objects: references resolve, hierarchy consistent, shaders preloaded
scene = {o.path_id: o for o in en.objects if not o.assets_file.name.endswith('sharedAssets')}
shared = {o.path_id: o for o in en.objects if o.assets_file.name.endswith('sharedAssets')}
sf_scene = next(o.assets_file for o in scene.values())
sf_shared = next(o.assets_file for o in shared.values())
shared_fid = 1 + next(i for i, e in enumerate(sf_scene.externals) if e.path.endswith('.sharedassets'))
shader_fid = 1 + next(i for i, e in enumerate(sf_shared.externals) if e.path == map_fx.SHADER_CAB)
pre = next(o for o in shared.values() if o.type.name == 'PreloadData').read_typetree()
pre_set = {(a['m_FileID'], a['m_PathID']) for a in pre['m_Assets']}
for sid in (map_fx.ADD_SHADER, map_fx.BLEND_SHADER):
    if (shader_fid, sid) not in pre_set:
        bad('shader not preloaded', sid)
alive = 0
nps = 0
for pid, o in scene.items():
    if o.type.name != 'ParticleSystem':
        continue
    nps += 1
    ps = o.read_typetree()
    g = scene[ps['m_GameObject']['m_PathID']].read_typetree()
    comps = [scene.get(c['component']['m_PathID']) for c in g['m_Component']]
    if any(c is None for c in comps) or sorted(c.type.name for c in comps) != ['ParticleSystem', 'ParticleSystemRenderer', 'Transform']:
        bad('effect components', g['m_Name'])
        continue
    tr = next(c for c in comps if c.type.name == 'Transform').read_typetree()
    father = scene[tr['m_Father']['m_PathID']].read_typetree()
    if not any(ch['m_PathID'] == next(c for c in comps if c.type.name == 'Transform').path_id for ch in father['m_Children']):
        bad('hierarchy', g['m_Name'])
    psr = next(c for c in comps if c.type.name == 'ParticleSystemRenderer').read_typetree()
    for m in psr['m_Materials']:
        if m['m_FileID'] != shared_fid or m['m_PathID'] not in shared or shared[m['m_PathID']].type.name != 'Material':
            bad('material ref', g['m_Name']); continue
        mt = shared[m['m_PathID']].read_typetree()
        if mt['m_Shader']['m_FileID'] != shader_fid or mt['m_Shader']['m_PathID'] not in (map_fx.ADD_SHADER, map_fx.BLEND_SHADER):
            bad('shader ref', mt['m_Name'])
        for slot, te in mt['m_SavedProperties']['m_TexEnvs']:
            p = te['m_Texture']
            if p['m_PathID'] and (p['m_FileID'] != 0 or shared.get(p['m_PathID']) is None or shared[p['m_PathID']].type.name != 'Texture2D'):
                bad('texture ref', mt['m_Name'], slot)
    im = ps['InitialModule']
    rate = ps['EmissionModule']['rateOverTime']['scalar']
    life = im['startLifetime']
    need = rate * max(life['scalar'], life['minScalar'])
    alive += rate * (life['scalar'] + life['minScalar']) / 2
    if im['maxNumParticles'] < need * 0.9 or im['maxNumParticles'] > 100:
        bad('particle capacity', g['m_Name'], im['maxNumParticles'], round(need, 1))
    if not (ps['looping'] and ps['prewarm'] and ps['playOnAwake']):
        bad('effect not looping/prewarmed', g['m_Name'])
print(f'effects: {nps} particle systems, ~{alive:.0f} particles alive in total')
if alive > 300:
    bad('particle budget exceeded', alive)

# new trees: components / hierarchy / asset references, baked lighting entries, and nothing over / hiding the paths
from map_render import Scene
from meshio import decode
sc_n = Scene(en)
root = [pid for pid, g in sc_n.gos.items() if g['m_Name'] == map_trees.ROOT_NAME]
if len(root) != 1:
    bad('tree root missing / duplicated', len(root))
root_t = sc_n.go_tr[root[0]] if root else None
names = {g['m_Name']: pid for pid, g in sc_n.gos.items()}
src_mr, src_mf = {}, {}
for src in map_trees.SOURCE:
    g = sc_n.gos[names[src]]
    src_mr[src] = next(c['component']['m_PathID'] for c in g['m_Component'] if c['component']['m_PathID'] in sc_n.mr)
    src_mf[src] = next(c['component']['m_PathID'] for c in g['m_Component'] if c['component']['m_PathID'] in sc_n.mf)
mats_n = {pid: o.read_typetree() for pid, o in sc_n.shared.items() if o.type.name == 'Material'}
texs_n = {pid: o.read_typetree() for pid, o in sc_n.shared.items() if o.type.name == 'Texture2D'}
src_mat = sc_n.mr[src_mr[map_trees.SOURCE[1]]]['m_Materials'][0]
leaf_mat_tt = mats_n[src_mat['m_PathID']]
cam_go = next(pid for pid, g in sc_n.gos.items() if g['m_Name'] == '3DCamera_11')
cam_fwd = sc_n.world(sc_n.go_tr[cam_go])[:3, :3] @ np.array([0.0, 0.0, 1.0])
hm_n = map_trees.solid_heightmap(en)
walk_edge = map_trees.walk_edge(hm_n)
walk_grid, walk_depth = map_trees.walkable_grid(hm_n, walk_edge)
expected_parts = {p['name']: p for p in map_trees.plan(eo)}
seen, new_mr = set(), {}
worst = {'edge': [99.0, 99.0], 'lane': [99.0, 99.0], 'wall': [0.0, 0.0, 0.0]}
for pid, g in sc_n.gos.items():
    if not g['m_Name'].startswith('Sanctum_') or g['m_Name'] == map_trees.ROOT_NAME:
        continue
    if g['m_Name'] not in expected_parts:
        bad('unexpected Sanctum_ object', g['m_Name']); continue
    ep = expected_parts[g['m_Name']]
    seen.add(g['m_Name'])
    comps = [c['component']['m_PathID'] for c in g['m_Component']]
    kinds = sorted(sc_n.ctype.get(c, '?') for c in comps)
    if kinds != ['MeshFilter', 'MeshRenderer', 'Transform']:
        bad('tree components', g['m_Name'], kinds); continue
    tr = sc_n.trs[sc_n.go_tr[pid]]
    if tr['m_Father']['m_PathID'] != root_t or not any(ch['m_PathID'] == sc_n.go_tr[pid] for ch in sc_n.trs[root_t]['m_Children']):
        bad('tree hierarchy', g['m_Name'])
    mf = next(sc_n.mf[c] for c in comps if c in sc_n.mf)
    mrp = next(c for c in comps if c in sc_n.mr)
    mr = sc_n.mr[mrp]
    if mf['m_Mesh'] != sc_n.mf[src_mf[ep['src']]]['m_Mesh']:
        bad('tree mesh differs from the source tree', g['m_Name'])
    if ep['variant']:
        m = mr['m_Materials'][0]
        mt = mats_n.get(m['m_PathID'])
        if m['m_FileID'] != src_mat['m_FileID'] or mt is None or mt['m_Name'] != map_trees.BLOSSOM_MAT.format(ep['variant']):
            bad('blossom material ref', g['m_Name']); continue
        a_ = dict(leaf_mat_tt); b_ = dict(mt)
        ea, eb = dict(a_['m_SavedProperties']['m_TexEnvs']), dict(b_['m_SavedProperties']['m_TexEnvs'])
        tp = eb['_MainTex']['m_Texture']
        tx = texs_n.get(tp['m_PathID'])
        if tp['m_FileID'] != 0 or tx is None or tx['m_Name'] != map_trees.BLOSSOM_TEX.format(ep['variant']):
            bad('blossom texture ref', mt['m_Name'])
        ea.pop('_MainTex'); eb.pop('_MainTex')
        if ea != eb or a_['m_Shader'] != b_['m_Shader'] or a_['m_SavedProperties']['m_Floats'] != b_['m_SavedProperties']['m_Floats']:
            bad('blossom material differs from the leaf material beyond its colour map', mt['m_Name'])
    elif mr['m_Materials'] != sc_n.mr[src_mr[ep['src']]]['m_Materials']:
        bad('tree material differs from the source tree', g['m_Name'])
    mesh = sc_n.shared.get(mf['m_Mesh']['m_PathID'])
    new_mr[mrp] = ep['src']
    d = decode(mesh.read_typetree())
    M = sc_n.world(sc_n.go_tr[pid])
    if not np.allclose(M, ep['M'], atol=1e-3):
        bad('tree transform differs from the plan', g['m_Name'])
    wp = (M @ np.c_[d['pos'][:, :3], np.ones(len(d['pos']))].T).T[:, :3]
    if ep['group'] == 'wall':
        o_, s_, f_ = map_trees.wall_clearance(wp, cam_fwd, hm_n, walk_grid, walk_depth)
        if o_ > map_trees.WALL_OVER_MAX + 1e-6 or s_ > map_trees.WALL_SIGHT_MAX + 1e-6 or f_ > map_trees.WALL_SIGHT_FRAC:
            bad('inner-wall tree hides too much of the paths', g['m_Name'], round(o_, 2), round(s_, 2), round(f_, 2))
        w = worst['wall']; w[0], w[1], w[2] = max(w[0], o_), max(w[1], s_), max(w[2], f_)
    else:
        n_over, n_hide, dv, dh = map_trees.clearance(wp, cam_fwd, walk_edge)
        if n_over or n_hide:
            bad('tree over / hiding walkable ground', g['m_Name'], n_over, n_hide, round(dv, 2), round(dh, 2))
        w = worst[ep['group']]; w[0], w[1] = min(w[0], dv), min(w[1], dh)
missing = set(expected_parts) - seen
if missing:
    bad('tree parts missing', sorted(missing)[:4])
src_trunk_entry = diffmap_src.get(src_mr[map_trees.SOURCE[0]])
trunks = [m for m, s_ in new_mr.items() if s_ == map_trees.SOURCE[0]]
got = {e['renderer']['m_PathID']: e for e in diffmap_new}
if sorted(got) != sorted(trunks):
    bad('diffmap entries do not match the cloned trunks', len(got), len(trunks))
for m, e in got.items():
    if src_trunk_entry is None or (e['diffmapIndex'], e['diffmapScaleOffset']) != (src_trunk_entry['diffmapIndex'], src_trunk_entry['diffmapScaleOffset']):
        bad('cloned trunk lighting differs from the source trunk', m)
n_g = collections.Counter(p['group'] for p in expected_parts.values())
print(f"trees: {len(seen) // 2} new trees ({len(seen)} parts: {n_g['edge'] // 2} green + {n_g['lane'] // 2} blossom along the "
      f"lane walls + {n_g['wall'] // 2} blossom on the jungle walls), {len(got)} diffmap entries")
print(f"  lane-wall trees: nothing above / no camera sight line onto walkable ground (closest "
      f"{min(worst['edge'][0], worst['lane'][0]):+.2f} / {min(worst['edge'][1], worst['lane'][1]):+.2f} m from the measured edge)")
print(f"  jungle-wall trees: canopy past the wall edge <= {worst['wall'][0]:.2f} m, sight lines into the path <= "
      f"{worst['wall'][1]:.2f} m for <= {100 * worst['wall'][2]:.0f} % of the vertices (limits 0.5 m / 0.75 m / 25 %)")
print(f'\nPROBLEMS: {problems}')
