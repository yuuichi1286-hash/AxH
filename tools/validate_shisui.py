"""Validate the Shisui x Suyou build against the originals.

usage: python validate_shisui.py <orig fx root> <orig model root> <new fx root> <new model root>

checks: byte-identical untouched files, bundle headers / internal names / object sets, every object re-reads,
texture decode + orientation + format/mip sizes, palette (every coloured particle / material colour of the
effects is green, except the kept Sharingan / blood / object elements), fade-in/out of every particle system,
DelayTime covers the last fade (incl. split overlays), icon atlas only changed inside the Suyou sprites.
"""
import sys, os, collections, colorsys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import numpy as np
import UnityPy
from UnityPy.files import BundleFile
from PIL import Image
import brutal, green
from vfx_fix import get_alpha, get_colors, interp, interp_col
from effect_timing import analyse as timing_analyse

o_fx, o_model, n_fx, n_model = sys.argv[1:5]
problems = 0


def bad(*a):
    global problems
    problems += 1
    print('PROBLEM', *a)


def bundle(path):
    try:
        env = UnityPy.load(path)
        return env if isinstance(env.files[list(env.files)[0]], BundleFile) else None
    except Exception:
        return None


UNTOUCHED_EXPECTED = ('hero_kaijiacike_skin.unity3d', 'Hero1261_add.unity3d', '.bnk', 'Kaijiacike_skill03_ui.unity3d')
stats = collections.Counter()
green_hits = collections.Counter()
nongreen = []
tex_report = []

for o_root, n_root in ((o_fx, n_fx), (o_model, n_model)):
    for dp, dn, fn in sorted(os.walk(o_root)):
        for f in sorted(fn):
            po = os.path.join(dp, f); rel = os.path.relpath(po, o_root); pn = os.path.join(n_root, rel)
            if not os.path.exists(pn):
                bad('MISSING', rel); continue
            bo, bn = open(po, 'rb').read(), open(pn, 'rb').read()
            if bo == bn:
                stats['identical'] += 1
                continue
            if f.endswith(UNTOUCHED_EXPECTED):
                bad('should be untouched', rel); continue
            stats['changed'] += 1
            eo, en = bundle(po), bundle(pn)
            if eo is None or en is None:
                bad('not a bundle', rel); continue
            fo = list(eo.files.values())[0]; fnn = list(en.files.values())[0]
            if (int(fo.dataflags), fo._block_info_flags, fo.version, fo.version_engine) != (int(fnn.dataflags), fnn._block_info_flags, fnn.version, fnn.version_engine):
                bad('HEADER FLAGS DIFFER', rel)
            if list(fo.files.keys()) != list(fnn.files.keys()):
                bad('INTERNAL NAMES DIFFER', rel)
            co = collections.Counter((o.type.name, o.path_id) for o in eo.objects)
            cn = collections.Counter((o.type.name, o.path_id) for o in en.objects)
            if co != cn:
                bad('OBJECT SET DIFFERS', rel)
            mo = {o.path_id: o for o in eo.objects}
            gos = {}
            for o in en.objects:
                try:
                    tn = o.read_typetree()
                    to = mo[o.path_id].read_typetree()
                except Exception as e:
                    bad('READ FAIL', rel, o.type.name, e); continue
                if set(tn.keys()) != set(to.keys()):
                    bad('KEYSET DIFF', rel, o.type.name)
                if o.type.name == 'GameObject':
                    gos[o.path_id] = tn['m_Name']
            # ---- textures
            for o in en.objects:
                if o.type.name != 'Texture2D':
                    continue
                d = o.read(); od = mo[o.path_id].read()
                try:
                    img = d.image.convert('RGBA')
                except Exception as e:
                    bad('TEX DECODE', rel, d.m_Name, e); continue
                tt = o.read_typetree()
                if tt['m_StreamData']['size'] == 0 and tt['m_CompleteImageSize'] != len(tt['image data']):
                    bad('TEX SIZE FIELD', rel, d.m_Name)
                if (d.m_Width, d.m_Height) != (od.m_Width, od.m_Height):
                    stats['tex_upscaled'] += 1
                    if max(d.m_Width, d.m_Height) > 512 and max(od.m_Width, od.m_Height) <= 256:
                        bad('TEX TOO BIG', rel, d.m_Name)
                # visible signal = value (max channel, kept by the recolour) x alpha: invisible texels do not count
                def vis(im_):
                    x = np.asarray(im_.convert('RGBA'), np.float32) / 255.0
                    return x[..., :3].max(-1) * x[..., 3] * 255.0
                a = vis(img.resize((od.m_Width, od.m_Height), Image.BILINEAR))
                b = vis(od.image)
                if a.std() > 2 and b.std() > 2:
                    c = np.corrcoef(a.ravel(), b.ravel())[0, 1]
                    cf = np.corrcoef(a[::-1].ravel(), b.ravel())[0, 1]
                    if c < 0.8 or (cf > c and abs(cf - c) > 0.02):
                        bad(f'TEX ORIENTATION/CONTENT {rel} {d.m_Name} corr {c:.3f} flipped {cf:.3f}')
                    stats['tex_checked'] += 1
            # ---- palette of particle systems and materials (effects only)
            rm = {}
            for o in en.objects:
                if o.type.name == 'ParticleSystemRenderer':
                    t = o.read_typetree(); rm[t['m_GameObject']['m_PathID']] = t['m_RenderMode']
            for o in en.objects:
                if o.type.name != 'ParticleSystem':
                    continue
                tt = o.read_typetree()
                go = gos.get(tt['m_GameObject']['m_PathID'], '')
                keep = brutal.role(go, rm.get(tt['m_GameObject']['m_PathID'])) == 'keep'
                sc = tt['InitialModule']['startColor']
                starts = [c for c in green.minmax_gradient_colors(sc)]
                gr = tt['ColorModule']['gradient']
                for t in (0.1, 0.4, 0.8):
                    over = interp_col(get_colors(gr['maxGradient']), t) if gr['minMaxState'] in (1, 3) else np.ones(3)
                    for c in starts:
                        col = np.array([c['r'], c['g'], c['b']]) * over
                        s, v = green.sat_val(col)
                        if s < 0.15 or v < 0.03:
                            continue
                        h = colorsys.rgb_to_hsv(*np.clip(col / max(col.max(), 1e-6), 0, 1))[0] * 360
                        is_green = 90 <= h <= 175
                        green_hits['keep' if keep else ('green' if is_green else 'other')] += 1
                        if not keep and not is_green and len(nongreen) < 25:
                            nongreen.append((rel.split('/')[-1][:40], go, round(h), tuple(np.round(col, 2))))
                # fades
                grads = [gr['maxGradient']] + ([gr['minGradient']] if gr['minMaxState'] == 3 else [])
                ok = tt['ColorModule']['enabled'] and gr['minMaxState'] in (1, 3) and all(
                    interp(get_alpha(g), 0.0) <= 0.02 and interp(get_alpha(g), 1.0) <= 0.02 for g in grads)
                stats['ps'] += 1
                if not ok:
                    bad('NO FADE', rel, go)
                if tt['InitialModule']['maxNumParticles'] > 200:
                    bad('TOO MANY PARTICLES', rel, go, tt['InitialModule']['maxNumParticles'])
            print(f'{rel:75s} {len(bo):>9d} -> {len(bn):>9d}')

