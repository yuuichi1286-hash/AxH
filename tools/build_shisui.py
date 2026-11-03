"""Build "Shisui x Suyou" (dark-green, brutal, HD) from the original effect + model/UI packages.

usage: python build_shisui.py <orig fx root (Art/..)> <orig model root> <out fx root> <out model root> <report.json> [workers]

fx root    : the effects package (Art/android/k, zzp1_k, zzp2_k)
model root : the skin package (Art/android/h, Audio, Ui)
"""
import sys, os, json, shutil, time, collections
from concurrent.futures import ProcessPoolExecutor
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import numpy as np
import UnityPy
from UnityPy.files import BundleFile

import green
import brutal
import vfx_fix
import cinematic
import fx_tex_hd
import icons
from build import fix_delay_times

BLEND_SHADERS = {-261248505249825764}           # alpha-blended uber effect shader (DG_blend, smoke, ...)
ADD_SHADERS = {3087322254700502312}             # additive uber effect shader (DG_add, glows, ...)
KEEP_TEXTURES = {
    'Special_FHD_CJQ_0083_00000_00000', 'Special_FHD_CJQ_0084',   # Sharingan / Mangekyo Sharingan stay red
    'Special_HD_CJQ_0298',                                          # bleeding eye
    'Special_HD_ZXD_0100', 'Special_HD_ZXD_0102', 'Special_HD_ZXD_0097',   # character art / scroll (easter egg)
    'Special_HD_WMD_0315',                                          # substitution log (wood)
    'Special_HD_ZXD_0094',                                          # shuriken (metal)
}
UNTOUCHED = ('hero_kaijiacike_skin.unity3d', 'Hero1261_add.unity3d')
ICON_ATLAS = 'Atlas_SkillIconAdd35_add.unity3d'


def is_bundle(path):
    try:
        env = UnityPy.load(path)
        return isinstance(env.files[list(env.files)[0]], BundleFile)
    except Exception:
        return False


def blend_mode(mat_tt, go_name=''):
    sid = mat_tt['m_Shader']['m_PathID']
    if sid in BLEND_SHADERS:
        return 'blend'
    if sid in ADD_SHADERS:
        return 'add'
    fl = dict(mat_tt['m_SavedProperties']['m_Floats'])
    if (fl.get('_SrcBlend'), fl.get('_DstBlend')) == (5.0, 10.0):
        return 'blend'
    if (fl.get('_SrcBlend'), fl.get('_DstBlend')) in ((5.0, 1.0), (1.0, 1.0)):
        return 'add'
    tk = brutal.tokens(go_name) + brutal.tokens(mat_tt['m_Name'])
    if any(t in ('bl', 'blend', 'an') or t.startswith(('hei', 'andi', 'smoke', 'yan')) for t in tk):
        return 'blend'
    return 'add'


def colored_fraction(img):
    a = np.asarray(img).astype(np.float32) / 255.0
    rgb = a[..., :3]
    mx, mn = rgb.max(-1), rgb.min(-1)
    sat = np.where(mx > 1e-3, (mx - mn) / np.maximum(mx, 1e-3), 0)
    vis = (a[..., 3] > 0.1) & (mx > 0.08)
    if not vis.any():
        return 0.0, 0.0
    return float((sat[vis] > 0.25).mean()), float(sat[vis].mean())


def channel_packed(img):
    a = np.asarray(img.convert('RGB')).astype(np.float32).reshape(-1, 3)
    if a.std(0).min() < 1.0:
        return False
    c = np.corrcoef(a.T)
    return abs(c[0, 1]) < 0.5 and abs(c[0, 2]) < 0.5 and abs(c[1, 2]) < 0.5


