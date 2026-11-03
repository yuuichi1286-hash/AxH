"""Inject new ambient particle effects into a MLBB scene bundle (Sanctum Island High).

New objects are plain Unity objects in the scene file (GameObject + Transform + ParticleSystem +
ParticleSystemRenderer) and in its sharedAssets (Material + Texture2D). The ParticleSystem /
ParticleSystemRenderer type trees and default field values come from a template captured from a real
Unity 2019.4.33f1 effect bundle (map_fx_templates.json); the scene file gets those two types appended to its
type table (identical type hashes to every other 2019.4.33f1 bundle of the game). Materials use the game's
existing additive / alpha-blend effect shaders, which live in the same shader bundle the map already depends
on; they are added to the scene's PreloadData so they are loaded with the map.

usage (template capture, once):
  python map_fx.py capture <add template bundle> <blend template bundle> <out.json>
"""
import sys, os, json, base64, copy, math
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import numpy as np
from PIL import Image

ADD_SHADER = 3087322254700502312
BLEND_SHADER = -261248505249825764
SHADER_CAB = 'archive:/cab-f2f459222c9238e5954e6e42f2874ba6/cab-f2f459222c9238e5954e6e42f2874ba6'


# ------------------------------------------------------------------ JSON-safe typetree dicts
def to_json(v):
    if isinstance(v, dict):
        return {k: to_json(x) for k, x in v.items()}
    if isinstance(v, (list, tuple)):
        return [to_json(x) for x in v]
    if isinstance(v, (bytes, bytearray)):
        return {'__bytes__': base64.b64encode(bytes(v)).decode()}
    return v


def from_json(v):
    if isinstance(v, dict):
        if set(v) == {'__bytes__'}:
            return base64.b64decode(v['__bytes__'])
        return {k: from_json(x) for k, x in v.items()}
    if isinstance(v, list):
        return [from_json(x) for x in v]
    return v


def null_pptrs(v):
    """Every PPtr -> null (templates must not point at objects of their source bundle)."""
    if isinstance(v, dict):
        if set(v) == {'m_FileID', 'm_PathID'}:
            v['m_FileID'] = 0
            v['m_PathID'] = 0
            return v
        for x in v.values():
            null_pptrs(x)
    elif isinstance(v, list):
        for x in v:
            null_pptrs(x)
    return v


# ------------------------------------------------------------------ template capture
def capture(add_bundle, blend_bundle, out_json):
    import UnityPy
    from UnityPy.streams import EndianBinaryWriter
    res = {'types': {}}
    for tag, path, go_name, mat_name in (('add', add_bundle, 'glow_1', 'FX_M_126_skin02_ZXD_213'),
                                         ('blend', blend_bundle, 'andi', 'FX_M_126_skin02_ZXD_197')):
        env = UnityPy.load(path)
        gos = {o.path_id: o.read_typetree()['m_Name'] for o in env.objects if o.type.name == 'GameObject'}
        for o in env.objects:
            t = o.type.name
            if t in ('ParticleSystem', 'ParticleSystemRenderer'):
                tt = o.read_typetree()
                if gos.get(tt['m_GameObject']['m_PathID']) != go_name:
                    continue
                if tag == 'add':
                    res['ps' if t == 'ParticleSystem' else 'psr'] = to_json(null_pptrs(tt))
                    sf = o.assets_file
                    w = EndianBinaryWriter(endian=sf.header.endian)
                    o.serialized_type.write(sf, w, False)
                    res['types'][str(o.class_id)] = {'blob': base64.b64encode(w.bytes).decode(), 'endian': sf.header.endian,
                                                     'version': sf.header.version, 'unity': sf.unity_version}
            elif t == 'Material':
                tt = o.read_typetree()
                if tt['m_Name'] == mat_name:
                    res['mat_' + tag] = to_json(null_pptrs(tt))
    json.dump(res, open(out_json, 'w'), indent=0)
    print('captured', list(res))


# ------------------------------------------------------------------ curve / gradient builders
def _key(t, v, s_in=0.0, s_out=0.0):
    return {'time': float(t), 'value': float(v), 'inSlope': float(s_in), 'outSlope': float(s_out),
            'weightedMode': 0, 'inWeight': 0.3333333432674408, 'outWeight': 0.3333333432674408}


