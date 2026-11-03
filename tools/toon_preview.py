"""Approximate the in-game Custom/ToonShadowWithBlobOption_Fixed main pass (incl. the modder's rim/pulse patch)
on a posed, skinned model.  Used only to compare material/texture settings before vs after."""
import sys, os, math
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import numpy as np
from PIL import Image, ImageDraw
from fk import Rig, clip_overrides

def skin_with_normals(rig, smr, W):
    d = smr['d']
    v = np.c_[d['pos'].astype(np.float64), np.ones(len(d['pos']))]
    nrm = d['normal'].astype(np.float64)
    mats = np.array([W[b] @ smr['bind'][i] for i, b in enumerate(smr['bones'])])
    P = np.zeros((len(v), 3)); N = np.zeros((len(v), 3))
    for k in range(4):
        w = d['weights'][:, k].astype(np.float64); idx = d['indices'][:, k].astype(int)
        M = mats[idx]
        P += w[:, None] * np.einsum('nij,nj->ni', M, v)[:, :3]
        N += w[:, None] * np.einsum('nij,nj->ni', M[:, :3, :3], nrm)
    N /= np.linalg.norm(N, axis=1, keepdims=True) + 1e-12
    return P, N

def shade(alb, N, F, mat, pulse=0.5):
    td = np.array(mat['ToonDir'], float); td /= np.linalg.norm(td)
    ndl = np.clip(N @ td, 0, 1)
    band = np.where(ndl < mat['T1'], mat['V1'], np.where(ndl < mat['T2'], mat['V2'], mat['V3']))
    col = band[:, None] * alb
    nf = np.clip(1 - np.abs(N @ F), 0, 1)
    rim = nf ** 3
    ratio = (alb[:, 0] - np.maximum(alb[:, 1], alb[:, 2])) / np.maximum(alb[:, 0], 1e-3)
    def ss(a, b, x):
        t = np.clip((x - a) / (b - a), 0, 1); return t * t * (3 - 2 * t)
    red = ss(0.55, 0.8, ratio) * ss(0.18, 0.4, alb[:, 0])
    col = col + alb * (0.14 * np.clip(-(N @ F), 0, 1))[:, None]
    col = col + alb * (red * (0.35 + 0.45 * pulse))[:, None]
    col = col + np.array([1.0, 0.07, 0.03]) * (rim * (0.55 + 0.5 * pulse))[:, None]
    return np.minimum(col, 1.0)

def render(P, N, UV, tris, tex, mat, size=420, pitch=math.radians(50), yaw=math.radians(25), extent=1.15, center=(0, 0.95, 0)):
    H = W = size
    cy, sy = math.cos(yaw), math.sin(yaw)
    Ry = np.array([[cy, 0, -sy], [0, 1, 0], [sy, 0, cy]])
    cp, sp = math.cos(pitch), math.sin(pitch)
    Rx = np.array([[1, 0, 0], [0, cp, sp], [0, -sp, cp]])
    R = Rx @ Ry                       # world -> camera (camera looks along +z_cam)
    Pc = (P - np.array(center)) @ R.T
    F = R.T @ np.array([0, 0, 1.0])   # camera forward in world
    sc = size / (2 * extent)
    X = Pc[:, 0] * sc + W / 2; Y = -Pc[:, 1] * sc + H / 2; Z = -Pc[:, 2]
    img = np.zeros((H, W, 3), np.float32); img[:] = (0.20, 0.22, 0.20)
    zb = np.full((H, W), -1e9, np.float32)
    th, tw = tex.shape[:2]
    for t in tris:
        x, y, z = X[t], Y[t], Z[t]
        x0, x1 = int(max(0, math.floor(x.min()))), int(min(W - 1, math.ceil(x.max())))
        y0, y1 = int(max(0, math.floor(y.min()))), int(min(H - 1, math.ceil(y.max())))
        if x1 < x0 or y1 < y0: continue
        xs, ys = np.meshgrid(np.arange(x0, x1 + 1) + 0.5, np.arange(y0, y1 + 1) + 0.5)
        d = (y[1] - y[2]) * (x[0] - x[2]) + (x[2] - x[1]) * (y[0] - y[2])
        if abs(d) < 1e-9: continue
        w0 = ((y[1] - y[2]) * (xs - x[2]) + (x[2] - x[1]) * (ys - y[2])) / d
        w1 = ((y[2] - y[0]) * (xs - x[2]) + (x[0] - x[2]) * (ys - y[2])) / d
        w2 = 1 - w0 - w1
        m = (w0 >= -1e-4) & (w1 >= -1e-4) & (w2 >= -1e-4)
        if not m.any(): continue
        zz = w0 * z[0] + w1 * z[1] + w2 * z[2]
        sub = zb[y0:y1 + 1, x0:x1 + 1]
        m &= zz > sub
        if not m.any(): continue
        uv = UV[t]
        u = w0 * uv[0, 0] + w1 * uv[1, 0] + w2 * uv[2, 0]; v = w0 * uv[0, 1] + w1 * uv[1, 1] + w2 * uv[2, 1]
        tx = np.clip((u % 1.0) * tw, 0, tw - 1).astype(int); ty = np.clip((1 - (v % 1.0)) * th, 0, th - 1).astype(int)
        alb = tex[ty[m], tx[m]]
        n = N[t]
        nn = w0[m, None] * n[0] + w1[m, None] * n[1] + w2[m, None] * n[2]
        nn /= np.linalg.norm(nn, axis=1, keepdims=True) + 1e-9
        col = shade(alb, nn, F, mat)
        sub[m] = zz[m]
        img[y0:y1 + 1, x0:x1 + 1][m] = col
    return (np.clip(img, 0, 1) * 255).astype(np.uint8)

def posed(rig, clipname, t, meshes=None):
    clip = [o for o in rig.env.objects if o.type.name == 'AnimationClip' and o.read_typetree()['m_Name'] == clipname][0].read_typetree()
    ovs, acts = clip_overrides(rig, clip, [t])
    W = rig.pose(ovs[0])
    Ps, Ns, UVs, Ts, off = [], [], [], [], 0
    for smr in rig.smrs:
        active = acts[0].get(smr['go']['m_Name'], smr['go']['m_IsActive'])
        if meshes is not None:
            active = smr['name'] in meshes
        if not active: continue
        P, N = skin_with_normals(rig, smr, W)
        Ps.append(P); Ns.append(N); UVs.append(smr['d']['uv0'].astype(np.float64)); Ts.append(smr['d']['index'].reshape(-1, 3) + off); off += len(P)
    return np.vstack(Ps), np.vstack(Ns), np.vstack(UVs), np.vstack(Ts)
