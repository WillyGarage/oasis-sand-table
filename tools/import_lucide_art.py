#!/usr/bin/env python3
"""Rebuild the reviewed guest paths from a local lucide-react 0.562.0 pnpm index.

    python3 tools/import_lucide_art.py /path/to/0.562.0-index.json

The outlines file names the selected icons and their display labels. For a new
study, use --outlines with a separate JSON file in the same format. Every
source is checked against the package index and sampled in a local browser.
"""
import argparse
import base64
import hashlib
import json
from pathlib import Path
import re

import numpy as np
from playwright.sync_api import sync_playwright

import compose
from wide_portrait import chromium


ROOT = Path(__file__).resolve().parents[1]
OUTLINES = ROOT / 'patterns/guest-rings/lucide-outlines.json'

# Sample the source curves in their native 24-unit coordinate system. Keep
# their aspect ratio and return along the same connections as a guest sketch.
WALK = """nodes => {
  const ns='http://www.w3.org/2000/svg', svg=document.createElementNS(ns,'svg');
  document.body.append(svg);
  try {
    const strokes=nodes.map(([tag,attrs])=>{
      const shape=document.createElementNS(ns,tag);
      for (const [key,value] of Object.entries(attrs)) if (key!=='key') shape.setAttribute(key,value);
      svg.append(shape);
      const length=shape.getTotalLength(), steps=Math.max(1,Math.ceil(length/.15));
      return Array.from({length:steps+1},(_,i)=>{
        const p=shape.getPointAtLength(length*i/steps); return [p.x,-p.y];
      });
    });
    const all=strokes.flat(), xs=all.map(p=>p[0]), ys=all.map(p=>p[1]);
    const cx=(Math.min(...xs)+Math.max(...xs))/2, cy=(Math.min(...ys)+Math.max(...ys))/2;
    const scale=.955/Math.max(...all.map(([x,y])=>Math.hypot(x-cx,y-cy)));
    const lines=strokes.map(s=>s.map(([x,y])=>[(x-cx)*scale,(y-cy)*scale]));
    const entry=lines.flat().reduce((far,p)=>p[1]>far[1]?p:far);
    return GuestArt.manageStrokes(lines,entry,{joinEdges:true,pointLimit:8000});
  } finally {svg.remove()}
}"""


def read_nodes(index, files, icon):
    entry = files[f'dist/esm/icons/{icon}.js']
    algorithm, encoded = entry['integrity'].split('-', 1)
    digest = base64.b64decode(encoded, validate=True).hex()
    source = (index.parents[2] / 'files' / digest[:2] / digest[2:]).read_bytes()
    if hashlib.new(algorithm, source).hexdigest() != digest:
        raise ValueError(f'Local package integrity check failed for {icon}')
    match = re.search(r'const __iconNode = (\[.*?\]);', source.decode(), re.S)
    if not match:
        raise ValueError(f'Expected Lucide drawing nodes in {icon}.js')
    return json.loads(re.sub(r'\b([a-zA-Z]+):', r'"\1":', match[1]))


def rebuild(index, outlines):
    package = json.loads(index.read_text())
    if (package['name'], package['version']) != ('lucide-react', '0.562.0'):
        raise ValueError('Expected the Lucide version credited in guest_line_art-LICENSE.txt')
    subjects = json.loads(outlines.read_text())
    rows = []
    with sync_playwright() as pw, pw.chromium.launch(executable_path=chromium(pw, None)) as browser, browser.new_page() as page:
        page.add_script_tag(path=ROOT / 'web/guest-art.js')
        for key, art in subjects.items():
            nodes = read_nodes(index, package['files'], art['icon'])
            walk = np.array(page.evaluate(WALK, nodes))
            points = np.rint(compose.simplify(walk, .0012) * 10000).astype(int)
            if not np.array_equal(points[0], points[-1]):
                points = np.vstack([points, points[0]])
            encoded = json.dumps(points.tolist(), separators=(',', ':'))
            rows.append(f'  {json.dumps(key)}: {{\n    "label": {json.dumps(art["label"])},\n'
                        f'    "icon": {json.dumps(art["icon"])},\n    "points": {encoded}\n  }}')
    outlines.write_text('{\n' + ',\n'.join(rows) + '\n}\n')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('index', type=Path)
    parser.add_argument('--outlines', type=Path, default=OUTLINES)
    args = parser.parse_args()
    rebuild(args.index.resolve(), args.outlines)
