"""Hidan's triple-bladed scythe from the detailed model (hero_argus_skin_extlow_add) on the main model.

The main model (hero_argus_skin / _high_add, meshes 'noraml' and 'ulti') already swings a simple scythe on the
L_Weapon bone; it is the weapon of every attack. That scythe is replaced by the detailed one of the extlow model
(badninja_skin04_weapon: steel blade edges, wrapped grip, 993 vertices):

* placement: the new scythe gets the old one's frame in L_Weapon space: shaft along the same axis, blades on the
  same side and in the same plane, the hand on the wrapped grip, the blade end as far from the hand as before (so
  the animations keep their reach and clearance); rigidly skinned to L_Weapon
* texture: the scythe's part of the 4096x1024 extlow atlas is graded like the rest of the model and placed in a
  free square of the 2048 atlas (the old scythe's texels are free now); the atlas is rebuilt once from the original
  texture (model_tex.revamp steps, then padding and ETC2 + mips), so nothing is compressed twice
* the black spike (R_Weapon) stays

usage: python scythe.py <original HIDAN dir> <HIDAN dir, modified in place>
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import numpy as np
import UnityPy
from PIL import Image
from fk import Rig
from meshio import decode, encode
import mesh_tess
import model_tex

SIZE = 2048
BUNDLES = ('hero_argus_skin.unity3d', 'hero_argus_skin_high_add.unity3d')
EXT = 'hero_argus_skin_extlow_add.unity3d'


def _frame(P):
    """scythe points -> (point on the shaft line, shaft axis butt->top, blade direction, length along the axis)"""
    m = P.mean(0)
    _, _, vt = np.linalg.svd(P - m, full_matrices=False)
    a = vt[0]
    t = (P - m) @ a
    lo, hi = t.min(), t.max()
    u = (t - lo) / (hi - lo)
    spread = lambda sel: np.linalg.norm((P[sel] - m) - np.outer(t[sel], a), axis=1).mean()
    if spread(u < 0.3) > spread(u > 0.7):        # blades are at the top end
        a, t = -a, -t
        lo, hi = t.min(), t.max()
        u = (t - lo) / (hi - lo)
    shaft = u < 0.4
    c = P[shaft].mean(0)
    c = c - a * ((c - m) @ a)                      # point on the shaft line (axis through it)
    off = (P - c) - np.outer((P - c) @ a, a)
    b = off[u > 0.5].mean(0)
    b /= np.linalg.norm(b)
    return c, a, b, u, (P - c) @ a


def _bone_index(smr_tt, rig, name):
    names = [rig.goname[b['m_PathID']] for b in smr_tt['m_Bones']]
    return names.index(name)


def _mesh_space(rig, smr, bone_i, W):
    """world (bind pose) -> mesh space for a vertex rigid on bone_i"""
    return np.linalg.inv(W[smr['bones'][bone_i]] @ smr['bind'][bone_i])


def extlow_scythe(root):
    rig = Rig(os.path.join(root, 'Art', 'Android', 'h', EXT))
    W = rig.pose({})
    s = [s for s in rig.smrs if s['name'] == 'badninja_skin04_weapon'][0]
    P = rig.skin(s, W)
    tex = [o.read() for o in rig.env.objects if o.type.name == 'Texture2D' and o.read().m_Name == 'badninja_skin04_pbs_d'][0]
    img = np.asarray(tex.image.convert('RGB'), np.float32) / 255.0
    d = s['d']
    # normals: rigid in the source too (one bone) -> rotate with the bone's world matrix
    R = (W[s['bones'][0]] @ s['bind'][0])[:3, :3]
    N = d['normal'][:, :3].astype(np.float64) @ R.T
    return P, N, d['uv0'][:, :2].astype(np.float64), d['index'].reshape(-1, 3), img


def place(P_new, P_old_local):
    """rotation / scale / translation that put the extlow scythe on the old scythe's frame (L_Weapon space)"""
    c0, a0, b0, u0, t0 = _frame(P_old_local)
    c1, a1, b1, u1, t1 = _frame(P_new)
    n0, n1 = np.cross(a0, b0), np.cross(a1, b1)
    R = np.stack([a0, b0, n0], 1) @ np.stack([a1, b1, n1], 0)
    # the hand (L_Weapon origin) sits on the old shaft at t = grip0; new grip: same fraction of the shaft length
    grip0 = (np.zeros(3) - c0) @ a0
    frac = (grip0 - t0.min()) / (t0.max() - t0.min())
    grip1 = t1.min() + frac * (t1.max() - t1.min())
    s = (t0.max() - grip0) / (t1.max() - grip1)          # blade end as far from the hand as before
    g1 = c1 + a1 * grip1
    g0 = c0 + a0 * grip0
    return lambda X: (X - g1) @ R.T * s + g0, R


