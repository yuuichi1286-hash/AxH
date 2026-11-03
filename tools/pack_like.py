"""Pack a built tree into a zip with exactly the entry list / order / compression / timestamps of the original zip.

usage: python pack_like.py <original.zip> <built root (contains the zip's top-level folders)> <out.zip>
"""
import sys, os, zipfile

orig, root, out = sys.argv[1:4]
zo = zipfile.ZipFile(orig)
with zipfile.ZipFile(out, 'w') as zn:
    for info in zo.infolist():
        ni = zipfile.ZipInfo(info.filename, date_time=info.date_time)
        ni.compress_type = info.compress_type
        ni.external_attr = info.external_attr
        ni.create_system = info.create_system
        if info.is_dir():
            zn.writestr(ni, b'')
            continue
        path = os.path.join(root, info.filename)
        with open(path, 'rb') as fh:
            data = fh.read()
        zn.writestr(ni, data, compress_type=info.compress_type, compresslevel=9 if info.compress_type == zipfile.ZIP_DEFLATED else None)
print(out, os.path.getsize(out))
