"""For each roof of a set: its parameters and the roof tiles it produced, relative to its rectangle."""
import os, sys
sys.path.insert(0, 'C:/KnoxMap'); sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import bx
from bxshow import load
import xml.etree.ElementTree as ET
from knoxbuild.buildtiles import tile_name
H = os.path.dirname(os.path.abspath(__file__)); ORIGIN = 21000
case = sys.argv[1]; only = [int(a) for a in sys.argv[2:]]
root = ET.parse(f"{H}/bx/{case}/buildings/{case}.tbx").getroot()
names = {}
for e in [c for c in root if c.tag == 'tile_entry']:
    if e.get('category') in ('roof_slopes', 'roof_caps', 'roof_tops'):
        for t in e:
            s = (t.get('enum').replace('Slope', 's').replace('Cap', 'c').replace('Peak', 'k').replace('Rise', 'R')
                 .replace('Fall', 'F').replace('Point', 'p').replace('OnePt5', '1p5').replace('TwoPt5', '2p5').replace('Pt5', 'p5'))
            names.setdefault(tile_name(t.get('tile')), []).append(s)
cx = (ORIGIN + bx.LOT_X) // 256
sq, levels = load(f"{H}/bx/{case}/lots", cx, 0)
for i, (rt, d, w, h, caps) in enumerate(bx.ROOF_SETS[case]):
    if only and i not in only: continue
    x0, y0 = 2 + i * 13, 2
    print(f"-- roof {i}: {rt} {d} {w}x{h} caps={caps or '-'}")
    for z in range(1, levels):
        rows = []
        for y in range(y0 - 1, y0 + h + 2):
            row = []
            for x in range(x0 - 1, x0 + w + 2):
                st = sq.get((ORIGIN + bx.LOT_X + x - cx * 256, bx.LOT_Y + y, z), [])
                toks = [names.get(t, ['?' + t.rsplit('_', 1)[-1]])[0] for t in st if not t.startswith('ceilings')]
                row.append(('/'.join(toks) or '.').ljust(7))
            rows.append(' '.join(row))
        if any(set(r.replace(' ', '').replace('.', '')) for r in rows):
            print(f"   level {z}:"); [print('    ' + r) for r in rows]
