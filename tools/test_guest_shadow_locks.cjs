const fs=require('node:fs'), vm=require('node:vm'), assert=require('node:assert/strict'), test=require('node:test');
const code=fs.readFileSync(require.resolve('../web/guest-photo.js'),'utf8'),sandbox={window:{},document:{currentScript:null}};
vm.runInNewContext(code.replace('  window.GuestPhoto={','  window.edge=contrastedHair;\n  window.GuestPhoto={'),sandbox);
function run(angle,mode){
 const n=420,w=110,ox=205,oy=180,c=Math.cos(angle),s=Math.sin(angle);
 const point=(u,v)=>[ox+w*(c*u-s*v),oy+w*(s*u+c*v)];
 const L=Array.from({length:68},()=>point(0,0));
 for(let i=0;i<17;i++){const t=Math.PI*i/16;L[i]=point(-.5*Math.cos(t),.69*Math.sin(t));}
 const top=Array.from({length:25},(_,i)=>{const t=Math.PI*i/24;return point(.5*Math.cos(t),-.51*Math.sin(t));});
 const frame={cx:ox,cy:oy,radius:w*.98,person:{head:[...L.slice(0,17),...top],glasses:[]},landmarks:L};
 const data=new Uint8ClampedArray(n*n*4);
 for(let y=0;y<n;y++)for(let x=0;x<n;x++){
  const dx=(x-ox)/w,dy=(y-oy)/w,u=dx*c+dy*s,v=-dx*s+dy*c;
  const scalp=(u/.8)**2+(v/.77)**2<1 && v<0;
  const locks=Math.abs(u)<.8 && v>=0 && v<.88 && (mode!=='one'||u<0);
  const skin=(u/.50)**2+(v/(v<0?.43:.70))**2<1;
  let color=[210,218,225];
  if((scalp||locks)&&mode!=='flat')color=[29,21,19];
  if(skin)color=[190,147,120];
  data.set([...color,255],4*(n*y+x));
 }
 return sandbox.window.edge({width:n,height:n,data},frame,mode==='small'?45:90,mode==='neighbor'?[{x:ox+.55*w,y:oy-.5*w,w:1.3*w}]:[]);
}
test('the silhouette has open shoulder-length ends at the same face size',()=>{
 for(const angle of [0,.24,-.31]){
  const v=run(angle,'both'),cos=Math.cos(angle),sin=Math.sin(angle);
  assert.ok(v?.outside.length>=75);
  assert.equal(v.cx,205);assert.equal(v.cy,180);assert.equal(v.radius,110*.98);
  for(const p of [v.outside[0],v.outside.at(-1)]){
   const x=p[0]-v.cx,y=p[1]-v.cy;
   assert.ok((-x*sin+y*cos)/110>.39);
   assert.ok(Math.abs(x*cos+y*sin)/110>.70);
  }
 }
});

test('a bare temple, overlapping face, flat image and small portrait keep the earlier face',()=>{
 for(const angle of [0,.24,-.31])for(const mode of ['one','neighbor','flat','small']){
  assert.equal(run(angle,mode),null);
 }
});
