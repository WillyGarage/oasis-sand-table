"""Rebuild icons.json from the lucide-static npm package (icons/*.svg run through svgstrokes) (ISC licence, see LICENSE next to this file).

    npm pack lucide-static && mkdir x && tar xzf lucide-static-*.tgz -C x
    python3 server/lucide/build.py x/package

Writes icons.json: {"version": "...", "icons": {name: {"t": [tags], "s": [[x, y, x, y, ...], ...]}}} with every
shape flattened to polylines on Lucide's 24 x 24 grid (2 decimals).
"""
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from server import svgstrokes  # noqa: E402


def main(pkg):
    pkg = Path(pkg)
    tags = json.loads((pkg / 'tags.json').read_text())
    version = json.loads((pkg / 'package.json').read_text())['version']
    icons, skipped = {}, []
    for f in sorted((pkg / 'icons').glob('*.svg')):
        name = f.stem
        try:
            text = re.sub(r'<!--.*?-->', '', f.read_text(), flags=re.S)
            strokes = svgstrokes.svg_to_strokes(text)
        except svgstrokes.SvgError as e:
            skipped.append((name, str(e)))
            continue
        icons[name] = {'t': tags.get(name, [])[:8],
                       's': [[round(c, 2) for p in s for c in p] for s in strokes]}
    out = Path(__file__).with_name('icons.json')
    out.write_text(json.dumps({'version': version, 'icons': icons}, separators=(',', ':')))
    print('%d icons, %d skipped %s, %d bytes' % (len(icons), len(skipped), skipped[:5], out.stat().st_size))


if __name__ == '__main__':
    main(sys.argv[1])
