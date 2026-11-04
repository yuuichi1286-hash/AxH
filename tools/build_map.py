"""Sanctum Island (PVP_049) HD remaster for the High graphics scene only.

usage: python build_map.py <orig Scenes/android dir> <out Scenes/android dir> <report.json> <sr.onnx> [workers]

Only PVP_049_add.unity3d (High) is changed. PVP_049_low (Low), the A* wall data and the other scenes are copied
byte-identical.
  * 16 ground tiles 1024 -> 2048: AI super-resolution (Real-ESRGAN compact, low-denoise blend), fine texture
    restored, cinematic grade, ASTC 6x6, full mip chain, trilinear + 4x anisotropic filtering
  * 40 prop textures 512 -> 1024: same pipeline (prop grade), ASTC 8x8, mips, trilinear + 2x aniso
  * sky 512 -> 1024 (sky grade), foliage cut-outs 512 -> 1024 (alpha upscaled separately, no mips = no thinning)
  * 7 lightmaps: ASTC block artefacts smoothed, warm-light / cool-shadow grade, ASTC 6x6 (same size)
  * masks 2x Lanczos, water noise 64 -> 256 (tileable)
  * new ambient effects (map_fx): fireflies, river sparkles + mist, Lord/Turtle pit aura, base sparkles, light motes
"""
import sys, os, json, shutil, time, collections
from concurrent.futures import ProcessPoolExecutor
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import numpy as np
from PIL import Image
import UnityPy

import map_hd
import map_decor
import map_fx
import map_trees
import map_bake
import fx_tex_hd

HIGH = 'PVP_049_add.unity3d'
TEMPLATES = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'map_fx_templates.json')


def kind_of(name):
    if 'hedaobake_' in name:
        return 'ground'
    if name.endswith('_DLM'):
        return 'lightmap'
    if name.endswith('_DA'):
        return 'foliage'
    if name.endswith('_A'):
        return 'mask'
    if 'Water_Noise' in name:
        return 'noise'
    if 'skybox' in name:
        return 'sky'
    return 'prop'


#            fmt  mips   filter aniso
PLAN = {'ground': (50, True, 2, 4), 'prop': (50, True, 2, 2), 'sky': (50, False, 1, 1), 'foliage': (50, False, 1, 1),
        'lightmap': (50, False, 1, 1), 'mask': (51, False, 1, 1), 'noise': (51, False, 1, 1)}


class CachedSR:
    """SR results cached on disk (exact float32, so a cached build is byte-identical to a fresh one).
    Enabled by the MAP_SR_CACHE environment variable (directory)."""

    def __init__(self, sr, onnx_path, cache_dir=None):
        import hashlib
        self.sr, self.dir = sr, cache_dir
        self.model = hashlib.sha1(open(onnx_path, 'rb').read()).hexdigest()[:16]
        if cache_dir:
            os.makedirs(cache_dir, exist_ok=True)

    def x2(self, rgb):
        import hashlib
        if not self.dir:
            return self.sr.x2(rgb)
        rgb = np.ascontiguousarray(rgb, np.float32)
        path = os.path.join(self.dir, hashlib.sha1(rgb.tobytes()).hexdigest() + self.model + '.npy')
        if os.path.exists(path):
            return np.load(path)
        out = self.sr.x2(rgb).astype(np.float32)
        np.save(path, out)
        return out


