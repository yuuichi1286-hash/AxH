"""New trees for Sanctum Island (High): clones of the map's own edge tree (trunk + leaf canopy) planted on free
spots of the outer cliff rim, outside the playable diamond, so they never block a lane, a jungle path or the view.

Clones reference the SAME mesh / material assets as the original tree (no new assets); only scene objects are
added: GameObject + Transform + MeshFilter + MeshRenderer per part, under one root. Trunks get the same baked
lighting as the original (an extra entry in the scene's BattleSceneDiffmapStorage); the leaf canopy carries its
lightmap in the material.
"""
import copy
import math
import numpy as np

SOURCE = ('PVP_049_2026s3_tree_04', 'PVP_049_2026s3_outsideleaf_05')     # trunk, canopy (pivot = trunk)

# (x, z, surface y, yaw deg, scale): trunk spots on the outer cliff rim, searched so that EVERY vertex of the tree
# stays outside the real lane walls (>= 5 m beyond the diamond |x|/50 + |z|/44 = 1, >= 9.5 m near the top / bottom
# tips, where the walls sit further out) and the game camera's sight lines through the tree reach the ground only
# beyond the walls' inner face: a new tree can never stand on, overhang or hide a lane or jungle path.
PLACEMENTS = [
    (20.6, 36.9, -0.84, 75.0, 1.6),
    (44.7, -14.8, -4.78, 180.0, 1.6),
    (19.7, -36.9, -2.13, 180.0, 1.6),
    (-28.0, -34.0, -2.47, 0.0, 1.6),
    (-45.0, -18.0, -4.96, 0.0, 1.6),
    (-17.3, 38.4, -0.91, 0.0, 1.6),
    (15.3, -42.4, -0.26, 165.0, 1.6),
]
# geometry rule shared with the validator
WALL_CLEAR, WALL_CLEAR_TIPS, SIGHT_CLEAR = 5.0, 9.5, 2.5


def d_out(x, z):
    """distance outside the playable diamond (m); the lane walls stand at ~2.5-4.75 m"""
    return (np.abs(x) / 50.0 + np.abs(z) / 44.0 - 1.0) * 33.0


def clearance_ok(world_verts, cam_fwd):
    """every vertex beyond the walls, and every camera sight line through a vertex reaching the ground beyond the
    walls' inner face -> (ok, closest vertex d_out, closest sight-line ground hit d_out)"""
    v = np.asarray(world_verts, np.float64)
    need = np.where(np.abs(v[:, 0]) < 12, WALL_CLEAR_TIPS, WALL_CLEAR)
    dv = d_out(v[:, 0], v[:, 2])
    f = np.asarray(cam_fwd, np.float64); f = f / np.linalg.norm(f)
    t = np.maximum(v[:, 1], 0) / -f[1]
    hit = v + f[None, :] * t[:, None]
    dh = d_out(hit[:, 0], hit[:, 2])
    return bool((dv >= need).all() and (dh >= SIGHT_CLEAR).all()), float(dv.min()), float(dh.min())


ROOT_NAME = 'Sanctum_NewTrees'


