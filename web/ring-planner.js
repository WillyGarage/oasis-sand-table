/* Assemble the same continuous middle-ring route used by tools/ring_scene.py.
   Angles are cumulative radians; the second coordinate is the working radius. */
const OasisRingPlanner = (() => {
  const tau = Math.PI * 2;
  const precision = 100000000;
  const fileLimit = 11998;
  const has = (object, key) => Object.prototype.hasOwnProperty.call(object, key);

  function unpack(encoded) {
    const bytes = Uint8Array.from(atob(encoded), char => char.charCodeAt(0));
    if (!bytes.length || bytes.length % 8) throw new Error("Invalid ring path data.");
    const view = new DataView(bytes.buffer);
    let theta = 0, radius = 0;
    const points = [];
    for (let i = 0; i < bytes.length; i += 8) {
      theta += view.getInt32(i, true);
      radius += view.getInt32(i + 4, true);
      points.push([theta / precision, radius / precision]);
    }
    return points;
  }

  function join(sections, tolerance = 0.000001) {
    const result = [];
    for (const section of sections) {
      if (!section.length) throw new Error("An empty section cannot be drawn.");
      const first = section[0];
      const end = result.length ? result[result.length - 1] : first;
      const offset = tau * Math.round((end[0] - first[0]) / tau);
      if (Math.abs(end[0] - first[0] - offset) > tolerance ||
          Math.abs(end[1] - first[1]) > tolerance) throw new Error("The ring path is disconnected.");
      for (let i = result.length ? 1 : 0; i < section.length; i++) {
        result.push([section[i][0] + offset, section[i][1]]);
      }
    }
    return result;
  }

  function line(a, r, b, s) {
    const steps = Math.max(1, Math.ceil(Math.abs(b - a) / 0.05), Math.ceil(Math.abs(s - r) / 0.015));
    return Array.from({length: steps + 1}, (_, i) => [a + (b - a) * i / steps, r + (s - r) * i / steps]);
  }

  function checkCustomShape(shape) {
    if (!Array.isArray(shape) || shape.length < 4 || shape.length > 8000) {
      throw new Error("A custom drawing needs 4 to 8,000 points including its return.");
    }
    if (!shape.every(p => Array.isArray(p) && p.length === 2 && p.every(Number.isFinite) &&
        Math.hypot(p[0], p[1]) <= 1 + 1e-8)) throw new Error("Custom drawing points must fit in the unit circle.");
    const [x0, y0] = shape[0];
    const end = shape[shape.length - 1];
    if (Math.hypot(end[0] - x0, end[1] - y0) > 1e-6) throw new Error("A custom drawing must return to its start.");
    if (!shape.some(([x, y]) => Math.hypot(x - x0, y - y0) > 1e-6)) {
      throw new Error("A custom drawing must contain at least one stroke.");
    }
  }

  function guestCoordinates(shape, slot, geometry) {
    const angle = geometry.angles[slot];
    const cx = geometry.center * Math.cos(angle), cy = geometry.center * Math.sin(angle);
    const rotation = geometry.faceEdge ? angle + Math.PI/2 : 0;
    const c = Math.cos(rotation), s = Math.sin(rotation);
    return shape.slice(0,-1).map(([x,y]) =>
      [cx + geometry.scale * (c*x-s*y), cy + geometry.scale * (s*x+c*y)]);
  }
  const guestStepCount=(dx,dy)=>Math.max(1,Math.ceil(Math.hypot(dx,dy)/.01));
  const guestTravelLimit=32000;
  function fitsGuestTravel(shape, slot, geometry) {
    const xy=guestCoordinates(shape,slot,geometry);
    let total=1, previous=xy.at(-1);
    for(const point of xy){
      total+=guestStepCount(point[0]-previous[0],point[1]-previous[1]);
      if(total>guestTravelLimit)return false;
      previous=point;
    }
    return true;
  }
  function customExcursion(shape, slot, geometry, drawing) {
    checkCustomShape(shape);
    const angle=geometry.angles[slot], local=guestCoordinates(shape,slot,geometry);
    // Enter at the outermost point. The central angle of this slot stays fixed
    // even for an asymmetrical drawing hanging from one end, like a guitar.
    let entry = 0, outerRadius = 0;
    for (let i = 0; i < local.length; i++) {
      const radius = Math.hypot(...local[i]);
      if (radius > outerRadius) { outerRadius = radius; entry = i; }
    }
    const xy = local.slice(entry).concat(local.slice(0, entry + 1));
    const path = [];
    let previousAngle = angle;
    function point(x, y) {
      const raw = Math.atan2(y, x);
      const theta = raw + tau * Math.round((previousAngle - raw) / tau);
      const radius = Math.hypot(x, y);
      if (radius < geometry.bounds[0] || radius > geometry.bounds[1]) {
        throw new Error("A custom drawing crossed the middle ring’s boundary.");
      }
      path.push([theta, radius]);
      previousAngle = theta;
    }
    point(...xy[0]);
    for (let i = 1; i < xy.length; i++) {
      const [x, y] = xy[i - 1];
      const dx = xy[i][0] - x, dy = xy[i][1] - y;
      const count = guestStepCount(dx,dy);
      if (path.length + count > guestTravelLimit) throw new Error("Simplify this drawing to fewer than 32,000 travel points.");
      for (let k = 1; k <= count; k++) point(x + dx * k / count, y + dy * k / count);
    }
    const theta = path[0][0], rail = geometry.rail;
    const [start, finish] = geometry.gates[slot];
    if (!(start < theta && theta < finish)) throw new Error("A custom drawing fell outside its assigned sector.");
    const entrance = line(theta, rail, theta, outerRadius);
    const lead = line(start, rail, theta, rail);
    if (drawing) {
      drawing.first = lead.length + entrance.length - 2;
      drawing.last = drawing.first + path.length - 1;
    }
    return join([lead, entrance, path, entrance.slice().reverse(), line(theta, rail, finish, rail)]);
  }

  // Find the enclosed spaces the generated ink drawing actually contains. The
  // raster measures centerlines before the ball broadens them into grooves.
  function smallInkOpenings(path, groove) {
    const xs=path.map(p=>p[0]), ys=path.map(p=>p[1]);
    const step=groove/24, x0=Math.min(...xs)-3*step, y0=Math.min(...ys)-3*step;
    const width=Math.ceil((Math.max(...xs)-x0)/step)+4, height=Math.ceil((Math.max(...ys)-y0)/step)+4;
    if (Math.max(width,height)>480 || Math.min(width,height)<30) return [];
    const ink=new Uint8Array(width*height);
    for (let i=0; i<path.length; i++) {
      const a=path[i], b=path[(i+1)%path.length], dx=b[0]-a[0], dy=b[1]-a[1];
      const steps=Math.max(1,Math.ceil(Math.hypot(dx,dy)/(.5*step)));
      for (let j=0; j<=steps; j++) {
        const x=Math.round((a[0]+dx*j/steps-x0)/step), y=Math.round((a[1]+dy*j/steps-y0)/step);
        ink[y*width+x]=1;
      }
    }
    const distance=Float32Array.from(ink,p=>p ? 0 : width+height);
    // An eight-neighbor distance to the nearest stroke, in raster pixels.
    for (const sign of [1,-1]) {
      for (let row=1; row<height-1; row++) for (let col=1; col<width-1; col++) {
        const y=sign===1 ? row : height-1-row, x=sign===1 ? col : width-1-col, k=y*width+x;
        distance[k]=Math.min(distance[k],1+distance[k-sign],1+distance[k-sign*width],
          Math.SQRT2+distance[k-sign*(width+1)],Math.SQRT2+distance[k-sign*(width-1)]);
      }
    }
    const queue=new Int32Array(ink.length), holes=[];
    // A one-cell frame keeps the flood inside this array. The component at
    // (1,1) is connected to the background and cannot become a target.
    ink.fill(1,0,width); ink.fill(1,ink.length-width);
    for (let y=1;y<height-1;y++) { ink[y*width]=1; ink[y*width+width-1]=1; }
    for (let start=width+1;start<ink.length-width;start++) {
      if (ink[start]) continue;
      let read=0, count=1, center=start;
      queue[0]=start; ink[start]=1;
      while (read<count) {
        const k=queue[read++];
        if (distance[k]>distance[center]) center=k;
        for (const next of [k-width,k+width,k-1,k+1]) if (!ink[next]) {
          ink[next]=1; queue[count++]=next;
        }
      }
      const radius=distance[center]*step;
      if (start===width+1 || radius<.24*groove) continue;
      holes.push({x:x0+(center%width)*step, y:y0+Math.floor(center/width)*step,
        radius, compact:count*step*step<=3.8*Math.PI*radius*radius});
    }
    return holes.sort((a,b)=>b.radius-a.radius);
  }

  function openInkDetails(path, groove, boundary, budget) {
    const observed=smallInkOpenings(path,groove), holes=[];
    function edgeDistance(hole, points) {
      let best=Infinity;
      for (let i=0;i<points.length;i++) {
        const a=points[i], b=points[(i+1)%points.length], dx=b[0]-a[0], dy=b[1]-a[1];
        const u=hole.x-a[0], v=hole.y-a[1], length=dx*dx+dy*dy;
        const t=length ? Math.max(0,Math.min(1,(u*dx+v*dy)/length)) : 0;
        best=Math.min(best,Math.hypot(u-t*dx,v-t*dy));
      }
      return best;
    }
    for (const hole of observed) {
      if (!hole.compact || hole.radius>=.80*groove) continue;
      hole.radius=edgeDistance(hole,path);
      if (hole.radius<.22*groove) continue;
      const gain=Math.min(.82*groove-hole.radius,.41*groove);
      // Leave wide bands and already-readable openings as the guest drew them.
      if (gain<.09*groove || holes.some(h=>Math.hypot(h.x-hole.x,h.y-hole.y)<1.65*groove)) continue;
      holes.push({...hole,gain,reach:hole.radius+1.8*gain+groove});
      if (holes.length===8) break;
    }
    if (!holes.length) return path;
    const protectedSpaces=observed.filter(h=>h.radius>.64*groove).map(h=>({...h,
      keep:Math.min(edgeDistance(h,path)-.025*groove,groove)}));
    function moved(p) {
      let dx=0,dy=0;
      for (const {x,y,radius,gain,reach} of holes) {
        const a=p[0]-x, b=p[1]-y, d=Math.hypot(a,b);
        if (!d || d>=reach) continue;
        const push=gain*Math.min(d/radius,(reach-d)/(reach-radius))/d;
        dx+=a*push; dy+=b*push;
      }
      if (!dx && !dy) return p;
      // Keep the guest place, the separation from its companion, and the
      // silhouette's extreme tips within the original fitted convex hull.
      let fraction=Math.min(1,.41*groove/Math.hypot(dx,dy));
      // A small window can share a wall with a larger one. Limit movement
      // towards an already open patch before applying the hull constraint.
      for (const h of protectedSpaces) {
        const u=p[0]-h.x,v=p[1]-h.y,d=Math.hypot(u,v),toward=-(dx*u+dy*v);
        if (toward>0) fraction=Math.min(fraction,Math.max(0,d-h.keep)*d/toward);
      }
      for (let i=0;i<boundary.length;i++) {
        const a=boundary[i], b=boundary[(i+1)%boundary.length], ex=b[0]-a[0], ey=b[1]-a[1];
        const crossing=ey*dx-ex*dy;
        if (crossing>0) fraction=Math.min(fraction,
          Math.max(0,ex*(p[1]-a[1])-ey*(p[0]-a[0]))/crossing);
      }
      return [p[0]+dx*fraction,p[1]+dy*fraction];
    }
    const revised=[];
    for (let i=0;i<path.length;i++) {
      const a=path[i],b=path[(i+1)%path.length],dx=b[0]-a[0],dy=b[1]-a[1],squared=dx*dx+dy*dy;
      let steps=1;
      if (squared && holes.some(h=>{
        const t=Math.max(0,Math.min(1,((h.x-a[0])*dx+(h.y-a[1])*dy)/squared));
        return Math.hypot(a[0]+t*dx-h.x,a[1]+t*dy-h.y)<h.reach;
      })) steps=Math.max(1,Math.ceil(Math.sqrt(squared)/(.2*groove)));
      if (revised.length+steps>budget) return path;
      for (let j=0;j<steps;j++) revised.push(moved(j ? [a[0]+dx*j/steps,a[1]+dy*j/steps] : a));
    }
    // Clipping a target beside a silhouette may leave it too tight to read.
    // Keep the exact earlier path unless at least one clear patch survives.
    const improved=holes.some(h=>edgeDistance(h,revised)>=Math.max(.65*groove,h.radius+.12*groove));
    return improved ? revised : path;
  }

  // Two upright drawings share one local disc. The connecting groove starts
  // and ends on their outlines; the outer ring supplies its own entrance.
  function pair(catalog, first, second, relation, fitTallPairs=true) {
    if (relation==='below') return pair(catalog,second,first,'above');
    if (relation==='right') return pair(catalog,second,first,'beside');
    const directions = {above:[0,1], beside:[-1,0], behind:[-.82,.57], lean:[-1,0]};
    if (!has(directions,relation)) throw Error('Choose above, below, beside, behind, or leaning.');
    const savedBeside = relation==='beside' && Boolean(first?.points || second?.points);
    if (!catalog?.pairMotifs || !(catalog.pairGroove > 0)) throw Error('Open the updated garden to place two drawings together.');
    const distance = (a,b) => Math.hypot(a[0]-b[0], a[1]-b[1]);
    const bounds = (points,axis) => {
      let lo=Infinity, hi=-Infinity;
      for (const p of points) {lo=Math.min(lo,p[axis]); hi=Math.max(hi,p[axis]);}
      return [lo,hi];
    };
    function comet() {
      // A round nucleus and two tapering trails can be distinguished at this
      // scale. The phone's emoji has several near-coincident filled contours.
      const p=[], radius=.245, cx=-.48;
      for (let i=0; i<=40; i++) {
        const a=Math.PI/2+i*tau/40; p.push([cx+radius*Math.cos(a),radius*Math.sin(a)]);
      }
      p.push([-.22,.285],[.10,.292],[.43,.275],[.82,.21],[.40,.15],[.10,.10],[-.12,.04],
             [.11,.065],[.39,.05],[.68,.005],[.31,-.035],[-.04,-.12],[-.28,-.207],[-.48,-.245]);
      // Leave along the front half of the nucleus, in its existing groove.
      for (let i=1; i<=20; i++) p.push(p[20-i]);
      const a=.36, c=Math.cos(a), s=Math.sin(a);
      return p.map(([x,y])=>[c*x-s*y,s*x+c*y]);
    }
    function stroke(art) {
      if (art && has(catalog.pairMotifs,art.id)) return unpack(catalog.pairMotifs[art.id]);
      if (art?.points) {
        checkCustomShape(art.points);
        return art.points;
      }
      if (!art?.glyph) throw Error('One subject has no drawing yet. Sketch the pair.');
      if (art.glyph.replace(/\uFE0F/g,'')==='☄') return comet();
      const lines=globalThis.GuestArt.glyphStrokes(art.glyph);
      const top=lines.flat().reduce((best,p)=>p[1]>best[1]?p:best);
      return globalThis.GuestArt.manageStrokes(lines,top);
    }
    if (relation==='lean' && first?.id==='guitar' && second?.id==='books' && catalog.pairMotifs.guitar_books) {
      return unpack(catalog.pairMotifs.guitar_books);
    }
    let firstPath=stroke(first), secondPath=stroke(second);
    // Photos can use nearly the whole 8,000-point budget by themselves.
    // When combining them would exceed it, merge only sub-groove samples.
    // Scaling into the disc can enlarge this tolerance to at most 1/32 groove.
    function thin(points) {
      const xs=bounds(points,0), ys=bounds(points,1);
      const tolerance = Math.max(xs[1]-xs[0],ys[1]-ys[0])*catalog.pairGroove/64;
      const extrema = new Set([points.findIndex(p=>p[0]===xs[0]), points.findIndex(p=>p[0]===xs[1]),
                               points.findIndex(p=>p[1]===ys[0]), points.findIndex(p=>p[1]===ys[1])]);
      const kept = [points[0]];
      for (let i=1; i<points.length-1; i++) {
        const p=points[i];
        if (extrema.has(i) || distance(p,kept.at(-1)) > tolerance) kept.push(p);
      }
      return kept.concat([points.at(-1)]);
    }
    const backPasses = relation==='behind' ? 2 : 1;
    if (firstPath.length*backPasses + secondPath.length + 3 > 8000) {
      if (first.points) firstPath=thin(firstPath);
      if (second.points) secondPath=thin(secondPath);
    }
    if (relation!=='behind' && firstPath.length+secondPath.length+3 > 8000)
      throw Error('These drawings have too much fine detail for one place. Try a simpler subject.');

    function centered(raw, size, tilt) {
      if (raw.length<3 || distance(raw[0],raw.at(-1))>.001) throw Error('Sketch the pair as a continuous drawing.');
      const xs=bounds(raw,0), ys=bounds(raw,1), cx=(xs[0]+xs[1])/2, cy=(ys[0]+ys[1])/2;
      const scale=size/Math.max(xs[1]-xs[0],ys[1]-ys[0]), c=Math.cos(tilt), s=Math.sin(tilt);
      return raw.slice(0,-1).map(([x,y])=>[scale*(c*(x-cx)-s*(y-cy)),scale*(s*(x-cx)+c*(y-cy))]);
    }
    const sky = relation === 'above';
    const smallComet = a => a?.glyph?.replace(/\uFE0F/g,'')==='☄';
    const aSize = relation === 'behind' ? .77 : sky && smallComet(first) ? .72 : 1;
    const bSize = sky && smallComet(second) ? .72 : 1;
    let a=centered(firstPath,aSize,relation==='lean'?-.34:0);
    let b=centered(secondPath,bSize,0);
    function hull(points) {
      const ordered=points.slice().sort((p,q)=>p[0]-q[0] || p[1]-q[1]);
      function half(list) {
        const edge=[];
        for (const p of list) {
          while(edge.length>=2) {
            const v=edge.at(-2), w=edge.at(-1);
            if ((w[0]-v[0])*(p[1]-v[1]) > (w[1]-v[1])*(p[0]-v[0])) break;
            edge.pop();
          }
          edge.push(p);
        }
        return edge.slice(0,-1);
      }
      return half(ordered).concat(half(ordered.reverse()));
    }
    // Slide the first silhouette along the requested axis until the hulls
    // meet. This lets the objects fill the disc even when one is tall and thin.
    const lift=38*Math.PI/180;
    let direction=savedBeside ? [-Math.cos(lift),(first.points ? -1 : 1)*Math.sin(lift)] : directions[relation];
    const offset=sky ? [.31*direction[1],0] : [0,savedBeside ? 0 : relation==='lean'?.08:.04];
    const ha=hull(a), hb=hull(b);
    const gap=relation==='behind' ? -.16 : catalog.pairGroove*(savedBeside ? 1.5 : relation==='lean' ? .25 : 1.2);
    function separation(axis) {
      let along=Infinity;
      for (const outline of [ha,hb]) for (let i=0; i<outline.length; i++) {
        const p=outline[i],q=outline[(i+1)%outline.length], len=distance(p,q);
        if (!len) continue;
        let nx=(q[1]-p[1])/len, ny=(p[0]-q[0])/len;
        let speed=nx*axis[0]+ny*axis[1];
        if (Math.abs(speed)<.0001) continue;
        if(speed<0){nx=-nx; ny=-ny; speed=-speed;}
        const alo=Math.min(...ha.map(v=>v[0]*nx+v[1]*ny)), bhi=Math.max(...hb.map(v=>v[0]*nx+v[1]*ny));
        along=Math.min(along,(bhi-alo+gap-offset[0]*nx-offset[1]*ny)/speed);
      }
      return along;
    }
    function enclosingCircle(all) {
      const xs=bounds(all,0), ys=bounds(all,1);
      let cx=(xs[0]+xs[1])/2, cy=(ys[0]+ys[1])/2;
      let radius=Math.max(...all.map(p=>Math.hypot(p[0]-cx,p[1]-cy)));
      if (savedBeside) {
        // The opposite tips of an asymmetric pair can fit a smaller circle
        // than its bounding box suggests. Check every point before enlarging it.
        const farthest = p => all.reduce((best,q)=>distance(q,p)>distance(best,p) ? q : best);
        const u=farthest([cx,cy]), v=farthest(u);
        const center=[(u[0]+v[0])/2,(u[1]+v[1])/2];
        const needed=Math.max(...all.map(p=>distance(p,center)));
        if (needed<radius) { [cx,cy]=center; radius=needed; }
      }
      return [cx,cy,radius];
    }
    let along=separation(direction);
    function upright(raw) {
      const [lo,hi]=bounds(raw,0), [bottom,top]=bounds(raw,1);
      return top-bottom > 1.15*(hi-lo);
    }
    let repositioned=false;
    // Limit the alternative fits to small hulls so dense photo outlines keep
    // their existing single-pass placement cost on a phone.
    if (fitTallPairs && savedBeside && ha.length+hb.length<=160 && upright(a) && upright(b)) {
      // Try a level baseline and a modest rise on either side. A metronome
      // can use the space beside a guitar neck while both subjects stay upright.
      function fittedScale(axis,span) {
        const left=ha.map(([x,y])=>[x+axis[0]*span,y+axis[1]*span]);
        return .975/enclosingCircle(left.concat(hb))[2];
      }
      // Keep the earlier layout unless the gain exceeds half a groove in height.
      let threshold=fittedScale(direction,along)+catalog.pairGroove/2;
      for (const angle of [0,-Math.PI/8,Math.PI/8]) {
        const axis=[-Math.cos(angle),Math.sin(angle)];
        const span=separation(axis), scale=fittedScale(axis,span);
        if (scale>threshold) {
          direction=axis; along=span; threshold=scale; repositioned=true;
        }
      }
    }
    const sightLine = sky && smallComet(first) && second.id === 'telescope';
    if (sightLine) {
      // Set the nucleus on the refractor's optical axis. The first 19 points
      // follow its real objective: opposite lips, with the front glass between.
      // Let the trail stream back across the open sky, clear of the tripod.
      for (const p of a) p[0] = -p[0];
      const glass=b[9], lens=b[0].map((v,i)=>(v+b[18][i])/2);
      const axis=glass.map((v,i)=>(v-lens[i])/distance(glass,lens));
      const nucleus=a[0].map((v,i)=>(v+a[20][i])/2);
      const radius=distance(a[0],nucleus);
      const centerlines=4.8*catalog.pairGroove;
      let fit=1;
      for(let trial=0; trial<3; trial++) {
        const dx=glass[0]+axis[0]*(radius+centerlines/fit)-(nucleus[0]+offset[0]);
        const dy=glass[1]+axis[1]*(radius+centerlines/fit)-(nucleus[1]+offset[1]);
        offset[0]+=dx; offset[1]+=dy;
        const placed=a.map(([x,y])=>[x+offset[0], y+offset[1]]).concat(b);
        const xs=bounds(placed,0), ys=bounds(placed,1);
        fit=.975/Math.max(...placed.map(p=>Math.hypot(p[0]-(xs[0]+xs[1])/2,p[1]-(ys[0]+ys[1])/2)));
      }
      along=0;
    }
    if (!Number.isFinite(along)) throw Error('These subjects need a wider drawing. Try a sketch.');
    for (const p of a) {p[0]+=offset[0]+direction[0]*along; p[1]+=offset[1]+direction[1]*along;}
    const all=a.concat(b);
    const [cx,cy,radius]=enclosingCircle(all);
    const scale=.975/radius;
    for (const p of all) {p[0]=scale*(p[0]-cx);p[1]=scale*(p[1]-cy);}

    // When the subjects have a gap, open up the fine detail in fresh ink at
    // its final size. Overlapping compositions and saved marks keep their paths.
    // Each outline is walked from a port and back; the final point closes the pair.
    const maxPairVertices=8000-5;
    if (savedBeside || sky) {
      if (first.generated) a=openInkDetails(a,catalog.pairGroove,hull(a),maxPairVertices-b.length);
      if (second.generated) b=openInkDetails(b,catalog.pairGroove,hull(b),maxPairVertices-a.length);
    }

    if (relation === 'behind') {
      // Cut the rear object at the actual foreground strokes. Each visible
      // portion leaves and rejoins the foreground at that exact crossing.
      // This keeps a connector from appearing through the face of the object.
      const cross=(u,v,x,y)=>u*y-v*x;
      const cuts=[], runs=[];
      let visibleParts=0, hasHidden=false;
      let current=null, length=0, visible=0;
      function inside(point) {
        let odd=false;
        for(let j=0,k=b.length-1; j<b.length; k=j++) {
          const q=b[j], r=b[k];
          if ((q[1]>point[1]) !== (r[1]>point[1]) &&
              point[0]<(r[0]-q[0])*(point[1]-q[1])/(r[1]-q[1])+q[0]) odd=!odd;
        }
        return odd;
      }
      for(let i=0; i<a.length; i++) {
        const p=a[i], q=a[(i+1)%a.length], dx=q[0]-p[0], dy=q[1]-p[1];
        if (!dx && !dy) continue;
        const edge=[{t:0,point:p},{t:1,point:q}];
        for(let j=0; j<b.length; j++) {
          const u=b[j], v=b[(j+1)%b.length], ex=v[0]-u[0], ey=v[1]-u[1];
          const den=cross(dx,dy,ex,ey);
          if (Math.abs(den)<1e-12) continue;
          const wx=u[0]-p[0], wy=u[1]-p[1], t=cross(wx,wy,ex,ey)/den, f=cross(wx,wy,dx,dy)/den;
          if (t>=0 && t<=1 && f>=0 && f<=1) edge.push({t, front:j, f, point:[p[0]+dx*t,p[1]+dy*t]});
        }
        edge.sort((x,y)=>x.t-y.t);
        for(let j=1; j<edge.length; j++) {
          const u=edge[j-1], v=edge[j];
          if(v.t-u.t<1e-9) continue;
          const mid=(u.t+v.t)/2;
          const hidden=inside([p[0]+mid*dx,p[1]+mid*dy]);
          if (hidden) hasHidden=true; else visibleParts++;
          // Each visible interval has an outward and a return stroke. Stop
          // counting highly interwoven drawings once the file cannot fit.
          if (hasHidden && b.length+2*visibleParts+1 > 8000)
            throw Error('This pair has too much fine detail. Try a simpler subject.');
          cuts.push({start:u, end:v, hidden});
        }
      }
      const start=cuts.findIndex(part=>part.hidden);
      if (start>=0) {
        for(let i=0; i<cuts.length; i++) {
          const part=cuts[(start+i)%cuts.length], d=distance(part.start.point,part.end.point);
          length+=d;
          if (part.hidden) {current=null; continue;}
          visible+=d;
          if (!current) {
            current={port:part.start, points:[part.start.point]};
            runs.push(current);
          }
          current.points.push(part.end.point);
          if (part.end.front !== undefined) current.end=part.end;
        }
        // A crossing exactly on a source vertex may belong to the preceding
        // edge. The other end of that visible portion is an equally good gate.
        const visits=new Map();
        for (const run of runs) {
          if (run.port.front===undefined && run.end) {run.port=run.end; run.points.reverse();}
          if (run.port.front===undefined) throw Error('The outlines meet too closely here. Try the pair beside each other.');
          const list=visits.get(run.port.front) || [];
          list.push(run); visits.set(run.port.front,list);
        }
        if (visible < .48*length) throw Error('The front drawing hides too much. Try the pair beside each other.');
        const path=[];
        for(let j=0; j<b.length; j++) {
          path.push(b[j]);
          for(const run of (visits.get(j)||[]).sort((u,v)=>u.port.f-v.port.f)) {
            path.push(...run.points, ...run.points.slice(0,-1).reverse());
          }
        }
        path.push(b[0]);
        if(path.length>8000) throw Error('This pair has too much fine detail. Try a simpler subject.');
        return path;
      }
    }

    // Closest points of two disjoint polylines lie at a vertex and its
    // projection onto the opposite segment. Insert the projected point
    // exactly, so even the travel to a long barrel or book spine stays outside.
    let best=Infinity, ports;
    function closest(vertices, edges, reverse) {
      for(let j=0; j<edges.length; j++) {
        const a=edges[j], b=edges[(j+1)%edges.length], dx=b[0]-a[0], dy=b[1]-a[1];
        const sq=dx*dx+dy*dy;
        for(let i=0; i<vertices.length; i++) {
          const p=vertices[i], k=sq?Math.max(0,Math.min(1,((p[0]-a[0])*dx+(p[1]-a[1])*dy)/sq)):0;
          const x=a[0]+k*dx,y=a[1]+k*dy, d=(p[0]-x)**2+(p[1]-y)**2;
          if(d>=best)continue;
          best=d;
          const vertex={at:i,point:p}, edge={at:j,point:[x,y]};
          ports=reverse?[edge,vertex]:[vertex,edge];
        }
      }
    }
    if (sightLine) {
      const glass = b[9], center = a[0].map((v,i)=>(v+a[20][i])/2);
      const near = center.map((v,i)=>v - (v-glass[i])*distance(a[0],center)/distance(glass,center));
      let tip=0;
      for(let i=1; i<40; i++) if(distance(a[i],near)<distance(a[tip],near)) tip=i;
      ports=[{at:tip,point:a[tip]}, {at:9,point:glass}];
      best=distance(a[tip],glass)**2;
    } else {
      closest(a,b,false); closest(b,a,true);
    }
    function walk(points, port) {
      const i=port.at+1;
      return [port.point,...points.slice(i),...points.slice(0,i),port.point];
    }
    const path=walk(a,ports[0]).concat(walk(b,ports[1]),[ports[0].point]);
    if(path.length>8000 || Math.sqrt(best)>.50) {
      if (repositioned) return pair(catalog,first,second,relation,false);
      throw Error('These two subjects leave too long a line between them. Try a sketch.');
    }
    return path;
  }

  function checkSelection(catalog,ids,customMotifs) {
    if (!catalog || catalog.version !== 1 || catalog.file_limit !== fileLimit) {
      throw new Error("Unrecognized ring catalog.");
    }
    if (!Array.isArray(ids) || ids.length !== 3 || !ids.every(id => typeof id === "string" && id.length > 0)) {
      throw new Error("Choose one drawing for each of the three places.");
    }
    if (!customMotifs || typeof customMotifs !== "object" || Array.isArray(customMotifs)) {
      throw new Error("Custom drawings must be supplied by name.");
    }
    for (const id of ids) {
      const standard = has(catalog.subjects,id) || id === catalog.openSubject;
      if (standard && has(customMotifs,id)) {
        throw new Error("A custom drawing shares a name with the catalog.");
      }
      if (!standard && !has(customMotifs,id)) throw new Error("Unknown ring drawing: " + id);
    }
  }

  function guestBandArt(catalog, ids, customMotifs) {
    checkSelection(catalog,ids,customMotifs);
    const parts = [unpack(catalog.fixed[0])];
    catalog.order.forEach((slot, index) => {
      parts.push(excursion(catalog,ids[slot],slot,customMotifs));
      parts.push(unpack(catalog.fixed[index + 1]));
    });
    return join(parts);
  }

  function plan(catalog, ids, customMotifs = {}) {
    const art = guestBandArt(catalog,ids,customMotifs);
    const transit = unpack(catalog.transit);
    const segments = [transit, unpack(catalog.erase), art, transit.slice().reverse()];
    return {art, path: join(segments), segments};
  }

  function restoreGuests(scene, ids, customMotifs = {}) {
    const wide = scene.live.wideCenter;
    if (!wide) throw Error('This garden needs compatible portrait and guest layouts to restore its drawings.');
    const petals = scene.zones.center.drawings[0];
    const guests = guestBandArt(scene.live.planner,ids,customMotifs);
    const art = join([petals,unpack(wide.restoreStem),guests]);
    const segments = [wide.transit,unpack(wide.restoreClear),art,wide.transit.slice().reverse()];
    return {art, segments, path:join(segments)};
  }

  function excursion(catalog,id,place,custom,drawing) {
    return has(catalog.subjects,id) || id === catalog.openSubject ? unpack(catalog.excursions[place][id]) :
      customExcursion(custom[id],place,catalog.geometry,drawing);
  }

  function fitsPlace(path, workspace, rail) {
    const {limits, radialBounds} = workspace;
    const range = pair => Array.isArray(pair) && pair.length === 2 && pair.every(Number.isFinite) && pair[0] < pair[1];
    if (!range(limits) || !range(radialBounds)) return false;
    const tolerance = 1e-7;
    const inside = ([theta, radius]) => theta >= limits[0] - tolerance && theta <= limits[1] + tolerance &&
      radius >= radialBounds[0] - tolerance && radius <= radialBounds[1] + tolerance;
    const onRail = point => Math.abs(point[1] - rail) <= tolerance;
    // The ball interpolates theta and radius linearly. Approaching the subject
    // on its existing circular rail is the only move allowed beyond this area.
    for (let i = 1; i < path.length; i++) {
      const a = path[i-1], b = path[i];
      if (onRail(a) && onRail(b)) continue;
      if (!inside(a) || !inside(b)) return false;
    }
    return true;
  }

  function filePathsFor(downloads) {
    return downloads.map(file => file.text.trim().split('\n')
      .map(row => row.trim().split(/\s+/).map(Number)));
  }

  // Find when each patch of sand will last be disturbed by the ordinary clear.
  // Sample the player's polar interpolation. Expand the guard by half a sample,
  // both grid-cell half diagonals and half a custom drawing segment (<= .01).
  function lastClearNearArt(catalog, place, clear, recut, exit) {
    const {groove,margin} = catalog.customReveal, {center,scale,angles} = catalog.geometry;
    const cell = Math.max(groove/3,scale/80);
    const clearance = 1.65*groove + 2*margin + .00002;
    const reach = clearance/cell + 1.42 + .5 + .0051/cell;
    const side = Math.ceil(2*(scale/cell+reach+2));
    const left = center*Math.cos(angles[place])-side*cell/2;
    const bottom = center*Math.sin(angles[place])-side*cell/2;
    const touched = new Int32Array(side*side), cached = new Int32Array(side*side).fill(-1);
    function mark(path, finishing) {
      for (let i=0;i<path.length-1;i++) {
        const [a,r]=path[i], [b,s]=path[i+1];
        const steps=Math.max(1,Math.ceil((Math.abs(s-r)+Math.max(r,s)*Math.abs(b-a))/cell));
        for (let k=0;k<=steps;k++) {
          const angle=a+(b-a)*k/steps, radius=r+(s-r)*k/steps;
          const x=Math.floor((radius*Math.cos(angle)-left)/cell), y=Math.floor((radius*Math.sin(angle)-bottom)/cell);
          if (x>=0 && y>=0 && x<side && y<side) touched[y*side+x]=finishing ? clear.length+1 : i+1;
        }
      }
    }
    mark(clear,false); mark(recut,true); mark(exit,true);
    const offsets=[];
    for (let y=-Math.floor(reach);y<=reach;y++) {
      for (let x=-Math.floor(reach);x<=reach;x++) if (x*x+y*y<=reach*reach) offsets.push(y*side+x);
    }
    return (theta,radius) => {
      // Queried midpoints are in the custom drawing disc. The extra guard
      // around that disc keeps all neighborhood offsets within this array.
      const x=Math.floor((radius*Math.cos(theta)-left)/cell), y=Math.floor((radius*Math.sin(theta)-bottom)/cell);
      const index=y*side+x;
      if (cached[index]>=0) return cached[index];
      let latest=0;
      for (const offset of offsets) latest=Math.max(latest,touched[index+offset]);
      cached[index]=latest;
      return latest;
    };
  }

  // Both paths interpolate linearly in theta and radius between signed rows.
  // Ignore nearly parallel segments and crossings indistinguishable from a
  // vertex after rounding either download to five decimals.
  function interiorCross(a,b,c,d,shift) {
    const x=b[0]-a[0], y=b[1]-a[1], u=d[0]-c[0], v=d[1]-c[1];
    const det=x*v-y*u, px=c[0]+shift-a[0], py=c[1]-a[1];
    if (Math.abs(det)<.015*Math.hypot(x,y)*Math.hypot(u,v) || det===0) return null;
    const t=(px*v-py*u)/det, s=(px*y-py*x)/det;
    if (Math.min(t,1-t)*Math.hypot(x,y)<.00004 || Math.min(s,1-s)*Math.hypot(u,v)<.00004) return null;
    return [a[0]+t*x, a[1]+t*y];
  }

  function customVisit(catalog, place, drawing, approach, clear, recut, next, exit) {
    const {groove,margin}=catalog.customReveal, {angles,scale,center}=catalog.geometry;
    if (!(groove>0 && margin>=0 && 1.65*groove+2*margin < scale)) return null;
    const {first,last}=drawing, distance=travelDistances(next), wipeDistance=travelDistances(clear);
    // Ignore the hanger and rail. For dense custom shapes, sample candidate
    // entry edges by distance. The chosen excursion still uses EVERY vertex.
    const bodyLength=distance[last]-distance[first];
    if (!(bodyLength>4*groove)) return null;
    const width=Math.max(groove,scale/12), buckets=new Map();
    const key=(x,y)=>x+','+y;
    function cells(a,b,visit) {
      const x0=Math.floor(Math.min(a[0],b[0])*center/width), x1=Math.floor(Math.max(a[0],b[0])*center/width);
      const y0=Math.floor(Math.min(a[1],b[1])/width), y1=Math.floor(Math.max(a[1],b[1])/width);
      for(let x=x0;x<=x1;x++) for(let y=y0;y<=y1;y++) visit(key(x,y));
    }
    let sample=0;
    for (let j=first;j<last;j++) {
      const reached=distance[j+1]-distance[first];
      if (reached<sample || distance[j+1]-distance[j]<.00008) continue;
      sample=Math.max(sample+bodyLength/1100,reached);
      cells(next[j],next[j+1],k=>{
        if(!buckets.has(k)) buckets.set(k,[]);
        buckets.get(k).push(j);
      });
    }
    const windows=Array.from({length:12},()=>[]);
    for (let i=0;i<clear.length-1;i++) {
      const fraction=wipeDistance[i]/wipeDistance.at(-1);
      if (fraction<.10 || fraction>.78) continue;
      const a=clear[i], b=clear[i+1];
      const shift=tau*Math.round((a[0]-angles[place])/tau);
      const found=new Set();
      cells([a[0]-shift,a[1]],[b[0]-shift,b[1]],k=>{
        for (const j of buckets.get(k) || []) found.add(j);
      });
      for (const j of found) {
        const cross=interiorCross(a,b,next[j],next[j+1],shift);
        if (cross) windows[Math.min(11,Math.floor((fraction-.10)/.68*12))].push({i,j,cross,shift});
      }
    }
    if (!windows.some(w=>w.length)) return null;
    const lastTouch=lastClearNearArt(catalog,place,clear,recut,exit);
    const latest=new Int32Array(next.length).fill(-1);
    function clearAfter(edge) {
      if (latest[edge]<0) {
        const a=next[edge], b=next[edge+1];
        latest[edge]=lastTouch((a[0]+b[0])/2,(a[1]+b[1])/2);
      }
      return latest[edge];
    }
    const walkLimit=Math.min(5*scale,bodyLength*.52), guard=1.65*groove+2*margin;
    function walkPoints({j,end,cross,shift}) {
      const walk=[[cross[0]-shift,cross[1]]], dir=end>j?1:-1;
      for(let k=dir>0?j+1:j;;k+=dir) {
        walk.push(next[k]);
        if(k===end)return walk;
      }
    }
    function choose(firstVisit) {
      const opportunities=[];
      const original=firstVisit && walkPoints(firstVisit);
      const known=new Float64Array(next.length).fill(-1);
      const separation=(a,b)=>Math.hypot((a[0]-b[0])*center,a[1]-b[1]);
      function distanceToFirst(point,index) {
        if(index>=0 && known[index]>=0)return known[index];
        let gap=Infinity;
        for(const mark of original) gap=Math.min(gap,separation(point,mark));
        if(index>=0)known[index]=gap;
        return gap;
      }
      for (const candidates of windows) {
        let best=null;
        // Sample each phase separately so densely hatched artwork still gets
        // a fair comparison at later crossings.
        const step=Math.max(1,Math.ceil(candidates.length/45));
        for(let n=0;n<candidates.length;n+=step) {
          const {i,j,cross,shift}=candidates[n], fraction=wipeDistance[i]/wipeDistance.at(-1);
          if(firstVisit && (i===firstVisit.i || fraction>firstVisit.fraction+.10)) continue;
          for(const dir of [-1,1]) {
            let traveled=0,safe=0,sinceSafe=0,minT=Infinity,maxT=-Infinity,minR=Infinity,maxR=-Infinity;
            let previous=[cross[0]-shift,cross[1]], contact=null, peak=0, enclosure=0, added=0;
            if(original && distanceToFirst(previous,-1)<=2.2*groove)contact=previous;
            for(let k=dir>0?j+1:j, count=0;k>=first && k<=last && count<400;k+=dir,count++) {
              const point=next[k], amount=Math.hypot(point[1]-previous[1],(point[0]-previous[0])*(point[1]+previous[1])/2);
              traveled+=amount;
              if(traveled>walkLimit)break;
              const lasting=clearAfter(dir>0?k-1:k)<=i;
              if (lasting) {
                safe+=amount; sinceSafe=0;
                minT=Math.min(minT,point[0]);maxT=Math.max(maxT,point[0]);
                minR=Math.min(minR,point[1]);maxR=Math.max(maxR,point[1]);
              } else sinceSafe+=amount;
              previous=point;
              if (sinceSafe>1.9*guard)break;
              if(original) {
                // A second visit earns its travel by leaving and meeting the
                // first stroke at different points, completing a visible shape.
                const gap=distanceToFirst(point,k);
                if(gap<=2.2*groove) {
                  if(contact && peak>2.8*groove)enclosure=Math.max(enclosure,Math.sqrt(peak*separation(contact,point)));
                  if(!contact || peak>0) contact=point;
                  peak=0;
                } else {
                  peak=Math.max(peak,gap);
                  if(lasting)added+=amount;
                }
              }
              const span=Math.hypot((maxT-minT)*center,maxR-minR);
              if(safe<3*groove || safe<traveled*.62 || span<2*groove || sinceSafe>0)continue;
              if(original && (added<3*groove || enclosure<2.25*groove))continue;
              const score=original ? enclosure+.2*Math.min(added,scale)-.15*scale*fraction :
                Math.min(span,1.6*scale)+.35*Math.min(safe,2.5*scale)-.4*scale*fraction;
              if(!best || score>best.score)best={score,i,j,end:k,cross,shift,fraction};
            }
          }
        }
        if(best)opportunities.push(best);
      }
      // Choose an earlier row if it exposes nearly as much of the picture.
      const strongest=Math.max(0,...opportunities.map(o=>o.score));
      return opportunities.find(o=>o.score>=.83*strongest);
    }
    const firstVisit=choose(null);
    if(!firstVisit)return null;
    const secondVisit=choose(firstVisit);
    const visits=secondVisit ? [firstVisit,secondVisit].sort((a,b)=>a.i-b.i) : [firstVisit];
    const wipe=[], detours=[];
    let resume=0,cut=0;
    for(const visit of visits) {
      const walk=walkPoints(visit).map(([t,r])=>[t+visit.shift,r]);
      for(let k=resume;k<=visit.i;k++)wipe.push(clear[k]);
      wipe.push(...walk,...walk.slice(0,-1).reverse());
      resume=visit.i+1;
      cut=approach.length+wipe.length-2;
      detours.push({clearSegment:visit.i,artSegment:visit.j,end:visit.end});
    }
    for(let k=resume;k<clear.length;k++)wipe.push(clear[k]);
    const signed=files(join([approach,wipe,recut,next,exit])), customReveal=detours[0];
    if(detours[1])customReveal.second=detours[1];
    return signedProgress(signed,cut,{place,customReveal});
  }

  function signedProgress(signed,cut,details,steps) {
    const filePaths=filePathsFor(signed), path=join(filePaths);
    if (!Number.isInteger(cut) || cut <= 0 || cut >= path.length-1)
      throw Error('The guest drawing is missing its progress frame.');
    const distance=travelDistances(path), total=distance.at(-1);
    const route={...details,files:signed,filePaths,path,progressFraction:distance[cut]/total,
      segments:[[path[0]],path.slice(0,cut+1),path.slice(cut),[path.at(-1)]]};
    // Older signed drawings store only the default cut. Extra views must
    // end in the same place and appear in order along those exact files.
    if (Array.isArray(steps) && steps.length>1 && steps.at(-1)?.endIndex===cut &&
        steps.every((step,i)=>typeof step?.label==='string' && step.label.trim() &&
          Number.isInteger(step.endIndex) && step.endIndex>(i ? steps[i-1].endIndex : 0))) {
      route.progressMoments=steps.map(({label,endIndex})=>({label,endIndex,fraction:distance[endIndex]/total}));
    }
    return route;
  }

  function shortFillEntry(options, art, rail, approach, exit) {
    // The rail already connects the two gates. Keep the full engraving between
    // its first departure from the rail and its return, in its original order.
    const offRail = point => Math.abs(point[1]-rail) > 1e-7;
    const start = art.findIndex(offRail)-1, end = art.findLastIndex(offRail)+1;
    if (start < 0 || end >= art.length) return null;
    const left = art.slice(0,start+1), right = art.slice(end).reverse();
    const length = points => travelDistances(points).at(-1);
    const previousEntry = length(approach) + length(left);
    let shortest = (previousEntry + length(right) + length(exit)) / 2;
    let chosen = null;
    for (const [side, railLead] of [['left',left],['right',right]]) {
      if (!options[side]) continue;
      const entry = join([unpack(options[side]),railLead]);
      const distance = length(entry);
      // Enter no later than the through-trip. Both routes draw the same body.
      if (distance <= previousEntry + 1e-6 && distance < shortest - 1e-6) {
        shortest = distance;
        chosen = {side, entry};
      }
    }
    return chosen && {...chosen, body:art.slice(start,end+1)};
  }

  function planPlace(catalog, place, from, to, custom) {
    const workspace = catalog.places?.[place];
    if (!workspace) return null;
    const old = excursion(catalog, from, place, custom);
    const drawing = from !== catalog.openSubject && has(custom,to) && catalog.customReveal ? {} : null;
    const next = excursion(catalog, to, place, custom, drawing);
    const rail = catalog.geometry.rail;
    if (!fitsPlace(old, workspace, rail) || !fitsPlace(next, workspace, rail)) return null;

    const approach = unpack(workspace.approach);
    if (from === catalog.openSubject) {
      const exit = unpack(workspace.fillExit || workspace.exit);
      const short = workspace.shortFill && shortFillEntry(workspace.shortFill,next,rail,approach,exit);
      const body = short ? short.body : next, cut = halfIndex(travelDistances(body));
      const entry = short ? short.entry : approach, leave = short ? entry.slice().reverse() : exit;
      const segments = [entry, body.slice(0,cut+1), body.slice(cut), leave];
      return {place, fill:true, ...(short && {shortFill:short.side}), art:next, segments, path:join([entry,body,leave])};
    }
    const addition = workspace.additions?.[from]?.[to];
    if (addition && has(catalog.subjects,from) && has(catalog.subjects,to)) {
      return signedProgress(addition.files,addition.progressIndex,{place,addFrom:from});
    }
    const shared = workspace.revealTargets?.[to];
    const reveal = has(catalog.subjects,from) && has(catalog.subjects,to) && to !== catalog.openSubject &&
      (workspace.reveals?.[from]?.[to] || (Array.isArray(shared?.from) && shared.from.includes(from) && shared));
    if (reveal) {
      return signedProgress(reveal.files,reveal.progressIndex,{place,earlyFrom:from},reveal.progressMoments);
    }
    const [clear, recut, exit] = ['clear','recut','exit'].map(key => unpack(workspace[key]));
    if (drawing) {
      const early = customVisit(catalog, place, drawing, approach, clear, recut, next, exit);
      if (early) return early;
    }
    const art = join([recut, next]);
    const segments = [approach, clear, art, exit];
    return {place, art, path:join(segments), segments};
  }

  function connectedFills(candidates, trips, separateLength, places) {
    if (!candidates?.length || !trips.every(({route})=>route.fill)) return null;
    const length = path => travelDistances(path).at(-1);
    const artwork = new Map();
    let drawingLength = 0;
    let previousShortest = Infinity, previousFirst = Infinity, previousPlace = Infinity;
    for (const {route} of trips) {
      const art = route.art, distance = travelDistances(art);
      const rail = art.at(-1)[1];
      let finished = art.length-1;
      while (finished && Math.abs(art[finished-1][1]-rail) < 1e-7) finished--;
      artwork.set(route.place,{art, finished:distance[finished]});
      drawingLength += distance.at(-1);
      // A new approach can make a different guest the quickest solo drawing.
      // Retain the old first-finish limit so a small head start for one guest
      // cannot turn an established short group tour into three long round trips.
      const place = places[route.place];
      const entry = length(route.shortFill ? unpack(place.approach) : route.segments[0]);
      const exit = length(route.shortFill ? unpack(place.fillExit || place.exit) : route.segments.at(-1));
      const previousTrip = entry + distance.at(-1) + exit;
      if (previousTrip < previousShortest || (previousTrip === previousShortest && route.place < previousPlace)) {
        previousShortest = previousTrip;
        previousPlace = route.place;
        previousFirst = entry + distance[finished];
      }
    }
    // The returning ball has reached the hanging rail and the entire first
    // subject is visible. The last ride to its exit gate adds no artwork.
    const separateFirst = trips[0].route;
    const separateFinish = separateFirst.shortFill ? separateFirst.segments.slice(0,3).reduce((sum,p)=>sum+length(p),0) :
      length(separateFirst.segments[0]) + artwork.get(separateFirst.place).finished;
    const firstLimit = Math.max(separateFinish, previousFirst);
    let best, bestLength = separateLength, firstFinish = Infinity;
    for (const candidate of candidates) {
      const legs = candidate.map(({place,approach,exit})=>({
        place, approach:unpack(approach), exit:exit ? unpack(exit) : null
      }));
      const total = legs.reduce((sum,leg)=>sum+length(leg.approach)+(leg.exit ? length(leg.exit) : 0),drawingLength);
      const first = length(legs[0].approach)+artwork.get(legs[0].place).finished;
      if (first <= firstLimit+1e-6 && total < separateLength && (total < bestLength-1e-6 ||
          (Math.abs(total-bestLength) <= 1e-6 && first < firstFinish))) {
        best = legs;
        bestLength = total;
        firstFinish = first;
      }
    }
    return best?.map(({place,approach,exit})=>{
      const sections = [approach,artwork.get(place).art];
      if (exit) sections.push(exit);
      return {place,fill:true,path:join(sections)};
    });
  }

  function planChange(catalog, current, drawings, custom = {}, onlyPlaces = false) {
    checkSelection(catalog, current, custom);
    checkSelection(catalog, drawings, custom);
    const changed = drawings.map((id,i) => id === current[i] ? -1 : i).filter(i => i >= 0);
    const visits = changed.map(i => planPlace(catalog, i, current[i], drawings[i], custom));
    if (!visits.length || visits.includes(null)) {
      if (onlyPlaces) throw Error(visits.length ? 'This drawing cannot fit within its guest place.' :
        'Those drawings are already in the requested places.');
      return plan(catalog, drawings, custom);
    }
    if (visits.length === 1) return visits[0];

    const trips = visits.map(route => ({route, length:travelDistances(route.path).at(-1)}));
    const separateLength = trips.reduce((sum, trip) => sum + trip.length, 0);
    const preservesGuest = current.some((id,i) => id !== catalog.openSubject && id === drawings[i]);
    if (!onlyPlaces && !preservesGuest && !visits.some(route => route.fill || route.addFrom)) {
      const full = plan(catalog, drawings, custom);
      if (travelDistances(full.path).at(-1) < separateLength) return full;
    }
    // Separate trips complete an open place first, then the shortest replacement.
    trips.sort((a,b) => Number(!!b.route.fill) - Number(!!a.route.fill) || a.length - b.length);
    // A through-trip can sweep sand back onto a finished chin as it passes
    // the next seat. Explicit place-by-place requests use each seat's own trip.
    const tour = !onlyPlaces && connectedFills(catalog.fillTours?.[changed.join('-')], trips, separateLength, catalog.places);
    const routes = tour || trips.map(trip=>trip.route);
    const showMoments = routes.some(route=>route.addFrom || route.earlyFrom || route.customReveal);
    const downloads = [], filePaths = [], parts = [], moments = [];
    let endIndex = 0;
    for (const route of routes) {
      const signed = route.files || files(route.path);
      const part = {place:route.place, count:signed.length};
      if (route.fill) part.fill = true;
      if (route.shortFill) part.shortFill = route.shortFill;
      if (route.addFrom) part.addFrom = route.addFrom;
      if (route.earlyFrom) part.earlyFrom = route.earlyFrom;
      if (route.customReveal) part.customReveal = route.customReveal;
      parts.push(part);
      // A reveal's progress cut is local to its decoded files. Translate it
      // into the full journey, counting each shared file endpoint only once.
      if (part.addFrom || part.earlyFrom || part.customReveal) {
        moments.push({place:part.place,forming:true,endIndex:endIndex+route.segments[1].length-1});
      }
      const paths = route.filePaths || filePathsFor(signed);
      for (const [i,{text}] of signed.entries()) {
        downloads.push({name:'guest-ring-' + (downloads.length + 1) + '.thr', text});
        filePaths.push(paths[i]);
        endIndex += paths[i].length-1;
      }
      if (showMoments) moments.push({place:part.place,forming:false,endIndex});
    }
    // Consecutive files may describe the same joint one full turn apart.
    // Five-decimal rounding can also differ by one final digit at that joint.
    const path = join(filePaths, 0.000011);
    const firstEnd = filePaths.slice(0, parts[0].count).reduce((n,p) => n + p.length - 1, 0);
    const segments = [[path[0]], path.slice(0,firstEnd+1), path.slice(firstEnd), [path.at(-1)]];
    if (showMoments) {
      const distance=travelDistances(path), total=distance.at(-1);
      for (const moment of moments) moment.fraction=distance[moment.endIndex]/total;
    }
    return {parts, files:downloads, filePaths, path, segments, ...(tour && {tour:true}), ...(showMoments && {moments})};
  }

  // The photo converter returns a Cartesian walk starting on its unit rim,
  // already connected to the clothing or outline. Retain that entry point.
  function portraitStroke(points, scale, entranceAngle, entryRadius = scale, maxStep = 0.01) {
    const epsilon = scale * 1e-12;
    const result = [[entranceAngle, entryRadius]];
    const angleNear = (raw, prior) => raw + tau * Math.round((prior - raw) / tau);
    function emit(theta, radius) {
      if (result.length >= 180000) throw new Error("This portrait has too many travel points.");
      result.push([theta, radius]);
    }
    function radial(theta, from, to) {
      for (const sample of line(theta, from, theta, to).slice(1)) emit(...sample);
    }

    // Keep Cartesian lines straight through small radii. Turning the heading
    // of a diameter stroke while the radius is still positive would cut a bow.
    function segment(x0, y0, x1, y1) {
      const [prior] = result[result.length - 1];
      const a = Math.hypot(x0, y0), b = Math.hypot(x1, y1);
      if (b <= epsilon) {
        radial(prior, a, 0);
        return;
      }
      const target = angleNear(Math.atan2(y1, x1), prior);
      if (a <= epsilon) {
        for (const turn of line(prior, 0, target, 0).slice(1)) emit(...turn);
        radial(target, 0, b);
        return;
      }
      if (Math.hypot(x1 - x0, y1 - y0) > maxStep || Math.abs(target - prior) > 0.05) {
        const mx = (x0 + x1) / 2, my = (y0 + y1) / 2;
        segment(x0, y0, mx, my);
        segment(mx, my, x1, y1);
        return;
      }
      emit(target, b);
    }

    let [x0, y0] = points[0].map(x => x * scale);
    for (let i = 1; i < points.length; i++) {
      const x1 = points[i][0] * scale, y1 = points[i][1] * scale;
      const dx = x1 - x0, dy = y1 - y0;
      const squaredLength = dx * dx + dy * dy;
      const closest = squaredLength ? -(x0 * dx + y0 * dy) / squaredLength : 0;
      // A crossing can fall anywhere on a segment, including away from the
      // midpoint. Split that chord at the actual origin only to roundoff.
      if (closest > 0 && closest < 1 && Math.hypot(x0 + closest * dx, y0 + closest * dy) <= epsilon) {
        segment(x0, y0, 0, 0);
        segment(0, 0, x1, y1);
      } else {
        segment(x0, y0, x1, y1);
      }
      x0 = x1;
      y0 = y1;
    }
    return result;
  }

  function photo(centerZone, normalizedPoints) {
    const {transit, erase, photoErase} = centerZone || {};
    const isFinitePath = p => Array.isArray(p) && p.length >= 2 &&
      p.every(pt => Array.isArray(pt) && pt.length === 2 && pt.every(Number.isFinite));
    if (!isFinitePath(transit) || !isFinitePath(erase)) throw new Error("The center zone has no valid path.");
    const clear = photoErase === undefined ? erase.slice().reverse() : unpack(photoErase);
    const [gate, high] = transit[transit.length - 1];
    if (!(high > 0 && high < 1) || Math.abs(transit[0][1] - 1) > 1e-6 ||
        !transit.every(([t, r]) => Math.abs(t - gate) <= 1e-6 && r >= high && r <= 1) ||
        !clear.every(([t, r], i) => r >= 0 && r <= high + 1e-7 &&
          (i === 0 || Math.abs(clear[i - 1][0] - t) < Math.PI)) ||
        !clear.some(([, r]) => r === 0)) throw new Error("The portrait needs the garden’s center zone.");
    if (!isFinitePath(normalizedPoints) || normalizedPoints.length < 4 || normalizedPoints.length > 32000 ||
        !normalizedPoints.every(p => Math.hypot(...p) <= 1 + 1e-8)) {
      throw new Error("The photo must fit in its circle and contain 4 to 32,000 finite points.");
    }
    const first = normalizedPoints[0], last = normalizedPoints[normalizedPoints.length - 1];
    if (Math.abs(Math.hypot(...first) - 1) > 1e-6 || Math.hypot(first[0] - last[0], first[1] - last[1]) > 1e-6 ||
        !normalizedPoints.some(p => Math.hypot(...p) < 1 - 1e-6)) {
      throw new Error("The photo path must start at its rim, enter the drawing and return to the same place.");
    }

    const raw = Math.atan2(first[1], first[0]);
    const entryAngle = raw + tau * Math.round((gate - raw) / tau);
    const rim = line(gate, high, entryAngle, high);
    const stroke = portraitStroke(normalizedPoints, high, entryAngle);
    const art = join([rim, stroke, rim.slice().reverse()]);
    // The portrait erase wipes out its incoming stem. Leave by its own outline.
    const segments = [transit, clear, art, transit.slice().reverse()];
    return {art, path: join(segments), segments};
  }

  // A center print can make its picture by changing the spacing of the rake.
  // Prove coverage from its actual continuous ball path before removing the
  // usual separate erase. A sample inside a square's allowable distance from
  // its center covers the entire square, including the corners. Subdivide
  // uncertain squares. A failed proof always retains the regular center erase.
  function coversPortraitCenter(art, radiusMM, edgeMM, grooveMM) {
    const half = grooveMM / 2, step = half / 5, grid = Math.ceil(edgeMM / half) + 2;
    const width = 2 * grid + 1, bins = new Array(width * width);
    const bin = value => Math.floor(value / half) + grid;
    function put(angle, radius) {
      const x = radiusMM * radius * Math.cos(angle), y = radiusMM * radius * Math.sin(angle);
      const key = bin(y) * width + bin(x);
      (bins[key] || (bins[key] = [])).push(x, y);
    }
    put(...art[0]);
    let samples = 1;
    for (let i = 1; i < art.length; i++) {
      const [t, r] = art[i - 1], [end, last] = art[i];
      const turn = end - t, move = last - r;
      const steps = Math.max(1, Math.ceil(radiusMM * Math.hypot(move, turn * Math.max(r, last)) / step));
      samples += steps;
      if (samples > 550000) return false;
      for (let j = 1; j <= steps; j++) put(t + turn * j / steps, r + move * j / steps);
    }
    function hasSample(x, y, reach) {
      const limit = reach * reach;
      for (let row = bin(y - reach); row <= bin(y + reach); row++) {
        for (let col = bin(x - reach); col <= bin(x + reach); col++) {
          const points = bins[row * width + col];
          if (!points) continue;
          for (let i = 0; i < points.length; i += 2) {
            if ((points[i] - x) ** 2 + (points[i + 1] - y) ** 2 <= limit) return true;
          }
        }
      }
      return false;
    }
    function covered(x, y, side, depth) {
      const diagonal = Math.SQRT2 * side;
      if (Math.hypot(x, y) - diagonal > edgeMM) return true;
      // The device files round both polar coordinates to five decimals.
      // At this radius their combined positional error is less than 0.01 mm.
      if (hasSample(x, y, half - diagonal - .01)) return true;
      if (!depth) return false;
      const h = side / 2;
      return covered(x-h,y-h,h,depth-1) && covered(x+h,y-h,h,depth-1) &&
        covered(x-h,y+h,h,depth-1) && covered(x+h,y+h,h,depth-1);
    }
    const count = Math.ceil(edgeMM / half);
    for (let row = -count; row < count; row++) {
      for (let col = -count; col < count; col++) {
        if (!covered((col + .5) * half, (row + .5) * half, half / 2, 5)) return false;
      }
    }
    return true;
  }

  function preparedPhoto(centerZone, points, geometry, includesCenterRake) {
    const regular = photo(centerZone, points);
    if (!includesCenterRake) return regular;
    const radius = geometry?.radiusMM, groove = radius * geometry?.groove;
    const edge = radius * centerZone.transit.at(-1)[1];
    // This proof and its phone timing have been exercised on the wide garden.
    if (Math.abs(radius-420) > .001 || Math.abs(groove-7) > .001 ||
        Math.abs(edge-316.4) > .01 || ![radius,groove,edge].every(Number.isFinite) ||
        !coversPortraitCenter(regular.art,radius,edge,groove)) return regular;
    const split = splitTravel(centerZone.transit, regular.art);
    return {art:regular.art, path:split.path, segments:split.segments, interleaved:true,
      includesCenterRake:true, halfwayFraction:split.halfwayFraction};
  }

  function reviewedMixer(center, geometry) {
    const {joinAt,clearThrough,outline}=center.standMixer;
    const edge=center.transit.at(-1)[1];
    const spiral=unpack(center.photoErase).map(([angle,radius])=>{
      const r=Math.min(1,radius/edge);
      return [r*Math.cos(angle),r*Math.sin(angle)].map(v=>Number(v.toFixed(9)));
    });
    spiral[0]=spiral[spiral.length-1]=[0,-1];
    // Clear beyond the whisk and base, retrace the fresh grooves to the outline,
    // then return the same way before the outward spiral resumes.
    const back=spiral.slice(joinAt,clearThrough).reverse();
    const points=spiral.slice(0,clearThrough+1).concat(back,outline,back.slice().reverse(),spiral.slice(clearThrough));
    const route=preparedPhoto(center,points,geometry,true);
    if (!route.includesCenterRake) throw Error('This drawing needs the fitted wide-center spiral.');
    route.centerMode='widePortrait';
    return route;
  }

  function guestInCenter(centerZone, shape, rotation, groove) {
    checkCustomShape(shape);
    const radius = centerZone.transit.at(-1)[1];
    const points = shape.slice(0,-1);
    const farthest = points.reduce((best,p,i) => Math.hypot(...p) > Math.hypot(...points[best]) ? i : best, 0);
    const reach = Math.hypot(...points[farthest]);
    // Keep the guest's orientation and the full connected outline. Leave two
    // grooves around it. The short entrance only touches the outermost point.
    const scale = (1 - 2*groove/radius)/reach;
    if (!(scale > 0)) throw Error('This center is too small for the guest drawing.');
    const c=Math.cos(rotation), s=Math.sin(rotation);
    const ordered = points.slice(farthest).concat(points.slice(0,farthest+1));
    const ink = ordered.map(([x,y]) => [scale*(c*x-s*y),scale*(s*x+c*y)]);
    const entry = ink[0].map(v => v/Math.hypot(...ink[0]));
    return photo(centerZone,[entry,...ink,entry]);
  }

  // Register an excursion on the *actual* outward erase at its outermost
  // point's heading. The next lap must already clear the whole drawn mark.
  function shadowSweep(zone) {
    const {transit, erase, photoErase} = zone || {};
    const finite = path => Array.isArray(path) && path.length >= 2 &&
      path.every(p => Array.isArray(p) && p.length === 2 && p.every(Number.isFinite));
    if (!finite(transit) || !finite(erase)) throw Error('The center has no calibrated erase.');
    const clear = photoErase === undefined ? erase.slice().reverse() : unpack(photoErase);
    const [gate, high] = transit.at(-1);
    const center = clear.findLastIndex(p => p[1] === 0);
    const rim = clear.findIndex((p, i) => i > center && Math.abs(p[1] - high) < 1e-7);
    const nearGate = t => Math.abs(t - gate - tau * Math.round((t - gate) / tau)) < 1e-6;
    if (!finite(clear) || !(high > 0 && high < 1) || center < 1 || rim < center + 2 ||
        Math.abs(transit[0][1] - 1) > 1e-6 ||
        !transit.every(([t,r]) => Math.abs(t - gate) < 1e-6 && r >= high && r <= 1) ||
        !clear.slice(0, center + 1).every(([t]) => nearGate(t)) || !nearGate(clear.at(-1)[0]) ||
        !clear.slice(rim).every(p => Math.abs(p[1] - high) < 1e-7)) {
      throw Error('Photo shadows need a center with a continuous outward erase.');
    }
    const direction = Math.sign(clear[rim][0] - clear[center][0]);
    if (!direction || !clear.every(([t,r], i) => r >= 0 && r <= high + 1e-7 &&
        (!i || Math.abs(t - clear[i-1][0]) < Math.PI) &&
        (i <= center || i > rim || (r >= clear[i-1][1] && direction * (t - clear[i-1][0]) > 0)))) {
      throw Error('Photo shadows need a center with a continuous outward erase.');
    }

    function lowerBound(value, axis, sign) {
      let lo = center, hi = rim;
      while (lo < hi) {
        const mid = (lo + hi) >>> 1;
        if (sign * clear[mid][axis] < value) lo = mid + 1;
        else hi = mid;
      }
      return lo;
    }
    function atAngle(angle) {
      if (direction*(angle-clear[center][0]) <= 0 || direction*(angle-clear[rim][0]) > 0) return null;
      const index = lowerBound(direction * angle, 0, direction);
      const [t0,r0] = clear[index-1], [t1,r1] = clear[index];
      const radius = r0 + (r1-r0) * (angle-t0) / (t1-t0);
      return {index, angle, radius};
    }
    function anchor(raw, minimum) {
      if (minimum >= high) return null;
      const j = lowerBound(minimum, 1, 1), a = clear[j-1], b = clear[j];
      const start = a[0] + (b[0] - a[0]) * (minimum - a[1]) / (b[1] - a[1]);
      return atAngle(raw + direction * tau * Math.ceil(direction * (start - raw) / tau));
    }
    return {transit, clear, anchor, atAngle, high, direction};
  }

  // Visit the part of each portrait behind one turn of the outward erase.
  // Enter and leave at actual crossings of the final portrait with that
  // turn. Returning along the spiral leaves no access line across a face.
  function seatedPhoto(zone, result, geometry) {
    const ordinary = photo(zone, result.points);
    const seats = result.seatFaces, groove = geometry?.groove;
    if (!zone.photoErase || !Array.isArray(seats) || seats.length < 2 || !(groove > 0)) return ordinary;
    const sweep = shadowSweep(zone), {clear, high, direction} = sweep;
    const events = [];
    for (const seat of seats) {
      const brow = Math.hypot(...seat.brow), chin = Math.hypot(...seat.chin);
      // Pick a turn between the brows and chin. Stop short of the shoulders
      // so the subjects can be seen while there is still a garden to clear.
      const depth = high*Math.min(.76, Math.max(.60, brow + .60*(chin-brow)));
      if (depth < high*brow + groove) return ordinary;
      const lap = sweep.anchor(seat.seatAngle, depth);
      if (!lap || !sweep.atAngle(lap.angle-Math.PI) || !sweep.atAngle(lap.angle+Math.PI)) return ordinary;
      const points = result.points.slice(seat.inkStart, seat.inkEnd+1);
      const start = Math.atan2(points[0][1], points[0][0]);
      const angle = start + tau*Math.round((lap.angle-start)/tau);
      const ink = portraitStroke(points, high, angle, high*Math.hypot(...points[0]));
      const gap = p => p[1] - sweep.atAngle(p[0]).radius;
      // Both ends of the closed portrait walk are at its outward shoulder.
      if (gap(ink[0]) <= 0) return ordinary;
      let begin = null, count = events.length, previous = gap(ink[0]);
      for (let i=1; i<ink.length; i++) {
        const current = gap(ink[i]);
        if ((current < 0) !== (previous < 0)) {
          // The erase is piecewise linear in polar coordinates. Its angle
          // samples and the portrait's need not fall at the same vertices.
          const a=ink[i-1], b=ink[i];
          let lo=0, hi=1;
          for (let j=0; j<24; j++) {
            const mid=(lo+hi)/2;
            const p=[a[0]+mid*(b[0]-a[0]), a[1]+mid*(b[1]-a[1])];
            if ((gap(p)<0) === (previous<0)) lo=mid;
            else hi=mid;
          }
          const crossing=sweep.atAngle(a[0]+(lo+hi)/2*(b[0]-a[0]));
          if (current<0) begin={crossing,i};
          else if (begin) {
            const part=ink.slice(begin.i,i);
            if (part.some(p=>p[1] < depth-2*groove)) {
              let early=begin.crossing, late=crossing;
              if (direction*(early.angle-late.angle)>0) {
                [early,late]=[late,early];
              } else part.reverse();
              events.push({early,late,part});
            }
            begin=null;
          }
        }
        previous=current;
      }
      if (events.length===count || begin) return ordinary;
    }
    events.sort((a,b)=>direction*(a.late.angle-b.late.angle));
    const sections=[];
    let next=0;
    for (const {early,late,part} of events) {
      sections.push(clear.slice(next,late.index), [[late.angle,late.radius]], part,
        [[early.angle,early.radius]], clear.slice(early.index,late.index), [[late.angle,late.radius]]);
      next=late.index;
    }
    sections.push(clear.slice(next));
    const body=join([sections.flat(),ordinary.art]);
    if (body.length + 2*(sweep.transit.length-1) > 24*(fileLimit-1)+1) return ordinary;
    const {path,segments,halfwayFraction}=splitTravel(sweep.transit,body);
    return {path,segments,interleaved:true,seatedReveal:true,halfwayFraction};
  }

  // Spatially index the short access lines along with the artwork. With samples
  // at most step apart, adding step to the exclusion distance bounds the true
  // gap between any two straight segments, including their unsampled interiors.
  function separatedShadows(marks, sweep, radiusMM, groove, faces) {
    const step = .14 * groove, exclusion = (1.23 * groove) + step;
    const guard = 1.23 * groove, grid = new Map(), accepted = [];
    let sampleCount = 0;
    function length(points) {
      let total = 0;
      for (let i = 1; i < points.length; i++) {
        total += Math.hypot(points[i][0]-points[i-1][0], points[i][1]-points[i-1][1]);
      }
      return total;
    }
    function sample(points) {
      const result = [points[0]];
      for (let i = 1; i < points.length; i++) {
        const a = points[i - 1], b = points[i];
        const n = Math.max(1, Math.ceil(Math.hypot(b[0]-a[0], b[1]-a[1]) / step));
        sampleCount += n;
        if (sampleCount > 1000000) throw Error('This photograph has too many shadow lines.');
        for (let j = 1; j <= n; j++) {
          result.push([a[0] + (b[0]-a[0])*j/n, a[1] + (b[1]-a[1])*j/n]);
        }
      }
      return result;
    }
    const essential = kind => ['head', 'eye', 'glasses', 'smile'].includes(kind);
    const distinguishing = kind => ['hairline', 'brow', 'nose', 'bridge', 'shade'].includes(kind);
    function reserve(cloud, source) {
      const {kind, owner} = marks[source];
      for (const [x,y] of cloud) {
        const key = Math.floor(x/exclusion) + ',' + Math.floor(y/exclusion);
        if (!grid.has(key)) grid.set(key, []);
        grid.get(key).push([x,y,kind,owner,source]);
      }
    }
    function fits(cloud, points, source) {
      const {kind, owner} = marks[source];
      // The traced hairline ends at the head, and the spectacles' bridge at
      // the lenses. Permit contact only close to those actual endpoints.
      const joins = kind === 'hairline' ? 'head' : kind === 'bridge' ? 'glasses' : '';
      for (const [x,y] of cloud) {
        const ix = Math.floor(x/exclusion), iy = Math.floor(y/exclusion);
        for (let dx=-1; dx<=1; dx++) for (let dy=-1; dy<=1; dy++) {
          const cell = grid.get((ix+dx) + ',' + (iy+dy));
          if (!cell) continue;
          for (const other of cell) {
            if (source === other[4] || (x-other[0])**2 + (y-other[1])**2 >= exclusion**2) continue;
            if (joins && owner === other[3] && other[2] === joins && [points[0], points.at(-1)].some(p =>
              Math.hypot(x-p[0],y-p[1]) < 2.2*groove)) continue;
            return false;
          }
        }
      }
      return true;
    }
    function tryMark(points, closed, kind, source) {
      let outer = 0, radius = 0;
      for (let i = 0; i < points.length; i++) {
        const r = Math.hypot(...points[i]);
        if (r > radius) { outer = i; radius = r; }
      }
      if (!radius || radius + guard >= sweep.high) return false;
      const outline = sample(closed ? points.concat([points[0]]) : points);
      if (!fits(outline, points, source)) return false;
      function entrance(vertex, sideways) {
        const p = points[vertex], r = Math.hypot(...p);
        // Keep the registration turn outside the ENTIRE mark even if the
        // chosen entry is slightly inside its outermost vertex.
        const heading = Math.atan2(p[1], p[0]) + sideways / (radius + guard);
        const anchor = sweep.anchor(heading, radius + guard);
        if (!anchor || !r) return null;
        const entry = sideways ? [Math.cos(heading)*anchor.radius, Math.sin(heading)*anchor.radius] :
          p.map(x => x * anchor.radius / r);
        return {anchor, entry, vertex, distance:Math.hypot(entry[0]-p[0], entry[1]-p[1])};
      }
      let via = entrance(outer, 0);
      let connector = via && sample([via.entry, points[outer]]);
      if (!connector || !fits(connector, points, source)) {
        if (!['eye','glasses','smile'].includes(kind) && !marks[source].facialHair && !(faces && kind === 'head')) return false;
        // A lens or an eye near the silhouette may have ample room, but its
        // shortest radial entry could cut through the head. Try only short
        // links to real vertices of the same feature, shortest first.
        const alternatives = [];
        for (let i = 0; i < points.length; i++) {
          if (radius - Math.hypot(...points[i]) > 2.3*groove) continue;
          for (const offset of [0,-.5,.5,-1,1,-1.5,1.5]) {
            const option = entrance(i, offset * groove);
            if (option && option.distance <= 3.5*groove) alternatives.push(option);
          }
        }
        via = null;
        for (const option of alternatives.sort((a,b) => a.distance-b.distance)) {
          const p = points[option.vertex], trial = sample([option.entry, p]);
          if (!fits(trial, points, source)) continue;
          // Outside the join itself the entrance must also clear this
          // feature's own edges; a shortcut across a lens would mark its glass.
          if (trial.some(q => Math.hypot(q[0]-p[0],q[1]-p[1]) > 1.6*groove &&
              outline.some(v => (q[0]-v[0])**2 + (q[1]-v[1])**2 < exclusion**2))) continue;
          via = option; connector = trial;
          break;
        }
        if (!via) return false;
      }
      const {anchor, entry, vertex} = via;
      if (!faces || !essential(kind)) reserve(outline, source);
      reserve(connector, source);
      // Walk an open mark to each end and back on its own groove.
      const walk = closed ? points.slice(vertex).concat(points.slice(0,vertex+1)) :
        points.slice(0,vertex+1).reverse().concat(points.slice(1), points.slice(vertex,-1).reverse());
      accepted.push({anchor, walk:[entry, ...walk, entry], source, kind, radius, access:via.distance});
      return true;
    }
    const prepared = marks.map((mark, source) => {
      if (!mark || typeof mark.kind !== 'string' || typeof mark.closed !== 'boolean' ||
          !Array.isArray(mark.points) || mark.points.length < 2 || mark.points.length > 32000 ||
          !mark.points.every(p => Array.isArray(p) && p.length === 2 && p.every(Number.isFinite))) {
        throw Error('The photograph contained an invalid shadow line.');
      }
      const points = mark.points.map(([x,y]) => [x/radiusMM,y/radiusMM]);
      if (mark.closed && Math.hypot(points[0][0]-points.at(-1)[0],points[0][1]-points.at(-1)[1]) < 1e-9) points.pop();
      return {mark, points, source};
    });
    function place({mark, points, source}) {
      if (points.length < (mark.closed ? 3 : 2)) return false;
      const minimumLength = (mark.chinStrand ? 1.45 : 2.4) * groove;
      if (mark.kind === 'shade' && length(points) < minimumLength) return false;
      if (tryMark(points, mark.closed, mark.kind, source)) return true;
      if (mark.closed || !['shade','brow'].includes(mark.kind)) return false;
      // An access line or one end of a shading stroke may approach a feature.
      // Try a modest trim at either end without relocating photographic detail.
      // A short observed hair can have just one usable entrance. Keep the
      // number of trials bounded for high-resolution photographs.
      const trials=Math.min(32,points.length-2);
      const cuts=mark.chinStrand ? Array.from({length:trials},(_,i)=>Math.round((i+1)*(points.length-2)/trials)) :
        [.12,.25,.40].map(fraction=>Math.ceil(points.length*fraction));
      for (const cut of cuts) {
        if (points.length - cut < 2) continue;
        if ([0,cut,Math.floor(cut/2)].some(offset => {
          const part = points.slice(offset, points.length-cut+offset);
          return length(part) >= minimumLength && tryMark(part, false, mark.kind, source);
        })) return true;
      }
      return false;
    }
    function hasFace(lines) {
      return lines.some(m => m.kind === 'head') && lines.some(m => m.kind === 'smile') &&
        lines.filter(m => m.kind === 'eye' || m.kind === 'glasses').length >= 2;
    }
    if (faces) {
      const enoughSpace = () => Error('There is too little space between the photo shadows to preserve every selected face.');
      const required = prepared.filter(item => essential(item.mark.kind));
      // Reserve all faces before choosing anyone's connector. A valid route
      // to one cheek must never cut through another person's future eye.
      for (const {mark, points, source} of required) {
        if (points.length < (mark.closed ? 3 : 2)) throw enoughSpace();
        const outline = sample(mark.closed ? points.concat([points[0]]) : points);
        if (!fits(outline, points, source)) throw enoughSpace();
        reserve(outline, source);
      }
      for (const item of required) if (!place(item)) throw enoughSpace();
      const used = new Set();
      for (const owner of faces) {
        if (!hasFace(accepted.filter(m => marks[m.source].owner === owner))) throw enoughSpace();
        // Give each person first choice of one independent photographed detail,
        // before allowing the rest of a neighbor's shading to occupy the sand.
        const detail = prepared.find(item => item.mark.owner === owner && distinguishing(item.mark.kind) && place(item));
        if (!detail) throw enoughSpace();
        used.add(detail.source);
      }
      for (const item of prepared) {
        if (!essential(item.mark.kind) && !used.has(item.source)) place(item);
      }
    } else {
      for (const item of prepared) place(item);
      // In a long-haired portrait the outside of the hair is open and the
      // closed hairline also draws the jaw. Losing it would erase the face.
      const jaw=marks.findIndex(m=>m.kind==='hairline' && m.closed);
      const missingJaw=jaw>=0 && marks.some(m=>m.kind==='head' && !m.closed) &&
        !accepted.some(m=>m.source===jaw);
      const cannotKeepFace=missingJaw || !hasFace(accepted) || !accepted.some(m => m.kind === 'shade');
      const missingBridge=marks.some(m=>m.kind==='bridge') && !accepted.some(m=>m.kind==='bridge');
      const paired=marks.findIndex(m=>m.noseBase);
      if(paired>=0 && (cannotKeepFace || missingBridge ||
          ![paired,paired+1].every(i=>accepted.some(m=>m.source===i)))){
        // Both photographed openings need their own entrance. If one fails,
        // restore the original line and keep the caller's later source indices.
        const plain=marks.slice();
        plain.splice(paired,2,{...marks[paired],points:marks[paired].noseBase,noseBase:undefined});
        const retry=separatedShadows(plain,sweep,radiusMM,groove,faces);
        return retry.map(m=>m.source>paired ? {...m,source:m.source+1} : m);
      }
      if((cannotKeepFace || missingBridge) && marks.some(m=>m.opening)){
        const plain=marks.map(m=>m.opening ? {...m,points:m.opening,opening:undefined} : m);
        return separatedShadows(plain,sweep,radiusMM,groove,faces);
      }
      if((cannotKeepFace || missingBridge) && marks.some(m=>m.rim)){
        // A hinge can leave too little room for the other lens or bridge.
        // Retry the same photographed frames without the side extensions.
        const plain=marks.map(m=>m.rim ? {...m,points:m.rim,rim:undefined} : m);
        return separatedShadows(plain,sweep,radiusMM,groove,faces);
      }
      if (cannotKeepFace) {
        if(marks.some(mark=>mark.lids)){
          const plain=marks.map(mark=>mark.lids ? {...mark,points:mark.lids,lids:undefined} : mark);
          return separatedShadows(plain,sweep,radiusMM,groove,faces);
        }
        throw Error('There is too little space between the photo shadows to preserve this face.');
      }
    }
    return accepted.sort((a,b) => sweep.direction * (a.anchor.angle - b.anchor.angle));
  }

  function shadowPhoto(centerZone, marks, geometry, options) {
    const {radiusMM, groove} = geometry || {};
    if (!(Number.isFinite(radiusMM) && radiusMM > 0 && Number.isFinite(groove) && groove > 0) ||
        !Array.isArray(marks) || !marks.length || marks.length > 600) {
      throw Error('Photo shadows need measured table dimensions and face lines.');
    }
    const faces = options?.faces;
    if (options !== undefined || marks.some(mark => mark && has(mark, 'owner'))) {
      if (!Array.isArray(faces) || !faces.length || !faces.every(f => Number.isSafeInteger(f) && f >= 0) ||
          new Set(faces).size !== faces.length || !marks.every(mark => mark && faces.includes(mark.owner))) {
        throw Error('The shadow lines must belong to the selected people.');
      }
    }
    const sweep = shadowSweep(centerZone);
    const events = separatedShadows(marks, sweep, radiusMM, groove, faces);
    const body = [], progress = [];
    let shift = 0, next = 0;
    function appendSweep(end) {
      while (next < end) {
        const [t,r] = sweep.clear[next++];
        body.push([t+shift,r]);
      }
    }
    for (const event of events) {
      const {index,angle,radius} = event.anchor;
      appendSweep(index);
      const section = portraitStroke(event.walk, 1, angle+shift, radius, Math.min(.01, groove*.3));
      const first = sweep.transit.length - 1 + body.length;
      for (const p of section) body.push(p);
      shift = tau * Math.round((body.at(-1)[0] - angle) / tau);
      progress.push({source:event.source, kind:event.kind, first, last:first+section.length-1,
                     outerRadiusMM:event.radius*radiusMM, anchorRadiusMM:radius*radiusMM, accessMM:event.access*radiusMM});
      if (faces) progress.at(-1).owner = marks[event.source].owner;
      const totalPoints = 2*(sweep.transit.length-1) + body.length + sweep.clear.length - next;
      if (totalPoints > 24*(fileLimit-1)+1) throw Error('This shadow portrait is too long for the table.');
    }
    appendSweep(sweep.clear.length);
    const {path,segments,distance,halfwayFraction} = splitTravel(sweep.transit,body);
    const total = distance.at(-1);
    for (const m of progress) {
      m.startFraction = distance[m.first]/total;
      m.endFraction = distance[m.last]/total;
    }
    return {interleaved:true, path, segments, art:body, marks:progress, distanceMM:total*radiusMM,
            halfwayFraction};
  }

  function travelDistances(path) {
    const distance = new Float64Array(path.length);
    for (let i=1; i<path.length; i++) {
      const [t,r]=path[i], [a,b]=path[i-1];
      distance[i]=distance[i-1]+Math.hypot(r-b,(t-a)*(r+b)/2);
    }
    return distance;
  }

  function halfIndex(distance) {
    const total=distance.at(-1), half=total/2, upper=distance.findIndex(d=>d>=half);
    return upper > 0 && half-distance[upper-1] < distance[upper]-half ? upper-1 : upper;
  }

  function splitTravel(transit,body,useFileCoordinates=false) {
    const exit = transit.slice().reverse(), path = join([transit,body,exit]);
    // Rounding can change the number of samples on a tightly spaced rake.
    // Reproduce the released file's coordinates in its preview and halfway point.
    const drawn = useFileCoordinates ? path.map(point => point.map(v => Number(v.toFixed(5)))) : path;
    const distance = travelDistances(drawn), total = distance.at(-1), index = halfIndex(distance);
    const entry=transit.length-1, cut=index-entry, departure=entry+body.length-1;
    return {path,distance,cut,halfwayFraction:distance[index]/total,
      segments:useFileCoordinates ? [drawn.slice(0,entry+1),drawn.slice(entry,index+1),drawn.slice(index,departure+1),drawn.slice(departure)]
        : [transit,body.slice(0,cut+1),body.slice(cut),exit]};
  }

  function borderReveal(zone,design) {
    const reveal=zone.reveal[design], body=unpack(reveal.path);
    const {path,segments,cut,distance,halfwayFraction}=splitTravel(zone.transit,body,true);
    const entry=zone.transit.length-1, endIndex=entry+reveal.finished[0];
    return {interleaved:true,path,segments,halfwayFraction,halfwayFinished:reveal.finished.filter(last=>last<=cut).length,
      ornaments:reveal.finished.length,halfwayIndex:entry+cut,firstOrnament:{endIndex,fraction:distance[endIndex]/distance.at(-1)}};
  }

  function files(path, prefix = "guest-ring") {
    if (!Array.isArray(path) || path.length < 2 ||
        !path.every(p => Array.isArray(p) && p.length === 2 && p.every(Number.isFinite) && p[1] >= 0 && p[1] <= 1)) {
      throw new Error("Cannot export an invalid ring path.");
    }
    const result = [];
    for (let i = 0; i < path.length - 1; i += fileLimit - 1) {
      const chunk = path.slice(i, i + fileLimit);
      const rows = chunk.map(([theta, radius]) => theta.toFixed(5) + " " + radius.toFixed(5));
      result.push({name: prefix + "-" + (result.length + 1) + ".thr", text: rows.join("\n") + "\n"});
    }
    return result;
  }

  return {plan, planChange, restoreGuests, checkCustomShape, fitsGuestTravel, pair, photo, preparedPhoto, guestInCenter, seatedPhoto, shadowPhoto, borderReveal,
    travelDistances, halfIndex, join, unpack, files, portraitStroke, reviewedMixer};
})();
if (typeof globalThis === "object") globalThis.OasisRingPlanner = OasisRingPlanner;
if (typeof module !== "undefined" && module.exports) module.exports = OasisRingPlanner;