def mmc(tmpl, lo, hi=None, curve=None, curve_min=None):
    """MinMaxCurve: constant, random between two constants, curve or random between two curves."""
    c = copy.deepcopy(tmpl)
    if curve is not None:
        c['minMaxState'] = 2 if curve_min is not None else 1
        c['scalar'] = float(lo)
        c['minScalar'] = float(lo)
        c['maxCurve']['m_Curve'] = [_key(*k) for k in curve]
        c['minCurve']['m_Curve'] = [_key(*k) for k in (curve_min or [])]
    elif hi is None:
        c['minMaxState'] = 0
        c['scalar'] = c['minScalar'] = float(lo)
    else:
        c['minMaxState'] = 3
        c['minScalar'], c['scalar'] = float(lo), float(hi)
    return c


def gradient(g, colors, alphas):
    from vfx_fix import set_colors, set_alpha
    set_colors(g, [(t, tuple(c)) for t, c in colors])
    set_alpha(g, alphas)
    g['m_Mode'] = 0


# ------------------------------------------------------------------ procedural particle textures
def tex_glow(n=64):
    y, x = (np.mgrid[0:n, 0:n] + 0.5) / n * 2 - 1
    r = np.sqrt(x * x + y * y)
    a = np.exp(-(r / 0.42) ** 2) * 0.75 + np.exp(-(r / 0.13) ** 2) * 0.6
    a = np.clip(a * np.clip(1 - r, 0, 1) ** 0.5, 0, 1)
    return np.dstack([np.ones_like(a)] * 3 + [a])


def tex_sparkle(n=64):
    y, x = (np.mgrid[0:n, 0:n] + 0.5) / n * 2 - 1
    r = np.sqrt(x * x + y * y)
    ray = np.exp(-(np.abs(x) / 0.035)) * np.exp(-(np.abs(y) / 0.75) ** 2) + np.exp(-(np.abs(y) / 0.035)) * np.exp(-(np.abs(x) / 0.75) ** 2)
    diag = (np.exp(-np.abs(x - y) / 0.05) + np.exp(-np.abs(x + y) / 0.05)) * np.exp(-(r / 0.35) ** 2) * 0.35
    a = np.clip(ray + diag + np.exp(-(r / 0.12) ** 2), 0, 1) * np.clip(1 - r, 0, 1)
    return np.dstack([np.ones_like(a)] * 3 + [np.clip(a, 0, 1)])


def tex_mist(n=128, seed=7):
    import cv2
    rng = np.random.RandomState(seed)
    acc = np.zeros((n, n), np.float32)
    for octave, amp in ((4, 1.0), (8, 0.5), (16, 0.25), (32, 0.12)):
        g = rng.rand(octave, octave).astype(np.float32)
        acc += cv2.resize(g, (n, n), interpolation=cv2.INTER_CUBIC) * amp
    acc = (acc - acc.min()) / (acc.max() - acc.min())
    y, x = (np.mgrid[0:n, 0:n] + 0.5) / n * 2 - 1
    r = np.sqrt(x * x + y * y)
    fall = np.clip(1 - r, 0, 1) ** 1.6
    a = np.clip((acc * 0.75 + 0.25) * fall * 1.25, 0, 1)
    a = cv2.GaussianBlur(a, (0, 0), 1.2)
    return np.dstack([np.ones_like(a)] * 3 + [a])


def tex_leaf(n=64):
    """Pointed leaf with a mid-rib and soft shading (grey-white: the particle colour tints it)."""
    import cv2
    y, x = (np.mgrid[0:n, 0:n] + 0.5) / n * 2 - 1
    xr, yr = (x + y) / np.sqrt(2), (y - x) / np.sqrt(2)          # leaf along the diagonal
    half = 0.36 * np.clip(1 - np.abs(xr / 0.92) ** 1.6, 0, 1) ** 0.75
    inside = np.clip((half - np.abs(yr)) / 0.03, 0, 1) * (np.abs(xr) < 0.92)
    rib = np.exp(-(yr / 0.022) ** 2) * (np.abs(xr) < 0.85)
    veins = 0.12 * (np.sin((xr * 9 + np.abs(yr) * 7) * np.pi) > 0.6) * np.clip(half - np.abs(yr), 0, 1) / 0.36
    shade = 0.72 + 0.28 * (1 - np.abs(yr) / 0.36) - 0.18 * rib - veins
    a = cv2.GaussianBlur(inside.astype(np.float32), (0, 0), 0.6)
    v = np.clip(shade, 0, 1)
    return np.dstack([v, v, v, a])


