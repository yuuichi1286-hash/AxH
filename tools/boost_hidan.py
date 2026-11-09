"""Hidan v5: bigger, brutal blood-ritual effects (crimson palette) on top of v4.

Every particle system of a combat effect gets the cinematic treatment of brutal.py with a crimson profile:
bigger, heavier hits; sparks and debris fly further; more sparks / debris / flames (never more than 60 alive per
system, so the cost stays bounded); a white-hot birth that settles into Hidan's crimson; a long S-curve decay that
cools into deep blood red; shock rings and blooms grow while they fade; blood splashes, drips and fragments fall
with gravity. Fade-in / fade-out stay (alpha 0 at birth and death). The ritual sigils / glyphs and countdowns keep
their shape, the lobby showcase and the ultimate cut-in stay as they are. Effect lifetimes (DelayTime) are
extended afterwards so no particle is cut before it has faded.

Roles: the pinyin names of brutal.role(), plus the English names of the Hidan layers (ember, splash, drip,
blood_rain, frag, impact / cast bloom, glints, streak, echo / ghost, mist, aura, sigil, glyph, mark).

usage: python boost_hidan.py <HIDAN dir, modified in place> <report.json>
"""
import sys, os, json, collections, re
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import UnityPy
import brutal
from build import fix_delay_times

# end-of-life colour multipliers: everything cools into deep blood red instead of brutal's dark green
END = {
    'slash': (0.78, 0.22, 0.22), 'slash_dark': (0.55, 0.14, 0.14), 'flash': (0.82, 0.26, 0.24),
    'spark': (0.86, 0.32, 0.26), 'dark': (0.50, 0.12, 0.12), 'smoke': (0.45, 0.12, 0.12),
    'flame': (0.76, 0.26, 0.20), 'crack': (0.60, 0.16, 0.14), 'ring': (0.72, 0.22, 0.22),
    'mesh': (0.70, 0.22, 0.22),
}
PROFILE = {r: v[:8] + ((END[r] if v[8] is not None else None),) + v[9:] for r, v in brutal.PROFILE.items()}
HIDAN_KEEP = ('sigil', 'glyph', 'mark', 'daojishi', 'yachi')
HIDAN_ROLES = (
    (('ember', 'glint', 'glints'), 'spark'),
    (('splash', 'drip', 'rain', 'frag', 'droplet'), 'debris'),
    (('impact', 'bloom', 'cast', 'burst'), 'flash'),
    (('streak', 'echo', 'ghost', 'v7ghost'), 'slash'),
    (('mist',), 'smoke'),
    (('aura', 'xuanzhuan'), 'flow'),
    (('anwenli', 'noise'), 'dark'),
    (('kuosan',), 'ring'),
)


def role(name, render_mode):
    tk = [re.sub(r'\d+$', '', t) for t in brutal.tokens(name)]
    if any(t.startswith(k) for t in tk for k in HIDAN_KEEP):
        return 'keep'
    for words, r in HIDAN_ROLES:
        if any(t in words or any(t.startswith(w) for w in words) for t in tk):
            return r
    return brutal.role(name, render_mode)


def process(path, fname, totals):
    env = UnityPy.load(path)
    cls = brutal.bundle_class(fname)
    gos, rmode = {}, {}
    for o in env.objects:
        if o.type.name == 'GameObject':
            gos[o.path_id] = o.read_typetree()['m_Name']
        elif o.type.name == 'ParticleSystemRenderer':
            t = o.read_typetree()
            rmode[t['m_GameObject']['m_PathID']] = t['m_RenderMode']
    changed = 0
    for o in env.objects:
        if o.type.name != 'ParticleSystem':
            continue
        tt = o.read_typetree()
        gid = tt['m_GameObject']['m_PathID']
        r, done = brutal.apply(tt, gos.get(gid, ''), rmode.get(gid), cls, profile=PROFILE, role_fn=role)
        totals[f'role_{r}'] += 1
        for k in done:
            totals[f'boost_{k}'] += 1
        if done:
            o.save_typetree(tt)
            changed += 1
    if changed:
        with open(path, 'wb') as fh:
            fh.write(env.file.save(packer='original'))
    return changed


def main():
    root, report_path = sys.argv[1], sys.argv[2]
    totals = collections.Counter()
    per_file = {}
    for dp, dn, fn in sorted(os.walk(os.path.join(root, 'Art'))):
        dn.sort()
        for f in sorted(fn):
            if not f.endswith('.unity3d') or f.startswith(('hero_', 'heroshow', 'Hero45')) or 'Atlas' in f:
                continue
            n = process(os.path.join(dp, f), f, totals)
            if n:
                per_file[f] = n
    delays = fix_delay_times(root)
    report = {'particle_systems_boosted': sum(per_file.values()), 'files': per_file, 'totals': dict(totals),
              'delaytime_extended': delays}
    with open(report_path, 'w') as fh:
        json.dump(report, fh, indent=1, default=str)
    print(f'boosted {sum(per_file.values())} particle systems in {len(per_file)} effects, '
          f'DelayTime extended in {len(delays)}; roles '
          + ', '.join(f'{k[5:]} {v}' for k, v in sorted(totals.items()) if k.startswith('role_')))


if __name__ == '__main__':
    main()
