"""Real-ESRGAN (SRVGGNetCompact, realesr-general-x4v3) -> ONNX, loaded WITHOUT torch and without executing pickle code
(restricted unpickler that only rebuilds float tensors), plus a tiled x2 super-resolution helper.

usage: python sr_model.py <realesr-general-x4v3.pth> <out.onnx>
Model: https://github.com/xinntao/Real-ESRGAN/releases/download/v0.2.5.0/realesr-general-x4v3.pth (BSD-3-Clause)
"""
import sys, io, zipfile, pickle
import numpy as np

DTYPES = {'FloatStorage': np.float32, 'HalfStorage': np.float16, 'DoubleStorage': np.float64, 'LongStorage': np.int64,
          'IntStorage': np.int32}


class _Storage:
    def __init__(self, dtype, key):
        self.dtype, self.key = dtype, key


def load_pth(path):
    zf = zipfile.ZipFile(path)
    names = zf.namelist()
    prefix = names[0].split('/')[0]
    pkl = zf.read(f'{prefix}/data.pkl')

    class Restricted(pickle.Unpickler):
        def find_class(self, module, name):
            if module == 'collections' and name == 'OrderedDict':
                import collections
                return collections.OrderedDict
            if module == 'torch._utils' and name == '_rebuild_tensor_v2':
                return rebuild
            if module == 'torch' and name in DTYPES:
                return name
            raise pickle.UnpicklingError(f'blocked {module}.{name}')

        def persistent_load(self, pid):
            # ('storage', storage_type, key, location, numel)
            _, stype, key, _, _ = pid
            return _Storage(DTYPES[stype], key)

    def rebuild(storage, offset, size, stride, *args):
        raw = zf.read(f'{prefix}/data/{storage.key}')
        arr = np.frombuffer(raw, dtype=storage.dtype)
        n = int(np.prod(size)) if len(size) else 1
        el = arr.itemsize
        out = np.lib.stride_tricks.as_strided(arr[offset:], shape=tuple(size), strides=tuple(s * el for s in stride)) if n else arr[:0]
        return np.array(out, dtype=np.float32)

    obj = Restricted(io.BytesIO(pkl)).load()
    return obj.get('params', obj.get('params_ema', obj))


def build_onnx(params, out_path, scale=4):
    import onnx
    from onnx import helper, TensorProto, numpy_helper
    convs = sorted({int(k.split('.')[1]) for k in params if k.endswith('.weight') and params[k].ndim == 4})
    nodes, inits = [], []
    cur = 'input'
    for i, ci in enumerate(convs):
        w, b = params[f'body.{ci}.weight'], params[f'body.{ci}.bias']
        inits += [numpy_helper.from_array(w.astype(np.float32), f'w{ci}'), numpy_helper.from_array(b.astype(np.float32), f'b{ci}')]
        nodes.append(helper.make_node('Conv', [cur, f'w{ci}', f'b{ci}'], [f'c{ci}'], pads=[1, 1, 1, 1], kernel_shape=[3, 3]))
        cur = f'c{ci}'
        pk = f'body.{ci + 1}.weight'
        if pk in params and params[pk].ndim == 1:
            slope = params[pk].astype(np.float32).reshape(-1, 1, 1)
            inits.append(numpy_helper.from_array(slope, f'p{ci}'))
            nodes.append(helper.make_node('PRelu', [cur, f'p{ci}'], [f'a{ci}']))
            cur = f'a{ci}'
    nodes.append(helper.make_node('DepthToSpace', [cur], ['up'], blocksize=scale, mode='CRD'))
    inits.append(numpy_helper.from_array(np.array([1, 1, scale, scale], np.float32), 'scales'))
    nodes.append(helper.make_node('Resize', ['input', '', 'scales'], ['base'], mode='nearest'))
    nodes.append(helper.make_node('Add', ['up', 'base'], ['output']))
    g = helper.make_graph(nodes, 'srvgg', [helper.make_tensor_value_info('input', TensorProto.FLOAT, [1, 3, None, None])],
                          [helper.make_tensor_value_info('output', TensorProto.FLOAT, [1, 3, None, None])], inits)
    m = helper.make_model(g, opset_imports=[helper.make_opsetid('', 13)])
    m.ir_version = 8
    onnx.checker.check_model(m)
    onnx.save(m, out_path)


class SR:
    """x4 network, used for x2 output: run x4 on tiles (with overlap), then Lanczos-downscale by 2."""

    def __init__(self, onnx_path, threads=4):
        import onnxruntime as ort
        so = ort.SessionOptions()
        so.intra_op_num_threads = threads
        self.sess = ort.InferenceSession(onnx_path, so, providers=['CPUExecutionProvider'])

    def x4(self, rgb, tile=192, pad=12):
        """rgb float32 HxWx3 0..1 -> 4H x 4W x 3"""
        H, W, _ = rgb.shape
        out = np.zeros((H * 4, W * 4, 3), np.float32)
        for y in range(0, H, tile):
            for x in range(0, W, tile):
                y0, x0 = max(y - pad, 0), max(x - pad, 0)
                y1, x1 = min(y + tile + pad, H), min(x + tile + pad, W)
                inp = rgb[y0:y1, x0:x1].transpose(2, 0, 1)[None].astype(np.float32)
                res = self.sess.run(None, {'input': inp})[0][0].transpose(1, 2, 0)
                ty0, tx0 = (y - y0) * 4, (x - x0) * 4
                th, tw = (min(y + tile, H) - y) * 4, (min(x + tile, W) - x) * 4
                out[y * 4:y * 4 + th, x * 4:x * 4 + tw] = res[ty0:ty0 + th, tx0:tx0 + tw]
        return np.clip(out, 0, 1)

    def x2(self, rgb, wrap=False):
        import cv2
        H, W, _ = rgb.shape
        if wrap:                                   # tileable textures: pad with wrapped content
            p = 16
            big = np.pad(rgb, ((p, p), (p, p), (0, 0)), mode='wrap')
            r = self.x4(big)[p * 4:(p + H) * 4, p * 4:(p + W) * 4]
        else:
            p = 16
            big = np.pad(rgb, ((p, p), (p, p), (0, 0)), mode='reflect')
            r = self.x4(big)[p * 4:(p + H) * 4, p * 4:(p + W) * 4]
        return np.clip(cv2.resize(r, (W * 2, H * 2), interpolation=cv2.INTER_AREA), 0, 1)


if __name__ == '__main__':
    # python sr_model.py <realesr-general-x4v3.pth> <out.onnx>
    # python sr_model.py <realesr-general-x4v3.pth> <realesr-general-wdn-x4v3.pth> <denoise 0..1> <out.onnx>
    #   (deep network interpolation: denoise 0.2 = 20 % general + 80 % wdn -> keeps grass / stone grain)
    if len(sys.argv) == 5:
        a, b, s = load_pth(sys.argv[1]), load_pth(sys.argv[2]), float(sys.argv[3])
        params = {k: s * a[k] + (1 - s) * b[k] for k in a}
        out = sys.argv[4]
    else:
        params, out = load_pth(sys.argv[1]), sys.argv[2]
    build_onnx(params, out)
    print('saved', out, len(params), 'tensors')
