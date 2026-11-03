"""Build Hidan Revamp (v3) from the original Hidan.Revamp.zip contents.

usage: python build.py <original HIDAN dir> <output HIDAN dir> <report.json> [workers]
"""
import sys, os, json, shutil, time, collections
from concurrent.futures import ProcessPoolExecutor
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import numpy as np
import UnityPy
from PIL import Image

from fk import Rig
from meshio import decode
from anim_fix import ClipFixer, fix_controller
import mesh_tess
import model_tex
import vfx_fix
import fx_tex
import cinematic
from effect_timing import analyse as timing_analyse

MODEL_BUNDLES = {'hero_argus_skin.unity3d': 1024, 'hero_argus_skin_high_add.unity3d': 2048}
UNTOUCHED = ('hero_argus.unity3d', 'hero_argus_skin_extlow_add.unity3d', 'heroshow_ip03_add.unity3d')
TOON = {'_ToonThreshold1': 0.12, '_ToonThreshold2': 0.45, '_ToonValue1': 0.66, '_ToonValue2': 0.86, '_ToonValue3': 1.0}


def process_model(env, report, tex_size):
    rig = Rig(env)
    objs = {o.path_id: o for o in env.objects}
    # --- meshes: remember UV islands (for texture padding), then Phong-tessellate
    uv_tris = []
    mesh_rep = {}
    for o in env.objects:
        if o.type.name != 'SkinnedMeshRenderer':
            continue
        s = o.read_typetree()
        if s['m_Mesh']['m_PathID'] == 0:
            continue
        names = [rig.goname[b['m_PathID']] for b in s['m_Bones']]
        rigid = [i for i, n in enumerate(names) if 'Weapon' in n]
        mo = objs[s['m_Mesh']['m_PathID']]
        tt = mo.read_typetree()
        d = decode(tt)
        uv_tris.append(d['uv0'].astype(np.float64)[d['index'].reshape(-1, 3)])
        mesh_rep[tt['m_Name']] = mesh_tess.tessellate_mesh_typetree(tt, rigid_bones=rigid)
        mo.save_typetree(tt)
    report['meshes'] = mesh_rep
    # --- animation clips + controller
    fixer = ClipFixer(rig)
    r = report.setdefault('animations', {})
    for o in env.objects:
        t = o.type.name
        if t == 'AnimationClip':
            tt = o.read_typetree()
            res = fixer.process(tt)
            o.save_typetree(tt)
            r[res['name']] = {k: res[k] for k in ('dur', 'loop', 'worst_deg_per_frame_before', 'worst_deg_per_frame_after')}
        elif t == 'AnimatorController':
            tt = o.read_typetree()
            report['controller_transitions_changed'] = len(fix_controller(tt))
            o.save_typetree(tt)
    # --- texture + material
    for o in env.objects:
        t = o.type.name
        if t == 'Texture2D' and o.read_typetree()['m_Name'] == '777daa':
            new = model_tex.revamp(o.read().image, tex_size, uv_tris)
            size, nmip = model_tex.apply_to_texture_object(o, new)
            report['texture'] = {'name': '777daa', 'size': tex_size, 'format': 'ETC2_RGB4', 'mips': nmip, 'bytes': size}
        elif t == 'Material':
            tt = o.read_typetree()
            if tt['m_Name'] != '777daa':
                continue
            fl = dict((k, v) for k, v in tt['m_SavedProperties']['m_Floats'])
            fl.update(TOON)
            tt['m_SavedProperties']['m_Floats'] = sorted(fl.items())
            o.save_typetree(tt)
            report['material_toon'] = TOON


