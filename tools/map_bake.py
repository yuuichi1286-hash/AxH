"""Baked realism for Sanctum Island (High): cast shadows + ambient occlusion of every building / prop on the
ground, emboss relief, cavity AO and a PBR-like specular sheen in the textures, sharper water reflections.

The game's real-time renderer and shaders are not part of the map files, so real-time shadows / SSR / PBR
shaders cannot be switched on from a map. Everything here is baked into the textures and the reflection
cubemap instead: it looks the same from the fixed MOBA camera and costs nothing at run time.

Light: the map's own crystal shaders use _CustomLightDir (0.61, 0.71, -0.35) (direction towards the light);
shadows are cast along the opposite direction (towards -x / +z), elevation ~45 deg.
"""
import os, sys, math
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import numpy as np

TO_LIGHT = np.array([0.61, 0.71, -0.35]) / np.linalg.norm([0.61, 0.71, -0.35])
L = -TO_LIGHT                                   # light travel direction
GRID = (-72.0, 72.0, -58.0, 58.0)              # world x0, x1, z0, z1 of the bake grid
PPM = 20.0                                       # bake grid resolution (px per metre)
SKIP_PROPS = ('skybox', 'grass', 'leaf', 'outsideleaf')     # alpha-cut cards / sky dome: no solid shadow


def _ss(a, b, x):
    t = np.clip((x - a) / (b - a), 0, 1)
    return t * t * (3 - 2 * t)


# ------------------------------------------------------------------ scene geometry
def scene_meshes(env, layers):
    """[(name, world 4x4, decoded mesh)] for renderers on the given layers."""
    from map_render import Scene
    from meshio import decode
    sc = Scene(env)
    out, cache, failed = [], {}, 0
    for name, layer, M, mesh_pid, mats in sc.renderers():
        if layer not in layers:
            continue
        if mesh_pid not in cache:
            try:
                cache[mesh_pid] = decode(sc.shared[mesh_pid].read_typetree())
            except Exception:
                cache[mesh_pid] = None
        d = cache[mesh_pid]
        if d is None or 'pos' not in d:
            failed += 1
            continue
        out.append((name, M, d))
    return out, failed


def world_tris(M, d):
    pos = d['pos'][:, :3].astype(np.float64)
    wp = (M @ np.c_[pos, np.ones(len(pos))].T).T[:, :3]
    idx = d['index'].astype(np.int64)
    n = len(idx) // 3 * 3
    return wp[idx[:n]].reshape(-1, 3, 3)


def to_grid(x, z):
    x0, x1, z0, z1 = GRID
    return (x - x0) * PPM, (z1 - z) * PPM


def grid_size():
    x0, x1, z0, z1 = GRID
    return int((z1 - z0) * PPM), int((x1 - x0) * PPM)


def fill_tris(mask, tri_xy):
    """cv2.fillPoly with 4-bit sub-pixel precision for many triangles."""
    import cv2
    if not len(tri_xy):
        return
    pts = np.round(tri_xy * 16).astype(np.int32)
    cv2.fillPoly(mask, list(pts), 1.0, lineType=cv2.LINE_8, shift=4)


def raster_attr(shape, tri_xy, tri_val, out, cover):
    """Rasterise per-vertex attribute (k values) into out[H, W, k] (last triangle wins)."""
    H, W = shape
    for p, v in zip(tri_xy, tri_val):
        x0, x1 = int(max(np.floor(p[:, 0].min()), 0)), int(min(np.ceil(p[:, 0].max()), W - 1))
        y0, y1 = int(max(np.floor(p[:, 1].min()), 0)), int(min(np.ceil(p[:, 1].max()), H - 1))
        if x1 < x0 or y1 < y0:
            continue
        ys, xs = np.mgrid[y0:y1 + 1, x0:x1 + 1]
        px, py = xs + 0.5, ys + 0.5
        (ax, ay), (bx, by), (cx, cy) = p[0], p[1], p[2]
        den = (by - cy) * (ax - cx) + (cx - bx) * (ay - cy)
        if abs(den) < 1e-12:
            continue
        w0 = ((by - cy) * (px - cx) + (cx - bx) * (py - cy)) / den
        w1 = ((cy - ay) * (px - cx) + (ax - cx) * (py - cy)) / den
        w2 = 1 - w0 - w1
        m = (w0 >= -1e-3) & (w1 >= -1e-3) & (w2 >= -1e-3)
        if not m.any():
            continue
        val = w0[..., None] * v[0] + w1[..., None] * v[1] + w2[..., None] * v[2]
        out[ys[m], xs[m]] = val[m]
        cover[ys[m], xs[m]] = True