def free_square(used, need):
    """largest free square (<= need px) in the atlas, top-left corner, side"""
    free = (~used).astype(np.int64)
    ii = np.pad(free.cumsum(0).cumsum(1), ((1, 0), (1, 0)))
    for side in range(need, 191, -32):
        s = ii[side:, side:] - ii[:-side, side:] - ii[side:, :-side] + ii[:-side, :-side]
        ys, xs = np.nonzero(s[::8, ::8] == side * side)
        if len(ys):
            return int(xs[0] * 8), int(ys[0] * 8), side
    raise ValueError('no free space in the atlas for the scythe')


def edit_mesh(mesh_tt, smr, rig, W, xform, R, newP, newN, newUV, newT):
    d = decode(mesh_tt)
    names = [rig.goname[b] for b in smr['bones']]
    bi = names.index('L_Weapon')
    w = d['weights'].astype(np.float64)
    on = (w * (d['indices'] == bi)).sum(1) > 0.5
    tris = d['index'].reshape(-1, 3)
    keep_t = tris[~on[tris].all(1)]
    used = np.unique(keep_t)
    remap = -np.ones(len(on), np.int64)
    remap[used] = np.arange(len(used))
    arrays = {k: v[used] for k, v in d.items() if k != 'index'}
    # new scythe in mesh space, rigid on L_Weapon
    M = _mesh_space(rig, smr, bi, W)
    Pw = xform(newP)
    Pm = (np.c_[Pw, np.ones(len(Pw))] @ M.T)[:, :3]
    Nm = newN @ R.T @ M[:3, :3].T
    Nm /= np.linalg.norm(Nm, axis=1, keepdims=True)
    n_old, n_new = len(used), len(Pm)
    add = {'pos': Pm, 'normal': Nm, 'uv0': newUV,
           'weights': np.tile([1.0, 0.0, 0.0, 0.0], (n_new, 1)), 'indices': np.tile([bi, 0, 0, 0], (n_new, 1))}
    for k in arrays:
        v = add[k]
        cols = arrays[k].shape[1]
        if v.shape[1] < cols:                      # e.g. 4-component normals / weights layouts
            v = np.c_[v, np.zeros((n_new, cols - v.shape[1]))]
        arrays[k] = np.concatenate([arrays[k], v[:, :cols].astype(arrays[k].dtype)])
    idx = np.concatenate([remap[keep_t].reshape(-1), (newT + n_old).reshape(-1)])
    n = n_old + n_new
    if n >= 65535:
        raise ValueError('too many vertices')
    encode(mesh_tt, arrays, n)
    raw = idx.astype('<u2').tobytes()
    mesh_tt['m_IndexBuffer'] = raw if isinstance(mesh_tt['m_IndexBuffer'], (bytes, bytearray)) else list(raw)
    mesh_tt['m_IndexFormat'] = 0
    sm = mesh_tt['m_SubMeshes'][0]
    sm.update(firstByte=0, indexCount=int(len(idx)), firstVertex=0, vertexCount=int(n),
              localAABB=mesh_tess._aabb(arrays['pos'][:, :3].astype(np.float64)))
    mesh_tt['m_LocalAABB'] = sm['localAABB']
    mesh_tt['m_BonesAABB'] = mesh_tess.bones_aabb(mesh_tt, arrays['pos'][:, :3].astype(np.float64),
                                                  arrays['weights'].astype(np.float64), arrays['indices'].astype(np.int64))
    tri_uv = arrays['uv0'][:, :2].astype(np.float64)[idx.reshape(-1, 3)]
    return dict(removed_vertices=int((~np.isin(np.arange(len(on)), used)).sum()), added_vertices=n_new,
                triangles=int(len(idx) // 3)), tri_uv


def build_texture(orig_img, uv_tris, crop, rect):
    """model_tex.revamp steps on the original atlas, scythe crop pasted into rect, island padding over all UVs"""
    import cv2
    k = SIZE // 1024
    src = np.asarray(orig_img.convert('RGB')).astype(np.float32) / 255.0
    if src.shape[0] != SIZE:
        src = np.clip(cv2.resize(src, (SIZE, SIZE), interpolation=cv2.INTER_LANCZOS4), 0, 1)
    rgb, protect = model_tex.recolor_eyes_skin(src, k)
    rgb = model_tex.grade(rgb, protect)
    for cv_, bleed in model_tex.PENDANTS:
        model_tex.draw_pendant(rgb, cv_, bleed, k)
    rgb = model_tex.clean_and_sharpen(rgb, k)
    x, y, side = rect
    patch = cv2.resize(crop, (side, side), interpolation=cv2.INTER_AREA)
    patch = model_tex.grade(patch, np.zeros(patch.shape[:2], bool))
    rgb[y:y + side, x:x + side] = patch
    rgb = model_tex.pad_islands(rgb, model_tex.uv_used_mask(uv_tris, SIZE), k)
    return Image.fromarray((np.clip(rgb, 0, 1) * 255 + 0.5).astype(np.uint8), 'RGB')


def main():
    orig_root, root = sys.argv[1], sys.argv[2]
    hdir = os.path.join(root, 'Art', 'Android', 'h')
    P, N, UV, T, ext_img = extlow_scythe(root)
    # extlow atlas region of the scythe -> square crop
    H, Wd = ext_img.shape[:2]
    x0, x1 = int(np.floor(UV[:, 0].min() * Wd)) - 2, int(np.ceil(UV[:, 0].max() * Wd)) + 2
    y0, y1 = int(np.floor((1 - UV[:, 1].max()) * H)) - 2, int(np.ceil((1 - UV[:, 1].min()) * H)) + 2
    x0, y0, x1, y1 = max(x0, 0), max(y0, 0), min(x1, Wd), min(y1, H)
    crop = ext_img[y0:y1, x0:x1]
    report = {}
    first = True
    for bname in BUNDLES:
        path = os.path.join(hdir, bname)
        rig = Rig(path)
        W = rig.pose({})
        env = rig.env
        objs = {o.path_id: o for o in env.objects}
        if first:
            # old scythe in L_Weapon space (from the 'noraml' mesh) -> placement; free atlas square
            s0 = [s for s in rig.smrs if s['name'] == 'noraml'][0]
            names = [rig.goname[b] for b in s0['bones']]
            bi = names.index('L_Weapon')
            d0 = s0['d']
            on = (d0['weights'].astype(np.float64) * (d0['indices'] == bi)).sum(1) > 0.5
            Pw = rig.skin(s0, W)[on]
            Lw = np.linalg.inv(W[s0['bones'][bi]])
            old_local = (np.c_[Pw, np.ones(len(Pw))] @ Lw.T)[:, :3]
            to_local, R = place(P, old_local)
            Bw = W[s0['bones'][bi]]
            xform = lambda X: (np.c_[to_local(X), np.ones(len(X))] @ Bw.T)[:, :3]
            Rw = Bw[:3, :3] @ R
            keep_uv = []
            for s in rig.smrs:
                nm = [rig.goname[b] for b in s['bones']]
                j = nm.index('L_Weapon')
                o = (s['d']['weights'].astype(np.float64) * (s['d']['indices'] == j)).sum(1) > 0.5
                tr = s['d']['index'].reshape(-1, 3)
                keep_uv.append(s['d']['uv0'][:, :2].astype(np.float64)[tr[~o[tr].all(1)]])
            used = model_tex.uv_used_mask(keep_uv, SIZE)
            rect = free_square(used, 512)
            x, y, side = rect
            fx, fy = side / (x1 - x0), side / (y1 - y0)
            newUV = np.c_[(x + (UV[:, 0] * Wd - x0) * fx) / SIZE, 1 - (y + ((1 - UV[:, 1]) * H - y0) * fy) / SIZE]
            first = False
        all_uv = []
        for o in env.objects:
            if o.type.name != 'SkinnedMeshRenderer':
                continue
            st = o.read_typetree()
            if st['m_Mesh']['m_PathID'] == 0:
                continue
            mo = objs[st['m_Mesh']['m_PathID']]
            mt = mo.read_typetree()
            smr = [s for s in rig.smrs if s['name'] == mt['m_Name']][0]
            rep, tri_uv = edit_mesh(mt, smr, rig, W, xform, Rw, P, N, newUV, T)
            mo.save_typetree(mt)
            all_uv.append(tri_uv)
            report[f'{bname}:{mt["m_Name"]}'] = rep
        # texture: rebuilt from the original high atlas (the High source is what every setting shows since v5)
        src = [o.read().image for o in UnityPy.load(os.path.join(orig_root, 'Art', 'Android', 'h',
                                                                'hero_argus_skin_high_add.unity3d')).objects
               if o.type.name == 'Texture2D'][0]
        img = build_texture(src, all_uv, crop, rect)
        tex = [o for o in env.objects if o.type.name == 'Texture2D'][0]
        model_tex.apply_to_texture_object(tex, img)
        with open(path, 'wb') as fh:
            fh.write(env.file.save(packer='original'))
    print('scythe rect in atlas (x, y, side):', rect)
    for k, v in report.items():
        print(k, v)
    return rect


if __name__ == '__main__':
    main()
