"""Ground decoration for Sanctum Island (High), painted into the 16 ground tiles:

* monster carcasses: a horned beast skull with spine and ribs, half sunk into the ground, mossy, with a soil stain
* fallen leaves around the plants growing on the jungle walls (same shape / colour family as the tree leaves)

Placement is in WORLD space (seamless across tiles) with a fixed seed and mirrored through the map centre, so both
teams get the same scenery. Lanes stay clear: the carcasses lie only inside the jungle (never on a lane or in the
river), the fallen leaves never on the stone lanes. Every decal has its own height map: it is lit with the map's light direction, casts a short contact
shadow, and is drawn anti-aliased from 2x supersampled sprites (crisp, no blur, no grain).
"""
import math
import numpy as np

SPPM = 208.0                          # sprite resolution: px per metre (2x the ground texel density)
GPPM = 10.0                           # placement grid: px per metre
GRID = (-72.0, 72.0, -58.0, 58.0)
SEED = 20261104


def _ss(a, b, x):
    t = np.clip((x - a) / (b - a), 0, 1)
    return t * t * (3 - 2 * t)


# ================================================================== sprites
class Sprite:
    """alpha, colour (pre-grade albedo), height (m) on a square canvas; origin at the centre pixel"""

    def __init__(self, size_m):
        n = int(math.ceil(size_m * SPPM)) | 1
        self.n = n
        self.a = np.zeros((n, n), np.float32)
        self.c = np.zeros((n, n, 3), np.float32)
        self.h = np.zeros((n, n), np.float32)

    def _win(self, cx, cy, r):
        c0 = self.n // 2
        x0 = max(int(math.floor((cx - r) * SPPM)) + c0, 0); x1 = min(int(math.ceil((cx + r) * SPPM)) + c0 + 1, self.n)
        y0 = max(int(math.floor((cy - r) * SPPM)) + c0, 0); y1 = min(int(math.ceil((cy + r) * SPPM)) + c0 + 1, self.n)
        if x1 <= x0 or y1 <= y0:
            return None
        ys, xs = np.mgrid[y0:y1, x0:x1].astype(np.float32)
        return (slice(y0, y1), slice(x0, x1)), (xs - c0) / SPPM - cx, (ys - c0) / SPPM - cy

    def _put(self, sl, a, h, col):
        A, H, C = self.a[sl], self.h[sl], self.c[sl]
        vis = a * (h >= H - 1e-4)
        col = np.broadcast_to(np.asarray(col, np.float32), C.shape)
        C[:] = C * (1 - vis[..., None]) + col * vis[..., None]
        A[:] = A + vis * (1 - A)
        H[:] = np.where(vis > 0.5, np.maximum(H, h), H)

    def dome(self, cx, cy, rx, ry, ang, h, col, power=0.5):
        """ellipse with a rounded top; col: rgb or f(u, v, d) -> HxWx3 (u along the long axis, -1..1)"""
        w = self._win(cx, cy, max(rx, ry) + 2 / SPPM)
        if w is None:
            return
        sl, X, Y = w
        ca, sa = math.cos(ang), math.sin(ang)
        u = (X * ca + Y * sa) / rx
        v = (-X * sa + Y * ca) / ry
        d = np.sqrt(u * u + v * v)
        a = np.clip((1 - d) * min(rx, ry) * SPPM / 1.2, 0, 1)
        hh = h * np.clip(1 - d * d, 0, 1) ** power
        self._put(sl, a, hh, col(u, v, d) if callable(col) else col)

    def tube(self, pts, radii, heights, col):
        """tapered round tube along a polyline (bones, ribs, horns, stalks)"""
        pts = np.asarray(pts, np.float32)
        for i in range(len(pts) - 1):
            p0, p1 = pts[i], pts[i + 1]
            r0, r1 = radii[i], radii[i + 1]
            h0, h1 = heights[i], heights[i + 1]
            w = self._win((p0[0] + p1[0]) / 2, (p0[1] + p1[1]) / 2,
                          np.hypot(*(p1 - p0)) / 2 + max(r0, r1) + 2 / SPPM)
            if w is None:
                continue
            sl, X, Y = w
            X = X + (p0[0] + p1[0]) / 2 - p0[0]
            Y = Y + (p0[1] + p1[1]) / 2 - p0[1]
            dx, dy = p1 - p0
            L2 = max(dx * dx + dy * dy, 1e-9)
            t = np.clip((X * dx + Y * dy) / L2, 0, 1)
            d = np.hypot(X - t * dx, Y - t * dy)
            r = r0 + (r1 - r0) * t
            a = np.clip((r - d) * SPPM / 1.2, 0, 1)
            q = np.clip(1 - (d / np.maximum(r, 1e-4)) ** 2, 0, 1)
            hh = (h0 + (h1 - h0) * t) * np.sqrt(q)
            c = col(t, d / np.maximum(r, 1e-4)) if callable(col) else col
            self._put(sl, a, hh, c)

    def dent(self, cx, cy, rx, ry, ang, depth, col):
        """socket / hole: carves the existing surface and darkens it"""
        w = self._win(cx, cy, max(rx, ry) + 2 / SPPM)
        if w is None:
            return
        sl, X, Y = w
        ca, sa = math.cos(ang), math.sin(ang)
        u = (X * ca + Y * sa) / rx
        v = (-X * sa + Y * ca) / ry
        d = np.sqrt(u * u + v * v)
        k = np.clip((1 - d) * min(rx, ry) * SPPM / 1.2, 0, 1) * (self.a[sl] > 0.5)
        self.h[sl] = np.maximum(self.h[sl] - depth * np.clip(1 - d * d, 0, 1) * k, 0)
        self.c[sl] = self.c[sl] * (1 - k[..., None]) + np.asarray(col, np.float32) * k[..., None]

    def finish(self, blur=0.6):
        """light anti-aliasing (0.3 texel), then colour stored premultiplied by alpha (no dark fringes when the
        sprite is resampled)"""
        import cv2
        pc = self.c * self.a[..., None]
        if blur:
            self.a = cv2.GaussianBlur(self.a, (0, 0), blur)
            pc = cv2.GaussianBlur(pc, (0, 0), blur)
            self.h = cv2.GaussianBlur(self.h, (0, 0), blur)
        self.c = pc
        return self