def process_image(kind, rgba, sr, name='', bake=None):
    """rgba float32 HxWx4 -> processed float32 rgba"""
    import cv2
    rgb, a = rgba[..., :3], rgba[..., 3]
    H, W = a.shape
    if kind in ('ground', 'prop', 'sky', 'foliage'):
        # v4 "clean premium": denoising AI upscale -> Kuwahara painterly clean-up (grain, blotches and compression
        # noise flattened, every edge kept sharp) -> palette / ornaments -> sharpening only on real structure.
        # Nothing adds synthetic grain or noise.
        x = sr.x2(rgb)
        if kind == 'ground':
            x = map_hd.kuwahara(x, r=2)
            x = map_hd.naturalize(x, 'ground')                  # natural earthy palette (no blue / teal cast)
            x = map_hd.palette(x)                               # grass ramp, warm soil kept, teal-green water
            x = map_hd.ornament_glow(x)
            x = map_hd.structure_sharpen(x, 0.35, 1.6)          # crisp lane engravings / stone edges
            stone = map_hd.stone_mask(x)
            if bake is not None and name in bake['tiles']:
                xz, cov, tex_dir = bake['tiles'][name]
                x = map_bake.relief_ground(x, tex_dir, stone)   # carved stone / lane engravings, soft grass
                # flowers, monster carcasses, fallen leaves, pebbles (lit + contact shadows, off the lanes)
                x = map_decor.apply(x, xz, cov, tex_dir, map_decor.tile_decals(bake['decor'], xz, cov), bake['sprites'])
                x = map_bake.apply_shadow_ao(x, xz, bake['shadow'], bake['ao'])
            else:
                x = map_bake.relief_ground(x, (-0.6, -0.8), stone)
        elif kind == 'prop':
            x = map_hd.kuwahara(x, r=3)
            if not any(k in name for k in ('crystal', 'qiu')):     # magic crystals / team-colour orbs keep their hue
                x = map_hd.naturalize(x, 'prop')
            x = map_hd.ornament_glow(x, 0.6)                   # gold trims, blue runes and crystals shine more
            x = map_hd.structure_sharpen(x, 0.35, 1.4)
            x = map_bake.relief_pbr(x, emboss=0.10, cavity=0.12, sheen=0.09, kind='prop', fine=0.5)
        elif kind == 'foliage':
            x = map_hd.kuwahara(x, r=2)                        # transparent texels hold dilated colour: no fringes
            x = map_hd.naturalize(x, 'foliage')                # teal bushes / leaves -> natural green
        elif kind == 'sky':
            x = map_hd.clean_surface(x, r=4, eps=0.0030)       # smooth gradients: guided filter, not painterly
        x = map_hd.grade(x, {'ground': 'ground', 'prop': 'prop', 'sky': 'sky', 'foliage': 'prop'}[kind])
        x = map_hd.structure_sharpen(x, 0.45 if kind != 'sky' else 0.25, 1.2)
        if a.min() < 0.999:
            a2 = np.clip(cv2.resize(a, (W * 2, H * 2), interpolation=cv2.INTER_LANCZOS4), 0, 1)
            a2 = np.clip(a2 + (a2 - cv2.GaussianBlur(a2, (0, 0), 1.0)) * 0.5, 0, 1)
        else:
            a2 = np.ones((H * 2, W * 2), np.float32)
        return np.dstack([x, a2])
    if kind == 'lightmap':
        x = cv2.bilateralFilter(rgb.astype(np.float32), 9, 0.06, 4.0)       # smooth, clean lighting
        x = map_hd.grade(x, 'lightmap')
        return np.dstack([x, a])
    if kind == 'mask':
        x = np.clip(cv2.resize(rgba, (W * 2, H * 2), interpolation=cv2.INTER_LANCZOS4), 0, 1)
        return x
    if kind == 'noise':
        p = 8
        big = np.pad(rgba, ((p, p), (p, p), (0, 0)), mode='wrap')
        up = cv2.resize(big, ((W + 2 * p) * 4, (H + 2 * p) * 4), interpolation=cv2.INTER_CUBIC)
        return np.clip(up[p * 4:(p + H) * 4, p * 4:(p + W) * 4], 0, 1)
    raise ValueError(kind)


def encode_job(job):
    name, raw, size, fmt, mips = job
    img = Image.frombytes('RGBA', size, raw)
    return name, fx_tex_hd.encode(img, fmt, mips)


def bake_context(env):
    """World-space cast-shadow / contact-AO maps from the real prop geometry + per ground texture the world
    position of every texel (2x size) and the texture-space light direction."""
    ground, _ = map_bake.scene_meshes(env, (17,))
    props, failed = map_bake.scene_meshes(env, (10,))
    hm = map_bake.ground_heightmap(ground)
    shadow, ao, foot = map_bake.shadow_ao_maps(props, hm, with_footprint=True)
    from map_render import Scene
    sc = Scene(env)
    mats = {pid: o.read_typetree() for pid, o in sc.shared.items() if o.type.name == 'Material'}
    texname = {pid: o.read_typetree() for pid, o in sc.shared.items() if o.type.name == 'Texture2D'}
    from meshio import decode
    users = {}                                     # ground texture -> every layer-17 mesh sampling it
    for gname, layer, M, mesh_pid, mat_pids in sc.renderers():
        if layer != 17 or not mat_pids or mat_pids[0] not in mats:
            continue
        tp = dict(mats[mat_pids[0]]['m_SavedProperties']['m_TexEnvs']).get('_MainTex')
        t = texname.get(tp['m_Texture']['m_PathID']) if tp else None
        d = decode(sc.shared[mesh_pid].read_typetree())
        if t is None or 'uv0' not in d:
            continue
        users.setdefault(t['m_Name'], (t, []))[1].append((M, d))
    tiles = {}
    for tname, (t, meshes) in users.items():
        size = (t['m_Width'] * 2, t['m_Height'] * 2)
        tiles[tname] = map_bake.tile_position_map(meshes, size)
    # ground decoration: world-space placement from the ORIGINAL ground colours (grass / lanes / water), the props
    # footprint (walls) and the plants growing on the jungle walls
    tex_by_name = {o.read_typetree()['m_Name']: o for o in env.objects if o.type.name == 'Texture2D'}
    orig = {n: (np.asarray(tex_by_name[n].read().image.convert('RGB'), np.float32) / 255.0, tiles[n][0], tiles[n][1])
            for n in tiles if n in tex_by_name}
    classes = map_decor.world_classes(orig)
    plants = [tuple(M[[0, 2], 3]) for gname, layer, M, mesh_pid, mat_pids in sc.renderers()
              if gname.startswith('PVP_049_2026s3_leaf_')]
    decor = map_decor.placements(classes, foot, ao, plants)
    return {'shadow': shadow, 'ao': ao, 'tiles': tiles, 'props': len(props), 'props_failed': failed,
            'shadow_cover': float((shadow > 0.5).mean()), 'decor': decor, 'sprites': {}}


