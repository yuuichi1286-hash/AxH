"""Render filmstrip of a clip: python filmstrip.py bundle clipname out.png [nframes] [texture.png]"""
import sys, os, math
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import numpy as np, UnityPy
from PIL import Image, ImageDraw
from fk import Rig, clip_overrides
from render_obj import render

def render_world(V, T, F, tex, size, yaw=0.6, pitch=0.5, center=None, extent=2.2):
    # camera similar to MOBA top-down view; fixed framing (center/extent) so motion is visible
    import render_obj as ro
    Vv = V.copy(); Vv[:, 0] *= -1
    cy, sy = math.cos(yaw), math.sin(yaw)
    R = np.array([[cy, 0, sy], [0, 1, 0], [-sy, 0, cy]])
    cp, spp = math.cos(pitch), math.sin(pitch)
    P = np.array([[1, 0, 0], [0, cp, -spp], [0, spp, cp]])
    c = np.array(center if center is not None else [0, 0.9, 0.0]); c[0] *= -1
    Vc = (Vv - c) @ R.T @ P.T
    # hack: append two far points to fix scale via render()'s bbox normalisation
    pad = np.array([[extent, extent, 0], [-extent, -extent, 0]])
    Vall = np.vstack([Vc, pad]); Tall = np.vstack([T, [[0, 0], [0, 0]]])
    return render(Vall, Tall, F, tex, 0.0, size, 0.0)

def main():
    bundle, clipname, out = sys.argv[1], sys.argv[2], sys.argv[3]
    nfr = int(sys.argv[4]) if len(sys.argv) > 4 else 10
    texp = sys.argv[5] if len(sys.argv) > 5 else None
    rig = Rig(bundle)
    clip = [o for o in rig.env.objects if o.type.name == 'AnimationClip' and o.read_typetree()['m_Name'] == clipname][0].read_typetree()
    start, stop = clip['m_MuscleClip']['m_StartTime'], clip['m_MuscleClip']['m_StopTime']
    times = np.linspace(start, stop, nfr)
    ovs, acts = clip_overrides(rig, clip, times)
    tex = np.asarray(Image.open(texp).convert('RGB'), np.float32) / 255.0 if texp else np.ones((4, 4, 3), np.float32) * 0.8
    tiles = []
    for t, ov, act in zip(times, ovs, acts):
        W = rig.pose(ov)
        Vs = []; Ts = []; Fs = []; off = 0
        for smr in rig.smrs:
            name = smr['name']
            goact = act.get(smr['go']['m_Name'], smr['go']['m_IsActive'])
            if not goact: continue
            V = rig.skin(smr, W)
            d = smr['d']; tri = d['index'].reshape(-1, 3)
            Vs.append(V); Ts.append(d['uv0'].astype(np.float64)); Fs += [[(a + off, a + off), (b + off, b + off), (c + off, c + off)] for a, b, c in tri]
            off += len(V)
        V = np.vstack(Vs); T = np.vstack(Ts)
        im = render_world(V, T, Fs, tex, 300)
        img = Image.fromarray(im); ImageDraw.Draw(img).text((6, 6), f'{clipname} t={t:.2f}', fill=(255, 255, 0))
        tiles.append(np.asarray(img))
    rows = [np.concatenate(tiles[i:i + 5], 1) for i in range(0, len(tiles), 5)]
    w = max(r.shape[1] for r in rows)
    rows = [np.pad(r, ((0, 0), (0, w - r.shape[1]), (0, 0))) for r in rows]
    Image.fromarray(np.concatenate(rows, 0)).save(out)
if __name__ == "__main__":
    main()