def _shade_fn(base, tip=1.18, edge=0.18):
    base = np.asarray(base, np.float32)

    def f(u, v, d):
        k = (1 + (tip - 1) * np.clip((u + 1) / 2, 0, 1)) * (1 - edge * np.clip(d, 0, 1) ** 3)
        return np.clip(base * k[..., None], 0, 1)
    return f


def sprite_leaf(rng):
    S = Sprite(0.32)
    kind = rng.rand()
    if kind < 0.6:
        base = np.array([0.26, 0.38, 0.17]) * rng.uniform(0.85, 1.15)       # natural green, like the tree leaves
    elif kind < 0.85:
        base = np.array([0.62, 0.56, 0.26]) * rng.uniform(0.9, 1.1)        # yellowing
    else:
        base = np.array([0.46, 0.32, 0.18]) * rng.uniform(0.9, 1.1)        # dry brown
    L = rng.uniform(0.07, 0.11)
    ang = rng.uniform(0, 2 * math.pi)

    def col(u, v, d):
        half = np.where(v > 0, 1.0, 0.82)
        rib = np.exp(-(v / 0.08) ** 2) * 0.12
        return np.clip(base * (half * (0.9 + 0.1 * (u + 1) / 2) + rib)[..., None], 0, 1)
    S.dome(0, 0, L, L * 0.48, ang, 0.008, col, power=0.3)
    S.tube([(math.cos(ang) * -L, math.sin(ang) * -L), (math.cos(ang) * -L * 1.35, math.sin(ang) * -L * 1.35)],
           [0.004, 0.003], [0.006, 0.004], base * 0.8)
    return S.finish(0.5)


