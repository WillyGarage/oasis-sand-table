const assert=require('node:assert/strict');
const {readFileSync}=require('node:fs');
const vm=require('node:vm');
const test=require('node:test');
const source=readFileSync(require.resolve('../web/guest-photo.js'),'utf8');
const local={window:{},document:{currentScript:null}};
vm.runInNewContext(source.replace('  window.GuestPhoto={','  window.hinges=photographedHinges;\n  window.GuestPhoto={'),local);
function spectacleScene({angle=0,missing=false}={}) {
  const width=302,height=160,separation=90,data=new Uint8ClampedArray(width*height*4);
  const c=Math.cos(angle),s=Math.sin(angle);
  const photo=(x,y)=>[151+separation*(x*c-y*s),80+separation*(x*s+y*c)];
  const eyes=[-.5,.5].map(x=>[[-.16,0],[-.08,-.04],[.08,-.04],[.16,0],[.08,.04],[-.08,.04]].map(([u,v])=>photo(x+u,v)));
  const oval=t=>[.52+.42*Math.sign(Math.cos(t))*Math.abs(Math.cos(t))**.75,.025+.255*Math.sign(Math.sin(t))*Math.abs(Math.sin(t))**.75];
  const upper=x=>{const u=Math.max(0,Math.min(.9999,(x-.52)/.42));return .025-.255*(1-u**(2/.75))**(.75/2);};
  const hinges=[-1,1].map(sign=>photo(sign*1.04,upper(.80)+.24*.26+.005));
  const rims=[-1,1].map(sign=>Array.from({length:48},(_,i)=>{
    const [x,y]=oval(i*Math.PI/24);
    return photo(sign*x,y);
  }));
  for(let y=0;y<height;y++)for(let x=0;x<width;x++){
    const xx=((x-151)*c+(y-80)*s)/separation,yy=(-(x-151)*s+(y-80)*c)/separation;
    const u=Math.abs(xx),v=yy;
    const arc=u<.80 ? upper(u) : upper(.80)+(u-.80)*.26;
    const hasWire=u>.61 && u<(missing && xx>0 ? .89 : 1.04) && v>arc-.008 && v<arc+.015+.045*Math.max(0,(u-.79)/.25);
    const light=hasWire ? 25 : 180;
    data.set([light,light,light,255],4*(x+y*width));
  }
  return {image:{width,height,data},eyes,rims,hinges};
}
test('both flared hinges follow the photographed top wire under tilt',()=>{
  for(const angle of [0,.30,-.30]){
    const {image,eyes,rims,hinges}=spectacleScene({angle});
    const measured=local.window.hinges(image,eyes,rims,.7);
    assert.ok(measured);
    for(const [i,wire] of measured.entries()){
      const gap=line=>Math.min(...line.map(p=>Math.hypot(p[0]-hinges[i][0],p[1]-hinges[i][1])));
      assert.ok(gap(rims[i])>8);
      assert.ok(gap(wire)<2.2);
      assert.ok(rims[i].every(p=>wire.includes(p)),'keep the complete rim');
    }
  }
});

test('a missing tip or an undersized portrait keeps the original glasses',()=>{
  const {image,eyes,rims}=spectacleScene({missing:true});
  assert.equal(local.window.hinges(image,eyes,rims,.7),null);
  const complete=spectacleScene();
  assert.equal(local.window.hinges(complete.image,complete.eyes,complete.rims,.04),null);
});
