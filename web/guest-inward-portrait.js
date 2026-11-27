// A whole-Mini portrait on nested inward turns. Each turn stays inside the rim
// and the last turn meets the photographed head, which carries the ball back out.
(() => {
  'use strict';
  const tau = 2 * Math.PI, radiusMm = 114.03, groove = 5.32 / radiusMm, pitch = .020;
  const span = tau / pitch, gate = -Math.PI / 2;
  const reach = p => Math.hypot(...p);
  const gap = (a, b) => Math.hypot(a[0] - b[0], a[1] - b[1]);
  const near = (angle, prior) => angle + tau * Math.round((prior - angle) / tau);
  const lerp = (a, b, t) => [a[0] + t * (b[0] - a[0]), a[1] + t * (b[1] - a[1])];

  // Coalesce polar-linear segments within .018 mm. Keep reversals, cusps
  // and turns at zero, where a change of angle has no physical length.
  function compact(input) {
    const result = [input[0]];
    for (let first = 0; first + 1 < input.length;) {
      let last = first + 1;
      const [theta, r] = input[first];
      let scale = Math.max(r, input[last][1], 1e-6);
      let minRadius = Math.min(r, input[last][1]);
      for (let i = last + 1; i < Math.min(first + 32, input.length); i++) {
        const [end, s] = input[i];
        if (Math.abs(end - theta) > .0549 || Math.abs(s - r) > .045) break;
        minRadius = Math.min(minRadius, s);
        if (minRadius === 0 && r > 0 && s > 0) break;
        scale = Math.max(scale, s);
        const dx = (end - theta) * scale, dy = s - r;
        const length = Math.hypot(dx, dy);
        if (length < 1e-10) break;
        let prior = 0, fits = true;
        for (let k = first + 1; k <= i; k++) {
          const x = (input[k][0] - theta) * scale, y = input[k][1] - r;
          const along = (x * dx + y * dy) / length;
          if (along + 1e-10 < prior || Math.abs(x * dy - y * dx) > length * .018 / radiusMm) {
            fits = false;
            break;
          }
          prior = along;
        }
        if (!fits) break;
        last = i;
      }
      result.push(input[last]);
      first = last;
    }
    return result;
  }

  function normalize(contours, keepScale) {
    if (!Array.isArray(contours) || !contours.length)
      throw Error('Choose one face for the inward portrait.');
    const extent = contours.reduce((r, line) => line.reduce((v, p) => Math.max(v, reach(p)), r), 0);
    if (!(extent > 0) || !Number.isFinite(extent)) throw Error('The face has no drawable outline.');
    if (keepScale && extent > 1 - groove / 2 + 1e-8) throw Error('The selected faces reach outside their drawing area.');
    const scale = keepScale ? 1 : (1 - groove / 2) / extent;
    return contours.map(line => line.map(([x, y]) => [x * scale, y * scale]));
  }
  function carve(loops, opening, {headExit, word, quietFace = false} = {}) {
    if (!Number.isFinite(opening)) throw Error('The Mini needs a known starting position.');
    const [head, ...features] = loops;
    if (head.length < 3) throw Error('The head outline could not be traced.');
    const indexByRadius = (points, direction) => points.reduce((best, p, i) =>
      direction * reach(p) > direction * reach(points[best]) ? i : best, 0);
    const start = indexByRadius(head, -1), finish = headExit ? headExit.i : indexByRadius(head, 1);
    const center = head[start], c = reach(center), denom = 1 - c * c;
    const clearance = .52 * groove / (1 - c);
    // A point on a circle of radius r has physical position r*u + (1-r)*center.
    // Invert that relationship to locate each feature relative to the rake.
    function virtual(p) {
      const x = p[0] - center[0], y = p[1] - center[1];
      const dot = x * center[0] + y * center[1];
      const r = (dot + Math.sqrt(dot * dot + denom * (x * x + y * y))) / denom;
      return [Math.atan2(y + r * center[1], x + r * center[0]), r];
    }
    // Increase turn density gradually in the middle of the inward pass. The
    // outer and innermost turns keep the measured 0.020 spacing. A continuous
    // bearing derivative across both band edges avoids a seam in the sand.
    function rampIntegral(u) {
      const transition = .055;
      if (u <= 0) return 0;
      if (u >= transition) return u - transition / 2;
      return u * u / (2 * transition);
    }
    function winding(u) {
      if (!quietFace) return u * span;
      const extraTurns = 1 / .012 - 1 / pitch;
      return tau * (u / pitch + extraTurns * (rampIntegral(u - .26) - rampIntegral(u - .79)));
    }
    const endBearing = winding(1);
    function progressAt(bearing) {
      if (!quietFace) return bearing / span;
      if (bearing > endBearing + 1e-9) return Infinity;
      let lo = 0, hi = 1;
      for (let i = 0; i < 30; i++) {
        const u = (lo + hi) / 2;
        if (winding(u) < bearing) lo = u;
        else hi = u;
      }
      return (hi + lo) / 2;
    }
    function job(line) {
      // Inspect the chords too. Their inward extreme can lie between vertices.
      const points = [];
      for (let i = 0; i < line.length; i++) {
        const a = line[i], b = line[(i + 1) % line.length];
        const steps = Math.max(1, Math.ceil(gap(a, b) / .008));
        for (let k = 0; k < steps; k++) points.push(lerp(a, b, k / steps));
      }
      const polar = points.map(virtual);
      const inner = polar.reduce((best, p, i) => p[1] < polar[best][1] ? i : best, 0);
      const earliest = opening + winding(1 - polar[inner][1] + clearance);
      let at = 1, index = inner, shortest = Infinity;
      for (const [i, [t, r]] of polar.entries()) {
        const bearing = t + tau * Math.ceil((earliest - t) / tau);
        const u = progressAt(bearing - opening);
        const dist = r - (1 - u);
        if (u <= 1 && dist >= 0 && dist < shortest) {
          at = u; index = i; shortest = dist;
        }
      }
      return {at, stroke:[...points.slice(index), ...points.slice(0, index + 1)]};
    }
    function onSpiral(u) {
      const t = opening + winding(u);
      return [(1 - u) * Math.cos(t) + u * center[0], (1 - u) * Math.sin(t) + u * center[1]];
    }
    const xy = [onSpiral(0)];
    let previous = 0;
    function rake(end) {
      const beginAngle = winding(previous);
      const interval = quietFace ? winding(end) - beginAngle : (end - previous) * span;
      const steps = Math.ceil(interval / .026);
      for (let i = 1; i <= steps; i++) {
        let u = previous + (end - previous) * i / steps;
        if (quietFace) u = i === steps ? end : progressAt(beginAngle + interval * i / steps);
        xy.push(onSpiral(u));
      }
      previous = end;
    }
    for (const {at, stroke} of features.map(job).sort((a, b) => a.at - b.at)) {
      rake(at);
      for (const p of stroke) xy.push(p);
      xy.push(onSpiral(at));
    }
    rake(1);
    // Walk a complete outline and use its shorter side to the outermost point.
    const ordered = [...head.slice(start), ...head.slice(0, start + 1)];
    const exit = (finish - start + head.length) % head.length;
    const forward = ordered.slice(0, exit + 1), back = ordered.slice(exit).reverse();
    const length = path => path.slice(1).reduce((n, p, i) => n + gap(p, path[i]), 0);
    xy.push(...ordered, ...(length(forward) <= length(back) ? forward : back));
    const edge = head[finish], endAngle = Math.atan2(edge[1], edge[0]);
    xy.push(headExit ? headExit.gate : [Math.cos(endAngle), Math.sin(endAngle)]);
    const signed = compact(OasisRingPlanner.portraitStroke(xy, 1, opening, 1, .015));
    function followRim(angle) {
      const last = signed.at(-1)[0], delta = near(angle, last) - last;
      const steps = Math.ceil(Math.abs(delta) / .05);
      for (let i = 1; i <= steps; i++) signed.push([last + delta * i / steps, 1]);
    }
    if (word) {
      followRim(Math.atan2(word.gate[1], word.gate[0]));
      const letters = OasisRingPlanner.portraitStroke(word.walk, 1, signed.at(-1)[0], 1, .015);
      for (const point of compact(letters).slice(1)) signed.push(point);
    }
    followRim(gate);
    if (signed.length > 12000 && quietFace) throw Error('The closer erase and this portrait exceed the Mini’s single-pass limit. Choose Inward erase with hair engraving.');
    if (signed.length > 12000) throw Error('This face has too many lines for one inward pass. Use the ordinary portrait or choose another crop.');
    if (signed.some(([, r]) => r > 1 + 1e-8)) throw Error('This portrait reaches outside the Mini.');
    const files = OasisRingPlanner.files(signed.map(([t, r]) => [t, Math.min(r, 1)]), 'inward');
    // The portable exporter splits after 11,998 positions and repeats the
    // seam. The Mini can receive all 12,000 in its single physical file.
    const text = files.map((file,i) => i ? file.text.slice(file.text.indexOf('\n')+1) : file.text).join('');
    const path = text.trimEnd().split('\n').map(line => line.split(' ').map(Number));
    return {text, path};
  }
  function plan(contours, opening, {quietFace = false, keepScale = false} = {}) {
    return carve(normalize(contours, keepScale), opening, {quietFace});
  }
  function fitRimName(loops, lettering) {
    const points = loops.flat(), limit = 1 - groove;
    // Keep the face above every letter's top edge, with room for both grooves.
    const edges = lettering.strokes.map(({normal:[nx,ny]}) => ({
      nx, ny, furthest:points.reduce((max,[x,y]) => Math.max(max,x*nx+y*ny),-Infinity)
    }));
    const ceiling = lettering.topRadius - 1.75*groove;
    for (let pct = 100; pct >= 75; pct--) {
      const scale = pct / 100;
      let best;
      // A tilted head can often stay larger a few millimeters off center.
      for (let column = -15; column <= 15; column++) {
        const dx = column * groove / 3;
        const dy = Math.max(0, ...edges.map(({nx,ny,furthest}) => (scale*furthest+dx*nx-ceiling)/-ny));
        if (best && dx*dx + dy*dy >= best.distance) continue;
        if (points.every(([x,y]) => (x*scale+dx)**2 + (y*scale+dy)**2 <= limit**2))
          best = {dx,dy,distance:dx*dx+dy*dy};
      }
      if (best) return loops.map(line => line.map(([x,y]) => [x*scale+best.dx,y*scale+best.dy]));
    }
    return null;
  }
  async function namedPlan(contours, opening, name, {quietFace = false, keepScale = false} = {}) {
    const loops = normalize(contours, keepScale);
    const capitals = globalThis.GuestLettering?.rimName?.(name, groove);
    const face = capitals && fitRimName(loops, capitals);
    if (face) {
      const headExit = GuestPortraitCaption.entrance(face[0], true);
      const strokes = face.concat(capitals.strokes.map(letter => letter.path));
      return {...carve(strokes, opening, {headExit, quietFace}), inscription:'“'+capitals.label+'” follows the lower rim.'};
    }
    const {scale, shift, caption, label} = await GuestPortraitCaption.layout(loops.flat(), name, groove);
    const placed = loops.map(line => line.map(([x,y]) => [x * scale, y * scale + shift]));
    const headExit = GuestPortraitCaption.entrance(placed[0], true);
    const word = GuestPortraitCaption.entrance(caption, false);
    return {...carve(placed, opening, {headExit, word, quietFace}), inscription:'The ball follows the rim to write “'+label+'” below the face.'};
  }
  function preview(path, size) {
    const sand = new MiniLocalGrooves(size, groove, {
      floor:.72, floor_k:4, ridge:.42, ridge_at:1.5, ridge_w:.42, lighting:'mini'
    });
    const bed = sand.empty();
    sand.carve(bed, path);
    return sand.draw(bed);
  }
  // Same two-motor timing model as tools/mini_portrait_timing.py. A turn at
  // the center can take time even though the ball covers no distance in sand.
  function estimatedSeconds(path, status) {
    if (!path.length || !status?.cal) return null;
    const {vmax, vj, acc, accc} = status;
    const {l, rmax, a, a1, b1, b2} = status.cal;
    const det = -a*b1 - a1*b2;
    if (![vmax,vj,acc,accc,l,rmax].every(v => Number.isFinite(v) && v > 0) ||
        !Number.isFinite(det) || !det) return null;
    const lengths = [], limits = [], join = Math.min(vj,vmax);
    let base1, base2, last1, last2, tick1=0, tick2=0, ux, uy;
    for (const [bearing, radius] of path) {
      const angle = Math.fround(bearing);
      const elbow = tau - 2*Math.asin(Math.min(.999, Math.fround(radius)*rmax/(2*l)));
      const m1 = (a*elbow - b2*angle)/det, m2 = (-b1*angle - a1*elbow)/det;
      if (base1 === undefined) {
        base1=last1=m1; base2=last2=m2;
        continue;
      }
      const t1=Math.round((m1-base1)*16), t2=Math.round((m2-base2)*16);
      const len=Math.max(Math.abs(t1-tick1),Math.abs(t2-tick2))/16;
      if (!len) continue;
      const dx=m1-last1, dy=m2-last2, norm=Math.max(Math.abs(dx),Math.abs(dy));
      const nx=dx/norm, ny=dy/norm;
      if (lengths.length) {
        const change=Math.max(1e-8,Math.abs(nx-ux),Math.abs(ny-uy));
        const corner=Math.min((join/change)**2,accc*(lengths.at(-1)+len)/(2*change));
        limits.push(Math.min(vmax**2,Math.max(Math.min(40,vmax)**2,corner)));
      } else limits.push(join**2);
      lengths.push(len); ux=nx; uy=ny; tick1=t1; tick2=t2; last1=m1; last2=m2;
    }
    limits.push(join**2);
    for (let i=lengths.length-1; i>=0; i--)
      limits[i]=Math.min(limits[i],limits[i+1]+2*acc*lengths[i]);
    let seconds=0;
    for (let i=0; i<lengths.length; i++) {
      const start=limits[i], finish=Math.min(limits[i+1],start+2*acc*lengths[i]);
      limits[i+1]=finish;
      const peak=Math.min(vmax**2,acc*lengths[i]+(start+finish)/2);
      const cruise=Math.max(0,lengths[i]-(2*peak-start-finish)/(2*acc));
      seconds+=(2*Math.sqrt(peak)-Math.sqrt(start)-Math.sqrt(finish))/acc+cruise/Math.sqrt(peak);
    }
    return seconds;
  }
  globalThis.GuestInwardPortrait = {plan, namedPlan, preview, estimatedSeconds};
})();