TEXTURES = {'FX_Sanctum_glow': tex_glow, 'FX_Sanctum_sparkle': tex_sparkle, 'FX_Sanctum_mist': tex_mist,
            'FX_Sanctum_leaf': tex_leaf}


# ------------------------------------------------------------------ the ambient effects
def effects():
    """name, position, box size, texture, blend, rate, life, size, speed(xyz lo/hi), colours, alpha keys, max, extra"""
    E = []
    gold = [(0.0, (1.0, 0.86, 0.45)), (0.5, (0.85, 1.0, 0.55)), (1.0, (1.0, 0.8, 0.4))]
    flicker = [(0.0, 0.0), (0.12, 0.85), (0.3, 0.35), (0.45, 0.95), (0.62, 0.4), (0.78, 0.9), (1.0, 0.0)]
    for i, (x, z) in enumerate(((-16, 16), (-16, -17), (16, 17), (16, -16))):
        E.append(dict(name=f'FX_Fireflies_{i + 1}', pos=(x, 1.1, z), box=(20, 1.6, 20), tex='FX_Sanctum_glow', blend='add',
                      rate=3.5, life=(4.0, 6.5), size=(0.16, 0.3), vel=((-0.25, 0.25), (-0.05, 0.12), (-0.25, 0.25)),
                      colors=gold, alphas=flicker, wave=0.35, maxp=40))
    E.append(dict(name='FX_River_Sparkles', pos=(0, 0.12, 0), box=(10, 0.05, 56), tex='FX_Sanctum_sparkle', blend='add',
                  rate=18.0, life=(0.5, 1.0), size=(0.2, 0.4), vel=((0, 0), (0, 0.02), (0, 0)),
                  colors=[(0.0, (0.75, 1.0, 1.0)), (1.0, (0.55, 0.9, 1.0))],
                  alphas=[(0.0, 0.0), (0.25, 1.0), (0.55, 0.8), (1.0, 0.0)], spin=(40, 120), maxp=24))
    E.append(dict(name='FX_River_Mist', pos=(0, 0.35, 0), box=(9, 0.2, 54), tex='FX_Sanctum_mist', blend='blend',
                  rate=0.75, life=(9.0, 13.0), size=(3.5, 6.0), vel=((-0.12, 0.12), (0.0, 0.03), (-0.2, 0.2)),
                  colors=[(0.0, (0.82, 0.97, 1.0)), (1.0, (0.9, 1.0, 1.0))],
                  alphas=[(0.0, 0.0), (0.3, 0.16), (0.7, 0.14), (1.0, 0.0)], spin=(-8, 8), grow=1.35, maxp=16))
    for i, z in enumerate((21.4, -21.4)):
        E.append(dict(name=f'FX_Pit_Aura_{i + 1}', pos=(0.4 if z > 0 else -0.4, 0.6, z), box=(6.5, 0.3, 6.5), tex='FX_Sanctum_glow',
                      blend='add', rate=7.0, life=(2.5, 4.0), size=(0.12, 0.26), vel=((-0.08, 0.08), (0.45, 0.9), (-0.08, 0.08)),
                      colors=[(0.0, (0.55, 1.0, 0.95)), (0.6, (0.6, 0.85, 1.0)), (1.0, (0.85, 0.7, 1.0))],
                      alphas=[(0.0, 0.0), (0.15, 0.9), (0.7, 0.6), (1.0, 0.0)], wave=0.2, maxp=36))
    for i, x in enumerate((-50.2, 50.2)):
        E.append(dict(name=f'FX_Base_Sparkles_{i + 1}', pos=(x, 1.0, 0.0), box=(4.0, 1.0, 4.0), tex='FX_Sanctum_sparkle',
                      blend='add', rate=5.0, life=(2.2, 3.4), size=(0.14, 0.3), vel=((-0.1, 0.1), (0.6, 1.2), (-0.1, 0.1)),
                      colors=[(0.0, (1.0, 0.95, 0.8)), (1.0, (1.0, 0.88, 0.62))],
                      alphas=[(0.0, 0.0), (0.12, 1.0), (0.6, 0.7), (1.0, 0.0)], spin=(60, 160), maxp=24))
    E.append(dict(name='FX_Light_Motes', pos=(0, 2.2, 0), box=(110, 3.0, 80), tex='FX_Sanctum_glow', blend='add',
                  rate=6.0, life=(7.0, 10.0), size=(0.08, 0.15), vel=((-0.15, 0.15), (-0.03, 0.08), (-0.15, 0.15)),
                  colors=[(0.0, (1.0, 0.97, 0.88)), (1.0, (0.92, 1.0, 0.95))],
                  alphas=[(0.0, 0.0), (0.2, 0.55), (0.8, 0.5), (1.0, 0.0)], wave=0.25, maxp=80))
    for i, z in enumerate((44.0, -44.0)):
        E.append(dict(name=f'FX_Falling_Leaves_{i + 1}', pos=(0.0, 4.5, z), box=(40, 1.0, 6), tex='FX_Sanctum_leaf', blend='blend',
                      rate=1.3, life=(5.5, 7.5), size=(0.26, 0.42), vel=((-0.2, 0.2), (-0.75, -0.45), (-0.15, 0.15)),
                      colors=[(0.0, (0.62, 0.86, 0.38)), (0.5, (0.85, 0.82, 0.36)), (1.0, (0.95, 0.66, 0.3))],
                      alphas=[(0.0, 0.0), (0.12, 0.95), (0.8, 0.9), (1.0, 0.0)], wave=0.45, spin=(-110, 110), maxp=14))
    return E


