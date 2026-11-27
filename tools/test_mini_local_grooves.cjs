const assert = require('node:assert/strict');
const {readFileSync} = require('node:fs');
const test = require('node:test');
const vm = require('node:vm');

const renderer = readFileSync(require.resolve('../web/ring-sand.js'), 'utf8');
const local = readFileSync(require.resolve('./mini_local_grooves.js'), 'utf8');
const RenderSand = vm.runInNewContext(renderer + '\n' + local + '\nMiniLocalGrooves',
  {document: {createElement: () => ({})}});
const size = 177;
const sim = new RenderSand(size, .1, {ridge:.42, ridge_at:1.5, ridge_w:.42, floor:.72, floor_k:4});

function render(path) {
  const bed = sim.empty();
  bed.fill(.13);
  sim.carve(bed, path);
  return bed;
}

const pi = Math.PI;
const horizontal = [[pi,.84], [pi,0], [0,0], [0,.84]];
const vertical = [[pi/2,.84], [pi/2,0], [-pi/2,0], [-pi/2,.84]];

test('a local edit cannot change a later groove outside the reach of the ball', () => {
  // One excursion at the left rim, then the same two long cuts and rim travel.
  const start = horizontal[0];
  const path = [...horizontal, ...vertical];
  const detour = [start, [pi-.13,.89], [pi-.24,.81], start];
  const old = render(path), changed = render([...detour, ...path.slice(1)]);
  let altered = 0;
  for (let i = 0; i < old.length; i++) {
    if (i % size > .30 * size) assert.equal(changed[i], old[i]);
    else if (changed[i] !== old[i]) altered++;
  }
  assert.ok(altered > 200);
  // Pausing in place before the same run cannot change the resulting grooves.
  assert.deepEqual(render([...Array(27).fill(start), ...path]), old);
});

test('at a crossing the latest pass carves its own floor and leaves the rest intact', () => {
  const a = render(horizontal), b = render(vertical);
  const ab = render([...horizontal, ...vertical]);
  const ba = render([...vertical, [-pi,.84], ...horizontal]);
  const radius = sim.radius;
  let orderMatters = false;
  for (let y = -30; y <= 30; y++) {
    for (let x = -30; x <= 30; x++) {
      const i = (y + radius) * size + x + radius;
      if (Math.abs(x) < 1.6 * sim.half) assert.equal(ab[i], b[i]);
      if (Math.abs(y) < 1.6 * sim.half) assert.equal(ba[i], a[i]);
      if (Math.abs(x) > 2.3 * sim.half) assert.equal(ab[i], a[i]);
      if (Math.abs(y) > 2.3 * sim.half) assert.equal(ba[i], b[i]);
      if (Math.abs(ba[i] - ab[i]) > 1) orderMatters = true;
    }
  }
  assert.ok(orderMatters);
});