def process_bundle(env, filename, report, tex_cache, pool):
    objs = {o.path_id: o for o in env.objects}
    totals = collections.Counter()
    cls = brutal.bundle_class(filename)
    gos, mats, texs, renderers = {}, {}, {}, {}
    for o in env.objects:
        t = o.type.name
        if t == 'GameObject':
            gos[o.path_id] = o.read_typetree()['m_Name']
        elif t == 'Material':
            mats[o.path_id] = o.read_typetree()
    for o in env.objects:
        if o.type.name in ('ParticleSystemRenderer', 'MeshRenderer', 'SkinnedMeshRenderer', 'TrailRenderer', 'LineRenderer'):
            tt = o.read_typetree()
            gid = tt['m_GameObject']['m_PathID']
            renderers[gid] = (o.type.name, tt.get('m_RenderMode'), [m['m_PathID'] for m in tt['m_Materials'] if m['m_FileID'] == 0])
    # ---- textures: names, slots, keep flags
    tex_name = {}
    for o in env.objects:
        if o.type.name == 'Texture2D':
            tex_name[o.path_id] = o.read_typetree()['m_Name']
    tex_slots = collections.defaultdict(set)
    tex_keep = set()
    mat_keep = set()
    mat_users = collections.defaultdict(list)
    for gid, (rt, rm, ml) in renderers.items():
        for m in ml:
            mat_users[m].append(gos.get(gid, ''))
    for mid, m in mats.items():
        diffuse_keep = False
        for slot, te in m['m_SavedProperties']['m_TexEnvs']:
            pid = te['m_Texture']['m_PathID']
            if pid and te['m_Texture']['m_FileID'] == 0 and pid in tex_name:
                tex_slots[pid].add(slot)
                if tex_name[pid] in KEEP_TEXTURES and fx_tex_hd.slot_kind(slot) != 'data':
                    diffuse_keep = True
        if diffuse_keep or any(brutal.role(u, None) == 'keep' for u in mat_users.get(mid, [])):
            mat_keep.add(mid)
    for mid in mat_keep:
        for slot, te in mats[mid]['m_SavedProperties']['m_TexEnvs']:
            if te['m_Texture']['m_PathID'] and fx_tex_hd.slot_kind(slot) != 'data':
                tex_keep.add(te['m_Texture']['m_PathID'])
    # colour content of diffuse textures (for chain tint decisions)
    tex_img, tex_col = {}, {}
    for o in env.objects:
        if o.type.name == 'Texture2D':
            img = o.read().image.convert('RGBA')
            tex_img[o.path_id] = img
            tex_col[o.path_id] = colored_fraction(img)[0]

    def mat_info(mid):
        m = mats.get(mid)
        if m is None:                                   # material lives in another bundle
            return 'add', False, False
        diffuse_colored = any(tex_col.get(te['m_Texture']['m_PathID'], 0) > 0.2 for slot, te in m['m_SavedProperties']['m_TexEnvs']
                              if te['m_Texture']['m_PathID'] and fx_tex_hd.slot_kind(slot) in ('diffuse', 'other'))
        users = mat_users.get(mid, [''])
        return blend_mode(m, users[0] if users else ''), (green.material_tints(m) or diffuse_colored), mid in mat_keep

    # ---- particle systems
    for o in env.objects:
        if o.type.name != 'ParticleSystem':
            continue
        tt = o.read_typetree()
        gid = tt['m_GameObject']['m_PathID']
        go = gos.get(gid, '')
        rt, rmode, ml = renderers.get(gid, (None, None, []))
        mode, tint, keep = mat_info(ml[0]) if ml else ('add', False, False)
        keep = keep or brutal.role(go, rmode) == 'keep'
        if not keep:
            totals['ps_color_keys'] += green.recolor_particle_system(tt, mode, tint)
        rep = vfx_fix.process_particle_system_v3(tt, go, rmode, palette='green', budget=48)
        for k, v in rep.items():
            totals[k] += int(v)
        r, done = brutal.apply(tt, go, rmode, cls)
        totals[f'role_{r}'] += 1
        for k in done:
            totals[f'brutal_{k}'] += 1
        o.save_typetree(tt)
        totals['particle_systems'] += 1
    # ---- materials
    name_to_gid0 = {}
    for gid, nm in gos.items():
        name_to_gid0.setdefault(nm, gid)
    for mid, m in mats.items():
        if mid in mat_keep:
            totals['materials_kept'] += 1
            continue
        users = mat_users.get(mid, [''])
        mode = blend_mode(m, users[0] if users else '')
        n = green.recolor_material(m, mode)
        # thunderous cores: additive flashes / lightning / shock rings of combat effects burn 15 % hotter
        roles = {brutal.role(u, renderers.get(name_to_gid0.get(u), (None, None, []))[1]) for u in users}
        if cls == 'combat' and mode == 'add' and users and roles <= {'flash', 'lightning', 'ring'}:
            fl = m['m_SavedProperties']['m_Floats']
            for i, (k, v) in enumerate(fl):
                if k == '_Intensity' and 0 < v < 4:
                    fl[i] = (k, float(min(4.0, v * 1.15)))
                    n += 1
                    totals['material_intensity_boost'] += 1
        if n:
            objs[mid].save_typetree(m)
            totals['material_props_recolored'] += n
    # ---- legacy clips (mesh effects)
    name_to_gid = {}
    for gid, n in gos.items():
        name_to_gid.setdefault(n, gid)

    def mode_of_path(path):
        gid = name_to_gid.get(path.split('/')[-1])
        rt, rm, ml = renderers.get(gid, (None, None, []))
        return mat_info(ml[0])[0] if ml else 'add'

    def keep_path(path):
        gid = name_to_gid.get(path.split('/')[-1])
        rt, rm, ml = renderers.get(gid, (None, None, []))
        return brutal.role(path.split('/')[-1], None) == 'keep' or any(m in mat_keep for m in ml)

    for o in env.objects:
        if o.type.name != 'AnimationClip':
            continue
        tt = o.read_typetree()
        if not tt.get('m_Legacy'):
            continue
        n1 = vfx_fix.fade_legacy_clip(tt)
        n3 = cinematic.fix_legacy_popouts(tt)
        n4 = green.recolor_legacy_clip(tt, mode_of_path, keep_path)
        n2 = vfx_fix.smooth_legacy_tangents(tt)
        if n1 or n2 or n3 or n4:
            o.save_typetree(tt)
            totals['mesh_alpha_fadein'] += n1
            totals['mesh_popout_fixed'] += n3
            totals['mesh_color_curves_green'] += n4
            totals['mesh_curves_smoothed'] += n2
    # ---- textures
    pending = []
    for o in env.objects:
        if o.type.name != 'Texture2D':
            continue
        tt = o.read_typetree()
        name = tt['m_Name']
        img = tex_img[o.path_id]
        slots = tex_slots.get(o.path_id, set())
        keep = o.path_id in tex_keep or name in KEEP_TEXTURES
        n = name.lower()
        if n.endswith(('_m', '_n', '_normal', '_mask')) or (('pbs' in n or 'mask' in n) and channel_packed(img)):
            totals['textures_data_skipped'] += 1
            continue
        plan = fx_tex_hd.plan_for(name, tt['m_Width'], tt['m_Height'], tt['m_TextureFormat'], slots or {'_Diffuse'}, keep)
        if plan is None:
            totals['textures_data_skipped'] += 1
            continue
        fmt, mips = tt['m_TextureFormat'], tt['m_MipCount']
        if fmt not in (3, 4, 34, 47) and fmt not in fx_tex_hd.ASTC_BLOCKS:
            totals[f'textures_unsupported_fmt_{fmt}'] += 1
            continue
        key = fx_tex_hd.key_of(img, fmt, mips, plan)
        pending.append((o, key))
        if key not in tex_cache:
            tex_cache[key] = pool.submit(fx_tex_hd.process_texture_job, (key, img.tobytes(), img.size, fmt, mips, name, plan))
        totals['textures_recolored' if plan[0] else 'textures_kept_colour'] += 1
        totals['textures_upscaled_2x'] += plan[2] == 2
    for o, key in pending:
        k2, data, size, new_mips, cov = tex_cache[key].result()
        tt = o.read_typetree()
        tt['m_Width'], tt['m_Height'] = size
        tt['m_MipCount'] = new_mips
        tt['image data'] = data
        tt['m_CompleteImageSize'] = len(data)
        tt['m_StreamData'] = {'offset': 0, 'size': 0, 'path': ''}
        o.save_typetree(tt)
        totals['textures_written'] += 1
    report['fx'] = dict(totals)
    report['class'] = cls


