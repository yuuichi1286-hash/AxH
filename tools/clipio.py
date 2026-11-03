"""Decode/encode Unity (2017-2019) Mecanim generic AnimationClip runtime data (streamed/dense/constant)."""
import struct, zlib
import numpy as np

def f2u(f): return struct.unpack('<I', struct.pack('<f', f))[0]
def u2f(u): return struct.unpack('<f', struct.pack('<I', u & 0xFFFFFFFF))[0]

def parse_streamed(words):
    """words: list of uint32. returns list of frames: (time, [(curveIdx, c0,c1,c2,c3), ...])"""
    b = struct.pack('<%dI' % len(words), *[w & 0xFFFFFFFF for w in words])
    frames = []
    off = 0
    n = len(b)
    while off < n:
        t, cnt = struct.unpack_from('<fi', b, off); off += 8
        keys = []
        for _ in range(cnt):
            idx, c0, c1, c2, c3 = struct.unpack_from('<i4f', b, off); off += 20
            keys.append((idx, c0, c1, c2, c3))
        frames.append((t, keys))
    return frames

def build_streamed(frames):
    out = bytearray()
    for t, keys in frames:
        out += struct.pack('<fi', t, len(keys))
        for k in keys:
            out += struct.pack('<i4f', *k)
    return list(struct.unpack('<%dI' % (len(out) // 4), bytes(out)))

def streamed_keys_per_curve(frames, ncurves):
    per = [[] for _ in range(ncurves)]
    for t, keys in frames:
        for (idx, c0, c1, c2, c3) in keys:
            if 0 <= idx < ncurves:
                per[idx].append((t, c0, c1, c2, c3))
    return per

def eval_streamed(per_curve, times):
    out = np.zeros((len(times), len(per_curve)), np.float64)
    for ci, keys in enumerate(per_curve):
        if not keys: continue
        kt = np.array([k[0] for k in keys])
        kt_clamped = np.where(np.isfinite(kt), kt, np.where(kt < 0, -1e30, 1e30))
        pos = np.searchsorted(kt_clamped, times, side='right') - 1
        pos = np.clip(pos, 0, len(keys) - 1)
        for j, t in enumerate(times):
            k = keys[pos[j]]
            t0 = k[0]
            dt = 0.0 if not np.isfinite(t0) or abs(t0) > 1e29 else t - t0
            out[j, ci] = ((k[1] * dt + k[2]) * dt + k[3]) * dt + k[4]
    return out

def decode_clip(tt):
    mc = tt['m_MuscleClip']; data = mc['m_Clip']['data']
    sc, dc, cc = data['m_StreamedClip'], data['m_DenseClip'], data['m_ConstantClip']
    ns = sc['curveCount']; nd = dc['m_CurveCount']; ncst = len(cc['data'])
    start, stop = mc['m_StartTime'], mc['m_StopTime']
    return dict(ns=ns, nd=nd, nc=ncst, start=start, stop=stop,
                frames=parse_streamed(sc['data']) if ns else [],
                dense=np.array(dc['m_SampleArray'], np.float64).reshape(dc['m_FrameCount'], nd) if nd else None,
                dense_rate=dc['m_SampleRate'], dense_begin=dc['m_BeginTime'],
                const=np.array(cc['data'], np.float64))

def sample_clip(dec, times):
    """Return matrix times x (ns+nd+nc)"""
    parts = []
    if dec['ns']:
        per = streamed_keys_per_curve(dec['frames'], dec['ns'])
        parts.append(eval_streamed(per, times))
    if dec['nd']:
        D = dec['dense']; rate = dec['dense_rate']; begin = dec['dense_begin']
        fi = (times - begin) * rate
        i0 = np.clip(np.floor(fi).astype(int), 0, len(D) - 1)
        i1 = np.clip(i0 + 1, 0, len(D) - 1)
        w = np.clip(fi - np.floor(fi), 0, 1)[:, None]
        parts.append(D[i0] * (1 - w) + D[i1] * w)
    if dec['nc']:
        parts.append(np.tile(dec['const'][None, :], (len(times), 1)))
    return np.concatenate(parts, 1) if parts else np.zeros((len(times), 0))

def binding_layout(tt):
    """list of (pathHash, attribute, ncurves, firstCurveIndex) in curve order"""
    res = []; c = 0
    for b in tt['m_ClipBindingConstant']['genericBindings']:
        attr = b['attribute']; tid = b['typeID']
        if tid == 4:
            n = {1: 3, 2: 4, 3: 3, 4: 3}.get(attr, 1)
        else:
            n = 1
        res.append((b['path'], attr, n, c, tid))
        c += n
    return res, c

def transform_paths(env_objs, root_tf_pid):
    """map crc32(path)->name for all transforms under given root transform"""
    tfs = {}; names = {}
    for o in env_objs:
        if o.type.name == 'Transform':
            tfs[o.path_id] = o.read_typetree()
    gos = {o.path_id: o for o in env_objs if o.type.name == 'GameObject'}
    def nm(pid):
        return gos[tfs[pid]['m_GameObject']['m_PathID']].read_typetree()['m_Name']
    out = {}
    def walk(pid, path):
        for ch in tfs[pid]['m_Children']:
            cp = ch['m_PathID']
            p = (path + '/' if path else '') + nm(cp)
            out[zlib.crc32(p.encode())] = p
            walk(cp, p)
    out[zlib.crc32(b'')] = ''
    walk(root_tf_pid, '')
    return out