def sprite_carcass(rng):
    """horned beast skull + spine + ribs, half sunk, mossy (top view, ~4.6 m long)"""
    import cv2
    S = Sprite(5.8)
    bone = np.array([0.70, 0.65, 0.53])                    # weathered bone (pre-grade)

    def bone_col(t, rr):
        k = 0.82 + 0.18 * (1 - np.clip(rr, 0, 1) ** 2)
        return np.clip(bone * k[..., None], 0, 1)

    L = rng.uniform(2.6, 3.2)                       # spine length
    bend = rng.uniform(0.18, 0.35) * rng.choice([-1, 1])
    ts = np.linspace(0, 1, 40)
    sx = -0.9 + ts * L
    sy = bend * np.sin(ts * math.pi * 1.2) + 0.05 * np.sin(ts * 9)

    def spine(t):
        i = min(int(t * 39), 38); f = t * 39 - i
        p = np.array([sx[i] + (sx[i + 1] - sx[i]) * f, sy[i] + (sy[i + 1] - sy[i]) * f])
        tg = np.array([sx[i + 1] - sx[i], sy[i + 1] - sy[i]]); tg /= np.linalg.norm(tg)
        return p, tg, np.array([-tg[1], tg[0]])
    # ribs first (lower), spine and skull on top
    nr = rng.randint(6, 9)
    for i in range(nr):
        t = 0.06 + 0.5 * i / (nr - 1)
        p, tg, nm = spine(t)
        span = (1.0 - 0.45 * i / nr) * rng.uniform(0.85, 1.05)
        for side in (-1, 1):
            if rng.rand() < 0.12:
                continue                              # a missing rib
            smax = rng.uniform(0.6, 1.0) if rng.rand() < 0.3 else 1.0
            ss_ = np.linspace(0, smax, 9)
            pts = [p + nm * side * span * s + tg * (0.32 * s * s - 0.05 * s) for s in ss_]
            S.tube(pts, list(0.075 - 0.04 * ss_), list(0.24 * (1 - 0.75 * ss_) + 0.02), bone_col)
    nv = 18
    for i in range(nv):
        t = i / (nv - 1)
        p, tg, nm = spine(t)
        r = 0.16 - 0.10 * t
        S.dome(p[0], p[1], r * 1.05, r * 0.8, math.atan2(tg[1], tg[0]), 0.26 - 0.16 * t,
               _shade_fn(bone, tip=1.0, edge=0.35), power=0.6)
        if i % 2 == 0 and t < 0.7:
            S.dome(p[0], p[1], r * 0.3, r * 0.95, math.atan2(tg[1], tg[0]), 0.30 - 0.18 * t, _shade_fn(bone * 1.02))
    # skull, looking toward -x
    p, tg, nm = spine(0.0)
    fwd = -tg
    sk = p + fwd * 0.7
    ang = math.atan2(fwd[1], fwd[0])
    S.dome(sk[0], sk[1], 0.68, 0.52, ang, 0.55, _shade_fn(bone, tip=1.05, edge=0.3), power=0.55)
    sn0 = sk + fwd * 0.38; sn1 = sk + fwd * 1.2
    S.tube([sn0, sn1], [0.32, 0.18], [0.42, 0.26], bone_col)
    for side in (-1, 1):                              # jaws + fangs
        j0 = sk + nm * side * 0.3 + fwd * 0.2; j1 = sn1 + nm * side * 0.1 + fwd * 0.05
        S.tube([j0, j1], [0.09, 0.06], [0.18, 0.13], bone_col)
        for k in range(4):
            q = j0 + (j1 - j0) * (0.35 + 0.17 * k) + nm * side * 0.05
            S.dome(q[0], q[1], 0.045, 0.03, ang, 0.22, (0.80, 0.77, 0.68), power=0.4)
    for side in (-1, 1):                              # horns sweeping back
        b0 = sk + nm * side * 0.4 - fwd * 0.05
        ss_ = np.linspace(0, 1, 12)
        pts = [b0 + nm * side * (0.7 * s) - fwd * (1.3 * s - 0.4 * s ** 2.2) + nm * side * 0.3 * s ** 3 for s in ss_]
        horn = np.array([0.50, 0.42, 0.32])                # dark horn
        S.tube(pts, list(0.15 * (1 - ss_) + 0.015), list(0.5 * (1 - 0.55 * ss_)),
               lambda t, rr, horn=horn: np.clip(horn * (0.8 + 0.25 * (1 - rr[..., None] ** 2)) * (1 - 0.25 * t[..., None]), 0, 1))
    for side in (-1, 1):                              # eye sockets + nostrils
        e = sk + fwd * 0.16 + nm * side * 0.26
        S.dent(e[0], e[1], 0.15, 0.11, ang + side * 0.3, 0.18, (0.06, 0.05, 0.04))
        nn = sn1 - fwd * 0.08 + nm * side * 0.06
        S.dent(nn[0], nn[1], 0.04, 0.03, ang, 0.05, (0.1, 0.08, 0.07))
    # moss on the low parts + half-buried: smooth low-frequency noise, never per-pixel grain
    n = S.n
    g = rng.rand(8, 8).astype(np.float32)
    nz = cv2.resize(g, (n, n), interpolation=cv2.INTER_CUBIC)
    low = np.clip(1 - S.h / 0.3, 0, 1)
    S.c = S.c * (1 - 0.35 * low[..., None]) + np.array([0.30, 0.24, 0.16], np.float32) * 0.35 * low[..., None]
    moss = _ss(0.5, 0.75, nz) * (S.h < 0.2) * (S.a > 0.5)
    S.c = S.c * (1 - 0.8 * moss[..., None]) + np.array([0.24, 0.38, 0.16], np.float32) * 0.8 * moss[..., None]
    g2 = rng.rand(6, 6).astype(np.float32)
    bur = _ss(0.12, 0.3, cv2.resize(g2, (n, n), interpolation=cv2.INTER_CUBIC))
    S.a *= np.where(S.h < 0.12, bur, 1.0)
    return S.finish()