def ground_heightmap(ground):
    H, W = grid_size()
    hm = np.zeros((H, W, 1), np.float64)
    cov = np.zeros((H, W), bool)
    for name, M, d in ground:
        tris = world_tris(M, d)
        gx, gy = to_grid(tris[..., 0], tris[..., 2])
        raster_attr((H, W), np.stack([gx, gy], -1), tris[..., 1:2], hm, cov)
    hm = hm[..., 0]
    if (~cov).any():                               # outside the island: nearest ground height
        from scipy import ndimage
        idx = ndimage.distance_transform_edt(~cov, return_distances=False, return_indices=True)
        hm = hm[idx[0], idx[1]]
    return hm.astype(np.float32)


def shadow_ao_maps(props, hm):
    """World-space (grid) cast-shadow and contact-AO maps, both 0..1."""
    import cv2
    H, W = grid_size()
    shadow = np.zeros((H, W), np.float32)
    foot = np.zeros((H, W), np.float32)

    def h_at(x, z):
        gx, gy = to_grid(x, z)
        gx = np.clip(gx.astype(int), 0, W - 1); gy = np.clip(gy.astype(int), 0, H - 1)
        return hm[gy, gx]

    for name, M, d in props:
        if any(s in name.lower() for s in SKIP_PROPS):
            continue
        tris = world_tris(M, d)
        # buried geometry casts nothing: drop triangles fully under the ground, lift partly buried vertices
        hv = h_at(tris[..., 0].ravel(), tris[..., 2].ravel()).reshape(-1, 3)
        keep = (tris[..., 1] > hv + 0.03).any(1)
        tris = tris[keep].copy()
        hv = hv[keep]
        tris[..., 1] = np.maximum(tris[..., 1], hv)
        P = tris.reshape(-1, 3)
        t = np.maximum((P[:, 1] - h_at(P[:, 0], P[:, 2])) / -L[1], 0)
        Q = P + L * t[:, None]
        t = np.maximum((P[:, 1] - h_at(Q[:, 0], Q[:, 2])) / -L[1], 0)
        Q = P + L * t[:, None]
        gx, gy = to_grid(Q[:, 0], Q[:, 2])
        fill_tris(shadow, np.stack([gx, gy], -1).reshape(-1, 3, 2))
        # contact footprint: geometry within 0.9 m of the ground, projected straight down
        above = (P[:, 1] - h_at(P[:, 0], P[:, 2])).reshape(-1, 3)
        low = above.min(1) < 0.9
        if low.any():
            fx, fy = to_grid(tris[low][..., 0], tris[low][..., 2])
            fill_tris(foot, np.stack([fx, fy], -1))
    px = PPM
    soft = cv2.GaussianBlur(shadow, (0, 0), 0.12 * px) * 0.65 + cv2.GaussianBlur(shadow, (0, 0), 0.45 * px) * 0.35
    ao = np.clip(cv2.GaussianBlur(foot, (0, 0), 0.55 * px) * 1.6, 0, 1) * (1 - foot)
    ao = np.maximum(ao, cv2.GaussianBlur(foot, (0, 0), 1.6 * px) * 0.6 * (1 - foot))
    return np.clip(soft, 0, 1), np.clip(ao, 0, 1)


