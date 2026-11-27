const assert = require('node:assert/strict');
const test = require('node:test');

global.window = {};
require('../web/guest-art.js');
const {manageStrokes, sketchStroke, pathForStrokes, buffer} = window.GuestArt;
const {fitsGuestTravel} = require('../web/ring-planner.js');
const mini = require('../web/guest-paths.json');

function length(points) {
  return points.slice(1).reduce((sum, p, i) =>
    sum + Math.hypot(p[0] - points[i][0], p[1] - points[i][1]), 0);
}

test('separate strokes connect across the shortest gap and retrace it', () => {
  const lines = [[[-.8,0],[.8,0]], [[.2,.25],[.2,.7]]];
  const route = manageStrokes(lines, lines[0][0], {joinEdges:true});
  const distance = length(route) - 2 * lines.reduce((sum, line) => sum+length(line), 0);
  assert.ok(Math.abs(distance-2*.25) < 1e-10);
  assert.deepEqual(route[0], route.at(-1));
});

// Crossing zigzags put junctions between touch samples. Vary their length
// and amplitude to exercise the contour limit and each destination's travel limit.
function zigzags(vertices, extra, halfWidth, height) {
  return Array.from({length:24}, (_, row) => {
    const angle = 2*Math.PI*row/24+.03;
    const count = vertices+Number(row<extra);
    return sketchStroke(Array.from({length:count}, (_, i) => {
      const x = -halfWidth+2*halfWidth*i/(count-1), y = (i%2)*height+.015*(row%3);
      return [x*Math.cos(angle)-y*Math.sin(angle), x*Math.sin(angle)+y*Math.cos(angle)];
    }));
  });
}

test('a sketch at the size limit keeps every stroke and still closes', () => {
  const strokes = zigzags(166,0,.68,.029);
  const entry = strokes.flat().reduce((a,b) => a[1]>b[1] ? a : b);
  assert.ok(manageStrokes(strokes,entry).length <= 8000);
  assert.ok(manageStrokes(strokes,entry,{joinEdges:true}).length > 8000);
  const route = manageStrokes(strokes,entry,{joinEdges:true,pointLimit:8000});
  assert.ok(route.length <= 8000);
  assert.deepEqual(route[0], route.at(-1));
  const key = p => p.map(v => Math.round(v*1e9)).join(',');
  const visited = new Set(route.map(key));
  for(const line of strokes)for(const point of line)assert.ok(visited.has(key(point)));
});

test('joining strokes accounts for motor positions inserted by each table', () => {
  const ring = {angles:[7*Math.PI/6],center:.565,scale:.13617666666666667,faceEdge:true};
  const lines = zigzags(84,3,.58,.55);
  const top = lines.flat().reduce((a,b) => a[1]>b[1] ? a : b);
  const fits = points => fitsGuestTravel(points,0,ring);
  assert.ok(fits(manageStrokes(lines,top)));
  assert.ok(!fits(manageStrokes(lines,top,{joinEdges:true})));
  const fitted = manageStrokes(lines,top,{joinEdges:true,pointLimit:8000,finish:p=>fits(p)?p:null});
  assert.ok(fits(fitted));

  const miniLines = zigzags(125,6,.58,.070);
  const slot = mini.slots[0];
  assert.ok(buffer(pathForStrokes(miniLines,slot)).byteLength <= 12000*8);
  assert.ok(pathForStrokes(miniLines,slot,{joinEdges:true}).length > 12000);
  const motion = pathForStrokes(miniLines,slot,{joinEdges:true,pointLimit:12000});
  assert.equal(buffer(motion).byteLength, motion.length*8);
});