def build_ps(T, e, go_pptr):
    ps = copy.deepcopy(T['ps'])
    tm = ps['startDelay']                      # a MinMaxCurve to clone from
    ps['m_GameObject'] = go_pptr
    ps['lengthInSec'] = 5.0
    ps['looping'] = True
    ps['prewarm'] = True
    ps['playOnAwake'] = True
    ps['autoRandomSeed'] = True
    ps['moveWithTransform'] = 1                # world simulation space
    ps['scalingMode'] = 1                      # local
    ps['cullingMode'] = 0                      # automatic (paused while off screen)
    ps['startDelay'] = mmc(tm, 0.0)
    im = ps['InitialModule']
    im['enabled'] = True
    im['startLifetime'] = mmc(tm, *e['life'])
    im['startSpeed'] = mmc(tm, 0.0)
    im['startSize'] = mmc(tm, *e['size'])
    im['size3D'] = False
    im['rotation3D'] = False
    im['startRotation'] = mmc(tm, 0.0, 2 * math.pi)
    im['gravityModifier'] = mmc(tm, 0.0)
    im['maxNumParticles'] = int(e['maxp'])
    sc = im['startColor']
    sc['minMaxState'] = 0
    for k in ('r', 'g', 'b', 'a'):
        sc['maxColor'][k] = 1.0
    sh = ps['ShapeModule']
    sh['enabled'] = True
    sh['type'] = 5                             # box (volume)
    sh['m_Position'] = {'x': 0.0, 'y': 0.0, 'z': 0.0}
    sh['m_Rotation'] = {'x': 0.0, 'y': 0.0, 'z': 0.0}
    sh['m_Scale'] = {'x': float(e['box'][0]), 'y': float(e['box'][1]), 'z': float(e['box'][2])}
    sh['boxThickness'] = {'x': 0.0, 'y': 0.0, 'z': 0.0}
    sh['randomDirectionAmount'] = 0.0
    sh['randomPositionAmount'] = 0.0
    em = ps['EmissionModule']
    em['enabled'] = True
    em['rateOverTime'] = mmc(tm, e['rate'])
    em['rateOverDistance'] = mmc(tm, 0.0)
    em['m_Bursts'] = []
    em['m_BurstCount'] = 0
    cm = ps['ColorModule']
    cm['enabled'] = True
    gr = cm['gradient']
    gr['minMaxState'] = 1
    gradient(gr['maxGradient'], e['colors'], e['alphas'])
    vm = ps['VelocityModule']
    vm['enabled'] = True
    vm['inWorldSpace'] = True
    (x0, x1), (y0, y1), (z0, z1) = e['vel']
    w = e.get('wave', 0.0)
    if w:
        # random blend of two wavy curves per particle: gentle meandering paths without the Noise module
        vm['x'] = mmc(tm, 1.0, curve=[(0, x1), (0.33, x0 - w), (0.66, x1 + w), (1, x0)], curve_min=[(0, x0), (0.33, x1 + w), (0.66, x0 - w), (1, x1)])
        vm['z'] = mmc(tm, 1.0, curve=[(0, z0), (0.4, z1 + w), (0.8, z0 - w), (1, z1)], curve_min=[(0, z1), (0.4, z0 - w), (0.8, z1 + w), (1, z0)])
    else:
        vm['x'] = mmc(tm, x0, x1)
        vm['z'] = mmc(tm, z0, z1)
    vm['y'] = mmc(tm, y0, y1)
    for k in ('orbitalX', 'orbitalY', 'orbitalZ', 'orbitalOffsetX', 'orbitalOffsetY', 'orbitalOffsetZ', 'radial'):
        if k in vm:
            vm[k] = mmc(tm, 0.0)
    if 'speedModifier' in vm:
        vm['speedModifier'] = mmc(tm, 1.0)
    rm = ps['RotationModule']
    if e.get('spin'):
        rm['enabled'] = True
        rm['separateAxes'] = False
        a, b = e['spin']
        rm['curve'] = mmc(tm, math.radians(a), math.radians(b))
        for k in ('x', 'y'):
            if k in rm:
                rm[k] = mmc(tm, 0.0)
    else:
        rm['enabled'] = False
    sm = ps['SizeModule']
    if e.get('grow'):
        sm['enabled'] = True
        sm['separateAxes'] = False
        sm['curve'] = mmc(tm, 1.0, curve=[(0, 0.75, 0, 0.6), (1, e['grow'], 0.6, 0)])
    else:
        sm['enabled'] = True
        sm['separateAxes'] = False
        sm['curve'] = mmc(tm, 1.0, curve=[(0, 0.6, 0, 2.0), (0.2, 1.0, 0, 0), (1, 0.85, -0.2, 0)])
    for mod in ('NoiseModule', 'CollisionModule', 'TriggerModule', 'SubModule', 'LightsModule', 'TrailModule',
                'ExternalForcesModule', 'ClampVelocityModule', 'ForceModule', 'InheritVelocityModule', 'UVModule',
                'CustomDataModule', 'ColorBySpeedModule', 'SizeBySpeedModule', 'RotationBySpeedModule'):
        if mod in ps and isinstance(ps[mod], dict) and 'enabled' in ps[mod]:
            ps[mod]['enabled'] = False
    return ps


