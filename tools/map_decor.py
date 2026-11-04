"""Ground decoration for Sanctum Island (High), painted into the 16 ground tiles:

* a few small flower clumps in muted colours, pebbles, and fallen leaves - only on grass along the edges (the foot of
  walls, rocks, trees and buildings), never in open lanes

Placement is in WORLD space (seamless across tiles) with a fixed seed and mirrored through the map centre, so both
teams get the same scenery. Lanes stay clear: everything sits on grass at the foot of walls,
rocks, trees and buildings. Every decal has its own height map: it is lit with the map's light direction, casts a short contact
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


FLOWER_PALETTES = [  # petals, centre, weight: muted natural tones (a few soft accents, never colourful)
    ((0.93, 0.92, 0.84), (0.95, 0.78, 0.35), 0.50),      # cream white
    ((0.94, 0.87, 0.56), (0.85, 0.60, 0.26), 0.25),      # pale butter yellow
    ((0.78, 0.75, 0.90), (0.95, 0.86, 0.52), 0.15),      # soft lilac
    ((0.90, 0.75, 0.77), (0.95, 0.86, 0.52), 0.10),      # dusty pink
]


def sprite_flowers(rng, palette):
    """a small clump at the foot of a wall / rock: leaf rosette, 3-7 five/six-petal blossoms, a bud or two"""
    S = Sprite(0.8)
    leaf = _shade_fn((0.19, 0.34, 0.15), tip=1.35)
    for _ in range(rng.randint(5, 9)):
        a = rng.uniform(0, 2 * math.pi); L = rng.uniform(0.09, 0.16); r = rng.uniform(0.04, 0.22)
        S.dome(math.cos(a) * r, math.sin(a) * r, L * 0.55, L * 0.19, a + rng.uniform(-0.4, 0.4), 0.016, leaf)
    petal_c, centre_c = palette[0], palette[1]
    blossoms = []
    for _ in range(rng.randint(3, 8)):
        for _try in range(16):
            r = 0.26 * math.sqrt(rng.uniform(0, 1)); a = rng.uniform(0, 2 * math.pi)
            p = (math.cos(a) * r, math.sin(a) * r)
            if all(math.hypot(p[0] - q[0], p[1] - q[1]) > 0.12 for q in blossoms):
                blossoms.append(p)
                break
    for (cx, cy) in blossoms:
        R = rng.uniform(0.06, 0.085)
        hb = rng.uniform(0.035, 0.07)
        n_p = 5 if rng.rand() < 0.75 else 6
        rot = rng.uniform(0, 2 * math.pi)
        tint = np.clip(np.asarray(petal_c) * rng.uniform(0.92, 1.03), 0, 1)
        pf = _shade_fn(tint * 0.86, tip=1.18, edge=0.22)
        for j in range(n_p):
            a = rot + j * 2 * math.pi / n_p
            S.dome(cx + math.cos(a) * R * 0.5, cy + math.sin(a) * R * 0.5, R * 0.52, R * 0.4, a, hb + 0.012, pf)
        S.dome(cx, cy, R * 0.26, R * 0.26, 0, hb + 0.024, _shade_fn(centre_c, tip=1.0, edge=0.35), power=0.7)
    for _ in range(rng.randint(1, 3)):                      # closed buds
        a = rng.uniform(0, 2 * math.pi); r = rng.uniform(0.15, 0.3)
        S.dome(math.cos(a) * r, math.sin(a) * r, 0.028, 0.019, a, 0.032, _shade_fn(np.asarray(petal_c) * 0.8, tip=1.2))
    return S.finish()


def sprite_pebbles(rng):
    S = Sprite(0.7)
    for _ in range(rng.randint(3, 7)):
        r = rng.uniform(0.0, 0.2); a = rng.uniform(0, 2 * math.pi)
        rx = rng.uniform(0.035, 0.1); ry = rx * rng.uniform(0.6, 0.95)
        g = rng.uniform(0.36, 0.52)
        base = np.array([g * rng.uniform(0.98, 1.04), g * rng.uniform(0.98, 1.03), g * rng.uniform(0.95, 1.0)])
        S.dome(math.cos(a) * r, math.sin(a) * r, rx, ry, rng.uniform(0, math.pi), rx * 0.55,
               _shade_fn(base, tip=1.0, edge=0.3), power=0.7)
    return S.finish()


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


def placements(classes, foot, wall_plants):
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
    out = []
    xs_c = GRID[0] + (np.arange(W) + 0.5) / GPPM
    zs_c = GRID[3] - (np.arange(H) + 0.5) / GPPM
    half = xs_c[None, :] < -0.3
    base = (np.abs(xs_c)[None, :] > 43) & (np.abs(zs_c)[:, None] < 13)

    def poisson(ok, min_d, accept, n_try):
        ys, xs = np.nonzero(ok)
        if not len(ys):
            return []
        order = rng.permutation(len(ys))[:n_try]
        pts = []
        cell = min_d / math.sqrt(2)
        grid = {}
        for k in order:
            x, z = xs_c[xs[k]], zs_c[ys[k]]
            if rng.rand() > accept:
                continue
            gi, gj = int(x / cell), int(z / cell)
            if any(math.hypot(x - q[0], z - q[1]) < min_d for di in (-2, -1, 0, 1, 2) for dj in (-2, -1, 0, 1, 2)
                   for q in grid.get((gi + di, gj + dj), ())):
                continue
            grid.setdefault((gi, gj), []).append((x, z)); pts.append((x, z))
        return pts

    # everything lives only on GRASS along EDGES: the foot of walls, rocks, trees and buildings
    edge = (wall_d > 0.3) & (wall_d < 1.5)
    # --- flowers: few small clumps in muted colours
    ok = half & edge & (G['grass'] > 0.65) & (G['water_d'] > 0.6) & (G['edge_d'] > 0.6)
    cum = np.cumsum([p[2] for p in FLOWER_PALETTES]); cum = cum / cum[-1]
    for x, z in poisson(ok, 5.5, 0.5, 30000):
        pal = int(min(np.searchsorted(cum, rng.rand()), len(FLOWER_PALETTES) - 1))
        out.append(dict(kind='flowers', x=x, z=z, rot=rng.uniform(0, 360), scale=rng.uniform(0.85, 1.1),
                        seed=int(rng.randint(1 << 30)), variant=pal))
    # --- pebbles
    ok = half & edge & (wall_d < 1.1) & (G['grass'] > 0.35) & (G['water_d'] > 0.3) & (G['edge_d'] > 0.6) & ~base
    for x, z in poisson(ok, 3.5, 0.45, 30000):
        out.append(dict(kind='pebbles', x=x, z=z, rot=rng.uniform(0, 360), scale=rng.uniform(0.85, 1.25),
                        seed=int(rng.randint(1 << 30)), variant=0))
    # --- fallen leaves around the plants growing on the jungle walls
    for (px, pz) in wall_plants:
        if px >= -0.3:
            continue
        for _ in range(rng.randint(5, 10)):
            for _try in range(10):
                a = rng.uniform(0, 2 * math.pi); d = rng.uniform(0.6, 2.6)
                x, z = px + math.cos(a) * d, pz + math.sin(a) * d
                r, c = _cell(x, z)
                if 0 <= r < H and 0 <= c < W and 0.15 < wall_d[r, c] < 2.2 and G['cover'][r, c] \
                        and G['grass'][r, c] > 0.35 and not G['lane'][r, c] and G['water'][r, c] < 0.4:
                    out.append(dict(kind='leaf', x=x, z=z, rot=rng.uniform(0, 360), scale=rng.uniform(0.85, 1.3),
                                    seed=int(rng.randint(1 << 30)), variant=0))
                    break
    mirrored = [dict(d, x=-d['x'], z=-d['z'], rot=(d['rot'] + 180.0) % 360) for d in out]
    return out + mirrored


ORDER = {'leaf': 0, 'pebbles': 1, 'flowers': 2}


def make_sprite(d):
    rng = np.random.RandomState(d['seed'])
    k = d['kind']
    if k == 'flowers':
        return sprite_flowers(rng, FLOWER_PALETTES[d['variant']])
    if k == 'pebbles':
        return sprite_pebbles(rng)
    if k == 'leaf':
        return sprite_leaf(rng)
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
