// Approximate displaced sand along the ball's continuous path, including travel.
// Samples in each overlapping group share a groove. A later turn overwrites it.
class RingSand {
  constructor(size, groove, profile) {
    this.size = size;
    this.radius = (size - 1) / 2;
    const half = Math.max(.5, groove * this.radius / 2);
    this.step = Math.max(1, .3 * half);
    const support = 2.3 * half;
    this.bound = Math.ceil(support);
    this.scale = 511 / (support * support);
    this.depth = new Float32Array(512);
    this.mix = new Float32Array(512);
    for (let i = 0; i < 512; i++) {
      const u = 2.3 * Math.sqrt(i / 511);
      const ridge = profile.ridge * Math.exp(-(((u - profile.ridge_at) / profile.ridge_w) ** 2));
      this.depth[i] = ridge - Math.exp(-((u / profile.floor) ** profile.floor_k));
      this.mix[i] = u < 1.7 ? 1 : .5 * (1 + Math.cos(Math.PI * (u - 1.7) / .6));
    }
    this.useMiniLighting = profile.lighting === 'mini';
    this.half = half;
    this.closest = new Float32Array(size * size);
    this.owner = new Uint8Array(size * size);
    this.touched = new Int32Array(size * size);
    this.closest.fill(Infinity);
    this.canvas = document.createElement('canvas');
    this.canvas.width = this.canvas.height = size;
  }

  empty() { return new Float32Array(this.size * this.size); }

  carve(height, path) {
    if (path.length < 2) return;
    const xs = [], ys = [];
    const sample = (t, r) => {
      xs.push(this.radius * (1 + r * Math.cos(t)));
      ys.push(this.radius * (1 - r * Math.sin(t)));
    };
    sample(...path[0]);
    for (let i = 1; i < path.length; i++) {
      const [t0, r0] = path[i - 1], [t1, r1] = path[i];
      const dt = t1 - t0, dr = r1 - r0;
      const n = Math.max(1, Math.ceil(Math.hypot(dt * (r1 + r0) / 2, dr) * this.radius / this.step));
      for (let k = 1; k <= n; k++) sample(t0 + dt * k / n, r0 + dr * k / n);
    }
    for (let start = 0; start < xs.length; start += 36) {
      const end = Math.min(xs.length, start + 56);
      let count = 0;
      for (let j = start; j < end; j++) {
        const x = xs[j], y = ys[j], b = this.bound;
        const left = Math.max(0, Math.floor(x) - b), right = Math.min(this.size - 1, Math.ceil(x) + b);
        const top = Math.max(0, Math.floor(y) - b), bottom = Math.min(this.size - 1, Math.ceil(y) + b);
        for (let row = top; row <= bottom; row++) {
          const dy2 = (row - y) ** 2;
          for (let col = left; col <= right; col++) {
            const d = ((col - x) ** 2 + dy2) * this.scale;
            const p = row * this.size + col;
            if (d >= 511 || d >= this.closest[p]) continue;
            if (this.closest[p] === Infinity) this.touched[count++] = p;
            this.closest[p] = d;
            this.owner[p] = j - start;
          }
        }
      }
      const lo = start ? 10 : 0, hi = end === xs.length ? end - start : end - start - 10;
      for (let i = 0; i < count; i++) {
        const p = this.touched[i], index = Math.floor(this.closest[p]);
        if (this.owner[p] >= lo && this.owner[p] < hi) height[p] += this.mix[index] * (this.depth[index] - height[p]);
        this.closest[p] = Infinity;
      }
      if (end === xs.length) break;
    }
  }

  // Separable running sums keep the work per pixel independent of groove width.
  blurSand(source, result, radius, scratch) {
    const n = this.size, width = 2 * radius + 1;
    for (let y = 0; y < n; y++) {
      const row = y * n;
      let sum = source[row] * radius;
      for (let k = 0; k <= radius; k++) sum += source[row + k];
      for (let x = 0; x < n; x++) {
        scratch[row + x] = sum / width;
        sum += source[row + Math.min(n - 1, x + radius + 1)] - source[row + Math.max(0, x - radius)];
      }
    }
    for (let x = 0; x < n; x++) {
      let sum = scratch[x] * radius;
      for (let k = 0; k <= radius; k++) sum += scratch[k * n + x];
      for (let y = 0; y < n; y++) {
        result[y * n + x] = sum / width;
        sum += scratch[Math.min(n - 1, y + radius + 1) * n + x] - scratch[Math.max(0, y - radius) * n + x];
      }
    }
  }

