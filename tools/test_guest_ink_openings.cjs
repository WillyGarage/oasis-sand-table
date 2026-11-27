const assert = require('node:assert/strict');
const test = require('node:test');
const {pair} = require('../web/ring-planner.js');

const catalog = {pairGroove: .12, pairMotifs: {}};
const companion = {points: [[-.6,-.3], [.6,-.3], [.6,.3], [-.6,.3], [-.6,-.3]]};

// A closed frame with a small square opening. Both ends of the diagonal
// connecting the inner and outer contours are traversed twice by the ball.
function source(halfWidth) {
  const s = halfWidth;
  return {points: [[-.5,-.5], [.5,-.5], [.5,.5], [-.5,.5], [-.5,-.5],
    [-s,-s], [s,-s], [s,s], [-s,s], [-s,-s], [-.5,-.5]]};
}

function clearRadius(path, x, y) {
  const distances = path.slice(1).map(([bx,by], i) => {
    const [ax,ay] = path[i], dx = bx-ax, dy = by-ay;
    const length = dx*dx + dy*dy;
    const t = length ? Math.max(0, Math.min(1, ((x-ax)*dx+(y-ay)*dy)/length)) : 0;
    return Math.hypot(x-ax-t*dx, y-ay-t*dy);
  });
  return Math.min(...distances) - catalog.pairGroove/2;
}

test('fitted ball leaves clear sand inside a fine opening without moving the neighboring drawing', () => {
  const input = source(.06);
  for (const relation of ['beside', 'right', 'above', 'below']) {
    const before = pair(catalog, input, companion, relation);
    const after = pair(catalog, {...input,generated:true}, companion, relation);
    // Each outline walk starts and ends on its port. The final point closes
    // the bridge. The upper drawing can straddle the center of the guest place.
    const first = relation === 'beside' || relation === 'above';
    const companionLength = companion.points.length + 1;
    const subject = first ? before.slice(0, input.points.length + 1) : before.slice(companionLength, -1);
    const neighbor = path => first ? path.slice(-companionLength-1,-1) : path.slice(0,companionLength);
    const center = [0,1].map(axis => {
      const values = subject.map(p => p[axis]);
      return (Math.min(...values)+Math.max(...values))/2;
    });
    assert.ok(clearRadius(before, ...center) <= 0);
    assert.ok(clearRadius(after, ...center) > .15*catalog.pairGroove);
    assert.deepEqual(neighbor(after), neighbor(before));
    assert.deepEqual(after[0], after.at(-1));
    assert.ok(after.every(p => Math.hypot(...p) <= .975+1e-12));
  }
});

test('keep useful open spaces, other placements, and original art at the point limit', () => {
  const large = source(.24), small = source(.07);
  const crowded = {points: [...Array(7975).fill(small.points[0]), ...small.points]};
  for (const [input,relation] of [[large,'beside'], [large,'above'], [small,'lean'],
                                  [small,'behind'], [crowded,'beside'], [crowded,'above']]) {
    const before = pair(catalog, input, companion, relation);
    const after = pair(catalog, {...input,generated:true}, companion, relation);
    assert.deepEqual(after, before);
  }
});

test('tall side-by-side drawings leave the tines of a tuning fork free', () => {
  // Both paths close by retracing existing grooves. A connector near the
  // upper right tine makes the fork look attached to the instrument.
  const fork = {points: [
    [0,-.4],[-.15,-.32],[-.15,.8],[-.15,-.32],[0,-.4],[.15,-.32],[.15,.8],[.15,-.32],
    [0,-.4],[0,-.72],[-.2,-.72],[-.2,-.86],[.2,-.86],[.2,-.72],[0,-.72],[0,-.4]
  ]};
  const guitar = {points: [
    [-.03,-.30],[-.15,-.24],[-.33,-.27],[-.47,-.48],[-.42,-.66],[-.17,-.77],[.1,-.71],
    [.22,-.52],[.16,-.39],[.30,-.32],[.37,-.17],[.31,-.03],[.21,0],[.47,.52],[.56,.58],
    [.50,.76],[.40,.8],[.31,.62],[.31,.52],[.08,.04],[-.04,.08],[-.17,-.02],[-.16,-.17],[-.03,-.30]
  ]};
  const path = pair(catalog, fork, guitar, 'beside');
  const forkY = path.slice(0, fork.points.length + 1).map(p => p[1]);
  const base = Math.min(...forkY), height = Math.max(...forkY) - base;
  assert.ok(height > 1.3);
  assert.ok(path[0][1] - base < .2 * height);
  assert.deepEqual(path[0], path.at(-1));
  assert.ok(path.every(p => Math.hypot(...p) <= .975 + 1e-12));
  assert.deepEqual(pair(catalog, guitar, fork, 'right'), path);
});
