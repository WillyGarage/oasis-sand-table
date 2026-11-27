// Run with node --test tools/test_guest_temple_hair.cjs.
const assert = require('node:assert/strict');
const {readFileSync} = require('node:fs');
const test = require('node:test');
const vm = require('node:vm');

// Exercise the portrait converter's geometry without publishing a test method
// on the guest's phone or requiring the family's private source photograph.
const source = readFileSync(require.resolve('../web/guest-photo.js'), 'utf8');
const context = {window: {}, document: {currentScript: null}};
const publicMethods = '  window.GuestPhoto={';
vm.runInNewContext(source.replace(publicMethods, '  window.trimHair=visibleTempleHair;\n' + publicMethods), context);
const trim = context.window.trimHair;
const rim = [[7, -2], [10, -2], [10, 2], [7, 2]];
const hair = [[-12, 3], [-7, 7], [0, 8], [5, 7], [9, 1], [15, 2]];
const plain = value => JSON.parse(JSON.stringify(value));
const mirror = points => points.map(([x, y]) => [-x, y]).reverse();

test('the crown and clear side survive, including when the photograph is mirrored', () => {
  const cropped = plain(trim(hair, [rim], 1));
  assert.deepEqual(cropped.slice(0, -1), hair.slice(0, 4));
  const [x, y] = cropped.at(-1);
  assert.ok(x >= 7 && x <= 10 && y - 2 >= 1.15 && y - 2 <= 1.3);
  assert.deepEqual(plain(trim(mirror(hair), [mirror(rim)], 1)), plain(mirror(cropped)));
});

test('a long segment cannot cross a lens between two safe endpoints', () => {
  const through = [[-12, 9], [-8, 6], [0, 0], [18, 0], [21, -4]];
  const cropped = plain(trim(through, [rim], 1));
  assert.deepEqual(cropped.slice(0, -1), through.slice(0, 3));
  const [x, y] = cropped.at(-1);
  assert.equal(y, 0);
  assert.ok(7 - x >= 1.15 - 1e-10 && 7 - x <= 1.3 + 1e-10);
});

test('no glasses, a distant frame, and a missing groove measurement retain every hair landmark', () => {
  const far = rim.map(([x, y]) => [x, y + 30]);
  for (const [frames, scale] of [[[], 1], [[far], 1], [[rim], 0]]) {
    assert.deepEqual(plain(trim(hair, frames, scale)), hair);
  }
});
