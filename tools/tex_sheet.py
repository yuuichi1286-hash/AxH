"""Contact sheet of unique textures in a bundle tree: python tex_sheet.py <root> <out.png> [filter: all|colored|gray] [cols]"""
import sys, os, json
import numpy as np
import UnityPy
from UnityPy.files import BundleFile
from PIL import Image, ImageDraw
root, out = sys.argv[1], sys.argv[2]
mode = sys.argv[3] if len(sys.argv) > 3 else 'all'
cols = int(sys.argv[4]) if len(sys.argv) > 4 else 12
seen = {}
for dp, dn, fn in sorted(os.walk(root)):
    for f in sorted(fn):
        p = os.path.join(dp, f)
        try:
            env = UnityPy.load(p)
            if not isinstance(env.files[list(env.files)[0]], BundleFile):
                continue
        except Exception:
            continue
        for o in env.objects:
            if o.type.name != 'Texture2D':
                continue
            d = o.read()
            if d.m_Name in seen:
                continue
            img = d.image.convert('RGBA')
            a = np.asarray(img).astype(np.float32) / 255
            rgb = a[..., :3]; mx = rgb.max(-1); mn = rgb.min(-1)
            sat = np.where(mx > 1e-3, (mx - mn) / np.maximum(mx, 1e-3), 0)
            vis = (a[..., 3] > 0.1) & (mx > 0.08)
            s = float(sat[vis].mean()) if vis.any() else 0
            if mode == 'colored' and s < 0.25: continue
            if mode == 'gray' and s >= 0.25: continue
            seen[d.m_Name] = (img, f'{d.m_Name[:22]} {d.m_Width}x{d.m_Height} f{d.m_TextureFormat}')
T = 128
items = sorted(seen.items())
rows = (len(items) + cols - 1) // cols
sheet = Image.new('RGB', (cols * T, rows * (T + 12)), (20, 20, 20))
dr = ImageDraw.Draw(sheet)
for i, (n, (img, label)) in enumerate(items):
    x, y = (i % cols) * T, (i // cols) * (T + 12)
    im = img.resize((T - 4, T - 4), Image.LANCZOS)
    # composite: rgb * alpha over black (additive look)
    a = np.asarray(im).astype(np.float32) / 255
    rgb = a[..., :3] * a[..., 3:4]
    sheet.paste(Image.fromarray((rgb * 255).astype(np.uint8)), (x + 2, y + 2))
    dr.text((x + 2, y + T - 1), label[:24], fill=(255, 255, 0))
sheet.save(out)
print(len(items), sheet.size)
