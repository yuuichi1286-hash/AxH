"""Survey Shisui effect bundles -> JSON (materials, shaders, textures, PS colours, legacy clips)."""
import sys, os, json, collections, colorsys
import numpy as np
import UnityPy
from UnityPy.files import BundleFile

root, out = sys.argv[1], sys.argv[2]


def col(c):
    return [round(c[k], 3) for k in 'rgba']


def mmg(g):
    st = g['minMaxState']
    res = {'state': st}
    if st in (0, 2):
        res['max'] = col(g['maxColor'])
        if st == 2:
            res['min'] = col(g['minColor'])
    if st in (1, 3):
        gg = g['maxGradient']
        res['grad'] = [col(gg[f'key{i}'])[:3] for i in range(gg['m_NumColorKeys'])]
        res['alpha'] = [round(gg[f'key{i}']['a'], 2) for i in range(gg['m_NumAlphaKeys'])]
        if st == 3:
            gg = g['minGradient']
            res['grad_min'] = [col(gg[f'key{i}'])[:3] for i in range(gg['m_NumColorKeys'])]
    return res


def curve_max(c):
    st = c['minMaxState']
    if st == 0:
        return c['scalar']
    if st == 3:
        return max(c['scalar'], c['minScalar'])
    vals = [k['value'] for k in c['maxCurve']['m_Curve']] or [1]
    return c['scalar'] * max(vals)


