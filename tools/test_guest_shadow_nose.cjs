const vm = require('node:vm');
const fs = require('node:fs');
const assert = require('node:assert/strict');
const test = require('node:test');
const source = fs.readFileSync(require.resolve('../web/ring-shadow.js'),'utf8');
const sandbox = {window:{}};
vm.runInNewContext(source.replace('window.GuestShadow={','window.GuestShadow={photographedNostrils,'),sandbox);

function scene(angle, variant, radius=285, width=69) {
  const size=260, cx=127, cy=129, cos=Math.cos(angle), sin=Math.sin(angle);
  function position(u,v) {
    const x=(u-.5)*width, y=(v+.22)*width;
    return [cx+cos*x-sin*y,cy+sin*x+cos*y];
  }
  const frame={radius,cx,cy,landmarks:[]};
  frame.landmarks[31]=position(0,0);
  frame.landmarks[35]=position(1,0);
  const data=new Uint8ClampedArray(size*size*4);
  for(let y=0;y<size;y++)for(let x=0;x<size;x++){
    const a=x-cx,b=y-cy,u=(a*cos+b*sin)/width+.5,v=(-a*sin+b*cos)/width-.22;
    const left=((u-.05)/.18)**2+((v+.14)/.105)**2<=1;
    const right=((u-.94)/.18)**2+((v+.17)/.11)**2<=1;
    const openings=variant!=='flat' && (left || (variant!=='one' && right));
    const joined=variant==='joined' && u>=.01 && u<=.94 && v>=-.16 && v<=-.1;
    const gray=openings || joined ? 53 : 185;
    data.set([gray,gray,gray,255],4*(y*size+x));
  }
  const image={width:size,height:size,data};
  return {arcs:sandbox.window.GuestShadow.photographedNostrils(image,frame,630,7),
    target(u,v){const [x,y]=position(u,v);return [(x-cx)*315/radius,(cy-y)*315/radius];}};
}

test('each upper edge follows its photographed tilt',()=>{
  for(const angle of [-.62,0,.63,1.80]){
    const {arcs,target}=scene(angle,'both');
    assert.equal(arcs.length,2);
    for(const [side,u,v] of [[0,.05,-.245],[1,.94,-.28]]){
      const [x,y]=target(u,v);
      assert.ok(Math.min(...arcs[side].map(p=>Math.hypot(p[0]-x,p[1]-y)))<2);
    }
  }
});

test('indistinct, merged or undersized openings keep the original nose',()=>{
  for(const angle of [-.62,0,.63,1.80]){
    for(const type of ['flat','one','joined'])assert.equal(scene(angle,type).arcs,null);
  }
  assert.equal(scene(0,'both',285,17).arcs,null);
  assert.equal(scene(0,'both',700).arcs,null);
});