  miniLighting() {
    const n = this.size, half = this.half;
    // RGB medians at 10 radii in the upper and lower halves of the photographed
    // Mini after a .020 erase. The bottom rim is lit more brightly.
    const upper = [[194,186,173], [190,182,170], [185,177,166], [179,172,162], [173,166,158],
                   [166,161,154], [153,148,143], [143,141,138], [154,154,155], [209,211,217]];
    const lower = [[195,187,174], [190,183,170], [185,179,166], [181,175,163], [177,172,161],
                   [166,161,155], [155,153,148], [154,153,151], [179,180,181], [221,225,230]];
    const base = new Uint8Array(n * n * 3), gain = this.empty();
    const noise = this.empty(), soft = this.empty(), broad = this.empty(), scratch = this.empty();
    // Fixed grain makes untouched sand look identical across redraws and reloads.
    let seed = 1852;
    for (let i = 0; i < noise.length; i++) {
      seed = (Math.imul(1664525, seed) + 1013904223) >>> 0;
      noise[i] = (seed / 4294967296 - .5) * Math.sqrt(12);
    }
    const fineRadius = Math.min(n - 1, Math.max(1, Math.round(.28 * half)));
    const broadRadius = Math.min(n - 1, Math.max(1, Math.round(.86 * half)));
    this.blurSand(noise, soft, fineRadius, scratch);
    this.blurSand(noise, broad, broadRadius, scratch);
    for (let y = 0; y < n; y++) {
      const vy = (y - this.radius) / this.radius;
      for (let x = 0; x < n; x++) {
        const i = y * n + x, vx = (x - this.radius) / this.radius, r = Math.sqrt(vx * vx + vy * vy);
        const index = Math.max(0, Math.min(9, 10 * r - .5)), lo = Math.floor(index), hi = Math.min(9, lo + 1);
        const blend = Math.max(0, Math.min(1, .5 + .7 * vy / Math.max(.04, r)));
        const grain = 2.8 * (2 * fineRadius + 1) * soft[i] + 1.8 * (2 * broadRadius + 1) * broad[i];
        for (let c = 0; c < 3; c++) {
          const a = upper[lo][c] + (lower[lo][c] - upper[lo][c]) * blend;
          const b = upper[hi][c] + (lower[hi][c] - upper[hi][c]) * blend;
          base[3 * i + c] = Math.round(a + (b - a) * (index - lo) - 8 + grain);
        }
        gain[i] = .80 + 2.0 * r ** 2.7;
      }
    }
    return {base, gain, soft, broad, scratch};
  }

  miniImage(height, frame) {
    if (!this.lighting) this.lighting = this.miniLighting();
    const {base, gain, soft, broad, scratch} = this.lighting;
    const n = this.size, half = this.half;
    const spread = Math.min(n - 1, Math.max(1, Math.round(.48 * half)));
    this.blurSand(height, soft, spread, scratch);
    this.blurSand(soft, soft, spread, scratch);
    // Limit light falloff to the width of a groove and its shoulders.
    this.blurSand(height, broad, Math.min(n - 1, Math.max(1, Math.floor(2.4 * half))), scratch);
    for (let y = 0; y < n; y++) {
      const vy = (y - this.radius) / this.radius;
      for (let x = 0; x < n; x++) {
        const i = y * n + x, vx = (x - this.radius) / this.radius;
        const gx = .5 * half * (soft[x + 1 < n ? i + 1 : i] - soft[x ? i - 1 : i]);
        const gy = .5 * half * (soft[y + 1 < n ? i + n : i] - soft[y ? i - n : i]);
        const slope = Math.sqrt(gx * gx + gy * gy);
        // The ring lights both shoulders, while a smaller directional term gives them depth.
        const shoulder = 37 * slope * Math.max(0, Math.min(1, (soft[i] + .75) / .9));
        const side = 14 * (gx * (.68 * vx - .31) + gy * (.85 * vy + .28));
        const shade = .78 * (36 * (soft[i] - broad[i]) + shoulder + side) * gain[i];
        const p = 4 * i, b = 3 * i;
        frame.data[p] = base[b] + shade;
        frame.data[p + 1] = base[b + 1] + shade;
        frame.data[p + 2] = base[b + 2] + shade;
        frame.data[p + 3] = 255;
      }
    }
  }

  draw(height) {
    const n = this.size, ctx = this.canvas.getContext('2d'), frame = ctx.createImageData(n, n);
    if (this.useMiniLighting) {
      this.miniImage(height, frame);
      ctx.putImageData(frame, 0, 0);
      return this.canvas;
    }
    // A single low sidelight makes the floor and the raised lips read together.
    const soft = new Float32Array(height.length);
    for (let y = 0; y < n; y++) {
      for (let x = 0; x < n; x++) {
        const i = y * n + x, left = Math.max(i - 1, y * n), right = Math.min(i + 1, (y + 1)*n - 1);
        soft[i] = .25 * (height[left] + 2 * height[i] + height[right]);
      }
    }
    const smoothed = new Float32Array(height.length);
    for (let i = 0; i < soft.length; i++)
      smoothed[i] = .25 * (soft[i < n ? i : i-n] + 2 * soft[i] + soft[i+n >= soft.length ? i : i+n]);
    for (let y = 0; y < n; y++) {
      for (let x = 0; x < n; x++) {
        const i = y * n + x, l = x ? i - 1 : i, r = x + 1 < n ? i + 1 : i;
        const u = y ? i - n : i, d = y + 1 < n ? i + n : i;
        const slope = (smoothed[r] - smoothed[l] + smoothed[d] - smoothed[u]) * .5;
        const shade = Math.max(.45, Math.min(1.1, 1 + .53 * slope * this.half + .23 * Math.min(0, height[i])));
        const px = 4*i;
        frame.data[px] = 240 * shade; frame.data[px+1] = 235 * shade;
        frame.data[px+2] = 222 * shade; frame.data[px+3] = 255;
      }
    }
    ctx.putImageData(frame, 0, 0);
    return this.canvas;
  }

  image(height) {
    return this.draw(height).toDataURL('image/png');
  }
}

// Recover the prepared rim texture even from a garden kept by an older phone.
// The probes sample the laurel gaps, which a single-chair change never recuts.
const GuestBorderGrain = {
  read(scene, height) {
    const level = index => Math.round((1+Math.min(.5,Math.max(-1,height[index])))*170);
    const size = scene.live.size;
    let acrossRings = 0, acrossFlutes = 0;
    for (const [index,cosine,sine] of scene.live.guestBorderGrain) {
      const dx = level(index+1)-level(index-1), dy = level(index+size)-level(index-size);
      acrossRings += (dx*cosine-dy*sine)**2;
      acrossFlutes += (dx*sine+dy*cosine)**2;
    }
    return acrossRings > acrossFlutes ? 'spiral' : 'fluted';
  }
};