def tex_stats(img):
    a = np.asarray(img.convert('RGBA')).astype(np.float32) / 255
    rgb, al = a[..., :3], a[..., 3]
    mx, mn = rgb.max(-1), rgb.min(-1)
    sat = np.where(mx > 1e-3, (mx - mn) / np.maximum(mx, 1e-3), 0)
    lum = rgb @ np.array([.299, .587, .114])
    vis = (al > 0.1) & (lum > 0.08)
    res = {'alpha_mean': round(float(al.mean()), 3), 'alpha_min': round(float(al.min()), 3),
           'lum_mean': round(float(lum.mean()), 3)}
    if vis.any():
        res['sat_mean'] = round(float(sat[vis].mean()), 3)
        hsv = np.array([colorsys.rgb_to_hsv(*p) for p in rgb[vis][::max(1, vis.sum() // 4000)]])
        colored = hsv[hsv[:, 1] > 0.25]
        if len(colored):
            h = (colored[:, 0] * 360).astype(int) // 30 * 30
            res['hues'] = collections.Counter(h.tolist()).most_common(4)
            res['colored_frac'] = round(len(colored) / len(hsv), 3)
    # channel independence (channel-packed masks)
    if rgb.shape[0] * rgb.shape[1] > 0:
        c = np.corrcoef(rgb.reshape(-1, 3).T + 1e-6 * np.random.RandomState(0).rand(3, rgb.shape[0] * rgb.shape[1]))
        res['chan_corr'] = [round(float(c[0, 1]), 2), round(float(c[0, 2]), 2), round(float(c[1, 2]), 2)]
    return res


data = {}
for dp, dn, fn in sorted(os.walk(root)):
    for f in sorted(fn):
        p = os.path.join(dp, f)
        rel = os.path.relpath(p, root)
        try:
            env = UnityPy.load(p)
            if not isinstance(env.files[list(env.files)[0]], BundleFile):
                data[rel] = {'not_bundle': True}
                continue
        except Exception as e:
            data[rel] = {'error': str(e)}
            continue
        objs = {o.path_id: o for o in env.objects}
        B = {'mgr': None, 'ps': [], 'materials': {}, 'textures': {}, 'clips': [], 'renderers': [], 'gos': {}, 'other': collections.Counter()}
        for o in env.objects:
            t = o.type.name
            B['other'][t] += 1
            if t == 'GameObject':
                tt = o.read_typetree()
                B['gos'][o.path_id] = tt['m_Name']
        for o in env.objects:
            t = o.type.name
            try:
                if t == 'MonoBehaviour':
                    tt = o.read_typetree()
                    if 'DelayTime' in tt:
                        B['mgr'] = {k: tt[k] for k in ('DelayTime', 'FilterInfo', 'ParSysInfo') if k in tt}
                elif t == 'Material':
                    tt = o.read_typetree()
                    sh = tt['m_Shader']
                    ext = None
                    if sh['m_FileID'] > 0:
                        try:
                            ext = o.assets_file.externals[sh['m_FileID'] - 1].path
                        except Exception:
                            ext = '?'
                    sp = tt['m_SavedProperties']
                    B['materials'][o.path_id] = {
                        'name': tt['m_Name'], 'shader': [sh['m_FileID'], sh['m_PathID'], ext],
                        'kw': tt.get('m_ShaderKeywords'), 'queue': tt.get('m_CustomRenderQueue'),
                        'tex': {k: [v['m_Texture']['m_PathID'], [round(v['m_Scale']['x'], 2), round(v['m_Scale']['y'], 2)]] for k, v in sp['m_TexEnvs'] if v['m_Texture']['m_PathID']},
                        'floats': {k: round(v, 3) for k, v in sp['m_Floats']},
                        'colors': {k: col(v) for k, v in sp['m_Colors']}}
                elif t == 'Texture2D':
                    tt = o.read_typetree()
                    d = o.read()
                    st = {}
                    try:
                        st = tex_stats(d.image)
                    except Exception as e:
                        st = {'err': str(e)}
                    B['textures'][o.path_id] = dict(name=tt['m_Name'], w=tt['m_Width'], h=tt['m_Height'], fmt=tt['m_TextureFormat'], mips=tt['m_MipCount'],
                                                    stream=tt['m_StreamData']['size'], wrap=tt['m_TextureSettings']['m_WrapU'], **st)
                elif t == 'ParticleSystem':
                    tt = o.read_typetree()
                    im, cm, em, sm = tt['InitialModule'], tt['ColorModule'], tt['EmissionModule'], tt['SizeModule']
                    B['ps'].append(dict(pid=o.path_id, go=B['gos'].get(tt['m_GameObject']['m_PathID']), gid=tt['m_GameObject']['m_PathID'],
                                        len=round(tt['lengthInSec'], 2), loop=tt['looping'], delay=round(curve_max(tt['startDelay']), 2),
                                        life=round(curve_max(im['startLifetime']), 2), size=round(curve_max(im['startSize']), 3),
                                        speed=round(curve_max(im['startSpeed']), 2), maxp=im['maxNumParticles'],
                                        rate=round(curve_max(em['rateOverTime']), 1) if em['enabled'] else 0,
                                        bursts=[round(curve_max(b['countCurve']), 1) for b in em['m_Bursts']] if em['enabled'] else [],
                                        start=mmg(im['startColor']), colmod=mmg(cm['gradient']) if cm['enabled'] else None,
                                        sizemod=sm['enabled'], shape=tt['ShapeModule']['type'] if tt['ShapeModule']['enabled'] else None,
                                        mods=[m for m in ('NoiseModule', 'TrailModule', 'SubModule', 'LightsModule', 'CollisionModule', 'UVModule', 'VelocityModule', 'ForceModule', 'ClampVelocityModule', 'RotationModule', 'ColorBySpeedModule', 'SizeBySpeedModule', 'CustomDataModule') if m in tt and tt[m]['enabled']],
                                        gravity=round(curve_max(im['gravityModifier']), 2) if isinstance(im['gravityModifier'], dict) else im['gravityModifier'],
                                        scaling=tt.get('scalingMode'), sim=tt.get('moveWithTransform')))
                elif t in ('ParticleSystemRenderer', 'MeshRenderer', 'SkinnedMeshRenderer', 'TrailRenderer', 'LineRenderer'):
                    tt = o.read_typetree()
                    B['renderers'].append(dict(type=t, go=B['gos'].get(tt['m_GameObject']['m_PathID']), gid=tt['m_GameObject']['m_PathID'],
                                               mats=[m['m_PathID'] for m in tt['m_Materials']], rmode=tt.get('m_RenderMode'),
                                               mesh=tt.get('m_Mesh', {}).get('m_PathID') if isinstance(tt.get('m_Mesh'), dict) else None,
                                               enabled=tt.get('m_Enabled')))
                elif t == 'AnimationClip':
                    tt = o.read_typetree()
                    c = dict(name=tt['m_Name'], legacy=tt.get('m_Legacy'), len=None,
                             float=[(x['path'], x['attribute'], len(x['curve']['m_Curve'])) for x in tt['m_FloatCurves']],
                             pos=len(tt['m_PositionCurves']), rot=len(tt['m_RotationCurves']), scale=len(tt['m_ScaleCurves']),
                             euler=len(tt.get('m_EulerCurves', [])), pptr=len(tt.get('m_PPtrCurves', [])),
                             stop=tt['m_MuscleClip']['m_StopTime'] if 'm_MuscleClip' in tt else None)
                    B['clips'].append(c)
            except Exception as e:
                B.setdefault('errors', []).append((t, o.path_id, repr(e)[:200]))
        B['other'] = dict(B['other'])
        B['gos'] = {str(k): v for k, v in B['gos'].items()}
        B['materials'] = {str(k): v for k, v in B['materials'].items()}
        B['textures'] = {str(k): v for k, v in B['textures'].items()}
        data[rel] = B
        print(rel, len(B['ps']), len(B['materials']), len(B['textures']), len(B['clips']), flush=True)
json.dump(data, open(out, 'w'), indent=0, default=str)
