"""Structural validation of Mecanim clips + controller in a bundle."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import numpy as np, UnityPy
from clipio import binding_layout
def check(path, verbose=True):
    env = UnityPy.load(path)
    errs = []
    for o in env.objects:
        if o.type.name == 'AnimationClip':
            tt = o.read_typetree()
            if tt['m_Legacy']:
                continue
            mc = tt['m_MuscleClip']; d = mc['m_Clip']['data']
            sc, dc, cc = d['m_StreamedClip'], d['m_DenseClip'], d['m_ConstantClip']
            lay, ntot = binding_layout(tt)
            n_s, n_d, n_c = sc['curveCount'], dc['m_CurveCount'], len(cc['data'])
            nm = tt['m_Name']
            if len(dc['m_SampleArray']) != dc['m_FrameCount'] * n_d and n_d:
                errs.append(f'{nm}: dense size mismatch')
            if ntot != n_s + n_d + n_c:
                errs.append(f'{nm}: bindings curves {ntot} != {n_s}+{n_d}+{n_c}')
            if len(mc['m_ValueArrayDelta']) != ntot:
                errs.append(f'{nm}: VAD {len(mc["m_ValueArrayDelta"])} != {ntot}')
            if n_d:
                sw = len(sc['data'])
                exp = (1728 if sw else 1984) + 4 * (sw + len(dc['m_SampleArray']) + n_c + len(mc['m_IndexArray'])) + 8 * len(mc['m_ValueArrayDelta'])
                if exp != tt['m_MuscleClipSize']:
                    errs.append(f'{nm}: muscle size {tt["m_MuscleClipSize"]} != {exp}')
            if n_d:
                D = np.array(dc['m_SampleArray'], np.float64).reshape(dc['m_FrameCount'], n_d)
                if not np.isfinite(D).all():
                    errs.append(f'{nm}: non-finite dense values')
                if abs((dc['m_FrameCount'] - 1) / dc['m_SampleRate'] - (mc['m_StopTime'] - mc['m_StartTime'])) > 1e-3:
                    errs.append(f'{nm}: frame count vs duration mismatch')
                for (ph, attr, nc, c0, tid) in lay:
                    if tid == 4 and attr == 2 and c0 + 4 <= n_s + n_d and c0 >= n_s:
                        q = D[:, c0 - n_s:c0 - n_s + 4]
                        nrm = np.linalg.norm(q, axis=1)
                        if np.abs(nrm - 1).max() > 1e-3:
                            errs.append(f'{nm}: quaternion norm off {np.abs(nrm-1).max()}')
                        if (np.sum(q[1:] * q[:-1], 1) < 0).any():
                            errs.append(f'{nm}: quaternion hemisphere flip in dense data')
            if verbose:
                print(f'  {nm:12s} loop={mc["m_LoopTime"]} dur={mc["m_StopTime"]-mc["m_StartTime"]:.3f} dense={n_d}x{dc["m_FrameCount"]}@{dc["m_SampleRate"]} const={n_c} size={tt["m_MuscleClipSize"]}')
        elif o.type.name == 'AnimatorController':
            tt = o.read_typetree()
            sm = tt['m_Controller']['m_StateMachineArray'][0]
            sm = sm['data'] if 'data' in sm else sm
            for st in sm['m_StateConstantArray']:
                st = st['data'] if 'data' in st else st
                for tr in st['m_TransitionConstantArray']:
                    tr = tr['data'] if 'data' in tr else tr
                    if not (0 <= tr['m_TransitionDuration'] <= 1.0):
                        errs.append('bad transition duration')
    return errs
if __name__ == '__main__':
    for p in sys.argv[1:]:
        e = check(p)
        print(os.path.basename(p), 'OK' if not e else e)
