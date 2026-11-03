"""Phong tessellation (1 -> 4 triangles) for Unity skinned meshes stored with typetrees.

* edge midpoints are pushed onto the curved surface defined by the vertex normals (Boubekeur & Alexa,
  "Phong Tessellation", 2008) -> rounder silhouettes, 4x the triangles, no new texture work needed
* normals used for the curvature are welded per position, positions come from one canonical vertex per
  weld group, so edges split by UV seams / hard normals get bit-identical midpoints (no cracks)
* per-corner attributes (UV, shading normal) are interpolated per corner pair, so UV seams and hard
  edges stay exactly where they were
* skin weights of the two edge ends are merged, top-4 influences kept and renormalised
"""
import numpy as np
from meshio import decode, encode

ALPHA = 0.6          # 0 = flat (linear) subdivision, 1 = full Phong projection
MAX_REL = 0.12       # displacement <= 12 % of the edge length ...
MAX_ABS = 0.012      # ... and <= 1.2 cm (long thin parts such as the scythe pole must not inflate)


def _weld(pos, tol=1e-5):
    keys = np.round(pos / tol).astype(np.int64)
    _, first, inv = np.unique(keys, axis=0, return_index=True, return_inverse=True)
    return inv.reshape(-1), first


def _merge_weights(wa, ia, wb, ib):
    acc = {}
    for w, i in zip(np.concatenate([wa, wb]) * 0.5, np.concatenate([ia, ib])):
        if w > 0:
            acc[int(i)] = acc.get(int(i), 0.0) + float(w)
    top = sorted(acc.items(), key=lambda kv: -kv[1])[:4]
    s = sum(w for _, w in top) or 1.0
    idx = [i for i, _ in top] + [0] * (4 - len(top))
    wts = [w / s for _, w in top] + [0.0] * (4 - len(top))
    return wts, idx


def tessellate_arrays(d, alpha=ALPHA, rigid_bones=()):
    P = d['pos'].astype(np.float64)
    N = d['normal'].astype(np.float64)
    UV = d['uv0'].astype(np.float64)
    W = d['weights'].astype(np.float64)
    I = d['indices'].astype(np.int64)
    tris = d['index'].reshape(-1, 3).astype(np.int64)
    grp, first = _weld(P)
    canon = P[first]                                  # canonical position per weld group
    Nw = np.zeros((len(first), 3))
    np.add.at(Nw, grp, N)
    ln = np.linalg.norm(Nw, axis=1)
    ok = ln > 0.3 * np.bincount(grp, minlength=len(first))   # reject groups whose normals cancel (thin shells)
    Nw = np.where(ok[:, None], Nw / np.maximum(ln, 1e-12)[:, None], 0.0)

    dom = I[np.arange(len(I)), W.argmax(1)]
    rigid = np.isin(dom, np.array(list(rigid_bones), np.int64)) if len(rigid_bones) else np.zeros(len(P), bool)
    newP, newN, newUV, newW, newI = [list(a) for a in (P, N, UV, W, I)]
    cache = {}

    def mid(i, j):
        key = (i, j) if i < j else (j, i)
        if key in cache:
            return cache[key]
        ga, gb = grp[i], grp[j]
        if ga > gb:
            ga, gb = gb, ga
        pa, pb = canon[ga], canon[gb]
        m = 0.5 * (pa + pb)
        na, nb = Nw[ga], Nw[gb]
        if ok[ga] and ok[gb] and not (rigid[i] or rigid[j]):
            qa = m - np.dot(m - pa, na) * na
            qb = m - np.dot(m - pb, nb) * nb
            disp = alpha * (0.5 * (qa + qb) - m)
            lim = min(MAX_REL * float(np.linalg.norm(pb - pa)), MAX_ABS)
            dl = float(np.linalg.norm(disp))
            if dl > lim:
                disp *= lim / dl
            pos = m + disp
        else:
            pos = m
        n = N[i] + N[j]
        ln_ = np.linalg.norm(n)
        n = n / ln_ if ln_ > 1e-6 else N[i]
        wts, idx = _merge_weights(W[i], I[i], W[j], I[j])
        newP.append(pos); newN.append(n); newUV.append(0.5 * (UV[i] + UV[j]))
        newW.append(np.array(wts)); newI.append(np.array(idx))
        k = len(newP) - 1
        cache[key] = k
        return k

    out_tris = []
    for a, b, c in tris:
        ab, bc, ca = mid(a, b), mid(b, c), mid(c, a)
        out_tris += [(a, ab, ca), (ab, b, bc), (ca, bc, c), (ab, bc, ca)]
    return dict(pos=np.array(newP), normal=np.array(newN), uv0=np.array(newUV), weights=np.array(newW),
                indices=np.array(newI), index=np.array(out_tris, np.int64).reshape(-1))


def _aabb(points):
    mn, mx = points.min(0), points.max(0)
    c, e = (mn + mx) / 2, (mx - mn) / 2
    return {'m_Center': {'x': float(c[0]), 'y': float(c[1]), 'z': float(c[2])},
            'm_Extent': {'x': float(e[0]), 'y': float(e[1]), 'z': float(e[2])}}


def bones_aabb(tt, pos, weights, indices):
    bp = [np.array([[b[f'e{r}{c}'] for c in range(4)] for r in range(4)]) for b in tt['m_BindPose']]
    nb = len(bp)
    mn = np.full((nb, 3), np.inf); mx = np.full((nb, 3), -np.inf)
    hom = np.c_[pos, np.ones(len(pos))]
    for k in range(4):
        sel = weights[:, k] > 0
        for b in np.unique(indices[sel, k]):
            m = sel & (indices[:, k] == b)
            q = (hom[m] @ bp[b].T)[:, :3]
            mn[b] = np.minimum(mn[b], q.min(0)); mx[b] = np.maximum(mx[b], q.max(0))
    return [{'m_Min': {'x': float(a[0]), 'y': float(a[1]), 'z': float(a[2])},
             'm_Max': {'x': float(b_[0]), 'y': float(b_[1]), 'z': float(b_[2])}} for a, b_ in zip(mn, mx)]


def tessellate_mesh_typetree(tt, alpha=ALPHA, rigid_bones=()):
    """In-place: replace vertex/index data of a Mesh typetree with its Phong-tessellated version."""
    d = decode(tt)
    t = tessellate_arrays(d, alpha, rigid_bones)
    n = len(t['pos'])
    if n >= 65535:
        raise ValueError('too many vertices for 16-bit indices')
    encode(tt, {'pos': t['pos'], 'normal': t['normal'], 'uv0': t['uv0'], 'weights': t['weights'],
                'indices': t['indices']}, n)
    idx = t['index'].astype('<u2')
    raw = idx.tobytes()
    tt['m_IndexBuffer'] = raw if isinstance(tt['m_IndexBuffer'], (bytes, bytearray)) else list(raw)
    tt['m_IndexFormat'] = 0
    sm = tt['m_SubMeshes'][0]
    sm['firstByte'] = 0
    sm['indexCount'] = int(len(idx))
    sm['firstVertex'] = 0
    sm['vertexCount'] = int(n)
    sm['localAABB'] = _aabb(t['pos'])
    tt['m_LocalAABB'] = _aabb(t['pos'])
    tt['m_BonesAABB'] = bones_aabb(tt, t['pos'], t['weights'], t['indices'])
    return dict(vertices_before=len(d['pos']), vertices_after=n,
                triangles_before=len(d['index']) // 3, triangles_after=len(idx) // 3)
