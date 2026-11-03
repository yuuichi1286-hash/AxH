"""Decode / encode Unity 2019 Mesh vertex data from a typetree dict (numpy)."""
import numpy as np
FMT = {0:(np.float32,4),1:(np.float16,2),2:(np.uint8,1),3:(np.int8,1),4:(np.uint16,2),5:(np.int16,2),6:(np.uint8,1),7:(np.int8,1),8:(np.uint16,2),9:(np.int16,2),10:(np.uint32,4),11:(np.int32,4)}
CH = {0:'pos',1:'normal',2:'tangent',3:'color',4:'uv0',5:'uv1',6:'uv2',7:'uv3',8:'uv4',9:'uv5',10:'uv6',11:'uv7',12:'weights',13:'indices'}
def streams(vd):
    chans = vd['m_Channels']; n = vd['m_VertexCount']
    nstreams = 1 + max(c['stream'] for c in chans)
    out = []; off = 0
    for s in range(nstreams):
        stride = sum((c['dimension'] & 0xF)*FMT[c['format']][1] for c in chans if c['stream']==s and c['dimension'] & 0xF)
        out.append((off, stride))
        off += n*stride
        off = (off + 15) & ~15
    return out, off
def decode(tt):
    vd = tt['m_VertexData']; n = vd['m_VertexCount']
    raw = bytes(vd['m_DataSize'])
    st, total = streams(vd)
    res = {}
    for i, c in enumerate(vd['m_Channels']):
        dim = c['dimension'] & 0xF          # high bits are flags in 2019+ (e.g. 52 = half4 position)
        if dim == 0: continue
        dt, sz = FMT[c['format']]
        off, stride = st[c['stream']]
        buf = np.frombuffer(raw, dtype=np.uint8, count=n*stride, offset=off).reshape(n, stride)
        col = buf[:, c['offset']:c['offset']+dim*sz].copy().view(dt).reshape(n, dim)
        res[CH[i]] = col
    idx_raw = bytes(tt['m_IndexBuffer'])
    ifmt = np.uint16 if tt.get('m_IndexFormat', 0) == 0 else np.uint32
    res['index'] = np.frombuffer(idx_raw, dtype=ifmt).copy()
    return res
def encode(tt, arrays, n):
    """Write arrays (dict CH-name->np array with n rows) back using the existing channel layout."""
    vd = tt['m_VertexData']
    vd['m_VertexCount'] = n
    st, total = streams(vd)
    raw = bytearray(total)
    mv = np.frombuffer(raw, dtype=np.uint8)
    for i, c in enumerate(vd['m_Channels']):
        dim = c['dimension'] & 0xF
        if dim == 0: continue
        dt, sz = FMT[c['format']]
        off, stride = st[c['stream']]
        a = np.ascontiguousarray(arrays[CH[i]].astype(dt).reshape(n, dim))
        view = mv[off:off+n*stride].reshape(n, stride)
        view[:, c['offset']:c['offset']+dim*sz] = a.view(np.uint8).reshape(n, dim*sz)
    vd['m_DataSize'] = bytes(raw)
