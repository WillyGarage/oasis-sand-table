// Preview on this phone only. The held drawing is the ordinary saved garden.
function bindRingRotation(main, book, catalog, {ideasFor, isKept, sameDrawing, change, pendingEdit, table}) {
  const panel = main.querySelector('#changingGarden');
  const button = panel.querySelector('button');
  const status = panel.querySelector('[role=status]');
  const summary = panel.querySelector('summary');
  const title = summary.textContent;
  const holdSeconds = 30;
  let timer = null, cursor = 0, choices = [];
  let tableActive=false, submitting=false;
  // Only this uninterrupted run may rotate past a saved picture it chose itself.
  let automaticPictures = new Map();
  if (table) panel.querySelector('p').textContent =
    'Change one guest’s drawing after the table finishes and its viewing time ends. Photos and sketches guests place themselves stay on display. Keep this page open.';
  const symbolSupport = new Map();
  const missing = new Set();
  function outline(glyph) {
    try { return JSON.stringify(GuestArt.glyphStrokes(glyph)[0]); }
    catch { return ''; }
  }
  function available(art) {
    if (Object.hasOwn(catalog.subjects, art.id) || isKept(art.id)) return true;
    if (!art.glyph) return false;
    if (!symbolSupport.has(art.glyph)) {
      // Missing-glyph boxes can include different digits inside the same outline.
      if (!missing.size) for (const unused of ['\u0378','\u{10ffff}']) missing.add(outline(unused));
      const shape = outline(art.glyph);
      symbolSupport.set(art.glyph, !!shape && !missing.has(shape));
    }
    return symbolSupport.get(art.glyph);
  }
  function next() {
    const current = book.active.map(person => person.subject);
    const order = current.map((_,n)=>(cursor+n)%current.length);
    // Give guests who have a clear place a drawing before replacing one on display.
    if (catalog.openSubject) order.sort((a,b)=>Number(current[b]===catalog.openSubject)-Number(current[a]===catalog.openSubject));
    for (const slot of order) {
      const id = current[slot], ideas = choices[slot];
      if (id.startsWith('sketch-') && automaticPictures.get(slot) !== id) continue;
      const position = ideas.findIndex(art => sameDrawing(id, art));
      for (let offset = 1; offset <= ideas.length; offset++) {
        const art = ideas[(position + offset) % ideas.length];
        if (!current.some(other => sameDrawing(other, art))) return {slot, art};
      }
    }
    return null;
  }
  function advanced(slot, art) {
    if (isKept(art.id)) automaticPictures.set(slot, art.id);
    else automaticPictures.delete(slot);
    cursor = (slot + 1) % book.active.length;
  }
  function stop(message = table ? 'Automatic changes are off. Queued drawings will finish.' :
    'Stopped. The current drawing stays on display.') {
    if (timer === null && !tableActive) return;
    clearTimeout(timer);
    timer = null;
    tableActive=false;
    automaticPictures = new Map();
    button.textContent = 'Start changing';
    if (table) summary.textContent=title;
    status.textContent = message;
  }
  function schedule() {
    const upcoming = next();
    if (!upcoming) {
      stop();
      status.textContent = 'No other drawings match these guests.';
      return;
    }
    const {slot, art} = upcoming;
    button.textContent = 'Stop changing';
    status.textContent = 'Next for ' + book.active[slot].name + ' in ' + holdSeconds + ' seconds · ' + art.label;
    const scheduled = setTimeout(async () => {
      if (document.hidden || !main.isConnected) { stop(); return; }
      try {
        const kept = await change(slot, art);
        if (timer !== scheduled) return;
        if (!kept) { stop('The guest ring stopped at the last saved drawing.'); return; }
        advanced(slot, art);
        schedule();
      } catch (error) {
        stop(error.message || 'Could not preview the next drawing.');
      }
    }, holdSeconds * 1000);
    timer = scheduled;
  }
  function useCurrentGuests() {
    choices = book.active.map(person => ideasFor(GuestArt.guestInterest(person)).filter(available));
    if (!table) schedule();
  }
  async function onPlayback(data) {
    if (!tableActive || submitting || document.hidden || !main.isConnected) return;
    if (pendingEdit()) {
      status.textContent='Waiting for your current edit.';
      return;
    }
    if (!table.ready(data)) {
      status.textContent='Automatic changes are on. Waiting for the table.';
      return;
    }
    useCurrentGuests();
    const upcoming=next();
    if (!upcoming) {
      stop('No other drawings match these guests.');
      return;
    }
    submitting=true;
    const {slot,art}=upcoming;
    const run=automaticPictures;
    status.textContent='Queuing '+art.label+' for '+book.active[slot].name+'.';
    try {
      const kept=await table.change(slot,art);
      if (kept && tableActive && run===automaticPictures) advanced(slot, art);
      if (tableActive) status.textContent='Automatic changes are on. Waiting for the table.';
    } catch (error) {
      stop(error.message || 'Could not prepare the next guest drawing.');
    } finally { submitting=false; }
  }
  button.onclick = () => {
    if (timer !== null || tableActive) { stop(); return; }
    if (document.hidden) return;
    if (pendingEdit()) {
      status.textContent = 'Keep your current edit or clear it before starting.';
      return;
    }
    if (table) {
      tableActive=true;
      button.textContent='Stop changing';
      summary.textContent=title+' · on';
      status.textContent='Checking the table…';
      table.refresh();
    } else useCurrentGuests();
  };
  const events = new AbortController();
  function manual(event) {
    if (!table && !panel.contains(event.target) && event.target.closest('input, select, button, canvas, summary, form')) stop();
  }
  for (const type of ['focusin','pointerdown','click','input','change','submit']) {
    main.addEventListener(type, manual, {capture:true, signal:events.signal});
  }
  panel.ontoggle = () => { if (!table && !panel.open) stop(); };
  document.addEventListener('visibilitychange', () => {
    if (document.hidden && !table) stop();
    else if (!document.hidden && tableActive) table.refresh();
  }, {signal:events.signal});
  window.addEventListener('pagehide', () => stop(), {signal:events.signal});
  return {
    onPlayback,
    forget(slot) { automaticPictures.delete(slot); },
    changed(untouchedPlaces = []) {
      // A change from another phone can arrive between holds. Only retain
      // a choice when the room can verify that nobody edited that place.
      automaticPictures = new Map([...automaticPictures].filter(([slot]) => untouchedPlaces[slot]));
      if (timer !== null) {
        clearTimeout(timer);
        useCurrentGuests();
      }
    },
    close() { stop(); events.abort(); }
  };
}