def _quat_to_m(q):
    x, y, z, w = q['x'], q['y'], q['z'], q['w']
    return np.array([[1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
                     [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
                     [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)]])


def _m_to_quat(R):
    t = np.trace(R)
    if t > 0:
        s = math.sqrt(t + 1.0) * 2
        w, x, y, z = 0.25 * s, (R[2, 1] - R[1, 2]) / s, (R[0, 2] - R[2, 0]) / s, (R[1, 0] - R[0, 1]) / s
    elif R[0, 0] > R[1, 1] and R[0, 0] > R[2, 2]:
        s = math.sqrt(1.0 + R[0, 0] - R[1, 1] - R[2, 2]) * 2
        w, x, y, z = (R[2, 1] - R[1, 2]) / s, 0.25 * s, (R[0, 1] + R[1, 0]) / s, (R[0, 2] + R[2, 0]) / s
    elif R[1, 1] > R[2, 2]:
        s = math.sqrt(1.0 + R[1, 1] - R[0, 0] - R[2, 2]) * 2
        w, x, y, z = (R[0, 2] - R[2, 0]) / s, (R[0, 1] + R[1, 0]) / s, 0.25 * s, (R[1, 2] + R[2, 1]) / s
    else:
        s = math.sqrt(1.0 + R[2, 2] - R[0, 0] - R[1, 1]) * 2
        w, x, y, z = (R[1, 0] - R[0, 1]) / s, (R[0, 2] + R[2, 0]) / s, (R[1, 2] + R[2, 1]) / s, 0.25 * s
    n = math.sqrt(w * w + x * x + y * y + z * z)
    return {'x': float(x / n), 'y': float(y / n), 'z': float(z / n), 'w': float(w / n)}


def _yaw(deg):
    a = math.radians(deg)
    return np.array([[math.cos(a), 0, math.sin(a)], [0, 1, 0], [-math.sin(a), 0, math.cos(a)]])


def plan(env):
    """-> list of placed parts: dict(name, src_go, M (4x4 world), ...) and the world bounding boxes (for previews,
    leaf emitters and validation)."""
    from map_render import Scene
    from meshio import decode
    sc = Scene(env)
    src = {}
    for gid, g in sc.gos.items():
        if g['m_Name'] in SOURCE:
            mf = mr = None
            for c in g['m_Component']:
                p = c['component']['m_PathID']
                if p in sc.mf: mf = p
                if p in sc.mr: mr = p
            M = sc.world(sc.go_tr[gid])
            d = decode(sc.shared[sc.mf[mf]['m_Mesh']['m_PathID']].read_typetree())
            wp = (M @ np.c_[d['pos'][:, :3], np.ones(len(d['pos']))].T).T[:, :3]
            src[g['m_Name']] = dict(go=gid, mf=mf, mr=mr, M=M, wp=wp)
    trunk = src[SOURCE[0]]
    pivot = trunk['M'][:3, 3].copy()
    base_off = trunk['wp'][:, 1].min() - pivot[1]          # trunk foot below its pivot
    parts = []
    for i, (x, z, ys, yaw, s) in enumerate(PLACEMENTS):
        R = _yaw(yaw)
        new_pivot = np.array([x, ys - base_off * s - 0.25, z])        # foot sunk 25 cm into the rock
        for name in SOURCE:
            p = src[name]
            Mw = np.eye(4)
            Mw[:3, :3] = R @ (s * p['M'][:3, :3])
            Mw[:3, 3] = new_pivot + R @ (s * (p['M'][:3, 3] - pivot))
            wp = (R @ (s * (p['wp'] - pivot)).T).T + new_pivot
            parts.append(dict(name=f'{name.replace("PVP_049_2026s3_", "Sanctum_")}_new{i + 1}', src=name,
                              src_go=p['go'], src_mf=p['mf'], src_mr=p['mr'], M=Mw,
                              bbox=(wp.min(0).tolist(), wp.max(0).tolist()), tree=i))
    return parts


def canopies(parts):
    """world (centre, size) of each new canopy: for the falling-leaf emitters"""
    out = []
    for p in parts:
        if p['src'] == SOURCE[1]:
            lo, hi = np.array(p['bbox'][0]), np.array(p['bbox'][1])
            out.append(((lo + hi) / 2, hi - lo))
    return out


def inject(env, parts, new_object):
    """Adds the planned tree parts to the scene. new_object(sf, pid, st, idx, tree) writes one object."""
    bf = env.files[list(env.files)[0]]
    scene = next(sf for n, sf in bf.files.items() if hasattr(sf, 'types') and not n.endswith('.sharedAssets'))

    def type_of(cid):
        i = next(i for i, t in enumerate(scene.types) if t.class_id == cid)
        return i, scene.types[i]

    objs = scene.objects
    nid = max(objs) + 1

    def pp(pid):
        return {'m_FileID': 0, 'm_PathID': pid}

    go_i, go_t = type_of(1)
    tr_i, tr_t = type_of(4)
    mf_i, mf_t = type_of(33)
    mr_i, mr_t = type_of(23)
    tr_tmpl = next(o for o in objs.values() if o.type.name == 'Transform').read_typetree()
    pending = []
    root_g, root_t = nid, nid + 1
    nid += 2
    rg = copy.deepcopy(objs[parts[0]['src_go']].read_typetree())
    rg.update({'m_Name': ROOT_NAME, 'm_Component': [{'component': pp(root_t)}], 'm_IsActive': True})
    rt = copy.deepcopy(tr_tmpl)
    rt.update({'m_GameObject': pp(root_g), 'm_LocalRotation': {'x': 0.0, 'y': 0.0, 'z': 0.0, 'w': 1.0},
               'm_LocalPosition': {'x': 0.0, 'y': 0.0, 'z': 0.0}, 'm_LocalScale': {'x': 1.0, 'y': 1.0, 'z': 1.0},
               'm_Children': [], 'm_Father': pp(0)})
    new_mr = {}
    for p in parts:
        g_id, t_id, f_id, r_id = nid, nid + 1, nid + 2, nid + 3
        nid += 4
        g = copy.deepcopy(objs[p['src_go']].read_typetree())
        g.update({'m_Name': p['name'], 'm_IsActive': True,
                  'm_Component': [{'component': pp(t_id)}, {'component': pp(f_id)}, {'component': pp(r_id)}]})
        M = p['M']
        sx = float(np.linalg.norm(M[:3, 0]))
        t = copy.deepcopy(tr_tmpl)
        t.update({'m_GameObject': pp(g_id), 'm_LocalRotation': _m_to_quat(M[:3, :3] / sx),
                  'm_LocalPosition': {'x': float(M[0, 3]), 'y': float(M[1, 3]), 'z': float(M[2, 3])},
                  'm_LocalScale': {'x': sx, 'y': sx, 'z': sx}, 'm_Children': [], 'm_Father': pp(root_t)})
        f = copy.deepcopy(objs[p['src_mf']].read_typetree()); f['m_GameObject'] = pp(g_id)
        r = copy.deepcopy(objs[p['src_mr']].read_typetree()); r['m_GameObject'] = pp(g_id)
        rt['m_Children'].append(pp(t_id))
        pending += [(g_id, go_t, go_i, g), (t_id, tr_t, tr_i, t), (f_id, mf_t, mf_i, f), (r_id, mr_t, mr_i, r)]
        new_mr[r_id] = p['src_mr']
    pending = [(root_g, go_t, go_i, rg), (root_t, tr_t, tr_i, rt)] + pending
    for pid, st, idx, tree in sorted(pending, key=lambda x: x[0]):
        new_object(scene, pid, st, idx, tree)
    # baked lighting for the cloned trunks: same diffmap entry as the original renderer
    added = 0
    for o in list(objs.values()):
        if o.type.name != 'MonoBehaviour':
            continue
        tt = o.read_typetree()
        if 'rendererDiffmapInfos' not in tt:
            continue
        by_r = {e['renderer']['m_PathID']: e for e in tt['rendererDiffmapInfos']}
        for nr, sr in new_mr.items():
            if sr in by_r:
                e = copy.deepcopy(by_r[sr]); e['renderer'] = pp(nr)
                tt['rendererDiffmapInfos'].append(e); added += 1
        o.save_typetree(tt)
    if hasattr(scene, 'mark_changed'):
        scene.mark_changed()
    return {'trees': len(PLACEMENTS), 'parts': len(parts), 'scene_objects_added': len(pending),
            'diffmap_entries_added': added, 'root': ROOT_NAME,
            'placements': [dict(x=x, z=z, surface_y=ys, yaw=yaw, scale=s) for x, z, ys, yaw, s in PLACEMENTS]}
