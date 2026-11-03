"""Before/after preview of the Suyou skill icons: python icon_preview.py <orig atlas bundle> <new atlas bundle> <out.png>"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import numpy as np
import UnityPy
from PIL import Image, ImageDraw
from icons import SPRITES, MAIN, MASK

def load(p):
    env = UnityPy.load(p)
    tex, spr = {}, {}
    for o in env.objects:
        if o.type.name == 'Texture2D':
            d = o.read(); tex[d.m_Name] = d.image.convert('RGB')
        elif o.type.name == 'MonoBehaviour':
            try: tt = o.read_typetree()
            except Exception: continue
            for s in tt.get('mSprites', []):
                if s['name'] in SPRITES: spr[s['name']] = (s['x'], s['y'], s['width'], s['height'])
    return tex, spr

a_tex, spr = load(sys.argv[1]); b_tex, _ = load(sys.argv[2])
S = 200
labels = {'S12610': 'Pasif', 'S12620': 'Skill 1', 'S12630': 'Skill 2', 'S12640': 'Ultimate'}
sheet = Image.new('RGB', (len(SPRITES) * (S + 20) + 20, 2 * (S + 30) + 30), (16, 18, 20))
dr = ImageDraw.Draw(sheet)
for i, n in enumerate(SPRITES):
    x, y, w, h = spr[n]
    m = a_tex[MASK].crop((x, y, x + w, y + h)).convert('L').resize((S, S), Image.LANCZOS)
    for row, tex in enumerate((a_tex, b_tex)):
        ic = tex[MAIN].crop((x, y, x + w, y + h)).resize((S, S), Image.LANCZOS)
        bg = Image.new('RGB', (S, S), (16, 18, 20))
        bg.paste(ic, (0, 0), m)
        px, py = 20 + i * (S + 20), 30 + row * (S + 30)
        sheet.paste(bg, (px, py))
        dr.text((px, py - 14), f"{labels[n]} {'sebelum' if row == 0 else 'sesudah'}", fill=(230, 230, 230))
sheet.save(sys.argv[3])
# untouched check: every pixel outside the four sprite rects identical
A = np.asarray(a_tex[MAIN]).astype(int); B = np.asarray(b_tex[MAIN]).astype(int)
diff = np.abs(A - B).max(-1) > 0
for n in SPRITES:
    x, y, w, h = spr[n]; diff[max(0, y - 3):y + h + 3, max(0, x - 3):x + w + 3] = False   # sprite + its gap pixels
print('changed pixels outside the Suyou sprites (and their gap pixels):', int(diff.sum()))