def process_vfx(env, report, tex_cache, pool, filename=''):
    objs = {o.path_id: o for o in env.objects}
    rmode = {}
    for o in env.objects:
        if o.type.name == 'ParticleSystemRenderer':
            t = o.read_typetree()
            rmode[t['m_GameObject']['m_PathID']] = t['m_RenderMode']
    totals = collections.Counter()
    kind = cinematic.bundle_kind(filename)
    if kind:
        totals[f'cinematic_bundle_{kind}'] = 1
    pending = []
    for o in env.objects:
        t = o.type.name
        if t == 'ParticleSystem':
            tt = o.read_typetree()
            gid = tt['m_GameObject']['m_PathID']
            go = objs[gid].read_typetree()['m_Name'] if gid in objs else ''
            rep = vfx_fix.process_particle_system_v3(tt, go, rmode.get(gid))
            if kind:
                r, done = cinematic.apply_cinematic(tt, go, rmode.get(gid), filename)
                if done:
                    totals[f'cinematic_{r}'] += 1
            o.save_typetree(tt)
            totals['particle_systems'] += 1
            for k, v in rep.items():
                totals[k] += int(v)
        elif t == 'AnimationClip':
            tt = o.read_typetree()
            if tt.get('m_Legacy'):
                n1 = vfx_fix.fade_legacy_clip(tt)
                n3 = cinematic.fix_legacy_popouts(tt)
                if kind:
                    n4 = cinematic.flare_off_clip(tt)
                    totals['passive_off_flare'] += n4
                    n3 += n4
                n2 = vfx_fix.smooth_legacy_tangents(tt)
                if n1 or n2 or n3:
                    o.save_typetree(tt)
                    totals['mesh_alpha_fadein'] += n1
                    totals['mesh_popout_fixed'] += n3
                    totals['mesh_curves_smoothed'] += n2
        elif t == 'Texture2D':
            tt = o.read_typetree()
            img = o.read().image.convert('RGBA')
            fmt, mips = tt['m_TextureFormat'], tt['m_MipCount']
            force = False
            if tt['m_Width'] > 1024 or tt['m_Height'] > 1024:
                force = True
                img = img.resize((min(1024, tt['m_Width']), min(1024, tt['m_Height'])), Image.LANCZOS)
                fmt = 49
                totals['textures_downscaled'] += 1
            key = fx_tex.key_of(img, fmt, mips, tt['m_Name']) + ('F' if force else '')
            pending.append((o, key, img, fmt, mips))
            if key not in tex_cache:
                tex_cache[key] = pool.submit(fx_tex.process_texture_job, (key, img.tobytes(), img.size, fmt, mips, tt['m_Name'], force))
    for o, key, img, fmt, mips in pending:
        k2, data = tex_cache[key].result()
        if data is None:
            continue
        tt = o.read_typetree()
        tt['m_Width'], tt['m_Height'] = img.size
        tt['m_TextureFormat'] = fmt
        tt['m_MipCount'] = mips
        tt['image data'] = data
        tt['m_CompleteImageSize'] = len(data)
        tt['m_StreamData'] = {'offset': 0, 'size': 0, 'path': ''}
        o.save_typetree(tt)
        totals['textures_sharpened'] += 1
    report['vfx'] = dict(totals)


def fix_delay_times(root, margin=0.06):
    """Pass 2: every effect lives at least until its last particle (incl. overlay sub-effects) has faded."""
    paths = {}
    for dp, dn, fn in os.walk(root):
        for f in fn:
            if f.endswith('.unity3d'):
                paths[f[:-len('.unity3d')]] = os.path.join(dp, f)
    ends = {}
    def end_of(stem):
        if stem not in ends:
            mgr, e, loops = timing_analyse(paths[stem])
            ends[stem] = (mgr, e[0][0] if e else 0.0)
        return ends[stem]
    changes = {}
    for stem, path in sorted(paths.items()):
        if stem.startswith('hero_') or stem.startswith('heroshow') or 'Atlas' in stem or stem.startswith('Hero45'):
            continue
        mgr, own = end_of(stem)
        if not mgr or mgr['DelayTime'] >= 7000:
            continue
        last = own
        fi = mgr.get('FilterInfo', {})
        for k in ('strSpliteNode1', 'strSpliteNode2'):
            sub = fi.get(k)
            if sub and sub in paths:
                last = max(last, end_of(sub)[1])
        need = round(last + margin, 3)
        if need > mgr['DelayTime'] + 1e-4:
            env = UnityPy.load(path)
            for o in env.objects:
                if o.type.name == 'MonoBehaviour':
                    try:
                        tt = o.read_typetree()
                    except Exception:
                        continue
                    if 'DelayTime' in tt:
                        changes[stem] = (round(tt['DelayTime'], 3), need)
                        tt['DelayTime'] = float(need)
                        o.save_typetree(tt)
            with open(path, 'wb') as fh:
                fh.write(env.file.save(packer='original'))
    return changes


def main():
    src_root, dst_root, report_path = sys.argv[1:4]
    workers = int(sys.argv[4]) if len(sys.argv) > 4 else 4
    if os.path.exists(dst_root):
        shutil.rmtree(dst_root)
    shutil.copytree(src_root, dst_root)
    report = {}
    t0 = time.time()
    tex_cache = {}
    with ProcessPoolExecutor(max_workers=workers) as pool:
        for dp, dn, fn in sorted(os.walk(dst_root)):
            dn.sort()
            for f in sorted(fn):
                if not f.endswith('.unity3d'):
                    continue
                path = os.path.join(dp, f)
                rel = os.path.relpath(path, dst_root)
                if f in UNTOUCHED or rel.startswith('UI'):
                    continue
                env = UnityPy.load(path)
                rep = {}
                if f in MODEL_BUNDLES:
                    process_model(env, rep, MODEL_BUNDLES[f])
                else:
                    process_vfx(env, rep, tex_cache, pool, f)
                data = env.file.save(packer='original')
                with open(path, 'wb') as fh:
                    fh.write(data)
                report[rel] = rep
                print(f'{rel}: {rep.get("vfx") or "model"}', flush=True)
    report['_delaytime'] = fix_delay_times(dst_root)
    report['_build_seconds'] = round(time.time() - t0, 1)
    with open(report_path, 'w') as fh:
        json.dump(report, fh, indent=1, default=str)


if __name__ == '__main__':
    main()
