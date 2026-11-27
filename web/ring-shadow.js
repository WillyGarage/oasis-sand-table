/* Convert the selected face's own shadows to separate sand strokes. Source
 * images and face measurements stay on the guest's device. Output coordinates
 * are millimeters from the portrait center, with positive y upwards. */
(() => {
  'use strict';

  const clamp=(n,lo,hi)=>Math.max(lo,Math.min(hi,n));
  const distance=(a,b)=>Math.hypot(a[0]-b[0],a[1]-b[1]);
  const midpoint=(a,b)=>[(a[0]+b[0])/2,(a[1]+b[1])/2];

  function anatomy(frame,diameter,groove) {
    const {person,landmarks:L,cx,cy,radius}=frame, scale=diameter/(2*radius);
    const physical=p=>[(p[0]-cx)*scale,(cy-p[1])*scale];
    const marks=[];
    function add(kind,points,closed=false) {
      if(points?.length>1)marks.push({kind,closed,points:points.map(physical)});
    }
    // Placement priority matters. The planner gives the silhouette, both eyes
    // and the actual mouth first choice of room for their entry and return.
    add('head',frame.longHair?.outside || person.head,!frame.longHair);
    if(person.glasses.length===2){
      for(const lens of person.glasses)add('glasses',lens,true);
    }else{
      for(const eye of person.eyes){
        const open=Math.max(distance(eye[1],eye[5]),distance(eye[2],eye[4]))*scale>=1.2*groove;
        add('eye',open?eye:eye.slice(0,4),open);
      }
    }
    // 'smile' names the mouth mark for the route planner. A closed mouth is
    // represented by the measured lip seam without changing the expression.
    const open=distance(L[62],L[66])*scale>=1.35*groove;
    const seam=[L[60],midpoint(L[61],L[67]),midpoint(L[62],L[66]),midpoint(L[63],L[65]),L[64]];
    add('smile',frame.beardSmile || (open?L.slice(60,68):seam),frame.beardSmile ? true : open);
    if(person.frameBridge)add('bridge',person.frameBridge);
    if(frame.longHair)add('hairline',frame.longHair.inner,true);
    else if(person.hair.length)add('hairline',person.hair.slice(person.hair.length/2));
    add('nose',person.noseLine);
    if(!person.glasses.length)for(const brow of person.brows)add('brow',brow);
    if(frame.beardStrokes){
      // Leave enough room for the ball to enter the tuft from its independent
      // clearing turn without cutting back across the silhouette or the nose.
      const obstacles=marks.filter(m=>['head','smile','nose'].includes(m.kind)).flatMap(m=>
        m.points.slice(0,m.closed ? undefined : -1).map((a,i)=>{
          const b=m.points[(i+1)%m.points.length],dx=b[0]-a[0],dy=b[1]-a[1];
          return {a,dx,dy,d2:dx*dx+dy*dy};
        }));
      for(const stroke of frame.beardStrokes){
        const runs=[[]];
        for(const p of stroke.map(physical)){
          if(obstacles.some(({a,dx,dy,d2})=>{
            const x=p[0]-a[0],y=p[1]-a[1],t=clamp((x*dx+y*dy)/(d2 || 1),0,1);
            return Math.hypot(x-t*dx,y-t*dy)<1.55*groove;
          })){if(runs.at(-1).length)runs.push([]);}
          else runs.at(-1).push(p);
        }
        for(const points of runs)if(points.length>1 && distance(points[0],points.at(-1))>(stroke.chinStrand ? 1.45 : 2.4)*groove)
          marks.push({kind:'shade',facialHair:true,chinStrand:!!stroke.chinStrand,closed:false,points});
      }
    }
    return marks;
  }

  function faceMask(points,frame,n) {
    const canvas=document.createElement('canvas');
    canvas.width=canvas.height=n;
    const ctx=canvas.getContext('2d',{willReadFrequently:true}),scale=n/(2*frame.radius);
    ctx.translate(n/2,n/2);ctx.scale(scale,scale);ctx.translate(-frame.cx,-frame.cy);
    ctx.beginPath();
    for(const [i,p] of points.entries()){
      if(i===0)ctx.moveTo(p[0],p[1]);else ctx.lineTo(p[0],p[1]);
    }
    ctx.closePath();ctx.fill();
    const rgba=ctx.getImageData(0,0,n,n).data,mask=new Uint8Array(n*n);
    for(let i=0;i<mask.length;i++)mask[i]=rgba[4*i+3];
    return mask;
  }

  // Three separable box filters approximate a Gaussian without work growing
  // with the blur radius. The wider filter estimates illumination on the skin.
  function blur(input,n,sigma) {
    const r=Math.max(1,Math.round(sigma-.45)),width=2*r+1;
    const scratch=new Float32Array(input.length),output=new Float32Array(input.length);
    function axis(src,dst,stride){
      for(let line=0;line<n;line++){
        const start=stride===1?line*n:line;
        let sum=(r+1)*src[start];
        for(let k=1;k<=r;k++)sum+=src[start+Math.min(k,n-1)*stride];
        for(let k=0;k<n;k++){
          dst[start+k*stride]=sum/width;
          sum+=src[start+Math.min(n-1,k+r+1)*stride]-src[start+Math.max(0,k-r)*stride];
        }
      }
    }
    for(let k=0;k<3;k++){axis(k?output:input,scratch,1);axis(scratch,output,n);}
    return output;
  }

  // A dark earring leaves a curved band with skin visible through its
  // center. Measure both edges of that band before tracing the adjacent ear.
  function piercedEar(image,frame,diameterGrooves) {
    const L=frame.landmarks,dx=L[16][0]-L[0][0],dy=L[16][1]-L[0][1],width=Math.hypot(dx,dy);
    const perGroove=2*frame.radius/diameterGrooves;
    if(diameterGrooves<62 || width<94 || width/perGroove<26 || frame.longHair)return null;
    const unit=222,nx=118,ny=172,u0=-.10,v0=-.20;
    const angles=Array.from({length:12},(_,i)=>(-62+i*245/11)*Math.PI/180);
    const order=(a,f)=>a.slice().sort((x,y)=>x-y)[Math.floor((a.length-1)*f)];
    function fit(side) {
      const origin=L[side>0?16:0];
      const at=(x,y)=>{const u=side*(x/unit+u0),v=y/unit+v0;return [origin[0]+dx*u-dy*v,origin[1]+dy*u+dx*v];};
      if([[0,0],[0,ny-1],[nx-1,0],[nx-1,ny-1]].some(p=>{
        const [x,y]=at(...p);return x<1 || y<1 || x>=image.width-2 || y>=image.height-2;
      }))return null;
      const tone=new Float32Array(nx*ny),color=new Float32Array(3*nx*ny);
      for(let y=0;y<ny;y++)for(let x=0;x<nx;x++){
        const [px,py]=at(x,y),a=Math.floor(px),b=Math.floor(py),u=px-a,v=py-b,j=4*(b*image.width+a);
        const q=image.data,j2=j+4*image.width;
        if(Math.min(q[j+3],q[j+7],q[j2+3],q[j2+7])<240)return null;
        const rgb=[0,1,2].map(k=>{
          return (1-v)*((1-u)*q[j+k]+u*q[j+4+k])+v*((1-u)*q[j2+k]+u*q[j2+4+k]);});
        const i=y*nx+x,light=.299*rgb[0]+.587*rgb[1]+.114*rgb[2];
        tone[i]=light;color[3*i]=rgb[0]-rgb[1];color[3*i+1]=rgb[1]-rgb[2];color[3*i+2]=light*.30;
      }
      const soft=new Float32Array(tone);
      for(let y=1;y<ny-1;y++)for(let x=1;x<nx-1;x++){
        const i=y*nx+x;soft[i]=(4*tone[i]+2*(tone[i-1]+tone[i+1]+tone[i-nx]+tone[i+nx])+
          tone[i-nx-1]+tone[i-nx+1]+tone[i+nx-1]+tone[i+nx+1])/16;
      }
      function sample(x,y) {
        const a=Math.floor(x),b=Math.floor(y),u=x-a,v=y-b,i=b*nx+a;
        return (1-v)*((1-u)*soft[i]+u*soft[i+1])+v*((1-u)*soft[i+nx]+u*soft[i+nx+1]);
      }
      function offsets(rx,ry,rotation,ts=angles) {
        const c=Math.cos(rotation),s=Math.sin(rotation);
        return ts.map(t=>{const x=rx*Math.cos(t),y=ry*Math.sin(t);return [x*c-y*s,x*s+y*c];});
      }
      function evidence(cx,cy,arms) {
        const inside=[],outside=[],both=[];
        let clippedInner=0,clippedBoth=0;
        for(const [x,y] of arms){
          const band=sample(cx+x,cy+y);
          const inner=(sample(cx+x*.34,cy+y*.34)+sample(cx+x*.64,cy+y*.64))/2-band;
          const outer=(sample(cx+x*1.37,cy+y*1.37)+sample(cx+x*1.60,cy+y*1.60))/2-band;
          inside.push(inner);outside.push(outer);both.push(Math.min(inner,outer));
          clippedInner+=clamp(inner,-22,115);clippedBoth+=clamp(Math.min(inner,outer),-22,110);
        }
        return {score:.40*order(inside,.35)+.27*order(both,.30)+(.22*clippedBoth+.11*clippedInner)/arms.length,
          inner:order(inside,.2),outer:order(outside,.2)};
      }
      // Skip flat skin and dark hair before the more expensive shape fit.
      const centers=[];
      for(let y=(.23-v0)*unit;y<(.48-v0)*unit;y+=2.1)for(let x=-u0*unit;x<(.30-u0)*unit;x+=2.1){
        const i=Math.round(y)*nx+Math.round(x),r=.038*unit;
        if(tone[i]<60 || color[3*i]+color[3*i+1]<9)continue;
        const outside=Math.min(sample(x+r,y),sample(x+.7*r,y+.7*r),sample(x,y+r),sample(x-r,y));
        if(tone[i]-outside>23)centers.push([x,y]);
      }
      let best=null;
      function tryFit(cx,cy,rx,ry,rotation,arms) {
        const obs=evidence(cx,cy,arms);
        if(!best || obs.score>best.score)best={cx,cy,rx,ry,rotation,...obs};
      }
      for(const rx of [.027,.038,.05])for(const ry of [.032,.044,.055])for(const rotation of [-.38,0,.38]){
        const arms=offsets(rx*unit,ry*unit,rotation);
        for(const [x,y] of centers)tryFit(x,y,rx*unit,ry*unit,rotation,arms);
      }
      if(!best || best.score<43)return null;
      // Refine to the observed band itself, with the coarse fit as a bound.
      for(const step of [1,.50,.25]){
        for(let pass=0;pass<3;pass++){
          const prev=best;
          for(const [key,limit] of [['cx',step],['cy',step],['rx',step],['ry',step],['rotation',step*.13]]){
            for(const sign of [-1,1]){
              const trial={...best,[key]:best[key]+sign*limit};
              if(trial.rx<.022*unit || trial.rx>.057*unit || trial.ry<.026*unit || trial.ry>.07*unit || Math.abs(trial.rotation)>.65)continue;
              const {cx,cy,rx,ry,rotation}=trial;tryFit(cx,cy,rx,ry,rotation,offsets(rx,ry,rotation));
            }
          }
          if(best===prev)break;
        }
      }
      if(best.score<48 || best.inner<24 || best.outer<20 || 2*Math.min(best.rx,best.ry)*width/unit<2.3*perGroove)return null;
      const {cx,cy,rx,ry,rotation}=best;
      const phi=Array.from({length:28},(_,i)=>(-62+i*245/27)*Math.PI/180);
      const hoop=offsets(rx,ry,rotation,phi).map(([x,y])=>at(cx+x,cy+y));

      // Learn the lobe color just above the opening. Follow its outer edge
      // upward while the same skin remains distinct from the background.
      const swatch=(x,y)=>{const i=3*(Math.round(y)*nx+Math.round(x));return [color[i],color[i+1],color[i+2]];};
      const refs=[[-.62,1.4],[-.12,1.8],[.18,2.5],[.30,1.8],[-.5,2.6]].map(([x,y])=>swatch(cx+x*rx,cy-y*ry));
      const colorDistance=(a,b)=>Math.hypot(a[0]-b[0],a[1]-b[1],a[2]-b[2]);
      const closest=p=>{const near=refs.map(ref=>colorDistance(p,ref)).sort((a,b)=>a-b);return (near[0]+near[1])/2;};
      // Find one connected edge through the successive rows. Adjacent
      // samples may drift across a curve, but cannot jump to a second edge.
      function contour(xs,ys,start,slope,bend,maxStep,score) {
        let prev=xs.map(x=>-3.7*Math.abs(x-start));
        const parents=[],merits=[],window=Math.floor(maxStep/(xs[1]-xs[0])+1e-6);
        for(const y of ys){
          const row=xs.map(x=>score(x,y)),parent=[];
          const next=xs.map((x,i)=>{
            let best=-Infinity;
            for(let j=Math.max(0,i-window);j<=Math.min(xs.length-1,i+window);j++){
              const d=Math.abs(x-xs[j]),v=prev[j]-slope*d-bend*d*d;
              if(v>best){best=v;parent[i]=j;}
            }
            return best+row[i];
          });
          parents.push(parent);merits.push(row);prev=next;
        }
        let j=prev.indexOf(Math.max(...prev));
        const loc=[],quality=[];
        for(let i=ys.length-1;i>=0;i--){
          loc[i]=xs[j];quality[i]=merits[i][j];j=parents[i][j];
        }
        return {loc,quality};
      }
      const xs=Array.from({length:36},(_,i)=>cx+unit*(-.025+.215*i/35));
      const ys=[];
      for(let y=cy-.9*ry;y>=cy-.53*unit && y>=1;y-=2)ys.push(y);
      if(xs[0]<7 || xs.at(-1)>=nx-7 || ys.length<5)return null;
      const {loc,quality}=contour(xs,ys,cx+rx*1.18,2.2,.7,4.2,(x,y)=>{
        const skin=swatch(x-3,y),out=swatch(x+3,y),near=closest(skin);
        const far=Math.min(closest(out),closest(swatch(x+6,y)));
        return Math.min(44,far-near)+.58*Math.min(62,colorDistance(skin,out))-.53*near;
      });
      let end=quality.length-1;
      for(let i=3;i+2<quality.length;i++){
        if(ys[0]-ys[i]>.24*unit && quality.slice(i,i+3).every(v=>v<9)){end=i-1;break;}
      }
      while(end>0 && quality[end]<10)end--;
      if(ys[0]-ys[end]<.25*unit || order(quality.slice(0,end+1),.25)<16 || loc[0]-cx>2.2*rx)return null;
      const rim=ys.slice(0,end+1).map((y,i)=>at((loc[Math.max(0,i-1)]+2*loc[i]+loc[Math.min(end,i+1)])/4,y));
      // At the crown the skin is on the opposite side of the border.
      // Continue back towards the temple only where the photograph supports it.
      const tx=loc[end],ty=ys[end],innerXs=Array.from({length:60},(_,i)=>tx+unit*(-.20+.225*i/59));
      const innerYs=[];
      for(let y=ty;y<ty+.22*unit;y+=1.9)innerYs.push(y);
      if(innerXs[0]<7 || innerXs.at(-1)>=nx-7 || innerYs.at(-1)>=ny-2)return null;
      const inner=contour(innerXs,innerYs,tx-3,1.5,.51,4.3,(x,y)=>{
        const skin=closest(swatch(x+3,y)),hair=closest(swatch(x-3,y));
        const gradient=order([2,4,6].map(k=>sample(x+k,y)-sample(x-k,y)),.5);
        return .51*clamp(gradient,-40,65)+.65*Math.min(40,hair-skin)-.30*skin;
      });
      const upper=inner.loc;
      if(tx-upper[0]<-1 || tx-upper[0]>.058*unit || tx-upper.at(-1)<.066*unit ||
         order(inner.quality.slice(2),.25)<16)return null;
      const gap=tx-upper[0];
      for(let i=1;i<5;i++){
        const t=Math.PI*i/5;
        rim.push(at(tx-.5*gap*(1-Math.cos(t)),ty-.23*gap*Math.sin(t)));
      }
      for(let i=0;i<upper.length;i++){
        const x=(upper[Math.max(0,i-1)]+2*upper[i]+upper[Math.min(i+1,upper.length-1)])/4;
        rim.push(at(x,innerYs[i]));
      }
      return {rim,hoop};
    }
    const right=fit(1),left=fit(-1);
    return right && left ? null : (right || left);
  }

  // The hoop's near tip touches the side of the head. Approach along that
  // contact and circle the visible arc, leaving the photographed hole open.
  function joinPiercedEar(head,ear,groove) {
    const {hoop,rim}=ear;
    function closest(line,point,closed=false) {
      let best={distance:Infinity};
      for(let i=0;i<line.length-(closed?0:1);i++){
        const a=line[i],b=line[(i+1)%line.length],dx=b[0]-a[0],dy=b[1]-a[1];
        const t=clamp(((point[0]-a[0])*dx+(point[1]-a[1])*dy)/(dx*dx+dy*dy || 1),0,1);
        const p=[a[0]+t*dx,a[1]+t*dy],d=distance(p,point);
        if(d<best.distance)best={distance:d,p,i,t};
      }
      return best;
    }
    const low=closest(head,hoop.at(-1),true),hub=closest(hoop,rim[0]);
    if(low.distance>1.55*groove || hub.distance>1.65*groove)return null;
    const stem=[low.p,...hoop.slice(hub.i+1).reverse(),hub.p];
    const tip=hoop.slice(0,hub.i+1).reverse();
    const fromHoop=stem.concat(tip,tip.slice(0,-1).reverse(),[hub.p]);
    // A fitted outer head may already follow the upper helix. Rejoin at
    // the first sustained meeting, replacing just the inaccurate lower lobe.
    const contacts=rim.map(p=>closest(head,p,true));
    let meet=-1;
    for(let i=Math.ceil(.22*rim.length);i<rim.length-2;i++){
      if(contacts.slice(i,i+3).every(v=>v.distance<.75*groove)){meet=i;break;}
    }
    const walk=(a,b)=>{
      const pts=[a.p];let k=(a.i+1)%head.length;
      while(k!==(b.i+1)%head.length){pts.push(head[k]);k=(k+1)%head.length;}
      pts.push(b.p);return pts;
    };
    if(meet>=0){
      const high=contacts[meet],link=fromHoop.concat(rim.slice(0,meet+1),[high.p]);
      if(low.i===high.i)return null;
      const fwd=walk(low,high),back=walk(high,low);
      const length=pts=>pts.slice(1).reduce((n,p,i)=>n+distance(p,pts[i]),0);
      const retained=length(fwd)<length(back) ? back : fwd.slice().reverse();
      if(Math.min(length(fwd),length(back))>1.65*distance(low.p,high.p))return null;
      return link.concat(retained.slice(1,-1));
    }
    const link=fromHoop.concat(rim);
    return head.slice(0,low.i+1).concat(link,link.slice(0,-1).reverse(),head.slice(low.i+1));
  }

  // Sample in the nose's own axes so tilting the face does not tilt the search.
  // Only trace two compact dark openings surrounded by brighter skin.
  function photographedNostrils(image,frame,diameter,groove) {
    const left=frame.landmarks[31],right=frame.landmarks[35],dx=right[0]-left[0],dy=right[1]-left[1];
    const width=Math.hypot(dx,dy),scale=diameter/(2*frame.radius);
    if(width<20 || width*scale<7*groove)return null;
    const unit=72,n=129,ox=28,oy=72;
    const position=(x,y)=>[left[0]+((x-ox)*dx-(y-oy)*dy)/unit,left[1]+((x-ox)*dy+(y-oy)*dx)/unit];
    const outside=([x,y])=>x<0 || y<0 || x>=image.width-1 || y>=image.height-1;
    if([[0,0],[n-1,0],[0,n-1],[n-1,n-1]].some(p=>outside(position(...p))))return null;
    const samples=new Float32Array(n*n);
    const values=image.data;
    const light=i=>255+(values[i]*.299+values[i+1]*.587+values[i+2]*.114-255)*values[i+3]/255;
    for(let y=0;y<n;y++)for(let x=0;x<n;x++){
      const [px,py]=position(x,y),ix=Math.floor(px),iy=Math.floor(py),u=px-ix,v=py-iy;
      const i=4*(ix+iy*image.width),j=i+4*image.width;
      samples[y*n+x]=(1-v)*((1-u)*light(i)+u*light(i+4))+v*((1-u)*light(j)+u*light(j+4));
    }
    const local=blur(samples,n,unit*.021),broad=blur(samples,n,unit*.17);
    const arcs=[];
    let previousEnd=null;
    for(const [low,high] of [[-.2,.38],[.60,1.22]]){
      let evidence=20,center=-1;
      for(let y=oy-Math.floor(.39*unit);y<=oy;y++)for(let x=ox+Math.ceil(low*unit);x<=ox+Math.floor(high*unit);x++){
        const i=y*n+x,score=broad[i]-local[i];
        if(score>evidence){evidence=score;center=i;}
      }
      if(center<0)return null;
      const cx=center%n,cy=Math.floor(center/n),ring=[];
      for(let y=cy-18;y<=cy+18;y++)for(let x=cx-18;x<=cx+18;x++){
        const r=Math.hypot(x-cx,y-cy);
        if(x>=0 && x<n && r>=.18*unit && r<=.24*unit)ring.push(local[y*n+x]);
      }
      ring.sort((a,b)=>a-b);
      const span=ring[Math.floor(.72*(ring.length-1))]-local[center];
      if(span<35)return null;
      const threshold=local[center]+.42*span,visited=new Uint8Array(n*n),stack=[center];
      const top=new Int16Array(n).fill(n);
      let x0=cx,x1=cx,y0=cy,y1=cy;
      visited[center]=1;
      while(stack.length){
        const i=stack.pop(),x=i%n,y=Math.floor(i/n);
        x0=Math.min(x0,x);x1=Math.max(x1,x);y0=Math.min(y0,y);y1=Math.max(y1,y);
        if(!x || x===n-1 || !y || y===n-1 || x1-x0>.50*unit || y1-y0>.35*unit)return null;
        top[x]=Math.min(top[x],y);
        for(const j of [i-1,i+1,i-n,i+n])if(!visited[j] && local[j]<threshold){visited[j]=1;stack.push(j);}
      }
      if((x1-x0)*width*scale/unit<1.6*groove || x1-x0<.13*unit || y1-y0<.065*unit)return null;
      if(previousEnd!==null && (x0-previousEnd)*width*scale/unit<1.6*groove)return null;
      previousEnd=x1;
      const arc=[];
      for(let x=x0+1;x<x1;x++){
        const y=(top[x-1]+2*top[x]+top[x+1])/4;
        const [px,py]=position(x,y);
        arc.push([(px-frame.cx)*scale,(frame.cy-py)*scale]);
      }
      arcs.push(arc);
    }
    return arcs;
  }

  function sourceTone(image,frame,n,groovePixels,required=true) {
    // The open outer hair path has no photographed bottom. Shade the face
    // inside its jaw and forehead instead of closing a line across the neck.
    const mask=faceMask(frame.longHair?.inner || frame.person.head,frame,n);
    const hair=!frame.longHair && frame.person.hair.length?faceMask(frame.person.hair,frame,n):new Uint8Array(n*n);
    const beard=frame.beardMask && faceMask(frame.beardMask,frame,n);
    // In facial hair the useful change in brightness runs across the hairs,
    // which mostly point toward the jaw. The broad chin shadow runs along it.
    const dx=frame.landmarks[16][0]-frame.landmarks[0][0],dy=frame.landmarks[16][1]-frame.landmarks[0][1];
    const w=Math.hypot(dx,dy),down=w ? [-dy/w,dx/w] : [0,1];
    if(beard)for(let i=0;i<hair.length;i++)hair[i]=Math.max(hair[i],beard[i]);

    const cheeks=[[1,3,5,7,48,31,40],[15,13,11,9,54,35,46]].map(indices=>
      faceMask(indices.map(i=>frame.landmarks[i]),frame,n));
    const values=new Float32Array(n*n),hist=new Uint32Array(256);
    const {width,height,data}=image,scale=2*frame.radius/n;
    function light(x,y) {
      const k=(y*width+x)*4,alpha=data[k+3]/255;
      return 255+alpha*(.299*data[k]+.587*data[k+1]+.114*data[k+2]-255);
    }
    let used=0;
    for(let y=0;y<n;y++)for(let x=0;x<n;x++){
      const i=y*n+x;if(!mask[i])continue;
      const px=clamp(frame.cx+(x+.5-n/2)*scale,0,width-1);
      const py=clamp(frame.cy+(y+.5-n/2)*scale,0,height-1);
      const x0=Math.floor(px),y0=Math.floor(py),x1=Math.min(width-1,x0+1),y1=Math.min(height-1,y0+1);
      const u=px-x0,v=py-y0;
      values[i]=(1-v)*((1-u)*light(x0,y0)+u*light(x1,y0))+v*((1-u)*light(x0,y1)+u*light(x1,y1));
      if(mask[i]>=192){hist[Math.round(values[i])]++;used++;}
    }
    function quantile(frac) {
      let sum=0;
      for(let i=0;i<hist.length;i++){sum+=hist[i];if(sum>=frac*used)return i;}
      return 255;
    }
    const low=quantile(.04),high=quantile(.96);
    if(!used || high-low<12){
      if(!required)return null;
      throw Error('There is too little contrast inside this face for separate shadow lines.');
    }
    const luminance=blur(values,n,.42*groovePixels);
    for(let i=0;i<values.length;i++){
      values[i]=mask[i]/255*clamp((high-values[i])/(high-low),0,1)**1.35;
    }
    const tone=blur(values,n,.42*groovePixels),illumination=blur(tone,n,.075*n);
    for(let i=0;i<tone.length;i++){
      tone[i]=mask[i]/255*Math.max(0,tone[i]-.52*illumination[i]*(1-hair[i]/255));
    }
    return {tone,hair,mask,cheeks,luminance,beard,down,contrast:high-low};
  }

  function tangentField(tone,n,groovePixels) {
    const difference=new Float32Array(n*n),cross=new Float32Array(n*n);
    for(let y=1;y<n-1;y++)for(let x=1;x<n-1;x++){
      const i=y*n+x;
      const gx=tone[i-n+1]+2*tone[i+1]+tone[i+n+1]-tone[i-n-1]-2*tone[i-1]-tone[i+n-1];
      const gy=tone[i+n-1]+2*tone[i+n]+tone[i+n+1]-tone[i-n-1]-2*tone[i-n]-tone[i-n+1];
      difference[i]=gx*gx-gy*gy;cross[i]=2*gx*gy;
    }
    const along=blur(difference,n,1.6*groovePixels),across=blur(cross,n,1.6*groovePixels);
    // The tensor averages edge orientation even where the sign flips across
    // a strand of hair. The tangent follows the edge, rather than crossing it.
    for(let i=0;i<along.length;i++){
      const angle=.5*Math.atan2(across[i],along[i])+Math.PI/2;
      along[i]=Math.cos(angle);across[i]=Math.sin(angle);
    }
    return [along,across];
  }

  function simplify(points,tolerance) {
    if(points.length<3)return points;
    const keep=new Uint8Array(points.length),stack=[[0,points.length-1]];
    keep[0]=keep[points.length-1]=1;
    while(stack.length){
      const [start,end]=stack.pop(),a=points[start],b=points[end],dx=b[0]-a[0],dy=b[1]-a[1];
      const length=dx*dx+dy*dy;
      let best=-1,largest=tolerance*tolerance;
      for(let i=start+1;i<end;i++){
        const u=points[i][0]-a[0],v=points[i][1]-a[1],t=length?clamp((u*dx+v*dy)/length,0,1):0;
        const deviation=(u-dx*t)**2+(v-dy*t)**2;
        if(deviation>largest){largest=deviation;best=i;}
      }
      if(best<0)continue;
      keep[best]=1;stack.push([start,best],[best,end]);
    }
    return points.filter((_,i)=>keep[i]);
  }

  function shading(marks,photo,n,diameter,groove) {
    const [vx,vy]=tangentField(photo.tone,n,groove*n/diameter);
    if(photo.beard){
      const [bx,by]=tangentField(photo.luminance,n,.36*groove*n/diameter);
      for(let i=0;i<vx.length;i++)if(photo.beard[i]>=128){
        const [dx,dy]=photo.down,dp=dx*bx[i]+dy*by[i],weight=.70*Math.abs(dp);
        const x=dx*(1-weight)+bx[i]*Math.sign(dp)*weight;
        const y=dy*(1-weight)+by[i]*Math.sign(dp)*weight;
        const l=Math.hypot(x,y);vx[i]=x/l;vy[i]=y/l;
      }
    }
    const toPixels=p=>[(p[0]/diameter+.5)*n,(.5-p[1]/diameter)*n];
    const toMm=p=>[(p[0]/n-.5)*diameter,(.5-p[1]/n)*diameter];
    const occupied=new Uint8Array(n*n),broadShade=new Uint8Array(n*n),groovePixels=groove*n/diameter;
    const minimum=1.64*groovePixels,stamps=new Map();
    function cover(points,closed,radius,target=occupied) {
      radius=Math.ceil(radius+.8);
      if(!stamps.has(radius)){
        const rows=[];
        for(let y=-radius;y<=radius;y++)rows.push(Math.floor(Math.sqrt(radius*radius-y*y)));
        stamps.set(radius,rows);
      }
      const rows=stamps.get(radius);
      for(let i=0;i<points.length-(closed?0:1);i++){
        const a=points[i],b=points[(i+1)%points.length],steps=Math.max(1,Math.ceil(distance(a,b)));
        for(let j=0;j<=steps;j++){
          const x=Math.round(a[0]+(b[0]-a[0])*j/steps),y=Math.round(a[1]+(b[1]-a[1])*j/steps);
          if(x+radius<0 || x-radius>=n)continue;
          for(let yy=Math.max(0,y-radius);yy<=Math.min(n-1,y+radius);yy++){
            const half=rows[yy-y+radius],left=Math.max(x-half,0),right=Math.min(x+half,n-1);
            if(right>=left)target.fill(1,yy*n+left,yy*n+right+1);
          }
        }
      }
    }
    for(const mark of marks)cover(mark.points.map(toPixels),mark.closed,minimum);

    // A deterministic ordering gives the same person the same drawing the
    // next time the guest opens it. Prefer strong observed shadows first.
    let randomState=8168;
    function random(){randomState=(Math.imul(randomState,1664525)+1013904223)>>>0;return randomState/4294967296;}
    const bins=Array.from({length:128},()=>[]),stride=Math.max(2,Math.round(groovePixels*.65));
    for(let y=2;y<n-2;y+=stride)for(let x=2;x<n-2;x+=stride){
      const xx=Math.min(n-2,x+Math.floor(random()*stride)),yy=Math.min(n-2,y+Math.floor(random()*stride));
      const i=yy*n+xx,priority=.7*photo.tone[i]+.3*random();
      if(photo.tone[i]>.205 && !occupied[i])bins[Math.min(127,Math.floor(priority*128))].push(i);
    }
    const step=.32*groovePixels,cellSize=Math.max(2,.7*groovePixels);
    const cells=Math.ceil(n/cellSize),epochs=new Uint32Array(cells*cells),visits=new Uint16Array(cells*cells);
    let epoch=0;
    function trace(seed,sign,previous) {
      let x=seed%n,y=Math.floor(seed/n),px=0,py=0;
      const result=[];epoch++;
      for(let k=0;k<360;k++){
        const ix=Math.round(x),iy=Math.round(y),i=iy*n+ix;
        if(ix<1 || ix>=n-1 || iy<1 || iy>=n-1 || occupied[i] || photo.tone[i]<.18)break;
        const cell=Math.floor(y/cellSize)*cells+Math.floor(x/cellSize);
        if((epochs[cell]===epoch && k-visits[cell]>7) || (k>5 && previous?.has(cell)))break;
        epochs[cell]=epoch;visits[cell]=k;
        result.push([x,y]);
        const direction=k===0?sign:(vx[i]*px+vy[i]*py>=0?1:-1);
        let dx=vx[i]*direction,dy=vy[i]*direction;
        if(k){dx=.46*px+.54*dx;dy=.46*py+.54*dy;}
        const mag=Math.hypot(dx,dy);
        if(mag<.01)break;
        px=dx/mag;py=dy/mag;x+=step*px;y+=step*py;
      }
      return result;
    }
    // A fold is darker than skin on both sides. A broad lighting gradient
    // can suggest many parallel folds in sand even where the source has one
    // continuous shadow. Space those hatches farther from each other.
    function oneSidedLight(line){
      let samples=0,slope=0,cheek=0;
      for(let i=1;i+1<line.length;i+=3){
        const [x,y]=line[i],dx=line[i+1][0]-line[i-1][0],dy=line[i+1][1]-line[i-1][1];
        const index=Math.round(y)*n+Math.round(x);
        if(!photo.cheeks.some(mask=>mask[index]>=128))continue;
        cheek++;
        const length=Math.hypot(dx,dy);if(length<.01)continue;
        const k=1.5*groovePixels/length,nx=dy*k,ny=-dx*k;
        const a=Math.round(y+ny)*n+Math.round(x+nx),b=Math.round(y-ny)*n+Math.round(x-nx);
        if(photo.mask[a]<250 || photo.mask[b]<250)continue;
        const left=photo.luminance[a],right=photo.luminance[b],on=photo.luminance[Math.round(y)*n+Math.round(x)];
        samples++;
        if(Math.abs(left-right)>.05*photo.contrast && Math.min(left,right)-on<.02*photo.contrast)slope++;
      }
      return cheek*3>.35*line.length && samples>=4 && slope>.55*samples;
    }
    for(let b=bins.length-1;b>=0;b--)for(const seed of bins[b]){
      if(occupied[seed])continue;
      const back=trace(seed,-1,null);
      const earlier=new Set(back.slice(5).map(p=>Math.floor(p[1]/cellSize)*cells+Math.floor(p[0]/cellSize)));
      const front=trace(seed,1,earlier),line=back.slice(1).reverse().concat(front);
      if(line.length<3)continue;
      let hair=0,tone=0,beardSamples=0;
      for(const [x,y] of line){
        const i=Math.round(y)*n+Math.round(x);
        hair+=photo.hair[i];tone+=photo.tone[i];
        if(photo.beard && photo.beard[i]>=128)beardSamples++;
      }
      const inBeard=beardSamples>line.length/2;
      const inHair=hair>110*line.length;
      if((line.length-1)*step < groovePixels*(inHair?2.4:4.6))continue;
      const clean=simplify(line,.076*groovePixels);
      const spacing=minimum*(1+.65*(1-tone/line.length)**2);
      cover(clean,false,spacing);
      if(!inHair && oneSidedLight(line)){
        const nearEarlier=line.filter(([x,y])=>broadShade[Math.round(y)*n+Math.round(x)]).length;
        if(nearEarlier>.22*line.length)continue;
        cover(clean,false,2.5*spacing,broadShade);
      }
      marks.push({kind:'shade',...(inBeard ? {facialHair:true} : {}),closed:false,points:clean.map(toMm)});
    }
  }

  // A part is a narrow, continuous change of tone from the forehead into the
  // crown. Look on both sides of the ridge in a frame level with the jaw.
  // Return a second set of hair strokes only when a real sweep crosses it.
  function partedHair(image,frame,hairMask,diameterInGrooves,strands) {
    if(frame.beardMask || !strands.length)return null;
    const a=frame.landmarks[0],b=frame.landmarks[16],dx=b[0]-a[0],dy=b[1]-a[1];
    const width=Math.hypot(dx,dy),g=2/diameterInGrooves;
    if(width<50 || width/(frame.radius*g)<12)return null;
    const n=128,half=n/2,ox=(a[0]+b[0])/2,oy=(a[1]+b[1])/2;
    function drawing(x,y){
      const u=(x-half)/n,v=(y-n)/n;
      return [(ox+u*dx-v*dy-frame.cx)/frame.radius,(frame.cy-oy-u*dy-v*dx)/frame.radius];
    }
    const gray=new Float32Array(n*n),mask=new Uint8Array(n*n);
    for(let y=0;y<n;y++)for(let x=0;x<n;x++){
      const [hx,hy]=drawing(x,y),px=frame.cx+hx*frame.radius,py=frame.cy-hy*frame.radius;
      if(px<0 || px>=image.width-1 || py<0 || py>=image.height-1)continue;
      const i=y*n+x,k=4*(Math.round(py)*image.width+Math.round(px));
      const luma=.299*image.data[k]+.587*image.data[k+1]+.114*image.data[k+2];
      gray[i]=255+image.data[k+3]/255*(luma-255);
      const gx=Math.floor((hx+1)*96),gy=Math.floor((1-hy)*96);
      if(gx>=0 && gx<192 && gy>=0 && gy<192 && Math.hypot(hx,hy)<.967)mask[i]=hairMask[gy*192+gx];
    }
    const tone=blur(gray,n,1.3),ridge=new Float32Array(n*n);
    function contrast(i,gap){
      const left=tone[i-gap]-tone[i],right=tone[i+gap]-tone[i];
      return Math.max(Math.min(left,right),Math.min(-left,-right));
    }
    for(let y=0;y<n;y++)for(let x=6;x<n-6;x++){
      const i=y*n+x;
      ridge[i]=.6*contrast(i,3)+.4*contrast(i,5);
    }
    let best=null;
    for(let x=half-28;x<=half+28;x++){
      for(let y=38;y<=81;y+=2){
        if(mask[y*n+x]<210 || mask[(y+9)*n+x]>205)continue;
        for(let tilt=-.8;tilt<=.81;tilt+=.1){
          let strength=0,supported=0;
          for(let h=0;h<40;h++){
            const xx=Math.round(x-h*tilt),i=(y-h)*n+xx;
            if(y-h<2 || mask[i]<184)break;
            strength+=clamp(ridge[i],0,24);
            if(ridge[i]>3)supported++;
            if(h<15 || supported<.56*(h+1))continue;
            const score=strength/Math.sqrt(h+1);
            if(score>(best?.score ?? 19))best={x,y,tilt,h,score};
          }
        }
      }
    }
    if(!best)return null;
    // The crown mask can extend down onto a shaded forehead. The brightness
    // on both sides of the part locates the hairline in the actual photograph.
    const flank=t=>{
      const k=(best.y-t)*n+Math.round(best.x-t*best.tilt);
      return (tone[k-7]+tone[k+7])/2;
    };
    const hairLight=(flank(Math.round(best.h*.55))+flank(Math.round(best.h*.8)))/2;
    const skinLight=(flank(-15)+flank(-20))/2;
    if(Math.abs(skinLight-hairLight)<15)return null;
    let root=0;
    while(root<best.h && (flank(root)-hairLight)/(skinLight-hairLight)>.30)root++;
    if(best.h-root<13)return null;
    const part=[];
    for(let t=root;t<=best.h;t+=2){
      const {x,y,tilt}=best,center=x-t*tilt;
      let sx=0,weights=0;
      for(let k=-2;k<=2;k++){
        const xx=Math.round(center)+k,w=Math.max(0,ridge[(y-t)*n+xx])/(1+.30*k*k);
        sx+=w*xx;weights+=w;
      }
      part.push(drawing(weights?sx/weights:center,y-t));
    }
    const first=part[0];
    let choice;
    for(const [index,{points}] of strands.entries()){
      const dense=[points[0]];
      for(let i=1;i<points.length;i++){
        const p=points[i-1],q=points[i],n=Math.ceil(distance(p,q)/(.2*g));
        for(let j=1;j<=n;j++)dense.push([p[0]+j/n*(q[0]-p[0]),p[1]+j/n*(q[1]-p[1])]);
      }
      let gap=Infinity,cross,along;
      for(const [i,p] of dense.entries())for(const [j,s] of part.entries()){
        const d=distance(p,s);
        if(d<gap){gap=d;cross=i;along=j;}
      }
      if(gap>g || distance(first,part[along])<1.35*g || (choice && choice.dense.length>=dense.length))continue;
      choice={index,dense,cross,along};
    }
    if(!choice)return null;
    const {dense,cross,along,index}=choice;
    const [long,short]=[dense.slice(0,cross+1).reverse(),dense.slice(cross)].sort((a,b)=>b.length-a.length);
    // Make a rounded turn from the photographed part into the longer lock.
    // Leave open sand at the other end so the two locks read separately.
    const tail=long.findIndex(p=>distance(p,long[0])>2.9*g);
    if(tail<0 || distance(first,long.at(-1))<2.6*g)return null;
    const bend=part[along],end=long[tail],arc=[];
    for(let k=0;k<=10;k++){
      const t=k/10,s=1-t;
      arc.push([s*s*first[0]+2*s*t*bend[0]+t*t*end[0],s*s*first[1]+2*s*t*bend[1]+t*t*end[1]]);
    }
    // The rounded corner itself must remain in the measured hair, too.
    if(arc.some(([x,y])=>{
      const gx=Math.floor((x+1)*96),gy=Math.floor((1-y)*96);
      return Math.hypot(x,y)>.967 || gx<0 || gx>=192 || gy<0 || gy>=192 || hairMask[gy*192+gx]<160;
    }))return null;
    const pieces=[simplify(arc.concat(long.slice(tail+1)),.07*g)];
    const away=short.findIndex(p=>part.every(s=>distance(p,s)>1.5*g));
    if(away>=0 && distance(short[away],short.at(-1))>2*g)pieces.push(simplify(short.slice(away),.07*g));
    return strands.filter((_,i)=>i!==index).map(s=>s.points).concat(pieces);
  }

  function miniHair(image, frame, contours, diameterInGrooves, onPartedHair) {
    const size = 192, diameter = 2, groove = diameter/diameterInGrooves;
    const light = sourceTone(image, frame, size, size/diameterInGrooves, false);
    if (!light) return [];
    // Work in the exact crop used by the Mini's eyes, smile and head outline.
    // Restrict the seeds and their continuation to photographed hair or beard.
    const radius=size/2-.7*size/diameterInGrooves;
    for (let i=0; i<light.tone.length; i++) {
      // A long lock can continue beyond the circular crop inside this square
      // image. Its off-table shadows must not shrink the entire face to fit.
      if (light.hair[i]<192 || (frame.clipHairToRim &&
          (i%size-size/2)**2+(Math.floor(i/size)-size/2)**2>radius*radius)) light.tone[i]=0;
    }
    const marks = contours.map(points => ({points,closed:true}));
    shading(marks, light, size, diameter, groove);
    const strands=marks.slice(contours.length).filter(({points})=>{
      if(!frame.clipHairToRim)return true;
      // A short hatch grazing the rim reads as a spur on the outline.
      // Keep sweeping strands and hatches well inside the photographed hair.
      const length=points.slice(1).reduce((total,p,i)=>total+distance(points[i],p),0);
      return length>=18*groove || (length>=5*groove && points.some(p=>Math.hypot(...p)<1-2.5*groove));
    });
    const back=points=>[...points,...points.slice(1,-1).reverse()];
    if(onPartedHair){
      const swept=partedHair(image,frame,light.hair,diameterInGrooves,strands);
      if(swept){
        const extent=Math.max(...contours.concat(strands.map(s=>s.points)).map(line=>
          line.reduce((r,p)=>Math.max(r,Math.hypot(...p)),0)));
        if(swept.every(line=>line.every(p=>Math.hypot(...p)<=extent+1e-9)))onPartedHair(swept.map(back));
      }
    }
    return strands.map(({points})=>back(points));
  }

  function measuredGroove(diameter,diameterInGrooves){
    if(!Number.isFinite(diameter) || diameter<=0 || !Number.isFinite(diameterInGrooves) || diameterInGrooves<=0){
      throw Error('The portrait area needs a measured diameter and groove width for photo shadows.');
    }
    return diameter/diameterInGrooves;
  }

  function drawFace(image,frame,diameter,groove) {
    const marks=anatomy(frame,diameter,groove);
    const n=clamp(Math.round(3.4*diameter/groove),192,560);
    const fixed=marks.length;
    shading(marks,sourceTone(image,frame,n,groove*n/diameter),n,diameter,groove);
    if(frame.beardMask){
      const scale=diameter/(2*frame.radius);
      for(let i=marks.length-1;i>=fixed;i--){
        if(!marks[i].facialHair && echoesMouth(marks[i].points,frame,scale,groove))marks.splice(i,1);
      }
    }
    if(!marks.some(m=>m.kind==='shade'))throw Error('This face has no separate shadow lines at this size.');
    return marks;
  }

  function fromFace(image,frame,diameter,diameterInGrooves,measureEyes,onShadowFrame,measureSmile,tracking=0) {
    const groove=measuredGroove(diameter,diameterInGrooves);
    // A tilted head can be wider than its upright crop. Leave space outside
    // its contour for the last clearing turn without changing its proportions.
    if(frame.longHair)frame={...frame,cx:frame.longHair.cx,cy:frame.longHair.cy,radius:frame.longHair.radius};
    const {person,cx,cy}=frame;
    const extent=Math.max(...[...person.head,...person.glasses.flat()].map(p=>Math.hypot(p[0]-cx,p[1]-cy)));
    const interior=1-3.5/diameterInGrooves;
    if(!frame.longHair && interior>0 && extent>frame.radius*interior)frame={...frame,radius:extent/interior};
    const marks=drawFace(image,frame,diameter,groove);
    if(frame.hinges && frame.hinges.every(line=>line.every(([x,y])=>
      Math.hypot(x-cx,y-cy)<frame.radius*(1-3.5/diameterInGrooves)))){
      const scale=diameter/(2*frame.radius);
      for(const [i,mark] of marks.filter(m=>m.kind==='glasses').entries()){
        mark.rim=mark.points;
        mark.points=frame.hinges[i].map(([x,y])=>[(x-frame.cx)*scale,(frame.cy-y)*scale]);
      }
    }
    const lids=marks.filter(mark=>mark.kind==='eye');
    if(measureEyes && lids.length===2 && lids.every(mark=>mark.closed)){
      const scale=diameter/(2*frame.radius);
      const gaze=measureEyes(image,person.eyes,scale/groove);
      if(gaze?.every(eye=>!eye || eye.bothLids)){
        for(const [i,mark] of lids.entries()){
          if(!gaze[i])continue;
          // Keep the ordinary eye if the lower lid or the iris excursion
          // would block another essential feature in the finished drawing.
          mark.lids=mark.points;
          mark.points=gaze[i].line.map(([x,y])=>[(x-frame.cx)*scale,(frame.cy-y)*scale]);
        }
      }
    }
    const mouth=marks.find(m=>m.kind==='smile');
    if(measureSmile && !frame.beardStrokes && diameterInGrooves>=62 && mouth?.closed){
      const scale=diameter/(2*frame.radius);
      const curve=measureSmile(image,frame.landmarks,scale/groove,tracking);
      if(curve){
        mouth.opening=mouth.points;
        mouth.points=curve.map(([x,y])=>[(x-cx)*scale,(cy-y)*scale]);
      }
    }
    if(!frame.beardStrokes && diameterInGrooves>=62){
      const nose=marks.findIndex(m=>m.kind==='nose');
      const arcs=nose>=0 && photographedNostrils(image,frame,diameter,groove);
      if(arcs)marks.splice(nose,1,{...marks[nose],noseBase:marks[nose].points,points:arcs[0]},
        {kind:'nose',closed:false,points:arcs[1]});
    }
    if(frame.measuredEar){
      const scale=diameter/(2*frame.radius),mm=p=>[(p[0]-frame.cx)*scale,(frame.cy-p[1])*scale];
      const ear={hoop:frame.measuredEar.hoop.map(mm),rim:frame.measuredEar.rim.map(mm)};
      const head=marks.find(m=>m.kind==='head' && m.closed);
      const fitted=head && joinPiercedEar(head.points,ear,groove);
      if(fitted){head.points=fitted;frame={...frame,earTrace:ear};}
    }
    // A local host can trace the hair in the identical selected pixels and
    // physical coordinates, including a high-resolution crop or head tilt.
    if(onShadowFrame)onShadowFrame(image,frame);
    return marks;
  }

  // The photographed opening already supplies the mouth. A small group
  // portrait can acquire a second smile if a nearby lip or chin shadow runs
  // alongside it. Preserve folds that lead up the cheek or away from the lip.
  function echoesMouth(points,frame,scale,groove) {
    const [a,b]=[48,54].map(i=>[(frame.landmarks[i][0]-frame.cx)*scale,(frame.cy-frame.landmarks[i][1])*scale]);
    const width=distance(a,b);
    if(!width)return false;
    const center=midpoint(a,b),ux=(b[0]-a[0])/width,uy=(b[1]-a[1])/width;
    let near=0,length=0;
    for(let i=1;i<points.length;i++){
      const p=points[i-1],q=points[i],dx=q[0]-p[0],dy=q[1]-p[1],segment=Math.hypot(dx,dy);
      length+=segment;
      if(Math.abs(dx*ux+dy*uy)<.65*segment)continue;
      const n=Math.max(1,Math.ceil(segment/groove));
      for(let j=0;j<n;j++){
        const t=(j+.5)/n,x=p[0]+t*dx-center[0],y=p[1]+t*dy-center[1];
        const along=x*ux+y*uy,down=x*uy-y*ux;
        if(Math.abs(along)<.6*width+.6*groove && down>-.27*width && down<.53*width)near+=segment/n;
      }
    }
    return near>.46*length;
  }

  function fromGroup(image,people,diameter,diameterInGrooves) {
    const groove=measuredGroove(diameter,diameterInGrooves);
    const bounds=people.flatMap(p=>[p.shape.head,...p.shape.locks].flat().map(p.place));
    const xx=bounds.map(p=>p[0]),yy=bounds.map(p=>p[1]);
    const cx=(Math.min(...xx)+Math.max(...xx))/2,cy=(Math.min(...yy)+Math.max(...yy))/2;
    const reach=Math.max(...bounds.map(p=>Math.hypot(p[0]-cx,p[1]-cy)));
    const scale=(diameter/2-2.7*groove)/reach;
    if(!(scale>0))throw Error('This center is too small for separate faces.');
    const all=[];
    for(const {frame,place,owner} of people){
      const envelope=[frame.person.head,...frame.person.glasses].flat();
      const extent=Math.max(...envelope.map(p=>Math.hypot(p[0]-frame.cx,p[1]-frame.cy)));
      const radius=Math.max(frame.radius,1.02*extent);
      const local=drawFace(image,{...frame,radius},2*radius*scale,groove);
      const [x,y]=place([frame.cx,frame.cy]);
      for(const m of local){
        if(m.kind==='shade' && echoesMouth(m.points,frame,scale,groove))continue;
        const points=m.points.map(([u,v])=>[u+(x-cx)*scale,v+(cy-y)*scale]);
        all.push({...m,points,owner});
      }
    }
    const required=new Set(['head','eye','glasses','smile']);
    return all.sort((a,b)=>Number(required.has(b.kind))-Number(required.has(a.kind)));
  }

  window.GuestShadow={fromFace,fromGroup,piercedEar,joinPiercedEar,miniHair};
})();
