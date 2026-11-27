// Run with node --test tools/test_guest_gaze.cjs.
const assert = require('node:assert/strict');
const {readFileSync} = require('node:fs');
const test = require('node:test');
const vm = require('node:vm');

const source = readFileSync(require.resolve('../web/guest-photo.js'), 'utf8');
const context = {window:{}, document:{currentScript:null}};
vm.runInNewContext(source.replace('  window.GuestPhoto={',
  '  window.gaze=photographedGaze; window.lowerLid=photographedLowerLid;\n  window.GuestPhoto={'), context);

const eyes = [
  [[15.3,35],[31.3,28],[49.3,31],[65.3,38],[49.3,44],[31.3,41]],
  [[94.3,40],[110.3,33],[128.3,31],[144.3,37],[128.3,44],[110.3,46]]
];
const boundaries = [.64,.55];
// A 480-pixel portrait drawn in the 150.64 mm Mini center at a 5.32 mm groove.
// Each eye is under three grooves wide, with less than one groove between lids.
const scale = 150.64 / (5.32 * 480);

function lidY(eye, indices, x) {
  const i = indices.findIndex((j,k)=>k && x<=eye[j][0]);
  const [a,b] = [eye[indices[i-1]],eye[indices[i]]];
  return a[1]+(x-a[0])*(b[1]-a[1])/(b[0]-a[0]);
}

function eyeCoordinates(eye, [x,y]) {
  const top = lidY(eye,[0,1,2,3],x), bottom = lidY(eye,[0,5,4,3],x);
  return [(x-eye[0][0])/(eye[3][0]-eye[0][0]), (y-top)/(bottom-top)];
}

function photograph({mirror=false, whites=[205,205], directions=[1,1]}={}) {
  const width=162, height=78, data=new Uint8ClampedArray(width*height*4);
  for(let y=0;y<height;y++)for(let col=0;col<width;col++){
    const x=(mirror ? width-1-col : col)+.5;
    let gray=142;
    for(const [i,eye] of eyes.entries()){
      if(x<=eye[0][0] || x>=eye[3][0])continue;
      const [u,v]=eyeCoordinates(eye,[x,y+.5]);
      if(v<0 || v>1)continue;
      const edge=directions[i]>0 ? boundaries[i] : 1-boundaries[i];
      const transition=.5+.5*Math.tanh((u-edge-.04*(v-.5))*directions[i]/.055);
      gray=Math.round(35+(whites[i]-35)*transition);
    }
    data.set([gray,gray,gray,255],4*(col+y*width));
  }
  const landmarks=mirror ? eyes.slice().reverse().map(eye=>
    [3,2,1,0,5,4].map(j=>[width-eye[j][0],eye[j][1]])) : eyes;
  return {image:{width,height,data},landmarks};
}

function measure(scene, size=scale) {
  return context.window.gaze(scene.image,scene.landmarks,size);
}

test('each narrow Mini eye follows its own photographed iris edge', () => {
  const result=measure(photograph());
  assert.ok(result);
  for(const [i,eye] of result.entries()){
    assert.equal(eye.sign,1);
    assert.ok(Math.abs(eye.u-boundaries[i])<.065);
    const inside=eye.line.filter(p=>p[0]>eyes[i][0][0] && p[0]<eyes[i][3][0]);
    assert.ok(inside.map(p=>eyeCoordinates(eyes[i],p))
      .some(([u,v])=>Math.abs(u-boundaries[i])<.08 && v>.8),
      'the cut should reach the dark iris edge near the lower lid at center size');
  }
  assert.ok(result[0].u-result[1].u>.04);
});

test('the 633 mm center preserves both lids and the iris on a wide eye', () => {
  const wideScale=633/(7*480);
  for(const mirror of [false,true]){
    const scene=photograph({mirror}), result=measure(scene,wideScale);
    assert.ok(result);
    for(const [i,eye] of result.entries()){
      const landmarks=scene.landmarks[i];
      const samples=eye.line.filter(p=>p[0]>landmarks[0][0] && p[0]<landmarks[3][0])
        .map(p=>eyeCoordinates(landmarks,p));
      for(const [from,to] of [[.12,.30],[.70,.88]]){
        assert.ok(samples.some(([u,v])=>u>=from && u<=to && v<.18),'upper lid');
        assert.ok(samples.some(([u,v])=>u>=from && u<=to && v>.82),'lower lid');
      }
      assert.ok(samples.some(([u,v])=>Math.abs(u-eye.u)<.08 && v>.30 && v<.70),'iris edge');
    }
  }
});

test('mirroring the photo reverses both measured gaze positions', () => {
  const original=measure(photograph()), reflected=measure(photograph({mirror:true}));
  assert.ok(original && reflected);
  for(const [i,eye] of original.entries()){
    const opposite=reflected[1-i];
    assert.equal(opposite.sign,-eye.sign);
    assert.ok(Math.abs(eye.u+opposite.u-1)<.04);
  }
});

test('weak or disagreeing eyes and an undersized guest place keep their usual lids', () => {
  assert.equal(measure(photograph({whites:[44,44]})),null);
  assert.equal(measure(photograph({directions:[1,-1]})),null);
  assert.equal(measure(photograph(),92.36/(5.32*480)),null);
});

function lowerLidPhoto(contrast) {
  const width=110,height=85,data=new Uint8ClampedArray(width*height*4);
  const eye=[[22,39],[40,32],[60,31],[80,39],[61,44],[42,44]];
  for(let y=0;y<height;y++)for(let x=0;x<width;x++){
    const u=(x-22)/58, arch=Math.sin(Math.PI*u);
    const upper=39-8*arch, lower=39+11*arch;
    const darkness=u>=0 && u<=1 ? Math.min(1,Math.max(0,y-upper),Math.max(0,lower-y)) : 0;
    const gray=152-contrast*darkness, i=4*(y*width+x);
    data.set([gray,gray,gray,255],i);
  }
  return {image:{width,height,data},eye};
}

test('a visible lower eyelid keeps its photographed corners and clears the old six-point line', () => {
  const {image,eye}=lowerLidPhoto(110);
  const result=context.window.lowerLid(image,eye,1/6);
  assert.ok(result);
  assert.deepEqual(Array.from(result.line.slice(0,4),p=>Array.from(p)),eye.slice(0,4));
  for(const point of result.line.slice(4)){
    const u=(point[0]-22)/58;
    assert.ok(Math.abs(point[1]-(39+11*Math.sin(Math.PI*u)))<1.8);
  }
});

test('a weak, reversed, or undersized lower edge keeps the existing eye', () => {
  for(const contrast of [6,0,-75]){
    const {image,eye}=lowerLidPhoto(contrast);
    assert.equal(context.window.lowerLid(image,eye,1/6),null);
  }
  const {image,eye}=lowerLidPhoto(110);
  assert.equal(context.window.lowerLid(image,eye,1/16),null);
});
