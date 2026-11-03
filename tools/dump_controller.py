import sys, json
import UnityPy
p = sys.argv[1]
env = UnityPy.load(p)
for o in env.objects:
    if o.type.name == 'AnimatorController':
        tt = o.read_typetree()
        tos = tt['m_TOS']
        tosd = {}
        for e in tos:
            if isinstance(e, (list, tuple)): tosd[e[0]] = e[1]
            else: tosd[e['first']] = e['second']
        print('controller', tt['m_Name'], 'clips', len(tt['m_AnimationClips']), 'keys', list(tt.keys()))
        ctrl = tt['m_Controller']
        print(' ctrl keys', list(ctrl.keys()))
        for smi, sm in enumerate(ctrl['m_StateMachineArray']):
            sm = sm['data'] if 'data' in sm else sm
            print(' SM', smi, 'keys', list(sm.keys()))
            for si, st in enumerate(sm['m_StateConstantArray']):
                st = st['data'] if 'data' in st else st
                name = tosd.get(st['m_NameID'], st['m_NameID'])
                trs = []
                for tr in st['m_TransitionConstantArray']:
                    tr = tr['data'] if 'data' in tr else tr
                    trs.append(dict(dst=tr['m_DestinationState'], dur=round(tr['m_TransitionDuration'],3), off=tr['m_TransitionOffset'], exit=round(tr['m_ExitTime'],3), hasExit=tr['m_HasExitTime'], fixed=tr['m_HasFixedDuration'], conds=len(tr['m_ConditionConstantArray'])))
                print(f"  [{si}] {name} speed={st['m_Speed']} loop={st.get('m_Loop')} cycleOff={st['m_CycleOffset']} writeDef={st.get('m_WriteDefaultValues')} trans={trs}")
            for tr in sm['m_AnyStateTransitionConstantArray']:
                tr = tr['data'] if 'data' in tr else tr
                print('  ANY->', tr['m_DestinationState'], 'dur', tr['m_TransitionDuration'], 'canSelf', tr.get('m_CanTransitionToSelf'))
            print('  default state', sm['m_DefaultState'])
        if len(sys.argv) > 2:
            st = ctrl['m_StateMachineArray'][0]
            st = st['data'] if 'data' in st else st
            s0 = st['m_StateConstantArray'][0]; s0 = s0['data'] if 'data' in s0 else s0
            print(json.dumps({k: (v if not isinstance(v, (list, dict)) else str(v)[:300]) for k, v in s0.items()}, indent=1))