def sprite_stain(rng, size=5.6):
    """soft dark soil patch under a carcass"""
    import cv2
    S = Sprite(size)
    n = S.n
    y, x = (np.mgrid[0:n, 0:n].astype(np.float32) - n // 2) / SPPM
    g = cv2.resize(rng.rand(6, 6).astype(np.float32), (n, n), interpolation=cv2.INTER_CUBIC)
    r = np.sqrt((x / (size * 0.42)) ** 2 + (y / (size * 0.3)) ** 2) + (g - 0.5) * 0.25
    S.a = (_ss(1.0, 0.45, r) * 0.32).astype(np.float32)
    S.c[:] = np.array([0.30, 0.24, 0.16], np.float32)
    S.c *= S.a[..., None]                                      # premultiplied, like finish()
    return S


# ================================================================== world classes + placement
def world_classes(tiles):
    """tiles: {name: (original rgb HxWx3 (1024), xz map (2H x 2W x 2), coverage)} -> per grid cell colour masks"""
    import cv2
    import map_hd
    x0, x1, z0, z1 = GRID
    W, H = int((x1 - x0) * GPPM), int((z1 - z0) * GPPM)
    acc = np.zeros((H, W, 3), np.float64); cnt = np.zeros((H, W), np.float64)
    for name, (rgb, xz, cov) in sorted(tiles.items()):
        f = xz.shape[0] // rgb.shape[0]
        xs, cs = xz[::f, ::f], cov[::f, ::f]
        gx = ((xs[..., 0] - x0) * GPPM).astype(np.int64); gy = ((z1 - xs[..., 1]) * GPPM).astype(np.int64)
        m = cs & (gx >= 0) & (gx < W) & (gy >= 0) & (gy < H)
        np.add.at(acc, (gy[m], gx[m]), rgb[m].astype(np.float64))
        np.add.at(cnt, (gy[m], gx[m]), 1.0)
    cover = cnt > 0
    col = (acc / np.maximum(cnt, 1)[..., None]).astype(np.float32)
    grass, water, _ = map_hd.masks(col)
    grass, water = grass * cover, water * cover
    lane = cv2.GaussianBlur(((1 - grass - water) > 0.55).astype(np.float32) * cover, (0, 0), 1.0) > 0.5
    lane_d = cv2.distanceTransform((~lane).astype(np.uint8), cv2.DIST_L2, 5) / GPPM
    water_d = cv2.distanceTransform((water < 0.4).astype(np.uint8), cv2.DIST_L2, 5) / GPPM
    edge_d = cv2.distanceTransform(cover.astype(np.uint8), cv2.DIST_L2, 5) / GPPM
    return dict(grass=grass, water=water, lane=lane, lane_d=lane_d, water_d=water_d, edge_d=edge_d, cover=cover)


def _cell(x, z):
    x0, x1, z0, z1 = GRID
    return int((z1 - z) * GPPM), int((x - x0) * GPPM)


# Monster carcasses on the blue half (mirrored through the map centre): x, z, rotation (deg), scale, sprite seed.
# Found by a search for open jungle clearings (clear of walls and water, >= 9 m apart, never on a lane or in the
# river) and then pinned to the spots the user approved, so later changes elsewhere can never move them.
CARCASSES = [
    (-20.95, -11.25, 128.935, 0.8697, 295269503),
    (-10.45, -10.75, 177.972, 0.8842, 770912452),
]


def placements(classes, foot, ao, wall_plants):
    """-> list of decals {kind, x, z, rot, scale, seed, variant}; generated on the blue half (x < 0) and mirrored
    through the map centre (x, z, rot) -> (-x, -z, rot + 180 deg)."""
    import cv2
    rng = np.random.RandomState(SEED)
    G = classes
    H, W = G['grass'].shape
    # props footprint (walls, rocks, buildings) on the placement grid, dilated: nothing is painted under / into them
    fh, fw = foot.shape
    foot_g = cv2.resize((foot > 0.5).astype(np.uint8), (W, H), interpolation=cv2.INTER_NEAREST) if (fh, fw) != (H, W) else (foot > 0.5).astype(np.uint8)
    wall_d = cv2.distanceTransform((1 - foot_g).astype(np.uint8), cv2.DIST_L2, 5) / GPPM
    ao_g = cv2.resize(ao, (W, H), interpolation=cv2.INTER_LINEAR) if ao.shape != (H, W) else ao
    out = []
    xs_c = GRID[0] + (np.arange(W) + 0.5) / GPPM
    zs_c = GRID[3] - (np.arange(H) + 0.5) / GPPM
    half = xs_c[None, :] < -0.3
    base = (np.abs(xs_c)[None, :] > 43) & (np.abs(zs_c)[:, None] < 13)
    # lane model (the lanes here are mostly grass-coloured, so colour alone cannot find them): side lanes run along
    # the diamond edges, the mid lane along z = 0, the river along x = 0
    d_in = (1 - np.abs(xs_c)[None, :] / 50.0 - np.abs(zs_c)[:, None] / 44.0) * 33.0
    side_lane = d_in < 8.5
    mid_lane = (np.abs(zs_c)[:, None] < 5.5) & (np.abs(xs_c)[None, :] < 46)
    river = np.abs(xs_c)[None, :] < 6.5
    jungle = ~side_lane & ~mid_lane & ~river

    # --- fallen leaves around the plants growing on the jungle walls
    for (px, pz) in wall_plants:
        if px >= -0.3:
            continue
        for _ in range(rng.randint(5, 10)):
            for _try in range(10):
                a = rng.uniform(0, 2 * math.pi); d = rng.uniform(0.6, 2.6)
                x, z = px + math.cos(a) * d, pz + math.sin(a) * d
                r, c = _cell(x, z)
                if 0 <= r < H and 0 <= c < W and wall_d[r, c] > 0.15 and G['cover'][r, c] and not G['lane'][r, c] \
                        and G['water'][r, c] < 0.4:
                    out.append(dict(kind='leaf', x=x, z=z, rot=rng.uniform(0, 360), scale=rng.uniform(0.85, 1.3),
                                    seed=int(rng.randint(1 << 30)), variant=0))
                    break
    # --- monster carcasses: the pinned spots (see CARCASSES); each must still lie on open jungle ground, clear of
    # walls and water, never on a lane or in the river
    k = int(1.6 * GPPM)
    clear = cv2.erode(((wall_d > 0.3) & (G['water_d'] > 0.2) & G['cover'] & (G['edge_d'] > 0.5)).astype(np.uint8),
                      cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * k + 1, 2 * k + 1))) > 0
    ok = clear & cv2.erode(jungle.astype(np.uint8), np.ones((31, 31), np.uint8)).astype(bool) & ~base
    for x, z, rot, s, sd in CARCASSES:
        r, c = _cell(x, z)
        if not ok[r, c]:
            raise ValueError(f'carcass at ({x}, {z}) is no longer on open jungle ground')
        out.append(dict(kind='stain', x=x, z=z, rot=rot, scale=s, seed=sd, variant=0))
        out.append(dict(kind='carcass', x=x, z=z, rot=rot, scale=s, seed=sd, variant=0))
    mirrored = [dict(d, x=-d['x'], z=-d['z'], rot=(d['rot'] + 180.0) % 360) for d in out]
    return out + mirrored


