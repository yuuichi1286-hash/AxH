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
import map_fx
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
PLAN = {'ground': (50, True, 2, 4), 'prop': (51, True, 2, 2), 'sky': (50, False, 1, 1), 'foliage': (50, False, 1, 1),
        'lightmap': (50, False, 1, 1), 'mask': (51, False, 1, 1), 'noise': (51, False, 1, 1)}


def process_image(kind, rgba, sr):
    """rgba float32 HxWx4 -> processed float32 rgba"""
    import cv2
    rgb, a = rgba[..., :3], rgba[..., 3]
    H, W = a.shape
    if kind in ('ground', 'prop', 'sky', 'foliage'):
        up = sr.x2(rgb)
        lz = np.clip(cv2.resize(rgb, (W * 2, H * 2), interpolation=cv2.INTER_LANCZOS4), 0, 1)
        x = map_hd.detail_restore(up, lz, 0.35 if kind == 'ground' else 0.25)
        x = map_hd.grade(x, {'ground': 'ground', 'prop': 'prop', 'sky': 'sky', 'foliage': 'prop'}[kind])
        x = map_hd.sharpen(x, 0.25 if kind != 'sky' else 0.15, 0.8)
        if a.min() < 0.999:
            a2 = np.clip(cv2.resize(a, (W * 2, H * 2), interpolation=cv2.INTER_LANCZOS4), 0, 1)
            a2 = np.clip(a2 + (a2 - cv2.GaussianBlur(a2, (0, 0), 1.0)) * 0.5, 0, 1)
        else:
            a2 = np.ones((H * 2, W * 2), np.float32)
        return np.dstack([x, a2])
    if kind == 'lightmap':
        x = cv2.bilateralFilter(rgb.astype(np.float32), 7, 0.05, 3.0)
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


def process_high(env, report, sr, pool):
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
        out = process_image(kind, img, sr)
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
    report['effects'] = map_fx.inject(env, TEMPLATES, fx_tex_hd.encode)


def main():
    src, dst, report_path, onnx_path = sys.argv[1:5]
    workers = int(sys.argv[5]) if len(sys.argv) > 5 else 4
    if os.path.exists(dst):
        shutil.rmtree(dst)
    shutil.copytree(src, dst)
    from sr_model import SR
    sr = SR(onnx_path, threads=workers)
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
