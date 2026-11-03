import json, sys
d = json.load(open(sys.argv[1]))
for key in sys.argv[2:]:
    for b, B in d.items():
        if key not in b or 'ps' not in B: continue
        print('=' * 20, b, 'mgr', B['mgr'] and {k: B['mgr'][k] for k in ('DelayTime',)}, (B['mgr'] or {}).get('FilterInfo'))
        mats, texs = B['materials'], B['textures']
        psby = {p['gid']: p for p in B['ps']}
        for r in B['renderers']:
            p = psby.get(r['gid'])
            line = f"  [{r['type'][:4]} rm={r['rmode']}] {r['go']}"
            if p:
                line += f" len={p['len']} loop={p['loop']} life={p['life']} size={p['size']} spd={p['speed']} rate={p['rate']} bursts={p['bursts']} maxp={p['maxp']} shape={p['shape']} mods={p['mods']}"
                line += f"\n      start={p['start']} col={p['colmod']}"
            print(line)
            for mid in r['mats']:
                m = mats.get(str(mid))
                if not m: print('      mat ext', mid); continue
                f = m['floats']; c = m['colors']
                tx = {k: (texs[str(v[0])]['name'] + f"({texs[str(v[0])]['w']},{texs[str(v[0])]['fmt']},s{texs[str(v[0])].get('sat_mean')},h{(texs[str(v[0])].get('hues') or [[None]])[0][0]})" if str(v[0]) in texs else v[0]) for k, v in m['tex'].items()}
                cc = {k: v for k, v in c.items() if k in ('_DiffuseColor', '_BackColor', '_DissolveColor', '_LeftColor', '_RightColor', '_TintColor', '_Color', '_MaskColor', '_MainColor') and v != [1.0, 1.0, 1.0, 1.0]}
                print(f"      mat {m['name']} sh={m['shader'][1]} kw={m['kw']} blend={f.get('_SrcBlend')},{f.get('_DstBlend')} hue={f.get('_Hue')},{f.get('_Saturation')},{f.get('_Contrast')} int={f.get('_Intensity')} dscale={f.get('_DiffuseScale')}")
                print(f"         tex={tx}")
                if cc: print(f"         colors={cc}")
        if B['clips']: print('  clips', [(c['name'], c['float'][:6]) for c in B['clips']])
