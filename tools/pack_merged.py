"""One zip with the skin and its effects: the effect folders (Art/android/k, zzp1_k, zzp2_k) go inside the skin's
top folder next to Art/android/h, so the whole skin installs from a single folder.

usage: python pack_merged.py <skin.zip> <skin built root> <effects.zip> <effects built root> <out.zip>

Entry order: the skin zip's entries, with the effect entries inserted right after the skin's Art/ section.
Every entry keeps the compression and timestamp of the original zip it comes from.
"""
import sys, os, zipfile

skin_zip, skin_root, fx_zip, fx_root, out = sys.argv[1:6]
zs, zf = zipfile.ZipFile(skin_zip), zipfile.ZipFile(fx_zip)
top = zs.infolist()[0].filename.split('/')[0] + '/'
assert all(i.filename.startswith(top) for i in zs.infolist()), 'skin zip must have a single top folder'

skin = [(i, os.path.join(skin_root, i.filename), i.filename) for i in zs.infolist()]
have = {i.filename for i in zs.infolist()}
fx = [(i, os.path.join(fx_root, i.filename), top + i.filename) for i in zf.infolist() if top + i.filename not in have]
art = top + 'Art/'
last_art = max(k for k, (i, p, n) in enumerate(skin) if n.startswith(art))
entries = skin[:last_art + 1] + fx + skin[last_art + 1:]
names = [n for _, _, n in entries]
assert len(names) == len(set(names)), 'duplicate entries'

with zipfile.ZipFile(out, 'w') as zn:
    for info, path, name in entries:
        ni = zipfile.ZipInfo(name, date_time=info.date_time)
        ni.compress_type = info.compress_type
        ni.external_attr = info.external_attr
        ni.create_system = info.create_system
        if info.is_dir():
            zn.writestr(ni, b'')
            continue
        with open(path, 'rb') as fh:
            data = fh.read()
        zn.writestr(ni, data, compress_type=info.compress_type,
                    compresslevel=9 if info.compress_type == zipfile.ZIP_DEFLATED else None)
print(out, os.path.getsize(out), len(entries), 'entries')
