"""Ultra skin on every graphics setting.

hero_argus_skin (the model the game shows below High) gets the look of hero_argus_skin_high_add (High / Ultra):
the 2048 texture, the high shader (Custom/MLBB_Final_Fixed) and its material values. Both bundles hold the same
prefab with the same object ids and the same type trees (Unity 2019.4.33f1), so the three objects are copied over
byte for byte; object names and the bundle's own objects stay.

usage: python skin_ultra.py <HIDAN dir, modified in place>
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import UnityPy
from merge_overlays import _sig

COPY = ('Texture2D', 'Shader', 'Material')


def main():
    d = os.path.join(sys.argv[1], 'Art', 'Android', 'h')
    base_p = os.path.join(d, 'hero_argus_skin.unity3d')
    high_p = os.path.join(d, 'hero_argus_skin_high_add.unity3d')
    eb, eh = UnityPy.load(base_p), UnityPy.load(high_p)
    hi = {o.path_id: o for o in eh.objects}
    done = []
    for o in eb.objects:
        if o.type.name not in COPY:
            continue
        q = hi[o.path_id]
        if q.type.name != o.type.name or _sig(o.serialized_type) != _sig(q.serialized_type):
            raise ValueError(f'{o.type.name} {o.path_id}: base and high differ in layout')
        raw = q.get_raw_data()
        if raw != o.get_raw_data():
            o.set_raw_data(raw)
            done.append(o.type.name)
    with open(base_p, 'wb') as fh:
        fh.write(eb.file.save(packer='original'))
    print('base skin now uses the Ultra', ', '.join(done) or 'nothing (already identical)')


if __name__ == '__main__':
    main()
