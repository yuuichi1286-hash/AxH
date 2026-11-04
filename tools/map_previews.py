"""Sanctum Island previews: ground before/after (overview + close-up), props, simulated ambient effects.

usage: python map_previews.py <orig PVP_049_add.unity3d> <new PVP_049_add.unity3d> <out dir>
"""
import sys, os, math
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import numpy as np
from PIL import Image, ImageDraw, ImageFont
import UnityPy
import map_render, map_fx

o_path, n_path, out = sys.argv[1:4]
os.makedirs(out, exist_ok=True)


def font(sz):
    for p in ('/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf', '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf'):
        if os.path.exists(p):
            return ImageFont.truetype(p, sz)
    return ImageFont.load_default()


F = font(20)
eo, en = UnityPy.load(o_path), UnityPy.load(n_path)


def pair(a, b, title, la='Asli (High)', lb='HD remaster'):
    w, h = a.size
    s = Image.new('RGB', (w * 2 + 12, h + 40), (12, 13, 15))
    s.paste(a, (0, 40)); s.paste(b, (w + 12, 40))
    d = ImageDraw.Draw(s)
    d.text((8, 8), f'{title} - kiri: {la}', font=F, fill=(230, 230, 230))
    d.text((w + 20, 8), f'kanan: {lb}', font=F, fill=(140, 230, 170))
    return s


# 0. the WHOLE map with buildings / props (supersampled), stacked vertically so it can be viewed large
full = (-64, 64, -50, 50)