def process_high(env, report, sr, pool):
    bake = bake_context(env)
    report['bake'] = {'props_casting': bake['props'], 'props_skipped_undecodable': bake['props_failed'],
                      'ground_tiles_shadowed': sorted(bake['tiles']), 'light_to': map_bake.TO_LIGHT.round(3).tolist()}
    report['decor'] = dict(collections.Counter(d['kind'] for d in bake['decor']))
    tex_objs = [o for o in env.objects if o.type.name == 'Texture2D']
    jobs = {}
    meta = {}
    counts = collections.Counter()
    t0 = time.time()
    for o in tex_objs:
        tt = o.read_typetree()
        name = tt['m_Name']
        kind = kind_of(name)
        img = np.asarray(o.read().image.convert('RGBA'), np.float32) / 255.0
        out = process_image(kind, img, sr, name, bake)
        im = Image.fromarray((np.clip(out, 0, 1) * 255 + 0.5).astype(np.uint8), 'RGBA')
        fmt, mips, filt, aniso = PLAN[kind]
        nm = fx_tex_hd.full_chain(*im.size) if mips else 1
        jobs[name] = pool.submit(encode_job, (name, im.tobytes(), im.size, fmt, nm))
        meta[name] = (o, im.size, fmt, nm, filt, aniso, kind, (tt['m_Width'], tt['m_Height'], tt['m_TextureFormat']))
        counts[kind] += 1
        print(f'  {name}: {kind} {tt["m_Width"]}->{im.size[0]} fmt {fmt} mips {nm} ({time.time() - t0:.0f}s)', flush=True)
    tex_rep = {}
    for name, fut in jobs.items():
        _, data = fut.result()
        o, size, fmt, nm, filt, aniso, kind, before = meta[name]
        tt = o.read_typetree()
        tt['m_Width'], tt['m_Height'] = size
        tt['m_TextureFormat'] = fmt
        tt['m_MipCount'] = nm
        tt['image data'] = data
        tt['m_CompleteImageSize'] = len(data)
        tt['m_StreamData'] = {'offset': 0, 'size': 0, 'path': ''}
        tt['m_TextureSettings']['m_FilterMode'] = filt
        tt['m_TextureSettings']['m_Aniso'] = aniso
        o.save_typetree(tt)
        tex_rep[name] = {'kind': kind, 'before': before, 'after': (size[0], size[1], fmt, nm), 'bytes': len(data)}
    report['textures'] = tex_rep
    report['texture_kinds'] = dict(counts)
    # sharper, higher resolution water reflection (cube map) + slightly stronger reflection / fresnel
    for o in env.objects:
        if o.type.name == 'Cubemap':
            tt = o.read_typetree()
            before = (tt['m_Width'], tt['m_TextureFormat'], tt['m_MipCount'])
            map_bake.upgrade_cubemap(tt, fx_tex_hd.encode)
            o.save_typetree(tt)
            report['cubemap'] = {tt['m_Name']: {'before': before, 'after': (tt['m_Width'], tt['m_TextureFormat'], tt['m_MipCount'])}}
        elif o.type.name == 'Material':
            tt = o.read_typetree()
            if any(k == '_Water_CubeMap' for k, v in tt['m_SavedProperties']['m_TexEnvs']):
                if map_bake.tweak_water_material(tt):
                    o.save_typetree(tt)
                    report.setdefault('water_materials', []).append(tt['m_Name'])
    # new trees (clones of the map's edge tree) on the outer cliff rim, then the ambient effects
    report['trees'] = map_trees.inject(env, map_trees.plan(env), map_fx._new_object)
    report['effects'] = map_fx.inject(env, TEMPLATES, fx_tex_hd.encode)


def main():
    src, dst, report_path, onnx_path = sys.argv[1:5]
    workers = int(sys.argv[5]) if len(sys.argv) > 5 else 4
    if os.path.exists(dst):
        shutil.rmtree(dst)
    shutil.copytree(src, dst)
    from sr_model import SR
    sr = CachedSR(SR(onnx_path, threads=workers), onnx_path, os.environ.get('MAP_SR_CACHE'))
    report = {}
    t0 = time.time()
    with ProcessPoolExecutor(max_workers=workers) as pool:
        path = os.path.join(dst, HIGH)
        env = UnityPy.load(path)
        process_high(env, report, sr, pool)
        data = env.file.save(packer='original')
        with open(path, 'wb') as fh:
            fh.write(data)
    report['_build_seconds'] = round(time.time() - t0, 1)
    report['_size'] = {'before': os.path.getsize(os.path.join(src, HIGH)), 'after': os.path.getsize(os.path.join(dst, HIGH))}
    with open(report_path, 'w') as fh:
        json.dump(report, fh, indent=1, default=str)
    print('done', report['_size'], report['_build_seconds'])


if __name__ == '__main__':
    main()
