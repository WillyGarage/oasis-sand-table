/* Mini center replacements and the seven-roof frame that was drawn in sand. */
const GuestCenterRoutes = (() => {
  const tau = 2 * Math.PI;
  const gate = -Math.PI / 2;
  const tolerance = 0.000025; // cumulative .thr coordinates are rounded to five decimals
  const limit = 12000;
  let loading;

  function unpack(encoded) {
    const path = globalThis.OasisRingPlanner.unpack(encoded);
    if (path.length < 2 || path.length > limit) {
      throw Error('The stored Mini route could not be read.');
    }
    return path;
  }

  function data() {
    if (!loading) {
      loading = (async () => {
        const response = await fetch('/lib/guest-center-data.json');
        if (!response.ok) throw Error('The Mini drawing data could not load. Try previewing again.');
        const stored = await response.json();
        const stock = {};
        for (const name of ['center-clear', 'phage', 'guitar', 'book', 'add-pencil']) {
          if (stored.stock[name]) stock[name] = unpack(stored.stock[name]);
        }
        // The planner reverses an inward erase when given this form of its zone.
        const photoZone = {transit:stored.transit, erase:unpack(stored.photoErase).reverse()};
        return {stock, frame:unpack(stored.frame), roofs:stored.roofs, photoZone,
                centerBounds:stored.centerBounds, outerBounds:stored.outerBounds};
      })().catch(error => { loading = undefined; throw error; });
    }
    return loading;
  }

  function wrapped(angle) {
    const turn = angle % tau;
    return turn > Math.PI ? turn - tau : turn < -Math.PI ? turn + tau : turn;
  }

  function join(parts) {
    return globalThis.OasisRingPlanner.join(parts, tolerance);
  }

  // Check the actual rounded rows the firmware will parse. Radius is monotonic
  // between the two endpoints of a polar segment. Travel outside the art band
  // must stay on the existing six-o'clock spoke or the frame's initial rim arc.
  function exportPath(path, bounds, startTheta, rimSteps = 0) {
    if (path.length < 2 || path.length > limit) throw Error('This drawing must fit in 12,000 table points.');
    const rows = [];
    let previous;
    for (const [index, point] of path.entries()) {
      if (!point.every(Number.isFinite) || point[1] < 0 || point[1] > 1) {
        throw Error('The Mini route contains an invalid position.');
      }
      const row = point.map(value => value.toFixed(5));
      const [theta, radius] = row.map(Number);
      const first = index === 0, last = index === path.length - 1;
      if ((first && (radius !== 1 || Math.abs(wrapped(theta - startTheta)) > tolerance)) ||
          (last && (radius !== 1 || Math.abs(wrapped(theta - gate)) > tolerance))) {
        throw Error('The Mini route does not connect to its rim position.');
      }
      if (radius < bounds[0] - tolerance) throw Error('The Mini route crosses a protected drawing.');
      if (previous) {
        const [priorTheta, priorRadius] = previous;
        const turn = Math.abs(theta - priorTheta);
        if (turn > Math.PI + tolerance) throw Error('The Mini route contains an unexpected turn.');
        if (index <= rimSteps) {
          if (radius !== 1 || priorRadius !== 1 || turn > 0.05 + 1e-10) {
            throw Error('The approach to the frame left the rim.');
          }
        } else if (Math.max(radius, priorRadius) > bounds[1] + tolerance &&
                   (turn > 2 * tolerance || Math.abs(wrapped(priorTheta - gate)) > tolerance ||
                    Math.abs(wrapped(theta - gate)) > tolerance)) {
          throw Error('The Mini route leaves the shared six-o’clock groove.');
        }
      }
      rows.push(row.join(' '));
      previous = [theta, radius];
    }
    return rows.join('\n') + '\n';
  }

  function roofPreview({roofs, frame}) {
    return join(roofs.map(([first, last]) => frame.slice(first, last + 1)));
  }

  async function border() {
    return roofPreview(await data());
  }

  async function photoDiameterGrooves(target = 'center') {
    // The Mini's measured working radius is 114.03 mm and its groove is 5.32 mm.
    const radius=target==='full' ? 1 : (await data()).centerBounds[1];
    return 2*radius*114.03/5.32;
  }

  async function frame(theta) {
    if (!Number.isFinite(theta)) throw Error('The table needs a known rim position to draw the frame.');
    const routes = await data();
    const signed = routes.frame;
    const dock = signed[0][0], start = wrapped(theta);
    const delta = wrapped(start - dock);
    // Use the signed file's original turns. Only the approach changes with the
    // ball's starting angle. Leave enough headroom for five-decimal rounding.
    const atDock = Math.abs(wrapped(start - gate)) <= 0.000005 || Math.abs(delta) <= 0.000005;
    const steps = atDock ? 0 : Math.ceil(Math.abs(delta) / 0.04999);
    const approach = Array.from({length:steps}, (_, i) => [dock + delta * (1 - i / steps), 1]);
    return {text:exportPath(approach.concat(signed), routes.outerBounds, start, steps),
            preview:roofPreview(routes)};
  }

  async function stock(subject) {
    if (!['phage','guitar','book','book-pencil'].includes(subject)) throw Error('Choose a center drawing.');
    const routes = await data();
    if (subject === 'book-pencil') {
      const {book, 'add-pencil': pencil} = routes.stock;
      if (!book || !pencil) throw Error('The pencil drawing is unavailable on this Mini.');
      return {text:exportPath(pencil, routes.centerBounds, gate), preview:join([book,pencil])};
    }
    const drawing = routes.stock[subject];
    if (!drawing || !routes.stock['center-clear']) throw Error('This center drawing is unavailable on this Mini.');
    return {text:exportPath(join([routes.stock['center-clear'], drawing]), routes.centerBounds, gate),
            preview:drawing.map(point => point.slice())};
  }

  async function photo(points) {
    const routes = await data();
    const zone = routes.photoZone;
    const tooDetailed = 'This photo is too detailed for one Mini drawing. Choose fewer faces or a simpler crop and preview again.';
    const fixedSteps = zone.erase.length - 1 + 2 * (zone.transit.length - 1);
    if (Array.isArray(points) && points.length + fixedSteps > limit) throw Error(tooDetailed);
    let planned;
    try {
      planned = globalThis.OasisRingPlanner.photo(zone, points);
    } catch (error) {
      if (error.message === 'This portrait has too many travel points.') throw Error(tooDetailed);
      throw error;
    }
    const {segments, path} = planned;
    if (path.length > limit) throw Error(tooDetailed);
    const [entry, , art, exit] = segments;
    return {text:exportPath(path, routes.centerBounds, gate), preview:join([entry, art, exit])};
  }

  return {stock, photo, frame, border, photoDiameterGrooves};
})();
globalThis.GuestCenterRoutes = GuestCenterRoutes;
if (typeof module !== 'undefined' && module.exports) module.exports = GuestCenterRoutes;
