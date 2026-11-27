const fs=require('node:fs'),vm=require('node:vm'),test=require('node:test'),assert=require('node:assert/strict');
const sandbox={window:{}};
const file=require.resolve('../web/ring-shadow.js');
vm.runInNewContext(fs.readFileSync(file,'utf8'),sandbox);
const {piercedEar}=sandbox.window.GuestShadow;

// A tilted, skin-colored lobe against a dark temple and a light background.
// Face-width units keep both ears and the simulated groove at the same scale.
function scene(side,angle,mode) {
  const n=620,axis=222,mid=[310,295],c=Math.cos(angle),s=Math.sin(angle);
  const at=(x,y)=>[mid[0]+c*x-s*y,mid[1]+s*x+c*y];
  const L=Array.from({length:68},()=>at(0,0));
  L[0]=at(-axis/2,0);L[16]=at(axis/2,0);
  const frame={cx:mid[0],cy:mid[1],radius:210,landmarks:L},data=new Uint8ClampedArray(n*n*4);
  const near=[[18,73],[25,65],[47,42],[65,35],[132,35],[146,48]];
  const far=[[18,74],[38,82],[56,84],[72,77],[92,69],[116,59],[130,57],[146,48]];
  function edge(points,y){
    const i=points.findIndex(p=>p[0]>=y);
    if(i<=0)return points[0][1];
    const [y0,x0]=points[i-1],[y1,x1]=points[i];
    return x0+(x1-x0)*(y-y0)/(y1-y0);
  }
  for(let y=0;y<n;y++)for(let x=0;x<n;x++){
    const dx=x-mid[0],dy=y-mid[1],u=side*(c*dx+s*dy)-axis/2+.1*axis,v=-s*dx+c*dy+.2*axis;
    const inner=edge(near,v),outer=edge(far,v);
    let rgb=[198,188,158];
    if(u<inner)rgb=[39,32,28];
    else if(v>=18 && v<=146 && u<=outer)rgb=[202,142,124];
    const rx=(u-47)/7.8,ry=(v-122)/9.2;
    const t=Math.atan2(ry,rx)*180/Math.PI;
    if(mode!=='absent' && Math.abs(Math.hypot(rx,ry)-1)<.22 &&
       (mode==='fold' ? t>20 && t<115 : t>=-69 || t<-176))rgb=[37,27,20];
    data.set(rgb,(y*n+x)*4);
    data[(y*n+x)*4+3]=(mode==='transparent' && Math.abs(rx)<2 && Math.abs(ry)<2)?0:255;
  }
  return piercedEar({width:n,height:n,data},frame,mode==='small'?48:94);
}

test('a pierced lobe follows its photographed side through head tilts',()=>{
  for(const side of [-1,1])for(const a of [-.21,0,.18]){
    const found=scene(side,a,'hoop');
    assert.ok(found && found.rim.length>=20 && found.hoop.length>=10);
    const center=found.hoop[Math.floor(found.hoop.length/2)];
    assert.ok(side*(center[0]-310)>75);
    assert.ok(Math.hypot(...found.hoop[0].map((v,i)=>v-found.hoop.at(-1)[i]))>3);
  }
});

test('bare skin, a short crease, transparent pixels and cramped grooves omit the hoop',()=>{
  for(const mode of ['absent','fold','transparent','small'])assert.equal(scene(1,.12,mode),null);
});
