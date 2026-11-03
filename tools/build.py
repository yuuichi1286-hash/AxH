"""Build Hidan Revamp v2 from the original Hidan.Revamp.zip contents.

usage: python build.py <original HIDAN dir> <output HIDAN dir> <report.json>
"""
import sys, os, json, shutil, time, collections
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import UnityPy
from PIL import Image

from fk import Rig
from anim_fix import ClipFixer, fix_controller
import model_tex
import vfx_fix

MODEL_BUNDLES = ('hero_argus_skin.unity3d', 'hero_argus_skin_high_add.unity3d')
UNTOUCHED = ('hero_argus.unity3d', 'hero_argus_skin_extlow_add.unity3d', 'heroshow_ip03_add.unity3d')
TOON = {'_ToonThreshold1': 0.12, '_ToonThreshold2': 0.45, '_ToonValue1': 0.66, '_ToonValue2': 0.86, '_ToonValue3': 1.0}


def process_model(env, report):
    rig = Rig(env)
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
            ch = fix_controller(tt)
            o.save_typetree(tt)
            report['controller_transitions_changed'] = len(ch)
        elif t == 'Texture2D':
            tt = o.read_typetree()
            if tt['m_Name'] != '777daa':
                continue
            src = o.read().image
            new = model_tex.revamp(src)
            size, nmip = model_tex.apply_to_texture_object(o, new)
            report['texture'] = {'name': '777daa', 'format': 'ETC2_RGB4', 'mips': nmip, 'bytes': size}
        elif t == 'Material':
            tt = o.read_typetree()
            if tt['m_Name'] != '777daa':
                continue
            fl = dict((k, v) for k, v in tt['m_SavedProperties']['m_Floats'])
            fl.update(TOON)
            tt['m_SavedProperties']['m_Floats'] = sorted(fl.items())
            o.save_typetree(tt)
            report['material_toon'] = TOON


def process_vfx(env, report):
    objs = {o.path_id: o for o in env.objects}
    totals = collections.Counter()
    for o in env.objects:
        t = o.type.name
        if t == 'ParticleSystem':
            tt = o.read_typetree()
            go = objs[tt['m_GameObject']['m_PathID']].read_typetree()['m_Name'] if tt['m_GameObject']['m_PathID'] in objs else ''
            rep = vfx_fix.process_particle_system(tt, go)
            o.save_typetree(tt)
            totals['particle_systems'] += 1
            for k, v in rep.items():
                totals[k] += int(v)
        elif t == 'AnimationClip':
            tt = o.read_typetree()
            if tt.get('m_Legacy'):
                n = vfx_fix.fade_legacy_clip(tt)
                if n:
                    o.save_typetree(tt)
                    totals['mesh_alpha_fadein'] += n
        elif t == 'Texture2D':
            tt = o.read_typetree()
            if tt['m_Width'] > 1024 or tt['m_Height'] > 1024:
                img = o.read().image
                w = min(1024, tt['m_Width']); h = min(1024, tt['m_Height'])
                img = img.resize((w, h), Image.LANCZOS)
                tex = o.read()
                tex.set_image(img, target_format=49)   # ASTC 5x5 (RGB(A)), same family as the other FX textures
                tex.save()
                totals['textures_downscaled'] += 1
    report['vfx'] = dict(totals)


def main():
    src_root, dst_root, report_path = sys.argv[1:4]
    if os.path.exists(dst_root):
        shutil.rmtree(dst_root)
    shutil.copytree(src_root, dst_root)
    report = {}
    t0 = time.time()
    for dp, dn, fn in os.walk(dst_root):
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
                process_model(env, rep)
            else:
                process_vfx(env, rep)
            data = env.file.save(packer='original')
            with open(path, 'wb') as fh:
                fh.write(data)
            report[rel] = rep
            print(f'{rel}: {rep.get("vfx", "") or "model"}', flush=True)
    report['_build_seconds'] = round(time.time() - t0, 1)
    with open(report_path, 'w') as fh:
        json.dump(report, fh, indent=1, default=str)


if __name__ == '__main__':
    main()
