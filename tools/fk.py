"""Forward kinematics + linear blend skinning for a Unity skinned character bundle (for previews)."""
import sys, os, math, zlib
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import numpy as np, UnityPy
from meshio import decode
from clipio import decode_clip, binding_layout, sample_clip

def qmat(q):
    x, y, z, w = q
    n = math.sqrt(x*x + y*y + z*z + w*w) or 1.0
    x, y, z, w = x/n, y/n, z/n, w/n
    return np.array([[1-2*(y*y+z*z), 2*(x*y-z*w), 2*(x*z+y*w)],
                     [2*(x*y+z*w), 1-2*(x*x+z*z), 2*(y*z-x*w)],
                     [2*(x*z-y*w), 2*(y*z+x*w), 1-2*(x*x+y*y)]])
def trs(t, q, s):
    M = np.eye(4); M[:3, :3] = qmat(q) * np.array(s)[None, :]; M[:3, 3] = t; return M

class Rig:
    def __init__(self, env_or_path):
        env = UnityPy.load(env_or_path) if isinstance(env_or_path, str) else env_or_path
        self.env = env
        objs = {o.path_id: o for o in env.objects}
        self.objs = objs
        self.tf = {pid: o.read_typetree() for pid, o in objs.items() if o.type.name == 'Transform'}
        self.goname = {pid: objs[t['m_GameObject']['m_PathID']].read_typetree()['m_Name'] for pid, t in self.tf.items()}
        anim = [o for o in objs.values() if o.type.name == 'Animator'][0].read_typetree()
        go = objs[anim['m_GameObject']['m_PathID']].read_typetree()
        self.root = [c['component']['m_PathID'] for c in go['m_Component'] if objs[c['component']['m_PathID']].type.name == 'Transform'][0]
        # path hashes
        self.path_of = {self.root: ''}
        order = [self.root]; i = 0
        while i < len(order):
            p = order[i]; i += 1
            for ch in self.tf[p]['m_Children']:
                c = ch['m_PathID']
                self.path_of[c] = (self.path_of[p] + '/' if self.path_of[p] else '') + self.goname[c]
                order.append(c)
        self.order = order
        self.hash_to_pid = {zlib.crc32(p.encode()): pid for pid, p in self.path_of.items()}
        self.parent = {}
        for p in order:
            for ch in self.tf[p]['m_Children']: self.parent[ch['m_PathID']] = p
        self.smrs = []
        for o in objs.values():
            if o.type.name == 'SkinnedMeshRenderer':
                s = o.read_typetree()
                if s['m_Mesh']['m_PathID'] == 0: continue
                mt = objs[s['m_Mesh']['m_PathID']].read_typetree()
                d = decode(mt)
                bp = np.array([[[b[f'e{r}{c}'] for c in range(4)] for r in range(4)] for b in mt['m_BindPose']])
                self.smrs.append(dict(name=mt['m_Name'], go=objs[s['m_GameObject']['m_PathID']].read_typetree(), bones=[b['m_PathID'] for b in s['m_Bones']], bind=bp, d=d))
    def default_local(self, pid):
        t = self.tf[pid]
        lp, lr, ls = t['m_LocalPosition'], t['m_LocalRotation'], t['m_LocalScale']
        return [lp['x'], lp['y'], lp['z']], [lr['x'], lr['y'], lr['z'], lr['w']], [ls['x'], ls['y'], ls['z']]
    def pose(self, overrides):
        """overrides: pid -> dict(t=,q=,s=). returns world matrices"""
        W = {}
        for p in self.order:
            t, q, s = self.default_local(p)
            ov = overrides.get(p, {})
            t = ov.get('t', t); q = ov.get('q', q); s = ov.get('s', s)
            L = trs(t, q, s) if p != self.root else np.eye(4)
            W[p] = W[self.parent[p]] @ L if p in self.parent and p != self.root else L
        return W
    def skin(self, smr, W):
        d = smr['d']; v = np.c_[d['pos'].astype(np.float64), np.ones(len(d['pos']))]
        mats = np.array([W[b] @ smr['bind'][i] for i, b in enumerate(smr['bones'])])
        out = np.zeros((len(v), 3))
        for k in range(4):
            w = d['weights'][:, k].astype(np.float64)
            idx = d['indices'][:, k].astype(int)
            out += w[:, None] * np.einsum('nij,nj->ni', mats[idx], v)[:, :3]
        return out

def clip_overrides(rig, tt, times):
    dec = decode_clip(tt); lay, n = binding_layout(tt)
    M = sample_clip(dec, np.asarray(times, float))
    res = []
    act = []
    for fi in range(len(times)):
        ov = {}; active = {}
        for (ph, attr, nc, c0, tid) in lay:
            pid = rig.hash_to_pid.get(ph)
            if pid is None: continue
            if tid == 4:
                v = M[fi, c0:c0 + nc]
                key = {1: 't', 2: 'q', 3: 's'}.get(attr)
                if key: ov.setdefault(pid, {})[key] = list(v)
            elif tid == 1:
                active[rig.goname[pid]] = M[fi, c0] > 0.5
        res.append(ov); act.append(active)
    return res, act
