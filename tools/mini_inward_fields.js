// Height and surviving artwork in a signed Mini route stopped at a specified row.
function inwardPortraitFields({size, groove, shape, pitch, previousPhase, previous, previousSpans, drawing, spans}) {
  const sand = new MiniLocalGrooves(size, groove, shape);
  function raked(phase) {
    const turns = 1 / pitch;
    const steps = Math.round(turns * 360);
    const path = Array.from({length: steps + 1}, (_, i) =>
      [phase + 2 * Math.PI * turns * i / steps, 1 - i / steps]);
    const bed = sand.empty();
    sand.carve(bed, path);
    return bed;
  }

  // A cut mixes the old height and the new groove. The difference between two
  // identical cuts into surfaces one unit apart gives the surviving old fraction.
  const low = sand.empty(), high = sand.empty();
  function coverage(path) {
    low.fill(0);
    high.fill(1);
    sand.carve(low, path);
    sand.carve(high, path);
    for (let i = 0; i < low.length; i++)
      low[i] = Math.max(0, Math.min(1, 1 - high[i] + low[i]));
    return low;
  }

  function survivingArt(route, segments, touched) {
    const art = sand.empty();
    for (const [first, last, engraving] of segments) {
      const weight = coverage(route.slice(first, last + 1));
      for (let i = 0; i < art.length; i++) art[i] += weight[i] * (engraving - art[i]);
    }
    // Adjacent spans share an endpoint. Keep fractional shoulder coverage
    // within what the single, uninterrupted ball movement actually touched.
    for (let i = 0; i < art.length; i++) art[i] = Math.min(art[i], touched[i]);
    return art;
  }

  const oldBed = raked(previousPhase), oldPortrait = previousSpans ? sand.empty() : oldBed.slice();
  sand.carve(oldPortrait, previous);
  const oldTouch = coverage(previous).slice();
  const oldCoverage = previousSpans ? survivingArt(previous, previousSpans, oldTouch) : oldTouch;
  const newBed = raked(drawing[0][0]), partial = oldPortrait.slice();
  sand.carve(partial, drawing);
  const touched = coverage(drawing).slice(), art = survivingArt(drawing, spans, touched);

  function encode(array) {
    const bytes = new Uint8Array(array.buffer), chunks = [];
    for (let i = 0; i < bytes.length; i += 16384)
      chunks.push(String.fromCharCode(...bytes.subarray(i, i + 16384)));
    return btoa(chunks.join(''));
  }
  return [oldBed, oldPortrait, oldCoverage, newBed, partial, touched, art].map(encode);
}
