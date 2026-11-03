"""Top-down render of a MLBB scene bundle's ground (and optionally props) for previews / layout analysis.

usage: python map_render.py <scene.unity3d> <out.png> [px_per_m] [x0 x1 z0 z1] [--props]
As a module: render(env, textures=None, px_per_m=24, extent=(-64, 64, -50, 50), layers=(17,), crop=None)
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import numpy as np
from PIL import Image
import UnityPy
from meshio import decode


def trs_matrix(t):
    q = t['m_LocalRotation']; x, y, z, w = q['x'], q['y'], q['z'], q['w']
    R = np.array([[1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
                  [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
                  [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)]])
    S = np.diag([t['m_LocalScale'][k] for k in 'xyz'])
    M = np.eye(4); M[:3, :3] = R @ S; M[:3, 3] = [t['m_LocalPosition'][k] for k in 'xyz']
    return M


class Scene:
    def __init__(self, env):
        self.env = env
        scene = [o for o in env.objects if not o.assets_file.name.endswith('sharedAssets')]
        self.shared = {o.path_id: o for o in env.objects if o.assets_file.name.endswith('sharedAssets')}
        self.gos = {o.path_id: o.read_typetree() for o in scene if o.type.name == 'GameObject'}
        self.trs = {o.path_id: o.read_typetree() for o in scene if o.type.name == 'Transform'}
        self.ctype = {o.path_id: o.type.name for o in scene}
        self.mr = {o.path_id: o.read_typetree() for o in scene if o.type.name == 'MeshRenderer'}
        self.mf = {o.path_id: o.read_typetree() for o in scene if o.type.name == 'MeshFilter'}
        self.go_tr = {}
        for gid, g in self.gos.items():
            for c in g['m_Component']:
                if self.ctype.get(c['component']['m_PathID']) == 'Transform':
                    self.go_tr[gid] = c['component']['m_PathID']

    def world(self, tpid):
        M = np.eye(4); chain = []
        p = tpid
        while p:
            chain.append(self.trs[p]); p = self.trs[p]['m_Father']['m_PathID']
        for t in reversed(chain):
            M = M @ trs_matrix(t)
        return M

    def renderers(self):
        """-> list of (go name, layer, world matrix, mesh pid, [material pids])"""
        out = []
        for gid, g in self.gos.items():
            mr = mf = None
            for c in g['m_Component']:
                p = c['component']['m_PathID']
                if p in self.mr: mr = self.mr[p]
                if p in self.mf: mf = self.mf[p]
            if mr is None or mf is None or not g['m_IsActive'] or not mr['m_Enabled']:
                continue
            out.append((g['m_Name'], g['m_Layer'], self.world(self.go_tr[gid]), mf['m_Mesh']['m_PathID'],
                        [m['m_PathID'] for m in mr['m_Materials']]))
        return out


def raster(img, zbuf, P, UV, tex, height=None):
    """img HxWx3 float, P: Nx3 (px, py, depth) triangle verts in image space, UV Nx2, tex float HxWx3/4."""
    H, W = img.shape[:2]
    th, tw = tex.shape[:2]
    for tri in range(0, len(P), 3):
        p = P[tri:tri + 3]; uv = UV[tri:tri + 3]
        x0, x1 = int(np.floor(p[:, 0].min())), int(np.ceil(p[:, 0].max()))
        y0, y1 = int(np.floor(p[:, 1].min())), int(np.ceil(p[:, 1].max()))
        x0, y0 = max(x0, 0), max(y0, 0); x1, y1 = min(x1, W - 1), min(y1, H - 1)
        if x1 < x0 or y1 < y0:
            continue
        ys, xs = np.mgrid[y0:y1 + 1, x0:x1 + 1]
        px, py = xs + 0.5, ys + 0.5
        (ax, ay), (bx, by), (cx, cy) = p[0, :2], p[1, :2], p[2, :2]
        den = (by - cy) * (ax - cx) + (cx - bx) * (ay - cy)
        if abs(den) < 1e-9:
            continue
        w0 = ((by - cy) * (px - cx) + (cx - bx) * (py - cy)) / den
        w1 = ((cy - ay) * (px - cx) + (ax - cx) * (py - cy)) / den
        w2 = 1 - w0 - w1
        m = (w0 >= -1e-4) & (w1 >= -1e-4) & (w2 >= -1e-4)
        if not m.any():
            continue
        d = w0 * p[0, 2] + w1 * p[1, 2] + w2 * p[2, 2]
        u = w0 * uv[0, 0] + w1 * uv[1, 0] + w2 * uv[2, 0]
        v = w0 * uv[0, 1] + w1 * uv[1, 1] + w2 * uv[2, 1]
        tx = np.clip(((u % 1.0) * tw).astype(int), 0, tw - 1)
        ty = np.clip(((1 - (v % 1.0)) * th).astype(int), 0, th - 1)
        col = tex[ty, tx, :3]
        zz = zbuf[ys, xs]
        m &= d >= zz
        yy, xx = ys[m], xs[m]
        img[yy, xx] = col[m]
        zbuf[yy, xx] = d[m]


def render(env, textures=None, px_per_m=24, extent=(-64, 64, -50, 50), layers=(17,), names=None):
    sc = Scene(env)
    x0, x1, z0, z1 = extent
    W, H = int((x1 - x0) * px_per_m), int((z1 - z0) * px_per_m)
    img = np.zeros((H, W, 3), np.float32) + 0.05
    zbuf = np.full((H, W), -1e9, np.float32)
    tex_cache = {}
    mats = {pid: o.read_typetree() for pid, o in sc.shared.items() if o.type.name == 'Material'}
    tex_objs = {pid: o for pid, o in sc.shared.items() if o.type.name == 'Texture2D'}
    meshes = {}
    for name, layer, M, mesh_pid, mat_pids in sc.renderers():
        if layer not in layers or (names and not any(n in name for n in names)):
            continue
        if mesh_pid not in meshes:
            try:
                meshes[mesh_pid] = decode(sc.shared[mesh_pid].read_typetree())
            except Exception:
                meshes[mesh_pid] = {}            # compressed / streamed vertex data: skipped in previews
        d = meshes[mesh_pid]
        if 'uv0' not in d:
            continue
        mt = mats.get(mat_pids[0]) if mat_pids else None
        if mt is None:
            continue
        tp = dict(mt['m_SavedProperties']['m_TexEnvs']).get('_MainTex')
        if not tp or tp['m_Texture']['m_PathID'] not in tex_objs:
            continue
        to = tex_objs[tp['m_Texture']['m_PathID']]
        tname = to.read_typetree()['m_Name']
        if tname not in tex_cache:
            im = textures[tname] if textures and tname in textures else to.read().image
            tex_cache[tname] = np.asarray(im.convert('RGB'), np.float32) / 255.0
        pos = d['pos'][:, :3].astype(np.float64)
        wp = (M @ np.c_[pos, np.ones(len(pos))].T).T[:, :3]
        idx = d['index'].astype(np.int64)
        tri = wp[idx]
        P = np.stack([(tri[:, 0] - x0) * px_per_m, (z1 - tri[:, 2]) * px_per_m, tri[:, 1]], -1)
        raster(img, zbuf, P, d['uv0'][idx].astype(np.float64), tex_cache[tname])
    return Image.fromarray((np.clip(img, 0, 1) * 255).astype(np.uint8))


if __name__ == '__main__':
    path, out = sys.argv[1], sys.argv[2]
    ppm = float(sys.argv[3]) if len(sys.argv) > 3 else 24
    ext = tuple(float(v) for v in sys.argv[4:8]) if len(sys.argv) > 7 else (-64, 64, -50, 50)
    layers = (17, 10) if '--props' in sys.argv else (17,)
    render(UnityPy.load(path), px_per_m=ppm, extent=ext, layers=layers).save(out)
    print(out)
