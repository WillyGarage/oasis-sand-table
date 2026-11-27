const vm=require('node:vm'),assert=require('node:assert/strict'),fs=require('node:fs'),test=require('node:test');
const code=fs.readFileSync(require.resolve('../web/guest-photo.js'),'utf8');
const sandbox={window:{},document:{currentScript:null}};
vm.runInNewContext(code.replace('  window.GuestPhoto={','  window.smile=photographedShadowSmile;\n  window.GuestPhoto={'),sandbox);
function scene(angle=0,variant='open'){
 const width=220,height=155,span=134,c=Math.cos(angle),s=Math.sin(angle),start=[40,78];
 const at=(u,v)=>[start[0]+span*(u*c-v*s),start[1]+span*(u*s+v*c)];
 const L=Array.from({length:68},()=>[80,80]);L[48]=at(0,0);L[54]=at(1,0);
 const marks=[[.035,.04],[.25,-.040],[.50,-.038],[.74,-.025],[.965,.035],[.74,.114],[.50,.145],[.25,.116]];
 for(const [i,p] of marks.entries())L[60+i]=at(...p);
 const data=new Uint8ClampedArray(width*height*4);
 const top=u=>-((4*u*(1-u))**.72)*(.048+.026*(1-2*u)),bottom=u=>(4*u*(1-u))**.72*(.214+.035*(2*u-1));
 function pixel(x,y){
  const a=x-start[0],b=y-start[1],u=(a*c+b*s)/span,v=(b*c-a*s)/span;
  let color=[202,148,131];
  if(u>0 && u<1){
   const g=(4*u*(1-u))**.65,t=top(u),h=bottom(u);
   if(v>t-.052*g && v<h+.078*g)color=[184,100,94];
   if(v>=t && v<=h)color=u<.10 || u>.89 ? [71,34,32] : [226,209,178];
   if(v>t-.009 && v<t+.010)color=[72,38,36];
   if(v>t+.010 && v<t+.047 && u>.12 && u<.88)color=[162,97,88];
   if(variant==='covered' && u>.5)color=[163,157,150];
   if(variant==='closed' && v>=t-.013 && v<=h)color=[180,94,87];
  }
  return color;
 }
 for(let y=0;y<height;y++)for(let x=0;x<width;x++){
  const rgb=[0,0,0];
  for(const xx of [-.4,0,.4])for(const yy of [-.4,0,.4]){
   const sub=pixel(x+xx,y+yy);
   for(let k=0;k<3;k++)rgb[k]+=sub[k]/9;
  }
  data.set([...rgb,255],4*(y*width+x));
 }
 return {image:{width,height,data},L,at,top,bottom,span};
}
test('both margins follow an open smile at the photographed tilt',()=>{
 for(const angle of [0,.18,-.18]){
  const {image,L,span,at,top,bottom}=scene(angle);
  const measured=sandbox.window.smile(image,L,.27,0);
  assert.ok(measured);
  assert.deepEqual(measured[0],measured.at(-1));
  const distance=(p,q)=>Math.hypot(p[0]-q[0],p[1]-q[1]);
  const gap=(p)=>Math.min(...measured.map(q=>distance(p,q)));
  const check=[.22,.33,.45,.55,.67,.78];
  for(const curve of [top,bottom]){
   assert.ok(check.every(u=>gap(at(u,curve(u)))<.055*span));
  }
 }
});

test('closed lips, an obscured corner, and an undersized smile keep the original route',()=>{
 for(const style of ['closed','covered']){
  const {image,L}=scene(0,style);
  assert.equal(sandbox.window.smile(image,L,.27,0),null);
 }
 const {image,L}=scene();
 assert.equal(sandbox.window.smile(image,L,.04,0),null);
});
