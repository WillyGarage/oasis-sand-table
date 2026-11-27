// A pass makes its deepest mark at each pixel where the ball first approaches
// and then recedes. Apply those closest approaches in the order of the signed
// movements. Editing a remote stroke cannot shift the grouping of later cuts.
class MiniLocalGrooves extends RingSand {
  carve(height, path) {
    if (path.length < 2) return;
    const size = this.size;
    const support = 2.3 * this.half;
    const epsilon = 1e-9;  // pixels, for points on the shared end of two chords

    const touch = (x, y, distanceSquared) => {
      const bin = Math.floor(distanceSquared * this.scale);
      if (bin >= 511) return;
      const i = y * size + x;
      height[i] += this.mix[bin] * (this.depth[bin] - height[i]);
    };

    // The closest point falls inside a chord only between the two planes
    // perpendicular to its ends. Clip each row to that narrow strip.
    const strip = (x, y, dx, dy, ux, uy, length) => {
      const padX = support * Math.abs(uy), padY = support * Math.abs(ux);
      const left = Math.max(0, Math.min(x, x + dx) - padX);
      const right = Math.min(size - 1, Math.max(x, x + dx) + padX);
      const top = Math.max(0, Math.ceil(Math.min(y, y + dy) - padY));
      const bottom = Math.min(size - 1, Math.floor(Math.max(y, y + dy) + padY));
      for (let row = top; row <= bottom; row++) {
        const offsetY = row - y;
        let lo = left, hi = right;
        if (Math.abs(ux) > 1e-12) {
          const start = x - offsetY * uy / ux;
          const end = start + length / ux;
          lo = Math.max(lo, Math.min(start, end));
          hi = Math.min(hi, Math.max(start, end));
        } else if (offsetY * uy <= 0 || offsetY * uy >= length) {
          continue;
        }
        if (Math.abs(uy) > 1e-12) {
          const center = x + offsetY * ux / uy;
          const halfWidth = support / Math.abs(uy);
          lo = Math.max(lo, center - halfWidth);
          hi = Math.min(hi, center + halfWidth);
        } else if (Math.abs(offsetY) >= support) {
          continue;
        }
        for (let col = Math.ceil(lo - epsilon); col <= Math.floor(hi + epsilon); col++) {
          const offsetX = col - x;
          const along = offsetX * ux + offsetY * uy;
          if (along <= epsilon || along >= length - epsilon) continue;
          const normal = offsetX * uy - offsetY * ux;
          touch(col, row, normal * normal);
        }
      }
    };

    // At a shared vertex the incoming chord must be approaching this pixel
    // and the outgoing chord leaving it. A zero direction gives an end cap.
    const vertex = (x, y, prevX, prevY, nextX, nextY) => {
      const top = Math.max(0, Math.ceil(y - support));
      const bottom = Math.min(size - 1, Math.floor(y + support));
      for (let row = top; row <= bottom; row++) {
        const offsetY = row - y;
        const span = Math.sqrt(Math.max(0, support * support - offsetY * offsetY));
        let lo = Math.max(0, x - span), hi = Math.min(size - 1, x + span);
        if (Math.abs(prevX) > 1e-12) {
          const edge = x + (-epsilon - offsetY * prevY) / prevX;
          if (prevX > 0) lo = Math.max(lo, edge);
          else hi = Math.min(hi, edge);
        } else if (offsetY * prevY < -epsilon) {
          continue;
        }
        if (Math.abs(nextX) > 1e-12) {
          const edge = x + (epsilon - offsetY * nextY) / nextX;
          if (nextX > 0) hi = Math.min(hi, edge);
          else lo = Math.max(lo, edge);
        } else if (offsetY * nextY > epsilon) {
          continue;
        }
        for (let col = Math.ceil(lo); col <= Math.floor(hi); col++) {
          touch(col, row, (col - x) ** 2 + offsetY ** 2);
        }
      }
    };

    const radius = this.radius;
    let x = radius * (1 + path[0][1] * Math.cos(path[0][0]));
    let y = radius * (1 - path[0][1] * Math.sin(path[0][0]));
    let prevX = 0, prevY = 0;
    for (let i = 1; i < path.length; i++) {
      const [t0, r0] = path[i - 1], [t1, r1] = path[i];
      const dt = t1 - t0, dr = r1 - r0;
      const length = Math.hypot(dt * (r1 + r0) / 2, dr) * radius;
      const chords = Math.max(1, Math.ceil(length / this.step));
      for (let k = 1; k <= chords; k++) {
        const theta = k === chords ? t1 : t0 + dt * k / chords;
        const r = k === chords ? r1 : r0 + dr * k / chords;
        const nextX = radius * (1 + r * Math.cos(theta));
        const nextY = radius * (1 - r * Math.sin(theta));
        const dx = nextX - x, dy = nextY - y, chord = Math.hypot(dx, dy);
        if (chord < epsilon) continue;
        const ux = dx / chord, uy = dy / chord;
        vertex(x, y, prevX, prevY, ux, uy);
        strip(x, y, dx, dy, ux, uy, chord);
        x = nextX;
        y = nextY;
        prevX = ux;
        prevY = uy;
      }
    }
    // A bearing change at zero radius or repeated row does not move the ball.
    if (prevX || prevY) vertex(x, y, prevX, prevY, 0, 0);
  }
}