def build_psr(T, go_pptr, mat_pptr):
    r = copy.deepcopy(T['psr'])
    r['m_GameObject'] = go_pptr
    r['m_Enabled'] = True
    r['m_CastShadows'] = 0
    r['m_ReceiveShadows'] = 0
    r['m_Materials'] = [mat_pptr]
    r['m_RenderMode'] = 0
    r['m_SortMode'] = 0
    r['m_MinParticleSize'] = 0.0
    r['m_MaxParticleSize'] = 0.5
    r['m_SortingFudge'] = 0.0
    r['m_UseCustomVertexStreams'] = False
    r['m_RenderAlignment'] = 0
    return r


def build_material(T, name, blend, tex_pptr, shader_file_id):
    m = copy.deepcopy(T['mat_' + blend])
    m['m_Name'] = name
    m['m_Shader'] = {'m_FileID': shader_file_id, 'm_PathID': ADD_SHADER if blend == 'add' else BLEND_SHADER}
    sp = m['m_SavedProperties']
    for pair in sp['m_TexEnvs']:
        if pair[0] == '_Diffuse':
            pair[1]['m_Texture'] = dict(tex_pptr)
    for pair in sp['m_Colors']:
        if pair[0] in ('_DiffuseColor', '_Color', '_MainColor', '_BackColor'):
            c = pair[1]
            c['r'] = c['g'] = c['b'] = 1.0           # neutral: the particle colours carry the tint (alpha kept)
    for i, pair in enumerate(sp['m_Floats']):
        if pair[0] == '_Hue':
            sp['m_Floats'][i] = [pair[0], 0.0]
    return m