def walk_bundles(root):
    out = []
    for dp, dn, fn in sorted(os.walk(root)):
        dn.sort()
        for f in sorted(fn):
            out.append(os.path.join(dp, f))
    return out


def main():
    fx_src, model_src, fx_dst, model_dst, report_path = sys.argv[1:6]
    workers = int(sys.argv[6]) if len(sys.argv) > 6 else 4
    for s, d in ((fx_src, fx_dst), (model_src, model_dst)):
        if os.path.exists(d):
            shutil.rmtree(d)
        shutil.copytree(s, d)
    report = {}
    t0 = time.time()
    tex_cache = {}
    with ProcessPoolExecutor(max_workers=workers) as pool:
        for root in (fx_dst, model_dst):
            for path in walk_bundles(root):
                f = os.path.basename(path)
                rel = os.path.relpath(path, root)
                if not f.endswith('.unity3d') or f in UNTOUCHED:
                    continue
                if not is_bundle(path):
                    report[rel] = {'skipped': 'not an asset bundle (kept byte-identical)'}
                    continue
                env = UnityPy.load(path)
                rep = {}
                if f == ICON_ATLAS:
                    rep['icons'] = icons.process_atlas(env)
                else:
                    process_bundle(env, f, rep, tex_cache, pool)
                with open(path, 'wb') as fh:
                    fh.write(env.file.save(packer='original'))
                report[rel] = rep
                print(f'{rel}: {rep}', flush=True)
    report['_delaytime'] = fix_delay_times(fx_dst)
    report['_build_seconds'] = round(time.time() - t0, 1)
    with open(report_path, 'w') as fh:
        json.dump(report, fh, indent=1, default=str)


if __name__ == '__main__':
    main()
