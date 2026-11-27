/* Local photo engraving. The phone sends only the resulting continuous drawing to the table. */
(() => {
  'use strict';

  const GRID = 95;
  const clamp = (x, lo, hi) => Math.min(Math.max(x, lo), hi);

  function insidePolygon([x,y], polygon) {
    let inside=false;
    for(let i=0,j=polygon.length-1;i<polygon.length;j=i++) {
      const [x0,y0]=polygon[j],[x1,y1]=polygon[i];
      if((y0>y)!==(y1>y) && x < x0+(y-y0)*(x1-x0)/(y1-y0)) inside=!inside;
    }
    return inside;
  }

  function grayAt(image, x, y) {
    const ix = clamp(Math.floor(x), 0, image.width - 1);
    const iy = clamp(Math.floor(y), 0, image.height - 1);
    const i = (iy * image.width + ix) * 4;
    return pixelGray(image.data, i);
  }

  function pixelGray(rgba, i) {
    const grey = 0.299 * rgba[i] + 0.587 * rgba[i+1] + 0.114 * rgba[i+2];
    return 255 + (grey - 255) * rgba[i+3] / 255;
  }

  function interpolatedGray(image,x,y) {
    const ix=Math.floor(x), iy=Math.floor(y), fx=x-ix, fy=y-iy;
    return (1-fy)*((1-fx)*grayAt(image,ix,iy)+fx*grayAt(image,ix+1,iy))+
      fy*((1-fx)*grayAt(image,ix,iy+1)+fx*grayAt(image,ix+1,iy+1));
  }

  // Convert each rectangle to the four integral-image offsets used at this scale.
  function rectangleOffsets(stumps, stride) {
    return stumps.map(stump => {
      const offsets = stump.slice();
      for (let i = 3; i < stump.length; i += 5) {
        const top = stump[i+1] * stride + stump[i];
        const bottom = top + stump[i+3] * stride;
        const width = stump[i+2];
        offsets[i] = top;
        offsets[i+1] = bottom + width;
        offsets[i+2] = top + width;
        offsets[i+3] = bottom;
      }
      return offsets;
    });
  }

  // A 24px Haar face cascade. Rectangle sums and image variance are constant-time
  // integral-image lookups; photos and classifier data stay in the guest's browser.
  function faceBoxes(image, scanSize=320, smallestScale=0) {
    const candidates = [];
    const stages = window.GuestFaceStages;
    if (!stages) return [];
    const start = Math.min(1, scanSize / Math.max(image.width, image.height));
    for (let scale = start; scale>smallestScale && Math.min(image.width, image.height)*scale >= 24; scale /= 1.13) {
      const w = Math.floor(image.width*scale), h = Math.floor(image.height*scale);
      const stride = w+1;
      const ii = new Int32Array(stride*(h+1));
      const square = new Float64Array(ii.length);
      const sourceColumns = new Int32Array(w);
      for (let x = 0; x < w; x++) sourceColumns[x] = 4*Math.floor((x+.5)/scale);
      const rgba = image.data;
      for (let y=0; y<h; y++) {
        const sourceRow = Math.floor((y+.5)/scale) * image.width * 4;
        let row=0, rowSq=0;
        for (let x=0; x<w; x++) {
          const gray=Math.round(pixelGray(rgba,sourceRow+sourceColumns[x]));
          row+=gray; rowSq+=gray*gray;
          const p=(y+1)*stride+x+1;
          ii[p]=row+ii[p-stride]; square[p]=rowSq+square[p-stride];
        }
      }
      function rect(integral, p, dx, dy) {
        return integral[p]+integral[p+dx+dy]-integral[p+dx]-integral[p+dy];
      }
      const offsetsByStage = [];
      function passes(x,y) {
        const pos=y*stride+x;
        const inner=pos+stride+1;
        const sum=rect(ii,inner,22,22*stride);
        const variance=22*22*rect(square,inner,22,22*stride)-sum*sum;
        if(variance<=1) return false;
        const norm=Math.sqrt(variance);
        for (let stage = 0; stage < stages.length; stage++) {
          const [threshold, source] = stages[stage];
          const stumps = offsetsByStage[stage] ??= rectangleOffsets(source, stride);
          let score=0;
          for(const stump of stumps){
            let weighted=0;
            for(let i=3;i<stump.length;i+=5){
              const sum=ii[pos+stump[i]]+ii[pos+stump[i+1]]-ii[pos+stump[i+2]]-ii[pos+stump[i+3]];
              weighted+=stump[i+4]*sum;
            }
            score+=stump[weighted<stump[0]*norm?1:2];
          }
          if(score<threshold) return false;
        }
        return true;
      }
      for(let y=0;y<=h-24;y+=2)for(let x=0;x<=w-24;x+=2){
        if(passes(x,y))candidates.push({x:(x+12)/scale,y:(y+12)/scale,w:24/scale});
      }
    }
    const clusters = [];
    for (const box of candidates.sort((a,b) => a.w-b.w)) {
      const found = clusters.find(c => Math.abs(c.x-box.x) < .28*Math.min(c.w,box.w)
        && Math.abs(c.y-box.y) < .28*Math.min(c.w,box.w) && box.w/c.w < 1.6);
      if (!found) clusters.push({...box,n:1});
      else {
        found.n++;
        for (const key of ['x','y','w']) found[key] += (box[key]-found[key])/found.n;
      }
    }
    const result = [];
    for (const box of clusters.filter(c => c.n>=3).sort((a,b) => b.n-a.n)) {
      if (result.every(c => Math.hypot(c.x-box.x,c.y-box.y) > .48*Math.max(c.w,box.w))) result.push(box);
    }
    return result.sort((a,b) => b.w-a.w);
  }

  // Use two different crop widths to measure the proposed face on its original
  // pixels. The overview remains the coordinate system used for a guest's taps.
  function locatePanoramaFace(source,image,box) {
    const crop=document.createElement('canvas'); crop.width=crop.height=320;
    const ctx=crop.getContext('2d',{willReadFrequently:true}), center=crop.width/2;
    for (const degrees of [0,20,-20]) {
      const angle=degrees*Math.PI/180, c=Math.cos(angle), s=Math.sin(angle);
      const matches=[];
      for (const factor of [3.5,5]) {
        const side=box.w*factor, scale=crop.width/side;
        ctx.setTransform(1,0,0,1,0,0);ctx.fillStyle='#888';ctx.fillRect(0,0,crop.width,crop.height);
        ctx.translate(center,center);ctx.scale(scale,scale);ctx.rotate(angle);
        ctx.drawImage(source,-box.x,-box.y,image.width,image.height);
        const close=faceBoxes(ctx.getImageData(0,0,crop.width,crop.height)).filter(b=>
          Math.hypot(b.x-center,b.y-center)<.36*scale*box.w && Math.abs(Math.log(b.w/(scale*box.w)))<.49);
        if (close.length!==1) break;
        const b=close[0], dx=(b.x-center)/scale, dy=(b.y-center)/scale;
        matches.push({x:box.x+c*dx+s*dy,y:box.y-s*dx+c*dy,w:b.w/scale,n:b.n});
      }
      if (matches.length!==2) continue;
      const [a,b]=matches;
      if (Math.abs(Math.log(a.w/b.w))>.22 || Math.hypot(a.x-b.x,a.y-b.y)>.2*Math.min(a.w,b.w)) continue;
      return {x:(a.x+b.x)/2,y:(a.y+b.y)/2,w:(a.w+b.w)/2,n:a.n+b.n,...(angle?{angle}:{})};
    }
    return null;
  }

  async function portraitBoxes(image,originalFile) {
    const found=faceBoxes(image);
    const src=document.createElement('canvas');
    src.width=image.width; src.height=image.height;
    src.getContext('2d').putImageData(image,0,0);
    const canvas=document.createElement('canvas'), ctx=canvas.getContext('2d',{willReadFrequently:true});
    const same=(a,b)=>Math.min(a.w,b.w)>.60*Math.max(a.w,b.w) &&
      Math.hypot(a.x-b.x,a.y-b.y)<.42*Math.min(a.w,b.w);
    function turned(degrees) {
      const angle=degrees*Math.PI/180, c=Math.cos(angle), s=Math.sin(angle);
      canvas.width=Math.ceil(Math.abs(image.width*c)+Math.abs(image.height*s));
      canvas.height=Math.ceil(Math.abs(image.width*s)+Math.abs(image.height*c));
      ctx.fillStyle='#888'; ctx.fillRect(0,0,canvas.width,canvas.height);
      ctx.translate(canvas.width/2,canvas.height/2); ctx.rotate(angle);
      ctx.drawImage(src,-image.width/2,-image.height/2);
      return faceBoxes(ctx.getImageData(0,0,canvas.width,canvas.height)).map(b=>{
        const x=b.x-canvas.width/2, y=b.y-canvas.height/2;
        return {...b,x:image.width/2+c*x+s*y,y:image.height/2-s*x+c*y,angle};
      });
    }
    // A tilted face may disappear in an upright scan. Keep a new location
    // only when the detector agrees at two additional angles on the same side.
    for (const sign of [-1,1]) {
      const candidates=turned(sign*20).filter(b=>b.n>=5 && !found.some(a=>same(a,b)) &&
        b.x>=b.w*.45 && image.width-b.x>=b.w*.45 && b.y>=b.w*.45 && image.height-b.y>=b.w*.45);
      if (!candidates.length) continue;
      const near=turned(sign*12);
      const confirmed=candidates.filter(b=>near.some(a=>same(a,b)));
      if (!confirmed.length) continue;
      const far=turned(sign*36);
      for (const b of confirmed) if (far.some(a=>same(a,b)) && !found.some(a=>same(a,b))) found.push(b);
    }
    // In a group photo a face can be smaller than the 24-pixel classifier
    // window on the normal overview. Search just the missing scales and
    // check each new location on an enlarged crop before offering it.
    const side=Math.max(image.width,image.height);
    if (side>400) {
      const fine=faceBoxes(image,720,320/side);
      const small=fine.filter(b=>!found.some(a=>same(a,b)));
      const candidates=small.length ? verifiedGroupBoxes(image,small,true) : [];
      if (candidates.length) {
        // The same detector can repeatedly mistake a sleeve or a nose for a
        // whole face. A separate local model checks only the extra candidates.
        try {
          await loadFaceVerifier();
          const verified=await window.GuestFaceVerify.check(src,candidates);
          found.push(...candidates.filter((_,i)=>verified[i]));
        } catch (error) {
          // The optional extra check must not prevent a guest from choosing
          // a detected face or drawing a frame by hand on an older Mini.
          console.warn('Extra face check unavailable',error);
          found.push(...candidates);
        }
      }
      // Searching at one size can miss everyone between the available Haar
      // windows, especially when a whole room is reduced to a strip. Search
      // overlapping squares along the photo. Keep a new face only if both
      // detectors put it in the same place on the source.
      if (side>=2*Math.min(image.width,image.height)) {
        try {
          await loadFaceVerifier();
          const proposals=await window.GuestFaceVerify.scanPanorama(src);
          const wanted=proposals.filter(box=>{
            const existing=found.find(other=>same(box,other));
            // Clarify a coarse window truncated by the smallest available scale.
            return !existing || fine.some(b=>same(existing,b) && Math.abs(Math.log(existing.w/b.w))>.22);
          });
          if (wanted.length) {
            const locate=source=>{
              for (const box of wanted) {
                const measured=locatePanoramaFace(source,image,box);
                if (!measured || !same(measured,box)) continue;
                const index=found.findIndex(b=>same(b,box));
                if (index<0) found.push(measured);
                else found[index]=measured;
              }
            };
            if (originalFile) await withOriginal(originalFile,locate);
            else locate(src);
          }
        } catch (error) {console.warn('Wide photo search unavailable',error);}
      }
    }
    // Check the weakest extra boxes before showing the picker. A patterned
    // sleeve can look like another face in the wide shot but disappear in a crop.
    const confirmed=new Set(found.length>1 ? verifiedGroupBoxes(image,found) : found);
    // The Haar cascade can miss one guest in a group when their photo is
    // mirrored. Reflect only the search image, then check and draw the
    // extra faces using their original positions and features.
    canvas.width=image.width; canvas.height=image.height;
    ctx.setTransform(-1,0,0,1,image.width,0);
    ctx.drawImage(src,0,0);
    const reflected=faceBoxes(ctx.getImageData(0,0,canvas.width,canvas.height))
      .map(box=>({...box,x:image.width-box.x}))
      .filter(box=>!found.some(other=>same(box,other)));
    const candidates=found.concat(reflected);
    const uncertain=candidates.filter(box=>!confirmed.has(box));
    if (uncertain.length) {
      try {
        await loadFaceVerifier();
        const checks=await window.GuestFaceVerify.check(src,uncertain);
        uncertain.forEach((box,i)=>{if (checks[i]?.score>=.8) confirmed.add(box);});
      } catch (error) {console.warn('Additional face checks unavailable',error);}
    }
    return candidates.filter(box=>confirmed.has(box));
  }

  // Keep the whole photograph for group engraving, including people the detector might miss.
  function framing(image, boxes, group) {
    const {width:w,height:h} = image;
    if (!group && boxes.length) {
      const b = boxes[0];
      return {cx:b.x,cy:b.y+.04*b.w,px:b.w*.85};
    }
    return {cx:w/2,cy:h/2,px:group ? Math.hypot(w,h)/1.91 : Math.min(w,h)/1.95};
  }

  function soften(src, size, passes) {
    let g = src;
    for (let k = 0; k < passes; k++) {
      const out = g.slice();
      for (let y=1; y<size-1; y++) {
        for (let x=1; x<size-1; x++) {
          const i=y*size+x;
          out[i]=(4*g[i]+2*(g[i-1]+g[i+1]+g[i-size]+g[i+size])
            +g[i-size-1]+g[i-size+1]+g[i+size-1]+g[i+size+1])/16;
        }
      }
      g=out;
    }
    return g;
  }

  // Trace boundaries of foreground pixels, keeping foreground on the right.
  // Remove tiny islands at the resolution of the Mini's steel ball.
  function boundaries(mask, size, minArea) {
    const edges = new Map(), stride = size+1;
    const edge = (a,b) => {
      let out=edges.get(a);
      if (!out) edges.set(a, out=[]);
      out.push(b);
    };
    for (let y=1; y<size-1; y++) for (let x=1; x<size-1; x++) {
      const i=y*size+x;
      if (!mask[i]) continue;
      const a=y*stride+x;
      if (!mask[i-size]) edge(a,a+1);
      if (!mask[i+1]) edge(a+1,a+stride+1);
      if (!mask[i+size]) edge(a+stride+1,a+stride);
      if (!mask[i-1]) edge(a+stride,a);
    }
    const loops=[];
    while (edges.size) {
      const start=edges.keys().next().value;
      let p=start,area=0;
      const contour=[];
      do {
        const next=edges.get(p);
        if (!next || !next.length) break;
        const q=next.pop();
        if (!next.length) edges.delete(p);
        const x=p%stride,y=Math.floor(p/stride);
        area+=x*Math.floor(q/stride)-y*(q%stride);
        contour.push([x,y]); p=q;
      } while (p!==start);
      if (contour.length<9 || p!==start || Math.abs(area)/2 < minArea) continue;
      const smooth=[];
      const n=contour.length, count=Math.ceil(n/2.5);
      for(let k=0;k<count;k++){
        const i=Math.floor(k*n/count), a=contour[(i+n-1)%n], b=contour[i], c=contour[(i+1)%n];
        smooth.push([(a[0]+2*b[0]+c[0])/4,(a[1]+2*b[1]+c[1])/4]);
      }
      loops.push(smooth);
    }
    return loops;
  }

  function engraving(image, frame, group, boxes) {
    const n=GRID, half=n/2;
    const field=new Float32Array(n*n).fill(255);
    const valid=new Uint8Array(n*n);
    const hist=[];
    for(let y=1;y<n-1;y++) for(let x=1;x<n-1;x++){
      const nx=(x+.5-half)/half, ny=(y+.5-half)/half;
      const sx=frame.cx+nx*frame.px, sy=frame.cy+ny*frame.px;
      if(Math.hypot(nx,ny)>.956 || sx<0 || sx>=image.width || sy<0 || sy>=image.height) continue;
      let lum=0;
      const step=frame.px/n*.52;
      for(const dx of [-step,step])for(const dy of [-step,step])lum+=grayAt(image,sx+dx,sy+dy);
      field[y*n+x]=lum/4;valid[y*n+x]=1;hist.push(lum/4);
    }
    hist.sort((a,b)=>a-b);
    const pct=f=>hist[Math.floor((hist.length-1)*f)];
    if(hist.length<25 || pct(.96)-pct(.04)<16) throw Error('Choose a photo with more contrast or crop closer.');
    const sm=soften(field,n,2);
    const masks=[];
    // Quantiles of this photograph keep the face readable in light or dark exposures.
    for (const f of (group ? [.28,.56] : [.20,.44,.68])) {
      const th=pct(f);
      const mask=Float32Array.from(sm,(v,i)=>valid[i] && v<th ? 1 : 0);
      const cleaned=soften(mask,n,2);
      masks.push(Uint8Array.from(cleaned,(v,i)=>valid[i] && v>.5 ? 1 : 0));
    }
    // Group shadows can merge eyes, mouth and hair into one patch. Inside detected
    // faces, trace the strongest small dark marks against that person's own lighting.
    // A person who turns away stays in the full photograph's outlines.
    if(group && boxes.length){
      const broad=soften(sm,n,12), detail=new Uint8Array(n*n);
      for(const b of boxes){
        const cx=half+(b.x-frame.cx)*half/frame.px, cy=half+(b.y-frame.cy)*half/frame.px;
        const box=b.w*half/frame.px;
        if(box<9)continue;
        const samples=[];
        for(let y=Math.max(1,Math.floor(cy-box*.44));y<Math.min(n-1,cy+box*.46);y++){
          for(let x=Math.max(1,Math.floor(cx-box*.39));x<Math.min(n-1,cx+box*.39);x++){
            const u=(x-cx)/box, v=(y-cy)/box;
            if((u/.40)**2+(v/.50)**2 < 1) samples.push([y*n+x,broad[y*n+x]-sm[y*n+x]]);
          }
        }
        if(!samples.length)continue;
        samples.sort((a,b)=>a[1]-b[1]);
        const cut=Math.max(5,samples[Math.floor(.77*(samples.length-1))][1]);
        for(const [i,diff] of samples) if(diff>=cut)detail[i]=1;
      }
      masks.push(detail);
    }
    const loops=masks.flatMap((m,index)=>boundaries(m,n,group ? (index===2 ? 4 : 11) : 8));
    if(!loops.length) throw Error('No clear shapes found. Crop closer to the people and try again.');
    return loops.map(loop=>loop.map(([x,y])=>[(x-half)/half,(half-y)/half]));
  }

  const scriptUrl = document.currentScript && document.currentScript.src;
  let landmarkNet, verifierReady;

  function loadPhotoScript(filename) {
    return new Promise((resolve,reject)=>{
      const script=document.createElement('script');
      script.src=new URL(filename,scriptUrl || document.baseURI).href;
      script.onload=resolve;
      script.onerror=()=>reject(Error('The table could not open its portrait tools. Reload and try again.'));
      document.head.appendChild(script);
    });
  }

  function loadLandmarks() {
    if (!landmarkNet) {
      landmarkNet = (async () => {
        if (!window.loadGuestLandmarks) {
          await loadPhotoScript('guest-landmarks.js');
        }
        return window.loadGuestLandmarks();
      })().catch(err => {landmarkNet=null;throw err;});
    }
    return landmarkNet;
  }

  function loadFaceVerifier() {
    if (!verifierReady) {
      verifierReady=Promise.all([loadLandmarks(),window.GuestFaceVerify ||
        loadPhotoScript('guest-face-verify.js')]).catch(error=>{verifierReady=null;throw error;});
    }
    return verifierReady;
  }

  function detectedFaces(image,analysis) {
    if (!analysis.boxes) {
      analysis.boxes=portraitBoxes(image,analysis.originalFile).catch(error=>{delete analysis.boxes;throw error;});
    }
    return analysis.boxes;
  }

  async function findLandmarks(image, boxes, original) {
    const net=await loadLandmarks();
    const src=document.createElement('canvas');
    src.width=image.width;src.height=image.height;
    src.getContext('2d').putImageData(image,0,0);
    const result=[];
    for(const b of boxes){
      const crop=document.createElement('canvas');crop.width=112;crop.height=112;
      const startX=b.x-b.w*.5,startY=b.y-b.w*.5;
      const ctx=crop.getContext('2d');
      // Sample the original crop directly when shrinking the whole photo
      // would throw away pixels needed by the 112-pixel landmark model.
      const source=original && b.w<112 ? original : src;
      if (b.angle) {
        ctx.translate(56,56); ctx.scale(112/b.w,112/b.w); ctx.rotate(b.angle);
        ctx.drawImage(source,-b.x,-b.y,image.width,image.height);
      } else {
        const sx=(source.naturalWidth || source.width)/image.width;
        const sy=(source.naturalHeight || source.height)/image.height;
        ctx.drawImage(source,startX*sx,startY*sy,b.w*sx,b.w*sy,0,0,112,112);
      }
      const lm=await net.detectLandmarks(crop);
      result.push(lm.positions.map(p=>{
        if (!b.angle) return [startX+p.x*b.w/112,startY+p.y*b.w/112];
        const dx=(p.x-56)*b.w/112,dy=(p.y-56)*b.w/112,c=Math.cos(b.angle),s=Math.sin(b.angle);
        return [b.x+c*dx+s*dy,b.y-s*dx+c*dy];
      }));
    }
    return result;
  }

  function rgb(image,p) {
    const x=clamp(Math.round(p[0]),0,image.width-1),y=clamp(Math.round(p[1]),0,image.height-1);
    const i=(x+y*image.width)*4;
    return [image.data[i],image.data[i+1],image.data[i+2]];
  }
  const colorDistance=(a,b)=>Math.hypot(a[0]-b[0],a[1]-b[1],a[2]-b[2]);
  const mix=(a,b,t)=>[a[0]+(b[0]-a[0])*t,a[1]+(b[1]-a[1])*t];
  const mean=arr=>arr.reduce((v,x)=>v+x,0)/arr.length;

  // Look for a dark frame thin enough that skin is lighter immediately on *both*
  // sides. Use only the lower half for the decision, where brows cannot look like frames.
  function lensOutline(image,eye) {
    const c=[mean(eye.map(p=>p[0])),mean(eye.map(p=>p[1]))];
    const dx=eye[3][0]-eye[0][0],dy=eye[3][1]-eye[0][1];
    function at(a,r) {
      const u=.97*Math.cos(a)*r, v=.67*Math.sin(a)*r+.08;
      return [c[0]+dx*u-dy*v,c[1]+dy*u+dx*v];
    }
    const sizes=[],n=40;
    let visible=0;
    for(let i=0;i<n;i++){
      const a=i*2*Math.PI/n;
      let score=-Infinity,best=1;
      for(let j=0;j<=16;j++){
        const r=.76+j*.03;
        const inner=grayAt(image,...at(a,r-.14)),outer=grayAt(image,...at(a,r+.14));
        const darkness=Math.min(inner,outer)-grayAt(image,...at(a,r));
        if(darkness>score){score=darkness;best=r;}
      }
      if(i<=n/2 && score>17)visible++;
      sizes.push(score>12?best:1);
    }
    if(visible<9)return null;
    return sizes.map((v,i)=>at(i*2*Math.PI/n,(sizes[(i+n-1)%n]+2*v+sizes[(i+1)%n])/4));
  }

  // Follow the dark upper wire to a flared hinge, where the rim turns down
  // around the glass. A continuous bright-to-dark edge must end at both tips.
  function photographedHinges(image,eyes,rims,groovesPerPixel) {
    const centers=eyes.map(eye=>[mean(eye.map(p=>p[0])),mean(eye.map(p=>p[1]))]);
    const origin=mix(...centers,.5),dx=centers[1][0]-centers[0][0],dy=centers[1][1]-centers[0][1];
    const span=Math.hypot(dx,dy),groove=1/groovesPerPixel;
    if(span<42 || span<9*groove)return null;
    const results=rims.map((rim,side)=>{
      const sign=side ? 1 : -1;
      const local=([x,y])=>[sign*((x-origin[0])*dx+(y-origin[1])*dy)/(span*span),
        ((y-origin[1])*dx-(x-origin[0])*dy)/(span*span)];
      const photo=(x,y)=>[origin[0]+sign*x*dx-y*dy,origin[1]+sign*x*dy+y*dx];
      function light(x,y){
        const [px,py]=photo(x,y),ix=Math.floor(px),iy=Math.floor(py),u=px-ix,v=py-iy;
        return (1-v)*((1-u)*grayAt(image,ix,iy)+u*grayAt(image,ix+1,iy))+
          v*((1-u)*grayAt(image,ix,iy+1)+u*grayAt(image,ix+1,iy+1));
      }
      const line=rim.map(local),high=Math.max(...line.map(p=>p[0])),top=Math.min(...line.map(p=>p[1]));
      const start=high-.215,upper=line.filter(([x,y])=>x>=high-.285 && x<=high-.14 && y<top+.16);
      if(!upper.length)return null;
      for(const u of [start,start+.42])for(const v of [top-.07,top+.34]){
        const [x,y]=photo(u,v);
        if(x<2 || y<2 || x>=image.width-2 || y>=image.height-2)return null;
      }
      let last=upper.reduce((a,b)=>Math.abs(a[0]-start)<Math.abs(b[0]-start)?a:b)[1]-.009;
      const samples=[],heights=[];
      for(let i=0;i<36;i++){
        const x=start+i*.012,n=heights.length;
        const slope=n>=2 ? clamp((last-heights[Math.max(0,n-4)])/(.012*Math.min(3,n-1)),-.55,.7) : 0;
        const predicted=last+.012*slope;
        let best=-Infinity,sample;
        for(let j=0;j<43;j++){
          const y=top-.035+.007*j;
          if(Math.abs(y-predicted)>=.029)continue;
          const dark=light(x,y+.012),contrast=light(x,y-.023)-dark;
          const score=contrast-590*Math.abs(y-predicted);
          if(score>best){best=score;sample={y,dark,contrast,point:photo(x,y+.010)};}
        }
        if(!sample)return null;
        last=sample.y;heights.push(last);samples.push(sample);
      }
      const middle=values=>values.sort((a,b)=>a-b)[Math.floor(values.length/2)];
      const reference=middle(samples.slice(0,9).map(p=>p.dark));
      const good=samples.map(p=>p.contrast>16 && p.dark<reference+32);
      // An upper line ending in hair or a reflection has no observed end.
      // Require a sustained dark run and lighter material just beyond it.
      let stop=2;
      while(stop<good.length-1 && (good[stop] || good[stop+1]))stop++;
      let tip=stop-1;
      while(tip>=0 && !good[tip])tip--;
      if(start+.012*tip<high+.025 || stop>good.length-3 || good.slice(0,tip+1).filter(Boolean).length<.84*(tip+1) ||
         middle(samples.slice(stop,stop+3).map(p=>p.dark))<reference+24)return null;
      const points=samples.slice(0,tip+1).map(p=>p.point),end=points.at(-1);
      if(Math.min(...rim.map(p=>Math.hypot(p[0]-end[0],p[1]-end[1])))<1.15*groove)return null;
      // Revisit the same wire when returning from the hinge. A direct
      // diagonal from its tip to the lower rim would cut across the lens.
      let vertex=-1,join=-1;
      for(const [k,p] of rim.entries()){
        for(let j=join+1;j<points.length-3;j++){
          const q=points[j];
          if(Math.hypot(p[0]-q[0],p[1]-q[1])<=.48*groove){vertex=k;join=j;}
        }
      }
      if(vertex<0)return null;
      const tail=points.slice(join+1);
      return [...rim.slice(0,vertex+1),...tail,...tail.slice(0,-1).reverse(),...rim.slice(vertex)];
    });
    return results.every(Boolean) ? results : null;
  }

  // A thin upper rim can be much darker than the transparent lower rim. Look
  // for the narrow bridge across the nose and two descending inner rims first.
  function thinFrames(image, L) {
    const eyes=[L.slice(36,42),L.slice(42,48)].map(eye=>[mean(eye.map(p=>p[0])),mean(eye.map(p=>p[1]))]);
    const center=mix(...eyes,.5), dx=eyes[1][0]-eyes[0][0], dy=eyes[1][1]-eyes[0][1];
    const separation=Math.hypot(dx,dy);
    if(separation<40)return null;
    const at=(u,v)=>[center[0]+dx*u-dy*v,center[1]+dy*u+dx*v];
    const light=(u,v)=>grayAt(image,...at(u,v));
    const nx=((L[27][0]-center[0])*dx+(L[27][1]-center[1])*dy)/(separation**2);
    const ny=(-(L[27][0]-center[0])*dy+(L[27][1]-center[1])*dx)/(separation**2);
    let bridge;
    for(const x of [nx-.04,nx,nx+.04])for(let j=-19;j<=9;j++)for(const slope of [-.12,0,.12]){
      const y=ny+j*.01, contrast=[];
      for(let k=-4;k<=4;k++){
        const u=k*.01875,v=y+slope*u;
        contrast.push(Math.min(light(x+u,v-.045),light(x+u,v+.045))-light(x+u,v));
      }
      contrast.sort((a,b)=>a-b);
      const score=contrast[2]+.25*mean(contrast);
      if(!bridge || score>bridge.score)bridge={x,y,slope,score};
    }
    if(bridge.score<26)return null;
    const lenses=[], junctions=[];
    for(const sign of [-1,1]){
      let rail;
      for(let j=0;j<24;j++)for(let k=-4;k<=4;k++){
        const x=bridge.x+sign*(.055+j*.008), slope=k*.1, contrast=[];
        for(let i=0;i<8;i++){
          const v=.025+i*.145/7,u=x+slope*v,y=bridge.y+v;
          contrast.push(Math.min(light(u-.04,y),light(u+.04,y))-light(u,y));
        }
        contrast.sort((a,b)=>a-b);
        const score=mean(contrast)+.4*contrast[2]-45*Math.abs(x-bridge.x-sign*.13);
        if(!rail || score>rail.score)rail={x,slope,score};
      }
      if(rail.score<16)return null;

      // Follow the actual rim around each eye. Bound changes between successive
      // rays so one eyelash or specular glint cannot pull a lens onto the eye.
      const cu=rail.x+sign*.39,cv=bridge.y+.095, steps=48, levels=36;
      const r0=.59,dr=.025,anchor=sign<0?0:steps/2;
      const candidates=[],parents=[],first=clamp(Math.round((Math.abs(cu-rail.x-rail.slope*.095)/.405-r0)/dr),0,levels-1);
      let previous=new Float64Array(levels).fill(-Infinity);
      for(let k=0;k<steps;k++){
        const angle=(k+anchor)*Math.PI*2/steps,cos=Math.cos(angle),sin=Math.sin(angle);
        const u=.405*Math.sign(cos)*Math.abs(cos)**.76,v=.298*Math.sign(sin)*Math.abs(sin)**.76;
        const probe=.029/Math.hypot(u,v),du=u*probe,dv=v*probe;
        const row=[],links=new Int8Array(levels),next=new Float64Array(levels).fill(-Infinity);
        for(let j=0;j<levels;j++){
          const r=r0+dr*j,x=cu+u*r,y=cv+v*r;
          const inside=light(x-du,y-dv),outside=light(x+du,y+dv),on=light(x,y);
          const contrast=Math.max(Math.min(inside,outside)-on,.52*(on-Math.max(inside,outside)));
          row.push({point:at(x,y),contrast});
          const evidence=Math.min(contrast,60)+.13*Math.min(Math.abs(inside-outside),60)-Math.abs(r-1)*45;
          if(!k){if(j===first)next[j]=evidence;continue;}
          for(let t=Math.max(0,j-4);t<=Math.min(levels-1,j+4);t++){
            const score=previous[t]+evidence-4.5*Math.abs(t-j);
            if(score>next[j]){next[j]=score;links[j]=t;}
          }
        }
        candidates.push(row);parents.push(links);previous=next;
      }
      let index=first;
      for(let j=Math.max(0,first-4);j<=Math.min(levels-1,first+4);j++){
        if(previous[j]-4.5*Math.abs(j-first)>previous[index]-4.5*Math.abs(index-first))index=j;
      }
      const rim=[];let lower=0,upper=0;
      for(let k=steps-1;k>=0;k--){
        const i=(k+anchor)%steps,{point,contrast}=candidates[k][index];
        rim[i]=point;
        if(i<steps/2 && contrast>7)lower++;
        if(i>=steps/2 && contrast>15)upper++;
        index=parents[k][index];
      }
      if(lower<8 || upper<12)return null;
      const junction=at(rail.x,bridge.y+bridge.slope*(rail.x-bridge.x));
      // Remove sampling jitter along skinny wire while keeping the measured corners.
      const smooth=rim.map((p,i)=>mix(p,mix(rim[(i+steps-1)%steps],rim[(i+1)%steps],.5),.5));
      lenses.push(smooth);junctions.push(junction);
    }
    return {lenses,junctions};
  }

  // Recover a hair band when the strongest edge was the hairline and the
  // initial portrait consequently has no hair. Look for a second edge beyond
  // material with hair texture or a continuous dark interior. A smooth scalp
  // against a detailed wall can also have two color edges on isolated rays.
  function recoverCrown(image, ray, skinColors, count) {
    const colorAt = (angle, r) => rgb(image, ray(angle, r));
    const skinDistance = color => Math.min(...skinColors.map(skin => colorDistance(color, skin)));
    const median = values => values.sort((a, b) => a-b)[Math.floor(values.length/2)];
    function edge(angle, r) {
      return median([-.04, 0, .04].map(delta =>
        colorDistance(colorAt(angle+delta, r-.045), colorAt(angle+delta, r+.045))));
    }
    function texture(angle, inner, outer) {
      const values = [];
      for (const fraction of [.25, .4, .57, .75]) {
        const r = inner + fraction*(outer-inner);
        for (const delta of [-.04, -.02, 0, .02, .04]) {
          const [x,y] = ray(angle+delta, r);
          const local = (grayAt(image,x-2,y) + grayAt(image,x+2,y) +
                         grayAt(image,x,y-2) + grayAt(image,x,y+2))/4;
          values.push(Math.abs(grayAt(image,x,y) - local));
        }
      }
      return median(values);
    }
    const samples = [];
    const textures = [];
    for (let i = 0; i < count; i++) {
      const angle = Math.PI*i/(count-1);
      let best = null, score = 0;
      // Reuse the outer-edge evidence across all hairline candidates on this ray.
      const rims = [];
      for (let r = 1; r < 1.8; r += .035) {
        const strength = edge(angle,r);
        if (strength >= 20) rims.push({r, strength});
      }
      for (let h = .54; h < 1.15; h += .035) {
        const strength = edge(angle,h);
        if (strength < 22) continue;
        const skin = colorAt(angle,h-.08);
        const distance = skinDistance(skin);
        if (distance > 80 || skinDistance(colorAt(angle,h+.08)) < distance+14) continue;
        for (const rim of rims) {
          if (rim.r < h+.17) continue;
          const middle = colorAt(angle,(h+rim.r)/2);
          if (skinDistance(middle) < 30 || colorDistance(middle,skin) < 28) continue;
          const merit = Math.min(strength,85) + Math.min(rim.strength,80) -
                        27*Math.abs(rim.r-1.25) - 16*Math.abs(h-.88);
          if (merit > score) {
            score = merit;
            best = {inner:h, outer:rim.r};
          }
        }
      }
      samples.push(best);
      if (best && i >= 4 && i < count-4) textures.push(texture(angle,best.inner,best.outer));
    }
    if (textures.length < (count-8)*.56) return null;
    if (median(textures) <= 4.4) {
      // Pulled-back hair or a straight fringe can be smooth. Require two
      // distinct edges around a dark band on most rays across the forehead.
      // Isolated shadows on bare scalps do not form a continuous band.
      const dark=samples.slice(4,-4).filter((sample,i)=>{
        if (!sample || sample.outer-sample.inner<.19) return false;
        const angle=Math.PI*(i+4)/(count-1);
        const inner=colorAt(angle,sample.inner-.08);
        const band=colorAt(angle,(sample.inner+sample.outer)/2);
        const light=c=>.30*c[0]+.59*c[1]+.11*c[2];
        return light(inner)-light(band)>52 && skinDistance(band)-skinDistance(inner)>44 &&
          edge(angle,sample.outer)>25;
      });
      if (dark.length < (count-8)*.75) return null;
    }
    return samples.map((_,i) => {
      const near = samples.slice(Math.max(0,i-2),i+3).filter(Boolean);
      if (near.length < 2) return null;
      const angle = Math.PI*i/(count-1);
      const outer = median(near.map(s => s.outer));
      const refs = [.38,.46,.54].map(r => colorAt(angle,r));
      const distance = r => median([-.03,0,.03].map(delta => {
        const color = colorAt(angle+delta,r);
        return Math.min(...refs.map(ref => colorDistance(color,ref)));
      }));
      let inner = median(near.map(s => s.inner));
      for (let r=.52; r<outer-.10; r+=.025) {
        if(distance(r)>44 && distance(r+.06)>44 && distance(r+.12)>44) {
          inner = r;
          break;
        }
      }
      return {inner, outer};
    });
  }

  // The 68 landmarks supply the real chin, cheek widths, head tilt, eye and mouth geometry.
  // Sample the photo across the upper head to find its crown, hairline and beard edge.
  function portraitShapes(image,L,group,minimumCrownWidth=120) {
    const origin=mix(L[0],L[16],.5),dx=L[16][0]-L[0][0],dy=L[16][1]-L[0][1];
    const width=Math.hypot(dx,dy);
    const at=(u,v)=>[origin[0]+dx*u-dy*v,origin[1]+dy*u+dx*v];
    const local=p=>[((p[0]-origin[0])*dx+(p[1]-origin[1])*dy)/(width*width),
      (-(p[0]-origin[0])*dy+(p[1]-origin[1])*dx)/(width*width)];
    const chin=local(L[8]);
    const skinSamples=[mix(L[2],L[31],.55),mix(L[14],L[35],.55),mix(L[21],L[22],.5)];
    for(const i of [18,19,20,23,24,25]){
      const [x,y]=local(L[i]);
      for(const delta of [.08,.14,.20])skinSamples.push(at(x,y-delta));
    }
    const cheek=skinSamples.map(p=>rgb(image,p));
    const luminance=c=>.30*c[0]+.59*c[1]+.11*c[2];
    const skinDist=p=>{
      const c=rgb(image,p),y=luminance(c);
      return Math.min(...cheek.map(ref=>{
        const v=luminance(ref);
        return Math.hypot((c[0]-y)-(ref[0]-v),(c[2]-y)-(ref[2]-v),.36*(y-v));
      }));
    };
    const rays=25, radii=[], starts=[];
    function ray(t,r){return at(.51*Math.cos(t)*r,-.66*Math.sin(t)*r);}
    for(let i=0;i<rays;i++){
      const t=Math.PI*i/(rays-1);
      let best=.97,score=-Infinity;
      for(let k=0;k<=24;k++){
        const r=.78+.022*k;
        const diff=colorDistance(rgb(image,ray(t,r-.04)),rgb(image,ray(t,r+.04)));
        const merit=Math.min(diff,150)-130*Math.abs(r-.99);
        if(merit>score){score=merit;best=r;}
      }
      if(group){
        // A dark hairline is often a stronger edge than the crown against the wall.
        // Search beyond it for the outermost coherent edge over several adjacent rays.
        let outer=-Infinity;
        for(let k=0;k<=24;k++){
          const r=.99+.022*k;
          const deltas=[-.05,0,.05].map(dt=>colorDistance(rgb(image,ray(t+dt,r-.035)),rgb(image,ray(t+dt,r+.035))));
          deltas.sort((a,b)=>a-b);
          const merit=deltas[1]-26*Math.abs(r-1.14);
          if(merit>13 && merit>outer*.70){outer=Math.max(outer,merit);best=r;}
        }
      }
      radii.push(best);
    }
    const crown=[], hairline=[];
    for(let i=0;i<rays;i++){
      const t=Math.PI*i/(rays-1),r=(radii[Math.max(0,i-1)]+2*radii[i]+radii[Math.min(rays-1,i+1)])/4;
      const edge=ray(t,r);
      crown.push(edge);
      let skinEnd=.69;
      for(let k=0;k<13;k++){
        const f=.965-.024*k;
        if(skinDist(ray(t,r*f))<18 && skinDist(ray(t,r*(f-.04)))<18){
          skinEnd=f;break;
        }
      }
      if(group){
        const refs=cheek.slice(0,3);
        const previousDist=q=>Math.min(...refs.map(c=>colorDistance(rgb(image,q),c)));
        skinEnd=.96;
        for(let k=0;k<=17;k++){
          const f=.48+.027*k;
          if(previousDist(ray(t,r*f))>43 && previousDist(ray(t,r*(f+.055)))>43){skinEnd=f;break;}
        }
      }
      starts.push(skinEnd);
    }
    for(let i=0;i<rays;i++){
      const f=(starts[Math.max(0,i-1)]+2*starts[i]+starts[Math.min(rays-1,i+1)])/4;
      hairline.push(mix(origin,crown[i],f));
    }
    const hasHair=mean(starts.slice(5,20)) < (group ? .86 : .91);
    // The fine texture test requires a face resolved in the source photograph.
    const recovered = !group && !hasHair && width >= minimumCrownWidth
      ? recoverCrown(image, ray, cheek.slice(0,3), rays) : null;
    if (recovered) {
      for (const [i,sample] of recovered.entries()) {
        if (!sample) continue;
        const angle = Math.PI*i/(rays-1);
        const blend = clamp(Math.min(i,rays-1-i)/4,0,1);
        crown[i] = mix(crown[i],ray(angle,sample.outer),blend);
        const left = recovered[Math.max(0,i-1)] || sample;
        const right = recovered[Math.min(rays-1,i+1)] || sample;
        const inner = (left.inner + 2*sample.inner + right.inner)/4;
        hairline[i] = mix(hairline[i],ray(angle,inner),blend);
      }
    }
    const head=[...L.slice(0,17),...crown];
    const hair=(hasHair || recovered) ? [...crown,...hairline.slice().reverse()] : [];
    const eyes=[L.slice(36,42),L.slice(42,48)];
    const mouth=L.slice(48,60);
    const lens=eyes.map(e=>lensOutline(image,e));
    const complete=lens.every(Boolean);
    const frames=complete?null:thinFrames(image,L);
    const glasses=complete?lens:(frames?.lenses || []);
    const frameBridge=frames?.junctions;
    const sideHair=[];
    if(hasHair){
      const hairSamples=crown.slice(5,20).map((p,i)=>rgb(image,mix(hairline[i+5],p,.55)));
      const yRef=mean(cheek.map(luminance));
      for(const sign of [-1,1]){
        const outer=[],inner=[];
        for(let j=0;j<=18;j++){
          const v=-.22+j*.055;
          const left=clamp(.40-Math.max(v,0)*.14,.27,.40);
          const found=[];
          for(let k=0;k<25;k++){
            const u=left+k*.017, p=at(sign*u,v), c=rgb(image,p);
            if(luminance(c)<yRef-35 && skinDist(p)>20 && Math.min(...hairSamples.map(ref=>colorDistance(c,ref)))<68)found.push(u);
          }
          if(found.length<4){ if(outer.length>4)break;continue; }
          const depth=outer.length;
          const easeIn=Math.min(1,(depth+1)/5);
          const begin=Math.min(...found),end=begin+easeIn*(Math.max(...found)-begin);
          outer.push(at(sign*end,v));inner.push(at(sign*begin,v));
        }
        if(outer.length>=12){
          const end=outer.length-1,hairEnd=mix(outer[end],inner[end],.48);
          const tip=[hairEnd[0]+dx*sign*.03-dy*.09,hairEnd[1]+dy*sign*.03+dx*.09];
          // The visible locks taper away from the ear. Angle the lower turn in towards the chin.
          const envelope=outer.map((pt,i)=>{
            const edge=Math.min(1,(end-i+1)/4);
            return mix(inner[i],pt,edge);
          });
          const smoothed=envelope.map((pt,i)=>i&&i<end?mix(pt,mix(envelope[i-1],envelope[i+1],.5),.6):pt);
          sideHair.push([...smoothed,tip,...inner.reverse()]);
        }
      }
    }
    const saturation=c=>Math.hypot(c[0]-luminance(c),c[2]-luminance(c));
    const avgPatch=p=>{
      const colors=[];
      for(const u of [-.025,0,.025])for(const v of [-.022,0,.022]){
        colors.push(rgb(image,[p[0]+u*width,p[1]+v*width]));
      }
      return mean(colors.map(saturation));
    };
    const cheekColor=mean([avgPatch(skinSamples[0]),avgPatch(skinSamples[1])]);
    const chinColor=mean([.28,.43,.57,.72].map(t=>avgPatch(mix(L[57],L[8],t))));
    const beard=chinColor<cheekColor*.83 && cheekColor>8;
    let goatee=[];
    if(beard){
      const bottom=mix(L[8],L[57],.045);
      goatee=[mix(L[48],L[4],.22),mix(L[48],L[33],.26),mix(L[54],L[33],.26),mix(L[54],L[12],.22),
        mix(L[12],L[54],.52),mix(L[10],L[55],.18),bottom,mix(L[6],L[59],.18),mix(L[4],L[48],.52)];
    }
    const noseLine=[L[31],L[32],L[33],L[34],L[35]];
    const brows=[L.slice(17,22),L.slice(22,27)];
    const jawLeft=local(L[4]), jawRight=local(L[12]);
    // The collar joins each head to its shoulders. Keep some measured left/right asymmetry.
    const left=jawLeft[0]-.53,right=jawRight[0]+.53;
    const bottom=chin[1]+.43;
    const clothing=[L[4],L[5],L[6],L[7],L[8],L[9],L[10],L[11],L[12],
      at(jawRight[0]-.02,chin[1]+.08),at(right-.14,chin[1]+.20),at(right, bottom-.08),at(right,bottom),
      at(left,bottom),at(left,bottom-.08),at(left+.14,chin[1]+.20),at(jawLeft[0]+.02,chin[1]+.08)];
    return {head,hair,sideHair,goatee,glasses,frameBridge,eyes,mouth,noseLine,brows,clothing,width,recoveredHair:!!recovered};
  }

  // Learn foreground colors from the clothing under each chin and background colors
  // from above the heads. This traces actual shoulders, crossed hands, and high-contrast
  // clothing details. A headshot with too little clothing or separation uses the busts.
  function groupClothes(image,people,landmarks) {
    const bodies=landmarks.map((L,i)=>({x:L[8][0],y:L[8][1],w:people[i].width,
      top:Math.min(...people[i].head.map(p=>p[1])),
      skin:[mix(L[2],L[31],.58),mix(L[14],L[35],.58),L[30]].map(p=>rgb(image,p))}));
    const w=image.width,h=image.height;
    const left=Math.max(0,Math.min(...bodies.map(b=>b.x-1.70*b.w)));
    const right=Math.min(w-1,Math.max(...bodies.map(b=>b.x+1.70*b.w)));
    const top=Math.max(0,Math.min(...bodies.map(b=>b.y-.25*b.w)));
    const bottom=Math.min(h-1,Math.max(...bodies.map(b=>b.y+2.8*b.w)));
    if(bottom-top<8 || right-left<12)return null;
    const lum=c=>.30*c[0]+.59*c[1]+.11*c[2];
    const tone=c=>{const y=lum(c);return [(c[0]-y)*1.15,(c[2]-y)*1.15,y*.55];};
    const diff=(a,b)=>(a[0]-b[0])**2+(a[1]-b[1])**2+(a[2]-b[2])**2;
    const nearest=(c,set)=>Math.min(...set.map(b=>diff(c,b)));
    const cloth=[],back=[],skin=bodies.flatMap(b=>b.skin.map(tone));
    for(const b of bodies){
      for(const dy of [.38,.58,.86,1.14])for(const dx of [-.42,-.2,.13,.37]){
        const x=b.x+dx*b.w,y=b.y+dy*b.w;
        if(x>=0 && x<w && y<h){
          const sample=tone(rgb(image,[x,y]));
          if(nearest(sample,skin)>280)cloth.push(sample);
        }
      }
      for(const dx of [-1.03,-.7,0,.7,1.03])for(const dy of [.10,.28,.43]){
        const x=b.x+dx*b.w,y=b.top-dy*b.w;
        if(x>=0 && x<w && y>=0)back.push(tone(rgb(image,[x,y])));
      }
    }
    // The wall can change color at shoulder height. Learn the strip between heads too.
    const smallest=Math.min(...bodies.map(b=>b.w));
    for(let sx=left;sx<=right;sx+=Math.max(4,smallest*.27)){
      for(let sy=top;sy<top+.7*smallest;sy+=Math.max(3,smallest*.12)){
        if(bodies.every(b=>Math.abs(sx-b.x)>.68*b.w && sy<b.y+.23*b.w)){
          back.push(tone(rgb(image,[sx,sy])));
        }
      }
    }
    if(cloth.length<6 || back.length<3)return null;
    const n=135,step=Math.max(right-left,bottom-top)/(n-4);
    const point=(x,y)=>[left+(x-2)*step,top+(y-2)*step];
    const garment=new Float32Array(n*n),hand=new Float32Array(n*n),gray=new Float32Array(n*n);
    let distinct=0,seeds=0;
    for(let y=1;y<n-1;y++)for(let x=1;x<n-1;x++){
      const [sx,sy]=point(x+.5,y+.5),i=y*n+x;
      if(sx<left||sx>=right||sy<top||sy>=bottom)continue;
      const nearby=bodies.filter(b=>{
        const v=(sy-b.y)/b.w;
        return v>=-.23 && v<=3.40 && Math.abs(sx-b.x)/b.w<Math.min(1.78,.30+Math.max(0,v+.07)*1.95);
      });
      if(!nearby.length)continue;
      const color=rgb(image,[sx,sy]),value=tone(color),fore=nearest(value,cloth),bg=nearest(value,back);
      const skinScore=nearest(value,skin);
      const interior=nearby.some(b=>sy>b.y+b.w*.18 && Math.abs(sx-b.x)<b.w*.62);
      if(interior){seeds++;if(bg>fore+130)distinct++;}
      // A hand on a sleeve counts as foreground even though its color differs from the cloth.
      const visibleSkin=skinScore<270 && skinScore<fore*.72;
      // Skin below the chin is the neck, never the sky visible between heads.
      const onNeck=visibleSkin && nearby.some(b=>sy>=b.y-.17*b.w && sy<b.y+.49*b.w && Math.abs(sx-b.x)<.34*b.w);
      const onArms=visibleSkin && nearby.some(b=>sy>b.y+.65*b.w);
      const exposedSkin=skinScore<480 && nearby.every(b=>Math.abs(sx-b.x)>.32*b.w || sy>b.y+.52*b.w);
      if((!exposedSkin && fore<1400 && fore<(interior?bg+200:bg*.70)) || onNeck || onArms){
        garment[i]=1;hand[i]=onArms?1:0;gray[i]=lum(color);
      }
    }
    if(seeds<25 || distinct/seeds<.39)return null;
    const cut=(data,passes,level)=>Uint8Array.from(soften(data,n,passes),v=>v>=level?1:0);
    const bodyMask=cut(garment,3,.48);
    function area(poly){return poly.reduce((v,a,i)=>{const b=poly[(i+1)%poly.length];return v+a[0]*b[1]-a[1]*b[0];},0)/2;}
    const big=boundaries(bodyMask,n,40).filter(p=>area(p)>0).sort((a,b)=>area(b)-area(a));
    if(!big.length || area(big[0])<80)return null;
    // Smooth only the data within clothing so the artificial image border cannot become a seam.
    const blurred=soften(gray,n,25),coverage=soften(garment,n,25);
    const light=new Float32Array(n*n),dark=new Float32Array(n*n);
    for(let i=0;i<gray.length;i++)if(garment[i] && !hand[i] && coverage[i]>.48){
      const delta=gray[i]-blurred[i]/coverage[i];
      if(delta>23)light[i]=1;
      if(delta< -15)dark[i]=1;
    }
    const regions=(data,level,minimum,limit)=>boundaries(cut(data,2,level),n,minimum)
      .filter(p=>area(p)>0).sort((a,b)=>area(b)-area(a)).slice(0,limit);
    const hands=regions(hand,.44,8,people.length).filter(poly=>{
      const y=mean(poly.map(p=>point(...p)[1]));
      return bodies.some(b=>y>b.y+.64*b.w);
    });
    // Long folds and sleeve edges can separate two coats of the same color. Trace
    // non-maximum gradient ridges at sand resolution; ordinary camera texture falls away.
    const blur=soften(gray,n,3),weights=soften(garment,n,3);
    const field=Float32Array.from(blur,(v,i)=>weights[i]>.2?v/weights[i]:0);
    const mag=new Float32Array(n*n),gx=new Float32Array(n*n),gy=new Float32Array(n*n);
    const edge=new Uint8Array(n*n);
    for(let y=2;y<n-2;y++)for(let x=2;x<n-2;x++){
      const i=y*n+x;
      if(weights[i]<.90)continue;
      gx[i]=field[i+1]-field[i-1];gy[i]=field[i+n]-field[i-n];
      mag[i]=Math.hypot(gx[i],gy[i]);
    }
    for(let i=n+1;i<n*n-n-1;i++){
      if(mag[i]<6)continue;
      const horizontal=Math.abs(gx[i])>2.414*Math.abs(gy[i]);
      const vertical=Math.abs(gy[i])>2.414*Math.abs(gx[i]);
      const offset=horizontal?1:vertical?n:(gx[i]*gy[i]>0?n+1:n-1);
      if(mag[i]>=mag[i-offset] && mag[i]>=mag[i+offset])edge[i]=1;
    }
    const taken=new Uint8Array(n*n),seams=[];
    function follow(start,sign){
      const line=[];
      let i=start,dx=-sign*gy[i]/mag[i],dy=sign*gx[i]/mag[i];
      while(true){
        const x=i%n,y=Math.floor(i/n);
        let next=-1,merit=0;
        for(let yy=-2;yy<=2;yy++)for(let xx=-2;xx<=2;xx++){
          const len=Math.hypot(xx,yy);
          if(!len||len>2.3)continue;
          const q=(y+yy)*n+x+xx;
          if(!edge[q]||taken[q])continue;
          const alignment=(dx*xx+dy*yy)/len;
          const along=Math.abs((-gy[q]*xx+gx[q]*yy)/(mag[q]*len));
          const score=alignment>.43 && along>.47?(alignment+along)*Math.min(22,mag[q])/len:0;
          if(score>merit){merit=score;next=q;}
        }
        if(next<0)break;
        const nx=next%n,ny=Math.floor(next/n),len=Math.hypot(nx-x,ny-y);
        dx=(nx-x)/len;dy=(ny-y)/len;i=next;taken[i]=1;line.push([nx+.5,ny+.5]);
      }
      return line;
    }
    const ordered=Array.from({length:n*n},(_,i)=>i).filter(i=>edge[i]).sort((a,b)=>mag[b]-mag[a]);
    for(const i of ordered){
      if(taken[i])continue;
      taken[i]=1;
      const line=[...follow(i,-1).reverse(),[i%n+.5,Math.floor(i/n)+.5],...follow(i,1)];
      if(line.length<6)continue;
      const points=line.map(q=>point(...q)),a=points[0],b=points[points.length-1],
        length=points.slice(1).reduce((s,q,k)=>s+Math.hypot(q[0]-points[k][0],q[1]-points[k][1]),0);
      const travel=Math.hypot(b[0]-a[0],b[1]-a[1]);
      const p=points[Math.floor(line.length/2)];
      const owner=bodies.reduce((best,b,j)=>Math.abs(p[0]-b.x)/b.w < Math.abs(p[0]-bodies[best].x)/bodies[best].w?j:best,0);
      if(length<bodies[owner].w*.4 || travel<length*.47)continue;
      // Keep long seams in the body of a coat rather than stitching along its collar rim.
      if(p[1]<bodies[owner].y+.42*bodies[owner].w)continue;
      seams.push({owner,points,score:travel*Math.min(1.4,Math.sqrt(mag[i]/16))});
    }
    const counts=bodies.map(()=>0);
    const selected=seams.sort((a,b)=>b.score-a.score).filter(s=>counts[s.owner]++<2);
    const marks=[...hands,...regions(light,.43,9,people.length),...regions(dark,.55,18,2)];
    const world=p=>p.map(([x,y])=>point(x,y));
    return {shape:big.slice(0,people.length).map(world),marks:marks.map(world),
      seams:selected.map(s=>s.points),bottom};
  }

  // At Mini size the upper and lower edges of a broad smile can merge. Trace
  // the lower edge of the visible opening and approach it along a smile fold.
  function compactSmile(image, L, person, groovesPerPixel) {
    if (!groovesPerPixel || person.goatee.length || (person.glasses.length && !person.frameBridge)) return null;
    const distance=(a,b)=>Math.hypot(a[0]-b[0],a[1]-b[1]);
    const gap=distance(L[62],L[66]);
    if (gap < .18*distance(L[48],L[54]) || gap*groovesPerPixel >= 2.1 ||
        person.eyes.some(eye=>Math.max(distance(eye[1],eye[5]),distance(eye[2],eye[4]))*groovesPerPixel >= 1.25)) return null;
    const probe=Math.max(1,Math.round(person.width*.025));
    const folds=[0,1].map(side=>{
      const wing=L[side?35:31], corner=L[side?64:60], length=distance(wing,corner);
      const nx=(wing[1]-corner[1])/(length||1), ny=(corner[0]-wing[0])/(length||1);
      const points=[wing];
      let score=0;
      for(let j=1;j<6;j++){
        const t=j/6, mid=mix(wing,corner,t);
        let darkest=-Infinity, best=mid;
        for(let k=-4;k<=4;k++){
          const offset=k*.011*person.width*Math.sin(t*Math.PI);
          const x=mid[0]+nx*offset, y=mid[1]+ny*offset;
          const flank=Math.min(grayAt(image,x-nx*probe,y-ny*probe),grayAt(image,x+nx*probe,y+ny*probe));
          const contrast=flank-grayAt(image,x,y)-1.6*Math.abs(k);
          if(contrast>darkest){darkest=contrast;best=[x,y];}
        }
        score+=darkest;points.push(best);
      }
      const lowerLip=side?[L[64],L[65],L[66],L[67],L[60]]:[L[60],L[67],L[66],L[65],L[64]];
      return {side,points:[...points,...lowerLip],score:score/5-length*.13};
    });
    return folds[0].score>folds[1].score?folds[0]:folds[1];
  }

  // Wide seated smiles have room for the photographed mouth opening. Fit two
  // broad arcs through its corners; individual teeth never become strokes.
  function photographedSmile(image, L, groovesPerPixel, tracking, outerLowerLip=false, requireObserved=false) {
    const left=L[48], right=L[54], dx=right[0]-left[0], dy=right[1]-left[1];
    const width=Math.hypot(dx,dy);
    const point=(u,v)=>[left[0]+u*dx-v*dy,left[1]+u*dy+v*dx];
    const coords=([x,y])=>[((x-left[0])*dx+(y-left[1])*dy)/width**2,
                           ((y-left[1])*dx-(x-left[0])*dy)/width**2];
    const arch=u=>(4*u*(1-u))**.72;
    const light=(u,v)=>grayAt(image,...point(u,v));
    const lipColor=(u,v)=>{
      const [x,y]=point(u,v);
      const i=4*(clamp(Math.round(y),0,image.height-1)*image.width+clamp(Math.round(x),0,image.width-1));
      const rgba=image.data, r=rgba[i], g=rgba[i+1], b=rgba[i+2], a=rgba[i+3];
      return [255+(.299*r+.587*g+.114*b-255)*a/255,(r-.63*g-.37*b)*a/255];
    };
    function margin(u,v,upper) {
      if(upper) {
        // The narrow shadow where the upper lip meets the opening. A strong
        // change in color alone can pick the bright teeth below the gum.
        const seam=(light(u,v-.008)+light(u,v)+light(u,v+.008))/3;
        const above=(light(u,v-.04)+light(u,v-.065))/2;
        const below=(light(u,v+.035)+light(u,v+.065))/2;
        return Math.min(above,below)-seam;
      }
      // A lower lip can border either bright teeth or a dark mouth. Measure
      // the change in brightness and the redder lip just outside the opening.
      let brightness=0, redness=0;
      for(const offset of [.018,.035]){
        const outside=lipColor(u,v+offset), inside=lipColor(u,v-offset);
        brightness+=(outside[0]-inside[0])/2;
        redness+=(outside[1]-inside[1])/2;
      }
      // At the outside edge of the lower lip the skin gets less red. This
      // gives a second real contour when the tooth opening is too narrow.
      if(outerLowerLip)return .45*clamp(brightness,-60,60)-clamp(redness,-70,50);
      return .45*Math.min(70,Math.abs(brightness))+clamp(redness,-50,70);
    }
    function fit(indices, upper, fitsOpening=null) {
      const marks=indices.map(i=>coords(L[i]));
      if(marks.some(([u],i)=>u<.04 || u>.96 || (i && u<=marks[i-1][0])))return null;
      const [middle,height]=marks[1], initial=height/arch(middle);
      const cuts=Array.from({length:15},(_,i)=>.08+i*.06);
      let best=null;
      for(let lift=-6;lift<=6;lift++)for(let lean=-5;lean<=5;lean++){
        const level=initial+lift*.015, tilt=lean*.03;
        const depth=u=>arch(u)*(level+tilt*(2*u-1));
        if(fitsOpening && !fitsOpening(depth))continue;
        const offsets=marks.map(([u,v])=>Math.abs(v-depth(u)));
        if(Math.max(...offsets)>.12)continue;
        const scores=cuts.map(u=>margin(u,depth(u),upper)).sort((a,b)=>a-b);
        const quality=.68*mean(scores)+.32*scores[4]-35*mean(offsets);
        if(!best || quality>best.quality)best={depth,quality};
      }
      return best && best.quality>=(upper?8:15) ? best.depth : null;
    }
    const bottom=fit(outerLowerLip ? [58,57,56] : [67,66,65],false);
    if(!bottom)return null;
    // Allow both strokes to drift inward and leave a quarter groove of open sand.
    const fitsOpening=top=>[.42,.5,.58].every(u=>
      (bottom(u)-top(u))*width*groovesPerPixel>=1.25+2*tracking);
    let top=fit([61,62,63],true,fitsOpening);
    if(!top){
      if(requireObserved)return null;
      // Even when the gum obscures the upper margin, a clear lower lip can
      // be used with the measured upper outline if the opening stays legible.
      const guides=[[0,0],...L.slice(61,64).map(coords),[1,0]];
      if(guides.some(([u],i)=>i && u<=guides[i-1][0]))return null;
      top=u=>{
        const i=guides.slice(1).findIndex(([end])=>end>=u);
        const [a,y]=guides[i], [b,z]=guides[i+1];
        return y+(z-y)*(u-a)/(b-a);
      };
      if(!fitsOpening(top))return null;
    }
    const stations=Array.from({length:25},(_,i)=>i/24);
    if(stations.some(u=>bottom(u)<top(u)))return null;
    const upper=stations.map(u=>point(u,top(u))), lower=stations.map(u=>point(u,bottom(u)));
    return [...upper.slice(12),...lower.slice(0,-1).reverse(),...upper.slice(1,13)];
  }

  // Compare both photographed lip margins with the original opening at the
  // same columns. A smile needs a visible band of teeth between them.
  function photographedShadowSmile(image,L,groovesPerPixel,tracking) {
    const measured=photographedMouthCorners(image,L);
    if(!measured)return null;
    const left=measured[48],dx=measured[54][0]-left[0],dy=measured[54][1]-left[1];
    const width=Math.hypot(dx,dy);
    if(width<29 || width*groovesPerPixel<9)return null;
    const curve=photographedSmile(image,measured,groovesPerPixel,tracking,false,true);
    if(!curve)return null;
    const local=([x,y])=>[((x-left[0])*dx+(y-left[1])*dy)/width**2,
      ((y-left[1])*dx-(x-left[0])*dy)/width**2];
    function margins(loop,u){
      const ys=[];
      for(let i=0;i<loop.length;i++){
        const a=loop[i],b=loop[(i+1)%loop.length];
        if((a[0]<=u)===(b[0]<=u))continue;
        ys.push(a[1]+(u-a[0])*(b[1]-a[1])/(b[0]-a[0]));
      }
      return ys.length===2 ? ys.sort((a,b)=>a-b) : null;
    }
    function sample(u,v){
      const x=left[0]+u*dx-v*dy,y=left[1]+u*dy+v*dx,ix=Math.floor(x),iy=Math.floor(y);
      let light=0,red=0;
      for(let j=0;j<=1;j++)for(let k=0;k<=1;k++){
        const i=4*(clamp(iy+j,0,image.height-1)*image.width+clamp(ix+k,0,image.width-1));
        const c=image.data,alpha=c[i+3]/255,w=(j?y-iy:1-y+iy)*(k?x-ix:1-x+ix);
        light+=w*(255+alpha*(.299*c[i]+.587*c[i+1]+.114*c[i+2]-255));
        red+=w*alpha*(c[i]-.64*c[i+1]-.36*c[i+2]);
      }
      return [light,red];
    }
    function edge(u,v,side){
      const [middle]=sample(u,v);
      return Math.min(...[.023,.045].map(h=>{
        const [inside,ri]=sample(u,v+side*h),[outside,ro]=sample(u,v-side*h);
        return Math.max(1.3*(Math.min(inside,outside)-middle),.55*Math.abs(outside-inside)+.75*(ro-ri));
      }));
    }
    const old=L.slice(60,68).map(local),fresh=curve.map(local);
    const earlier=[[],[]],after=[[],[]],teeth=[];
    const pale=([light,red])=>light-.65*red;
    for(let i=0;i<23;i++){
      const u=(i+5)/32,base=margins(old,u),fit=margins(fresh,u);
      if(!base || !fit)return null;
      for(const [j,side] of [1,-1].entries()){
        earlier[j].push(edge(u,base[j],side));
        after[j].push(edge(u,fit[j],side));
      }
      const tooth=pale(sample(u,.41*fit[0]+.59*fit[1]));
      teeth.push(tooth-Math.max(pale(sample(u,fit[0]-.035)),pale(sample(u,fit[1]+.035))));
    }
    const median=v=>v.slice().sort((a,b)=>a-b)[Math.floor(v.length/2)];
    if(median(teeth)<18 || teeth.filter(v=>v>8).length<.65*teeth.length)return null;
    for(let j=0;j<2;j++){
      if(median(after[j])<12 || median(after[j])-median(earlier[j])<3)return null;
      if(after[j].filter(s=>s>7).length<.72*after[j].length)return null;
    }
    return curve;
  }

  // At group-photo resolution the inner lip landmarks can be a pixel apart.
  // Find the pale band of teeth between two darker lips in mouth coordinates.
  // Use its lower edge as one stroke when two edges would merge in the sand.
  function smallGroupSmile(image,L,groovesPerPixel,tracking,fullBeard=false,openingGrooves=1.25+2*tracking) {
    const left=L[48],right=L[54],dx=right[0]-left[0],dy=right[1]-left[1];
    const width=Math.hypot(dx,dy);
    if(width<16 || width*groovesPerPixel<(fullBeard ? 1.7 : 3.5))return null;
    const depth=p=>((p[1]-left[1])*dx-(p[0]-left[0])*dy)/(width*width);
    const upper=depth(L[62]), lower=depth(L[66]);
    if((lower-upper)*width<1 || lower-upper<.045 || lower-upper>.42)return null;
    const point=(u,v)=>[left[0]+u*dx-v*dy,left[1]+u*dy+v*dx];
    function toothLight(u,v) {
      const [x,y]=point(u,v), ix=Math.floor(x), iy=Math.floor(y), fx=x-ix, fy=y-iy;
      let sum=0;
      for(let row=0;row<2;row++)for(let col=0;col<2;col++){
        const offset=4*(clamp(iy+row,0,image.height-1)*image.width+clamp(ix+col,0,image.width-1));
        const data=image.data, alpha=data[offset+3]/255;
        // Luminance minus the red cast of the adjoining lip.
        const pink=fullBeard ? Math.max(0,data[offset+2]-data[offset+1]) : 0;
        const value=-.501*data[offset]+1.103*data[offset+1]+.398*data[offset+2]-1.8*pink;
        sum+=(col?fx:1-fx)*(row?fy:1-fy)*(255+(value-255)*alpha);
      }
      return sum;
    }
    const samples=fullBeard ? 41 : 13;
    let cuts=[];
    for(let i=0;i<samples;i++){
      const u=fullBeard ? .025+i*.95/(samples-1) : .16+i*.68/12;
      let peak=-Infinity,center=0;
      for(let j=0;j<=12;j++){
        const v=upper-.025+(lower-upper+.045)*j/12, value=toothLight(u,v);
        if(value>peak){peak=value;center=v;}
      }
      const edges=[];
      for(const sign of [-1,1]){
        let darkest=Infinity,limit=center;
        for(let j=0;j<10;j++){
          const v=center+sign*(.035+(sign<0?.14:.18)*j/9), value=toothLight(u,v);
          if(value<darkest){darkest=value;limit=v;}
        }
        if(peak-darkest<22)break;
        let v=center;
        for(let j=1;j<=16;j++){
          v=center+(limit-center)*j/16;
          if(toothLight(u,v)<(peak+darkest)/2)break;
        }
        edges.push(v);
      }
      if(edges.length===2 && (edges[1]-edges[0])*width>=1.25) cuts.push({u,edges,index:i});
    }
    // Isolated highlights on skin and tooth-size flecks in a beard are not
    // an opening. Demand continuous evidence on both sides of the midpoint.
    let start=0, end=1, cornerDepth=[0,0];
    if(fullBeard) {
      // Hair can move the landmark corners well beyond the exposed teeth.
      // Follow only the unbroken band through the middle. Its ends locate
      // the smile independently of the moustache or a bright fleck beside it.
      const center=cuts.findIndex(c=>c.index===(samples-1)/2);
      if(center<0)return null;
      let a=center,b=center;
      while(a>0 && cuts[a-1].index===cuts[a].index-1)a--;
      while(b+1<cuts.length && cuts[b+1].index===cuts[b].index+1)b++;
      cuts=cuts.slice(a,b+1);
      start=cuts[0].u;end=cuts.at(-1).u;
      if(end-start<.40 || start>.37 || end<.64 || (end-start)*width*groovesPerPixel<1.25)return null;
      // Where the pale band ends, upper and lower strokes meet at its measured
      // mid-depth. Do not extend a line to an unsupported dark corner.
      const ends=[cuts[0],cuts.at(-1)];
      const corners=ends.map((edge,i)=>{
        const sign=i ? 1 : -1, middle=mean(edge.edges), edgeLight=toothLight(edge.u,middle);
        let best=[edge.u,middle],bestScore=12;
        // The dark end of the opening is bordered by the lip below and
        // lighter skin or hair outside. If these sides cannot be measured,
        // close the shape where the tooth band itself loses support.
        for(let a=0;a<13;a++)for(let b=0;b<12;b++){
          const du=.02+.17*a/12, dv=-.12+.138*b/11;
          const u=edge.u+sign*du, v=middle+dv, base=toothLight(u,v);
          const above=(toothLight(u,v-.045)+toothLight(u,v-.075))/2-base;
          const below=(toothLight(u,v+.045)+toothLight(u,v+.075))/2-base;
          const outside=(toothLight(u+sign*.035,v)+toothLight(u+sign*.07,v))/2-base;
          if(above<8 || below<12 || outside<10)continue;
          const score=.5*Math.min(above,below)+.3*Math.min(below,outside)+.2*outside-
            20*Math.abs(dv+.5*du)-14*du;
          if(score<=bestScore)continue;
          // A detached dark hair can have bright flanks. The intervening
          // pixels must remain in the shadow beside the teeth.
          if([.35,.65,.85].some(t=>toothLight(edge.u+sign*du*t,middle+dv*t)>edgeLight+14))continue;
          bestScore=score;best=[u,v];
        }
        return best;
      });
      [start,end]=corners.map(p=>p[0]);cornerDepth=corners.map(p=>p[1]);

    } else if(cuts.length<9 || cuts[1].u>.35 || cuts.at(-2).u<.65 ||
              !cuts.some(c=>Math.abs(c.u-.5)<.04))return null;
    function curve(side){
      const positions=fullBeard ? [0,.09,.19,.33,.50,.67,.81,.91,1] : [0,.22,.36,.5,.64,.78,1];
      const stations=positions.map(t=>{
        const u=start+t*(end-start);
        if(t===0 || t===1)return [u,cornerDepth[t]];
        const reach=(fullBeard ? .095 : .16)*(end-start);
        const near=cuts.filter(c=>Math.abs(c.u-u)<reach)
          .map(c=>c.edges[side]).sort((a,b)=>a-b);
        const middle=near.length ? near[Math.floor(near.length/2)] :
          cuts.reduce((a,b)=>Math.abs(a.u-u)<Math.abs(b.u-u)?a:b).edges[side];
        return [u,middle];
      });
      // Cut one smooth line through the broad contour, without tracing
      // individual teeth or the stair steps of a twenty-pixel mouth.
      const path=[stations[0]];
      for(let i=1;i<stations.length-1;i++){
        const a=path.at(-1), b=stations[i], c=i===stations.length-2 ? stations.at(-1) : mix(b,stations[i+1],.5);
        for(let j=1;j<=4;j++){
          const t=j/4;
          path.push(mix(mix(a,b,t),mix(b,c,t),t));
        }
      }
      return path;
    }
    const top=curve(0), bottom=curve(1), mid=Math.floor(top.length/2);
    const separate=[mid-1,mid,mid+1].every(i=>(bottom[i][1]-top[i][1])*width*groovesPerPixel>=openingGrooves);
    const low=bottom.map(([u,v])=>point(u,v)), high=separate ? top.map(([u,v])=>point(u,v)) : low;
    const loop=[...high.slice(mid),...low.slice(0,-1).reverse(),...high.slice(1,mid+1)];
    if(fullBeard){
      const rightIndex=high.length-1-mid, leftIndex=rightIndex+low.length-1;
      loop.toothTop=top.map(([u,v])=>point(u,v));
      loop.cornerIndices=[leftIndex,rightIndex];
      loop.corners=[loop[leftIndex],loop[rightIndex]];
    }
    return loop;
  }

  function photographedLid(image, eye, rim, scale) {
    const [a,,,b]=eye, dx=b[0]-a[0], dy=b[1]-a[1], width=Math.hypot(dx,dy);
    const at=(u,v)=>[a[0]+dx*u-dy*v,a[1]+dy*u+dx*v];
    const light=(u,v)=>grayAt(image,...at(u,v));
    let best=null;
    // A photographed lid is darker than the skin above and below it. Fit a
    // shallow arc in eye coordinates; glasses can pull the landmarks upward.
    const levels=[-.12,0,.12,.24,.36];
    for(const left of levels)for(const right of levels)for(const arch of [.04,.12,.20,.28]) {
      const points=[],contrast=[];
      for(let j=0;j<=10;j++){
        const u=.10+.094*j,v=left*(1-u)+right*u-4*arch*u*(1-u);
        const p=at(u,v),dark=(light(u,v)+light(u,v+.04))/2;
        const above=(light(u,v-.12)+light(u,v-.18))/2;
        const below=(light(u,v+.20)+light(u,v+.28))/2;
        points.push(p);contrast.push(Math.min(above,below)-dark);
      }
      const score=.65*mean(contrast)+.35*contrast.slice().sort((a,b)=>a-b)[3];
      if(!best || score>best.score)best={score,points};
    }
    if(best.score<17)return null;
    // The free part must clear the frame. Enter at an end through the side
    // of the lens. A shortest jump from the upper bar cuts a false eyebrow.
    const points=best.points;
    if(!insidePolygon(points[0],rim))return null;
    for(let j=1;j<points.length;j++){
      const start=points[j-1],end=points[j],middle=mix(start,end,.5);
      const half=Math.hypot(end[0]-start[0],end[1]-start[1])/2;
      const clearance=(j<=2 || j>=points.length-2 ? .65 : .85)/scale;
      // A disc about the midpoint encloses the whole segment. Keep the
      // disc inside the aperture, even where the frame has few vertices.
      for(let i=1;i<rim.length;i++){
        const [x,y]=rim[i-1],vx=rim[i][0]-x,vy=rim[i][1]-y;
        const t=clamp(((middle[0]-x)*vx+(middle[1]-y)*vy)/(vx*vx+vy*vy || 1),0,1);
        if(Math.hypot(middle[0]-x-t*vx,middle[1]-y-t*vy)<=half+clearance)return null;
      }
    }
    let closest=Infinity,entry;
    for(const j of [0,points.length-1]) {
      const p=points[j],sign=j?1:-1;
      for(let i=0;i<rim.length-1;i++){
        const x=rim[i][0]-p[0],y=rim[i][1]-p[1],gap=Math.hypot(x,y);
        const along=sign*(x*dx+y*dy)/(width*gap || 1);
        if(along<.94 || gap*scale>2.4)continue;
        const score=gap*scale+1-along;
        if(score<closest){closest=score;entry={i,reverse:!!j};}
      }
    }
    if(!entry)return null;
    if(entry.reverse)points.reverse();
    return {index:entry.i,stroke:[...points,...points.slice(0,-1).reverse()]};
  }

  function spectacleStroke(person, groovesPerPixel, image=null, rimsOnly=false) {
    const path=[],ports=[];
    const {glasses,eyes,frameBridge}=person;
    for(let side=0;side<2;side++){
      const rim=glasses[side],joint=frameBridge[side], eye=eyes[side];
      const dist=(a,b)=>Math.hypot(a[0]-b[0],a[1]-b[1]);
      const nearest=(points,target)=>points.reduce((best,p,i)=>dist(p,target)<dist(points[best],target)?i:best,0);
      const unroll=(points,start)=>[...points.slice(start),...points.slice(0,start+1)];
      const contact=nearest(rim,joint), steps=rim.length;
      const height=dist(rim[steps/4],rim[3*steps/4])*groovesPerPixel;
      if(groovesPerPixel && height<1.75){
        // In a very small group the top and bottom rims would merge. Trace the
        // black upper bar from the bridge to the temple and retrace it.
        const bar=[joint];
        for(let i=contact;i!==(side?0:steps/2);i=(i+(side?1:-1)+steps)%steps)bar.push(rim[i]);
        bar.push(rim[side?0:steps/2]);
        ports.push(path.length+bar.length-1);
        path.push(...bar,...bar.slice(0,-1).reverse());
        continue;
      }
      const ordered=unroll(rim,contact);
      if(rimsOnly){
        path.push(joint,...ordered,joint);
        continue;
      }
      const gaps=eye.map(p=>dist(p,rim[nearest(rim,p)])*groovesPerPixel);
      let eyeStroke=[],entry=-1;
      // On a small plate the real eye almost touches the top bar. Preserve the
      // photographed lens opening; an added lid there would fill it with sand.
      let lid=[];
      const enoughRoom=[...gaps].sort((a,b)=>a-b)[2]>1.45;
      if(image && !enoughRoom && dist(eye[0],eye[3])*groovesPerPixel>=2.6 && dist(eye[0],eye[3])>=15){
        const measured=photographedLid(image,eye,ordered,groovesPerPixel);
        if(measured){entry=measured.index;eyeStroke=measured.stroke;}
      }else if(enoughRoom){
        const open=dist(eye[1],eye[5])*groovesPerPixel>=1.2;
        lid=open?eye:[...eye.slice(0,4),eye[2],eye[1]];
      }else if(gaps[4]>=1.45 && gaps[5]>=1.45){
        // A lower lid can clear the rim even when the top of the eye meets
        // the dark frame. Retain the measured portion with room around it.
        const lower=[3,4,5,0].filter(i=>gaps[i]>=1.3).map(i=>eye[i]);
        if(dist(lower[0],lower.at(-1))*groovesPerPixel>1.3)lid=[...lower,...lower.slice(1,-1).reverse()];
      }
      if(lid.length){
        let gap=Infinity,lidIndex=0;
        for(let i=0;i<ordered.length-1;i++)for(let j=0;j<lid.length;j++){
          const d=dist(ordered[i],lid[j]);
          if(d<gap){gap=d;entry=i;lidIndex=j;}
        }
        eyeStroke=unroll(lid,lidIndex);
      }
      path.push(joint);
      const width=Math.max(...rim.map(p=>dist(p,joint)));
      for(let i=0;i<ordered.length;i++){
        if(dist(ordered[i],joint)>.86*width)ports.push(path.length);
        path.push(ordered[i]);
        if(i===entry)path.push(...eyeStroke,ordered[i]);
      }
      path.push(joint);
    }
    path.push(frameBridge[0]);  // return across the photographed bridge
    return {path,ports};
  }

  function photographedSmileCrease(image, L, width, lips, small=false) {
    const distance=(a,b)=>Math.hypot(a[0]-b[0],a[1]-b[1]);
    const span=distance(L[36],L[45]);
    if(span<12) return null;
    const x=(L[45][0]-L[36][0])/span, y=(L[45][1]-L[36][1])/span;
    // A short mouth in a group photo can have a strong cheek fold a few
    // pixels outside the lip. Search independently at the nose and the cheek.
    const handles=small ? [.05,.11,.17,.23].flatMap(nose=>
      [.04,.10,.16].flatMap(cheek=>[.025,.08,.16].map(rise=>[nose,-rise,cheek,-.025]))) :
      [.65,1,1.35].map(k=>[.04*k,-.075*k,.08*k,.018*k]);
    function light(px,py) {
      if(!small)return grayAt(image,px,py);
      const ix=Math.floor(px),iy=Math.floor(py),fx=px-ix,fy=py-iy;
      return (1-fy)*((1-fx)*grayAt(image,ix,iy)+fx*grayAt(image,ix+1,iy))+
        fy*((1-fx)*grayAt(image,ix,iy+1)+fx*grayAt(image,ix+1,iy+1));
    }
    let best=null, bestScore=14;
    for(const side of [0,1]) {
      const wing=L[side?35:31], corner=L[side?54:48], sign=side?1:-1;
      const port=lips.findIndex(p=>distance(p,corner)<.00001);
      if(port<0 || distance(wing,corner)<1)continue;
      const offset=(p,across,down)=>[p[0]+width*(sign*x*across-y*down),p[1]+width*(sign*y*across+x*down)];
      for(const [across,up,out,down] of handles) {
        const a=offset(wing,across,up), b=offset(corner,out,down);
        const points=Array.from({length:23},(_,j)=>{
          const t=j/22, u=1-t;
          return [0,1].map(k=>u*u*u*wing[k]+3*u*u*t*a[k]+3*u*t*t*b[k]+t*t*t*corner[k]);
        });
        const length=points.slice(1).reduce((sum,p,i)=>sum+distance(p,points[i]),0);
        // A longer sweep draws a conspicuous hook beside the mouth.
        if(length>(small?1.93:1.38)*distance(wing,corner)) continue;
        const contrast=[];
        for(let j=2;j<points.length-2;j++) {
          const [px,py]=points[j], prev=points[j-1], next=points[j+1];
          const normal=distance(prev,next);
          if(normal<1e-6)continue;
          let nx=(next[1]-prev[1])/normal, ny=(prev[0]-next[0])/normal;
          if(sign*(nx*x+ny*y)<0) { nx=-nx; ny=-ny; }
          const sample=d=>light(px+nx*d*width,py+ny*d*width);
          const floor=sample(0), outer=(sample(.03)+sample(.045))/2-floor;
          const inner=(sample(-.03)+sample(-.045))/2-floor;
          // The cheek outside a fold is brighter. A shadow with no local
          // valley on its other side should not give a strong vote.
          contrast.push(.65*Math.min(inner,outer)+.35*outer);
        }
        if(contrast.length<15)continue;
        contrast.sort((a,b)=>a-b);
        const score=small ? .5*mean(contrast)+.5*contrast[6]-1.8*(across+out) :
          .6*mean(contrast)+.4*contrast[5]-4*length/width;
        if(contrast[4]>=(small ? 4 : 12) && score>bestScore) {
          bestScore=score;
          best={side,points,lipLoop:[...lips.slice(port+1,-1),...lips.slice(0,port+1)]};
        }
      }
    }
    return best;
  }

  // The five nose landmarks describe its base. Find the lit-to-shaded edge
  // on the chosen side, then turn the sampling direction under the wing.
  // Small portraits and indistinct shadows keep the landmark drawing.
  function photographedNoseSide(image,L,side,person,start,groovesPerPixel) {
    const ax=L[35][0]-L[31][0],ay=L[35][1]-L[31][1],width=Math.hypot(ax,ay);
    if(width<24 || width*groovesPerPixel<4)return null;
    const center=mix(L[31],L[35],.5),sign=side?1:-1;
    const at=(u,v)=>[center[0]+sign*u*ax-v*ay,center[1]+sign*u*ay+v*ax];
    const light=(u,v)=>grayAt(image,...at(u,v));
    const rows=[];
    function addRow(ou,ov,du,dv,lo,hi,count,preferred) {
      const row=[];
      for(let j=0;j<count;j++){
        const r=lo+(hi-lo)*j/(count-1),u=ou+du*r,v=ov+dv*r;
        const difference=d=>light(u-d*du,v-d*dv)-light(u+d*du,v+d*dv);
        const contrast=.62*difference(.058)+.38*difference(.128);
        let score=clamp(contrast,-22,67)-17*Math.abs(r-preferred),prev=-1;
        if(rows.length){
          let best=-Infinity;
          const prior=rows.at(-1);
          for(let k=0;k<prior.length;k++){
            const distance=Math.hypot(prior[k].u-u,prior[k].v-v);
            if(distance>.145)continue;
            const value=prior[k].score-85*distance;
            if(value>best){best=value;prev=k;}
          }
          score+=best;
        }
        row.push({u,v,contrast,score,prev});
      }
      rows.push(row);
    }
    for(let i=0;i<=16;i++)addRow(0,-.92+.72*i/16,1,0,.18,1.10,42,.43+.30*i/16);
    for(let i=1;i<=12;i++){
      const a=i*100/12*Math.PI/180;
      addRow(.49,-.20,Math.cos(a),Math.sin(a),.085,.52,35,.29);
    }
    let choice=rows.at(-1).reduce((best,q,i,row)=>q.score>row[best].score?i:best,0);
    const edge=[];
    for(let i=rows.length-1;i>=0;i--){
      const point=rows[i][choice];
      if(!point || !Number.isFinite(point.score))return null;
      edge.unshift(point);choice=point.prev;
    }
    const evidence=edge.map(q=>q.contrast).sort((a,b)=>a-b);
    // A straight glasses edge or cast shadow can have strong contrast along
    // the side, but supplies no underside as the sampling direction turns.
    const underside=edge.slice(-6).filter(q=>q.contrast>=14).length;
    if(evidence[5]<14 || evidence[14]<25 || underside<4 || edge[16].u-edge[0].u<.13)return null;
    // A beard or smile crease can keep the shaded side going past the wing.
    // Rejoining the nostril then makes the underside visibly double back.
    let lowest=edge[16].v;
    for(const point of edge.slice(17)){
      lowest=Math.max(lowest,point.v);
      if((lowest-point.v)*width*groovesPerPixel>.5)return null;
    }
    const path=edge.map(q=>at(q.u,q.v));
    const smooth=path.map((p,i)=>!i || i===path.length-1 ? p : mix(p,mix(path[i-1],path[i+1],.5),.5));
    // The underside turns in toward the middle landmark. Sample the shadow
    // at the intervening nostril; jumping straight to a high landmark can
    // leave a notch between the wing and the tip.
    const axis=p=>sign*((p[0]-center[0])*ax+(p[1]-center[1])*ay)/(width*width);
    const depth=p=>(-(p[0]-center[0])*ay+(p[1]-center[1])*ax)/(width*width);
    const tip=L[33],u=axis(L[side?34:32]),end=edge.at(-1);
    if(u>=end.u || u<=axis(tip)+.025)return null;
    const t=(end.u-u)/(end.u-axis(tip)),middle=end.v*(1-t)+depth(tip)*t;
    if(t<.15 || t>.85)return null;
    let selected=middle,best=10;
    for(let k=-5;k<=5;k++){
      const v=middle+.016*k;
      const contrast=mean([-.035,0,.035].map(d=>light(u+d,v-.06)-light(u+d,v+.07)));
      const score=contrast-1.7*Math.abs(k);
      if(score>best){selected=v;best=score;}
    }
    const toTip=Array.from({length:9},(_,i)=>{
      const f=i/8,bend=(selected-middle)*f*(1-f)/(t*(1-t));
      return at(end.u+(axis(tip)-end.u)*f,end.v+(depth(tip)-end.v)*f+bend);
    });
    if(person.frameBridge){
      // Join at the photographed inner rim and follow its existing groove
      // before turning down the nose. A chord here could cross the lens.
      const rim=person.glasses[side],dist=(a,b)=>Math.hypot(a[0]-b[0],a[1]-b[1]);
      const nearest=p=>rim.reduce((best,q,i)=>dist(p,q)<dist(p,rim[best])?i:best,0);
      const begin=nearest(start),end=nearest(smooth[0]);
      if(dist(rim[end],smooth[0])>.23*width)return null;
      const arc=step=>{
        const part=[start,rim[begin]];
        for(let i=begin;i!==end;){i=(i+step+rim.length)%rim.length;part.push(rim[i]);}
        return part;
      };
      const length=p=>p.slice(1).reduce((s,q,i)=>s+dist(q,p[i]),0);
      const a=arc(1),b=arc(-1),lead=length(a)<=length(b)?a:b;
      if(length(lead)>1.25*width)return null;
      return {bridge:[...lead,...smooth],toTip};
    }
    const bend=mix(smooth[0],smooth[4],-.85);
    const lead=Array.from({length:9},(_,i)=>mix(mix(start,bend,i/8),mix(bend,smooth[0],i/8),i/8));
    return {bridge:[...lead,...smooth.slice(1)],toTip};
  }

  function expressionStroke(image, landmarks, person, measuredLips, fold, seatScale=0) {
    // A single line follows the shaded side of the nose down from the brow.
    // The lip and nose can then share the short groove above the upper lip.
    const shadows = [31, 35].map(index => mean([.35, .55, .75].map(distance => {
      const sample = mix(landmarks[29], landmarks[index], distance);
      return grayAt(image, ...sample);
    })));
    const side = shadows[0] < shadows[1] ? 0 : 1;
    const brow = person.frameBridge ? [person.frameBridge[side]] : side ? [...person.brows[1]].reverse() : person.brows[0];
    const wing = landmarks[side ? 35 : 31];
    const bend = mix(landmarks[29], wing, .36);
    const fitted=seatScale && photographedNoseSide(image,landmarks,side,person,brow.at(-1),seatScale);
    const bridge = fitted?.bridge || Array.from({length: 11}, (_, index) => {
      const t = index/10;
      return mix(mix(brow.at(-1), bend, t), mix(bend, wing, t), t);
    });
    const nose = side ? [...person.noseLine].reverse() : person.noseLine;
    const toTip=fitted?.toTip || nose.slice(0,3);
    const inward = [...brow, ...bridge.slice(1), ...toTip.slice(1)];
    if(fold?.moustache){
      return {path:[...inward,nose[3],nose[4],nose[3],nose[2],...fold.moustache,...inward.slice().reverse()],side};
    }
    if (fold) {
      inward.push(nose[3],nose[4]);
      if (fold.side===side) inward.push(nose[3],...toTip.slice().reverse());
      inward.push(...fold.points.slice(1));
      return {path:[...inward,...(fold.lipLoop || []),...inward.slice(0,-1).reverse()],side};
    }
    const lip = measuredLips || [...person.mouth.slice(3), ...person.mouth.slice(0, 4)];
    const path = [...inward, nose[3], nose[4], nose[3], nose[2], ...lip,
                  ...inward.slice().reverse()];
    return {path, side, noseStroke:[...bridge,...toTip.slice(1),nose[3],nose[4]]};
  }

  function soloFrame(person,landmarks) {
    const h=person.head,top=Math.min(...h.map(p=>p[1])),chin=Math.max(...h.map(p=>p[1]));
    const radius=(chin-top)/1.58,cy=top+.9*radius;
    const cx=(Math.min(...h.map(p=>p[0]))+Math.max(...h.map(p=>p[0])))/2;
    return {cx,cy,radius,person,landmarks};
  }

  // The photographed hairline can end behind the glasses on the turning side
  // of a head. Leave room for the ball to finish the rim in front of the hair.
  function visibleTempleHair(line,glasses,scale) {
    if(!glasses.length || !scale)return line;
    function nearLens(point) {
      return glasses.some(rim=>insidePolygon(point,rim) || rim.some((a,i)=>{
        const b=rim[(i+1)%rim.length],dx=b[0]-a[0],dy=b[1]-a[1];
        const t=clamp(((point[0]-a[0])*dx+(point[1]-a[1])*dy)/(dx*dx+dy*dy || 1),0,1);
        return Math.hypot(point[0]-a[0]-t*dx,point[1]-a[1]-t*dy)*scale<1.15;
      }));
    }
    const middle=Math.floor(line.length/2);
    function toward(end,step) {
      const part=[line[middle]];
      for(let i=middle;i!==end;i+=step){
        const a=line[i],b=line[i+step];
        const count=Math.max(1,Math.ceil(Math.hypot(b[0]-a[0],b[1]-a[1])*scale/.15));
        for(let k=1;k<=count;k++){
          if(nearLens(mix(a,b,k/count))){
            if(k>1)part.push(mix(a,b,(k-1)/count));
            return part;
          }
        }
        part.push(b);
      }
      return part;
    }
    return [...toward(0,-1).reverse(),...toward(line.length-1,1).slice(1)];
  }

  // The recovered hairline follows the main mass of hair. A narrow dark lock
  // between two skin patches may extend well below it on the forehead.
  function photographedFringe(image, L, lower, groovesPerPixel) {
    const left=L[0], dx=L[16][0]-left[0],dy=L[16][1]-left[1], width=Math.hypot(dx,dy);
    if (width<80 || !(groovesPerPixel>0)) return lower;
    const origin=mix(left,L[16],.5);
    const at=(u,v)=>[origin[0]+u*dx-v*dy,origin[1]+u*dy+v*dx];
    const uv=([x,y])=>[((x-origin[0])*dx+(y-origin[1])*dy)/width**2,
      ((y-origin[1])*dx-(x-origin[0])*dy)/width**2];
    const brows=L.slice(17,27).map(uv);
    const edge=lower.map(uv);
    const light=(u,v)=>grayAt(image,...at(u,v));
    function strand(u,v) {
      const core=(light(u-.005,v)+light(u+.005,v))/2;
      return Math.min(light(u-.05,v),light(u+.05,v))-core>24;
    }
    const gap=1.4/(groovesPerPixel*width);
    let tip=null;
    for(let i=1;i<edge.length;i++){
      const [x0,y0]=edge[i-1],[x1,y1]=edge[i];
      if(x1<=x0 || x0<-.34 || x1>.34)continue;
      for(let u=x0;u<x1;u+=.012){
        const start=y0+(u-x0)*(y1-y0)/(x1-x0);
        const near=brows.filter(([x])=>Math.abs(x-u)<Math.max(.14,gap));
        if (!near.length) continue;
        const ceiling=Math.min(...near.map(([x,y])=>y-Math.max(.055,Math.sqrt(Math.max(0,gap*gap-(u-x)**2)))));
        for(let v=start+.09;v<ceiling;v+=.012){
          // A forehead crease and the end of an eyebrow lack this downward
          // run of dark hair flanked by skin. Allow the strand to slope.
          const supports=[0,-.025,-.05,-.075].every(dv=>[-.016,0,.016].some(du=>strand(u+du,v+dv)));
          if(supports && (!tip || v-start>tip.depth))tip={u,v,depth:v-start};
        }
      }
    }
    if(!tip)return lower;
    // Keep the photographed tip distinct from the brow and from each side of
    // the fringe after the steel ball cuts its groove.
    const span=Math.max(.085,1.05/(groovesPerPixel*width));
    const first=edge.findIndex(([u])=>u>tip.u-span), last=edge.findIndex(([u])=>u>tip.u+span);
    if(first<1 || last<=first)return lower;
    return [...lower.slice(0,first),at(tip.u,tip.v),...lower.slice(last)];
  }

  // Trace an off-center part only when the same hair continues past the temple.
  // A dark cheek or earring alone must not add a lock to the silhouette.
  function sweptTempleHair(image,L,shape,diameterGrooves) {
    const left=L[0],right=L[16],o=mix(left,right,.5),dx=right[0]-left[0],dy=right[1]-left[1],w=shape.width;
    if(w<100 || !shape.recoveredHair || shape.glasses.length || !(diameterGrooves>0))return null;
    const at=(u,v)=>[o[0]+u*dx-v*dy,o[1]+u*dy+v*dx];
    const uv=([x,y])=>[((x-o[0])*dx+(y-o[1])*dy)/(w*w),((y-o[1])*dx-(x-o[0])*dy)/(w*w)];
    const color=(x,y)=>rgb(image,at(x,y)), light=c=>.3*c[0]+.59*c[1]+.11*c[2];
    const middle=a=>a.sort((a,b)=>a-b)[Math.floor(a.length/2)];
    const medianColor=colors=>[0,1,2].map(i=>middle(colors.map(c=>c[i])));
    const inner=shape.hair.slice(shape.hair.length/2).map(uv),crown=shape.head.slice(17).reverse().map(uv);
    const dark=medianColor(inner.slice(4,-4).map((p,i)=>color(...mix(p,crown[i+4],.5))));
    const skin=medianColor([[-.18,-.08],[0,-.20],[.18,-.05]].map(([x,y])=>color(x,y)));
    if(light(skin)-light(dark)<45)return null;
    function sample(line,x){
      for(let i=1;i<line.length;i++){
        const [a,b]=[line[i-1],line[i]];
        if(x>=a[0] && x<=b[0] && a[0]!==b[0])return a[1]+(b[1]-a[1])*(x-a[0])/(b[0]-a[0]);
      }
      return NaN;
    }
    const jaw=L.slice(0,17).map(uv);
    const locks=[];
    for(const side of [-1,1]){
      const cheek=(side===1 ? jaw.slice(8).reverse() : jaw.slice(0,9)).map(([x,y])=>[y,side*x]);
      let previous=.54; const edge=[];
      for(let v=-.19;v<.77;v+=.035){
        const limit=v<=0 ? .5 : sample(cheek,v);
        if(!Number.isFinite(limit))break;
        let best=null,score=6;
        for(let u=.12;u<.89;u+=.008){
          if(u<limit-.04 || u>limit+.23 || Math.abs(u-previous)>.11)continue;
          const c=color(side*u,v),tone=light(c),distance=colorDistance(c,dark);
          if(distance>85 || tone>light(skin)-26)continue;
          const strength=Math.min(light(color(side*(u-.055),v)),light(color(side*(u+.055),v)))-tone
            -.10*distance-95*Math.abs(u-previous);
          if(strength>score){score=strength;best=u;}
        }
        if(best===null){
          if(edge.length && v-edge.at(-1)[1]>.075)break;
        } else {edge.push([side*best,v]);previous=best;}
      }
      if(edge.length<15 || edge[0][1]>-.10 || edge.at(-1)[1]<.38)continue;
      locks.push({side,edge});
    }
    if(locks.length!==1)return null;
    const {side,edge}=locks[0];
    // Follow the taper with narrower flank samples. The last strands can
    // take on the color of the wall behind them, so compare with both sides.
    const contrast=colorDistance(skin,dark),direction=skin.map((value,i)=>(value-dark[i])/contrast);
    const shade=c=>c.reduce((s,t,i)=>s+t*direction[i],0);
    let previous=Math.abs(edge.at(-1)[0]);
    for(let y=edge.at(-1)[1]+.035;y<.80;y+=.035){
      let best=null,score=6;
      for(let x=previous-.044;x<=previous+.044;x+=.006){
        const c=color(side*x,y);
        if(colorDistance(c,dark)>125 || light(c)>light(skin)-15)continue;
        const flanks=Math.min(shade(color(side*(x-.028),y)),shade(color(side*(x+.028),y)));
        const strength=.75*(flanks-shade(c))-.03*colorDistance(c,dark)-95*Math.abs(x-previous);
        if(strength>score){best=x;score=strength;}
      }
      if(best===null)break;
      previous=best;edge.push([side*best,y]);
    }
    // At a small guest-face size a taper can merge into the cheek. Measure
    // its tip against the nearest jaw segment at the proposed portrait size.
    const tip=at(...edge.at(-1)), headY=shape.head.map(q=>q[1]);
    const pixelsPerGroove=(Math.max(...headY)-Math.min(...headY))/(.90*diameterGrooves);
    const jawGap=Math.min(...L.slice(0,16).map((a,i)=>{
      const b=L[i+1],dx=b[0]-a[0],dy=b[1]-a[1];
      const t=clamp(((tip[0]-a[0])*dx+(tip[1]-a[1])*dy)/(dx*dx+dy*dy || 1),0,1);
      return Math.hypot(tip[0]-a[0]-t*dx,tip[1]-a[1]-t*dy);
    }));
    if(jawGap<1.15*pixelsPerGroove)return null;
    // A forehead-to-hair boundary across several neighboring columns locates
    // the part. Sample above and below each edge in the colors of this face.
    const measured=inner.map(([x,prior])=>{
      if(Math.abs(x)>.35)return [x,prior];
      let best=prior,score=19;
      for(let y=Math.max(-.84,prior-.23);y<Math.min(prior+.19,-.035);y+=.012){
        const tone=d=>medianColor([-.018,0,.018].map(h=>color(x+h,y+d)));
        const below=tone(.045),above=tone(-.045);
        if(light(below)<light(dark)+21 || light(above)>light(skin)-13 || colorDistance(below,skin)>115 ||
           colorDistance(above,dark)>100 || [.075,.105].some(d=>light(color(x,y+d))<light(dark)+22 ||
           light(color(x,y-d))>light(skin)-15))continue;
        const strength=light(below)-light(above)-25*Math.abs(y-prior);
        if(strength>score){best=y;score=strength;}
      }
      return [x,best];
    });
    let part=-1;
    for(let i=1;i<measured.length-1;i++){
      const [x,y]=measured[i];
      if(side*x<.07 || side*x>.33 || inner[i][1]-y<.07)continue;
      if(part<0 || y<measured[part][1])part=i;
    }
    if(part<0 || ![part-1,part+1].some(i=>inner[i][1]-measured[i][1]>.055))return null;
    const smooth=points=>points.map((p,i)=>i && i<points.length-1?mix(p,mix(points[i-1],points[i+1],.5),.65):p);
    const boundary=smooth(measured), root=boundary[part];
    const sweep=[root]; let last=root[1]-.016;
    for(let x=root[0]-side*.025;side*x>-.65;x-=side*.025){
      const upper=sample(crown,x),lower=sample(boundary,x);
      let point=null,score=-Infinity;
      for(let y=Math.max(upper+.04,last-.07);y<Math.min(lower-.04,last+.07);y+=.009){
        const tone=d=>middle([-.012,0,.012].map(h=>light(color(x+h,y+d))));
        const above=tone(-.033),below=tone(.033),delta=below-above;
        if(Math.max(above,below)>light(skin)-35 || delta<3)continue;
        const strength=delta-.4*Math.abs(tone(0)-light(dark))-55*Math.abs(y-last);
        if(strength>score){score=strength;point=y;}
      }
      if(point===null)break;
      sweep.push([x,point]);last=point;
    }
    if(sweep.length<15)return null;
    return {side,edge:smooth(edge).map(p=>at(...p)),boundary:boundary.map(p=>at(...p)),
      part,sweep:smooth(smooth(sweep)).map(p=>at(...p))};
  }

  // Measure where the iris meets visible sclera on the same side of both eyes.
  // On a small face, one groove follows the dark band in the photo. A larger
  // eye can also show the iris edge without closing its lighter corner.
  function photographedGaze(image, eyes, scale) {
    const observations=eyes.map(eye=>{
      const [left,,,right]=eye,dx=right[0]-left[0],dy=right[1]-left[1],width=Math.hypot(dx,dy);
      if(width<18 || width*scale<2.4)return null;
      const along=eye.map(q=>((q[0]-left[0])*dx+(q[1]-left[1])*dy)/(width*width));
      const upper=[0,1,2,3], lower=[0,5,4,3];
      if([upper,lower].some(ids=>ids.some((j,k)=>k && along[j]<=along[ids[k-1]])))return null;
      function edge(u,indices) {
        const k=indices.findIndex((j,i)=>i && along[j]>=u);
        const a=indices[k-1],b=indices[k];
        return mix(eye[a],eye[b],(u-along[a])/(along[b]-along[a]));
      }
      const at=(u,v)=>mix(edge(u,upper),edge(u,lower),v);
      const light=(u,v)=>grayAt(image,...at(u,v));
      const rows=[.34,.48,.62,.76];
      let best=null;
      for(const sign of [-1,1])for(let i=0;i<=20;i++){
        const u=.25+.025*i;
        if(Math.abs(u-.17*sign-.5)>.27)continue;
        const contrast=rows.map(v=>{
          const white=mean([.06,.10,.14].map(d=>light(u+sign*d,v)));
          const iris=mean([.045,.08,.12].map(d=>light(u-sign*d,v)));
          return white-iris;
        }).sort((a,b)=>a-b);
        if(contrast[1]<17 || contrast[2]<25)continue;
        const score=mean(contrast.slice(0,3));
        if(!best || score>best.score)best={u,sign,score};
      }
      if(!best)return null;
      const {u,sign}=best;
      const far=u+sign*.10;
      const lid=[left];
      for(let k=1;k<10;k++){
        const t=k/10, white=light(far,.65);
        const bands=[-.15,.05,.25,.45,.65,.85];
        const weights=bands.map(v=>Math.max(0,white-light(t,v)));
        const total=weights.reduce((a,b)=>a+b,0);
        const depth=total>25 ? clamp(bands.reduce((sum,v,i)=>sum+v*weights[i],0)/total,-.05,.62) : 0;
        lid.push(at(t,depth));
      }
      lid.push(right);
      let line=[...lid,...lid.slice(1,-1).reverse()];
      const height=Math.hypot(...at(u,1).map((v,i)=>v-at(u,0)[i]))*scale;
      if(height>=.62){
        // Refine the boundary independently at the top and bottom of the iris.
        const fit=v=>{
          let bestU=u, strength=-Infinity;
          for(let k=-3;k<=3;k++){
            const x=u+k*.015;
            const d=light(x+sign*.055,v)-light(x-sign*.055,v)-Math.abs(k)*2;
            if(d>strength){bestU=x;strength=d;}
          }
          return bestU;
        };
        const top=fit(rows[0]),bottom=fit(rows.at(-1));
        if(height>1.9){
          // Both eyelids fit. Interpolate through their photographed landmarks,
          // preserving each lid's extrema and the sharp turns at the corners.
          const smoothLid=ids=>{
            const xs=ids.map(j=>along[j]);
            const ys=ids.map(j=>((eye[j][1]-left[1])*dx-(eye[j][0]-left[0])*dy)/width);
            const slopes=xs.slice(1).map((x,i)=>(ys[i+1]-ys[i])/(x-xs[i]));
            const tangent=(a,b)=>a*b<=0 ? 0 : 2*a*b/(a+b);
            const tangents=[slopes[0],tangent(slopes[0],slopes[1]),tangent(slopes[1],slopes[2]),slopes[2]];
            return x=>{
              const i=xs.findIndex((v,k)=>k && v>=x)-1;
              const h=xs[i+1]-xs[i], t=(x-xs[i])/h, s=1-t;
              const y=s*s*(1+2*t)*ys[i]+s*s*t*h*tangents[i]+t*t*(3-2*t)*ys[i+1]-t*t*s*h*tangents[i+1];
              return [left[0]+x*dx-y*dy/width,left[1]+x*dy+y*dx/width];
            };
          };
          const upperLid=smoothLid(upper), lowerLid=smoothLid(lower);
          const steps=Array.from({length:15},(_,i)=>(i+1)/16);
          const fractions=(ids,extra)=>[...new Set([...steps,along[ids[1]],along[ids[2]],extra])].sort((a,b)=>a-b);
          const topSteps=fractions(upper,top), bottomSteps=fractions(lower,bottom);
          // A catchlight can interrupt one contrast sample. Keep the measured
          // edge's gentle bend without engraving each pixel fluctuation.
          const bend=clamp((fit(.48)+fit(.62)-top-bottom)/2,-.04,.04);
          const iris=Array.from({length:9},(_,i)=>{
            const v=i/8, x=top+(bottom-top)*v+4*v*(1-v)*bend;
            return mix(upperLid(x),lowerLid(x),v);
          });
          // Enter the iris from the upper lid and return along it, leaving
          // the white corner free of travel between the two contours.
          line=[left,...topSteps.filter(t=>t<top).map(upperLid),...iris,...iris.slice(0,-1).reverse(),
            ...topSteps.filter(t=>t>top).map(upperLid),right,...bottomSteps.reverse().map(lowerLid)];
          return {line,corners:[left,right],bothLids:true,...best};
        }
        const mark=[at(top,0),at(fit(.50),.50),at(bottom,.94)];
        const towardWhite=sign>0 ? upper : upper.slice().reverse();
        const awayFromWhite=sign>0 ? [4,5,0] : [5,4,3];
        const bright=towardWhite.filter(j=>(along[j]-top)*sign>0).map(j=>eye[j]);
        line=[...towardWhite.filter(j=>(along[j]-top)*sign<=0).map(j=>eye[j]),mark[0],...bright,
          ...bright.slice(0,-1).reverse(),...mark,...awayFromWhite.filter(j=>(along[j]-bottom)*sign<0).map(j=>eye[j])];
      }
      return {line,corners:[left,right],...best};
    });
    if(!observations.every(Boolean))return null;
    const [a,b]=observations;
    return a.sign===b.sign && Math.abs(a.u-b.u)<=.16 && Math.max(a.score,b.score)>=42 ? observations : null;
  }

  // Six landmarks can leave a straight groove through the dark of a smiling eye.
  // Keep the photographed corners and upper lid. Fit the lower edge only when
  // dark eye meets lighter skin across both halves of the opening.
  function photographedLowerLid(image, eye, scale) {
    const [left,,,right]=eye, dx=right[0]-left[0], dy=right[1]-left[1];
    const span=Math.hypot(dx,dy), groove=1/scale;
    if(span<24 || span<5.2*groove)return null;
    const local=eye.map(([x,y])=>[
      ((x-left[0])*dx+(y-left[1])*dy)/(span*span),
      ((y-left[1])*dx-(x-left[0])*dy)/span
    ]);
    const upper=[local[0],local[1],local[2],local[3]];
    const lower=[local[0],local[5],local[4],local[3]];
    const [first,second]=lower.slice(1,3);
    if(first[0]<.18 || second[0]>.84 || second[0]-first[0]<.19 ||
       upper[1][0]<=0 || upper[2][0]<=upper[1][0] || upper[2][0]>=1)return null;
    const photoPoint=(u,v)=>[left[0]+u*dx-v*dy/span,left[1]+u*dy+v*dx/span];
    function landmarkEdge(points,u){
      const i=points.findIndex((p,k)=>k && p[0]>=u), a=points[i-1], b=points[i];
      return a[1]+(b[1]-a[1])*(u-a[0])/(b[0]-a[0]);
    }
    function light(u,v){
      return interpolatedGray(image,...photoPoint(u,v));
    }
    const reach=Math.min(.085*span,.68*groove);
    const contrast=(u,v)=>Math.min(...[.58,1.05].map(f=>light(u,v+f*reach)-light(u,v-f*reach)));
    const median=values=>values.slice().sort((a,b)=>a-b)[Math.floor(values.length/2)];

    // A single smooth arch can tip towards either corner without following
    // individual lashes or a small catchlight.
    const arch=(u,a,b)=>Math.sin(Math.PI*u)*(a+(b-a)*u);
    const firstDepth=first[1]/Math.sin(Math.PI*first[0]);
    const secondDepth=second[1]/Math.sin(Math.PI*second[0]);
    const tilt=(secondDepth-firstDepth)/(second[0]-first[0]), base=firstDepth-first[0]*tilt;
    const fitting=Array.from({length:13},(_,i)=>(i+3)/18);
    let best=null;
    for(let i=-5;i<=5;i++)for(let j=-5;j<=5;j++){
      const a=base+i*.36*groove, b=base+tilt+j*.36*groove;
      const offsets=fitting.map(u=>Math.abs(arch(u,a,b)-landmarkEdge(lower,u)));
      if(Math.max(...offsets)>1.04*groove)continue;
      const strengths=fitting.map(u=>{
        const v=arch(u,a,b);
        // Near a sharp edge several curves can pass the wider contrast check.
        // A narrow sample locates the middle of that transition.
        const localSlope=light(u,v+.3*reach)-light(u,v-.3*reach);
        return clamp(contrast(u,v),-10,70)+.55*clamp(localSlope,-10,100);
      });
      const score=mean(strengths)-4*mean(offsets)/groove;
      if(!best || score>best.score)best={a,b,score};
    }
    if(!best)return null;

    // Test halfway between fitting samples. Each third needs a visible edge,
    // and both halves must improve on the line the ball would otherwise use.
    const check=Array.from({length:12},(_,i)=>(3.5+i)/18);
    const height=u=>arch(u,best.a,best.b);
    const strengths=check.map(u=>contrast(u,height(u)));
    const gains=check.map((u,i)=>strengths[i]-contrast(u,landmarkEdge(lower,u)));
    if([0,4,8].some(k=>median(strengths.slice(k,k+4))<15) || median(gains)<6 ||
       Math.min(median(gains.slice(0,6)),median(gains.slice(6)))<3 ||
       median(check.map(u=>Math.abs(height(u)-landmarkEdge(lower,u))))<.22*groove ||
       median(check.map(u=>height(u)-landmarkEdge(upper,u)))<1.65*groove)return null;
    const line=eye.slice(0,4);
    for(let i=15;i>0;i--)line.push(photoPoint(i/16,height(i/16)));
    return {line,bothLids:true};
  }

  function photographedShadowEyes(image, eyes, scale) {
    const gaze=photographedGaze(image,eyes,scale);
    if(gaze?.every(eye=>eye.bothLids))return gaze;
    const lids=eyes.map(eye=>photographedLowerLid(image,eye,scale));
    return lids.some(Boolean) ? lids : null;
  }

  // From the eyebrow side of the forehead find a continuous skin-to-hair
  // transition inside an existing unshaded head. Nothing extends the crop.
  function photographedFringeForMini(image,frame,scale,contours) {
    const p=frame.person,L=frame.landmarks;
    if(p.hair.length || p.glasses.length || p.goatee.length || frame.beardMask || !scale)return null;
    const dx=L[16][0]-L[0][0],dy=L[16][1]-L[0][1],width=Math.hypot(dx,dy);
    if(width<100)return null;
    const origin=mix(L[0],L[16],.5);
    const local=([x,y])=>[((x-origin[0])*dx+(y-origin[1])*dy)/(width*width),
      ((y-origin[1])*dx-(x-origin[0])*dy)/(width*width)];
    const at=(angle,r)=>[origin[0]+r*(dx*Math.cos(angle)+dy*Math.sin(angle)),
      origin[1]+r*(dy*Math.cos(angle)-dx*Math.sin(angle))];
    const median=v=>v.sort((a,b)=>a-b)[v.length>>1];
    const outer=p.head.slice(17).map(local).map(([x,y])=>({a:clamp(Math.atan2(-y,x),0,Math.PI),r:Math.hypot(x,y)})).sort((a,b)=>a.a-b.a);
    if(outer.length<12)return null;
    const n=61,m=85,lo=.23,step=.0075,quality=[],rims=[],angles=[];
    let prior;
    const parent=[];
    for(let i=0;i<n;i++){
      const angle=.10+(Math.PI-.20)*i/(n-1);
      const upperIndex=outer.findIndex(q=>q.a>=angle),j=upperIndex<0 ? outer.length-1 : upperIndex;
      const a=outer[Math.max(0,j-1)],b=outer[j];
      const rim=a.r+(b.r-a.r)*clamp((angle-a.a)/Math.max(.0001,b.a-a.a),0,1);
      const lum=Array.from({length:m},(_,k)=>median([-.012,0,.012].map(t=>interpolatedGray(image,...at(angle+t,lo+step*k)))));
      // Require a dark band outside the candidate edge. Nearby bare temples
      // and highlights are sampled in the same photo and exposure.
      const observation=new Float32Array(m).fill(-600),row=new Float32Array(m).fill(-600);
      for(let k=7;k<m-9;k++){
        const r=lo+step*k;
        if(r<.29+.055*Math.sin(angle) || r>=rim-.012)continue;
        const before=median([2,4,6].map(h=>lum[k-h])),after=median([2,4,7].map(h=>lum[k+h]));
        const local=lum[k-1]-lum[k+1];
        observation[k]=Math.min(75,before-after);
        row[k]=observation[k]+.38*clamp(local,-24,44)-38*Math.abs(r-(.38+.13*Math.sin(angle)));
      }
      quality.push(observation);rims.push(rim);angles.push(angle);
      if(!prior){prior=row;continue;}
      const prev=new Uint8Array(m),next=new Float64Array(m);
      for(let k=0;k<m;k++){
        let best=-Infinity;
        for(let h=Math.max(0,k-5);h<=Math.min(m-1,k+5);h++){
          const move=Math.abs(k-h),val=prior[h]-1.7*move-.8*move*move;
          if(val>best){best=val;prev[k]=h;}
        }
        next[k]=best+row[k];
      }
      parent.push(prev);prior=next;
    }
    const chosen=[];let k=prior.indexOf(Math.max(...prior));
    for(let i=n-1;i>=0;i--){chosen[i]=k;if(i)k=parent[i-1][k];}
    const widthInGrooves=width*scale;
    // Carve on the hair side of a soft transition. Centering the full-width
    // groove on the first dark pixels would cut into the photographed forehead.
    const radii=chosen.map((j,i)=>{
      const edge=lo+step*(2*j+chosen[Math.max(0,i-1)]+chosen[Math.min(n-1,i+1)])/4;
      return edge+Math.min(.55/widthInGrooves,.22*Math.max(0,rims[i]-edge));
    });
    const clear=radii.map((r,i)=>widthInGrooves*(rims[i]-r));
    const good=chosen.map((j,i)=>quality[i][j]>=16 && clear[i]>=1.0);
    let bestStart=-1,bestEnd=-1,start=0;
    for(let i=0;i<=n;i++){
      if(i<n && !(i>0 && !good[i] && !good[i-1]) && clear[i]>=.75)continue;
      let a=start,b=i-1;while(a<=b && !good[a])a++;while(b>=a && !good[b])b--;
      if(b-a>bestEnd-bestStart){bestStart=a;bestEnd=b;}
      start=i+1;
    }
    if(bestStart<0 || bestEnd-bestStart<13 || good.slice(bestStart,bestEnd+1).filter(Boolean).length<.72*(bestEnd-bestStart+1))return null;
    const groove=1/(scale*frame.radius), segments=[];
    const extent=contours.reduce((r,line)=>line.reduce((v,p)=>Math.max(v,Math.hypot(...p)),r),0);
    for(const path of contours)for(let i=0;i<path.length;i++){
      const a=path[i],b=path[(i+1)%path.length],vx=b[0]-a[0],vy=b[1]-a[1];
      segments.push([a[0],a[1],vx,vy,vx*vx+vy*vy || 1]);
    }
    // A temple often reaches an eyebrow. Keep the continuous portion with
    // enough room for both grooves, without engraving an artificial join.
    let line=[],best=[];
    for(let i=bestStart;i<=bestEnd;i++){
      const xy=at(angles[i],radii[i]);
      const point=[(xy[0]-frame.cx)/frame.radius,(frame.cy-xy[1])/frame.radius];
      const near=segments.some(([x,y,vx,vy,denom])=>{
        const dx=point[0]-x,dy=point[1]-y,t=clamp((dx*vx+dy*vy)/denom,0,1);
        return Math.hypot(dx-t*vx,dy-t*vy)<1.30*groove;
      });
      if(near || Math.hypot(...point)>extent)line=[];
      else {line.push(point);if(line.length>best.length)best=line;}
    }
    if(best.length<8 || best.reduce((len,p,i)=>len+(i?Math.hypot(p[0]-best[i-1][0],p[1]-best[i-1][1]):0),0)<5*groove)return null;
    return [...best,...best.slice(1,-1).reverse()];
  }

  // At Mini scale a full dark iris and lashes may read as a single band. If
  // one eye is visibly more open, keep both upper strokes and fit the lower
  // edges independently. Require clear skin on either side of both bands.
  function inwardLowerLids(image,eyes,scale) {
    const median=values=>values.slice().sort((a,b)=>a-b)[Math.floor(values.length/2)];
    function edgeAt(points,u) {
      const i=points.findIndex((p,k)=>k && p[0]>=u);
      const [x,y]=points[i-1], [end,height]=points[i];
      return y+(height-y)*(u-x)/(end-x);
    }
    function trace(eye) {
      const [left,,,right]=eye, dx=right[0]-left[0], dy=right[1]-left[1];
      const width=Math.hypot(dx,dy), grooves=width*scale;
      if(width<20 || grooves<3 || grooves>6)return null;
      const at=(u,v)=>[left[0]+u*dx-v*dy,left[1]+u*dy+v*dx];
      const local=eye.map(([x,y])=>[
        ((x-left[0])*dx+(y-left[1])*dy)/width**2, ((y-left[1])*dx-(x-left[0])*dy)/width**2
      ]);
      const upper=local.slice(0,4), lower=[local[0],local[5],local[4],local[3]];
      if([upper,lower].some(line=>line.some(([u],i)=>i && u<=line[i-1][0])))return null;
      const sections=[];
      for(let column=0;column<15;column++){
        const u=.15+.05*column;
        // The landmark origin is at the image edge; pixel 0 is centered at .5.
        const tones=Array.from({length:76},(_,i)=>{
          const [x,y]=at(u,(i-35)/100);
          return interpolatedGray(image,x-.5,y-.5);
        });
        const dark=tones.slice(15,58).sort((a,b)=>a-b)[3];
        const above=median(tones.slice(2,11)), below=median(tones.slice(64,75));
        if(Math.min(above,below)-dark<15)return null;
        const cutoff=dark+.43*(.75*above+.25*below-dark);
        // A highlight can divide the iris. Choose the best supported connected
        // band, allowing a gap of up to one sixth of the eye width.
        const bands=[];
        for(let i=11;i<=59;i++)if(tones[i]<cutoff){
          if(!bands.length || i-bands.at(-1).at(-1)>17)bands.push([]);
          bands.at(-1).push(i);
        }
        const band=bands.sort((a,b)=>b.length-a.length)[0];
        if(!band || band.length<4 || band[0]===11 || band.at(-1)===59)return null;
        const crossing=(i,step)=>(i-35+step*(cutoff-tones[i])/(tones[i+step]-tones[i]))/100;
        sections.push({u,top:crossing(band[0],-1),bottom:crossing(band.at(-1),1)});
      }
      const opening=median(sections.map(s=>s.bottom-s.top))*grooves;
      if(opening<.50 || median(sections.map(s=>Math.abs(s.top-edgeAt(upper,s.u))))*grooves>.20)return null;
      // Fit every other section, suppress isolated lashes, then check the
      // intervening sections withheld from the fit. Anchor both real corners.
      const fit=sections.filter((s,i)=>i%2);
      const knots=[[0,0],...fit.map((s,i)=>[s.u,median([fit[Math.max(0,i-1)].bottom,s.bottom,
        fit[Math.min(fit.length-1,i+1)].bottom])]),[1,0]];
      const check=sections.filter((s,i)=>i%2===0);
      const errors=check.map(s=>Math.abs(edgeAt(knots,s.u)-s.bottom)*grooves);
      if(median(errors)>.15 || Math.max(...errors)>.35)return null;
      const change=median(sections.map(s=>edgeAt(knots,s.u)-edgeAt(lower,s.u)))*grooves;
      return {change,opening,line:[...eye.slice(0,4),...knots.slice(1,-1).reverse().map(([u,v])=>at(u,v))]};
    }
    const lids=eyes.map(trace);
    if(!lids.every(Boolean))return null;
    // Distinguish a genuine difference in opening from moving both lids
    // under a shadow. The width change must matter at the ball's groove.
    const [narrow,wide]=lids.slice().sort((a,b)=>a.opening-b.opening);
    return wide.opening-narrow.opening>.40 && narrow.change<-.15 && wide.change>.15 ?
      lids.map(lid=>lid.line) : null;
  }

  function attachMeasuredEye(path,contacts,eye) {
    let shortest=Infinity,join,entry;
    for(const p of contacts.length ? contacts : [path[0]])for(const corner of eye.corners){
      const gap=Math.hypot(corner[0]-p[0],corner[1]-p[1]);
      if(gap<shortest){join=p;entry=eye.line.indexOf(corner);shortest=gap;}
    }
    const i=path.indexOf(join);
    return [...path.slice(0,i+1),...eye.line.slice(entry),...eye.line.slice(0,entry+1),join,...path.slice(i+1)];
  }

  function measuredDrawing(image,landmarks,group,portraitDiameterGrooves,shadowFrame,headOnly=false,trackingGrooves,headFrame,compactBeardGrain=false,inward=null) {
    const people=landmarks.map(l=>portraitShapes(image,l,group));
    const beard=!group && !shadowFrame && portraitDiameterGrooves>0 && photographedFullBeard(image,landmarks[0]);
    const tracking=Number.isFinite(trackingGrooves) && trackingGrooves>=0 ? trackingGrooves : .5;
    const goatee=!group && !shadowFrame && !beard && photographedGoatee(image,landmarks[0],people[0]);
    if(beard || goatee){
      const person=people[0];
      person.head=[...(beard || goatee).outline,...person.head.slice(17)];
      person.goatee=[];
      if(goatee){
        const drop=goatee.jaw[8].map((v,k)=>v-landmarks[0][8][k]);
        for(let i=9;i<person.clothing.length;i++)person.clothing[i]=person.clothing[i].map((v,k)=>v+drop[k]);
      }
    }
    const swept=headOnly && !group && !beard && !goatee ? sweptTempleHair(image,landmarks[0],people[0],portraitDiameterGrooves):null;
    if(swept){
      const p=people[0],L=landmarks[0],dx=L[16][0]-L[0][0],dy=L[16][1]-L[0][1],w=p.width;
      const localV=q=>(-dy*(q[0]-L[0][0])+dx*(q[1]-L[0][1]))/(w*w);
      const v=swept.edge.map(localV),tip=v.at(-1);
      const indices=swept.side===1?[16,15,14,13,12,11,10,9]:[0,1,2,3,4,5,6,7];
      // Use one contour where the lock hugs the jaw, then let the photographed
      // tip separate once the steel ball can leave daylight beside the cheek.
      let fork=null;
      for(const i of indices){
        const y=localV(L[i]),k=v.findIndex(z=>z>=y);
        if(k<1 || y>=tip)break;
        const point=mix(swept.edge[k-1],swept.edge[k],(y-v[k-1])/(v[k]-v[k-1]));
        const gap=Math.hypot(point[0]-L[i][0],point[1]-L[i][1])/w;
        if(gap>.045 && y>.18 && tip-y>.14){fork={y,point,index:k};break;}
      }
      if(fork)swept.tail=[fork.point,...swept.edge.slice(fork.index)];
      // The outline carries the shared upper part of the side lock.
      const outer=p.head.map((q,i)=>{
        const side=swept.side===1?i>=9 && i<=20:i<=7 || i>=p.head.length-4;
        if(!side)return q;
        const y=localV(q),k=v.findIndex(z=>z>=y);
        if(k<1 || y>(fork?fork.y:tip))return q;
        const point=mix(swept.edge[k-1],swept.edge[k],(y-v[k-1])/(v[k]-v[k-1]));
        return point;
      });
      p.head=outer;
    }
    const clothes=group?groupClothes(image,people,landmarks):null;
    // Fit the full photographed silhouette, including hair and the outside of any glasses.
    const outlines=headOnly ? [...people[0].head,...people[0].sideHair.flat(),...people[0].glasses.flat(),...(swept?.tail || [])]
      : clothes ? [...people.flatMap(p=>p.head),...clothes.shape.flat()]
      : people.flatMap(p=>[...p.head,...p.clothing]);
    const xs=outlines.map(p=>p[0]),ys=outlines.map(p=>p[1]);
    let cx=(Math.min(...xs)+Math.max(...xs))/2,cy=(Math.min(...ys)+Math.max(...ys))/2;
    let radius=Math.max(...outlines.map(p=>Math.hypot(p[0]-cx,p[1]-cy)))/(headOnly ? .964 : .975);
    if(!group && !headOnly){
      const frame=soloFrame(people[0],landmarks[0]);
      ({cx,cy,radius}=frame);
      if(shadowFrame)Object.assign(shadowFrame,frame);
    }
    if(headFrame)Object.assign(headFrame,{cx,cy,radius,glasses:people[0].glasses,eyes:people[0].eyes});
    const norm=p=>[(p[0]-cx)/radius,(cy-p[1])/radius];
    const n=145, half=n/2,grid=p=>[half+p[0]*half,half-p[1]*half];
    const art=[];
    // Draw on separate masks before combining paths. This also clips shoulders hidden by
    // another head and turns measured eye and lip islands into holes in the face fill.
    const canvas=()=>{const c=document.createElement('canvas');c.width=n;c.height=n;return c.getContext('2d',{willReadFrequently:true});};
    const toMask=ctx=>{
      const a=ctx.getImageData(0,0,n,n).data;
      return Uint8Array.from({length:n*n},(_,i)=>
        a[4*i+3]>127 && Math.hypot((i%n+.5-half)/half,(Math.floor(i/n)+.5-half)/half)<.969 ? 1:0);
    };
    function paint(ctx,poly,erase=false) {
      if(poly.length<3)return;
      ctx.globalCompositeOperation=erase?'destination-out':'source-over';
      ctx.beginPath();
      const t=poly.map(p=>grid(norm(p)));
      ctx.moveTo((t[0][0]+t[t.length-1][0])/2,(t[0][1]+t[t.length-1][1])/2);
      for(let i=0;i<t.length;i++){
        const cur=t[i],next=t[(i+1)%t.length];
        ctx.quadraticCurveTo(cur[0],cur[1],(cur[0]+next[0])/2,(cur[1]+next[1])/2);
      }
      ctx.closePath();ctx.fill();
    }
    function inset(mask,level) {
      const d=Float32Array.from(mask,v=>v?1000:0),rt=Math.SQRT2;
      for(let y=1;y<n-1;y++)for(let x=1;x<n-1;x++){
        const i=y*n+x; if(d[i])d[i]=Math.min(d[i],d[i-1]+1,d[i-n]+1,d[i-n-1]+rt,d[i-n+1]+rt);
      }
      for(let y=n-2;y>=1;y--)for(let x=n-2;x>=1;x--){
        const i=y*n+x; if(d[i])d[i]=Math.min(d[i],d[i+1]+1,d[i+n]+1,d[i+n+1]+rt,d[i+n-1]+rt);
      }
      return Uint8Array.from(d,v=>v>=level?1:0);
    }
    function outline(mask,minimum=3) {
      return boundaries(mask,n,minimum).map(loop=>loop.map(([x,y])=>[(x-half)/half,(half-y)/half]));
    }
    if(!headOnly){
      const coats=canvas();
      for(const poly of (clothes?clothes.shape:people.map(p=>p.clothing)))paint(coats,poly);
      for(const p of people)paint(coats,p.head,true);
      const coatMask=toMask(coats);
      for(const line of outline(coatMask,15)){
        // A crop is an edge of the photograph, not a horizontal mark in the clothing.
        const bottomY=clothes ? norm([0,clothes.bottom])[1] : -2;
        const k=line.findIndex(p=>p[1]<bottomY+.023);
        if(k<0){art.push(line);continue;}
        let run=[];
        for(let i=1;i<=line.length;i++){
          const point=line[(k+i)%line.length];
          if(point[1]<bottomY+.023){
            if(run.length>5)art.push([...run,...run.slice(1,-1).reverse()]);
            run=[];
          }else run.push(point);
        }
      }
      if(clothes){
        for(const shape of clothes.marks)art.push(shape.map(norm));
        for(const seam of clothes.seams)art.push([...seam,...seam.slice(1,-1).reverse()].map(norm));
      }else art.push(...outline(inset(coatMask,4.8),15));
    }
    const groovesPerPixel = Number.isFinite(portraitDiameterGrooves) && portraitDiameterGrooves > 0
      ? portraitDiameterGrooves / (2 * radius) : 0;
    const grooveDistance = (a, b) => Math.hypot(a[0]-b[0], a[1]-b[1]) * groovesPerPixel;
    const inwardReplacements=new Map();
    let inwardSmile=null, inwardEyes=[], firstInwardFeature=0;
    for(const [owner,p] of people.entries()){
      const hair=canvas();
      const hairParts=group || p.recoveredHair ? [p.goatee] : [p.hair,...p.sideHair,p.goatee];
      for(const part of hairParts)paint(hair,part);
      if(p.goatee.length)paint(hair,p.mouth,true);
      const marks = landmarks[owner];
      // The brow and the upper eyelid each carve a full groove. Keep a visible
      // strip of sand between them, and resolve the width of the nose itself.
      const browsClear = Math.min(grooveDistance(marks[19], marks[37]), grooveDistance(marks[24], marks[44])) >= 1.65;
      const groupDetail = group && browsClear && grooveDistance(marks[31], marks[35]) >= 2.25;
      const eyeMarks=(!group && p.glasses.length) ? p.glasses : p.eyes;
      const hairMask=toMask(hair);
      // Explicit landmark paths keep small features even when they occupy less than
      // a couple of pixels of the fill mask. A group needs breathing room between them.
      let outer=p.head.map(norm);
      if(!group){
        for(let pass=0;pass<2;pass++)outer=outer.flatMap((point,i)=>{
          const next=outer[(i+1)%outer.length];
          return [mix(point,next,.25),mix(point,next,.75)];
        });
      }
      outer.faceOwner=owner;
      art.push(outer);
      if(swept?.tail){
        const edge=swept.tail.map(norm),strand=[...edge,...edge.slice(1,-1).reverse()];
        strand.featureOwner=owner;strand.ports=[0];art.push(strand);
      }

      const goateeSmile=goatee && smallGroupSmile(image,marks,groovesPerPixel || 48/(2*radius),tracking,true);
      if(goatee){
        const line=[...goatee.top,...goatee.top.slice(1,-1).reverse()].map(norm);
        line.featureOwner=owner;line.ports=[0,goatee.top.length-1];
        art.push(line);
      }
      if(beard){
        const smile=smallGroupSmile(image,marks,groovesPerPixel,tracking,true);
        const beardLines=beardStrokes(beard,marks,groovesPerPixel,tracking,smile);
        for(const stroke of beardLines){
          const line=[...stroke,...stroke.slice(1,-1).reverse()].map(norm);
          line.featureOwner=owner;
          line.faceOwner=owner;
          line.branchFeatures=true;
          line.ports=[0];
          art.push(line);
        }
        // At the Mini center's working size the two cheeks can fit while the
        // usual full-beard engraving cannot. Branch from the existing jaw
        // only along strands supported by the guest's photo.
        if(compactBeardGrain && headOnly && portraitDiameterGrooves>=24 && portraitDiameterGrooves<=36 && beardLines.length===2){
          const strokes=photographedBeardGrain(image,beard,marks,smile || p.mouth,beardLines,groovesPerPixel,tracking);
          for(const stroke of strokes){
            const line=[...stroke,...stroke.slice(1,-1).reverse()].map(norm);
            line.featureOwner=owner;
            line.ports=[0];
            art.push(line);
          }
        }
        // Enter the smile at a corner, using the beard as the approach.
        // The nose has its own return to the brow.
        const lips=(smile || p.mouth).map(norm);
        lips.featureOwner=owner;
        lips.ports=smile?.cornerIndices || [0,6];
        art.push(lips);
      }
      if((group || p.recoveredHair) && p.hair.length){
        let lower=p.hair.slice(p.hair.length/2);
        if(headOnly && !p.glasses.length && p.recoveredHair)lower=photographedFringe(image,marks,lower,groovesPerPixel);
        if(headOnly && p.frameBridge)lower=visibleTempleHair(lower,p.glasses,groovesPerPixel);
        if(swept){
          lower=swept.boundary.slice();
          // The second line leaves the off-center part and follows the visible
          // divide between the swept hair and the darker crown, then retraces.
          lower.splice(swept.part+1,0,...swept.sweep.slice(1),...swept.sweep.slice(0,-1).reverse());
        }
        lower=lower.map(norm);
        const hairline=[...lower,...lower.slice(1,-1).reverse()];
        if(group)hairline.faceOwner=owner;
        art.push(hairline);
      }
      if(hairParts.some(part=>part.length)) {
        const borders=outline(hairMask,5);
        if(group)for(const border of borders)border.faceOwner=owner;
        art.push(...borders);
        if(!group) art.push(...outline(inset(hairMask,4.6),8));
      }
      // Eyes and lips are terminal marks: return along the same groove and never
      // use them as short cuts to the other side of someone's face.
      if(inward)firstInwardFeature=art.filter(line=>line.length>2).length;
      const fold=goateeSmile ? goateeExpression(image,marks,goateeSmile,groovesPerPixel || 48/(2*radius)) :
        !group && !beard && compactSmile(image,marks,p,groovesPerPixel);
      let expressionFold=fold;
      let separateSmile=null;
      if(headOnly && !p.glasses.length && !beard && !goatee && !p.goatee.length && groovesPerPixel){
        const toothBand=smallGroupSmile(image,marks,groovesPerPixel,tracking);
        if(toothBand){
          const opening=photographedSmile(image,marks,groovesPerPixel,tracking);
          const lips=opening || photographedSmile(image,marks,groovesPerPixel,tracking,true) || toothBand;
          expressionFold=photographedSmileCrease(image,marks,p.width,lips,true) || fold;
          // The inward spiral can reach the smile on its own. Leave the skin
          // above a measured open mouth clear when there is no visible crease.
          if(inward && !expressionFold)separateSmile=opening;
        }
      }
      if (p.frameBridge) {
        const frame=spectacleStroke(p,groovesPerPixel);
        const line=frame.path.map(norm);
        line.ports=frame.ports;
        line.featureOwner=owner;line.faceOwner=owner;line.branchFeatures=true;
        art.push(line);
        if(inward && !inward.sharedCrop){
          const lids=p.glasses.map((rim,i)=>{
            const eye=p.eyes[i],width=Math.hypot(eye[0][0]-eye[3][0],eye[0][1]-eye[3][1]);
            return width>=15 && width*groovesPerPixel>=2.6 &&
              photographedLid(image,eye,[...rim,rim[0]],groovesPerPixel);
          });
          if(lids.every(Boolean)){
            // The inward spiral can visit each lid independently, leaving the
            // clear glass between the photographed eye and its rim untouched.
            inwardReplacements.set(line,spectacleStroke(p,groovesPerPixel,null,true).path.map(norm));
            inwardEyes=lids.map(lid=>lid.stroke.map(norm));
          }
        }
        const expression=expressionStroke(image,marks,p,beard ? [] : undefined,fold,beard ? groovesPerPixel : 0).path.map(norm);
        expression.featureOwner=owner;expression.ports=[0];
        art.push(expression);
        continue;
      }
      const gaze=headOnly && !p.glasses.length && !p.goatee.length && !beard && photographedGaze(image,p.eyes,groovesPerPixel);
      const lowerLids=inward && !gaze && !fold && !beard && !goatee && !p.goatee.length &&
        !p.glasses.length && inwardLowerLids(image,p.eyes,groovesPerPixel);
      for(const [i,eye] of (gaze ? [] : eyeMarks).entries()){
        const lid=eye.slice(0,4);
        const singleLid=fold || (beard && grooveDistance(eye[1],eye[5])<1.65);
        const line=(singleLid?[...lid,...lid.slice(1,-1).reverse()]:eye).map(norm);
        if(group || fold){line.featureOwner=owner;line.ports=[0,3];}
        art.push(line);
        if(lowerLids)inwardReplacements.set(line,lowerLids[i].map(norm));
      }
      if (((!group && !p.goatee.length) || groupDetail) && !p.glasses.length) {
        const {path, side} = expressionStroke(image,marks,p,beard ? [] : undefined,expressionFold,
          beard || expressionFold?.lipLoop ? groovesPerPixel : 0);
        // Join from the photographed side of the nose or from this eye's own brow.
        // Joining the eyes to each other would engrave a false spectacle bridge.
        const floor=gaze && Math.max(...gaze[side].corners.map(q=>q[1]));
        const trace=points=>(gaze ? attachMeasuredEye(points,points.filter(q=>q[1]<=floor),gaze[side]) : points).map(norm);
        const line=trace(path);
        line.ports = [0];  // reach this stroke at the outer brow
        line.featureOwner = owner;
        if(fold && !gaze){line.faceOwner=owner;line.branchFeatures=true;}
        art.push(line);
        const brow=gaze && !side ? p.brows[1].slice().reverse() : p.brows[1-side];
        const back=[...brow,...brow.slice(1,-1).reverse()];
        const other=(gaze ? attachMeasuredEye(back,brow,gaze[1-side]) : back).map(norm);
        if(fold && !gaze){other.faceOwner=owner;other.branchFeatures=true;}
        if (gaze || groupDetail || fold) {
          other.featureOwner = owner;
          other.ports = [gaze || side ? 0 : brow.length-1];
        }
        art.push(other);
        if(separateSmile){
          const nose=expressionStroke(image,marks,p,[],null).path;
          inwardReplacements.set(line,trace(nose));
          inwardSmile=separateSmile.map(norm);
        }
        continue;
      }
      if(!beard){
        const lips=p.mouth.map(norm);
        if(group){lips.featureOwner=owner;lips.ports=[9];}
        art.push(lips);
      }
      if(!group || p.width/radius>.56)art.push([...p.noseLine,...p.noseLine.slice(1,-1).reverse()].map(norm));
      // Offset rings around unframed eyes resemble glasses; put the fill in the hair and clothing.
      if(!group && !p.glasses.length){
        for(const brow of p.brows)art.push([...brow,...brow.slice(1,-1).reverse()].map(norm));
      }
    }
    const contours=art.filter(p=>p.length>2);
    // A tilted head can put a few hair points outside the shoulder crop.
    // Fit the traced picture as one piece before connecting it to the rim.
    if(!headOnly && !group){
      const extent=contours.reduce((r,line)=>line.reduce((v,p)=>Math.max(v,Math.hypot(...p)),r),0);
      if(extent>1+1e-8){
        const shrink=.975/extent;
        for(const line of contours)for(let i=0;i<line.length;i++)line[i]=line[i].map(v=>v*shrink);
      }
    }
    if(inward && contours[0]?.faceOwner===0){
      const frame={cx,cy,radius,person:people[0],landmarks:landmarks[0]};
      if(beard)frame.beardMask=[...beard.cheeks[0],...beard.moustache[0],...beard.moustache[1].slice().reverse(),
        ...beard.cheeks[1].slice().reverse(),...beard.outline.slice().reverse()];
      else if(goatee)frame.beardMask=[...goatee.top,...goatee.bottom.slice().reverse()];
      const lines=contours.map(line=>inwardReplacements.get(line) || line);
      if(inwardSmile)lines.push(inwardSmile);
      lines.push(...inwardEyes);
      const long=!inward.sharedCrop && !frame.beardMask && !swept && !frame.person.goatee.length &&
        inwardLongHair(image,frame,lines,firstInwardFeature,portraitDiameterGrooves,inward.neighbors);
      inward.contours=long ? long.lines : lines;
      if(!inward.sharedCrop && !long && !frame.beardMask &&
          (!frame.person.glasses.length || frame.person.frameBridge) && !frame.person.goatee.length && !inwardSmile)
        inward.expression=singleSmileLines(image,frame,lines,groovesPerPixel,tracking);
      inward.hair=GuestShadow.miniHair(image,long ? long.frame : frame,inward.contours,portraitDiameterGrooves,
        inward.sharedCrop ? null : hair=>{inward.partedHair=hair;});
      if(!long && !inward.sharedCrop && !inward.hair.length)
        inward.fringe=photographedFringeForMini(image,frame,groovesPerPixel,inward.contours);
    }
    return contours;
  }

  // Pack measured heads at one common scale. Retain the order of existing rows;
  // a single long row becomes a staggered group, still ordered from left to right.
  function arrangeFaces(people) {
    const width = mean(people.map(p => p.shape.width));
    const gap = .17 * width;
    const rows = [];
    for (const p of [...people].sort((a,b) => a.nose[1]-b.nose[1])) {
      let row = rows[rows.length-1];
      if (!row || p.nose[1] - mean(row.map(q => q.nose[1])) > .78*width) rows.push(row=[]);
      row.push(p);
    }
    if (rows.length === 1 && people.length > 2) {
      const sorted = rows.pop().sort((a,b) => a.nose[0]-b.nose[0]);
      const count = Math.ceil(Math.sqrt(sorted.length/2));
      for (let i=0;i<count;i++) rows.push(sorted.filter((p,j) => j%count === i));
    }

    const previous = [];
    for (const row of rows) {
      row.sort((a,b) => a.nose[0]-b.nose[0]);
      const eyeLevel = mean(row.map(p => p.nose[1]));
      let x = 0;
      for (const p of row) {
        const xx = [p.shape.head,...p.shape.locks].flat().map(v => v[0]);
        p.dx = x - Math.min(...xx);
        p.dy = -(p.localNoseY??p.nose[1]) + clamp(p.nose[1]-eyeLevel, -.12*width, .12*width);
        x += Math.max(...xx) - Math.min(...xx) + gap;
      }
      const current = [];
      for (const p of row) {
        p.dx -= (x-gap)/2;
        p.place = ([u,v]) => [u+p.dx,v+p.dy];
        // Sample the silhouette, including the long edges of a tilted jaw.
        for (const contour of [p.shape.head,...p.shape.locks]) {
          const edge=contour.map(p.place);
          for (let i=0;i<edge.length;i++) {
            const a=edge[i], b=edge[(i+1)%edge.length];
            const steps=Math.max(1, Math.ceil(Math.hypot(a[0]-b[0],a[1]-b[1])/(width*.04)));
            for(let k=0;k<steps;k++) current.push(mix(a,b,k/steps));
          }
        }
      }
      // Rows can nest into the spaces between the heads above without touching
      // them. Test neighboring contour points in x including the requested gap.
      previous.sort((a,b) => a[0]-b[0]);
      current.sort((a,b) => a[0]-b[0]);
      let y = 0, start = 0;
      for (const b of current) {
        while (start<previous.length && previous[start][0]<b[0]-gap) start++;
        for (let i=start;i<previous.length && previous[i][0]<=b[0]+gap;i++) {
          const a=previous[i], dx=a[0]-b[0];
          y=Math.max(y, a[1]-b[1]+Math.sqrt(Math.max(0,gap*gap-dx*dx)));
        }
      }
      for (const p of row) p.dy += y;
      for(const [u,v] of current) previous.push([u,v+y]);
    }
    return rows;
  }

  // A lock swept behind the shoulder can end sooner than the lock on the
  // other side. Follow both silhouette edges where the photographed hair is
  // consistently darker than both the skin and the surrounding background.
  function contrastedHair(image,frame,diameterGrooves,otherFaces=[]) {
    const {person,landmarks:L}=frame;
    if(diameterGrooves<62 || person.glasses.length || frame.beardStrokes)return null;
    const origin=mix(L[0],L[16],.5),dx=L[16][0]-L[0][0],dy=L[16][1]-L[0][1],width=Math.hypot(dx,dy);
    if(width<75)return null;
    const at=(u,v)=>[origin[0]+dx*u-dy*v,origin[1]+dy*u+dx*v];
    const median=a=>a.sort((x,y)=>x-y)[Math.floor(a.length/2)];
    const light=p=>{const [r,g,b]=rgb(image,p);return .299*r+.587*g+.114*b;};
    const skin=median([[-.18,.18],[.16,.2],[0,-.16],[-.11,-.13],[.11,-.13]].map(p=>light(at(...p))));
    const sides=[-1,1].map(side=>median([.55,.60,.65].flatMap(u=>
      [-.05,.14,.30,.44].map(v=>light(at(side*u,v))))));
    const scalp=median([[-.25,-.52],[-.14,-.64],[0,-.67],[.14,-.62],[.25,-.54]].map(p=>light(at(...p))));
    if(skin-Math.max(scalp,...sides)<52 || Math.abs(sides[0]-sides[1])>34)return null;
    const level=Math.min(skin-22,Math.max(scalp+34,Math.max(...sides)+16));
    const dark=t=>1/(1+Math.exp((t-level)/9));
    const grid=.01, first=.08, count=130, step=width*.007;
    function trace(angles,outer,boundary) {
      const rows=[],parents=[],ranges=Array.from({length:count},(_,j)=>first+j*grid);
      let prior=null;
      for(const [i,angle] of angles.entries()){
        const ca=Math.cos(angle),sa=Math.sin(angle);
        const end=at(1.39*ca,-1.39*sa);
        if(end[0]<step || end[1]<step || end[0]>=image.width-step || end[1]>=image.height-step)return null;
        const tones=ranges.map(r=>{
          const [x,y]=at(r*ca,-r*sa);
          return (2*light([x,y])+light([x-step,y])+light([x+step,y])+light([x,y-step])+light([x,y+step]))/6;
        });
        const hair=tones.map(dark),score=new Float32Array(count),parent=new Uint8Array(count);
        const limit=outer ? 10 : 8;
        const low=outer ? .47+.045*sa*sa : Math.abs(ca)>.75 ? .43 : .30;
        const high=outer ? 1.29 : boundary[i]-.055;
        const expected=outer ? .65+.10*sa*sa+.13*Math.max(0,-sa) : .50+.08*sa*sa;
        const next=new Float32Array(count);
        for(let j=0;j<count;j++){
          const r=ranges[j];
          if(r<low || r>high || j<14 || j+14>=count){score[j]=next[j]=-1e6;continue;}
          if(outer){
            const fg=median([3,6,10,14].map(n=>hair[j-n]));
            const bg=median([4,8,13].map(n=>hair[j+n]));
            const edge=median([3,5,8].map(n=>tones[j+n]-tones[j-n]));
            score[j]=47*(fg-bg)+.52*clamp(edge,-35,95)-35*Math.abs(r-expected);
          }else{
            const fg=median([3,6,10].map(n=>hair[j+n]));
            const bg=(hair[j-3]+hair[j-6])/2;
            const edge=median([3,5,8].map(n=>tones[j-n]-tones[j+n]));
            score[j]=45*(fg-bg)+.52*clamp(edge,-35,90)-45*Math.abs(r-expected);
          }
          let best=prior ? -Infinity : 0;
          if(prior)for(let k=Math.max(0,j-limit);k<=Math.min(count-1,j+limit);k++){
            const delta=Math.abs(j-k)*grid,value=prior[k]-155*delta-900*delta*delta;
            if(value>best){best=value;parent[j]=k;}
          }
          next[j]=score[j]+best;
        }
        rows.push(score);parents.push(parent);prior=next;
      }
      let j=prior.indexOf(Math.max(...prior));const evidence=[],distances=[];
      for(let i=angles.length-1;i>=0;i--){
        distances[i]=ranges[j];evidence[i]=rows[i][j];j=parents[i][j];
      }
      // One clear edge is insufficient. Both sides and the crown must have
      // enough local contrast to distinguish the hair from a wall or a tree.
      for(let band=0;band<3;band++){
        const part=evidence.slice(Math.floor(band*evidence.length/3),Math.floor((band+1)*evidence.length/3));
        if(median(part)<(outer?50:46) || part.filter(s=>s>22).length<.66*part.length)return null;
      }
      const radii=distances.map((r,i)=>(r*2+distances[Math.max(0,i-1)]+distances[Math.min(i+1,distances.length-1)])/4);
      return {radii,points:radii.map((r,i)=>at(r*Math.cos(angles[i]),-r*Math.sin(angles[i])))};
    }
    const start=-.91, end=Math.PI+.91;
    const angles=Array.from({length:95},(_,i)=>start+(end-start)*i/94);
    const outer=trace(angles,true);
    if(!outer)return null;
    const top=Array.from({length:45},(_,i)=>Math.PI*i/44);
    const inside=trace(top,false,top.map(a=>outer.radii[Math.round((a-start)/(end-start)*94)]));
    if(!inside || otherFaces.some(f=>outer.points.some(([x,y])=>Math.hypot(x-f.x,y-f.y)<.55*f.w)))return null;
    const inner=L.slice(0,17).concat(inside.points);
    const {cx,cy}=frame,margin=1-3.5/diameterGrooves;
    const priorExtent=Math.max(...person.head.map(p=>Math.hypot(p[0]-cx,p[1]-cy)));
    const radius=Math.max(frame.radius,priorExtent/margin);
    // Keep the original face size and location. Let the open tips leave
    // the portrait where the photograph would be cropped by its circle.
    const within=p=>Math.hypot(p[0]-cx,p[1]-cy)<=margin*radius;
    const middle=Math.floor(angles.length/2);
    let lo=middle,hi=middle;
    if(!within(outer.points[middle]))return null;
    while(lo>0 && within(outer.points[lo-1]))lo--;
    while(hi<outer.points.length-1 && within(outer.points[hi+1]))hi++;
    const depth=p=>((p[1]-origin[1])*dx-(p[0]-origin[0])*dy)/(width*width);
    if(hi-lo<.84*(angles.length-1) || [outer.points[lo],outer.points[hi]].some(p=>depth(p)<.39) ||
       !inner.every(within))return null;
    return {outside:outer.points.slice(lo,hi+1),inner,cx,cy,radius};
  }

  // Fit an outer contour only when both photographed locks continue below the jaw.
  // Foreground samples come from hair just outside the forehead. Learn the
  // background separately around each side: a dark tree can resemble the hair.
  function longHairSilhouette(image, frame, diameterGrooves, otherFaces=[], inward=false) {
    const {person,landmarks:L}=frame,crown=person.head.slice(17);
    const inside=person.hair.slice(crown.length).reverse();
    if(inside.length!==25 || person.glasses.length || frame.beardStrokes || diameterGrooves<(inward?35:62))return null;
    const locks=longHair(image,L,person,crown,inside,true);
    if(locks.length!==2)return null;
    const origin=mix(L[0],L[16],.5), dx=L[16][0]-L[0][0],dy=L[16][1]-L[0][1],span=Math.hypot(dx,dy);
    const at=(u,v)=>[origin[0]+u*dx-v*dy,origin[1]+u*dy+v*dx];
    const depth=([x,y])=>((y-origin[1])*dx-(x-origin[0])*dy)/(span*span);
    const radial=(a,r)=>at(.51*Math.cos(a)*r,-.66*Math.sin(a)*r);
    const distance=(p,q)=>Math.hypot(p[0]-q[0],p[1]-q[1]);
    // Presence of photographic material beyond the candidate edge is required.
    // Clamping a sampling ray at the edge of the photo would invent a silhouette.
    const rays=65,angles=Array.from({length:rays},(_,i)=>i*Math.PI/(rays-1));
    if(angles.some(a=>{const [x,y]=radial(a,1.66);return x<3 || y<3 || x>image.width-4 || y>image.height-4;}))return null;
    function color(a,r) {
      const p=radial(a,r), w=Math.max(.65,.005*span);
      const samples=[[p[0]-w,p[1]],[p[0]+w,p[1]],[p[0],p[1]-w],[p[0],p[1]+w]].map(q=>rgb(image,q));
      const [red,green,blue]=[0,1,2].map(j=>mean(samples.map(s=>s[j])));
      return [red-green,blue-green,.4*(.299*red+.587*green+.114*blue)];
    }
    function distanceToPalette(c, palette) {
      let one=Infinity,two=Infinity,three=Infinity;
      for(const k of palette){
        const d=(k[0]-c[0])**2+(k[1]-c[1])**2+(k[2]-c[2])**2;
        if(d<one){three=two;two=one;one=d;}
        else if(d<two){three=two;two=d;}
        else if(d<three)three=d;
      }
      return (Math.sqrt(one)+Math.sqrt(two)+Math.sqrt(three))/3;
    }
    const median3=(a,b,c)=>a+b+c-Math.min(a,b,c)-Math.max(a,b,c);
    const radii=Array.from({length:77},(_,i)=>.67+.01*i);
    const observations=angles.map((a,i)=>{
      const t=i*24/(rays-1),k=Math.min(23,Math.floor(t)), forehead=mix(inside[k],inside[k+1],t-k);
      const inner=distance(forehead,origin)/distance(radial(a,1),origin);
      return {inner,fg:Array.from({length:6},(_,j)=>color(a,inner+.035+j*.02)),
        bg:Array.from({length:8},(_,j)=>color(a,1.42+j*.24/7))};
    });
    const evidence=[];
    const scores=angles.map((a,i)=>{
      const neighborhood=observations.slice(Math.max(0,i-3),i+4);
      const fg=neighborhood.flatMap(o=>o.fg),bg=neighborhood.flatMap(o=>o.bg);
      const samples=Array.from({length:101},(_,k)=>{
        const c=color(a,.55+.01*k);
        return {c,h:distanceToPalette(c,fg),b:distanceToPalette(c,bg)};
      });
      evidence.push(samples);
      let accumulated=0;
      return radii.map((r,k)=>{
        const j=k+12,o=samples[j];
        accumulated+=clamp((o.b-o.h)/(3+.14*(o.b+o.h)),-6,6);
        if(r<observations[i].inner+.065)return -100;
        const local=[3,7,12].map(n=>{
          const inner=samples[j-n],outer=samples[j+n];
          return clamp(outer.h-outer.b+inner.b-inner.h,-35,35)+.75*Math.min(45,colorDistance(outer.c,inner.c));
        });
        return 1.5*accumulated+median3(...local)-10*Math.abs(r-1.07);
      });
    });
    // Find one continuous change from hair to background. Crossing a second
    // strong edge farther away on an isolated ray cannot move the entire crown.
    const parents=[];let prior=scores[0];
    for(const row of scores.slice(1)){
      const parent=new Uint8Array(radii.length);
      const next=row.map((s,j)=>{
        let best=-Infinity;
        for(let k=Math.max(0,j-7);k<=Math.min(radii.length-1,j+7);k++){
          const change=.01*Math.abs(j-k),value=prior[k]-160*change-800*change**2;
          if(value>best){best=value;parent[j]=k;}
        }
        return best+s;
      });
      prior=next;parents.push(parent);
    }
    let index=prior.indexOf(Math.max(...prior));
    const chosen=new Uint8Array(rays);
    for(let i=rays-1;i>=0;i--){chosen[i]=index;if(i)index=parents[i-1][index];}
    const supported=Array.from(chosen,(index,i)=>{
      const ray=evidence[i],j=index+12;
      const margins=[4,7,11].map(shift=>{
        const inner=ray[j-shift],outer=ray[j+shift];
        return Math.min(inner.b-inner.h,outer.h-outer.b);
      });
      return median3(...margins);
    });
    // Require the foreground and background to be distinguishable on BOTH
    // sides. A similarly colored wall, a clipped crop or one clear lock alone
    // cannot establish the rest of the photographed head.
    const half=Math.floor(rays/2);
    if([supported.slice(0,half),supported.slice(half+1)].some(side=>
      side.filter(margin=>margin>2.5).length<side.length/4))return null;
    const crownRadii=Array.from(chosen,j=>radii[j]);
    if(inward){
      // When bark and hair have similar colors, one angular scan can follow a
      // trunk well beyond the scalp. Fit the local slope from neighboring
      // photographed transitions, giving ambiguous colors little influence.
      const raw=crownRadii.slice();
      let fit=raw;
      for(let pass=0;pass<3;pass++){
        fit=raw.map((r,i)=>{
          let w0=0,w1=0,w2=0,y0=0,y1=0;
          for(let j=Math.max(0,i-18);j<=Math.min(rays-1,i+18);j++){
            const d=j-i, color=clamp((supported[j]-5)/15,.005,1);
            const consistent=Math.min(1,(.05/Math.max(.001,Math.abs(fit[j]-raw[j])))**2);
            const weight=Math.exp(-d*d/72)*color*consistent;
            w0+=weight; w1+=weight*d; w2+=weight*d*d;
            y0+=weight*raw[j]; y1+=weight*d*raw[j];
          }
          return (w2*y0-w1*y1)/(w0*w2-w1*w1);
        });
      }
      for(let i=0;i<rays;i++)crownRadii[i]=raw[i]+(fit[i]-raw[i])*clamp(Math.min(i,rays-1-i)/6,0,1);
    }
    const measured=angles.map((a,i)=>{
      const r=[1,4,6,4,1].reduce((sum,weight,j)=>sum+weight*crownRadii[clamp(i+j-2,0,rays-1)],0)/16;
      return radial(a,r);
    });

    const chin=depth(L[8]),middle=(measured.length-1)/2;
    const sides=locks.map((lock,i)=>{
      // longHair's first eight positions connect to the former head shape.
      // Join the independently measured side and scalp across their overlap.
      const edge=lock.slice(8).filter(p=>depth(p)<=chin+(inward ? .40 : .16));
      if(edge.length<7 || depth(edge[0])>-.10 || depth(edge.at(-1))<chin+.08)return null;
      const top=i===0 ? measured.slice(middle) : measured.slice(0,middle+1).reverse();
      let pos=0;const start=Math.max(-.27,depth(edge[0])),end=-.015;
      for(let k=1;k<top.length;k++){
        const v=depth(top[k]);if(v<start)continue;
        while(pos<edge.length-2 && depth(edge[pos+1])<v)pos++;
        const a=edge[pos],b=edge[pos+1],f=clamp((v-depth(a))/(depth(b)-depth(a) || 1),0,1);
        const side=mix(a,b,f),blend=clamp((v-start)/(end-start),0,1);
        if(distance(top[k],side)>.19*span)return null;
        top[k]=mix(top[k],side,blend*blend*(3-2*blend));
      }
      return top.concat(edge.filter(p=>depth(p)>depth(top.at(-1))+.009));
    });
    if(sides.some(s=>!s))return null;
    const outside=sides[0].slice().reverse().concat(sides[1].slice(1));
    if(otherFaces.some(f=>outside.some(([x,y])=>Math.hypot(x-f.x,y-f.y)<.55*f.w)))return null;
    // Use the guest's real jaw and forehead as the inner face
    // contour. The outside of the long hair stays open below the shoulders.
    const inner=L.slice(0,17).concat(inside);
    const average=outside.map((p,i)=>i>0 && i<outside.length-1 ? mix(p,mix(outside[i-1],outside[i+1],.5),.52):p);
    if(inward){
      // The long-lock check already required a band of photographed hair
      // inside both edges below the ears. Shade only this band and the crown.
      const innerSides=sides.map((side,i)=>side.filter(p=>depth(p)>0).map(([x,y])=>
        [x+(i ? -.25 : .25)*dx,y+(i ? -.25 : .25)*dy]));
      return {outside:average,inner,crown:measured,
        hair:[...average,...innerSides[1].reverse(),...inside,...innerSides[0]]};
    }
    // Ritter's refinement starts with the longest pair of endpoints, then
    // shifts the enclosing circle only as far as each remaining point needs.
    const points=average.concat(inner);
    const far=p=>points.reduce((a,b)=>distance(p,a)>distance(p,b)?a:b);
    const a=far(points[0]),b=far(a);
    let center=mix(a,b,.5),radius=distance(a,b)/2;
    for(const point of points){
      const gap=distance(point,center);if(gap<=radius)continue;
      const next=(radius+gap)/2;center=mix(center,point,(next-radius)/gap);radius=next;
    }
    radius=Math.max(frame.radius,radius/(1-3.6/diameterGrooves));
    if(radius>1.21*frame.radius)return null;
    return {outside:average,inner,cx:center[0],cy:center[1],radius};
  }

  function inwardLongHair(image,frame,contours,faceStart,diameter,neighbors) {
    const hair=longHairSilhouette(image,frame,diameter,neighbors,true);
    if(!hair)return null;
    const extent=Math.max(...contours.map(line=>Math.max(...line.map(p=>Math.hypot(...p)))));
    const radius=frame.radius*extent;
    const middle=axis=>{
      const q=hair.inner.map(p=>p[axis]);
      return (Math.min(...q)+Math.max(...q))/2;
    };
    // Keep the original physical face size. Shift toward the jaw to make
    // room for both locks, leaving some of the original head centering.
    const cx=.63*middle(0)+.37*frame.cx;
    let cy=middle(1);
    for(const [x,y] of hair.crown){
      const remaining=radius**2-(x-cx)**2;
      if(remaining<=0)continue;
      cy=Math.min(cy,y+Math.sqrt(remaining)-.5);
    }
    const norm=([x,y])=>[(x-cx)/radius,(cy-y)/radius];
    const outside=hair.outside.map(norm),inside=p=>Math.hypot(...p)<=1;
    const crown=outside.findIndex(inside);
    if(crown<0)return null;
    let end=crown;
    while(end+1<outside.length && inside(outside[end+1]))end++;
    // A stray lock tip can reenter along the rim. A second substantial
    // segment inside the disc needs a different crop to show the whole face.
    if(end-crown<18 || outside.slice(end+1).some(p=>Math.hypot(...p)<.92) ||
       (crown===0 && end===outside.length-1))return null;
    const edge=outside.slice(crown,end+1);
    // Intersect the real hair edge with the round crop. An open lock is
    // retraced so the ball never cuts a horizontal line between shoulders.
    function rim(a,b){
      const dx=b[0]-a[0],dy=b[1]-a[1],dot=a[0]*dx+a[1]*dy,dd=dx*dx+dy*dy;
      const t=(-dot+Math.sqrt(dot*dot+dd*(1-a[0]**2-a[1]**2)))/dd;
      return mix(a,b,clamp(t,0,1));
    }
    if(crown>0)edge.unshift(rim(edge[0],outside[crown-1]));
    if(end+1<outside.length)edge.push(rim(edge.at(-1),outside[end+1]));
    const transform=([u,v])=>norm([frame.cx+u*frame.radius,frame.cy-v*frame.radius]);
    const details=[hair.inner.map(norm),...contours.slice(faceStart).map(line=>line.map(transform))];
    if(details.some(line=>line.some(p=>!inside(p))))return null;
    return {lines:[[...edge,...edge.slice(1,-1).reverse()],...details],
      frame:{...frame,cx,cy,radius,clipHairToRim:true,person:{...frame.person,head:hair.outside,hair:hair.hair}}};
  }


  function longHair(image,L,shape,crown,hair,checkContinuity=false) {
    if(!hair.length)return [];
    const o=mix(L[0],L[16],.5), dx=L[16][0]-L[0][0], dy=L[16][1]-L[0][1], w=shape.width;
    const at=(u,v)=>[o[0]+dx*u-dy*v,o[1]+dy*u+dx*v];
    const skin=[mix(L[2],L[31],.55),mix(L[14],L[35],.55)].map(v=>rgb(image,v));
    const refs=crown.slice(3,-3).map((v,i)=>rgb(image,mix(v,hair[i+3],.5)))
      .filter(c=>Math.min(...skin.map(k=>colorDistance(c,k)))>30);
    if(refs.length<5)return [];
    const closeness=c=>Math.min(...refs.map(k=>colorDistance(c,k)));
    const chin=((L[8][1]-o[1])*dx-(L[8][0]-o[0])*dy)/(w*w);
    const median=values=>values.sort((a,b)=>a-b)[Math.floor(values.length/2)];
    const locks=[];
    for(const side of [-1,1]){
      let previous=.59;
      const samples=[],texture=[];
      for(let v=-.24;v<chin+.51;v+=.045){
        let best=null,maxScore=-Infinity;
        for(let u=.44;u<1.16;u+=.025){
          if(Math.abs(u-previous)>(samples.length ? .17 : .22))continue;
          const inside=rgb(image,at(side*(u-.052),v)),outside=rgb(image,at(side*(u+.052),v));
          const d=closeness(inside), edge=colorDistance(inside,outside);
          if(d>58 || edge<24 || closeness(outside)<d+12 ||
             Math.min(...skin.map(k=>colorDistance(inside,k)))<d+12)continue;
          const strength=Math.min(edge,90)-.55*d-200*Math.abs(u-previous);
          if(strength>maxScore){maxScore=strength;best=u;}
        }
        if(best===null){
          if(samples.length && v-samples.at(-1).v>.17)break;
          continue;
        }
        previous=best;
        samples.push({u:best,v});
        for(const depth of [.06,.11,.16]){
          const [x,y]=at(side*(best-depth),v),r=Math.max(1,.015*w);
          const g=grayAt(image,x,y);
          texture.push(Math.max(Math.abs(grayAt(image,x+r,y)-g),Math.abs(grayAt(image,x-r,y)-g)));
        }
      }
      if(samples.length<13 || samples[0].v>0 || samples.at(-1).v<chin+.15 || median(texture)<2.1)continue;
      const low=samples.filter(pt=>pt.v>.15);
      const good=(c)=>closeness(c)<57 && Math.min(...skin.map(k=>colorDistance(c,k)))>closeness(c)+18;
      const widthScores=low.map(({u,v})=>[.07,.13,.19,.25].filter(depth=>good(rgb(image,at(side*(u-depth),v)))).length);
      // Require a band a quarter of a face wide below the ear; an ear,
      // beard edge or dark shirt collar can supply a convincing single edge.
      if(median(widthScores)<4 || median(low.map(pt=>pt.u))<.57)continue;
      let edge=samples.map((pt,k)=>at(side*(pt.u*2+samples[Math.max(0,k-1)].u+
        samples[Math.min(k+1,samples.length-1)].u)/4,pt.v));
      if(checkContinuity){
        // A dark shirt can continue the edge of a lock through an exposed
        // ear and off the photograph. Follow the color inside the hair band.
        const tones=edge.map(([x,y])=>{
          const colors=[.06,.10,.15].map(d=>rgb(image,[x-side*d*dx,y-side*d*dy]));
          return [median(colors.map(([r,g,b])=>.30*r+.59*g+.11*b)),
            median(colors.map(([r,g,b])=>(r-b)/(r+g+b+15)))];
        });
        const top=tones.filter((_,i)=>samples[i].v<=.10);
        if(top.length>=4){
          const base=[0,1].map(j=>median(top.map(t=>t[j])));
          const tolerance=[32,.10].map((floor,j)=>Math.max(floor,3.5*median(top.map(t=>Math.abs(t[j]-base[j])))));
          let different=0;
          for(let i=top.length;i<edge.length;i++){
            different=tones[i].some((v,j)=>Math.abs(v-base[j])>tolerance[j]) ? different+1 : 0;
            if(different===3){edge=edge.slice(0,i-2);break;}
          }
        }
        const outside=edge.findIndex(([x,y])=>x<0 || x>=image.width || y<0 || y>=image.height);
        if(outside>=0)edge=edge.slice(0,outside);
        if(!edge.length || samples[edge.length-1].v<chin+.15)continue;
        edge=edge.map((p,i)=>i && i<edge.length-1 ? mix(p,mix(edge[i-1],edge[i+1],.5),.55) : p);
      }
      const root=crown[side>0?5:crown.length-6];
      const control=[edge[0][0],root[1]];
      const start=Array.from({length:8},(_,k)=>{
        const t=k/8;return mix(mix(root,control,t),mix(control,edge[0],t),t);
      });
      locks.push([...start,...edge]);
    }
    return locks;
  }

  // A full beard needs dark, textured hair on BOTH lower cheeks and below
  // the lip. A colored shirt, a goatee or one cheek in shadow is insufficient.
  function photographedFullBeard(image,L) {
    const origin=mix(L[0],L[16],.5), dx=L[16][0]-L[0][0], dy=L[16][1]-L[0][1], w=Math.hypot(dx,dy);
    if(w<48)return null;
    const at=(u,v)=>[origin[0]+dx*u-dy*v,origin[1]+dy*u+dx*v];
    const uv=([x,y])=>[((x-origin[0])*dx+(y-origin[1])*dy)/(w*w),((y-origin[1])*dx-(x-origin[0])*dy)/(w*w)];
    const Q=L.map(uv), light=c=>.30*c[0]+.59*c[1]+.11*c[2];
    const median=values=>values.sort((a,b)=>a-b)[Math.floor(values.length/2)];
    function patch(point,r=.018) {
      const values=[];
      for(const i of [-1,0,1])for(const j of [-1,0,1]) {
        values.push(rgb(image,at(point[0]+i*r,point[1]+j*r)));
      }
      return {point,color:[0,1,2].map(k=>median(values.map(c=>c[k])))};
    }
    function texture({point}) {
      // A few isolated pixels can change under JPEG compression or a small
      // shift in a landmark. Measure the typical fine texture over each patch.
      const grain=[],step=Math.max(1,w*.012);
      for(let i=-3;i<=3;i++)for(let j=-3;j<=3;j++){
        const [x,y]=at(point[0]+i*.0078,point[1]+j*.0078);
        const surround=(grayAt(image,x-step,y)+grayAt(image,x+step,y)+grayAt(image,x,y-step)+grayAt(image,x,y+step))/4;
        grain.push(Math.abs(grayAt(image,x,y)-surround));
      }
      return median(grain);
    }
    const cheek=[mix(Q[2],Q[31],.5),mix(Q[14],Q[35],.5)].map(([u,v])=>patch([u,v-.06]));
    const hair=[[5,48],[11,54],[8,57]].map(([a,b])=>patch(mix(Q[a],Q[b],a===8?.30:.22)));
    const exposure=clamp(mean(cheek.map(p=>light(p.color)))/160,.5,1);
    if(!cheek.every((skin,k)=>light(hair[k].color)<.70*light(skin.color) && light(skin.color)-light(hair[k].color)>32*exposure) ||
       light(hair[2].color)>.72*Math.min(...cheek.map(p=>light(p.color))) ||
       median(hair.map(texture))<Math.max(1.2*exposure,.65*exposure+1.10*median(cheek.map(texture))))return null;
    function tone(u,v,side) {
      const a=hair[side].color,b=cheek[side].color;
      const c=rgb(image,at(u,v));let score=0,den=0;
      for(let k=0;k<3;k++){score+=(c[k]-a[k])*(b[k]-a[k]);den+=(b[k]-a[k])**2;}
      return score/den;
    }
    const cheeks=[];
    for(const side of [0,1]) {
      const sign=side?1:-1, corner=Q[side?54:48], inner=corner[0];
      const run=[];let last=null;
      for(let n=0;n<=20;n++) {
        const u=inner+(sign*.48-inner)*n/20;
        let best=null;
        const floor=mix(Q[side?35:31],Q[27],Math.min(.98,.04+.9*(n/20)**1.5))[1];
        for(let v=floor;v<=corner[1]+.039;v+=.008) {
          if(last!==null && Math.abs(v-last)>.105)continue;
          const above=.5*(tone(u,v-.03,side)+tone(u,v-.055,side));
          const below=.5*(tone(u,v+.03,side)+tone(u,v+.055,side));
          if(above<.46 || below>.47 || above-below<.28) continue;
          const score=above-below-.58*Math.abs(tone(u,v,side)-.49)-(last===null?0:1.8*Math.abs(v-last));
          if(!best || score>best.score)best={v,score};
        }
        if(best){run.push([u,best.v]);last=best.v;}
        else if(run.length && Math.abs(u-run.at(-1)[0])>.057)break;
      }
      if(run.length<9 || Math.abs(run[0][0]-run.at(-1)[0])<.155)return null;
      const smooth=run.map((a,i)=>i && i<run.length-1 ? [a[0],.50*a[1]+.25*(run[i-1][1]+run[i+1][1])]:a);
      cheeks.push(smooth.reverse().map(p=>at(...p)));
    }
    // Search beyond the landmark jaw for the change from beard to clothing
    // or background. Short unsupported pieces keep their landmark boundary.
    const focus=mix(L[33],L[57],.39), jaw=L.slice(0,17).map(p=>p.slice()), evidence=[];
    for(let i=2;i<=14;i++) {
      const p=L[i],vx=p[0]-focus[0],vy=p[1]-focus[1],len=Math.hypot(vx,vy),nx=vx/len,ny=vy/len;
      const point=(rad,t=0)=>[p[0]+w*(nx*rad-ny*t),p[1]+w*(ny*rad+nx*t)];
      const hairColor=hair[i<7?0:i>9?1:2].color;
      let best=null;
      for(let rad=0;rad<.256;rad+=.009) {
        const inside=[-.024,0,.024].map(t=>rgb(image,point(rad-.035,t)));
        const outside=[-.024,0,.024].map(t=>rgb(image,point(rad+.035,t)));
        const contrast=(a,b)=>Math.hypot(.7*(light(a)-light(b)),1.6*((a[0]-a[2])-(b[0]-b[2])));
        const delta=median(inside.map((v,k)=>contrast(v,outside[k])));
        const before=median(inside.map(v=>contrast(v,hairColor))),after=median(outside.map(v=>contrast(v,hairColor)));
        // Blue cloth can be as dark as black hair, but it changes hue.
        if(before>66 || after-before<9 || delta<20)continue;
        const score=delta+.45*(after-before)-60*rad;
        if(!best || score>best.score)best={score,rad};
      }
      evidence[i]=best?.rad ?? null;
    }
    for(let i=1;i<=15;i++) {
      let count=0,total=0,weight=0;
      for(let j=Math.max(1,i-2);j<=Math.min(15,i+2);j++) {
        if(j===1 || j===15) {weight+=3-Math.abs(i-j);continue;}
        if(evidence[j]==null)continue;
        count++;const n=3-Math.abs(i-j); total+=n*evidence[j];weight+=n;
      }
      if(count<2)continue;
      const offset=total/weight;
      const v=[L[i][0]-focus[0],L[i][1]-focus[1]],len=Math.hypot(...v);
      jaw[i]=L[i].map((x,k)=>x+offset*w*v[k]/len);
    }
    // The 17 anatomical landmarks can be a long way apart on a wide chin.
    // Follow the hair-to-neck or hair-to-shirt edge between them. Use the
    // coarse contour as a prior where black clothing merges with the hair.
    const offsets=Array.from({length:39},(_,i)=>(i-16)*.007);
    const lower=[];
    for(let column=0;column<=40;column++) {
      const k=4+column/5;
      const i=Math.floor(k), t=k-i, p=mix(jaw[i],jaw[i+1],t);
      const vx=p[0]-focus[0],vy=p[1]-focus[1],r=Math.hypot(vx,vy),nx=vx/r,ny=vy/r;
      const along=(rad,tangent=0)=>[p[0]+w*(nx*rad-ny*tangent),p[1]+w*(ny*rad+nx*tangent)];
      const cost=offsets.map(offset=>{
        const edge=[-.012,0,.012].map(t=>{
          const a=rgb(image,along(offset-.017,t)),b=rgb(image,along(offset+.017,t));
          const inside=rgb(image,along(offset-.037,t)),outside=rgb(image,along(offset+.037,t));
          // A change in hue still marks the silhouette against dark fabric.
          const jump=(u,v)=>Math.hypot(.75*(light(u)-light(v)),1.5*(u[0]-u[2]-v[0]+v[2]));
          const support=Math.min(jump(a,b),jump(inside,outside));
          return Math.max(0,support-.52*jump(a,inside)-.38*jump(b,outside));
        });
        return Math.min(85,median(edge))-65*Math.abs(offset);
      });
      const prev=lower.at(-1);
      const score=[],back=[];
      for(const [j,offset] of offsets.entries()){
        let best=0,index=j;
        if(prev){best=-Infinity;
          for(let n=Math.max(0,j-10);n<=Math.min(offsets.length-1,j+10);n++){
            const change=Math.abs(offset-offsets[n]);
            const value=prev.score[n]-315*change-2400*change**2;
            if(value>best){best=value;index=n;}
          }
        }
        const fade=clamp(Math.min(k-4,12-k),0,1);
        score.push(best+cost[j]*fade-230*(1-fade)*Math.abs(offset));
        back.push(index);
      }
      lower.push({along,score,back});
    }
    const last=lower.at(-1).score;
    let best=last.indexOf(Math.max(...last));
    const points=Array(lower.length);
    for(let i=lower.length-1;i>=0;i--){
      points[i]=lower[i].along(offsets[best]);best=lower[i].back[best];
    }
    const edge=points.map((p,i)=>i && i+1<points.length ? mix(p,mix(points[i-1],points[i+1],.5),.35):p);
    const outline=[...jaw.slice(0,4),...edge,...jaw.slice(13)];
    for(let i=4;i<=12;i++)jaw[i]=edge[(i-4)*5];

    // Trace the upper moustache toward each nostril; the center can be
    // indistinguishable from the shadow already engraved beneath the nose.
    const moustache=[];
    for(const side of [0,1]) {
      const wing=Q[side?35:31],corner=Q[side?54:48],points=[];
      let previous=uv(cheeks[side].at(-1))[1];
      for(let i=0;i<=18;i++) {
        const t=i/18,u=mix(corner,wing,t)[0];let best=null;
        for(let v=wing[1]-.058;v<=corner[1]-.028;v+=.006) {
          if(Math.abs(v-previous)>.067)continue;
          const upper=tone(u,v-.022,side),lower=tone(u,v+.028,side);
          if(upper<.48 || lower>.46 || upper-lower<.26)continue;
          const score=upper-lower-.5*Math.abs(tone(u,v,side)-.43)-2*Math.abs(v-previous);
          if(!best || score>best.score)best={v,score};
        }
        if(!best)break;
        points.push(at(u,best.v));previous=best.v;
      }
      moustache.push(points);
    }
    // Sample evenly spaced roots across the photographed beard. From each,
    // follow a dark run where the image changes more across the hair than
    // along it. Preserve the naturally differing lengths at the two sides.
    const fibers=[], bottom=outline.slice(4,-4);
    const lengths=[0];
    for(let k=1;k<bottom.length;k++)lengths.push(lengths[k-1]+Math.hypot(bottom[k][0]-bottom[k-1][0],bottom[k][1]-bottom[k-1][1]));
    const bright=(u,v)=>light(rgb(image,at(u,v)));
    for(const f of [.50,.20,.80,.35,.65,.075,.925,.425,.575,.125,.875,.275,.725]) {
      const d=f*lengths.at(-1), k=lengths.findIndex(v=>v>d), t=(d-lengths[k-1])/(lengths[k]-lengths[k-1]);
      const start=mix(bottom[k-1],bottom[k],t), base=uv(start),side=base[0]<0?0:1;
      const a=uv(bottom[k-1]),b=uv(bottom[k]),tx=b[0]-a[0],ty=b[1]-a[1];
      let best=null;
      for(const slope of [-.75,-.45,-.15,.15,.45,.75]) {
        const line=[start],dx=slope/Math.hypot(1,slope),dy=-1/Math.hypot(1,slope);
        if((dx*ty-dy*tx)/Math.hypot(tx,ty)<.42)continue;
        let score=0;
        for(let n=1;n<=24;n++) {
          const t=n*.014, u=base[0]+dx*t, v=base[1]+dy*t, p=at(u,v);
          if(!insidePolygon(p,outline) || (n>=3 && tone(u,v,side)>.45))break;
          const across=Math.abs(bright(u-.014*dy,v+.014*dx)-bright(u+.014*dy,v-.014*dx));
          const along=Math.abs(bright(u-.014*dx,v-.014*dy)-bright(u+.014*dx,v+.014*dy));
          // Adjacent beard hairs usually share a direction. The pixels can
          // outweigh that preference wherever a tuft follows another slope.
          score+=1+clamp((across-along)/17,-.7,1)-.26*Math.abs(slope-.6*base[0]);line.push(p);
        }
        if(line.length>=6 && (!best || score>best.score))best={line,score,slope};
      }
      if(!best)continue;
      // Follow local changes in the direction of the hair instead of
      // continuing in a straight line through the whole tuft.
      let u=base[0],v=base[1],direction=best.slope;
      const curved=[start];
      for(let j=1;j<best.line.length;j++) {
        let turn=direction, strongest=-Infinity;
        for(const shift of [-.6,-.3,0,.3,.6]){
          const slope=clamp(direction+shift,-1.1,1.1),dx=slope/Math.hypot(1,slope),dy=-1/Math.hypot(1,slope);
          let quality=0;
          for(let k=1;k<=3;k++){
            const x=u+k*.012*dx,y=v+k*.012*dy;
            const across=Math.abs(bright(x-.012*dy,y+.012*dx)-bright(x+.012*dy,y-.012*dx));
            const along=Math.abs(bright(x-.012*dx,y-.012*dy)-bright(x+.012*dx,y+.012*dy));
            quality+=clamp((across-along)/18,-.8,1);
          }
          quality-=.48*Math.abs(shift)+.90*Math.abs(slope-best.slope);
          if(quality>strongest){strongest=quality;turn=slope;}
        }
        direction=.61*direction+.39*turn;
        const step=.014/Math.hypot(1,direction);u+=step*direction;v-=step;
        const pt=at(u,v);
        if(!insidePolygon(pt,outline) || (j>2 && tone(u,v,side)>.45) || (j>13 && strongest<-.22))break;
        curved.push(pt);
      }
      if(curved.length>5)fibers.push(curved);
    }
    return {jaw,outline,cheeks,moustache,fibers};
  }

  // A chin lock extends below the anatomical jaw, with bare, brighter skin
  // under both mouth corners. Follow the dark-to-light boundary into the neck.
  function photographedGoatee(image,L,shape,allowUnevenLight=false) {
    if(!shape.goatee.length || !hasBeardTexture(image,L,shape.width))return null;
    const dx=L[16][0]-L[0][0],dy=L[16][1]-L[0][1],w=shape.width;
    const at=(u,v)=>[L[8][0]+dx*u-dy*v,L[8][1]+dy*u+dx*v];
    const column=([x,y])=>((x-L[8][0])*dx+(y-L[8][1])*dy)/(w*w);
    const median=values=>values.sort((a,b)=>a-b)[Math.floor(values.length/2)];
    function light(u,v) {
      return median([-.008,0,.008].map(t=>grayAt(image,...at(u+t,v))));
    }
    const cheek=[];
    let strong=0;
    for(const depth of [.35,.55]) {
      const base=mix(L[57],L[8],depth), sides=[];
      for(const across of [-.23,0,.23]){
        const values=[];
        for(const a of [-.04,0,.04])for(const b of [-.10,0,.10])
          values.push(grayAt(image,...base.map((v,k)=>v+(a+across)*(L[54][k]-L[48][k])+b*(L[8][k]-L[57][k]))));
        sides.push(median(values));
      }
      const skin=Math.min(sides[0],sides[2]);
      // Allow uneven light across the cheeks. Both sides still have to be
      // lighter than the tuft, with a strong drop from their mean.
      if(sides[1]>.79*(sides[0]+sides[2])/2)return null;
      if(sides[1]<=.90*skin && skin-sides[1]>=9)strong++;
      else if(!allowUnevenLight || sides[1]>.94*skin || skin-sides[1]<7)return null;
      cheek.push(skin);
    }
    if(!strong)return null;
    const skin=mean(cheek);
    function edge(u,prior) {
      let best=null;
      for(let v=prior===null ? .046 : -.104;v<=.278;v+=.004){
        if(prior!==null && Math.abs(v-prior)>.055)continue;
        const inner=(light(u,v-.014)+light(u,v-.028))/2, outer=(light(u,v+.014)+light(u,v+.028))/2;
        if(inner>.48*skin || outer-inner<Math.max(9,.10*skin))continue;
        const delta=light(u,v+.009)-light(u,v-.009);
        const score=.7*delta+.3*(outer-inner)-(prior===null ? 0 : 90*Math.abs(v-prior));
        if(!best || score>best.score)best={u,v,score};
      }
      return best;
    }
    const middle=edge(0,null);
    if(!middle)return null;
    const slices=[middle];
    for(const sign of [-1,1]){
      let prev=middle;
      for(let i=1;i<=23;i++){
        const next=edge(sign*i*.014,prev.v);
        if(!next)break;
        if(sign<0)slices.unshift(next);else slices.push(next);
        prev=next;
      }
    }
    if(slices[0].u>-.13 || slices.at(-1).u<.13)return null;
    const bottom=slices.map((c,i)=>at(c.u,i && i+1<slices.length ? (slices[i-1].v+2*c.v+slices[i+1].v)/4:c.v));
    const top=slices.map(({u,v})=>{
      // First sustained return to bare chin above the dark lock.
      let t=v-.014;
      for(;t>-.13;t-=.006)if(light(u,t)>.58*skin && light(u,t-.014)>.62*skin)break;
      return at(u,t);
    }).map((p,i,a)=>i && i+1<a.length ? mix(p,mix(a[i-1],a[i+1],.5),.55):p);
    let left=5,right=11;
    while(left>1 && column(L[left])>=slices[0].u)left--;
    while(right<15 && column(L[right])<=slices.at(-1).u)right++;
    const outline=[...L.slice(0,left+1),...bottom,...L.slice(right,17)];
    const jaw=L.slice(0,17);
    for(let i=left+1;i<right;i++){
      const u=column(L[i]),index=slices.reduce((a,b,k)=>Math.abs(b.u-u)<Math.abs(slices[a].u-u)?k:a,0);
      jaw[i]=bottom[index];
    }
    return {outline,jaw,top,bottom};
  }

  // Follow individual dark runs from a photographed chin tuft toward the lip.
  // Outside the measured tuft, a strand must stay darker than the skin on both sides.
  function chinStrands(image,L,chin,groovesPerPixel){
    const width=Math.hypot(L[16][0]-L[0][0],L[16][1]-L[0][1]);
    const across=L[16].map((v,k)=>(v-L[0][k])/width),up=[across[1],-across[0]];
    const mask=[...chin.top,...chin.bottom.slice().reverse()],lines=[];
    const dot=(p,v)=>p[0]*v[0]+p[1]*v[1],lip=dot(L[57],up);
    const delta=Math.max(1,.18/groovesPerPixel),probe=Math.max(1,.012*width);
    const light=(q,axis,step=0)=>grayAt(image,q[0]+step*axis[0],q[1]+step*axis[1]);
    const candidates=[];
    for(const [k,bottom] of chin.bottom.entries()){
      const root=mix(bottom,chin.top[k],.23);let best=null;
      for(const slope of [-.7,-.42,-.18,0,.18,.42,.7]){
        const len=Math.hypot(1,slope),dir=up.map((v,i)=>(v+across[i]*slope)/len);
        const normal=[-dir[1],dir[0]],points=[];let evidence=0,contrast=0;
        for(let step=0;step<.45*width;step+=delta){
          const point=root.map((v,i)=>v+dir[i]*step);
          if(dot(point,up)>lip-.018*width)break;
          const on=.5*light(point,up)+.25*(light(point,dir,probe*.5)+light(point,dir,-probe*.5));
          if(!insidePolygon(point,mask)){
            if(Math.abs(dot(point,across)-dot(L[57],across))>.12*width)break;
            const bare=Math.min(...[-1,1].map(sign=>
              (light(point,across,sign*.12*width)+light(point,across,sign*.15*width))/2));
            if(bare-on<Math.max(12,.14*bare))break;
          }
          const sides=[light(point,normal,-probe),light(point,normal,probe)];
          const cross=(sides[0]+sides[1])/2-on,along=Math.abs(light(point,dir,probe)-light(point,dir,-probe));
          contrast+=Math.max(0,cross);evidence+=Math.max(-.65,Math.min(1.6,(cross-.25*along)/12));
          points.push(point);
        }
        const length=(points.length-1)*delta*groovesPerPixel;
        if(length<2.4 || contrast/points.length<2.5)continue;
        const score=length*(.6+evidence/points.length);
        if(!best || score>best.score)best={points,score};
      }
      if(best)candidates.push(best);
    }
    for(const {points} of candidates.sort((a,b)=>b.score-a.score)){
      const center=points[Math.floor(points.length/2)];
      if(lines.some(line=>{
        const other=line[Math.floor(line.length/2)];
        return Math.abs(dot(center,across)-dot(other,across))*groovesPerPixel<1.7;
      }))continue;
      points.chinStrand=true;
      lines.push(points);
    }
    // Follow the lighter break between a central lock below the lip and
    // the tuft on the chin. A single long straight stroke resembles a crease.
    const pieces=[];
    for(const line of lines){
      if(line.length<5 || line.length*delta*groovesPerPixel<=5.8){pieces.push(line);continue;}
      const lo=Math.floor(line.length*.33),hi=Math.floor(line.length*.7);
      let gap=lo,max=-Infinity;
      for(let i=lo;i<=hi;i++){
        const v=(light(line[i-1],up)+light(line[i],up)+light(line[i+1],up))/3;
        if(v>max){max=v;gap=i;}
      }
      const half=Math.ceil(1.15/(delta*groovesPerPixel));
      for(const range of [line.slice(0,Math.max(0,gap-half)),line.slice(gap+half)]){
        if(range.length>1){range.chinStrand=true;pieces.push(range);}
      }
    }
    // Give the sides first access to the clearing spiral. Reserve the limited
    // space on either side before the better-lit middle of the tuft.
    const center=dot(L[8],across);
    return pieces.sort((a,b)=>Math.abs(dot(b[0],across)-center)-Math.abs(dot(a[0],across)-center));
  }

  // Track the edge between the dark moustache and the redder upper lip.
  // Search above the measured tooth opening, below the nose. The cheek
  // crease to either side is outside this strip.
  function goateeExpression(image,L,smile,groovesPerPixel) {
    const [a,b]=smile.corners, dx=b[0]-a[0],dy=b[1]-a[1],width=Math.hypot(dx,dy);
    const at=(u,v)=>[a[0]+dx*u-dy*v,a[1]+dy*u+dx*v];
    const uv=([x,y])=>[((x-a[0])*dx+(y-a[1])*dy)/width**2,((y-a[1])*dx-(x-a[0])*dy)/width**2];
    const lip=smile.toothTop.map(uv), tip=uv(L[33]), rows=[];
    function color(u,v){
      const c=rgb(image,at(u,v));
      return .30*c[0]+.59*c[1]+.11*c[2]+.90*(c[0]-.63*c[1]-.37*c[2]);
    }
    for(let i=0;i<=28;i++){
      const u=.035+i*.93/28;
      const k=lip.findIndex(q=>q[0]>=u), p=lip[Math.max(0,k-1)],q=lip[k<0?lip.length-1:k];
      const tooth=p[1]+(q[1]-p[1])*clamp((u-p[0])/(q[0]-p[0] || 1),0,1);
      const arch=Math.sin(Math.PI*u), base=tooth-.055-.105*arch;
      const levels=[];
      for(let j=-9;j<=9;j++){
        const v=base+j*.010;
        if(v>tooth-.035 || v<Math.max(tip[1]+.018,tooth-.070-.21*arch))continue;
        const edges=[-.014,0,.014].map(t=>{
          const c=color(u+t,v-.018), d=color(u+t,v+.023);
          const lipSide=(d-c)+.28*(color(u+t,v+.047)-color(u+t,v-.038));
          // Near a corner, the outer dark hairs stand above the lip against
          // lighter cheek. Switch to their skin-to-hair edge at the tip.
          const cheekSide=grayAt(image,...at(u+t,v-.035))-grayAt(image,...at(u+t,v+.024));
          const center=clamp((Math.min(u,1-u)-.12)/.17,0,1);
          return center*lipSide+(1-center)*cheekSide;
        }).sort((h,k)=>h-k);
        const strength=edges[1], quality=clamp(strength,-50,85)-80*Math.abs(v-base);
        let best=quality,parent=null;
        if(i){
          best=-Infinity;
          for(const prior of rows[i-1]){
            const delta=Math.abs(prior.v-v), score=quality+prior.score-380*delta-2100*delta**2;
            if(score>best){best=score;parent=prior;}
          }
        }
        levels.push({u,v,strength,score:best,parent});
      }
      if(!levels.length)break;
      rows.push(levels);
    }
    let half=[],other=[],side=0;
    if(rows.length===29){
      let node=rows.at(-1).reduce((a,b)=>a.score>b.score?a:b), edge=[];
      while(node){edge.unshift(node);node=node.parent;}
      const line=edge.map((p,i)=>at(p.u,i && i+1<edge.length ? (edge[i-1].v+2*p.v+edge[i+1].v)/4 : p.v));
      const mid=edge.reduce((best,p,i)=>Math.abs(p.u-tip[0])<Math.abs(edge[best].u-tip[0]) ? i:best,14);
      const halves=[line.slice(0,mid+1).reverse(),line.slice(mid)], scores=[edge.slice(0,mid),edge.slice(mid+1)].map(part=>{
        const support=part.map(p=>p.strength).sort((a,b)=>a-b);
        return support[Math.floor(support.length/2)] || 0;
      });
      side=scores[1]>scores[0]?1:0;
      if(scores[side]>10) {
        half=halves[side];other=halves[1-side];
        // End near the center on a small portrait. Two marks less than a
        // groove apart between the nose and the lip would merge.
        if(scores[1-side]<10 || width*groovesPerPixel<5.5)other=[];
      }
    }
    if(!half.length){
      side=Math.hypot(...L[31].map((v,i)=>v-a[i]))<=Math.hypot(...L[35].map((v,i)=>v-b[i])) ? 0:1;
      half=[mix(L[side?35:31],smile.corners[side],.5)];
    }
    const port=smile.cornerIndices[side], corner=smile.corners[side];
    const moustache=[...other,...other.slice(0,-1).reverse(),
      ...half,corner,...smile.slice(port+1,-1),...smile.slice(0,port+1),...half.slice().reverse()];
    return {moustache,upperLip:other.slice().reverse().concat(half)};
  }

  function photographedBeardGrain(image,beard,L,mouth,cheeks,groovesPerPixel,tracking){
    const distance=(a,b)=>Math.hypot(a[0]-b[0],a[1]-b[1]);
    function clearance(p,line){
      let best=Infinity;
      for(let i=1;i<line.length;i++){
        const a=line[i-1],b=line[i],dx=b[0]-a[0],dy=b[1]-a[1];
        const t=clamp(((p[0]-a[0])*dx+(p[1]-a[1])*dy)/(dx*dx+dy*dy || 1),0,1);
        best=Math.min(best,Math.hypot(p[0]-a[0]-t*dx,p[1]-a[1]-t*dy));
      }
      return best*groovesPerPixel;
    }
    const outline=beard.outline.slice(3,-3), protectedLines=[mouth,[...L.slice(48,60),L[48]],...cheeks];
    const lengths=[0];
    for(let i=1;i<outline.length;i++)lengths.push(lengths.at(-1)+distance(outline[i],outline[i-1]));
    const width=distance(L[0],L[16]),across=L[16].map((v,i)=>(v-L[0][i])/width),up=[across[1],-across[0]];
    const choices=[];
    const mouthCenter=mouth.reduce((a,p)=>[a[0]+p[0]/mouth.length,a[1]+p[1]/mouth.length],[0,0]);
    // Establish the beard's own hair tone at its border, and stop if a stroke
    // approaches the brighter lip, skin or an existing cheek line.
    for(let rootDistance=.7/groovesPerPixel;rootDistance<lengths.at(-1)-.5/groovesPerPixel;rootDistance+=.7/groovesPerPixel){
      const k=lengths.findIndex(v=>v>=rootDistance);
      const start=mix(outline[k-1],outline[k],(rootDistance-lengths[k-1])/(lengths[k]-lengths[k-1]));
      const span=distance(start,mouthCenter),aim=mouthCenter.map((v,i)=>(v-start[i])/span);
      let best=null;
      for(const turn of [-.66,-.44,-.22,0,.22,.44,.66]){
        const dir=[aim[0]*Math.cos(turn)-aim[1]*Math.sin(turn),aim[1]*Math.cos(turn)+aim[0]*Math.sin(turn)];
        if(dir[0]*up[0]+dir[1]*up[1]<.38)continue;
        let heading=Math.atan2(dir[1],dir[0]);
        const original=heading, points=[start];
        let score=0,rootLight=0;
        for(let j=1;j<=21;j++){
          // Across a strand the photo changes tone more than along its length.
          let bestTurn=null;
          for(const turnStep of [-.42,-.21,0,.21,.42]){
            const theta=heading+turnStep, vector=[Math.cos(theta),Math.sin(theta)], normal=[-vector[1],vector[0]];
            if(Math.abs(theta-original)>1.0)continue;
            const q=points.at(-1).map((v,i)=>v+.25/groovesPerPixel*vector[i]);
            if(!insidePolygon(q,beard.outline) || protectedLines.some(path=>clearance(q,path)<1.7+tracking*.55))continue;
            if(j>=5 && clearance(q,outline)<.37*j*.25)continue;
            const sample=(dx,dy)=>grayAt(image,...q.map((v,i)=>v+(dx*normal[i]+dy*vector[i])/groovesPerPixel));
            const val=sample(0,0);
            if(j>4 && val>rootLight+24)continue;
            let support=0;
            for(const next of [0,.27,.54]){
              const middle=sample(0,next),left=sample(-.26,next),right=sample(.26,next);
              const cross=Math.abs(left-right)*.5+Math.abs((left+right)/2-middle);
              const along=Math.abs(sample(0,next-.26)-sample(0,next+.26));
              support+=clamp(cross-.52*along,-12,35)/3;
            }
            const rank=support-3.4*Math.abs(turnStep)-1.1*Math.abs(theta-original);
            if(!bestTurn || rank>bestTurn.rank)bestTurn={q,theta,rank,support,val};
          }
          if(!bestTurn)break;
          const {q,theta,support,val}=bestTurn;
          if(j<=3)rootLight+=val/3;
          score+=support;
          heading=.4*heading+.6*theta;
          points.push(q);
        }
        if(points.length<9 || clearance(points.at(-1),outline)<1.55)continue;
        const support=score/(points.length-1);
        if(support<3.0)continue;
        const rank=support*Math.sqrt(points.length-1);
        if(!best || rank>best.rank)best={rank,points};
      }
      if(best)choices.push(best);
    }
    // Roots are wider apart than neighboring ends. Each accepted stroke
    // retraces itself to its own point on the jaw, leaving open sand at the lip.
    const output=[];
    for(const {points} of choices.sort((a,b)=>b.rank-a.rank)){
      if(output.some(other=>distance(points[0],other[0])*groovesPerPixel<3.15))continue;
      const end=points.findIndex(q=>output.some(line=>clearance(q,line)<1.62+tracking*.45));
      const line=end<0?points:points.slice(0,end);
      if(line.length<9 || clearance(line.at(-1),outline)<1.5)continue;
      output.push(line);
      if(output.length===4)break;
    }
    return output;
  }

  function beardStrokes(beard,L,groovesPerPixel,tracking,smile) {
    if(!beard || !(groovesPerPixel>0))return [];
    const gap=(1.25+2*(tracking ?? .5))/groovesPerPixel;
    const mouth=L.slice(48,60);
    const dist=(a,b)=>Math.hypot(a[0]-b[0],a[1]-b[1]);
    function kept(line) {
      const out=[];
      for(const pt of line) {
        if(mouth.some(p=>dist(p,pt)<gap))break;
        out.push(pt);
      }
      return out.length>1 && dist(out[0],out.at(-1))>=1.6*gap?out:[];
    }
    const cheeks=beard.cheeks.map((edge,i)=>kept([...edge,...beard.moustache[i]]));
    if(cheeks.some(line=>!line.length)){
      // A guest place can resolve a cheek and a single lip groove even
      // when the upper moustache would close the gap around the mouth.
      if(!smile?.corners)return [];
      const compact=beard.cheeks.map((edge,side)=>{
        const line=[];
        for(const p of edge){
          if(dist(p,smile.corners[side])*groovesPerPixel<.85+tracking)break;
          line.push(p);
        }
        return line;
      });
      return compact.every(line=>line.length>1 && dist(line[0],line.at(-1))*groovesPerPixel>=1.2) ? compact : [];
    }
    const output=cheeks.slice(), width=dist(L[0],L[16]), maximum=.22*width+3.8/groovesPerPixel;
    for(const line of beard.fibers) {
      const stroke=[];
      for(const p of line) {
        if(dist(p,line[0])>maximum || mouth.some(q=>dist(p,q)<gap) ||
           output.some(path=>path.some(q=>dist(p,q)<gap)))break;
        stroke.push(p);
      }
      if(stroke.length>=3 && dist(stroke[0],stroke.at(-1))>=1.45/groovesPerPixel)output.push(stroke);
    }
    return output;
  }

  function hasBeardTexture(image,L,width) {
    // Compare local grain under the lip with both cheeks. Side lighting can
    // remove skin color across half a face without indicating facial hair.
    const median=xs=>xs.sort((a,b)=>a-b)[Math.floor(xs.length/2)];
    const step=Math.max(1,Math.round(width*.02));
    function patch(a,b,c,d) {
      const light=[],texture=[];
      for(let i=1;i<8;i++) for(let j=1;j<7;j++) {
        const [x,y]=mix(mix(a,b,i/8),mix(c,d,i/8),j/7);
        const v=grayAt(image,x,y);
        const surround=(grayAt(image,x-step,y)+grayAt(image,x+step,y)+
          grayAt(image,x,y-step)+grayAt(image,x,y+step))/4;
        light.push(v);texture.push(Math.abs(v-surround));
      }
      return [median(light),median(texture)];
    }
    const left=patch(L[2],L[4],L[48],L[6]), right=patch(L[14],L[12],L[54],L[10]);
    const chin=patch(L[59],L[7],L[55],L[9]);
    return Math.min(left[0],right[0])>.42*Math.max(left[0],right[0]) &&
      chin[1] > 1.15*Math.min(left[1],right[1])+.4;
  }

  // Add each eye as a round trip from a rim point in the finished drawing.
  // Re-routing all the portrait features would move the original connectors.
  function pairEyeExcursions(pixels,person,fit,diameter,points) {
    const {frame,dx,dy}=person;
    if(frame.glasses.length!==2)return [];
    const project=([x,y])=>[(x-frame.cx+dx-fit.cx)/fit.radius,(frame.cy-y+dy-fit.cy)/fit.radius];
    const scale=diameter/(2*fit.radius);
    const lids=frame.glasses.map((rim,side)=>{
      const eye=frame.eyes[side], width=Math.hypot(eye[3][0]-eye[0][0],eye[3][1]-eye[0][1]);
      if(width<15 || width*scale<2)return null;
      const measured=photographedLid(pixels,eye,[...rim,rim[0]],scale);
      if(!measured)return null;
      const at=project(rim[measured.index]);
      const anchor=points.find(q=>Math.hypot(q[0]-at[0],q[1]-at[1])<1e-8);
      if(!anchor)return null;
      const stroke=measured.stroke.map(project);
      // Skip eyes or connectors already crossing the interior of this lens.
      for(const [x,y] of stroke.slice(3,8)){
        for(let j=1;j<points.length;j++){
          const [ax,ay]=points[j-1],vx=points[j][0]-ax,vy=points[j][1]-ay;
          const t=clamp(((x-ax)*vx+(y-ay)*vy)/(vx*vx+vy*vy || 1),0,1);
          if(Math.hypot(x-ax-t*vx,y-ay-t*vy)*diameter/2<.85)return null;
        }
      }
      return [anchor,[...stroke,anchor]];
    });
    return lids.every(Boolean) ? lids : [];
  }

  // The dark end of a smile has lighter skin outside and both lips around it.
  function photographedMouthCorners(image,L) {
    const [x,y]=L[48], dx=L[54][0]-x, dy=L[54][1]-y;
    const at=(u,v)=>[x+u*dx-v*dy,y+u*dy+v*dx];
    const light=(u,v)=>{
      const [px,py]=at(u,v), ix=Math.floor(px), iy=Math.floor(py),fx=px-ix,fy=py-iy;
      return (1-fy)*((1-fx)*grayAt(image,ix,iy)+fx*grayAt(image,ix+1,iy))+
        fy*((1-fx)*grayAt(image,ix,iy+1)+fx*grayAt(image,ix+1,iy+1));
    };
    const corners=[0,1].map(side=>{
      const sign=side?-1:1;
      let best=null,quality=18;
      for(let i=-7;i<=7;i++)for(let j=-9;j<=9;j++){
        const du=.015*i,v=.015*j,u=side+sign*du;
        const middle=mean([.005,.022,.045].map(n=>light(u+sign*n,v)));
        const flank=s=>mean([.035,.06,.09].map(n=>light(u+sign*.025,v+s*n)))-middle;
        const outside=mean([.035,.06,.095].map(n=>light(u-sign*n,v)))-middle;
        const above=flank(-1),below=flank(1),weakest=Math.min(above,below,outside);
        const score=.45*weakest+.35*outside+.2*(above+below+outside)/3-42*Math.abs(du)-24*Math.abs(v);
        if(weakest>=12 && score>quality){best=at(u,v);quality=score;}
      }
      return best;
    });
    if(corners.some(q=>!q))return null;
    const adjusted=L.slice();[adjusted[48],adjusted[54]]=corners;
    return adjusted;
  }

  // Fine teeth and the colored lip can look like one open oval at Mini scale.
  // Follow their lower boundary once when the photographed opening is too
  // narrow for two grooves. Keep the remainder of the original engraving.
  function singleSmileLines(image,frame,lines,scale,tracking) {
    const {landmarks:L,cx,cy,radius}=frame;
    const project=([x,y])=>[(x-cx)/radius,(cy-y)/radius];
    const old=[L[33],...L.slice(51,60),...L.slice(48,52),L[33]].map(project);
    let index=-1, at=-1;
    for(const [i,line] of lines.entries()){
      at=line.findIndex((_,n)=>n+old.length<=line.length && old.every(([x,y],j)=>
        Math.hypot(line[n+j][0]-x,line[n+j][1]-y)<1e-8));
      if(at>=0){index=i;break;}
    }
    if(index<0)return null;
    const marks=photographedMouthCorners(image,L);
    if(!marks)return null;
    const start=marks[48],end=marks[54],dx=end[0]-start[0],dy=end[1]-start[1],width=Math.hypot(dx,dy);
    const grooves=width*scale;
    if(width<32 || grooves<6)return null;
    const depth=p=>((p[1]-start[1])*dx-(p[0]-start[0])*dy)/(width*width);
    const aperture=(depth(L[66])-depth(L[62]))*grooves;
    if(aperture<.85 || (depth(L[57])-depth(L[51]))*grooves-aperture<1)return null;
    // Sample the light, less-red band between the lips. Dark gaps between
    // individual teeth are allowed, but a single bright fleck is insufficient.
    const top=depth(L[62]),lower=depth(L[66]),slope=2*(depth(L[65])-depth(L[67]));
    const point=(u,v)=>[start[0]+dx*u-dy*v,start[1]+dy*u+dx*v];
    const bow=u=>(4*u*(1-u))**.8;
    const tone=(u,v)=>{
      const [r,g,b]=rgb(image,point(u,v));
      return -.501*r+1.103*g+.398*b;
    };
    const median=v=>v.slice().sort((a,b)=>a-b)[Math.floor(v.length/2)];
    const columns=Array.from({length:23},(_,i)=>.29+.49*i/22);
    const teeth=columns.map(u=>{
      const center=(top*.44+lower*.56)*bow(u);
      return tone(u,center)-Math.max(tone(u,bow(u)*top-.04),tone(u,bow(u)*lower+.04));
    });
    if(median(teeth)<19 || teeth.filter(v=>v>10).length<columns.length/2)return null;
    function lowerMargin(shifts){
      let best=null;
      for(const shift of shifts){
        const level=u=>bow(u)*(lower+slope*(2*u-1)+shift/grooves);
        const edges=columns.map(u=>Math.min(...[.25,.4].map(g=>
          tone(u,level(u)-g/grooves)-tone(u,level(u)+g/grooves))));
        const quality=median(edges)-7*Math.abs(shift);
        if(!best || quality>best.quality)best={level,quality,edges};
      }
      return best.quality>=9 && best.edges.filter(v=>v>8).length>=columns.length/2 ? best : null;
    }
    // Mouth landmarks can follow the fleshy lip below the visible tooth line.
    // Only search farther when the nearby fit has too little support in the photo.
    const best=lowerMargin([-.24,-.12,0,.12,.24]) || lowerMargin([-1,-.75,-.5,.5,.75,1]);
    if(!best)return null;
    const margin=Array.from({length:25},(_,i)=>i===0 ? start : i===24 ? end : point(i/24,best.level(i/24)));
    const close=points=>points.concat(points.slice(1,-1).reverse()).map(project);
    const base=lines.slice(),joint=lines[index];
    base[index]=joint.slice(0,at+1).concat(joint.slice(at+old.length));
    const single=base.concat([close(margin)]);
    const versions={line:single};
    // Fit the dark seam above the teeth independently of their lower edge.
    // A tilted lobe can leave room for light sand over only half of a smile.
    const cuts=Array.from({length:33},(_,i)=>.12+.76*i/32);
    let upper=null;
    for(const lift of [-.7,-.5,-.3,-.1,.1,.3,.5,.7])for(const lean of [-.09,-.06,-.03,0,.03,.06,.09]){
      const level=u=>bow(u)*(top+lift/grooves+lean*(2*u-1));
      const signal=cuts.map(u=>{
        const v=level(u),light=h=>grayAt(image,...point(u,v+h));
        const above=mean([-.025,-.048,-.069].map(light)),below=mean([.024,.040,.073].map(light));
        return Math.min(above,below)-light(0);
      });
      const capped=signal.map(v=>clamp(v,-15,50));
      const score=.6*mean(capped)+.4*median(capped)-22*Math.abs(lift/grooves)-13*Math.abs(lean);
      if(!upper || score>upper.score)upper={level,score};
    }
    const gaps=Array.from({length:25},(_,i)=>(best.level(i/24)-upper.level(i/24))*grooves);
    if(upper.score>=7 && gaps.every(v=>v>=0) && gaps.filter(v=>v>=1.40).length>=6){
      const topLine=margin.map((p,i)=>i===0 || i===24 ? p : point(i/24,upper.level(i/24)));
      versions.open=base.concat([[...margin,...topLine.slice(1,-1).reverse()].map(project)]);
    }
    // For a broad opening, one light edge alone could belong to the lower lip.
    if(aperture>1.25+2*tracking && !versions.open)return null;
    return versions;
  }

  function pairSmilePath(image,L,person,fit,diameter,points,inwardLines) {
    const {frame,dx,dy}=person, scale=diameter/(2*fit.radius);
    const width=Math.hypot(L[54][0]-L[48][0],L[54][1]-L[48][1]);
    if(width<24 || width*scale<3.5)return null;
    const project=([x,y])=>[(x-frame.cx+dx-fit.cx)/fit.radius,(frame.cy-y+dy-fit.cy)/fit.radius];
    // Replace only the old outside-lip loop that starts and ends at the
    // middle of the nose. Preserve separately traced smiles, beards and folds.
    const old=[L[33],...L.slice(51,60),...L.slice(48,52),L[33]].map(project);
    const lipStart=line=>line.findIndex((q,i)=>i+old.length<=line.length && old.every(([x,y],j)=>
      Math.hypot(line[i+j][0]-x,line[i+j][1]-y)<1e-8));
    const start=lipStart(points);
    if(start<0)return null;
    const marks=photographedMouthCorners(image,L);
    if(!marks)return null;
    // Both margins must be at least 1.25 nominal grooves apart through the
    // center of the opening. The guest can compare this with the first style.
    const smile=photographedSmile(image,marks,scale,0);
    if(!smile)return null;
    const measured=smile.map(project);
    // The inward rake can reach the measured mouth directly. Remove the
    // old trip from nose to lips, keeping the return along the nose itself.
    for(const line of inwardLines || []){
      // A face with separate glasses rims already has a standalone lip loop.
      if(line.length===12 && old.slice(1,13).every(([x,y])=>
          line.some(q=>Math.hypot(q[0]-x,q[1]-y)<1e-8))){
        line.splice(0,line.length,...measured);
        break;
      }
      const at=lipStart(line);
      if(at<0)continue;
      line.splice(at+1,old.length-1);
      inwardLines.push(measured);
      break;
    }
    const jawWidth=Math.hypot(L[16][0]-L[0][0],L[16][1]-L[0][1]);
    const fold=photographedSmileCrease(image,marks,jawWidth,smile,true) ||
      photographedSmileCrease(image,marks,jawWidth,smile);
    let path=smile;
    if(fold){
      // Enter the corner along the photographed cheek fold and retrace it
      // to the existing nose groove, avoiding a line down the middle of a lip.
      const lead=[L[fold.side?34:32],...fold.points];
      path=[...lead,...fold.lipLoop,...lead.slice(0,-1).reverse()];
    }
    return [...points.slice(0,start+1),...path.map(project),...points.slice(start+old.length-1)];
  }

  // Two adjacent heads at the proportions and angle of the source photograph.
  // Each face enters from the nearby rim and leaves by its own grooves.
  function pairedHeads(image,landmarks,locals,diameter,tracking,tracePairEyes,tracePairSmiles,traceInward) {
    if(!Number.isFinite(diameter) || diameter<=3)throw Error('Choose a measured portrait area for two heads.');
    function portraits(sizes,withInward=false) {
      return landmarks.map((marks,i)=>{
        const frame={}, tile=locals?.[i];
        const inward=withInward ? {sharedCrop:true} : null;
        const art=measuredDrawing(tile?.image||image,[marks],false,sizes[i],null,true,tracking,frame,false,inward);
        return {art,frame,inward,x:frame.cx+(tile?.x||0),y:-frame.cy-(tile?.y||0)};
      });
    }
    function arrange(people) {
      const [a,b]=people, dx=b.x-a.x,dy=b.y-a.y, length=Math.hypot(dx,dy);
      const axis=length ? [dx/length,dy/length] : [1,0], positions=[];
      const extent=(p,sign)=>Math.max(...p.art.flat().map(([x,y])=>sign*(x*axis[0]+y*axis[1])*p.frame.radius));
      const gap=3*(a.frame.radius+b.frame.radius)/diameter;
      const separation=extent(a,1)+extent(b,-1)+gap;
      for(const [i,p] of people.entries()){
        p.dx=(i-.5)*separation*axis[0];p.dy=(i-.5)*separation*axis[1];
        for(const line of p.art)for(const [x,y] of line)positions.push([x*p.frame.radius+p.dx,y*p.frame.radius+p.dy]);
      }
      const xx=positions.map(q=>q[0]),yy=positions.map(q=>q[1]);
      let cx=(Math.min(...xx)+Math.max(...xx))/2, cy=(Math.min(...yy)+Math.max(...yy))/2;
      const farthest=([x,y])=>positions.reduce((best,p)=>Math.hypot(p[0]-x,p[1]-y)>Math.hypot(best[0]-x,best[1]-y)?p:best);
      const edge=farthest([cx,cy]),opposite=farthest(edge),middle=mix(edge,opposite,.5),other=farthest(middle);
      if(Math.hypot(other[0]-middle[0],other[1]-middle[1])<Math.hypot(edge[0]-cx,edge[1]-cy))[cx,cy]=middle;
      const radius=Math.max(...positions.map(([x,y])=>Math.hypot(x-cx,y-cy)))/(1-3/diameter);
      return {cx,cy,radius};
    }
    let people=portraits([diameter/2,diameter/2]), fit=arrange(people);
    // Select the existing solo details at the scale the ball will actually draw.
    people=portraits(people.map(p=>diameter*p.frame.radius/fit.radius),traceInward);
    fit=arrange(people);
    const excursions=new Map(), smiles=[], engravings=[];
    const drawings=people.map((p,personIndex)=>{
      const place=([x,y])=>[(x*p.frame.radius+p.dx-fit.cx)/fit.radius,(y*p.frame.radius+p.dy-fit.cy)/fit.radius];
      const engraving=p.inward?.contours && {
        contours:p.inward.contours.map(line=>line.map(place)),hair:p.inward.hair.map(line=>line.map(place))
      };
      for(const line of p.art)for(let i=0;i<line.length;i++){
        line[i]=place(line[i]);
      }
      const points=route(p.art);
      const pixels=locals?.[personIndex]?.image || image;
      if(tracePairSmiles)smiles[personIndex]=pairSmilePath(pixels,landmarks[personIndex],p,fit,diameter,points,engraving?.contours);
      if(tracePairEyes){
        const lids=pairEyeExcursions(pixels,p,fit,diameter,points);
        for(const [anchor,stroke] of lids){
          excursions.set(anchor,stroke);
          // Enter the eyelid from its own glasses rim; a separate visit
          // from the spiral can put a diagonal through the open lens.
          for(const line of engraving?.contours || []){
            const at=line.findIndex(q=>Math.hypot(q[0]-anchor[0],q[1]-anchor[1])<1e-8);
            if(at>=0){line.splice(at+1,0,...stroke);break;}
          }
        }
      }
      if(engraving)engravings.push(engraving);
      return points;
    });
    const [first,second]=drawings;
    const start=Math.atan2(first[0][1],first[0][0]), end=Math.atan2(second[0][1],second[0][0]);
    const turn=Math.atan2(Math.sin(end-start),Math.cos(end-start)),n=Math.max(1,Math.ceil(Math.abs(turn)/.035));
    const rim=Array.from({length:n-1},(_,i)=>[Math.cos(start+turn*(i+1)/n),Math.sin(start+turn*(i+1)/n)]);
    const back=rim.slice().reverse();
    function pair(a,b){
      const points=[...a,...rim,...b,...back,a[0]];
      if(!excursions.size)return {points};
      const pending=new Map(excursions),pairEyePoints=[];
      for(const point of points){
        pairEyePoints.push(point);
        if(pending.has(point)){
          pairEyePoints.push(...pending.get(point));
          pending.delete(point);
        }
      }
      return {points,pairEyePoints};
    }
    const original=pair(first,second);
    if(engravings.length===2){
      // Finish on the head nearest the rim so the final connector stays short.
      const outer=p=>Math.max(...p.contours[0].map(([x,y])=>Math.hypot(x,y)));
      engravings.sort((a,b)=>outer(b)-outer(a));
      original.inwardContours=engravings.flatMap(p=>p.contours);
      original.inwardHair=engravings.flatMap(p=>p.hair);
    }
    if(smiles.some(Boolean))original.smiles=pair(smiles[0] || first,smiles[1] || second);
    return original;
  }

  // Three upright engravings keep the order and head tilts from the photo.
  // Only the positions of the three spaces turn. Their artwork never rotates.
  function threeHeads(image,landmarks,locals,diameter,trackingGrooves,_eyes,_smiles,traceInward) {
    if(!(diameter>0) || !Number.isFinite(diameter))return null;
    const tracking=Number.isFinite(trackingGrooves) && trackingGrooves>=0 ? trackingGrooves : .5;
    const count=3, step=2*Math.PI/count;
    // Reserve an open strip between silhouettes and the round border, including
    // the groove itself and relative tracking error on the two passes.
    const clearance=(2.5+2*tracking)/diameter, outside=1-2*clearance;
    if(outside*Math.sin(step/2)<=clearance)return null;
    const noses=landmarks.map((L,i)=>[L[30][0]+(locals?.[i]?.x||0),-L[30][1]-(locals?.[i]?.y||0)]);
    const cx=mean(noses.map(p=>p[0])),cy=mean(noses.map(p=>p[1]));
    const order=noses.map(([x,y],index)=>({x:x-cx,y:y-cy,index}))
      .sort((a,b)=>Math.atan2(a.y,a.x)-Math.atan2(b.y,b.x) || a.index-b.index);
    // Least-squares rotation of the three evenly spaced directions onto the
    // photographed centers. Ties retain the picker order.
    let dot=0,cross=0;
    for(const [j,{x,y}] of order.entries()){
      dot+=x*Math.cos(j*step)+y*Math.sin(j*step);
      cross+=y*Math.cos(j*step)-x*Math.sin(j*step);
    }
    const start=Math.atan2(cross,dot);
    const heads=[];
    for(const [j,{index}] of order.entries()){
      const angle=start+j*step, ux=Math.cos(angle),uy=Math.sin(angle);
      const L=landmarks[index],pixels=locals?.[index]?.image||image;
      const detail={headOnly:true,count,tracking};
      function fit(size) {
        const {art,cx,cy,radius}=closeFaceArtwork(pixels,[L],size,detail);
        const frame=art.flat().map(([x,y])=>{
          const u=(x-cx)/radius,v=(cy-y)/radius;
          return [-uy*u+ux*v,ux*u+uy*v];
        });
        const fitted=fitSeat(frame,{sourceCenter:[0,0],count,clearance,outside});
        return {art,cx,cy,radius,...fitted};
      }
      const estimate=fit(diameter/2);
      const {art,cx,cy,radius,scale,centerRadius,offset}=fit(diameter*estimate.scale);
      const groovesPerPixel=scale*diameter/(2*radius);
      // In a very narrow center the previous shared arrangement remains
      // available. A supported close-up needs room for two ends of each lid.
      if([[36,39],[42,45]].some(([a,b])=>Math.hypot(L[b][0]-L[a][0],L[b][1]-L[a][1])*groovesPerPixel<1+2*tracking))return null;
      const x=centerRadius*ux+scale*offset*uy,y=centerRadius*uy-scale*offset*ux;
      for(const line of art)for(const [k,[u,v]] of line.entries())line[k]=[x+scale*(u-cx)/radius,y+scale*(cy-v)/radius];
      // The closed tour retraces its internal links. Rotate that tour to the
      // furthest engraved point so the radial entrance meets this head first.
      const contour=route(art).slice(1,-2);
      let outer=0;
      for(let k=1;k<contour.length;k++)if(Math.hypot(...contour[k])>Math.hypot(...contour[outer]))outer=k;
      const gateAngle=Math.atan2(contour[outer][1],contour[outer][0]);
      heads.push({gateAngle,gate:[Math.cos(gateAngle),Math.sin(gateAngle)],
        path:contour.slice(outer).concat(contour.slice(0,outer+1))});
    }
    heads.sort((a,b)=>a.gateAngle-b.gateAngle);
    const points=[];
    for(const [j,head] of heads.entries()){
      points.push(head.gate);
      for(const p of head.path)points.push(p);
      points.push(head.gate);
      const next=heads[(j+1)%count].gateAngle+(j+1===count?2*Math.PI:0);
      const n=Math.ceil((next-head.gateAngle)/.035);
      for(let k=1;k<n;k++){
        const a=head.gateAngle+(next-head.gateAngle)*k/n;
        points.push([Math.cos(a),Math.sin(a)]);
      }
    }
    points.push(heads[0].gate);
    const inward=traceInward ? trioEngraving(heads.map(h=>h.path)) : null;
    return {points,...inward};
  }

  function trioEngraving(paths,mouths=[]) {
    // The spiral visits an entire face at once. Its connected tour keeps the
    // original eyes inside their glasses and avoids a new entry across a cheek.
    const outer=path=>path.reduce((r,p)=>Math.max(r,Math.hypot(...p)),0);
    return {inwardContours:paths.sort((a,b)=>outer(b)-outer(a)).concat(mouths),inwardHair:[]};
  }

  function trioMouth(image,landmarks,scale,tracking) {
    const fixed=photographedMouthCorners(image,landmarks);
    if(!fixed)return null;
    const measured=smallGroupSmile(image,fixed,scale,tracking);
    if(measured)return measured;
    // With a narrow opening the Mini can follow a single lip. Keep both
    // optically located corners and the three inner lower-lip landmarks.
    const left=fixed[48],right=fixed[54],dx=right[0]-left[0],dy=right[1]-left[1],span=dx*dx+dy*dy;
    if(Math.sqrt(span)*scale<2+2*tracking)return null;
    const edge=[left];
    let prior=0;
    for(const point of [fixed[67],fixed[66],fixed[65]]){
      const x=point[0]-left[0],y=point[1]-left[1],along=(x*dx+y*dy)/span;
      if(along<=prior || along>=1 || Math.abs(y*dx-x*dy)/span>.35)return null;
      edge.push(point);prior=along;
    }
    edge.push(right);
    return edge.concat(edge.slice(1,-1).reverse());
  }

  // On a small head the lid and the top of the nose can occupy the same groove.
  // Keep the photographed lid in place. The inward spiral can visit the nose
  // separately once its traced bridge has cleared the eye.
  function separateNoseStroke(lid, nose, scale, enlargement) {
    function grooveGap(point, line) {
      let gap=Infinity;
      for(let i=1;i<line.length;i++){
        const a=line[i-1], b=line[i], dx=b[0]-a[0], dy=b[1]-a[1];
        const t=clamp(((point[0]-a[0])*dx+(point[1]-a[1])*dy)/(dx*dx+dy*dy || 1),0,1);
        gap=Math.min(gap,Math.hypot(point[0]-a[0]-t*dx,point[1]-a[1]-t*dy)*scale);
      }
      return gap;
    }
    // A close corner still reads. Test overlap along the entire photographed lid.
    let overlap=0, length=0;
    for(let i=1;i<lid.length;i++){
      const a=lid[i-1], b=lid[i], part=Math.hypot(b[0]-a[0],b[1]-a[1])*scale;
      const samples=Math.max(1,Math.ceil(part/.1));
      for(let j=0;j<samples;j++){
        if(grooveGap(mix(a,b,(j+.5)/samples),nose)*enlargement<1)overlap+=part/samples;
      }
      length+=part;
    }
    if(overlap<=length/2)return null;
    const first=nose.findLastIndex(point=>grooveGap(point,lid)<1.05)+1;
    if(!first || first>=nose.length-3)return null;
    // Keep as much bridge as the groove permits, including a partial segment.
    const a=nose[first-1], b=nose[first];
    let low=0, high=1;
    for(let j=0;j<10;j++){
      const t=(low+high)/2;
      if(grooveGap(mix(a,b,t),lid)<1.05)low=t; else high=t;
    }
    const retained=[mix(a,b,high),...nose.slice(first)];
    return retained.concat(retained.slice(1,-1).reverse());
  }

  // Track the hair/background boundary from below one temple, over the crown
  // and down the other side. The face landmarks define the local axes so the
  // resulting outline keeps the sitter's head tilt.
  function photographedHairSides(image,L,shape) {
    if(shape.glasses.length || shape.goatee.length)return null;
    const dx=L[16][0]-L[0][0],dy=L[16][1]-L[0][1],width=Math.hypot(dx,dy),origin=mix(L[0],L[16],.5);
    if(width<70 || !shape.hair.length)return null;
    const at=(u,v)=>[origin[0]+u*dx-v*dy,origin[1]+u*dy+v*dx],median=a=>a.sort((a,b)=>a-b)[a.length>>1];
    const color=([r,g,b])=>[.299*r+.587*g+.114*b,.75*(r-g),.75*(b-g)];
    const distance=(a,b)=>Math.hypot(a[0]-b[0],a[1]-b[1],a[2]-b[2]);
    const skin=[mix(L[2],L[31],.55),mix(L[14],L[35],.55)].map(p=>color(rgb(image,p)));
    // Brightness plus red/green and blue/green differences distinguish dark
    // hair from both the cheek and backgrounds of a similar brightness.
    const hair=[[-.23,-.56],[.15,-.64],[0,-.70],[-.53,.13],[.53,.13],[-.54,-.16],[.54,-.16]].map(q=>color(rgb(image,at(...q)))).filter(c=>Math.min(...skin.map(s=>s[0]-c[0]))>22);
    if(hair.length<5)return null;
    const samples=105,steps=98,lower=.40,dr=.0095,bend=.77,parents=[],support=[];
    const colorAt=(u,v)=>color(rgb(image,at(u,v)));
    const likeness=c=>Math.min(...hair.map(h=>distance(c,h)));
    // Connect neighboring rays at the strongest supported edge. Penalize large
    // changes in radius so a background window does not become part of the hair.
    let prior;
    const angles=Array.from({length:samples},(_,i)=>-bend+(Math.PI+2*bend)*i/(samples-1));
    for(const angle of angles){
      const cs=Math.cos(angle),sn=-Math.sin(angle);
      const colors=Array.from({length:steps},(_,i)=>colorAt((lower+i*dr)*cs,(lower+i*dr)*sn));
      const hairDistance=colors.map(likeness),row=new Float32Array(steps).fill(-1e4),info=new Float32Array(steps);
      for(let j=8;j<steps-8;j++){
        const r=lower+j*dr;
        if(r<.50 || (sn<-.5 && r<.54) || (sn>.17 && r*Math.abs(cs)<.44))continue;
        const inDist=median([2,4,7].map(k=>hairDistance[j-k])),outDist=median([2,4,7].map(k=>hairDistance[j+k]));
        const signed=median([2,4,7].map(k=>colors[j+k][0]-colors[j-k][0]));
        const edge=median([2,4,7].map(k=>distance(colors[j+k],colors[j-k])));
        info[j]=Math.min(60,edge)+Math.max(-30,Math.min(60,outDist-inDist))-.55*inDist;
        row[j]=info[j]+.16*Math.min(80,signed)-6*Math.abs(r-.86);
      }
      support.push(info);
      if(!prior){prior=row;continue;}
      const predecessor=new Uint8Array(steps);
      const next=Array.from(row,(v,j)=>{
        let best=-Infinity,pi=j;
        for(let k=Math.max(0,j-5);k<=Math.min(steps-1,j+5);k++){
          const step=Math.abs(k-j),val=prior[k]-2.4*step-1.18*step*step;
          if(val>best){best=val;pi=k;}
        }
        predecessor[j]=pi;
        return best+v;
      });
      parents.push(predecessor);
      prior=next;
    }
    let j=prior.indexOf(Math.max(...prior));
    const radii=[],quality=[];
    for(let i=samples-1;i>=0;i--){
      radii[i]=lower+j*dr;
      quality[i]=support[i][j];
      if(i)j=parents[i-1][j];
    }
    const outer=angles.map((a,i)=>{
      const radius=[1,3,5,3,1].reduce((v,w,k)=>v+w*radii[clamp(i+k-2,0,samples-1)],0)/13;
      return at(radius*Math.cos(a),-radius*Math.sin(a));
    });
    if(outer.some(([x,y])=>x<1 || y<1 || x>=image.width-1 || y>=image.height-1))return null;
    // Both sides need a broad, distinct hair band outside the ears. A short
    // haircut can have an excellent measured crown but has no side locks.
    for(const pick of [angles.map(a=>a<.1),angles.map(a=>a>3.04)]){
      const side=angles.map((a,i)=>[Math.abs(Math.cos(a))*radii[i],quality[i]]).filter((_,i)=>pick[i]);
      if(median(side.map(s=>s[0]))<.62 || median(side.map(s=>s[1]))<48)return null;
    }
    return outer;
  }

  // Lay the measured hair around a face at its established size. Try its
  // original position first. When the wider hair needs room, move only this
  // sitter by up to three grooves. The other faces retain their exact routes.
  function hairTrio(heads, limit, groove) {
    if(!heads.some(h=>h.alt))return null;
    const placed=heads.map(h=>({path:h.path,features:h.features}));
    let changed=false;
    for(const [i,h] of heads.entries()){
      if(!h.alt)continue;
      const outside=[...h.alt.outside,...h.alt.outside.slice(1,-1).reverse()];
      const features=[...h.features,outside];
      const neighbors=placed.flatMap((other,j)=>j===i ? [] : [other.path,...other.features]);
      const gap=1.22*groove, segments=[];
      for(const line of neighbors)for(let j=1;j<line.length;j++){
        const [x,y]=line[j-1], [endX,endY]=line[j],dx=endX-x,dy=endY-y;
        segments.push({x,y,dx,dy,denom:dx*dx+dy*dy || 1,
          x0:Math.min(x,endX)-gap,x1:Math.max(x,endX)+gap,
          y0:Math.min(y,endY)-gap,y1:Math.max(y,endY)+gap});
      }
      const points=[];
      for(const line of [h.alt.path,...h.features,h.alt.outside]){
        points.push(line[0]);
        for(let j=1;j<line.length;j++){
          const a=line[j-1],b=line[j],count=Math.ceil(Math.hypot(b[0]-a[0],b[1]-a[1])/(.22*groove));
          for(let n=1;n<=count;n++)points.push(mix(a,b,n/count));
        }
      }
      function fits(dx,dy){
        for(const q of points){
          const x=q[0]+dx,y=q[1]+dy;
          if(x*x+y*y>limit*limit)return false;
          for(const s of segments){
            if(x<s.x0 || x>s.x1 || y<s.y0 || y>s.y1)continue;
            const t=clamp(((x-s.x)*s.dx+(y-s.y)*s.dy)/s.denom,0,1);
            if((x-s.x-t*s.dx)**2+(y-s.y-t*s.dy)**2<gap*gap)return false;
          }
        }
        return true;
      }
      let offset;
      for(let step=0;step<=6 && !offset;step++){
        const headings=step ? 24 : 1;
        for(let j=0;j<headings;j++){
          const a=2*Math.PI*j/headings, r=.5*step*groove;
          const dx=r*Math.cos(a),dy=r*Math.sin(a);
          if(fits(dx,dy)){offset=[dx,dy];break;}
        }
      }
      if(!offset)continue;
      const move=q=>[q[0]+offset[0],q[1]+offset[1]];
      placed[i]={path:h.alt.path.map(move),features:features.map(line=>line.map(move))};
      changed=true;
    }
    return changed ? trioEngraving(placed.map(h=>h.path),placed.flatMap(h=>h.features)).inwardContours : null;
  }

  const eyeSpanGain=(widest,span)=>.4*(widest-span);

  function largerTrio(heads, gap, groove, companion) {
    // Close part of the difference between the photographed eye spans, preserving
    // the largest face and scaling every stroke of each smaller face together.
    const widest=Math.max(...heads.map(h=>h.eyeSpan));
    const gain=heads.map(h=>eyeSpanGain(widest,h.eyeSpan));
    if(Math.max(...gain)<groove/2)return null;
    const origin=[0,1].map(k=>mean(heads.map(h=>h.center[k])));
    const scaled=heads.map((h,i)=>{
      const enlarge=q=>mix(h.center,q,1+gain[i]/h.eyeSpan);
      return {center:h.center,path:h.path.map(enlarge),features:h.features.map(line=>line.map(enlarge))};
    });
    const points=scaled.map(h=>h.path.concat(h.features.flat()));
    let spread=0;
    for(let i=0;i<3;i++)for(let j=i+1;j<3;j++){
      const dx=scaled[j].center[0]-scaled[i].center[0],dy=scaled[j].center[1]-scaled[i].center[1];
      const distance=Math.hypot(dx,dy);
      if(!distance)return null;
      const project=([x,y])=>(x*dx+y*dy)/distance;
      const space=Math.min(...points[j].map(project))-Math.max(...points[i].map(project));
      spread=Math.max(spread,(gap-space)/distance);
    }
    const placed=scaled.map(h=>{
      const move=([x,y])=>[x+spread*(h.center[0]-origin[0]),y+spread*(h.center[1]-origin[1])];
      return {path:h.path.map(move),features:h.features.map(line=>line.map(move))};
    });
    // Translate only as far as the rim requires. Moving the center toward the
    // worst point projects it into that point's admissible disc. Test every
    // stroke after each move; a crowded crop simply keeps its original sizes.
    const all=placed.flatMap(h=>h.path.concat(h.features.flat()));
    const limit=1-.85*groove;
    let center=[0,0];
    for(let attempt=0;attempt<24;attempt++){
      let distance=0,outer;
      for(const q of all){
        const r=Math.hypot(q[0]-center[0],q[1]-center[1]);
        if(r>distance){distance=r;outer=q;}
      }
      if(distance<=limit+1e-8){
        const move=([x,y])=>[x-center[0],y-center[1]];
        if(companion && heads.some(h=>h.alt)){
          const decorated=placed.map((h,i)=>{
            const original=heads[i];
            const offset=h.path[0].map((v,k)=>v-scaled[i].path[0][k]-center[k]);
            const map=q=>mix(original.center,q,1+gain[i]/original.eyeSpan).map((v,k)=>v+offset[k]);
            const alt=original.alt && {path:original.alt.path.map(map),outside:original.alt.outside.map(map)};
            return {path:h.path.map(move),features:h.features.map(line=>line.map(move)),alt};
          });
          companion.hair=hairTrio(decorated,limit,groove);
        }
        return trioEngraving(placed.map(h=>h.path.map(move)),
          placed.flatMap(h=>h.features.map(line=>line.map(move)))).inwardContours;
      }
      center=mix(center,outer,(distance-limit)/distance);
    }
    return null;
  }

  function inwardCloseTrio(people, cx, cy, radius, diameter, tracking, separateCrowdedEyes) {
    const groove=2/diameter, gap=(1+2*tracking)*groove, heads=[];
    let canSeparateEyes=false;
    const span=(a,b)=>Math.hypot(a[0]-b[0],a[1]-b[1])/radius;
    const eyeSpans=people.map(({L})=>span(mix(L[36],L[39],.5),mix(L[42],L[45],.5)));
    const widest=Math.max(...eyeSpans);
    for(const [i,p] of people.entries()){
      const L=p.L;
      // Preserve room for distinct eyes and the length of the smile at the
      // exact size of this person's ordinary photo, including tracking error.
      const eyeSpan=eyeSpans[i];
      if(eyeSpan<groove+gap ||
          span(L[48],L[54])<groove+gap)return null;
      const detail={headOnly:true,count:3,tracking,groupRadius:radius,separateCrowdedEyes,
        enlargement:1+eyeSpanGain(widest,eyeSpan)/eyeSpan};
      const {art,people:local,detachedMouth,detachedNose}=closeFaceArtwork(p.pixels,[L],diameter,detail);
      if(detachedNose)canSeparateEyes=true;
      const place=q=>{
        const [x,y]=p.place(q);
        return [(x-cx)/radius,(cy-y)/radius];
      };
      const shape=local[0].shape;
      const outside=!shape.lowerFace && shape.hairline.length && photographedHairSides(p.pixels,L,shape);
      for(const line of art)for(const [i,q] of line.entries())line[i]=place(q);
      let alt;
      if(outside){
        // Join the existing smoothed jaw to the photographed hairline. The
        // new outside edge is a separate visit of the inward rake. Keep all
        // face-feature lines and their connection points from the normal art.
        const jawVertices=2*(17-1);
        const inner=shape.head.slice(0,jawVertices).concat(shape.hairline).map(place);
        inner.faceOwner=0;
        const features=art.slice(1+shape.locks.length).filter(line=>!line.hairline);
        alt={path:route([inner,...features]).slice(1,-2),outside:outside.map(place)};
      }
      const path=route(art).slice(1,-2),face=art[0];
      heads.push({path,alt,eyeSpan,features:[detachedMouth,separateCrowdedEyes && detachedNose].filter(Boolean).map(line=>line.map(place)),center:[mean(face.map(q=>q[0])),mean(face.map(q=>q[1]))]});
    }
    // Open space between neighboring silhouettes by moving each whole face.
    // Stretch only the triangle of centers; the photographed features keep
    // their size and tilt. Each separating strip includes both tracking errors.
    const center=[mean(heads.map(h=>h.center[0])),mean(heads.map(h=>h.center[1]))];
    let spread=0;
    for(let i=0;i<heads.length;i++)for(let j=i+1;j<heads.length;j++){
      const a=heads[i],b=heads[j],dx=b.center[0]-a.center[0],dy=b.center[1]-a.center[1],length=Math.hypot(dx,dy);
      if(!length)return null;
      const project=([x,y])=>(x*dx+y*dy)/length;
      const space=Math.min(...b.path.map(project))-Math.max(...a.path.map(project));
      spread=Math.max(spread,(gap-space)/length);
    }
    const paths=[],features=[],placed=[];
    for(const head of heads){
      const shift=([x,y])=>[x+spread*(head.center[0]-center[0]),y+spread*(head.center[1]-center[1])];
      const path=head.path.map(shift),local=head.features.map(line=>line.map(shift));
      const alt=head.alt && {path:head.alt.path.map(shift),outside:head.alt.outside.map(shift)};
      placed.push({path,features:local,center:shift(head.center),eyeSpan:head.eyeSpan,alt});
      paths.push(path);
      features.push(...local);
    }
    if([...paths,...features].some(path=>path.some(q=>Math.hypot(...q)>1-groove/2)))return null;
    const native=hairTrio(placed,1-groove/2,groove);
    const companion={};
    const largerFaceContours=largerTrio(placed,gap,groove,companion);
    return {...trioEngraving(paths,features),canSeparateEyes,largerFaceContours,largerHairContours:companion.hair,hairContours:native};
  }

  function closeFaces(image, landmarks, portraitDiameterGrooves, locals=null, trio=null, trackingGrooves,separateCrowdedEyes=false) {
    const {art,cx,cy,radius,people}=closeFaceArtwork(image,landmarks,portraitDiameterGrooves,null,locals);
    // A pair of glasses can extend past its owner's face at the perimeter.
    let fit=radius;
    for(const line of art) for(const [x,y] of line) fit=Math.max(fit,Math.hypot(x-cx,y-cy)/.985);
    if(trio){
      const tracking=Number.isFinite(trackingGrooves) && trackingGrooves>=0 ? trackingGrooves : .5;
      Object.assign(trio,inwardCloseTrio(people,cx,cy,fit,portraitDiameterGrooves,tracking,separateCrowdedEyes));
    }
    for(const line of art) for(let i=0;i<line.length;i++) line[i]=[(line[i][0]-cx)/fit,(cy-line[i][1])/fit];
    return art;
  }

  function closeFaceArtwork(shared, landmarks, portraitDiameterGrooves, seat=null, locals=null) {
    const people=landmarks.map((L,owner) => {
      const tile=locals?.[owner], image=tile?.image || shared;
      const shape=portraitShapes(image,L,false,30);
      if(seat?.headOnly && !shape.hair.length){
        // The outer edge of a dark hairstyle can lie past the solo crop.
        // Follow the wider search only when hair continues below the ear.
        const wider=portraitShapes(image,L,true,30);
        if(wider.hair.length){
          const outer=wider.head.slice(17),inner=wider.hair.slice(outer.length).reverse();
          if(longHair(image,L,wider,outer,inner,true).length){
            shape.hair=wider.hair;
            shape.head=wider.head;
          } else {
            // Short hair keeps its original crown. Its photographed hairline
            // can extend only as far as the crown on the corresponding ray.
            const crown=shape.head.slice(17),origin=mix(L[0],L[16],.5);
            const line=crown.map((q,k)=>mix(origin,q,Math.min(1,Math.hypot(inner[k][0]-origin[0],inner[k][1]-origin[1])/
              Math.max(.000001,Math.hypot(q[0]-origin[0],q[1]-origin[1])))));
            shape.hair=[...crown,...line.reverse()];
          }
        }
      }
      if(shape.goatee.length && !hasBeardTexture(image,L,shape.width))shape.goatee=[];
      shape.fullBeard=seat && photographedFullBeard(image,L);
      shape.chinLock=seat && !shape.fullBeard ? photographedGoatee(image,L,shape) : null;
      shape.lowerFace=shape.fullBeard || shape.chinLock;
      if(shape.lowerFace)shape.goatee=[];
      const crown=shape.head.slice(17), n=crown.length;
      const hair=shape.hair.length ? shape.hair.slice(n).reverse() : [];
      // The two outer face landmarks are the actual temples. Taper any
      // overhanging scalp estimates smoothly into these measured endpoints.
      for(const [end,temple] of [[0,L[16]],[n-1,L[0]]]) {
        const dx=temple[0]-crown[end][0], dy=temple[1]-crown[end][1];
        for(let k=0;k<6;k++) {
          const i=end===0?k:end-k, blend=(1-k/6)**2;
          crown[i]=[crown[i][0]+blend*dx,crown[i][1]+blend*dy];
          if(hair.length) hair[i]=mix(hair[i],crown[i],blend);
        }
      }
      shape.locks=longHair(image,L,shape,crown,hair,!!seat);
      if(seat?.headOnly && shape.locks.length){
        // Crop long hair just under the chin with the head's own tilt. This
        // keeps a narrow face from shrinking to fit a full shoulder-length lock.
        const dx=L[16][0]-L[0][0],dy=L[16][1]-L[0][1],w=shape.width;
        shape.locks=shape.locks.map(lock=>lock.filter(([x,y])=>
          (y-L[8][1])*dx-(x-L[8][0])*dy<=.18*w*w)).filter(lock=>lock.length>=2);
      }
      // Corner cutting rounds a noisy pixel boundary while retaining jaw width.
      function smooth(line) {
        return line.flatMap((point,i) => {
          const next=line[(i+1)%line.length];
          return [mix(point,next,.16),mix(point,next,.84)];
        });
      }
      shape.head=smooth([...(shape.lowerFace?.outline || L.slice(0,17)),...crown.slice(1,-1)]);
      shape.hairline=hair.length ? hair.map((v,i)=>i && i<n-1 ? mix(v,mix(hair[i-1],hair[i+1],.5),.48):v) : [];
      return {owner,L,nose:tile ? [L[30][0]+tile.x,L[30][1]+tile.y] : L[30], localNoseY:L[30][1], shape, pixels:image};
    });
    const rows=seat ? [people] : arrangeFaces(people);
    for(const p of people) {
      if(seat) p.place=point=>point;
      p.head=p.shape.head.map(p.place);
      p.locks=p.shape.locks.map(edge=>edge.map(p.place));
    }
    const art=[], collars=[];
    let detachedMouth=null, detachedNose=null;
    for(const row of rows) for(const [i,p] of row.entries()) {
      p.head.faceOwner=p.owner;
      art.push(p.head);
      for(const edge of p.locks) {
        const lock=[...edge,...edge.slice(1,-1).reverse()];
        lock.featureOwner=p.owner;
        lock.faceOwner=p.owner;
        lock.branchFeatures=true;
        art.push(lock);
      }
      if(seat?.headOnly)continue;
      // Each pair of shoulders meets between neighbors. Stop a back shoulder
      // where it reaches a head in front, so no join travels across a face.
      for(const side of [-1,1]) {
        const right=side===1, near=row[i+side], c=p.shape.clothing;
        const leftJaw=seat?5:4;
        const cheek=p.place((p.shape.lowerFace?.jaw || p.L)[right?16-leftJaw:leftJaw]);
        let neck=p.place(c[right?9:16]), shoulder=p.place(c[right?10:15]);
        let end=mix(shoulder,p.place(c[right?11:14]),.62);
        if(seat) {
          // Crop the bust at the turn of the shoulder. The short neck still
          // joins the portrait to the rim without putting the chin on it.
          if(p.shape.lowerFace){
            const drop=p.shape.lowerFace.jaw[8].map((v,k)=>v-p.L[8][k]);
            neck=neck.map((v,k)=>v+drop[k]);
            shoulder=shoulder.map((v,k)=>v+drop[k]);
          }
          const collar=neck;
          neck=mix(cheek,collar,.69);
          end=mix(neck,shoulder,.29);
          shoulder=mix(neck,collar,.56);
        } else if(near) {
          const q=near.place(near.shape.clothing[right?15:10]);
          end=[(shoulder[0]+q[0])/2, Math.max(shoulder[1],q[1])+.08*Math.min(p.shape.width,near.shape.width)];
          shoulder[0]=(neck[0]+end[0])/2;
          shoulder[1]=clamp(shoulder[1],Math.min(neck[1],end[1]),Math.max(neck[1],end[1]));
        }
        const line=[cheek];
        for(let j=1;j<=28;j++){
          const t=j/28;
          const next=t<.35?mix(cheek,neck,t/.35)
            :mix(mix(neck,shoulder,(t-.35)/.65),mix(shoulder,end,(t-.35)/.65),(t-.35)/.65);
          if(people.some(q=>(q!==p && insidePolygon(next,q.head)) || q.locks.some(lock=>insidePolygon(next,lock)))) break;
          line.push(next);
        }
        if(line.length>2) {
          if(seat?.count>=3)collars.push({index:art.length,line});
          art.push([...line,...line.slice(1,-1).reverse()]);
        }
      }
    }
    const diameter=Number.isFinite(portraitDiameterGrooves) && portraitDiameterGrooves>0 ? portraitDiameterGrooves : 48;
    if(collars.length) {
      // Use the shortest existing neckline that keeps the jaw separate from
      // the perimeter after allowing for the groove and drift on both passes.
      function trimCollars(count) {
        for(const {index,line} of collars) {
          const kept=line.slice(0,count);
          art[index]=[...kept,...kept.slice(1,-1).reverse()];
        }
      }
      const person=people[0], [cx,cy]=seat.sourceCenter;
      const needed=1.25+2*seat.tracking;
      let low=3, high=Math.max(...collars.map(c=>c.line.length));
      while(low<high) {
        const mid=Math.floor((low+high)/2);
        trimCollars(mid);
        const {scale,centerRadius,offset}=fitSeat([...art.flat(),...person.shape.glasses.flat()],seat);
        const jaw=Math.max(...(person.shape.lowerFace?.outline || person.L.slice(0,17)).map(([x,y])=>
          Math.hypot(scale*(x-cx-offset),centerRadius+scale*(y-cy))));
        if((1-jaw)*diameter/2>=needed)high=mid;
        else low=mid+1;
      }
      trimCollars(high);
    }
    const frame=art.flat(), xx=frame.map(p=>p[0]), yy=frame.map(p=>p[1]);
    const cx=(Math.min(...xx)+Math.max(...xx))/2, cy=(Math.min(...yy)+Math.max(...yy))/2;
    const radius=Math.max(...frame.map(v=>Math.hypot(v[0]-cx,v[1]-cy)))/.964;
    // Size the features for the particular seat. Include the measured frames,
    // which may extend past the temples, in the initial estimate.
    const seatFit=seat && !seat.headOnly && fitSeat([...frame,...people[0].shape.glasses.flat()],seat);
    const drawingRadius=seat?.groupRadius || radius;
    const groovesPerPixel=seatFit ? diameter*seatFit.scale/2 : diameter/(2*drawingRadius);
    const distance=(a,b)=>seatFit ? Math.hypot(a[0]-b[0],a[1]-b[1])*groovesPerPixel :
      Math.hypot(a[0]-b[0],a[1]-b[1])*diameter/(2*drawingRadius);
    for(const p of people){
      const {shape,L,owner,place}=p;
      const image=p.pixels;
      // Internal strokes may branch only from this face's own silhouette.
      function feature(path,ports) {
        const line=path.map(place);
        line.featureOwner=owner;
        line.ports=ports;
        art.push(line);
      }
      const back=path=>[...path,...path.slice(1,-1).reverse()];
      function silhouettePart(path,ports) {
        const line=path.map(place);
        line.featureOwner=owner;
        line.faceOwner=owner;
        line.branchFeatures=true;
        if(ports)line.ports=ports;
        art.push(line);
        return line;
      }
      if(shape.hairline.length){
        const hair=seat?.headOnly ? visibleTempleHair(shape.hairline,[...shape.glasses,...shape.brows],groovesPerPixel) : shape.hairline;
        if(hair.length>=2)silhouettePart(back(hair)).hairline=true;
      }
      if(shape.goatee.length) silhouettePart(shape.goatee);
      if(shape.chinLock)feature(back(shape.chinLock.top),[0,shape.chinLock.top.length-1]);
      // Start at the measured center of the mouth. An open smile surrounds
      // the tooth opening; a closed or very narrow one follows the lip seam.
      const open=distance(L[62],L[66])>=1.4;
      const lipCenter=mix(L[62],L[66],open?0:.48);
      const rightLip=[lipCenter,mix(L[63],L[65],open?0:.48),L[54]];
      const leftLip=[L[48],mix(L[61],L[67],open?0:.48),lipCenter];
      const wideSmile=seat && !shape.goatee.length && Math.hypot(L[48][0]-L[54][0],L[48][1]-L[54][1])>=30 &&
        distance(L[62],L[66])>=2;
      const beardSmile=shape.fullBeard && smallGroupSmile(image,L,groovesPerPixel,seat.tracking,true);
      const goateeSmile=shape.chinLock && smallGroupSmile(image,L,groovesPerPixel,seat.tracking,true);
      const broad=!goateeSmile && !beardSmile && wideSmile && photographedSmile(image,L,groovesPerPixel,seat.tracking);
      const smallSmile=!goateeSmile && !beardSmile && !broad && seat?.count>=3 && smallGroupSmile(image,L,groovesPerPixel,seat.tracking);
      const smile=goateeSmile || beardSmile || broad || smallSmile;
      if(seat?.groupRadius && !shape.lowerFace && !shape.goatee.length)
        detachedMouth=trioMouth(image,L,groovesPerPixel,seat.tracking);
      const lips=smile || [...rightLip,...(open ? [L[65],L[66],L[67]] :
        [...rightLip.slice(0,-1).reverse(),...leftLip.slice(1).reverse()]),...leftLip];
      const beardLines=shape.fullBeard ? beardStrokes(shape.fullBeard,L,groovesPerPixel,seat.tracking,beardSmile) : [];
      if(beardLines.length) {
        // Reach the smile at its photographed corner from the nearest cheek.
        // A vertical connection from the nose would cut through the teeth.
        const loop=lips.slice(0,-1), corners=lips.corners || [L[48],L[54]];
        let entry;
        for(const [side,corner] of corners.entries()) {
          const index=lips.cornerIndices?.[side] ?? loop.reduce((best,p,k)=>distance(p,corner)<distance(loop[best],corner)?k:best,0);
          beardLines[side].forEach((p,k)=>{
            const gap=distance(p,loop[index]);
            if(!entry || gap<entry.gap)entry={side,k,index,gap};
          });
        }
        for(const [side,line] of beardLines.entries()) {
          const stroke=back(line);
          if(side===entry.side) {
            const {k,index}=entry;
            stroke.splice(k+1,0,...loop.slice(index),...loop.slice(0,index+1),line[k]);
          }
          feature(stroke,[0]);
        }
      }
      const linkedLips=beardLines.length || detachedMouth ? [] : lips;
      const crease=goateeSmile ? goateeExpression(image,L,goateeSmile,groovesPerPixel) : linkedLips.length && (wideSmile || smile) && photographedSmileCrease(image,L,shape.width,lips,!!smallSmile && !shape.goatee.length);
      if(shape.frameBridge){
        const frame=spectacleStroke(shape,groovesPerPixel,seat ? image : null);
        silhouettePart(frame.path,frame.ports);
        const fold=linkedLips.length && compactSmile(image,L,shape,groovesPerPixel);
        feature(expressionStroke(image,L,shape,linkedLips,beardLines.length?null:(fold || crease),seat ? groovesPerPixel : 0).path,[0]);
        continue;
      }
      const expression=expressionStroke(image,L,shape,linkedLips,beardLines.length?null:crease,seat ? groovesPerPixel : 0);
      if(detachedMouth && expression.noseStroke && !shape.glasses.length)
        detachedNose=separateNoseStroke(shape.eyes[expression.side].slice(0,4),expression.noseStroke,groovesPerPixel,seat.enlargement);
      const eyeDetail=Math.min(distance(L[19],L[37]),distance(L[24],L[44]))>=1.4;
      for(const [i,eye] of shape.eyes.entries()){
        const brow=i===0?shape.brows[i]:[...shape.brows[i]].reverse();
        const eyeShape=distance(eye[1],eye[5])>=1.2 ? eye : back(eye.slice(0,4));
        // Both measured eyes branch from their nearest brow, above the lid.
        // Connecting directly to a temple would engrave a spurious glasses arm.
        let browPath=back(brow);
        if(i===expression.side){
          // Keep the original entry and return ports on this brow when the
          // nose becomes a separate visit. Moving a port can cut the cheek.
          browPath=detachedNose && seat.separateCrowdedEyes ? [...brow,...brow.slice().reverse()] : expression.path.slice();
        }
        if(shape.glasses.length) {
          silhouettePart(shape.glasses[i]);
          if(eyeDetail) feature(eyeShape,[0,1,2,3]);
        } else {
          let best=Infinity,bi=0,ei=0;
          for(let k=0;k<brow.length;k++) for(let j=0;j<4;j++){
            const d=distance(brow[k],eyeShape[j]);
            if(d<best){best=d;bi=k;ei=j;}
          }
          const around=[...eyeShape.slice(ei),...eyeShape.slice(0,ei+1)];
          browPath.splice(bi+1,0,...around,brow[bi]);
        }
        feature(browPath,[0,1,browPath.length-1]);
      }
    }
    return {art,cx,cy,radius,people,detachedMouth,detachedNose,width:people[0].shape.width,chin:people[0].shape.chinLock?.jaw[8]};
  }

  function fitFramedHead(strokes,diameterGrooves) {
    // A tilted head can put the crown against the circular frame while leaving
    // unused room beside the chin. Compare its current fit with the axis between
    // those two ends before reducing the entire drawing at the same scale.
    const points=strokes.flat();
    const top=points.reduce((a,b)=>a[1]>=b[1]?a:b);
    const chin=points.reduce((a,b)=>a[1]<=b[1]?a:b);
    const centered=mix(top,chin,.5);
    const extent=([x,y])=>points.reduce((r,p)=>Math.max(r,Math.hypot(p[0]-x,p[1]-y)),0);
    const original=extent([0,0]), shifted=extent(centered);
    // Leave half a groove of sand between the edges of the frame and hair.
    const limit=1-3/diameterGrooves;
    if(original<=limit)return;
    const [x,y]=shifted<original ? centered : [0,0];
    const scale=Math.min(1,limit/Math.min(original,shifted));
    for(const line of strokes)for(let i=0;i<line.length;i++){
      const point=line[i];
      line[i]=[(point[0]-x)*scale,(point[1]-y)*scale];
    }
  }

  // Start and finish at the rim nearest the artwork, so a wide group has no long entrance below it.
  // A shortest-gap tree joins the contours; its return retraces each bridge.
  function route(loops,enterBelow=false) {
    let anchor, angle, bestScore=-Infinity;
    for(const loop of loops.filter(p=>p.featureOwner===undefined)) for(const p of loop){
      let turn=Math.atan2(p[1],p[0])+Math.PI/2;
      if(turn>Math.PI) turn-=2*Math.PI;
      if(enterBelow && Math.abs(turn)>Math.PI/4)continue;
      const score=Math.hypot(...p)-.007*Math.abs(turn);
      if(score>bestScore){bestScore=score;anchor=p;angle=turn;}
    }
    if(enterBelow && !anchor)return route(loops);
    const gateAngle=angle-Math.PI/2;
    const rim=[[Math.cos(gateAngle),Math.sin(gateAngle)]];
    const sets=[[anchor], ...loops];
    const best=sets.map(()=>({d:Infinity}));
    const seen=new Set([0]), children=sets.map(()=>[]);
    let src=0;
    while(seen.size<sets.length){
      for(let j=1;j<sets.length;j++)if(!seen.has(j)){
        if(sets[src].featureOwner!==undefined &&
           (!sets[src].branchFeatures || sets[j].featureOwner!==sets[src].featureOwner))continue;
        if(sets[j].featureOwner!==undefined && sets[j].featureOwner!==sets[src].faceOwner)continue;
        for(let a=0;a<sets[src].length;a++) for(let b=0;b<sets[j].length;b++){
          if(sets[j].ports && !sets[j].ports.includes(b))continue;
          const p=sets[src][a],q=sets[j][b];
          const d=(p[0]-q[0])**2+(p[1]-q[1])**2;
          if(d<best[j].d)best[j]={d,src,a,b};
        }
      }
      let j=-1;
      for(let i=1;i<best.length;i++) if(!seen.has(i) && (j<0 || best[i].d<best[j].d))j=i;
      const e=best[j];
      children[e.src].push({i:e.a,child:j,at:e.b});
      seen.add(j);src=j;
    }
    const points=[...rim];
    function visit(i,at){
      const poly=sets[i],n=poly.length;
      for(let k=0;k<n;k++){
        const j=(at+k)%n;
        points.push(poly[j]);
        for(const e of children[i])if(e.i===j){ visit(e.child,e.at); points.push(poly[j]); }
      }
      points.push(poly[at]);
    }
    visit(0,0);
    return points.concat(rim.reverse());
  }

  // In an upright portrait u runs right and v runs up from the face center.
  function fitSeat(frame,{sourceCenter,count,clearance,outside=.98}) {
    const half=Math.PI/count, cot=Math.cos(half)/Math.sin(half);
    const uv=frame.map(([x,y])=>[x-sourceCenter[0],sourceCenter[1]-y]);
    const gap=clearance/Math.sin(half), room=outside*outside-gap*gap;
    let left=-Infinity, right=-Infinity;
    for(const [u,v] of uv){
      left=Math.max(left,v-u*cot);
      right=Math.max(right,v+u*cot);
    }
    // The straight sides put the innermost center at gap + scale * tip.
    // At that center, solve each vertex's distance to the curved rim for scale.
    function fitAt(offset,tip) {
      let scale=Infinity;
      for(const [u,v] of uv){
        const x=u-offset, y=tip-v, b=gap*y;
        const divisor=Math.sqrt(b*b+room*(x*x+y*y))+b;
        if(divisor>0)scale=Math.min(scale,room/divisor);
      }
      return {scale,centerRadius:gap+scale*tip,offset};
    }
    const centered=fitAt(0,Math.max(left,right));
    if(count===2)return centered;
    // A tilted head may reach just one side. Also try a horizontal shift
    // that touches both sides at the same scale and keep the roomier fit.
    const balanced=fitAt((right-left)/(2*cot),(right+left)/2);
    return balanced.scale>centered.scale ? balanced : centered;
  }

  function groupSeatOrder(image,landmarks,boxes,seatOrder) {
    const order=boxes.map((box,sourceIndex)=>({image,L:landmarks[sourceIndex],box,sourceIndex}))
      .sort((a,b)=>a.box.x-b.box.x || a.box.y-b.box.y || a.sourceIndex-b.sourceIndex);
    if (Array.isArray(seatOrder)) {
      // Face selections and landmark indices stay in source order. Move only
      // selected boxes that the guest explicitly placed at a seat.
      const placed=[];
      for (const face of seatOrder) {
        const index=order.findIndex(({box})=>face && box.x===face.x && box.y===face.y && box.w===face.w);
        if (index>=0) placed.push(order.splice(index,1)[0]);
      }
      order.unshift(...placed);
    }
    return order;
  }

  function seatedDrawing(order,diameter,trackingGrooves) {
    const count=order.length, tau=2*Math.PI, start=-Math.PI/2;
    const diameterGrooves=Number.isFinite(diameter) && diameter>0 ? diameter : 48;
    // Both furrows can drift toward their common boundary. Each portrait
    // keeps half a furrow, its own measured tracking allowance, and half of
    // a quarter-furrow strip of clear sand on its side of that boundary.
    const tracking=Number.isFinite(trackingGrooves) && trackingGrooves>=0 ? trackingGrooves : .5;
    const clearance=Math.max(Math.min(.027,.18*Math.sin(Math.PI/count)),(1.25+2*tracking)/diameterGrooves);
    if(clearance>=.98*Math.sin(Math.PI/count))
      throw Error('These people need more room between their faces. Choose fewer people or a wider center.');
    const points=[[0,-1]],seatFaces=[];
    let currentAngle=start;
    // Sample the true perimeter because downstream drawing files interpolate
    // x and y between these points. A chord would cut across the portraits.
    function rimTo(angle) {
      const steps=Math.max(1,Math.ceil(Math.abs(angle-currentAngle)/.045));
      for(let i=1;i<=steps;i++){
        const a=currentAngle+(angle-currentAngle)*i/steps;
        points.push([Math.cos(a),Math.sin(a)]);
      }
      currentAngle=angle;
    }
    for(const [index,{image,L,box,sourceIndex}] of order.entries()){
      const sourceCenter=mix(L[0],L[16],.5);
      const seat={sourceCenter,count,clearance,tracking};
      const {art,width,chin}=closeFaceArtwork(image,[L],diameterGrooves,seat);
      const {scale,centerRadius,offset}=fitSeat(art.flat(),seat);
      sourceCenter[0]+=offset;
      const seatAngle=start-index*tau/count,rotation=seatAngle-start;
      const center=[Math.cos(seatAngle)*centerRadius,Math.sin(seatAngle)*centerRadius];
      const cos=Math.cos(rotation),sin=Math.sin(rotation);
      function place([x,y]){
        const u=scale*(x-sourceCenter[0]),v=scale*(sourceCenter[1]-y);
        return [center[0]+cos*u-sin*v,center[1]+sin*u+cos*v];
      }
      // Keep each stroke's ownership and entry ports when rotating the portrait.
      for(const line of art)for(let j=0;j<line.length;j++)line[j]=place(line[j]);
      const ink=route(art).slice(1,-1);
      // The contour walk is closed. Start it at its most outward mark (often
      // a shoulder). A radial approach beyond that point cannot cross any ink.
      ink.pop();
      let outer=0;
      for(let i=1;i<ink.length;i++)if(Math.hypot(...ink[i])>Math.hypot(...ink[outer]))outer=i;
      const anchor=ink[outer],bearing=Math.atan2(anchor[1],anchor[0]);
      const gateAngle=seatAngle+Math.atan2(Math.sin(bearing-seatAngle),Math.cos(bearing-seatAngle));
      rimTo(gateAngle);
      const gate=points.at(-1),gateIndex=points.length-1;
      points.push(...ink.slice(outer),...ink.slice(0,outer+1),gate);
      const xx=ink.map(p=>p[0]), yy=ink.map(p=>p[1]);
      seatFaces.push({sourceIndex,sourceBox:{x:box.x,y:box.y,w:box.w},sourceCenter,
        center,centerRadius,seatAngle,rotation,scale,headWidth:width*scale,chin:place(chin || L[8]),
        brow:place(mix(L[21],L[22],.5)),bounds:[Math.min(...xx),Math.min(...yy),Math.max(...xx),Math.max(...yy)],
        anchor,gate,gateIndex,inkStart:gateIndex+1,inkEnd:points.length-2});
    }
    rimTo(start-tau);
    points[points.length-1]=[0,-1];
    return {points,seatFaces,seatLayout:{count,ringRadius:mean(seatFaces.map(s=>s.centerRadius)),
      minimumGap:2*clearance,diameterGrooves,trackingGrooves:tracking}};
  }

  // A pen line needs one groove through its middle. Thin the thresholded ink
  // without breaking loops or junctions (Zhang–Suen, two alternating passes).
  function thinInk(mask,n) {
    const offsets=[-n,1-n,1,1+n,n,n-1,-1,-1-n], remove=[];
    let changed;
    do {
      changed=false;
      for(let pass=0;pass<2;pass++){
        for(let i=n+1;i<mask.length-n-1;i++){
          if(!mask[i])continue;
          let count=0,rises=0,prior=mask[i+offsets[7]];
          for(const delta of offsets){
            const next=mask[i+delta];count+=next;rises+=next>prior;prior=next;
          }
          if(count<2 || count>6 || rises!==1)continue;
          const t=mask[i-n],r=mask[i+1],b=mask[i+n],l=mask[i-1];
          if(pass ? !(t*r*l || t*b*l) : !(t*r*b || r*b*l))remove.push(i);
        }
        if(remove.length)changed=true;
        for(const i of remove)mask[i]=0;
        remove.length=0;
      }
    }while(changed);
  }

  // Follow each undirected pixel link once, going straight on through a crossing.
  // Ignore a diagonal if two axial links already connect the same pixels.
  function edgeStrokes(mask,n) {
    const dirs=[1,n+1,n,n-1,-1,-n-1,-n,1-n], links=new Uint8Array(mask.length);
    for(let i=n+1;i<mask.length-n-1;i++)if(mask[i]){
      for(let d=0;d<8;d++){
        if(!mask[i+dirs[d]] || (d%2 && (mask[i+dirs[d-1]] || mask[i+dirs[(d+1)%8]])))continue;
        links[i]|=1<<d;
      }
    }
    const lines=[];
    function follow(start) {
      const line=[];let p=start, previous=-1;
      do {
        line.push([p%n,Math.floor(p/n)]);
        const bits=links[p];let next=-1,turn=9;
        for(let d=0;d<8;d++)if(bits&(1<<d)){
          const bend=previous<0?0:Math.min((d-previous+8)%8,(previous-d+8)%8);
          if(bend<turn){next=d;turn=bend;}
        }
        if(next<0)break;
        links[p]&=~(1<<next);p+=dirs[next];links[p]&=~(1<<((next+4)%8));previous=next;
      }while(p!==start);
      if(p===start && line.length>1)line.push(line[0]);
      if(line.length>4)lines.push(line);
    }
    for(let i=0;i<links.length;i++)if(links[i] && !(links[i]&(links[i]-1)))follow(i);
    for(let i=0;i<links.length;i++)while(links[i])follow(i);
    return lines;
  }

  // On a simple landscape the left and right margins describe the background
  // at each height. Isolate a single solid subject that interrupts their horizon.
  function horizonSubject(image, channels, n, x0, y0, w, h) {
    if (Math.min(w,h) < 40) return null;
    const strip=Math.max(4,Math.round(.14*w));
    const percentile=(a,f)=>a.sort((x,y)=>x-y)[Math.floor((a.length-1)*f)];
    const colorDistance=(a,b)=>Math.hypot(a[0]-b[0],a[1]-b[1],a[2]-b[2])/Math.sqrt(3);
    const sides=[[],[]], noise=[];
    for(let y=0;y<h;y++){
      for(let side=0;side<2;side++){
        const i=(y+y0)*n+x0+(side?w-strip:0);
        const rgb=channels.map(c=>percentile(c.slice(i,i+strip),.5));
        sides[side].push(rgb);
        for(let x=0;x<strip;x+=2)noise.push(colorDistance(channels.map(c=>c[i+x]),rgb));
      }
    }
    const scatter=percentile(noise,.9);
    if(scatter>14)return null;
    // Find the same color transition on both exposed sides. A tilted camera
    // puts it on different rows. Their separation gives the slope of the
    // background, which must come from the image even behind the subject.
    const edges=sides.map(rows=>{
      let row=0,strength=0;
      for(let y=Math.ceil(.15*h);y<.85*h;y++){
        const d=colorDistance(rows[y+2],rows[y-2]);
        if(d>strength){row=y;strength=d;}
      }
      return {row,strength,delta:rows[row+2].map((v,c)=>v-rows[Math.max(0,row-2)][c])};
    });
    const [a,b]=edges;
    if(Math.min(a.strength,b.strength)<32 ||
       a.delta.reduce((sum,v,c)=>sum+v*b.delta[c],0)<.85*3*a.strength*b.strength)return null;
    const rise=b.row-a.row, span=w-strip;
    // One source-grid row is within the uncertainty of the edge measurement.
    const slope=Math.abs(rise)>1 ? rise/span : 0;
    if(Math.abs(slope)>.15)return null;
    const leftCenter=(strip-1)/2, rightCenter=leftCenter+span;
    const horizonAt=x=>(a.row+b.row)/2+slope*(x-(w-1)/2);
    const disagreement=[];
    for(let y=0;y<h;y++){
      const shift=slope*span/2;
      disagreement.push(colorDistance(sides[0][clamp(Math.round(y-shift),0,h-1)],
                                      sides[1][clamp(Math.round(y+shift),0,h-1)]));
    }
    if(percentile(disagreement,.75)>16)return null;
    const mask=new Uint8Array(n*n), threshold=Math.max(19,2.2*scatter)**2*3;
    for(let y=1;y<h-1;y++)for(let x=1;x<w-1;x++){
      const i=(y+y0)*n+x+x0,t=x/(w-1);
      const leftY=y+Math.round(slope*(leftCenter-x)),rightY=y+Math.round(slope*(rightCenter-x));
      let foreground=true;
      // Small changes in the height of the horizon should not become broad
      // horizontal strokes on either side of the wanted object.
      for(let offset=-2;offset<=2 && foreground;offset++){
        const left=sides[0][clamp(leftY+offset,0,h-1)],right=sides[1][clamp(rightY+offset,0,h-1)];
        let error=0;
        for(let c=0;c<3;c++)error+=(channels[c][i]-((1-t)*left[c]+t*right[c]))**2;
        foreground=error>threshold;
      }
      mask[i]=foreground;
    }
    const clean=new Uint8Array(n*n);
    for(let i=n+1;i<mask.length-n-1;i++){
      const sum=mask[i-n-1]+mask[i-n]+mask[i-n+1]+mask[i-1]+mask[i]+mask[i+1]+
        mask[i+n-1]+mask[i+n]+mask[i+n+1];
      clean[i]=sum>=5;
    }
    // Preserve the entire connected silhouette, including a narrow trunk or
    // stand. Several comparably sized objects need the guest's choice of frame.
    const components=[];
    for(let i=0;i<clean.length;i++)if(clean[i]){
      const pixels=[i];clean[i]=0;
      for(let k=0;k<pixels.length;k++)for(const d of [-n,-1,1,n]){
        const j=pixels[k]+d;if(clean[j]){clean[j]=0;pixels.push(j);}
      }
      if(pixels.length>.003*w*h)components.push(pixels);
    }
    components.sort((a,b)=>b.length-a.length);
    const body=components[0];
    if(!body || body.length<.014*w*h || body.length>.44*w*h || components[1]?.length>body.length*.28)return null;
    const xs=body.map(i=>i%n-x0),ys=body.map(i=>Math.floor(i/n)-y0);
    const left=Math.min(...xs),right=Math.max(...xs),top=Math.min(...ys),bottom=Math.max(...ys);
    const width=right-left+1,height=bottom-top+1;
    if(left<.09*w || right>.91*w || top<.05*h || bottom>.95*h ||
       Math.max(width,height)<25 || Math.min(width,height)<8 || body.length<.34*width*height)return null;
    const offsets=body.map((_,k)=>ys[k]-horizonAt(xs[k]));
    const depth=Math.max(2,Math.min(.06*h,.16*height));
    if(Math.min(...offsets)>-depth || Math.max(...offsets)<depth)return null;
    const keep=new Uint8Array(n*n);
    for(const i of body)keep[i]=1;
    const dx=image.width/w,dy=image.height/h, pad=4;
    const crop={x:Math.max(0,left-pad)*dx,y:Math.max(0,top-pad)*dy};
    crop.w=Math.min(w,right+pad+1)*dx-crop.x;crop.h=Math.min(h,bottom+pad+1)*dy-crop.y;
    function opacity(sx,sy){
      const x=x0+(sx+.5)/dx-.5,y=y0+(sy+.5)/dy-.5,ix=Math.floor(x),iy=Math.floor(y);
      const i=iy*n+ix,fx=x-ix,fy=y-iy;
      return (1-fy)*((1-fx)*keep[i]+fx*keep[i+1])+fy*((1-fx)*keep[i+n]+fx*keep[i+n+1]);
    }
    return {crop,opacity};
  }

  // A broad light or shadow can give a solid silhouette its characteristic
  // shape. Follow a tonal boundary that reaches the outline, so the ball can
  // enter along that feature without crossing a patch of clear sand.
  function subjectShade(gray,coverage,n,grooves,outline) {
    const support=soften(coverage,n,8);
    const light=soften(gray.map((v,i)=>coverage[i] ? v-255*(1-coverage[i]) : 0),n,8);
    const inside=[];
    for(let i=0;i<light.length;i++){
      light[i]/=Math.max(.001,support[i]);
      if(support[i]>.93)inside.push(light[i]);
    }
    inside.sort((a,b)=>a-b);
    const tone=f=>inside[Math.floor((inside.length-1)*f)];
    if(!inside.length || tone(.90)-tone(.10)<24)return null;
    const groove=n/grooves;
    let best=null, bestScore=0;
    for(const fraction of [.48,.60]){
      const level=tone(fraction),mask=Uint8Array.from(light,(v,i)=>support[i]>.50 && v<level);
      for(const loop of boundaries(mask,n,groove**2)){
        const at=([x,y])=>Math.round(y)*n+Math.round(x);
        const edge=loop.findIndex(p=>support[at(p)]<=.93);
        if(edge<0)continue;
        let stroke=[];
        for(let j=1;j<=loop.length;j++){
          const p=loop[(edge+j)%loop.length];
          if(support[at(p)]>.93){stroke.push(p);continue;}
          if(stroke.length>=5){
            let length=0,strong=0;
            for(let k=1;k<stroke.length;k++){
              const a=stroke[k-1],b=stroke[k],i=at(b);
              length+=Math.hypot(b[0]-a[0],b[1]-a[1]);
              strong+=Math.hypot(light[i+1]-light[i-1],light[i+n]-light[i-n]);
            }
            const score=strong/Math.sqrt(stroke.length);
            if(length>=groove*3 && score>bestScore){best=stroke;bestScore=score;}
          }
          stroke=[];
        }
      }
    }
    if(!best)return null;
    const distance=(a,b)=>Math.hypot(a[0]-b[0],a[1]-b[1]);
    const travel=[0];
    for(let i=1;i<best.length;i++)travel.push(travel[i-1]+distance(best[i-1],best[i]));
    const length=travel.at(-1);
    if(length<=7*groove || length<=1.8*distance(best[0],best.at(-1)))return best;
    // A winding shadow can fold back into the same grooves from a chair.
    // Follow it from the nearer end to its deepest point inside the outline,
    // keeping a short part of the turn so its curvature is still visible.
    let depth=0,turn=0;
    for(let i=1;i<best.length-1;i++){
      const inset=Math.min(...outline.map(p=>distance(p,best[i])));
      if(inset>depth){depth=inset;turn=i;}
    }
    if(depth<=2*groove)return best;
    if(travel[turn]<=length/2){
      const end=travel.findIndex(at=>at>=travel[turn]+1.5*groove);
      return end<0 ? best : best.slice(0,end+1);
    }
    const start=travel.findIndex(at=>at>=travel[turn]-1.5*groove);
    return best.slice(start);
  }

  function objectDrawing(image,frame,diameter,includeBackground=false,subject=null) {
    const {width,height}=image;
    if(frame && (![frame.x,frame.y,frame.w].every(Number.isFinite) || frame.w<18 ||
        frame.x-frame.w/2<-.001 || frame.y-frame.w/2<-.001 ||
        frame.x+frame.w/2>width+.001 || frame.y+frame.w/2>height+.001)){
      throw Error('Drag a square inside the photo around the object.');
    }
    const crop=subject?.crop || (frame?{x:frame.x-frame.w/2,y:frame.y-frame.w/2,w:frame.w,h:frame.w}:{x:0,y:0,w:width,h:height});
    const n=151, scale=(n-8)/Math.max(crop.w,crop.h), w=Math.max(1,Math.round(crop.w*scale)),h=Math.max(1,Math.round(crop.h*scale));
    const x0=Math.floor((n-w)/2),y0=Math.floor((n-h)/2);
    const grooves=clamp(Number.isFinite(diameter)?diameter:30,12,80);
    const gray=new Float32Array(n*n), channels=Array.from({length:3},()=>new Float32Array(n*n));
    const coverage=subject ? new Float32Array(n*n) : null;
    const hist=new Int32Array(256),frameTones=[];
    for(let y=y0;y<y0+h;y++)for(let x=x0;x<x0+w;x++){
      const i=y*n+x;
      for(const dy of [.18,.5,.82])for(const dx of [.18,.5,.82]){
        const sx=clamp(Math.floor(crop.x+(x-x0+dx)*crop.w/w),0,width-1);
        const sy=clamp(Math.floor(crop.y+(y-y0+dy)*crop.h/h),0,height-1);
        const p=4*(sx+sy*width), alpha=image.data[p+3]/255*(subject ? subject.opacity(sx,sy) : 1);
        if(coverage)coverage[i]+=alpha/9;
        for(let c=0;c<3;c++)channels[c][i]+=(255+(image.data[p+c]-255)*alpha)/9;
      }
      gray[i]=.299*channels[0][i]+.587*channels[1][i]+.114*channels[2][i];
      hist[clamp(Math.round(gray[i]),0,255)]++;
      if(x===x0 || y===y0 || x===x0+w-1 || y===y0+h-1)frameTones.push(gray[i]);
    }
    const result={name:'Object from photo',points:[],sourceWidth:width,sourceHeight:height,objectFrame:frame,
      faceBoxes:[],includedFaces:[],facesDetected:0,hasPortrait:false};
    const none=()=>({...result,message:'Frame one object or sketch with a clearer outline.'});
    const total=w*h;
    function percentile(f){let sum=0;for(let v=0;v<256;v++){sum+=hist[v];if(sum>=f*total)return v;}return 255;}
    function sortedP(values,f){return values[Math.floor((values.length-1)*f)];}
    let mean=0;for(let v=0;v<256;v++)mean+=hist[v]*v;
    let cut=0,score=0,count=0,sum=0;
    for(let v=0;v<255;v++){
      count+=hist[v];sum+=v*hist[v];if(!count || count===total)continue;
      const between=(mean*count-sum*total)**2/(count*(total-count));
      if(between>score){score=between;cut=v;}
    }
    frameTones.sort((a,b)=>a-b);
    const bright=sortedP(frameTones,.5)>cut, uniform=sortedP(frameTones,.85)-sortedP(frameTones,.15)<24;
    const mask=new Uint8Array(n*n);
    for(let y=y0+1;y<y0+h-1;y++)for(let x=x0+1;x<x0+w-1;x++){
      const i=y*n+x;mask[i]=bright?gray[i]<cut+.5:gray[i]>cut+.5;
    }
    let area=0,thick=0,onFrame=0;
    for(let y=y0+1;y<y0+h-1;y++)for(let x=x0+1;x<x0+w-1;x++){
      const i=y*n+x;if(!mask[i])continue;area++;
      if(x===x0+1 || y===y0+1 || x===x0+w-2 || y===y0+h-2)onFrame++;
      if(mask[i-2] && mask[i+2] && mask[i-2*n] && mask[i+2*n])thick++;
    }
    const contrast=percentile(.997)-percentile(.003);
    const paper=uniform && contrast>=24 && area>12 && area<.52*total && onFrame<.15*(w+h);
    const ink=paper && thick/area<.19;
    if(!frame && !subject && !paper){
      const focus=horizonSubject(image,channels,n,x0,y0,w,h);
      if(focus){
        if(includeBackground)result.hasIsolatedSubject=true;
        else {
          const isolated=objectDrawing(image,null,diameter,false,focus);
          if(isolated.points.length)return {...isolated,hasIsolatedSubject:true};
        }
      }
    }
    let lines=[];
    const mag=new Float32Array(n*n);
    if(ink){
      thinInk(mask,n);lines=edgeStrokes(mask,n);
    }else{
      // Color gradients also see transitions between equally bright colors.
      // Sample only where every neighbor belongs to the source; otherwise a
      // rectangular crop would turn into a powerful, entirely invented edge.
      const RGB=channels.map(c=>soften(c,n,3)), gx=new Float32Array(n*n),gy=gx.slice(), peaks=[];
      for(let y=y0+3;y<y0+h-3;y++)for(let x=x0+3;x<x0+w-3;x++){
        const i=y*n+x;
        for(const c of RGB){
          const dx=(c[i+1]-c[i-1])*.5,dy=(c[i+n]-c[i-n])*.5,m=Math.hypot(dx,dy);
          if(m>mag[i]){mag[i]=m;gx[i]=dx;gy[i]=dy;}
        }
      }
      const ridges=new Uint8Array(n*n);
      for(let y=y0+4;y<y0+h-4;y++)for(let x=x0+4;x<x0+w-4;x++){
        const i=y*n+x,m=mag[i];if(m<2.8)continue;
        const a=Math.abs(gx[i]),b=Math.abs(gy[i]),diagonal=gx[i]*gy[i]>0?n+1:1-n;
        const d=a>b?1:n,f=Math.min(a,b)/Math.max(a,b);
        if(m<(1-f)*mag[i-d]+f*mag[i-diagonal] || m<=(1-f)*mag[i+d]+f*mag[i+diagonal])continue;
        ridges[i]=1;peaks.push(m);
      }
      if(!peaks.length)return none();
      peaks.sort((a,b)=>a-b);
      const high=Math.max(5,sortedP(peaks,.59)),low=Math.max(2.8,.35*high),edge=new Uint8Array(n*n),stack=[];
      for(let i=0;i<ridges.length;i++)if(ridges[i] && mag[i]>=high){edge[i]=1;stack.push(i);}
      while(stack.length){
        const i=stack.pop();
        for(const d of [-n-1,-n,1-n,-1,1,n-1,n,n+1]){
          const j=i+d;if(ridges[j] && !edge[j] && mag[j]>=low){edge[j]=1;stack.push(j);}
        }
      }
      thinInk(edge,n);lines=edgeStrokes(edge,n);
      // A single measured edge that already spans most of the subject (e.g.
      // the profile of a roof) is a more faithful outline than joining rays.
      for(const line of lines){
        const xs=line.map(p=>p[0]),ys=line.map(p=>p[1]);
        line.spans=line.length>Math.min(w,h) &&
          Math.max(...xs)-Math.min(...xs)>.46*w && Math.max(...ys)-Math.min(...ys)>.46*h;
      }
      const tracedOutline=lines.some(line=>line.spans);
      if(!tracedOutline && !paper){
        // A closed outside edge can weaken where fur meets carpet or a petal
        // meets a leaf. Follow the strongest outward color change around the
        // framed subject, trading a short weak section for continuity.
        const spokes=96, greatest=Math.ceil(Math.min(w,h)*.62);
        const least=Math.max(4,Math.round(Math.min(w,h)*.22));
        const rows=[],cx=x0+w/2,cy=y0+h/2;
        function sample(c,x,y){
          const ix=clamp(Math.floor(x),0,n-2),iy=clamp(Math.floor(y),0,n-2),fx=x-ix,fy=y-iy,i=iy*n+ix;
          return (1-fy)*((1-fx)*c[i]+fx*c[i+1])+fy*((1-fx)*c[i+n]+fx*c[i+n+1]);
        }
        for(let a=0;a<spokes;a++){
          const t=2*Math.PI*a/spokes,ux=Math.cos(t),uy=Math.sin(t),e=new Float32Array(greatest+1).fill(-1000);
          for(let r=least;r<=greatest;r++){
            const x=cx+ux*r,y=cy+uy*r;
            if(x<x0+4 || y<y0+4 || x>=x0+w-4 || y>=y0+h-4)continue;
            let near=0,far=0;
            for(const c of RGB){
              const v=sample(c,x+ux*2,y+uy*2)-sample(c,x-ux*2,y-uy*2);
              const u=sample(c,x+ux*5,y+uy*5)-sample(c,x-ux*5,y-uy*5);
              near+=v*v;far+=u*u;
            }
            e[r]=.61*Math.min(80,Math.sqrt(near/3))+.39*Math.min(80,Math.sqrt(far/3));
          }
          rows.push(e);
        }
        // Two turns let the seam land on the same measured edge from either side.
        const prev=rows[0].slice(),history=[];
        for(let a=1;a<=2*spokes;a++){
          const e=rows[a%spokes],current=e.slice(),back=new Uint8Array(greatest+1);
          for(let r=least;r<=greatest;r++){
            let best=-Infinity;
            for(let q=Math.max(least,r-5);q<=Math.min(greatest,r+5);q++){
              const score=prev[q]-3.6*Math.abs(r-q);
              if(score>best){best=score;back[r]=q;}
            }
            current[r]+=best;
          }
          prev.set(current);history.push(back);
        }
        let tip=least;for(let r=least+1;r<=greatest;r++)if(prev[r]>prev[tip])tip=r;
        const outline=new Array(spokes),supported=[];
        const seam=tip;
        for(let a=spokes;a>0;a--){
          const angle=2*Math.PI*a/spokes;
          outline[a%spokes]=[cx+Math.cos(angle)*tip,cy+Math.sin(angle)*tip];
          supported.push(rows[a%spokes][tip]);tip=history[a+spokes-1][tip];
        }
        supported.sort((a,b)=>a-b);
        if(Math.abs(tip-seam)<5 && sortedP(supported,.2)>11 && sortedP(supported,.5)>25){
          outline.push(outline[0]);outline.shell=true;lines.push(outline);
        }
      }
      const innerLoop=(loop)=>loop.every(([x,y])=>x>x0+3 && x<x0+w-3 && y>y0+3 && y<y0+h-3);
      function addRegions(values,widthThreshold,kind,level){
        const region=Uint8Array.from(soften(values,n,3),v=>v>.5);
        for(const loop of boundaries(region,n,widthThreshold)){
          if(!innerLoop(loop))continue;
          loop.push(loop[0]);loop.region=kind;loop.level=level;lines.push(loop);
        }
      }
      // Closed, dark details (an eye, handle opening or nose) often survive
      // blur better as a tonal island than as several disconnected edges.
      if(!tracedOutline && !paper && contrast>20)for(const level of [.065,.15,.25]){
        const tone=percentile(level),detail=new Float32Array(n*n);
        for(let y=y0+1;y<y0+h-1;y++)for(let x=x0+1;x<x0+w-1;x++){
          const i=y*n+x;detail[i]=gray[i]<tone;
        }
        addRegions(detail,Math.max(18,total*.002),'dark',level);
      }
      if(!tracedOutline && !paper){
        // Learn the colors of this frame's background along its perimeter.
        // Colors concentrated inside the frame can complete a broken edge.
        const bins=10,inner=new Float32Array(bins**3),outer=inner.slice();
        const code=new Int16Array(n*n);
        let ni=0,no=0;
        for(let y=y0;y<y0+h;y++)for(let x=x0;x<x0+w;x++){
          const i=y*n+x, rgb=RGB.map(c=>clamp(Math.floor(c[i]*bins/256),0,bins-1));
          const [r,g,b]=rgb;code[i]=r*bins*bins+g*bins+b;
          const border=Math.min((x-x0)/w,(x0+w-1-x)/w,(y-y0)/h,(y0+h-1-y)/h)<.115;
          const freq=border?outer:inner;if(border)no++;else ni++;
          for(let dr=-1;dr<=1;dr++)for(let dg=-1;dg<=1;dg++)for(let db=-1;db<=1;db++){
            if(r+dr<0 || r+dr>=bins || g+dg<0 || g+dg>=bins || b+db<0 || b+db>=bins)continue;
            freq[code[i]+dr*bins*bins+dg*bins+db]+=1/(1+2*(dr*dr+dg*dg+db*db));
          }
        }
        const salient=new Float32Array(n*n);
        for(let y=y0+1;y<y0+h-1;y++)for(let x=x0+1;x<x0+w-1;x++){
          const i=y*n+x,k=code[i];
          salient[i]=(inner[k]+12)*no>(outer[k]+12)*ni*2.3;
        }
        addRegions(salient,total*.016,'color');
      }
      // A solid object on even paper has a better outer silhouette than its
      // broken highlight edges. Masks touching the frame cannot supply outlines.
      if(paper && !onFrame){
        for(const loop of boundaries(mask,n,Math.max(12,total*.003))){
          loop.push(loop[0]);loop.silhouette=true;lines.push(loop);
        }
      }
    }
    // Prefer long, distinct source lines near the selected area. Limit small
    // parallel edges that will merge at the measured diameter of the ball.
    const dist=(a,b)=>Math.hypot(a[0]-b[0],a[1]-b[1]);
    function inside(point,loop){
      const [x,y]=point;let yes=false;
      for(let i=0,j=loop.length-1;i<loop.length;j=i++){
        const a=loop[i],b=loop[j];
        if((a[1]>y)!==(b[1]>y) && x<(b[0]-a[0])*(y-a[1])/(b[1]-a[1])+a[0])yes=!yes;
      }
      return yes;
    }
    const shadows=lines.filter(line=>line.region==='dark').map(line=>({line,
      center:line.reduce((p,q)=>[p[0]+q[0]/line.length,p[1]+q[1]/line.length],[0,0])}));
    // When a light threshold joins two dark marks, keep their darker cores
    // separate. Wrapping both details in a single enclosing groove loses them.
    lines=lines.filter(line=>line.region!=='dark' || !shadows.some(s=>s.line.level<line.level && inside(s.center,line)));
    const shell=lines.find(line=>line.shell);
    if(shell){
      const near=(p,q)=>Math.abs(p[0]-q[0])<n*.068 && Math.abs(p[1]-q[1])<n*.068;
      lines=lines.filter(line=>line===shell || line.filter(p=>inside(p,shell)||shell.some(q=>near(p,q))).length>line.length*.64);
    }
    if(coverage){
      const outlines=boundaries(Uint8Array.from(coverage,v=>v>.5),n,n*n*.015);
      const outside=outlines.sort((a,b)=>b.length-a.length)[0];
      if(outside){
        outside.push(outside[0]);outside.priority=2;lines.push(outside);
        const shade=subjectShade(gray,coverage,n,grooves,outside);
        if(shade){shade.priority=1;lines.push(shade);}
      }
    }
    // A junction can split a clean pen drawing into short pieces. Roofs,
    // handles and cabinet corners still need those pieces to close their
    // outlines. Use the ink's fitted diameter for their spacing in the sand.
    let inkGroove=n/grooves;
    if(ink && lines.length){
      let left=n,right=0,top=n,bottom=0;
      for(const line of lines)for(const [x,y] of line){
        left=Math.min(left,x);right=Math.max(right,x);top=Math.min(top,y);bottom=Math.max(bottom,y);
      }
      const cx=(left+right)/2,cy=(top+bottom)/2;
      let radius=0;
      for(const line of lines)for(const [x,y] of line)radius=Math.max(radius,Math.hypot(x-cx,y-cy));
      inkGroove=2*radius/(.955*grooves);
    }
    const minLength=ink ? Math.max(5,.8*inkGroove) : Math.max(7,n/grooves*1.9);
    const maxLines=ink ? Math.round(clamp(grooves*.85,10,24)) : Math.round(clamp(grooves*.27,5,13));
    const candidates=lines.map(line=>{
      let length=0,strength=0,mx=0,my=0;
      for(let i=0;i<line.length;i++){
        const [x,y]=line[i];mx+=x;my+=y;strength+=mag[Math.round(y)*n+Math.round(x)];
        if(i)length+=dist(line[i-1],line[i]);
      }
      const radius=Math.hypot(mx/line.length-n/2,my/line.length-n/2)/n;
      const rank=length*(1-.7*radius)*(ink?1:Math.sqrt(Math.max(3,strength/line.length)))*(line.spans?3.6:line.shell?3.5:line.silhouette?2:line.region==='color'?1.9:line.region==='dark'?3.0:1);
      return {line,length,rank,priority:line.priority || 0};
    }).filter(c=>c.length>=minLength).sort((a,b)=>b.priority-a.priority || b.rank-a.rank);
    const covered=new Uint8Array(n*n),nearby=new Uint8Array(n*n),chosen=[];
    const clear=Math.max(2,Math.round(ink ? inkGroove*.40 : n/grooves*.64));
    for(const {line,length} of candidates){
      const fresh=line.reduce((v,[x,y])=>v+!covered[Math.round(y)*n+Math.round(x)],0);
      if(fresh<line.length*(ink?.25:line.region==='dark'?.30:.57) || (!ink && chosen.length && length<n*.065))continue;
      // Keep a separate background edge from causing a long false connector.
      if(!ink && chosen.length && !line.some(([x,y])=>nearby[Math.round(y)*n+Math.round(x)]))continue;
      // Remove staircase corners by a local average, then sample at subgroove
      // spacing. Preserve both endpoints of open strokes for an exact retrace.
      const closed=dist(line[0],line.at(-1))<2;
      const smooth=line.map((p,i)=>{
        if(!closed && (!i || i===line.length-1))return p;
        const prev=line[(i-1+line.length)%line.length],next=line[(i+1)%line.length];
        return [(prev[0]+2*p[0]+next[0])/4,(prev[1]+2*p[1]+next[1])/4];
      });
      const step=Math.max(1,Math.round(n/grooves*.40),Math.ceil(smooth.length/250)),path=smooth.filter((_,i)=>i%step===0);
      if(!closed)path.push(smooth.at(-1));
      path.closed=closed;path.dark=line.region==='dark';chosen.push(path);
      for(const [x,y] of line){
        const xx=Math.round(x),yy=Math.round(y),reach=Math.round(n*.12);
        for(let dy=-reach;dy<=reach;dy++){
          const row=yy+dy;if(row<0 || row>=n)continue;
          const side=Math.floor(Math.sqrt(reach*reach-dy*dy));
          nearby.fill(1,row*n+Math.max(0,xx-side),row*n+Math.min(n,xx+side+1));
          if(Math.abs(dy)<=clear){
            const half=Math.floor(Math.sqrt(clear*clear-dy*dy));
            covered.fill(1,row*n+Math.max(0,xx-half),row*n+Math.min(n,xx+half+1));
          }
        }
      }
      if(chosen.length>=maxLines)break;
    }
    if(!chosen.length)return none();
    const all=chosen.flat(),xs=all.map(p=>p[0]),ys=all.map(p=>p[1]);
    const cx=(Math.min(...xs)+Math.max(...xs))/2,cy=(Math.min(...ys)+Math.max(...ys))/2;
    const radius=Math.max(...all.map(([x,y])=>Math.hypot(x-cx,y-cy)))/.955;
    if(radius<6)return none();
    const paths=chosen.map(path=>{
      const local=path.map(([x,y])=>[(x-cx)/radius,(cy-y)/radius]);
      return path.closed?local:[...local,...local.slice(1,-1).reverse()];
    });
    // Dark areas wider than two grooves can hold one extra stroke. Fit it
    // inside the source mask; a skinny pen mark never gets an extra edge.
    const groove=2*radius/grooves;
    for(const line of chosen.filter(line=>line.dark)){
      const xs=line.map(p=>p[0]),ys=line.map(p=>p[1]);
      const bounds=[Math.min(...xs),Math.max(...xs),Math.min(...ys),Math.max(...ys)];
      const horizontal=bounds[1]-bounds[0]>bounds[3]-bounds[2];
      if(Math.min(bounds[1]-bounds[0],bounds[3]-bounds[2])<groove*2.4)continue;
      let longest=[];
      const [u,v]=horizontal?[xs,ys]:[ys,xs];
      for(let j=Math.ceil(Math.min(...v));j<Math.max(...v);j++){
        let run=[];
        for(let i=Math.ceil(Math.min(...u));i<Math.max(...u);i++){
          const p=horizontal?[i,j]:[j,i];
          if(!inside(p,line) || line.some(q=>dist(p,q)<groove*.95)){run=[];continue;}
          run.push(p);if(run.length>longest.length)longest=run.slice();
        }
      }
      if(longest.length>groove*.8)paths.push([longest[0],longest.at(-1)].map(([x,y])=>[(x-cx)/radius,(cy-y)/radius]));
    }
    const points=route(paths);
    return {...result,points,entryAngle:Math.atan2(points[0][1],points[0][0])};
  }

  function framedFace(face, image) {
    if (face && [face.x,face.y,face.w].every(Number.isFinite) && face.w >= 18 &&
        face.x-face.w/2 >= -.001 && face.x+face.w/2 <= image.width+.001 &&
        face.y-face.w/2 >= -.001 && face.y+face.w/2 <= image.height+.001) return face;
    throw Error('Select a face in this photo.');
  }

  // A single, distant face near the edge can belong to the background of
  // a close group photo. Size alone would wrongly leave out children or a
  // second row. In doubtful arrangements the group starts with everybody.
  function distantFace(boxes,width,height) {
    if(boxes.length<4)return null;
    const [small,...front]=boxes.slice().sort((a,b)=>a.w-b.w);
    if(small.w>3*front[0].w/8 || small.w>Math.min(width,height)/16 ||
       front.at(-1).w>2*front[0].w)return null;
    // Look only along an edge with a real break between head outlines.
    const edgeGap=front[0].w/2;
    const separate=(axis,size)=>(small[axis]<size/8 &&
      front.every(p=>p[axis]-p.w/2>small[axis]+small.w/2+edgeGap)) ||
      (small[axis]>7*size/8 && front.every(p=>p[axis]+p.w/2<small[axis]-small.w/2-edgeGap));
    if(!separate('x',width) && !separate('y',height))return null;
    const distance=(a,b)=>2*Math.hypot(a.x-b.x,a.y-b.y)/(a.w+b.w);
    const gap=Math.min(...front.map(p=>distance(p,small)));
    if(gap<=2.5)return null;
    // Everyone else must form one group at substantially closer spacing.
    // Several separate pairs do not establish which group is the subject.
    const together=new Set([front[0]]);
    for(const person of together)for(const other of front){
      if(!together.has(other) && distance(person,other)<gap/1.5)together.add(other);
    }
    return together.size===front.length ? small : null;
  }

  async function fromPixels(image, {group=false,whole=false,foregroundFirst=false,groupStyle,portraitStyle,portraitFraming,portraitDiameterMm,
                                    portraitDiameterGrooves,portraitTrackingGrooves,compactBeardGrain=false,tracePairEyes=false,tracePairSmiles=false,face=null,groupFaces=null,seatOrder=null,
                                    object=false,objectFrame=null,includeBackground=false,onShadowFrame,fitShadowMarks,shoulderLocks=true,earJewelry=true,inwardContours=false,separateCrowdedEyes=false}={}, analysis={}) {
    if(!image || !image.width || !image.height || !image.data) throw Error('This photo could not be read.');
    if(object)return objectDrawing(image,objectFrame,portraitDiameterGrooves,includeBackground);
    const found=whole ? [] : await detectedFaces(image,analysis);
    const separateFaces=group && !whole && ['faces','seats','heads'].includes(groupStyle);
    const distant=group && !whole && foregroundFirst ? distantFace(found,image.width,image.height) : null;
    const boxes=group && !whole && Array.isArray(groupFaces)
      ? groupFaces.filter(b=>b.included!==false).map(b=>found.find(c=>c.x===b.x && c.y===b.y && c.w===b.w) || framedFace(b,image))
      : distant ? found.filter(b=>b!==distant) : found;
    let selected=group?boxes:boxes.slice(0,1);
    let tiltedShadowBox=null;
    const shadows=portraitStyle==='shadow' && !group && !whole;
    if (!group && !whole && face !== null) {
      if (Number.isInteger(face) && face >= 0 && face < boxes.length) selected=[boxes[face]];
      else {
        const box=framedFace(face,image);
        // An automatic box copied by the face picker omits its private tilt.
        if(shadows && !box.angle)tiltedShadowBox=boxes.find(b=>b.angle && b.x===box.x && b.y===box.y && b.w===box.w);
        selected=[box];
      }
    }
    const sourceWidth=image.width, sourceHeight=image.height, selectedInSource=selected;
    const detail=await portraitDetail(analysis,image,selected);
    if (detail) {
      image=detail.image;
      selected=selected.map(detail.place);
      if (seatOrder) seatOrder=seatOrder.map(detail.place);
      if (tiltedShadowBox) tiltedShadowBox=detail.place(tiltedShadowBox);
      analysis=detail.analysis;
    }
    const local=!detail && separateFaces && (groupStyle==='faces' || groupStyle==='heads') && portraitStyle!=='shadow' && selected.length>1
      ? await closeGroupTiles(analysis,image,selected) : null;
    const landmarks=local
      ? (await Promise.all(local.map(tile=>cachedLandmarks(tile.analysis,tile.image,[tile.box])))).flat()
      : await cachedLandmarks(analysis,image,selected);
    const close=separateFaces && landmarks.length>1;
    const headLayout=landmarks.length===2 ? pairedHeads : landmarks.length===3 ? threeHeads : null;
    const heads=close && headLayout && groupStyle==='heads' && portraitStyle!=='shadow'
      ? headLayout(image,landmarks,local,portraitDiameterGrooves,portraitTrackingGrooves,tracePairEyes,tracePairSmiles,inwardContours) : null;
    const seated=close && groupStyle==='seats' ? seatedDrawing(groupSeatOrder(image,landmarks,selected,seatOrder),
      portraitDiameterGrooves,portraitTrackingGrooves) : null;
    const groupShadows=group && !whole && groupStyle==='faces' && portraitStyle==='shadow';
    const shadowFrame=shadows && selected.length ? {} : null;
    const soloHead=selected.length===1 && (!group || groupStyle==='heads');
    const framedHead=soloHead && !whole && !shadows &&
      portraitFraming==='framedHead' && Number.isFinite(portraitDiameterGrooves) && portraitDiameterGrooves>3;
    const headOnly=soloHead && !whole && !shadows && (portraitFraming==='head' || framedHead);
    function nearbyFaces(){
      const face=selectedInSource[0],others=found.filter(b=>b.x!==face.x || b.y!==face.y);
      return detail ? others.map(detail.place) : others;
    }
    const inward=inwardContours && headOnly && !framedHead ? {neighbors:nearbyFaces()} : null;
    const trio=inwardContours && groupStyle==='heads' && landmarks.length===3 && !heads &&
      Number.isFinite(portraitDiameterGrooves) && portraitDiameterGrooves>0 ? {} : null;
    const paths=seated || heads ? null : close ? closeFaces(image,landmarks,portraitDiameterGrooves,local,trio,portraitTrackingGrooves,separateCrowdedEyes)
      : selected.length ? measuredDrawing(image,landmarks,group && !headOnly,portraitDiameterGrooves,shadowFrame,headOnly,portraitTrackingGrooves,undefined,compactBeardGrain && !group,inward)
      : engraving(image,framing(image,boxes,group),group,boxes);
    if(framedHead)fitFramedHead(paths,portraitDiameterGrooves);
    const points=heads?.points || seated?.points || route(paths,framedHead);
    const result={name:group?'Group photo':'Portrait',points,entryAngle:Math.atan2(points[0][1],points[0][0]),
      ...(heads?.smiles ? {smiles:heads.smiles} : {}),
      ...(heads?.inwardContours ? {inwardContours:heads.inwardContours,inwardHair:heads.inwardHair} : {}),
      ...trio,
      ...(heads?.pairEyePoints ? {pairEyePoints:heads.pairEyePoints} : {}),
      sourceWidth,sourceHeight,facesDetected:boxes.length,
      faceBoxes:found.map(({x,y,w})=>({x,y,w})), includedFaces:selectedInSource.map(({x,y,w})=>({x,y,w})),
      hasPortrait:!!selected.length,
      ...(inward?.contours ? {inwardContours:inward.contours,inwardHair:inward.hair,partedHair:inward.partedHair,fringe:inward.fringe,soloSmile:inward.expression} : {}),
      ...(distant ? {distantFace:{x:distant.x,y:distant.y,w:distant.w}} : {}),
      ...(group ? {groupStyle:heads || headOnly ? 'heads' : seated?'seats':close?'faces':'pose'} : {}),
      ...(seated ? {seatFaces:seated.seatFaces,seatLayout:seated.seatLayout} : {})};
    if (detail && seated) for (const person of result.seatFaces) {
      const {x,y,w}=selectedInSource[person.sourceIndex];
      person.sourceBox={x,y,w};
    }
    if(shadowFrame){
      try {
        if(!window.GuestShadow)throw Error('Photo shadows are unavailable here.');
        let frame=shadowFrame;
        if(tiltedShadowBox){
          const [tilted]=await cachedLandmarks(analysis,image,[tiltedShadowBox]);
          frame=soloFrame(portraitShapes(image,tilted,false),tilted);
        }
        const {person,landmarks:L}=frame;
        const scaleKnown=Number.isFinite(portraitDiameterGrooves) && portraitDiameterGrooves>0;
        if(scaleKnown && portraitDiameterGrooves>=62 && person.glasses.length===2){
          // The generic eye-centered outlines can find both lenses but miss
          // their bridge. A measured bridge and two traced rims take priority.
          const wire=person.frameBridge ? null : thinFrames(image,L);
          const fitted=wire ? {...person,glasses:wire.lenses,frameBridge:wire.junctions} : person;
          frame={...frame,person:fitted,hinges:photographedHinges(image,fitted.eyes,fitted.glasses,
            portraitDiameterGrooves/(2*frame.radius))};
        }
        const full=scaleKnown && photographedFullBeard(image,L);
        const chin=scaleKnown && !full && photographedGoatee(image,L,person,true);
        if(full || chin){
          const head=[...(full || chin).outline,...person.head.slice(17)];
          frame=soloFrame({...person,head},L);
          const groovesPerPixel=portraitDiameterGrooves/(2*frame.radius);
          frame.beardStrokes=full ? [...full.cheeks.map((line,i)=>line.concat(full.moustache[i])),...full.fibers] :
            chinStrands(image,L,chin,groovesPerPixel);
          // The two sides of an opening share one excursion from the spiral.
          // Match the existing shadow portrait's 1.35-groove opening limit.
          frame.beardSmile=smallGroupSmile(image,L,groovesPerPixel,portraitTrackingGrooves,true,1.35);
          if(chin && frame.beardSmile){
            const lip=goateeExpression(image,L,frame.beardSmile,groovesPerPixel).upperLip;
            if(lip.length>2)frame.beardStrokes.push(lip);
          }
          frame.beardMask=full ? [...full.cheeks[0],...full.moustache[0],...full.moustache[1].slice().reverse(),
            ...full.cheeks[1].slice().reverse(),...full.outline.slice().reverse()] : [...chin.top,...chin.bottom.slice().reverse()];
        }
        let previousFrame=null;
        if(scaleKnown && !frame.beardStrokes){
          const neighbors=nearbyFaces();
          let hair=longHairSilhouette(image,frame,portraitDiameterGrooves,neighbors);
          if(!hair && shoulderLocks){
            hair=contrastedHair(image,frame,portraitDiameterGrooves,neighbors);
            if(hair)previousFrame=frame;
          }
          if(hair)frame={...frame,longHair:hair};
        }
        if(earJewelry && scaleKnown && portraitDiameterGrooves>=62){
          const ear=window.GuestShadow.piercedEar(image,frame,portraitDiameterGrooves);
          if(ear){previousFrame=previousFrame || frame;frame={...frame,measuredEar:ear};}
        }
        // A laptop can also measure hair beyond this crop. Describe the same
        // frame in face-picker coordinates even when we used original pixels.
        const callback=onShadowFrame && ((pixels,actual)=>{
          const box=selected[0],source=selectedInSource[0],scale=source.w/box.w;
          onShadowFrame(pixels,actual,{x:source.x+(actual.cx-box.x)*scale,y:source.y+(actual.cy-box.y)*scale,
            radius:actual.radius*scale,width:sourceWidth,height:sourceHeight});
        });
        const draw=actual=>window.GuestShadow.fromFace(image,actual,portraitDiameterMm,portraitDiameterGrooves,
          photographedShadowEyes,callback,photographedShadowSmile,portraitTrackingGrooves);
        try {
          result.shadowMarks=draw(frame);
          if(previousFrame && fitShadowMarks)fitShadowMarks(result.shadowMarks);
        } catch(error) {
          if(!previousFrame)throw error;
          // Preserve the old close-up when the longer hair would block a
          // photographed eye, jaw or smile on this table's actual spiral.
          result.shadowMarks=draw(previousFrame);
        }
      } catch(error) {
        result.shadowReason=error.message || 'This photo did not yield separate shadow lines.';
      }
    } else if(groupShadows && close){
      try {
        if(!window.GuestShadow)throw Error('Photo shadows are unavailable here.');
        const people=landmarks.map((L,owner)=>{
          const person=portraitShapes(image,L,false,30);
          return {owner,nose:L[30],shape:{head:person.head,width:person.width,locks:person.glasses},
                  frame:soloFrame(person,L)};
        });
        const rows=arrangeFaces(people);
        if(people.length===2 && rows.length===2){
          // Centering two one-person rows loses the left/right direction of
          // a diagonal pair. Keep their original bearing, then bring them
          // together until a clear strip remains between the two outlines.
          const edges=people.map(p=>[p.shape.head,...p.shape.locks].flat());
          const centers=edges.map(edge=>[0,1].map(axis=>{
            const values=edge.map(point=>point[axis]);
            return (Math.min(...values)+Math.max(...values))/2;
          }));
          const dx=centers[1][0]-centers[0][0],dy=centers[1][1]-centers[0][1];
          const length=Math.hypot(dx,dy);
          if(!length)throw Error('There is too little space to separate both selected faces.');
          const ux=dx/length,uy=dy/length;
          const reach=edges.map((edge,i)=>Math.max(...edge.map(([x,y])=>
            (i===0?1:-1)*((x-centers[i][0])*ux+(y-centers[i][1])*uy))));
          const gap=.17*mean(people.map(p=>p.shape.width)),separation=reach[0]+reach[1]+gap;
          for(const [i,p] of people.entries()){
            const offset=(i-.5)*separation;
            p.dx=ux*offset-centers[i][0];
            p.dy=uy*offset-centers[i][1];
          }
        }
        result.shadowMarks=window.GuestShadow.fromGroup(image,people,portraitDiameterMm,portraitDiameterGrooves);
      } catch(error) {
        result.shadowReason=error.message || 'There is too little shadow detail for every selected face.';
      }
    } else if(groupShadows) result.shadowReason='Choose at least two people to draw a group from photo shadows.';
    else if(shadows) result.shadowReason='Choose a face to draw photo shadows.';
    return result;
  }

  function verifiedGroupBoxes(image, boxes, verifyAll=false) {
    // A minimally supported face on a sleeve can resemble a head once enlarged.
    // Recheck only these borderline hits with more source pixels around each face.
    if (!verifyAll && boxes.every(box => box.n > 3)) return boxes;
    const source = document.createElement('canvas');
    source.width = image.width; source.height = image.height;
    source.getContext('2d').putImageData(image,0,0);
    const size = 140, crop = document.createElement('canvas');
    crop.width = crop.height = size;
    const ctx = crop.getContext('2d',{willReadFrequently:true});
    return boxes.filter(box => {
      if (!verifyAll && box.n > 3) return true;
      let hits = 0;
      for (const scale of [1.5,2.1]) {
        const width = scale * box.w;
        for (const reflected of verifyAll ? [false] : [false,true]) {
          ctx.setTransform(reflected ? -1 : 1,0,0,1,reflected ? size : 0,0);
          ctx.clearRect(0,0,size,size);
          ctx.drawImage(source,box.x-width/2,box.y-width/2,width,width,0,0,size,size);
          const repeat = faceBoxes(ctx.getImageData(0,0,size,size)).find(b =>
            Math.hypot(b.x-size/2,b.y-size/2) < size*.18 && Math.abs(Math.log(b.w*scale/size)) < .48);
          if (!repeat) {
            if (verifyAll) return false;
            continue;
          }
          hits++;
          if ((!verifyAll && repeat.n>=5) || hits>=2) return true;
        }
      }
      return false;
    });
  }

  async function cachedLandmarks(analysis, image, selected) {
    // Cache by box, so single portraits and group compositions can share the measurements.
    const entries = analysis.landmarks ||= new Map();
    const key=box=>[box.x,box.y,box.w,box.angle || 0].join(',');
    const missing = selected.filter(box => !entries.has(key(box)));
    if (missing.length) {
      const job = analysis.originalFile && missing.some(box=>box.w<112)
        ? withOriginal(analysis.originalFile, original=>findLandmarks(image,missing,original))
        : findLandmarks(image,missing);
      missing.forEach((box,i) => entries.set(key(box), {job, i}));
      job.catch(() => missing.forEach(box => entries.delete(key(box))));
    }
    return Promise.all(selected.map(async box => {
      const {job,i} = entries.get(key(box));
      return (await job)[i];
    }));
  }

  const unreadableHeic = new WeakSet();
  // Read the primary TIFF orientation only. Skip compressed image chunks and
  // embedded thumbnails; the browser remains responsible for decoding pixels.
  async function storedOrientation(file) {
    let buffer, offset=-1;
    async function header(at,size) {
      if (!buffer || at<offset || at+size>offset+buffer.byteLength) {
        buffer=await file.slice(at,at+Math.max(1024,size)).arrayBuffer();offset=at;
      }
      return new DataView(buffer,at-offset,size);
    }
    async function tiff(at,end) {
      let h=await header(at,8);
      const little=h.getUint16(0)===0x4949;
      if ((!little && h.getUint16(0)!==0x4d4d) || h.getUint16(2,little)!==42) return false;
      const dir=at+h.getUint32(4,little);
      if (dir+2>end) return false;
      const count=(await header(dir,2)).getUint16(0,little);
      if (dir+2+12*count>end) return false;
      h=await header(dir+2,12*count);
      for (let i=0;i<h.byteLength;i+=12) {
        if (h.getUint16(i,little)===274 && h.getUint16(i+2,little)===3 && h.getUint32(i+4,little)===1) {
          const value=h.getUint16(i+8,little);
          if (value>=2 && value<=8) return {value, at:dir+2+i+8, little};
          return null;
        }
      }
      return false;
    }
    const first=await header(0,12);
    const jpeg=first.getUint16(0)===0xffd8, png=first.getUint32(0)===0x89504e47;
    const webp=first.getUint32(0)===0x52494646 && first.getUint32(8)===0x57454250;
    if (!jpeg && !png && !webp) return false;
    let pos=jpeg?2:png?8:12;
    while(pos+12<=file.size) {
      const h=await header(pos,12);
      const chunk=pos;
      let start,end,exif;
      if (jpeg) {
        if (h.getUint8(0)!==255 || h.getUint8(1)===0xda || h.getUint8(1)===0xd9) return false;
        if (h.getUint8(1)===255) {pos++;continue;}
        end=pos+2+h.getUint16(2);
        exif=h.getUint8(1)===0xe1 && h.getUint32(4)===0x45786966 && h.getUint16(8)===0;
        start=pos+10;pos=end;
      } else {
        start=pos+8;
        end=start+h.getUint32(png?0:4,webp);
        exif=h.getUint32(png?4:0)===(png?0x65584966:0x45584946);
        if (webp && exif && h.getUint32(8)===0x45786966) start+=6;
        pos=end+(png?4:end%2);
      }
      if (end>file.size) return false;
      if (exif && start+8<=end) {
        const tag=await tiff(start,end);
        if (!tag) return null;
        // PNG protects the whole metadata chunk with a checksum. Drop it
        // from the decode copy. In JPEG and WebP, neutralize only this tag.
        const parts=png ? [file.slice(0,chunk),file.slice(pos)] : [
          file.slice(0,tag.at),new Uint8Array(tag.little ? [1,0] : [0,1]),file.slice(tag.at+2)
        ];
        return {value:tag.value, raw:new Blob(parts,{type:file.type})};
      }
    }
    return false;
  }

  async function readPhotoFile(file, read) {
    const url=URL.createObjectURL(file);
    const img=new Image();
    try {
      img.src=url;
      try { await img.decode(); }
      catch {
        if (/^image\/hei[cf]$/i.test(file.type) || /\.hei[cf]$/i.test(file.name || '')) {
          unreadableHeic.add(file);
          if (document.querySelector('meta[name=oasis-heic]')) {
            throw Error('This phone cannot open the HEIC photo. The garden laptop can make a JPEG copy.');
          }
        }
        throw Error('Could not open this photo. Try a JPEG or PNG.');
      }
      return await read(img);
    } finally {URL.revokeObjectURL(url);}
  }

  const uprightFiles=new WeakMap();
  function uprightPhoto(file) {
    if (!uprightFiles.has(file)) {
      // The same upright pixels downsample differently when a rotation or
      // mirror is still attached. This can move a detected eyelid or hairline.
      // Strip the transform once, losslessly, for every crop of that file.
      const upright=storedOrientation(file).then(stored=>stored ? readPhotoFile(stored.raw,async img=>{
        const w=img.naturalWidth,h=img.naturalHeight;
        const canvas=document.createElement('canvas');
        const swap=stored.value>=5;
        canvas.width=swap?h:w;
        canvas.height=swap?w:h;
        try {
          const transforms={
            2:[-1,0,0,1,w,0], 3:[-1,0,0,-1,w,h], 4:[1,0,0,-1,0,h],
            5:[0,1,1,0,0,0], 6:[0,1,-1,0,h,0], 7:[0,-1,-1,0,h,w], 8:[0,-1,1,0,0,w]
          };
          const ctx=canvas.getContext('2d');
          ctx.setTransform(...transforms[stored.value]);
          ctx.drawImage(img,0,0);
          return await new Promise(resolve=>canvas.toBlob(blob=>resolve(blob || file),'image/png'));
        } finally {canvas.width=canvas.height=0;}
      }) : file).catch(()=>file);
      uprightFiles.set(file,upright);
    }
    return uprightFiles.get(file);
  }

  function withOriginal(file,read) {
    return uprightPhoto(file).then(upright=>readPhotoFile(upright,read));
  }

  function decodeFile(file,analysis) {
    return withOriginal(file,img=>{
      const scale=Math.min(1,1000/Math.max(img.naturalWidth,img.naturalHeight));
      if (scale<1) {
        analysis.originalFile=file;
        analysis.originalWidth=img.naturalWidth;
        analysis.originalHeight=img.naturalHeight;
      }
      const c=document.createElement('canvas');
      c.width=Math.max(1,Math.round(img.naturalWidth*scale)); c.height=Math.max(1,Math.round(img.naturalHeight*scale));
      const ctx=c.getContext('2d',{willReadFrequently:true});
      ctx.drawImage(img,0,0,c.width,c.height);
      return ctx.getImageData(0,0,c.width,c.height);
    });
  }

  async function laptopPhoto(file) {
    const extension=file.name.split('.').pop().toLowerCase();
    const type=file.type || ({jpg:'image/jpeg',jpeg:'image/jpeg',png:'image/png',webp:'image/webp',
      avif:'image/avif',heic:'image/heic',heif:'image/heif'})[extension];
    if (!['image/avif','image/heic','image/heif'].includes(type)) {
      return !file.type && type ? file.slice(0,file.size,type) : file;
    }
    // The picker already decoded this photo. Bake the same displayed orientation
    // and full-resolution pixels into a still the offline laptop can read.
    return withOriginal(file,async img=>{
      const w=img.naturalWidth,h=img.naturalHeight;
      if (!w || !h || Math.max(w,h)>16384 || w*h>50500000) throw Error('Choose a smaller copy for the garden laptop.');
      const canvas=document.createElement('canvas');
      canvas.width=w; canvas.height=h;
      try {
        const ctx=canvas.getContext('2d');
        ctx.fillStyle='white'; ctx.fillRect(0,0,w,h);
        ctx.drawImage(img,0,0);
        for (const quality of [.97,.86]) {
          const jpeg=await new Promise(resolve=>canvas.toBlob(resolve,'image/jpeg',quality));
          if (jpeg?.type==='image/jpeg' && jpeg.size>0 && jpeg.size<=16*1024*1024) return jpeg;
        }
        throw Error('Choose a smaller copy for the garden laptop.');
      } finally {
        canvas.width=canvas.height=0;
      }
    });
  }

  // A room-sized group can lose glasses, lips and hair when the entire image
  // is reduced for face detection. Measure both landmarks and visible features
  // from a bounded crop of the original pixels. Picker coordinates stay tied
  // to the same overview before and after a person is selected.
  async function closeGroupTiles(analysis, overview, boxes) {
    if (!analysis.originalFile || !boxes.some(box=>box.w<160)) return null;
    const key=boxes.map(b=>[b.x,b.y,b.w,b.angle || 0].join(',')).join(';');
    if (analysis.groupTiles?.key===key) return analysis.groupTiles.result;
    const sx=analysis.originalWidth/overview.width, sy=analysis.originalHeight/overview.height;
    // Choose exact integer camera-pixel rectangles before applying any memory limit.
    const regions=boxes.map(box=>{
      const cx=box.x*sx, cy=box.y*sy, width=box.w*sx;
      const x=Math.max(0,Math.floor(cx-1.35*width)), y=Math.max(0,Math.floor(cy-1.35*width));
      const right=Math.min(analysis.originalWidth,Math.ceil(cx+1.35*width));
      const lower=Math.min(analysis.originalHeight,Math.ceil(cy+1.35*width));
      return {box,cx,cy,width,x,y,w:right-x,h:lower-y};
    });
    const area=regions.reduce((s,r)=>s+r.w*r.h,0);
    const scale=Math.min(1,Math.sqrt(6000000/area),2000/Math.max(...regions.map(r=>Math.max(r.w,r.h))));
    if (scale*Math.min(sx,sy)<1.25) return null;
    const result=withOriginal(analysis.originalFile,img=>regions.map(({box,cx,cy,width,x,y,w,h})=>{
      const c=document.createElement('canvas');c.width=Math.ceil(scale*w);c.height=Math.ceil(scale*h);
      const ctx=c.getContext('2d',{willReadFrequently:true});
      ctx.drawImage(img,x,y,w,h,0,0,scale*w,scale*h);
      return {image:ctx.getImageData(0,0,c.width,c.height),analysis:{},x:x*scale,y:y*scale,
        box:{...box,x:(cx-x)*scale,y:(cy-y)*scale,w:width*scale}};
    }));
    // Re-previewing a caption or size can reuse the original pixels and
    // landmarks. Only the most recent group selection is retained per file.
    analysis.groupTiles={key,result};
    result.catch(()=>{if (analysis.groupTiles?.result===result) delete analysis.groupTiles;});
    return result;
  }

  async function portraitDetail(analysis,image,boxes) {
    // Narrow details such as the glasses rim still benefit from a sharper
    // crop even when the face already fills the 112-pixel landmark input.
    if (!analysis.originalFile || !boxes.some(b=>b.w<160)) return null;
    const left=Math.max(0,Math.floor(Math.min(...boxes.map(b=>b.x-1.4*b.w))));
    const upper=Math.max(0,Math.floor(Math.min(...boxes.map(b=>b.y-1.2*b.w))));
    const right=Math.min(image.width,Math.ceil(Math.max(...boxes.map(b=>b.x+1.4*b.w))));
    const lower=Math.min(image.height,Math.ceil(Math.max(...boxes.map(b=>b.y+1.6*b.w))));
    const w=right-left, h=lower-upper;
    const sx=analysis.originalWidth/image.width, sy=analysis.originalHeight/image.height;
    const scale=Math.min(sx,sy,1000/Math.max(w,h));
    if (scale<1.25) return null;
    const key=[left,upper,right,lower].join(',');
    if (analysis.detail?.key!==key) {
      const result=withOriginal(analysis.originalFile,img=>{
        const c=document.createElement('canvas');
        c.width=Math.ceil(w*scale); c.height=Math.ceil(h*scale);
        const ctx=c.getContext('2d',{willReadFrequently:true});
        ctx.drawImage(img,left*sx,upper*sy,w*sx,h*sy,0,0,w*scale,h*scale);
        return {image:ctx.getImageData(0,0,c.width,c.height),analysis:{},
          place:b=>({...b,x:(b.x-left)*scale,y:(b.y-upper)*scale,w:b.w*scale})};
      });
      analysis.detail={key,result};
      result.catch(()=>{if (analysis.detail?.result===result) delete analysis.detail;});
    }
    return analysis.detail.result;
  }

  // Nothing is persisted. Dropping the chosen File also releases its decoded photo and face measurements.
  const fileAnalyses = new WeakMap();
  function fileAnalysis(file) {
    if(!file || typeof file!=='object')throw Error('Choose a photo first.');
    let analysis = fileAnalyses.get(file);
    if (!analysis) {
      analysis = {};
      analysis.pixels=decodeFile(file,analysis);
      fileAnalyses.set(file, analysis);
      analysis.pixels.catch(() => fileAnalyses.delete(file));
    }
    return analysis;
  }

  async function fromFile(file, options) {
    const analysis=fileAnalysis(file);
    const result=await fromPixels(await analysis.pixels,options,analysis);
    if(result.soloSmile?.open && window.GuestReviewedPortrait){
      const drawing=await window.GuestReviewedPortrait.forPhoto(file,options?.face,result.soloSmile,analysis);
      if(drawing)result.reviewedPortrait=drawing;
    }
    return result;
  }

  async function inspectSeatPhoto(file) {
    const analysis=fileAnalysis(file), image=await analysis.pixels;
    const boxes=await detectedFaces(image,analysis);
    return {sourceWidth:image.width,sourceHeight:image.height,facesDetected:boxes.length,
      detectedFaces:boxes.map(({x,y,w})=>({x,y,w}))};
  }

  // Keep each face in its own photo's coordinates right through the feature
  // measurements. Only the finished strokes are fitted into a shared disc.
  async function fromSeatPhotos(entries,{portraitDiameterGrooves,portraitTrackingGrooves}={}) {
    if(!Array.isArray(entries) || entries.length<2)throw Error('Choose a photo for at least two chairs.');
    const order=[];
    for(const [sourceIndex,entry] of entries.entries()) {
      const analysis=fileAnalysis(entry?.file), image=await analysis.pixels;
      const boxes=await detectedFaces(image,analysis), face=entry.face;
      // Detected frames carry a private head tilt used by the landmark model.
      // A hand-drawn frame is upright in this source photo.
      const box=boxes.find(b=>face && b.x===face.x && b.y===face.y && b.w===face.w) ||
        framedFace(face && {x:face.x,y:face.y,w:face.w},image);
      const detail=await portraitDetail(analysis,image,[box]);
      const framed=detail ? detail.place(box) : box, pixels=detail?.image || image;
      const [L]=await cachedLandmarks(detail?.analysis || analysis,pixels,[framed]);
      order.push({image:pixels,L,box:framed,sourceBox:box,sourceIndex});
    }
    const drawing=seatedDrawing(order,portraitDiameterGrooves,portraitTrackingGrooves);
    for (const face of drawing.seatFaces) {
      const {x,y,w}=order[face.sourceIndex].sourceBox;
      face.sourceBox={x,y,w};
    }
    return {...drawing,name:'Seated portraits',entryAngle:-Math.PI/2,facesDetected:order.length,
      hasPortrait:true,groupStyle:'seats'};
  }
  window.GuestPhoto={fromPixels,fromFile,inspectSeatPhoto,fromSeatPhotos,laptopPhoto,uprightPhoto,
    needsHeicReader:file=>unreadableHeic.has(file)};
})();