def texture_dict(tmpl, name, img_rgba01, encode):
    """Texture2D dict (ETC2 RGBA8 + full mip chain) built from an existing Texture2D dict of the target file."""
    t = copy.deepcopy(tmpl)
    im = Image.fromarray((np.clip(img_rgba01, 0, 1) * 255 + 0.5).astype(np.uint8), 'RGBA')
    mips = int(math.log2(max(im.size))) + 1
    data = encode(im, 47, mips)
    t.update({'m_Name': name, 'm_Width': im.width, 'm_Height': im.height, 'm_TextureFormat': 47, 'm_MipCount': mips,
              'm_CompleteImageSize': len(data), 'image data': data, 'm_IsReadable': False, 'm_ImageCount': 1,
              'm_StreamData': {'offset': 0, 'size': 0, 'path': ''}})
    t['m_TextureSettings'] = dict(t['m_TextureSettings'], m_FilterMode=2, m_Aniso=1, m_WrapU=1, m_WrapV=1, m_WrapW=1)
    return t


# ------------------------------------------------------------------ injection
def _new_object(sf, path_id, stype, type_index, tree):
    from UnityPy.files.ObjectReader import ObjectReader
    from UnityPy.enums import ClassIDType
    obj = ObjectReader(sf, sf.reader, path_id, type_index, stype, stype.class_id, ClassIDType(stype.class_id),
                       0, 0, None, None)
    obj.save_typetree(tree, nodes=stype.node)
    sf.objects[path_id] = obj
    return obj