def whole(env, ppm=14):
    im = map_render.render(env, px_per_m=ppm * 2, extent=full, layers=(17, 10))
    return im.resize((im.width // 2, im.height // 2), Image.BOX)


a, b = whole(eo), whole(en)
w, h = a.size
s0 = Image.new('RGB', (w, 2 * h + 90), (12, 13, 15))
s0.paste(a, (0, 40)); s0.paste(b, (0, h + 90))
d0 = ImageDraw.Draw(s0)
d0.text((8, 8), 'SELURUH PETA - atas: asli (High)', font=F, fill=(230, 230, 230))
d0.text((8, h + 56), 'SELURUH PETA - bawah: remaster (semua 16 petak tanah, 40 props, langit, lightmap, air diubah)', font=F, fill=(140, 230, 170))
s0.save(os.path.join(out, '0_seluruh_peta.png'))

# 1. overview + close-ups
a = map_render.render(eo, px_per_m=9, extent=full)
b = map_render.render(en, px_per_m=9, extent=full)
pair(a, b, 'Sanctum Island, tampak atas').save(os.path.join(out, '1_peta_sebelum_sesudah.png'))
for i, ext in enumerate(((-30, -12, 0, 10), (-8, 8, 15, 28))):
    a = map_render.render(eo, px_per_m=56, extent=ext)
    b = map_render.render(en, px_per_m=56, extent=ext)
    pair(a, b, f'Close-up {i + 1} (1 m = 56 px)').save(os.path.join(out, f'{2 + i}_closeup_{i + 1}.png'))

# 1b. close-up at about the in-game zoom (1 m = 100 px, roughly one ground texel per screen pixel), with props
ext_game = (-15, -3, -9, -1)
a, b = (map_render.render(e, px_per_m=200, extent=ext_game, layers=(17, 10)) for e in (eo, en))
a, b = (im.resize((im.width // 2, im.height // 2), Image.BOX) for im in (a, b))
pair(a, b, 'Close-up skala game (1 m = 100 px)').save(os.path.join(out, '9_closeup_skala_game.png'))


# 2. props textures
def textures(env):
    return {o.read().m_Name: o.read() for o in env.objects if o.type.name == 'Texture2D'}


to, tn = textures(eo), textures(en)
names = ['PVP_049_2026s3_statue_03', 'PVP_049_2026s3_tree_01', 'PVP_049_2026s3_build_01', 'PVP_049_2026s3_shanshi_01',
         'PVP_049_2026s3_crystal_01_D', 'PVP_049_2026s3_skybox_01_D']
T = 300
s = Image.new('RGB', (len(names) * (T + 8), 2 * (T + 26) + 40), (12, 13, 15))
d = ImageDraw.Draw(s)
d.text((8, 8), 'Tekstur props: atas = asli 512 ASTC 8x8, bawah = 1024 AI-HD + grading', font=F, fill=(230, 230, 230))
for i, n in enumerate(names):
    for r, t in enumerate((to[n], tn[n])):
        im = t.image.convert('RGB')
        w, h = im.size
        crop = im.crop((w // 4, h // 4, w // 4 + w // 2, h // 4 + h // 2)).resize((T, T), Image.LANCZOS)
        s.paste(crop, (i * (T + 8), 40 + r * (T + 26)))
        d.text((i * (T + 8) + 4, 40 + r * (T + 26) + T + 2), f'{n.split("2026s3_")[-1]} {w}x{h}', font=font(14), fill=(200, 200, 200))
s.save(os.path.join(out, '4_tekstur_props.png'))

# 3. simulated ambient effects over the new ground (snapshot; particles drawn from the real effect parameters)
texs = {k: fn() for k, fn in map_fx.TEXTURES.items()}


def simulate(extent, ppm, enlarge, seed=3):
    base = np.asarray(map_render.render(en, px_per_m=ppm, extent=extent), np.float32) / 255.0
    img = base * 0.9
    rng = np.random.RandomState(seed)
    x0, x1, z0, z1 = extent
    H, W = img.shape[:2]
    for e in map_fx.effects():
        n_alive = int(e['rate'] * sum(e['life']) / 2)
        tex = texs[e['tex']]
        for _ in range(n_alive):
            life = rng.uniform(*e['life']); age = rng.uniform(0, life); u = age / life
            p = [e['pos'][k] + rng.uniform(-0.5, 0.5) * e['box'][k] for k in range(3)]
            p[0] += rng.uniform(*e['vel'][0]) * age; p[2] += rng.uniform(*e['vel'][2]) * age
            size = rng.uniform(*e['size']) * (e.get('grow', 1.0) ** u)
            al = np.interp(u, [t for t, _ in e['alphas']], [a for _, a in e['alphas']])
            col = np.array([np.interp(u, [t for t, _ in e['colors']], [c[k] for _, c in e['colors']]) for k in range(3)])
            if e.get('tint2'):                     # per-particle start colour between two tints (falling leaves)
                t1, t2 = (np.asarray(c, np.float64) for c in e['tint2'])
                col = col * (t1 + (t2 - t1) * rng.uniform())
            px, pz = (p[0] - x0) * ppm, (z1 - p[2]) * ppm
            r = max(1, int(size * ppm * 0.5 * enlarge))
            ya, xa = int(pz) - r, int(px) - r
            if ya < 0 or xa < 0 or ya + 2 * r > H or xa + 2 * r > W:
                continue
            sp = np.asarray(Image.fromarray((tex * 255).astype(np.uint8)).resize((2 * r, 2 * r), Image.BILINEAR), np.float32) / 255.0
            reg = img[ya:ya + 2 * r, xa:xa + 2 * r]
            a = sp[..., 3:4] * al
            if e['blend'] == 'add':
                reg += col * a * 1.3
            else:
                reg[:] = reg * (1 - a) + col * a
    return Image.fromarray((np.clip(img, 0, 1) * 255).astype(np.uint8))


views = [('Sungai + lubang Lord/Turtle: kilau sungai, aura', (-11, 11, 12, 30), 40),
         ('Jungle: kunang-kunang + debu cahaya', (-27, -5, 6, 24), 40),
         ('Base: kilau naik di sekitar orb', (-58, -42, -7, 7), 50),
         ('Pohon tepi atas: daun jatuh dari kanopi', (2, 26, 30, 48), 34)]
tiles = [simulate(ext, ppm, 1.6) for _, ext, ppm in views]
Ht = max(t.size[1] for t in tiles)
canvas = Image.new('RGB', (sum(t.size[0] for t in tiles) + 16 * (len(tiles) - 1), Ht + 70), (12, 13, 15))
d = ImageDraw.Draw(canvas)
d.text((8, 8), 'Efek ambient baru (simulasi tampak atas dari parameter efek yang dipasang, partikel diperbesar 1,6x)', font=F, fill=(230, 230, 230))
x = 0
for (title, ext, ppm), t in zip(views, tiles):
    canvas.paste(t, (x, 64))
    d.text((x + 6, 38), title, font=font(16), fill=(140, 230, 170))
    x += t.size[0] + 16
canvas.save(os.path.join(out, '5_efek_baru_simulasi.png'))
print('ok')


# 6. baked building shadows + AO (ground and props), 7. water reflection cube map
for i, ext in enumerate(((-30, -6, -34, -14), (-62, -40, -12, 10))):
    a = map_render.render(eo, px_per_m=36, extent=ext, layers=(17, 10))
    b = map_render.render(en, px_per_m=36, extent=ext, layers=(17, 10))
    pair(a, b, f'Bayangan + AO + emboss/PBR {i + 1}').save(
        os.path.join(out, f'{6 + i}_bayangan_ao_{i + 1}.png'))


def cube_faces(env):
    import texture2ddecoder, math as m_
    o = next(o for o in env.objects if o.type.name == 'Cubemap')
    tt = o.read_typetree()
    w, fmt, per = tt['m_Width'], tt['m_TextureFormat'], tt['m_CompleteImageSize']
    blk = {48: 4, 49: 5, 50: 6, 51: 8}[fmt]
    faces = []
    for f in range(6):
        raw = bytes(tt['image data'][f * per: f * per + m_.ceil(w / blk) ** 2 * 16])
        bgra = np.frombuffer(texture2ddecoder.decode_astc(raw, w, w, blk, blk), np.uint8).reshape(w, w, 4)
        faces.append(Image.fromarray(bgra[..., [2, 1, 0]].copy()).resize((192, 192), Image.NEAREST if w < 64 else Image.LANCZOS))
    return faces, w


fa, wa = cube_faces(eo)
fb, wb = cube_faces(en)
c = Image.new('RGB', (6 * 200, 2 * 222 + 40), (12, 13, 15))
d = ImageDraw.Draw(c)
d.text((8, 8), f'Cubemap pantulan air (pengganti SSR): atas = asli {wa}px, bawah = {wb}px lebih tajam', font=F, fill=(230, 230, 230))
for i in range(6):
    c.paste(fa[i], (i * 200, 40)); c.paste(fb[i], (i * 200, 40 + 222))
c.save(os.path.join(out, '8_pantulan_air.png'))
print('ok 6-8')


# 10+. game-camera perspective (orientation / FOV of the game's 3DCamera_11, baked lighting applied):
# original (left) vs new (right): new trees, flowers, monster carcasses, pebbles, fallen leaves, relief
FWD = np.array([0.542, -0.707, 0.455]); UP = np.array([0.542, 0.707, 0.455])


def cam(env, x, z, dist=24.0, size=(1280, 720)):
    eye = np.array([x, 0.0, z]) - FWD / np.linalg.norm(FWD) * dist
    return map_render.render_view(env, eye, FWD, UP, fov=30, size=size)


cam_views = [('Jungle: bangkai monster, warna alami (kamera game)', -14.0, -10.0, 22.0),
             ('Pohon baru menempel di tembok lane (kamera game)', -17.0, 29.0, 22.0),
             ('Jungle atas: bunga kecil di kaki batu (kamera game)', -18.0, 20.0, 22.0),
             ('Lane bawah + pohon baru di tembok (kamera game)', 27.0, -20.0, 24.0)]
for i, (title, x, z, dist) in enumerate(cam_views):
    pair(cam(eo, x, z, dist), cam(en, x, z, dist), title).save(os.path.join(out, f'{13 + i}_kamera_game_{i + 1}.png'))
print('ok 10+')
