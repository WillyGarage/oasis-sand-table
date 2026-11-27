// Run with node --test tools/test_guest_photo_subject.cjs. The fixture is a
// colored disc spanning a landscape horizon, with a removable shadow.
const assert = require('node:assert/strict');
const test = require('node:test');

global.window = {};
global.document = {currentScript: null};
require('../web/guest-photo.js');

function landscape({centers = [96], slope = 0, shaded = false} = {}) {
  const width = 240, height = 160, radius = 31;
  const data = new Uint8ClampedArray(width * height * 4);
  for (let y = 0; y < height; y++) {
    for (let x = 0; x < width; x++) {
      const cx = centers.find(center => Math.hypot(x - center, y - 82) < radius);
      let color = y < 86 + (x - width / 2) * slope ? [162, 195, 228] : [116, 145, 81];
      if (cx !== undefined) {
        color = shaded && x - cx < (y - 82) / 3 ? [120, 35, 30] : [226, 94, 52];
      }
      data.set([...color, 255], (y * width + x) * 4);
    }
  }
  return {width, height, data};
}

function draw(image, options = {}) {
  return window.GuestPhoto.fromPixels(image, {object: true, portraitDiameterGrooves: 18, ...options});
}

// Measure the actual strokes, including long segments with no vertex near
// the middle. A solid disc should have a clear center; its shadow crosses it.
function closestStrokeToCenter(points) {
  let closest = Infinity;
  for (let i = 1; i < points.length; i++) {
    const [x, y] = points[i - 1], dx = points[i][0] - x, dy = points[i][1] - y;
    const lengthSquared = dx * dx + dy * dy;
    const t = lengthSquared ? Math.max(0, Math.min(1, -(x * dx + y * dy) / lengthSquared)) : 0;
    closest = Math.min(closest, Math.hypot(x + t * dx, y + t * dy));
  }
  return closest;
}

test('remove a horizon from a single off-center subject and keep its measured shading', async () => {
  for (const [cx, slope] of [[96, 0], [152, 0.10]]) {
    const flat = await draw(landscape({centers: [cx], slope}));
    assert.equal(flat.hasIsolatedSubject, true);
    assert.ok(flat.points.length > 10 && closestStrokeToCenter(flat.points) > 0.75);
    const photo = landscape({centers: [cx], slope, shaded: true});
    const isolated = await draw(photo);
    assert.equal(isolated.hasIsolatedSubject, true);
    assert.ok(closestStrokeToCenter(isolated.points) < 0.25);
    const background = await draw(photo, {includeBackground: true});
    assert.equal(background.hasIsolatedSubject, true);
    assert.notDeepEqual(background.points, isolated.points);
    assert.deepEqual((await draw(photo)).points, isolated.points);
  }
});

test('honor the guest’s frame and leave competing or clipped subjects alone', async () => {
  for (const centers of [[67, 173], [8], []]) {
    const image = landscape({centers});
    const ordinary = await draw(image);
    assert.ok(!ordinary.hasIsolatedSubject);
    assert.deepEqual((await draw(image, {includeBackground: true})).points, ordinary.points);
  }
  const image = landscape(), objectFrame = {x: 96, y: 82, w: 80};
  const framed = await draw(image, {objectFrame});
  assert.ok(!framed.hasIsolatedSubject && framed.points.length > 0);
  assert.deepEqual((await draw(image, {objectFrame, includeBackground: true})).points, framed.points);
});

test('preserve the doorway and walls of a small ink treehouse', async () => {
  // The door and walls meet longer strokes. Their individual branches are
  // short, yet they each cover more than a groove at this drawing size.
  const trunk = [[10,88],[22,92],[29,38],[36,12],[44,38],[50,92],[63,89]];
  const strokes = [trunk, [[28,46],[13,38]], [[46,41],[62,33]],
    [[44,55],[64,40],[83,55]], [[46,72],[83,72]], [[51,55],[51,72]],
    [[77,55],[77,72]], [[59,72],[59,60],[67,60],[67,72]],
    [[54,92],[54,72]], [[61,92],[61,72]]];
  function distanceToSegment([x,y], a, b) {
    const dx=b[0]-a[0], dy=b[1]-a[1];
    const fraction=((x-a[0])*dx+(y-a[1])*dy)/(dx*dx+dy*dy || 1);
    const t=Math.max(0,Math.min(1,fraction));
    return Math.hypot(x-a[0]-t*dx,y-a[1]-t*dy);
  }
  const width=240, data=new Uint8ClampedArray(width*width*4).fill(255);
  for (const stroke of strokes) for (let i=1;i<stroke.length;i++) {
    const a=stroke[i-1], b=stroke[i];
    for (let y=0;y<width;y++) for (let x=0;x<width;x++) {
      if (distanceToSegment([x/2.4,y/2.4],a,b)<.73) {
        const pixel=4*(y*width+x);
        data.fill(0,pixel,pixel+3);
      }
    }
  }
  const result=await draw({width,height:width,data},{portraitDiameterGrooves:16});
  const lines=result.points.slice(1,-1);
  const xs=lines.map(p=>p[0]), ys=lines.map(p=>p[1]);
  const left=Math.min(...xs), right=Math.max(...xs), top=Math.max(...ys), bottom=Math.min(...ys);
  for (const [x,y] of [[63,60],[51,63],[77,64]]) {
    const mark=[left+(x-10)*(right-left)/73, top-(y-12)*(top-bottom)/80];
    const distance=Math.min(...lines.slice(1).map((next,i)=>distanceToSegment(mark,lines[i],next)));
    assert.ok(distance < .045, `Missing a treehouse feature at ${x},${y}`);
  }
});
