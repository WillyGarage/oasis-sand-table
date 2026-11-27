// Run with node --test tools/test_guest_fringe.cjs.
const assert = require('node:assert/strict');
const {readFileSync} = require('node:fs');
const test = require('node:test');
const vm = require('node:vm');

const source = readFileSync(require.resolve('../web/guest-photo.js'), 'utf8');
const context = {window:{}, document:{currentScript:null}};
vm.runInNewContext(source.replace('  window.GuestPhoto={',
  '  window.fringe=photographedFringe;\n  window.GuestPhoto={'), context);

const marks = Array.from({length:68}, () => [128,140]);
marks[0]=[36,150]; marks[16]=[220,150];
for (const [i,x] of [53,67,83,101,119,137,155,171,187,202].entries()) marks[17+i]=[x,137];
const outline = Array.from({length:19}, (_,i) => [46+i*9,70]);
const groovesPerPixel = .08;

function forehead(strand,mirror=false) {
  const side=256, data=new Uint8ClampedArray(side*side*4);
  for (let y=0;y<side;y++) for (let x=0;x<side;x++) {
    const ink=strand(mirror ? side-x : x,y) ? 40 : 190;
    data.set([ink,ink,ink,255],4*(x+y*side));
  }
  return {width:side,height:side,data};
}

test('draw the photographed taper on either side while keeping the brow clear', () => {
  const hair=(x,y)=>y>=60 && y<138 && Math.abs(x-(103+.18*(y-70)))<3;
  const tips=[false,true].map(mirror=>{
    const path=context.window.fringe(forehead(hair,mirror),marks,outline,groovesPerPixel);
    const tip=path.find(p=>p[1]>80);
    assert.ok(tip && tip[1]>111 && tip[1]<128);
    assert.equal(path.filter(p=>p[1]>80).length,1);
    assert.ok(marks.slice(17,27).every(([x,y])=>Math.hypot(x-tip[0],y-tip[1])*groovesPerPixel>=1.4));
    assert.deepEqual(path[0],outline[0]);
    assert.deepEqual(path.at(-1),outline.at(-1));
    return tip;
  });
  assert.ok(Math.abs(tips[0][0]+tips[1][0]-256)<9);
});

test('smooth hair and an isolated mark retain their original paths', () => {
  const spot=(x,y)=>Math.hypot(x-118,y-100)<3;
  for(const image of [forehead(()=>false),forehead(spot)]){
    assert.equal(context.window.fringe(image,marks,outline,groovesPerPixel),outline);
    assert.equal(context.window.fringe(image,marks,outline,0),outline);
  }
});