print('\n', dict(stats))
tot = green_hits['green'] + green_hits['other']
print(f"PALETTE particle colours: green {green_hits['green']}, other {green_hits['other']} ({100.0 * green_hits['green'] / max(tot, 1):.1f}% green), kept (Sharingan/objects) {green_hits['keep']}")
for x in nongreen:
    print('   non-green:', x)

# ---- DelayTime covers the last fade of every effect incl. overlays
paths = {}
for dp, dn, fn in os.walk(n_fx):
    for f in fn:
        if f.endswith('.unity3d'):
            paths[f[:-len('.unity3d')]] = os.path.join(dp, f)
cache = {}


def tend(stem):
    if stem not in cache:
        mgr, e, loops = timing_analyse(paths[stem]); cache[stem] = (mgr, e[0][0] if e else 0.0)
    return cache[stem]


cut = checked = 0
for stem in sorted(paths):
    mgr, own = tend(stem)
    if not mgr or mgr['DelayTime'] >= 7000:
        continue
    last = own
    for k in ('strSpliteNode1', 'strSpliteNode2'):
        sub = mgr.get('FilterInfo', {}).get(k)
        if sub and sub in paths:
            last = max(last, tend(sub)[1])
    checked += 1
    if last > mgr['DelayTime'] + 1e-3:
        cut += 1; bad(f'TIMING CUT {stem}: last fade {last:.2f} > DelayTime {mgr["DelayTime"]:.2f}')
print(f'TIMING effects checked {checked}, cut before fade end: {cut}', 'OK' if cut == 0 else 'BAD')

# ---- icon atlas: only the Suyou sprites changed
import icons
ao = os.path.join(o_model, 'Ui/android/Atlas_SkillIconAdd35_add.unity3d')
an = os.path.join(n_model, 'Ui/android/Atlas_SkillIconAdd35_add.unity3d')
if os.path.exists(ao):
    def main_and_sprites(p):
        env = UnityPy.load(p); tex = None; spr = {}
        for o in env.objects:
            if o.type.name == 'Texture2D' and o.read_typetree()['m_Name'] == icons.MAIN:
                tex = np.asarray(o.read().image.convert('RGB')).astype(int)
            elif o.type.name == 'MonoBehaviour':
                try:
                    t = o.read_typetree()
                except Exception:
                    continue
                for s in t.get('mSprites', []):
                    spr[s['name']] = (s['x'], s['y'], s['width'], s['height'])
        return tex, spr
    A, spr = main_and_sprites(ao); B, spr2 = main_and_sprites(an)
    diff = np.abs(A - B).max(-1) > 0
    inside = np.zeros_like(diff)
    for n in icons.SPRITES:
        x, y, w, h = spr[n]
        inside[max(0, y - 3):y + h + 3, max(0, x - 3):x + w + 3] = True
    other = [n for n, (x, y, w, h) in spr.items() if n not in icons.SPRITES and diff[y:y + h, x:x + w].any()]
    print(f'ICONS changed px inside Suyou sprites {int((diff & inside).sum())}, outside {int((diff & ~inside).sum())}, other sprites touched: {other}',
          'OK' if not other and not (diff & ~inside).any() else 'BAD')
    if other or (diff & ~inside).any():
        problems += 1
print(f'\nPROBLEMS: {problems}')