def tile_position_map(meshes, size):
    """Per-texel world (x, z) of a ground texture, rasterised from EVERY mesh that samples it (ground tile and
    the river surface meshes that reuse the same texture); texels outside all UV islands take the nearest."""
    from scipy import ndimage
    W, H = size
    out = np.zeros((H, W, 2), np.float64)
    cov = np.zeros((H, W), bool)
    uv_all, xz_all = [], []
    for M, d in meshes:
        tris = world_tris(M, d)
        uv = d['uv0'][:, :2].astype(np.float64)
        idx = d['index'].astype(np.int64)
        n = len(idx) // 3 * 3
        uvt = uv[idx[:n]].reshape(-1, 3, 2)
        px = np.stack([uvt[..., 0] * W, (1 - uvt[..., 1]) * H], -1)
        raster_attr((H, W), px, tris[..., [0, 2]], out, cov)
        uv_all.append(uvt.reshape(-1, 2)); xz_all.append(tris[..., [0, 2]].reshape(-1, 2))
    if (~cov).any() and cov.any():
        ii = ndimage.distance_transform_edt(~cov, return_distances=False, return_indices=True)
        out = out[ii[0], ii[1]]
    # texture-space direction of the horizontal light (for relief shading): least squares uv -> world
    uvs, xzs = np.concatenate(uv_all), np.concatenate(xz_all)
    A = np.c_[uvs, np.ones(len(uvs))]
    sol, *_ = np.linalg.lstsq(A, xzs, rcond=None)
    J = sol[:2].T                                  # d(world x,z) / d(u,v)
    to_light_xz = TO_LIGHT[[0, 2]]
    duv = np.linalg.lstsq(J, to_light_xz, rcond=None)[0]
    tex_dir = np.array([duv[0], -duv[1]])          # image x right, y down
    tex_dir = tex_dir / max(np.linalg.norm(tex_dir), 1e-9)
    return out.astype(np.float32), cov, tex_dir


def sample_grid(grid, xz):
    import cv2
    gx, gy = to_grid(xz[..., 0], xz[..., 1])
    return cv2.remap(grid, gx.astype(np.float32), gy.astype(np.float32), cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE)


def apply_shadow_ao(rgb, xz, shadow, ao, s_strength=0.55, ao_strength=0.40):
    sh = sample_grid(shadow, xz)
    oc = sample_grid(ao, xz)
    mul = (1 - s_strength * sh) * (1 - ao_strength * oc)
    cool = 1 + (np.array([0.965, 0.99, 1.045], np.float32) - 1) * sh[..., None]   # sky-lit shadows are cooler
    return np.clip(rgb * mul[..., None] * cool, 0, 1).astype(np.float32)


# ------------------------------------------------------------------ texture-space relief / cavity / sheen
def relief_pbr(rgb, light_dir_tex=(-0.6, -0.8), emboss=0.10, cavity=0.16, sheen=0.09, kind='ground'):
    """Emboss relief from a luminance height proxy, cavity AO in crevices and a PBR-like specular sheen on
    stone / metal (low saturation, bright); vegetation gets relief and AO but almost no sheen."""
    import cv2
    from map_hd import lum, rgb_hsv
    Lm = lum(rgb).astype(np.float32)
    k = max(1.0, min(rgb.shape[:2]) / 1024.0)
    hgt = cv2.GaussianBlur(Lm, (0, 0), 1.2 * k)
    gx = cv2.Sobel(hgt, cv2.CV_32F, 1, 0, ksize=3)
    gy = cv2.Sobel(hgt, cv2.CV_32F, 0, 1, ksize=3)
    sc = 6.0
    nx, ny, nz = -gx * sc, -gy * sc, np.ones_like(gx)
    inv = 1 / np.sqrt(nx * nx + ny * ny + nz * nz)
    nx, ny, nz = nx * inv, ny * inv, nz * inv
    lx, ly = light_dir_tex
    lz = 1.0                                       # ~45 deg elevation
    ln = math.sqrt(lx * lx + ly * ly + lz * lz)
    lx, ly, lz = lx / ln, ly / ln, lz / ln
    ndl = nx * lx + ny * ly + nz * lz
    relief = 1 + emboss * (ndl - lz) / max(1 - lz, 1e-3)
    # cavity AO (two scales)
    cav = np.clip((cv2.GaussianBlur(Lm, (0, 0), 3 * k) - Lm) * 3.0, 0, 1) * 0.6 + \
        np.clip((cv2.GaussianBlur(Lm, (0, 0), 9 * k) - Lm) * 2.0, 0, 1) * 0.4
    ao = 1 - cavity * cav
    # specular sheen (view straight down + light -> half vector)
    hx, hy, hz = lx, ly, lz + 1.0
    hn = math.sqrt(hx * hx + hy * hy + hz * hz)
    ndh = np.clip((nx * hx + ny * hy + nz * hz) / hn, 0, 1)
    h, s, v = rgb_hsv(rgb)
    stone = (1 - _ss(0.18, 0.4, s)) * _ss(0.35, 0.75, v)
    if kind == 'ground':
        stone *= 1.0
    spec = (ndh ** 28) * stone * sheen
    out = rgb * (relief * ao)[..., None] + spec[..., None] * np.array([1.0, 0.97, 0.9], np.float32)
    return np.clip(out, 0, 1).astype(np.float32)


