"""Validate the Sanctum Island High remaster against the original scene bundles.

usage: python validate_map.py <orig Scenes/android> <new Scenes/android>
"""
import sys, os, collections, math
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import numpy as np
import UnityPy
from PIL import Image
import map_fx

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
expected = {(False, 'GameObject'): n_fx + 1, (False, 'Transform'): n_fx + 1, (False, 'ParticleSystem'): n_fx,
            (False, 'ParticleSystemRenderer'): n_fx, (True, 'Texture2D'): len(map_fx.TEXTURES), (True, 'Material'): n_mat}
if dict(added) != expected:
    bad('unexpected added object set', dict(added))

# every object re-reads; untouched kinds keep their exact bytes
reread = 0
for k, o in mn.items():
    try:
        o.read_typetree(); reread += 1
    except Exception as e:
        bad('read fail', k, o.type.name, e)
    if k in mo and o.type.name not in ('Texture2D', 'PreloadData'):
        if o.get_raw_data() != mo[k].get_raw_data():
            bad('object bytes changed', k, o.type.name)
print('objects re-read:', reread)

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
            if c < 0.8 or cf > c:
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
if alive > 260:
    bad('particle budget exceeded', alive)
print(f'\nPROBLEMS: {problems}')