def inject(env, templates_path, encode):
    """Adds the ambient effects to the scene bundle loaded in env. Returns a report dict."""
    from UnityPy.files.SerializedFile import SerializedType
    from UnityPy.streams import EndianBinaryReader
    T = from_json(json.load(open(templates_path)))
    bf = env.files[list(env.files)[0]]
    scene = next(sf for n, sf in bf.files.items() if hasattr(sf, 'types') and not n.endswith('.sharedAssets'))
    shared = next(sf for n, sf in bf.files.items() if n.endswith('.sharedAssets'))
    # --- type table of the scene file: append ParticleSystem (198) / ParticleSystemRenderer (199)
    tindex = {}
    for cid in (198, 199):
        info = T['types'][str(cid)]
        assert info['version'] == scene.header.version and info['unity'] == scene.unity_version
        st = SerializedType(EndianBinaryReader(base64.b64decode(info['blob']), endian=info['endian']), scene, False)
        existing = [i for i, t in enumerate(scene.types) if t.class_id == cid]
        if existing:
            tindex[cid] = existing[0]
        else:
            scene.types.append(st)
            tindex[cid] = len(scene.types) - 1

    def type_of(sf, cid):
        i = next(i for i, t in enumerate(sf.types) if t.class_id == cid)
        return i, sf.types[i]

    # --- external file ids
    shader_fid = 1 + next(i for i, e in enumerate(shared.externals) if e.path == SHADER_CAB)
    shared_fid = 1 + next(i for i, e in enumerate(scene.externals) if e.path.endswith('.sharedassets'))
    # --- textures + materials in sharedAssets
    next_shared = max(shared.objects) + 1
    tex_tmpl = next(o for o in shared.objects.values() if o.type.name == 'Texture2D').read_typetree()
    mat_ids, tex_ids = {}, {}
    ti, tt_ = type_of(shared, 28)
    for name, fn in TEXTURES.items():
        _new_object(shared, next_shared, tt_, ti, texture_dict(tex_tmpl, name, fn(), encode))
        tex_ids[name] = next_shared
        next_shared += 1
    mi, mt = type_of(shared, 21)
    for e in effects():
        key = (e['tex'], e['blend'])
        if key in mat_ids:
            continue
        name = f"FX_M_Sanctum_{e['tex'].split('_')[-1]}_{e['blend']}"
        _new_object(shared, next_shared, mt, mi, build_material(T, name, e['blend'], {'m_FileID': 0, 'm_PathID': tex_ids[e['tex']]}, shader_fid))
        mat_ids[key] = next_shared
        next_shared += 1
    # --- PreloadData: make sure the two effect shaders are loaded with the scene
    pre = next(o for o in shared.objects.values() if o.type.name == 'PreloadData')
    ptt = pre.read_typetree()
    have = {(a['m_FileID'], a['m_PathID']) for a in ptt['m_Assets']}
    for sid in (ADD_SHADER, BLEND_SHADER):
        if (shader_fid, sid) not in have:
            ptt['m_Assets'].append({'m_FileID': shader_fid, 'm_PathID': sid})
    pre.save_typetree(ptt)
    # --- scene objects
    go_i, go_t = type_of(scene, 1)
    tr_i, tr_t = type_of(scene, 4)
    go_tmpl = next(o for o in scene.objects.values() if o.type.name == 'GameObject').read_typetree()
    tr_tmpl = next(o for o in scene.objects.values() if o.type.name == 'Transform').read_typetree()
    nid = max(scene.objects) + 1

    def pp(pid):
        return {'m_FileID': 0, 'm_PathID': pid}

    def add_go(name, pos, father, comps):
        nonlocal nid
        g_id, t_id = nid, nid + 1
        nid += 2
        g = copy.deepcopy(go_tmpl)
        g.update({'m_Name': name, 'm_Layer': 10, 'm_Tag': 0, 'm_IsActive': True,
                  'm_Component': [{'component': pp(t_id)}] + [{'component': pp(c)} for c in comps]})
        t = copy.deepcopy(tr_tmpl)
        t.update({'m_GameObject': pp(g_id), 'm_LocalRotation': {'x': 0.0, 'y': 0.0, 'z': 0.0, 'w': 1.0},
                  'm_LocalPosition': {'x': float(pos[0]), 'y': float(pos[1]), 'z': float(pos[2])},
                  'm_LocalScale': {'x': 1.0, 'y': 1.0, 'z': 1.0}, 'm_Children': [], 'm_Father': pp(father)})
        return g_id, t_id, g, t

    root_g, root_t, rg, rt = add_go('FX_SanctumAmbient', (0, 0, 0), 0, [])
    children = []
    pending = []
    for e in effects():
        ps_id, psr_id = nid, nid + 1
        nid += 2
        g_id, t_id, g, t = add_go(e['name'], e['pos'], root_t, [ps_id, psr_id])
        children.append(pp(t_id))
        ps = build_ps(T, e, pp(g_id))
        psr = build_psr(T, pp(g_id), {'m_FileID': shared_fid, 'm_PathID': mat_ids[(e['tex'], e['blend'])]})
        pending += [(g_id, go_t, go_i, g), (t_id, tr_t, tr_i, t), (ps_id, scene.types[tindex[198]], tindex[198], ps),
                    (psr_id, scene.types[tindex[199]], tindex[199], psr)]
    rt['m_Children'] = children
    pending = [(root_g, go_t, go_i, rg), (root_t, tr_t, tr_i, rt)] + pending
    for pid, st, idx, tree in sorted(pending, key=lambda x: x[0]):
        _new_object(scene, pid, st, idx, tree)
    scene.mark_changed() if hasattr(scene, 'mark_changed') else None
    shared.mark_changed() if hasattr(shared, 'mark_changed') else None
    est = sum(e['rate'] * sum(e['life']) / 2 for e in effects())
    return {'effects': [e['name'] for e in effects()], 'scene_objects_added': len(pending),
            'shared_objects_added': len(tex_ids) + len(mat_ids), 'estimated_particles_alive': round(est),
            'materials': len(mat_ids), 'textures': list(tex_ids)}


if __name__ == '__main__':
    if sys.argv[1] == 'capture':
        capture(*sys.argv[2:5])