ORDER = {'stain': 0, 'leaf': 1, 'carcass': 2}


def make_sprite(d):
    rng = np.random.RandomState(d['seed'])
    k = d['kind']
    if k == 'leaf':
        return sprite_leaf(rng)
    if k == 'carcass':
        return sprite_carcass(rng)
    if k == 'stain':
        return sprite_stain(rng)
    raise ValueError(k)


# ================================================================== painting into a ground tile
def tile_decals(decals, xz, cov):
    """decals whose footprint touches this tile's covered texels"""
    lo = xz[cov].min(0) - 3.0; hi = xz[cov].max(0) + 3.0
    return [d for d in decals if lo[0] <= d['x'] <= hi[0] and lo[1] <= d['z'] <= hi[1]]


def apply(rgb, xz, cov, tex_dir, decals, sprites):
    """Paint decals into a (pre-shadow, pre-grade) ground texture. xz: per-texel world position; tex_dir: light
    direction in texture space. sprites: cache {id(decal) or key: Sprite}."""
    import cv2
    H, W = rgb.shape[:2]
    # texel <-> world affine (exact for the planar ground UVs), from the covered texels
    yy, xx = np.nonzero(cov[::16, ::16])
    P = np.c_[xx * 16, yy * 16, np.ones(len(xx))]
    Q = xz[yy * 16, xx * 16]
    Aw = np.linalg.lstsq(P, Q, rcond=None)[0]                      # texel -> world: [tx, ty, 1] @ Aw
    tpm = 1.0 / math.sqrt(abs(np.linalg.det(Aw[:2])))               # texels per metre
    A = np.zeros((H, W), np.float32)
    C = np.zeros((H, W, 3), np.float32)
    Hh = np.zeros((H, W), np.float32)
    for d in sorted(decals, key=lambda d: (ORDER[d['kind']], d['seed'])):
        key = (d['kind'], d['seed'], d['variant'])
        if key not in sprites:
            sprites[key] = make_sprite(d)
        S = sprites[key]
        s = d['scale']
        rad = S.n / 2 / SPPM * s * 1.42
        # texel window around the decal
        c_tex = np.linalg.solve(Aw[:2].T, np.array([d['x'], d['z']]) - Aw[2])
        rt = rad * tpm
        x0, x1 = int(max(c_tex[0] - rt, 0)), int(min(c_tex[0] + rt + 1, W))
        y0, y1 = int(max(c_tex[1] - rt, 0)), int(min(c_tex[1] + rt + 1, H))
        if x1 <= x0 or y1 <= y0:
            continue
        X = xz[y0:y1, x0:x1, 0] - d['x']
        Z = xz[y0:y1, x0:x1, 1] - d['z']
        th = math.radians(d['rot'])
        u = (math.cos(th) * X + math.sin(th) * Z) / s          # sprite x (m)
        v = (math.sin(th) * X - math.cos(th) * Z) / s          # sprite y (m, image down = -z)
        mx = (u * SPPM + S.n // 2).astype(np.float32)
        my = (v * SPPM + S.n // 2).astype(np.float32)
        a = cv2.remap(S.a, mx, my, cv2.INTER_LINEAR, borderMode=cv2.BORDER_CONSTANT, borderValue=0)
        if a.max() < 1e-3:
            continue
        c = cv2.remap(S.c, mx, my, cv2.INTER_LINEAR, borderMode=cv2.BORDER_CONSTANT, borderValue=0)
        c = c / np.maximum(a, 1e-4)[..., None]                   # premultiplied -> straight colour
        h = cv2.remap(S.h, mx, my, cv2.INTER_LINEAR, borderMode=cv2.BORDER_CONSTANT, borderValue=0) * s
        a = a * cov[y0:y1, x0:x1]
        sl = (slice(y0, y1), slice(x0, x1))
        if d['kind'] == 'stain':                               # flat tint of the ground only
            C[sl] = C[sl] * (1 - a[..., None]) + c * a[..., None]
            A[sl] = A[sl] + a * (1 - A[sl])
            continue
        vis = a * (h >= Hh[sl] - 1e-4)
        C[sl] = C[sl] * (1 - vis[..., None]) + c * vis[..., None]
        A[sl] = A[sl] + vis * (1 - A[sl])
        Hh[sl] = np.where(vis > 0.5, np.maximum(Hh[sl], h), Hh[sl])
    if A.max() < 1e-4:
        return rgb
    # --- light the decal layer like the rest of the map (same texture-space light direction, 45 deg sun)
    lx, ly = float(tex_dir[0]), float(tex_dir[1])
    el = math.radians(45.0)
    Lv = np.array([lx * math.cos(el), ly * math.cos(el), math.sin(el)])
    hp = Hh * tpm                                              # height in texels
    gx = cv2.Sobel(hp, cv2.CV_32F, 1, 0, ksize=3) / 8.0
    gy = cv2.Sobel(hp, cv2.CV_32F, 0, 1, ksize=3) / 8.0
    nz = 1.0 / np.sqrt(gx * gx + gy * gy + 1.0)
    ndl = (-gx * Lv[0] - gy * Lv[1] + Lv[2]) * nz
    shade = 0.45 + 0.55 * np.clip(ndl, 0, 1) / Lv[2]
    cav = np.clip((cv2.GaussianBlur(hp, (0, 0), 3.0) - hp) / 6.0, 0, 1)     # crevices between bones / petals
    shade = shade * (1 - 0.35 * cav)
    # --- contact shadow cast by raised decals onto the ground and onto each other
    sh = np.zeros_like(Hh)
    if Hh.max() > 0.005:
        step = 1.5
        nmax = int(min(Hh.max() * tpm / step, 40)) + 1
        for k in range(1, nmax + 1):
            t = k * step
            M = np.float32([[1, 0, -lx * t], [0, 1, -ly * t]])     # sample toward the light
            occ = cv2.warpAffine(hp, M, (W, H), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_CONSTANT)
            sh = np.maximum(sh, np.clip((occ - (hp + t * math.tan(el))) / 3.0, 0, 1))
        sh = cv2.GaussianBlur(sh, (0, 0), 1.2)
    ground = rgb * (1 - 0.45 * sh)[..., None]
    lit = np.clip(C * shade[..., None] * (1 - 0.35 * sh)[..., None], 0, 1)
    out = ground * (1 - A[..., None]) + lit * A[..., None]
    return np.clip(out, 0, 1).astype(np.float32)