# ------------------------------------------------------------------ reflection cubemap (SSR substitute)
def upgrade_cubemap(tt, encode_astc, size=128):
    """Sharper, higher resolution water reflection: each 32 px face (face-major data) -> 128 px with a richer
    sky gradient and a crisper sun glint; full mip chain, ASTC 6x6."""
    import cv2
    import texture2ddecoder
    from PIL import Image
    w = tt['m_Width']
    fmt = tt['m_TextureFormat']
    blk = {48: 4, 49: 5, 50: 6, 51: 8}[fmt]
    per_face = tt['m_CompleteImageSize']
    faces = []
    for f in range(6):
        raw = bytes(tt['image data'][f * per_face: f * per_face + math.ceil(w / blk) ** 2 * 16])
        bgra = np.frombuffer(texture2ddecoder.decode_astc(raw, w, w, blk, blk), np.uint8).reshape(w, w, 4)
        # raw data rows are bottom-up; encode() expects top-down images and flips them back
        faces.append(bgra[::-1, :, [2, 1, 0, 3]].astype(np.float32) / 255.0)
    new_faces = []
    for img in faces:
        big = cv2.resize(np.pad(img, ((2, 2), (2, 2), (0, 0)), mode='edge'), ((w + 4) * size // w, (w + 4) * size // w),
                         interpolation=cv2.INTER_CUBIC)
        o = 2 * size // w
        big = np.clip(big[o:o + size, o:o + size], 0, 1)
        rgb = big[..., :3]
        Lm = rgb @ np.array([0.299, 0.587, 0.114], np.float32)
        glint = _ss(0.45, 0.8, Lm)[..., None]
        rgb = rgb * (1 + 0.35 * glint) + (rgb - cv2.GaussianBlur(rgb, (0, 0), 2.0)) * 0.6
        rgb = rgb * np.array([0.96, 1.0, 1.06], np.float32)          # cleaner, slightly deeper blue sky
        big[..., :3] = np.clip(rgb, 0, 1)
        new_faces.append(Image.fromarray((big * 255 + 0.5).astype(np.uint8), 'RGBA'))
    mips = int(math.log2(size)) + 1
    data = b''
    face_bytes = None
    for im in new_faces:
        d = encode_astc(im, 50, mips)
        face_bytes = len(d)
        data += d
    tt['m_Width'] = tt['m_Height'] = size
    tt['m_TextureFormat'] = 50
    tt['m_MipCount'] = mips
    tt['image data'] = data
    tt['m_CompleteImageSize'] = face_bytes
    return tt


WATER_TWEAKS = {'_Water_Cube_Intensity': 0.8, '_Reflection_Fresnel_Intensity': 0.85}


def tweak_water_material(tt):
    fl = tt['m_SavedProperties']['m_Floats']
    n = 0
    for i, (k, v) in enumerate(fl):
        if k in WATER_TWEAKS and abs(v - WATER_TWEAKS[k]) > 1e-6:
            fl[i] = (k, float(WATER_TWEAKS[k]))
            n += 1
    return n
