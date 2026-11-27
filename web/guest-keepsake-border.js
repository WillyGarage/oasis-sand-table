/* Draw the current three guest subjects as upright keepsakes on a laurel garland. */
const GuestKeepsakeBorder = (() => {
  const tau = 2 * Math.PI;

  function line(a, r, b, s) {
    const steps = Math.max(1, Math.ceil(Math.abs(b-a)/.04), Math.ceil(Math.abs(s-r)/.012));
    return Array.from({length:steps+1}, (_, i) => [a+(b-a)*i/steps, r+(s-r)*i/steps]);
  }

  function fit(shape, angle, inner, outer, maxWidth) {
    if (!Array.isArray(shape) || shape.length < 4 || shape.length > 8000 ||
        !shape.every(p => Array.isArray(p) && p.length === 2 && p.every(Number.isFinite) &&
          Math.hypot(...p) <= 1 + 1e-8) ||
        Math.hypot(shape[0][0]-shape.at(-1)[0], shape[0][1]-shape.at(-1)[1]) > 1e-6) {
      throw Error('A guest border needs closed drawings that fit in their guest places.');
    }
    const points = shape.slice(0, -1);
    const xs = points.map(p => p[0]), ys = points.map(p => p[1]);
    const xmin = Math.min(...xs), xmax = Math.max(...xs), ymax = Math.max(...ys);
    if (Math.max(xmax-xmin, ymax-Math.min(...ys)) <= 1e-6) throw Error('The guest drawing has no visible stroke.');
    const mid = (xmin+xmax)/2, squared = outer*outer-inner*inner;
    let scale = xmax > xmin ? maxWidth/(xmax-xmin) : Infinity;
    for (const [x,y] of points) {
      const dx = x-mid, d = ymax-y;
      // Largest uniform scale whose innermost tangent plane is at 'inner'
      // and whose furthest vertex is no further out than 'outer'.
      const divisor = Math.hypot(inner*d, Math.hypot(dx,d)*Math.sqrt(squared)) + inner*d;
      if (divisor > 0) scale = Math.min(scale, squared/divisor);
    }
    let radial = Infinity;
    for (const [x,y] of points) {
      const tangent = (x-mid)*scale;
      radial = Math.min(radial, Math.sqrt(outer*outer-tangent*tangent)+scale*y);
    }
    function polar(x, y) {
      const tangent = scale*(x-mid), outward = radial-scale*y;
      return [angle+Math.atan2(tangent,outward), Math.hypot(tangent,outward)];
    }
    // The hanger meets the first outermost vertex. For a symmetric drawing,
    // retain the same starting side despite floating point roundoff.
    const entryVertex = points.findIndex(([x,y]) => polar(x,y)[1] >= outer-1e-9);
    if (entryVertex < 0) throw Error('Could not attach the guest drawing to the border.');
    const path = [polar(...points[entryVertex])];
    for (let i=0; i<points.length; i++) {
      const a = points[(entryVertex+i)%points.length], b = points[(entryVertex+i+1)%points.length];
      const dx = b[0]-a[0], dy = b[1]-a[1];
      const steps = Math.max(1, Math.ceil(scale*Math.hypot(dx,dy)/.01));
      if (path.length + steps > 32000) throw Error('This guest drawing is too detailed for the border. Choose a simpler outline.');
      for (let j=1; j<=steps; j++) path.push(polar(a[0]+dx*j/steps, a[1]+dy*j/steps));
    }
    const c = Math.cos(angle), s = Math.sin(angle);
    return {angle, scale, center:[radial*c+scale*mid*s, radial*s-scale*mid*c], entryVertex, path};
  }

  // A shallow hanging stem leaves the outside groove and returns to it
  // before each artwork. Open leaves grow from their own stem, each drawn
  // in one loop; a gap at the six-o'clock spoke gives future changes access.
  function garland(start, end, low, high) {
    const width = high-low, span = end-start;
    const stem = u => high - .50*width*Math.sin(Math.PI*u)**2;
    const path = [[start, high]];
    let from = 0;
    function follow(to) {
      const count = Math.max(1, Math.ceil((to-from)*span/.025));
      for (let i=1; i<=count; i++) {
        const u = from+(to-from)*i/count;
        path.push([start+span*u,stem(u)]);
      }
      from = to;
    }
    function leaf(root, outward) {
      follow(root);
      const sweep = Math.min(.16, .17*span), lift = .32*width*(outward ? 1 : -1);
      function edge(t, side) {
        const angle = start+span*root+sweep*t;
        const spine = stem(root+sweep*t/span);
        return [angle, spine+lift*(Math.sin(t*Math.PI/2)+side*.32*Math.sin(t*Math.PI))];
      }
      for (let i=1;i<=20;i++) path.push(edge(i/20,1));
      for (let i=19;i>=0;i--) path.push(edge(i/20,-1));
    }
    if (span > 1.1) {
      leaf(.16,false); leaf(.43,true); leaf(.69,false);
    } else if (span > .3) {
      leaf(.42,true);
    }
    follow(1);
    return path;
  }

  function guestSector({left,right,slot,angle}, {high,inner,outer,width}, outline) {
    if (outline === null) return {slot, left, right, art:line(left,high,right,high)};
    const piece = fit(outline,angle,inner,outer,1.45*width);
    const {path:stroke,...placement} = piece, [attach,radius] = stroke[0];
    const rail = line(left,high,attach,high), hanger = line(attach,high,attach,radius);
    placement.first = rail.length + hanger.length - 2;
    placement.last = placement.first + stroke.length - 1;
    const art = globalThis.OasisRingPlanner.join([rail,hanger,stroke,hanger.slice().reverse(),line(attach,high,right,high)]);
    return {slot, left, right, art, placement};
  }

  function wrap(angle) {
    return Math.atan2(Math.sin(angle),Math.cos(angle));
  }

  function checkBrushes(brushes, sectors) {
    if (!Array.isArray(brushes) || brushes.length !== sectors.length ||
        !sectors.every(({slot,left,right},i) => {
          const b = brushes[i];
          return b && b.slot === slot && Math.abs(left-b.left) < 1e-6 && Math.abs(right-b.right) < 1e-6;
        })) throw Error('This garden needs matching border sections to change one guest at a time.');
  }

  function progressive(brushes, sectors, transit, spoke) {
    const planner = globalThis.OasisRingPlanner, [gate,high] = transit.at(-1);
    checkBrushes(brushes,sectors);
    let first = -1, nearest = Infinity;
    sectors.forEach((s,i) => {
      const distance = Math.abs(wrap(s.left-gate));
      if (s.placement && distance < nearest) { first=i; nearest=distance; }
    });
    const entry = sectors[first].left;
    const body = [line(gate,high,gate+wrap(entry-gate),high)];
    const placements = Array(3).fill(null), moments = [], sectorSteps = [];
    let row = transit.length + body[0].length - 2, last = entry;
    for (let n=0; n<sectors.length; n++) {
      const index = (first+n)%sectors.length, s = sectors[index];
      // The same measured fluted brush as the stock border. Each sweep
      // finishes at its outer-left corner. The guest art then moves to
      // the outer-right corner, ready to start the adjoining brush.
      const clear = planner.unpack(brushes[index].clear);
      const start = row, clearEnd = row+clear.length-1;
      body.push(clear,s.art);
      if (s.placement) {
        const p = {...s.placement,first:clearEnd+s.placement.first,last:clearEnd+s.placement.last};
        placements[s.slot] = p;
        moments.push({place:s.slot,endIndex:p.last});
      }
      row = clearEnd+s.art.length-1;
      sectorSteps.push({sector:index,start,clearEnd,end:row});
      last = s.right;
    }
    body.push(line(last,high,last+wrap(gate-last),high),spoke,spoke.slice().reverse());
    const path = planner.join([transit,...body,transit.slice().reverse()]);
    const distance = planner.travelDistances(path), total = distance.at(-1);
    const halfwayIndex = planner.halfIndex(distance);
    for (const moment of moments) moment.fraction = distance[moment.endIndex]/total;
    const exitAt = path.length-transit.length;
    const segments = [transit,path.slice(transit.length-1,halfwayIndex+1),path.slice(halfwayIndex,exitAt+1),transit.slice().reverse()];
    return {path,segments,placements,moments,sectorSteps,interleaved:true,halfwayIndex,
            halfwayFraction:distance[halfwayIndex]/total,
            halfwayFinished:moments.filter(m=>m.endIndex<=halfwayIndex).length,ornaments:moments.length};
  }

  function borderLayout(scene) {
    const zone = scene?.zones?.outer, live = scene?.live, angles = live?.planner?.geometry?.angles;
    if (!zone?.transit?.length || !zone.erase?.length || !Array.isArray(angles) || angles.length !== 3 ||
        !angles.every(Number.isFinite)) {
      throw Error('Open a three-place dinner garden to make a guest border.');
    }
    const transit = zone.transit, erase = zone.erase;
    const [gate, high] = transit.at(-1);
    const low = erase.reduce((r,p) => Math.min(r,p[1]), high);
    const width = high-low, g = live.groove, inner = low+.6*g, outer = high-1.8*g;
    if (!(low > 0 && high <= 1 && g > 0 && outer > inner && inner > 0)) {
      throw Error('The measured border is too narrow for the guest drawings.');
    }
    const reserve = Math.atan2(.725*width,inner) + 1.8*g/inner;
    const stations = angles.map((original,slot) => {
      const angle = gate+((original-gate)%tau+tau)%tau;
      return {angle,slot};
    }).sort((a,b) => a.angle-b.angle);

    const sectors = [];
    let previous = gate;
    for (const {angle,slot} of stations) {
      const left = angle-reserve, right = angle+reserve;
      if (left <= previous || right >= gate+tau) throw Error('The guest places overlap the border access groove.');
      sectors.push({slot:null,left:previous,right:left},{slot,left,right,angle});
      previous = right;
    }
    sectors.push({slot:null,left:previous,right:gate+tau});
    return {transit,erase,brushes:live.guestBorderSectors,gate,low,high,width,inner,outer,sectors};
  }

  function plan(scene, outlines, order = 'whole') {
    const layout = borderLayout(scene), {transit,erase,gate,low,high} = layout;
    if (!Array.isArray(outlines) || outlines.length !== 3) throw Error('Choose three guest places for the border.');
    if (outlines.every(p => p === null)) throw Error('Draw something in a guest place before making the border.');
    const sectors = layout.sectors.map(s => s.slot === null
      ? {...s,art:garland(s.left,s.right,low,high)} : guestSector(s,layout,outlines[s.slot]));
    const spoke = line(gate+tau,high,gate+tau,low);
    if (order === 'progressive') return progressive(layout.brushes,sectors,transit,spoke);
    if (order !== 'whole') throw Error('Choose a whole-border or one-at-a-time reveal.');

    const planner = globalThis.OasisRingPlanner, placements = Array(3).fill(null);
    let row = transit.length+erase.length-2;
    for (const s of sectors) {
      if (s.placement) placements[s.slot] = {...s.placement,first:row+s.placement.first,last:row+s.placement.last};
      row += s.art.length-1;
    }
    const art = planner.join([...sectors.map(s=>s.art),spoke,spoke.slice().reverse()]);
    const segments = [transit,erase,art,transit.slice().reverse()];
    return {art, placements, segments, path:planner.join(segments)};
  }
  function planSeat(scene, place, outline, grain = 'fluted') {
    if (!Number.isInteger(place) || place < 0 || place >= 3) throw Error('Choose one guest place on the border.');
    const layout = borderLayout(scene), {brushes,sectors,transit,gate,high} = layout;
    checkBrushes(brushes,sectors);
    const index = sectors.findIndex(s => s.slot === place), {left,right} = sectors[index];
    const seat = guestSector(sectors[index],layout,outline);
    const planner = globalThis.OasisRingPlanner;
    // The completed garland already has its radial access groove. This trip
    // retraces the outside rail on either side and stops at that groove's top.
    const entry = planner.join([transit,line(gate,high,gate+wrap(left-gate),high)]);
    const packed = grain === 'fluted' ? brushes[index].clear : grain === 'spiral' ? brushes[index].spiral : null;
    if (!packed) throw Error('This garden has no matching brush for the existing border texture.');
    const brush = planner.unpack(packed);
    const finish = planner.join([seat.art,line(right,high,right+wrap(gate-right),high)]);
    const segments = [entry,brush,finish,transit.slice().reverse()];
    const start = entry.length-1, clearEnd = start+brush.length-1;
    const placements = Array(3).fill(null);
    if (seat.placement) {
      const p = seat.placement;
      placements[place] = {...p,first:clearEnd+p.first,last:clearEnd+p.last};
    }
    const sectorSteps = [{sector:index,start,clearEnd,end:clearEnd+seat.art.length-1}];
    return {path:planner.join(segments),segments,placements,sectorSteps};
  }

  return {plan, planSeat};
})();
globalThis.GuestKeepsakeBorder = GuestKeepsakeBorder;
if (typeof module !== 'undefined' && module.exports) module.exports = GuestKeepsakeBorder;
