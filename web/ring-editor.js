// Compare an erase and redraw against the guest's current simulated garden.
function startRingEditor(scene, carriedPhoto, initial, savedThisVisit) {
  const main = document.querySelector('main');
  const $ = id => main.querySelector('#' + id);
  const familyBorder = scene.layout==='portrait' && new URLSearchParams(location.search).get('example')==='family-border' &&
    scene.live.familyBorder;
  const room = !familyBorder && document.querySelector('meta[name=oasis-room]') ? new RingRoom(scene.layout, main) : null;
  const attached = !!room?.attached;
  const catalog = scene.live.planner;
  const exampleId=initial && /^#example-([a-z0-9-]+)$/.exec(location.hash)?.[1].replaceAll('-','_');
  const libraryExample=!!exampleId && !!catalog?.librarySubjects?.includes(exampleId);
  const book = catalog ? new RingGuestBook(catalog.defaults) : null;
  const photoPlaces = !!catalog?.places?.some(Boolean);
  const hasPhotoExamples = Object.values(scene.live.examples || {}).some(Boolean);
  const titles = {center:'Center', middle:'Middle ring', outer:'Outer ring'};
  const labels = {...catalog?.subjects};
  const preferred = catalog?.preferredSubjects || {};
  const styles = {dna:'dna_open', phage:'phage_faceted', paper_crane:'origami_crane', ...catalog?.styles};
  const roofName='(?:thai(?: temple)?|temple) (?:roof(?:top)?|gable)';
  const bookName='(?:open |pop ?up )?book';
  const article='(?:(?:a|an|the) )?';
  const risesFrom='(?:rising|emerging|springing|popping|folding) (?:up )?(?:out of|out from|from) ';
  const popupBookNames=new RegExp('^(?:'+roofName+' pop ?up book|'+roofName+' '+risesFrom+'(?:the pages of )?'+article+bookName+
    '|(?:open )?pop ?up book (?:with|featuring|showing|of) '+article+roofName+
    '|(?:open )?book with '+article+'pop ?up '+roofName+')$');
  const manifest = {preferredSubjects:preferred,subjects:Object.fromEntries(Object.entries(labels).map(([id, label]) => [id, {label}]))};
  const openSubject = catalog?.openSubject;
  const decorations = {
    temple_crescent:{base:'temple_gable',subject:'rooftop',detail:'crescent moon',details:['crescent','crescent moon','moon'],
      subjects:['roof','rooftop','thai rooftop','thai roof','temple roof','temple','thai temple'],positions:['over','above']},
    guitar_note:{base:'guitar_silhouette',subject:'guitar',detail:'music note',details:['note','music note','musical note'],
      subjects:['guitar','acoustic guitar','guitar silhouette'],positions:['beside','next to']},
    book_pencil:{base:'books_open',subject:'open book',detail:'pencil',details:['pencil'],
      subjects:['book','books','open book'],positions:['across','on','resting on','beside','next to']}
  };
  if (openSubject) labels[openSubject] = 'Open place';
  const renderer = new RingSand(scene.live.size, scene.live.groove, scene.live.profile);
  function replaySand(start, parts, endIndex=Infinity) {
    const height = start.slice();
    for (const part of parts) {
      if (endIndex<=0) break;
      renderer.carve(height, endIndex<part.length-1 ? part.slice(0,endIndex+1) : part);
      endIndex-=part.length-1;
    }
    return height;
  }
  const custom = Object.create(null);
  // Only paths that survived Keep may be recalled by another request; custom also
  // holds transient sketch, lettering and photo previews.
  let committedIds = [], savedDrawings = [], keptInterests = {};
  function eligibleDrawingName(id, label) {
    if (!/^sketch-\d+$/.test(id) || typeof label !== 'string') return '';
    const name = drawingNameKey(label);
    return /^(?:guest sketch|guest drawing|photo drawing|portrait from photo|“.*”)$/u.test(name) ? '' : name;
  }
  function normalizeDrawingInterest(text) {
    if (typeof text !== 'string' || /[\u0000-\u001f\u007f-\u009f\ud800-\udfff]/u.test(text))
      throw Error('Enter interests as ordinary words separated by commas.');
    const phrases = text.split(',').map(phrase=>phrase.trim()).filter(Boolean);
    const value = phrases.join(', ');
    if (phrases.length > 8 || [...text].length > 120 || [...value].length > 120)
      throw Error('Use up to 8 interests and 120 characters in total.');
    return value;
  }
  function interestForInk(id, shapes, names, tags) {
    const name = eligibleDrawingName(id,names[id]);
    if (!name || !shapes[id]) return '';
    if (Object.hasOwn(tags,id)) return tags[id];
    // The same kept picture can have different local IDs on two phones.
    for (const other of Object.keys(tags)) {
      if (eligibleDrawingName(other,names[other]) === name && shapes[other] && sameInk(shapes[id],shapes[other]))
        return tags[other];
    }
    return '';
  }
  function drawingInterest(id) { return interestForInk(id,custom,labels,keptInterests); }
  function setDrawingInterest(state, id, text) {
    const name=eligibleDrawingName(id,state.labels[id]), path=state.custom[id];
    if (!name || !path) throw Error('Choose a named guest drawing to save interests.');
    const value=normalizeDrawingInterest(text), tags={...state.drawingInterests};
    for (const other of Object.keys(state.custom)) {
      if (eligibleDrawingName(other,state.labels[other])!==name || !sameInk(path,state.custom[other])) continue;
      if (value) tags[other]=value; else delete tags[other];
    }
    // An explicit empty map can clear the final tag. Older phones omit the field.
    state.drawingInterests=tags;
  }
  function restoreDrawings(state) {
    for (const id of Object.keys(custom)) { delete custom[id]; delete labels[id]; }
    Object.assign(custom,state?.custom); Object.assign(labels,state?.labels);
    committedIds = Object.keys(state?.custom || {});
    keptInterests = {};
    for (const [id,text] of Object.entries(state?.drawingInterests || {})) {
      if (Object.hasOwn(custom,id) && eligibleDrawingName(id,labels[id])) {
        const value=normalizeDrawingInterest(text);
        if (value) keptInterests[id]=value;
      }
    }
    savedDrawings = namedDrawings(committedIds,custom,labels).map(art=>({...art,interests:drawingInterest(art.id)}));
  }
  function namedDrawings(ids, shapes, names) {
    const seen = new Map(), drawings = [];
    for (const id of ids) {
      const path=shapes[id], name=eligibleDrawingName(id,names[id]);
      if (!path || !name) continue;
      const matches = seen.get(name) || [];
      if (matches.some(other => sameInk(other,path))) continue;
      matches.push(path); seen.set(name,matches);
      drawings.push({id,label:names[id].trim()});
    }
    return drawings;
  }
  function keptDrawings() { return savedDrawings; }
  let bed = Float32Array.from(atob(scene.live.bed), b => b.charCodeAt(0) / 170 - 1);
  const selected = {center:0, outer:0};
  const borders = scene.zones.outer.names, borderPicker = borders.length > 2;
  const guestBorderIndex=-1, guestBorderTitle='Guest drawings';
  const hasGuestBorder=scene.live.guestBorder===true;
  const guestMotifs=new Map();
  let listedBorderIds;
  const outer = scene.zones.outer;
  const borderRadius = (outer.transit.at(-1)[1] + outer.erase.reduce((low,p)=>Math.min(low,p[1]),1)) / 2;
  let borderEdited = false;
  if (borderPicker) {
    selected.borderGuest = '';
    borders.forEach((name,i) => $('borderDesign').add(new Option(name,String(i))));
    if (hasGuestBorder) $('borderDesign').add(new Option(guestBorderTitle,String(guestBorderIndex)));
  }
  let keptPortrait = '', portraitDraft = null, samplePhoto = null, photoRequest = 0, converting = false;
  let faceChoice = null, groupFaces = null, seatOrder = null, objectFrame = null;
  let seatPhotos = [], seatPhotoIndex = 0, editorClosed = false;
  let hasIsolatedSubject = false;
  let assignmentScan = null;
  const assignments = guestPhotoAssignments(main, () => editPhoto(true));
  const displayFaces = guestFacePicker(main, face => {
    if (groupGuestPhoto()) {
      if (typeof face === 'object' && assignmentScan) {
        assignments.frame(face);
        assignments.markSource(displayFaces, assignmentScan);
        editPhoto(true);
      }
      return;
    }
    if (separatePhotos()) {
      const seat = seatPhotos[seatPhotoIndex];
      if (!seat?.scan) return;
      const box = typeof face === 'number' ? seat.scan.detectedFaces[face] : face;
      if (box) {
        seat.face = {x:box.x,y:box.y,w:box.w};
        editSeats();
      }
      return;
    }
    faceChoice = face;
    $('portraitForm').requestSubmit();
  }, (faces,reframed) => {
    groupFaces = faces;
    if (seatOrder && reframed) {
      const {from,to} = reframed;
      seatOrder = seatOrder.map(b=>b.x===from.x && b.y===from.y && b.w===from.w ? to : b);
    }
    $('portraitForm').requestSubmit();
  }, frame => {
    objectFrame = frame;
    resetObjectBackground();
    $('portraitForm').requestSubmit();
  }, order => {
    seatOrder = order;
    viewingSeat = 0;
    $('portraitForm').requestSubmit($('portraitSubmit'));
  }, active => {
    $('keep').disabled = active;
    if (active) {
      viewingSeat = 0;
      showSeatView();
    }
  });
  let sourceUrl = '', sourceFile = null, enlarged = false;
  let guestFocus = -1, guestPhotoPanel = false, draftPhotoIds = [];
  const defaults = catalog?.defaults || [];
  let current = defaults.slice();
  const storageKey = scene.live.storageKey || 'oasis-ring-' + scene.layout + '-v1';
  const previousOpening = scene.live.previousOpening;
  const wideCenter = scene.live.wideCenter;
  function photoZone() {
    return wideCenter && $('portraitArea').value==='wide' ? wideCenter : scene.zones.center;
  }
  function centerRadius(center) { return center.transit.at(-1)[1]; }
  function visibleCenterRadius() {
    const wide = stage==='original' ? selected.widePortrait : planned?.route.centerMode==='widePortrait';
    return centerRadius(wide ? wideCenter : scene.zones.center);
  }
  const {radiusMM, groove, trackingMarginMM} = scene.live;
  const portraitTrackingGrooves = Number.isFinite(trackingMarginMM) ? trackingMarginMM / (groove * radiusMM) : undefined;
  // The width available for separate eyes and shadow lines depends on the ball and table.
  function supportsPhotoShadows() { return 2 * centerRadius(photoZone()) / groove >= 60; }
  const groupShadowOption = $('portraitStyle').querySelector('[value=shadows]');
  const soloShadowOption = $('soloStyle').querySelector('[value=shadow]');
  const zoneCount = Object.keys(scene.zones).length;

  main.querySelector('input[value=middle]').closest('label').hidden = !scene.zones.middle;
  let kept = false;
  let exampleOpening, exampleSetup;
  function restore(state) {
    state ??= exampleOpening;
    if (state && ((state.edition !== scene.live.edition && state.edition !== scene.live.previousEdition) ||
        ![0,1].includes(state.center) || !validSavedBorder(state) ||
        (state.borderGuest !== undefined && (typeof state.borderGuest !== 'string' || [...state.borderGuest].length > 48)) ||
        (state.widePortrait !== undefined && (state.widePortrait!==true || !wideCenter || !state.portrait)) ||
        (state.portraitSeats !== undefined && (!Number.isSafeInteger(state.portraitSeats) || state.portraitSeats < 2 ||
          state.portraitSeats > 32000 || !state.portrait)) ||
        state.bed.length !== scene.live.bed.length || !Array.isArray(state.ids) || state.ids.length !== defaults.length)) {
      throw Error('This saved drawing belongs to another layout.');
    }
    if (state && catalog) OasisRingPlanner.plan(catalog,state.ids,state.custom);
    const restored = atob(state?.bed || scene.live.bed);
    if (restored.length !== bed.length) throw Error('Incomplete saved drawing.');
    bed = Float32Array.from(restored, b => b.charCodeAt(0) / 170 - 1);
    selected.center = state?.center ?? 0; selected.outer = state?.outer ?? 0;
    if (state?.guestBorder) selected.guestBorder=state.guestBorder;
    else delete selected.guestBorder;
    if (scene.live.guestBorderSeat===true && state?.guestBorderGrain) selected.guestBorderGrain=state.guestBorderGrain;
    else delete selected.guestBorderGrain;
    selected.portraitSeats = state?.portraitSeats;
    if (state?.widePortrait) selected.widePortrait=true;
    else delete selected.widePortrait;
    $('portraitArea').value=state?.widePortrait ? 'wide' : 'center';
    if (borderPicker) selected.borderGuest = state?.borderGuest ?? '';
    keptPortrait = state?.portrait || '';
    current = state?.ids.slice() || defaults.slice();
    draftPhotoIds = [];
    restoreDrawings(state);
    book?.restore(state?.guestBook, current, id => id === openSubject || Object.hasOwn(catalog.subjects,id) || Object.hasOwn(custom,id));
    kept = !!state && state.starting !== true;
  }
  function snapshot(height, selections, portrait, drawings, roster, starting = false, shapes = custom, names = labels, history = committedIds, tags = keptInterests) {
    const bytes = new Uint8Array(height.length);
    for (let i = 0; i < bytes.length; i++)
      bytes[i] = Math.round((Math.min(.5,Math.max(-1,height[i])) + 1) * 170);
    let packed = '';
    for (let i=0; i<bytes.length; i+=8192) packed += String.fromCharCode(...bytes.subarray(i,i+8192));
    const needed = new Set([...(roster?.people.map(p=>p.subject) || []), ...drawings].filter(id=>Object.hasOwn(shapes,id)));
    const extra = [];
    let points = 0;
    // Give the roster every path it needs. The remaining space holds the most
    // recently displayed named pictures, oldest first in the saved object.
    for (const {id} of namedDrawings([...needed,...history.slice().reverse()],shapes,names)) {
      if (needed.has(id)) continue;
      if (extra.length >= 12 || extra.length + needed.size >= 256) break;
      if (points + shapes[id].length > 16000) continue;
      extra.push(id); points += shapes[id].length;
    }
    const ids = [...extra.reverse(),...needed];
    const fields = obj => Object.fromEntries(ids.map(id=>[id,obj[id]]));
    const interests = Object.fromEntries(ids.map(id=>[id,interestForInk(id,shapes,names,tags)]).filter(([,text])=>text));
    return {edition:scene.live.edition, bed:btoa(packed),
      ...selections, ...(borderPicker ? {borderGuest:selections.borderGuest ?? ''} : {}),
      portrait, ids:drawings, custom:fields(shapes), labels:fields(names), guestBook:roster?.saved(),
      ...(Object.keys(interests).length ? {drawingInterests:interests} : {}),
      starting:starting || undefined};
  }
  function remember(state, compactOnQuota = true) {
    if (familyBorder) return;
    const text = JSON.stringify(state);
    savedThisVisit.set(storageKey, text);
    try {
      // An explicit reset also takes precedence over a compatible older save.
      if (state || scene.live.legacyStorageKey || previousOpening) localStorage.setItem(storageKey,text);
      else localStorage.removeItem(storageKey);
      savedThisVisit.delete(storageKey);
    } catch (error) {
      if (!state || !compactOnQuota || error.name !== 'QuotaExceededError') return;
      // Keep the full library for this visit. If browser storage is nearly
      // full, still update the persistent sand and everyone’s last drawing.
      const needed = new Set([...state.ids,...(state.guestBook?.people || []).map(p=>p.subject)]);
      const compact = {...state, custom:{...state.custom}, labels:{...state.labels}};
      const extra = Object.keys(compact.custom).filter(id=>!needed.has(id));
      if (!extra.length) return;
      if (state.drawingInterests) compact.drawingInterests={...state.drawingInterests};
      for (const id of extra) {
        delete compact.custom[id]; delete compact.labels[id];
        if (compact.drawingInterests) delete compact.drawingInterests[id];
      }
      try { localStorage.setItem(storageKey,JSON.stringify(compact)); } catch { /* Session copy remains available. */ }
    }
  }
  function restorePrivate() {
    const oldEditions = previousOpening ? [previousOpening.edition,previousOpening.previousEdition] : [];
    // Start with the current key. A stored null is an explicit reset, including
    // on a phone that still has a copy under one of the older keys.
    const candidates = [[storageKey, [scene.live.edition,scene.live.previousEdition,...oldEditions]]];
    if (previousOpening) {
      candidates.push([previousOpening.storageKey,oldEditions]);
      candidates.push([previousOpening.legacyStorageKey,[previousOpening.previousEdition]]);
    }
    // The full historical manifest identifies the physical size on a shared
    // legacy key. A hash based only on the starting image cannot do that.
    candidates.push([scene.live.legacyStorageKey,[scene.live.previousEdition]]);
    for (const [key,editions] of candidates) {
      if (!key) continue;
      const text = savedThisVisit.get(key) ?? localStorage.getItem(key);
      if (text === null) continue;
      const state = JSON.parse(text);
      if (state === null) return;
      if (typeof state?.edition !== 'string' || !editions.includes(state.edition)) continue;
      const carried = {...state,edition:scene.live.edition};
      if (scene.live.guestBorderSeat!==true) delete carried.guestBorderGrain;
      restore(carried);
      // If a duplicate won't fit, its complete earlier copy remains available on reload.
      if (key !== storageKey || state.edition !== scene.live.edition) remember(carried, false);
      return;
    }
  }
  if (familyBorder) {
    const center=scene.zones.center;
    const {shadowMarks}=checkedPreparedPortrait(familyBorder,2*centerRadius(center)*radiusMM,groove*radiusMM);
    const route=OasisRingPlanner.shadowPhoto(center,shadowMarks,scene.live);
    exampleSetup=OasisRingPlanner.files(route.path,'center-portrait');
    // Use the same four cuts and saved-bed precision as Keep on a prepared portrait.
    exampleOpening=snapshot(replaySand(bed,route.segments),{center:0,outer:0},'Family portrait',defaults,book,true);
    restore(exampleOpening);
  } else if (!room) {
    try { restorePrivate(); } catch { /* Ignore an unreadable private save. */ }
  }
  let original = renderer.image(bed);
  let proposed = defaultSuggestion(), proposedPeople = null;
  let zone = 'center', stage = 'original', planned = null;
  let viewingSeat = 0, chairView = false;
  let urls = [], sketchNumber = 0, dirtyInput = false;
  let suggestionVersion = 0;
  const savedPicker = $('savedDrawing');
  let listedDrawings;
  let pairChoices = null;
  let offeredPhoto = null, requestedPhoto = null;
  let wideSuggestionVersion = null;
  const phraseEndpoint=room && document.querySelector('meta[name=oasis-phrase]')?.content;
  const portraitService=room && document.querySelector('meta[name=oasis-portrait]');
  const portraitEndpoint=portraitService?.content;
  const heicEndpoint=room && document.querySelector('meta[name=oasis-heic]')?.content;
  const acceptedPhotos=heicEndpoint ? 'image/*,.heic,.heif' : 'image/*';
  $('seatPhotoFile').accept=$('replaceSeatPhotoFile').accept=acceptedPhotos;
  const laptopJpegs=new WeakSet();
  let openingHeic;
  const groupEngraving=portraitService?.dataset.group==='1';
  const groupHair=groupEngraving && portraitService.dataset.groupLocks==='1';
  const traceNose=portraitService?.dataset.nose==='1';
  const traceBrows=portraitService?.dataset.brows==='1';
  const traceSmile=portraitService?.dataset.smile==='1';
  const traceEyes=portraitService?.dataset.eyes==='1';
  const rakeButton=$('portraitRake'), rakePrint=rakeButton && portraitService?.dataset.rakePrint==='1';
  const pairRake=rakePrint && portraitService.dataset.groupRake==='1';
  const cheekButton=$('portraitCheeks'), cheekPrint=cheekButton && portraitService?.dataset.cheekPrint==='1';
  const fullHair=portraitService?.dataset.longHair==='1';
  const flowingHair=portraitService?.dataset.flowingHair==='1';
  const hairWoodcut=portraitService?.dataset.woodcut==='1';
  const featureNames=new Intl.ListFormat('en-GB',{type:'conjunction'});
  const availableFeatures=featureNames.format(['hair',traceNose && 'nose',traceBrows && 'eyebrows',traceSmile && 'smile',traceEyes && 'eyes'].filter(Boolean));
  const photoTraceAction=traceSmile || traceEyes ? 'Trace facial details from the photo' : 'Trace '+availableFeatures+' from the photo';
  const paths = [];
  let stroke = null;
  const pad = $('sketchPad'), ink = pad.getContext('2d');
  const radio = (name, value) => main.querySelector(`input[name="${name}"][value="${value}"]`);
  const peopleBox = $('peopleBox');
  const guestForm = book && bindRingPeople(main, book, manifest, {
    labels, openSubject, ideasFor, edit:editingSuggestion, preview:previewGuests, readSketch, resetSketch, report
  });
  const rotation = book && bindRingRotation(main, book, catalog, {
    ideasFor, isKept: isKeptDrawing, sameDrawing,
    change(slot, art) {
      if (selected.widePortrait) return false;
      prepareArt(art);
      const next = current.slice();
      next[slot] = art.id;
      previewRing(next, null);
      return keepDrawing(false);
    },
    table: attached && {
      refresh: () => room.readPlayback(),
      ready: data => !selected.widePortrait && !room.changed && !room.writing && room.revision !== null && data?.revision === room.revision &&
        data.ready === true && data.state === 'idle' && data.queued === 0 && data.drawing === null && data.holdSeconds === 0,
      async change(slot,art) {
        if (selected.widePortrait) return false;
        // Keep the visitor's current zone and preview controls in place.
        prepareArt(art);
        const drawings=current.slice();
        drawings[slot]=art.id;
        const route=guestChange(drawings);
        const height=replaySand(bed,route.filePaths || route.segments), roster=book.copy();
        roster.keep(null,drawings);
        const state=snapshot(height,selected,keptPortrait,drawings,roster);
        const motion=roomMotion('middle',route);
        if (!await room.save(state,motion,true)) return false;
        applyGarden(state);
        return true;
      }
    },
    pendingEdit
  });

  function pendingEdit() {
    return stage !== 'original' || borderEdited || proposedPeople || paths.length || $('idea').value.trim() || portraitDraft ||
      converting || samplePhoto || $('portraitFile').files.length || $('photoCaption').value.trim() || (separatePhotos() && seatPhotos.length) || $('target').value ||
      (attached && main.contains(document.activeElement) && document.activeElement.matches('form input, form select, form textarea, canvas')) ||
      (peopleBox.open && ($('personName').value.trim() || $('personInterest').value.trim()));
  }

  function ideasFor(interest) {
    return GuestArt.interestIdeas(interest, manifest, keptDrawings());
  }
  function isKeptDrawing(id) {
    return keptDrawings().some(art => art.id === id);
  }
  function readyIdeas(person) {
    // The first preview can use any path already available in this garden.
    return ideasFor(GuestArt.guestInterest(person)).filter(art =>
      Object.hasOwn(catalog.subjects,art.id) || isKeptDrawing(art.id));
  }
  function defaultSuggestion() {
    if (!catalog) return [];
    const ids = current.slice();
    const open = ids.indexOf(openSubject);
    if (open >= 0) {
      const first = readyIdeas(book.active[open])[0];
      if (first) { ids[open] = first.id; return ids; }
    }
    if (!book.personalized) {
      const slot = book.active.findIndex(person=>GuestArt.normalize(person.name)==='alex');
      const books = preferred.books || 'books', guitar = preferred.guitar || 'guitar';
      ids[slot] = ids[slot] === guitar ? books : guitar;
      return ids;
    }
    for (const [i, person] of book.active.entries()) {
      const options = readyIdeas(person);
      const next = alternate(options, ids[i]);
      if (next) { ids[i] = next.id; break; }
    }
    return ids;
  }
  function alternate(options, currentId) {
    if (!options.length) return null;
    const index = options.findIndex(item => item.id === currentId);
    const next = options[(index + 1) % options.length];
    return next.id === currentId ? null : next;
  }
  function sameRing() { return current.every((id, i) => id === proposed[i]); }
  function people(ids, roster) { return ids.map((id,i) => roster[i].name + ' · ' + labels[id]).join(' / '); }
  function validSavedBorder(state) {
    if (state.guestBorderGrain!==undefined && (state.outer!==guestBorderIndex ||
        !['spiral','fluted'].includes(state.guestBorderGrain))) return false;
    if (state.outer!==guestBorderIndex) return Number.isInteger(state.outer) && state.outer>=0 &&
      state.outer<borders.length && state.guestBorder===undefined;
    const sources=state.guestBorder;
    return hasGuestBorder && Array.isArray(sources) && sources.length===3 && sources.some(Boolean) &&
      sources.every(art=>art===null || (art && typeof art.label==='string' && art.label.trim() && [...art.label].length<=240 &&
        Array.isArray(art.points) && art.points.length>=4 && art.points.length<=8000 &&
        art.points.every(p=>Array.isArray(p) && p.length===2 && p.every(Number.isFinite))));
  }
  function guestDrawingSource(place,id) {
    if (id===openSubject) return null;
    let points=custom[id];
    if (!points && catalog.pairMotifs?.[id]) {
      if (!guestMotifs.has(id)) guestMotifs.set(id,OasisRingPlanner.unpack(catalog.pairMotifs[id]));
      points=guestMotifs.get(id);
    }
    return {label:book.active[place].name+' · '+labels[id],points};
  }
  function guestBorderSources() { return current.map((id,i)=>guestDrawingSource(i,id)); }
  function featureRequestId() {
    if (zone!=='middle' || guestFocus<0 || dirtyInput || proposedPeople || peopleBox.open ||
        $('centerPhoto').open || selected.widePortrait) return;
    if (stage==='cleared' || (stage==='original' && planned)) return;
    const id=(stage==='redrawn' ? proposed : current)[guestFocus];
    if (id && id!==openSubject && (custom[id] || catalog.pairMotifs?.[id])) return id;
  }
  function showCenterGuestChoices() {
    $('featureRequest').hidden=!featureRequestId();
    const picker=$('featureGuest');
    const available=zone==='center' && !selected.widePortrait && !$('centerPhoto').open && catalog ?
      current.map((id,slot)=>({id,slot})).filter(({id})=>id!==openSubject && (custom[id] || catalog.pairMotifs?.[id])) : [];
    $('featureGuestField').hidden=!available.length;
    if (!available.length) return;
    const names=available.map(({id,slot})=>book.active[slot].name+' · '+labels[id]);
    if (picker.options.length!==names.length+1 || available.some(({slot},i)=>
      picker.options[i+1].text!==names[i] || picker.options[i+1].value!==String(slot))) {
      picker.replaceChildren(picker.options[0],...available.map(({slot},i)=>new Option(names[i],String(slot))));
    }
    const featured=planned?.route.featuredGuest;
    const suggestion=featured && current[featured.slot]!==featured.id;
    picker.options[0].text=suggestion ? featured.title+' (suggestion)' : 'Choose from the guest ring';
    picker.value=featured && !suggestion ? String(featured.slot) : '';
  }
  function canEditBorderPlace() {
    return zone==='outer' && scene.live.guestBorderSeat===true && selected.outer===guestBorderIndex &&
      nextDesign()===guestBorderIndex;
  }
  function editingBorderPlace() { return canEditBorderPlace() && $('editBorderPlace').checked; }
  function refreshBorderChoices() {
    const place=$('borderPlace'), names=book.active.map(guest=>guest.name);
    if (place.options.length!==names.length || names.some((name,i)=>place.options[i].text!==name)) {
      const previous=place.selectedOptions[0]?.text;
      place.replaceChildren(...names.map((name,i)=>new Option(name,String(i))));
      if (previous) place.selectedIndex=names.indexOf(previous);
    }
    if (listedBorderIds===committedIds) return;
    listedBorderIds=committedIds;
    const saved=$('borderSaved'), previous=saved.value;
    const groups=new Map();
    for (const id of committedIds) {
      const key=drawingNameKey(labels[id]);
      if (!groups.has(key)) groups.set(key,[]);
      groups.get(key).push(id);
    }
    saved.replaceChildren(new Option('Choose a saved drawing…',''));
    for (const ids of groups.values()) ids.forEach((id,i)=>{
      const suffix=ids.length>1 ? ' ('+(i+1)+' of '+ids.length+')' : '';
      saved.add(new Option(labels[id]+suffix,id));
    });
    saved.value=committedIds.includes(previous) ? previous : '';
    saved.hidden=$('borderSavedLabel').hidden=!committedIds.length;
    const titles=new Set([...Object.values(catalog.subjects),...committedIds.map(id=>labels[id])]);
    $('borderSubjects').replaceChildren(...[...titles].map(title=>new Option(title,title)));
  }
  function savedBorderSubject(text) {
    const subject=requestSubject(text), explicit=/^saved\s+/iu.test(subject);
    const keys=explicit ? [drawingNameKey(subject.replace(/^saved\s+/iu,''))] :
      [...new Set([drawingNameKey(text),drawingNameKey(subject)])];
    for (const key of keys) {
      const matches=committedIds.filter(id=>drawingNameKey(labels[id])===key);
      if (!matches.length) continue;
      if (!explicit && Object.entries(catalog.subjects).some(([id,label])=>drawingNameKey(label)===key || drawingNameKey(id)===key)) continue;
      if (matches.length>1) throw Error('Choose a version of “'+labels[matches[0]]+'” from the saved drawings.');
      return matches[0];
    }
    return null;
  }
  function requestedBorderSubject(place) {
    const chosen=$('borderSaved').value;
    if (chosen && committedIds.includes(chosen)) return chosen;
    const text=$('borderSubject').value.trim(), saved=savedBorderSubject(text);
    if (saved) return saved;  // “A gift for Alex” can itself be a kept title.
    const req=GuestArt.splitRequest(text,book.active);
    if (req.recipient && req.guest!==book.active[place]) throw Error('Choose the same guest in the border place and the request.');
    if (req.from) throw Error('Name the new drawing for this border place.');
    const addressed=req.recipient && savedBorderSubject(req.to);
    if (addressed) return addressed;
    const subject=requestSubject(req.to);
    const stock=/^saved\s+/iu.test(subject) ? null : resolve(subject);
    const stockName=stock && [stock.id,stock.label].some(name=>drawingNameKey(name)===drawingNameKey(subject));
    if (stock && (Object.hasOwn(catalog.subjects,stock.id) || committedIds.includes(stock.id)) &&
        (stockName || stock.singleSubject || (!relationIn(subject,stock) && !GuestArt.separatedSubjects(subject,manifest)))) return stock.id;
    throw Error('Choose a known subject or a drawing already saved in this garden.');
  }
  function sameBorderDrawing(art,kept) {
    return art && kept ? art.label===kept.label && art.points && sameInk(art.points,kept.points) : art===kept;
  }
  function sameGuestBorder(sources,frozen) {
    return sources.every((art,i)=>sameBorderDrawing(art,frozen[i]));
  }
  function refreshBorderPlace(sources) {
    if (!sources || !canEditBorderPlace() || $('borderGuest').value.trim()!==selected.borderGuest) return -1;
    const changed=sources.map((art,i)=>sameBorderDrawing(art,selected.guestBorder[i]) ? -1 : i).filter(i=>i>=0);
    // A saved single-seat move requires an actual drawing. The full border
    // route also handles a newly emptied seat, multiple edits, and renaming.
    return changed.length===1 && sources[changed[0]]?.points ? changed[0] : -1;
  }
  function borderIsCurrent(index,sources) {
    return index===selected.outer && (index!==guestBorderIndex || sameGuestBorder(sources,selected.guestBorder));
  }
  function resetBorderForm() {
    if (!borderPicker) return;
    // Retain the original one-click wheat/waves comparison for unattributed layouts.
    const opening = familyBorder && selected.outer===0 && !selected.borderGuest;
    const target = opening ? 2 : !selected.borderGuest && [0,1].includes(selected.outer) ? 1 - selected.outer : selected.outer;
    $('borderDesign').value = String(target);
    $('borderOrder').value = 'progressive';
    $('borderGuest').value = opening ? 'Lek' : selected.borderGuest;
    $('editBorderPlace').checked=false; $('borderSubject').value=''; $('borderSaved').value='';
    borderEdited = !!opening;
  }
  function nextDesign() {
    if (zone === 'outer' && borderPicker) return Number($('borderDesign').value);
    return zone === 'center' && keptPortrait ? 0 : 1 - selected[zone];
  }
  function borderNameOnly() {
    return zone === 'outer' && borderPicker && !editingBorderPlace() && $('borderGuest').value.trim() !== selected.borderGuest &&
      borderIsCurrent(nextDesign(),nextDesign()===guestBorderIndex ? guestBorderSources() : null);
  }
  function showSeatView() {
    const display = $('sand').closest('.sand-display');
    const canTilt = Number.isFinite(radiusMM) && radiusMM > 0 && (zone==='center' || !enlarged);
    const tilted = chairView && canTilt;
    const portraitSeats = zone==='center' && stage!=='original' ? portraitDraft?.seats : selected.portraitSeats;
    const arranged = (zone==='center' || (tilted && zone==='outer')) && portraitSeats;
    const places = tilted && !arranged ? catalog?.geometry.angles : null;
    const seats = arranged || places?.length || (tilted ? 2 : 0);
    $('viewControls').hidden = !canTilt && !seats;
    $('chairView').hidden = !canTilt;
    $('chairView').setAttribute('aria-pressed', String(tilted));
    $('chairView').textContent = tilted ? 'View from above' : 'View from a chair';
    $('chairNote').hidden = !tilted;
    $('seatViews').hidden = seats < 2;
    viewingSeat = seats ? viewingSeat % seats : 0;
    // Rotate the drawing in its own plane before projecting the entire bowl.
    const degrees = places?.length ? 90 + places[viewingSeat] * 180/Math.PI : seats ? -360*viewingSeat/seats : 0;
    $('sand').style.rotate = degrees ? degrees+'deg' : '';
    const guests = (zone==='middle' && stage!=='original' && proposedPeople) || book?.active;
    if (seats) $('seatNumber').textContent = arranged ? 'Seat '+(viewingSeat+1)+' of '+seats :
      places?.length ? (guests[viewingSeat]?.name || 'Guest')+'’s chair' : viewingSeat ? 'Opposite side' : 'Near side';
    display.classList.toggle('from-chair', tilted);
    if (tilted) {
      const height = 560, distance = radiusMM + 260, sightline = Math.hypot(height,distance);
      const visibleRadius = enlarged ? radiusMM * visibleCenterRadius() / .96 : radiusMM;
      // Perspective divides each point by 1 - k*y, where y is the fraction of the radius toward the viewer.
      // The projected disc's bounding box is centered a little below the projected table center.
      const k = distance * visibleRadius / (sightline*sightline), fit = Math.sqrt(1 - k*k);
      const aspect = height / (sightline*fit);
      display.style.setProperty('--chair-aspect', aspect);
      display.style.setProperty('--chair-fit', fit);
      display.style.setProperty('--chair-top', (-50*(1 + aspect*k))+'%');
      display.style.setProperty('--chair-focal', (50*sightline/visibleRadius)+'cqw');
      display.style.setProperty('--chair-tilt', Math.atan2(distance,height)+'rad');
    }
  }
  function guestChange(drawings) {
    if (selected.widePortrait) throw Error('Bring back the guest places before changing a guest drawing.');
    return OasisRingPlanner.planChange(catalog,current,drawings,custom);
  }
  function plan() {
    if (zone === 'middle') return guestChange(proposed);
    if (zone === 'center' && portraitDraft) return portraitDraft.route;
    if (zone === 'center' && selected.widePortrait) throw Error('Preview a new portrait or bring back the guest places.');
    const z = scene.zones[zone];
    if (zone==='outer' && nextDesign()===guestBorderIndex) {
      const manual=editingBorderPlace(), currentSources=manual ? null : guestBorderSources();
      const order=scene.live.guestBorderProgressive===true ? $('borderOrder').value : 'whole';
      const place=manual ? $('borderPlace').selectedIndex : order==='progressive' ? refreshBorderPlace(currentSources) : -1;
      if (manual || place>=0) {
        if (place<0) throw Error('Choose a guest on the border.');
        const subject=manual ? requestedBorderSubject(place) : current[place];
        const art=guestDrawingSource(place,subject), sources=selected.guestBorder.slice();
        if (!art?.points) throw Error('Choose a drawing with a saved outline.');
        sources[place]={label:art.label,points:art.points.map(p=>p.slice())};
        if (sameGuestBorder(sources,selected.guestBorder)) throw Error('That drawing is already in this border place.');
        const grain=selected.guestBorderGrain ?? GuestBorderGrain.read(scene,bed);
        const route=GuestKeepsakeBorder.planSeat(scene,place,art.points,grain);
        if (!manual) {
          const {first,last}=route.placements[place];
          const ink=OasisRingPlanner.travelDistances(route.path.slice(first,last+1));
          route.borderDrawingHalfway=first+OasisRingPlanner.halfIndex(ink);
        }
        const guestBorderSeat={place,subject};
        if (grain==='spiral') guestBorderSeat.grain=grain;
        return {...route,guestBorder:sources,guestBorderSeat};
      }
      const sources=currentSources.map(art=>art && {label:art.label,points:art.points.map(point=>point.slice())});
      const route=GuestKeepsakeBorder.plan(scene,sources.map(art=>art?.points ?? null),order);
      return {...route,guestBorder:sources,...(order==='progressive' ? {guestBorderOrder:order} : {})};
    }
    if (zone==='outer' && z.reveal?.[nextDesign()] && $('borderOrder').value==='progressive') {
      return OasisRingPlanner.borderReveal(z,nextDesign());
    }
    const segments = [z.transit, z.erase, z.drawings[nextDesign()], z.transit.slice().reverse()];
    return {segments, path:OasisRingPlanner.join(segments)};
  }
  function hideDownloads() {
    urls.forEach(url => URL.revokeObjectURL(url));
    urls = [];
    $('downloads').open = false;
    $('downloads').hidden = true;
    $('downloads').querySelector('div').replaceChildren();
  }
  function borderProgress() {
    if (stage!=='cleared' || !planned) return null;
    if (planned.route.firstOrnament) {
      const first=planned.route.firstOrnament, halfway=(planned.momentIndex ?? (familyBorder ? 0 : 1))===1;
      return {first,halfway,endIndex:halfway ? planned.route.halfwayIndex : first.endIndex};
    }
    if (planned.route.guestBorderOrder!=='progressive') return null;
    const route=planned.route, first=route.moments[0], halfway=planned.momentIndex===1;
    const endIndex=halfway ? route.halfwayIndex : first.endIndex;
    return {halfway,first,endIndex,finished:route.moments.filter(m=>m.endIndex<=endIndex)};
  }
  function showFraming() {
    const middle = zone==='middle', before = stage==='original';
    const canZoom = zone==='center' && !!(portraitDraft || keptPortrait);
    const progressPlace = stage==='cleared' ? planned?.route.moments?.[planned.momentIndex]?.place : undefined;
    const focus = progressPlace ?? guestFocus;
    const guestZoom = middle && focus >= 0 && !dirtyInput && !peopleBox.open;
    const borderZoom = zone==='outer' && borderPicker;
    if (!canZoom && !guestZoom && !borderZoom) enlarged=false;
    $('sand').closest('.bowl').classList.toggle('border-detail',borderZoom && enlarged);
    $('zoom').hidden=!canZoom; $('zoom').textContent=enlarged?'Show whole table':'Enlarge center';
    $('zoom').setAttribute('aria-pressed',String(enlarged));
    $('sand').style.transform=enlarged ? 'scale('+(.96/visibleCenterRadius())+')' : '';
    showSeatView();
    $('guestZoom').hidden = !(guestZoom || borderZoom);
    if (guestZoom || borderZoom) {
      const person = guestZoom && ((!before && proposedPeople) || book.active)[focus];
      const open = guestZoom && (before ? current : proposed)[focus]===openSubject;
      $('guestZoom').textContent = enlarged ? 'Show whole table' : borderZoom ? 'Enlarge border' :
        'Enlarge '+person.name+(open ? '’s place' : '’s drawing');
      $('guestZoom').setAttribute('aria-pressed',String(enlarged));
      if (enlarged && borderZoom) {
        const border = before ? selected.outer : nextDesign();
        const count = outer.reveal?.[border]?.finished.length || 10;
        const sources=before ? selected.guestBorder : planned?.route.guestBorder || selected.guestBorder;
        const progress=borderProgress();
        const place=editingBorderPlace() ? $('borderPlace').selectedIndex :
          progress?.finished ? (progress.finished.at(-1) || progress.first).place :
          border===guestBorderIndex ? sources?.findIndex(Boolean) : -1;
        const angle=place>=0 ? catalog.geometry.angles[place] : -Math.PI/2 + Math.PI/count;
        const view=place>=0 ? 'rotate('+(angle+Math.PI/2)+'rad) ' : '';
        const zoom=place>=0 ? 3.6 : 2.6, x=borderRadius*Math.cos(angle), y=borderRadius*Math.sin(angle);
        $('sand').style.transform = view+'scale('+zoom+') translate('+(-50*x)+'%,'+(50*y)+'%)';
      } else if (enlarged) {
        const {center,scale,angles} = catalog.geometry, angle = angles[focus];
        const x = -50 * center * Math.cos(angle), y = 50 * center * Math.sin(angle);
        const view = catalog.geometry.faceEdge ? 'rotate('+(angle+Math.PI/2)+'rad) ' : '';
        $('sand').style.transform = view+'scale(' + (.68/scale) + ') translate(' + x + '%,' + y + '%)';
      }
    }
  }
  function show() {
    showHeicOption();
    const middle = zone === 'middle';
    showCenterGuestChoices();
    radio('zone','middle').disabled=!!selected.widePortrait;
    const restoring=planned?.route.centerMode==='restoreGuests';
    const needsWideAction=zone==='center' && selected.widePortrait && !portraitDraft && !restoring;
    const guestPhoto = middle && photoPlaces && $('centerPhoto').open;
    const pendingPhoto = guestPhoto ? converting || !planned?.route.placePhoto :
      needsWideAction || (zone === 'center' && $('centerPhoto').open && !portraitDraft && !restoring);
    const heading = familyBorder ? 'Family portrait · simulated sand' :
      attached ? 'Garden preview · includes queued drawings' : room ? 'Shared garden preview' : 'Simulated sand';
    const photoArea=restoring ? scene.zones.center : photoZone();
    const inches=2*centerRadius(photoArea)*radiusMM/25.4;
    const wideMixer=wideCenter?.standMixer && (stage==='original' ? keptPortrait : portraitDraft?.title)===wideCenter.standMixer.label;
    main.querySelector('header p').textContent = heading + (zone === 'center' ? ' · ' + inches.toFixed(1) + (photoArea===wideCenter && !wideMixer ? '-inch portrait' : '-inch center') :
      middle ? ' · three guest places'+(catalog.geometry.faceEdge ? ' · drawings face the nearest viewer' : '') : '');
    $('borderForm').hidden = zone !== 'outer' || !borderPicker;
    const choosingBorder=zone==='outer' && borderPicker;
    const seatEdit=editingBorderPlace();
    $('borderPlaceMode').hidden=!canEditBorderPlace();
    $('borderPlaceForm').hidden=!seatEdit;
    $('borderGuest').hidden=$('borderGuestLabel').hidden=seatEdit;
    if (seatEdit) {
      refreshBorderChoices();
      const slot=$('borderPlace').selectedIndex, art=selected.guestBorder[slot];
      $('currentBorderPlace').textContent=slot<0 ? 'Choose a guest in the current garden.' :
        art ? 'Currently showing '+art.label+'.' : 'This part of the border is open.';
    }
    $('borderPreview').textContent=seatEdit ? 'Preview border drawing' : 'Preview border';
    const missingSeat=seatEdit && ($('borderPlace').selectedIndex<0 || !($('borderSubject').value.trim() || $('borderSaved').value));
    const sources=choosingBorder && !seatEdit && nextDesign()===guestBorderIndex ? guestBorderSources() : null;
    const refreshPlace=refreshBorderPlace(sources);
    $('borderOrder').options[0].textContent=refreshPlace>=0 ? 'Update only '+book.active[refreshPlace].name+'’s drawing' :
      'Draw each section as it clears';
    const refreshOne=refreshPlace>=0 && $('borderOrder').value==='progressive';
    const singleBorder=seatEdit || refreshOne;
    const missingBorder=sources && !sources.every(art=>!art || art.points);
    const emptyBorder=sources && !sources.some(Boolean);
    $('guestBorderGuide').hidden=!sources;
    if (sources) $('guestBorderGuide').textContent=missingBorder ? 'A guest drawing has no outline in this garden.' :
      emptyBorder ? 'Keep at least one guest drawing before making this border.' :
      'The border keeps a copy of each guest drawing, even after their place changes.'+
      (sources.includes(null) ? ' Open places leave their part of the border clear.' : '');
    const sameBorder = choosingBorder && !seatEdit && borderIsCurrent(nextDesign(),sources);
    const canReveal = choosingBorder && !sameBorder && (outer.reveal?.[nextDesign()] ||
      (sources && !missingBorder && !emptyBorder && scene.live.guestBorderProgressive===true));
    const progressiveBorder = canReveal && !singleBorder && $('borderOrder').value === 'progressive';
    $('borderOrderField').hidden = !canReveal;
    const nameOnly = borderNameOnly(), sameArt = (middle && sameRing()) || sameBorder;
    $('borderPreview').disabled = (sameBorder && !nameOnly) || missingBorder || emptyBorder || missingSeat;
    radio('stage','redrawn').disabled = (middle && (dirtyInput || (sameArt && !proposedPeople))) ||
      (sameBorder && !nameOnly) || pendingPhoto || missingBorder || emptyBorder || missingSeat;
    radio('stage','cleared').disabled = pendingPhoto || (middle && dirtyInput) || sameArt || missingBorder || emptyBorder || missingSeat;
    if (radio('stage',stage).disabled) {
      stage='original'; radio('stage',stage).checked=true;
    }
    const before = stage === 'original';
    if (!before && !sameArt && !planned) {
      try { planned = {route:plan()}; }
      catch (error) {
        stage='original'; radio('stage',stage).checked=true;
        show(); report(error); return;
      }
    }
    const localRoute = planned?.localRoute || planned?.route;
    const wholeMiddle = middle && !!planned?.localRoute;
    const localParts = localRoute?.parts || (Number.isInteger(localRoute?.place) ? [localRoute] : []);
    const chooseRedraw = middle && !dirtyInput && localParts.length && localParts.every(({place,fill,addFrom})=>
      !fill && !addFrom && current[place]!==openSubject && proposed[place]!==openSubject && proposed[place]!==current[place]);
    const redraw = $('guestRedraw');
    $('guestRedrawField').hidden = !chooseRedraw;
    redraw.options[0].textContent = localParts.length>1 ? 'One guest’s place at a time' : 'Only this guest’s place';
    redraw.value = wholeMiddle ? 'ring' : 'place';
    const localPlace = middle && Number.isInteger(planned?.route.place);
    const visits = middle ? planned?.route.parts : null;
    const directFills = visits?.every(part=>part.fill);
    const singleMoments=stage==='cleared' && localPlace && planned.route.progressMoments;
    const moments = singleMoments || (stage==='cleared' && visits && planned.route.moments);
    const borderMoment=borderProgress();
    $('guestMoments').hidden = !moments && !borderMoment;
    $('momentLabel').textContent=borderMoment ? 'Show a moment in the border' : 'Show a moment in the drawing';
    if (borderMoment && planned.momentIndex===undefined) {
      const label=planned.route.firstOrnament ?
        ({'Thai roof peaks':'Thai roof','Lotus buds':'Lotus bud','Autumn leaves':'Autumn leaf'}[borders[nextDesign()]] || 'Border section') :
        planned.route.guestBorder[borderMoment.first.place].label;
      $('guestMoment').replaceChildren(new Option('First finished · '+label,'first'),new Option('Halfway through the ball’s travel','halfway'));
      planned.momentIndex=borderMoment.halfway ? 1 : 0;
      $('guestMoment').selectedIndex=planned.momentIndex;
    } else if (singleMoments && planned.momentIndex===undefined) {
      $('guestMoment').replaceChildren(...singleMoments.map(({label},i)=>new Option(label,String(i))));
      planned.momentIndex=singleMoments.length-1;
      $('guestMoment').selectedIndex=planned.momentIndex;
    } else if (moments && planned.momentIndex===undefined) {
      const guests=proposedPeople || book.active;
      const options=moments.map(({place,forming},i)=>{
        const name=guests[place].name;
        const detail=visits.find(part=>part.place===place)?.addFrom && decorations[proposed[place]];
        const label=detail ? name+'’s '+detail.detail+(forming ? ' takes shape' : ' is finished') :
          forming ? name+'’s drawing takes shape' : proposed[place]===openSubject
          ? name+'’s place is clear' : name+'’s drawing is finished';
        return new Option(label,String(i));
      });
      $('guestMoment').replaceChildren(...options);
      planned.momentIndex=moments.findIndex(moment=>!moment.forming);
      $('guestMoment').selectedIndex=planned.momentIndex;
    }
    const moment=moments && moments[planned.momentIndex];
    peopleBox.hidden = !middle || guestPhoto;
    $('changingGarden').hidden = !middle || guestPhoto;
    $('guestEditor').hidden = !middle || peopleBox.open || guestPhoto;
    if (middle) {
      refreshSavedPicker(); refreshAdditions();
      const [,first,second]=book.active;
      $('interestMixExample').textContent='Try “Combine '+first.name+' and '+second.name+'’s interests for '+first.name+'”.';
    }
    showSuggestionSources();
    $('openGuestPlaces').hidden = !openSubject || current.every(id=>id===openSubject);
    $('fillGuestPlaces').hidden = !openSubject || !current.includes(openSubject);
    const photoOpen = zone === 'center' && $('centerPhoto').open;
    $('portraitAreaField').hidden=!photoOpen || !wideCenter;
    $('portraitArea').options[0].disabled=!!selected.widePortrait;
    $('portraitAreaHint').hidden=$('portraitArea').value!=='wide';
    $('restoreGuests').hidden=zone!=='center' || !selected.widePortrait;
    groupShadowOption.hidden=groupShadowOption.disabled=!supportsPhotoShadows();
    soloShadowOption.hidden=soloShadowOption.disabled=!supportsPhotoShadows();
    const separate = photoOpen && separatePhotos();
    const prepared = photoOpen && $('portraitMode').value==='prepared';
    const groupPhoto = photoOpen && ($('portraitMode').value === 'group' || separate);
    const seatedStyle = separate || (groupPhoto && $('portraitStyle').value === 'seats');
    const namesAvailable=groupPhoto ? !seatedStyle && $('portraitStyle').value!=='shadows' :
      !supportsPhotoShadows() || $('soloStyle').value!=='shadow';
    $('photoCaptionField').hidden=!photoOpen || prepared;
    $('photoCaption').disabled=!namesAvailable || prepared;
    $('photoCaptionHint').hidden=namesAvailable;
    $('seatPhotos').hidden = !separate;
    $('portraitFile').hidden = $('portraitFileLabel').hidden = separate;
    $('portraitFileLabel').textContent=prepared ? 'Prepared portrait from your device' : 'Photo from your device';
    $('portraitFile').accept=prepared ? '.oasisportrait,application/json' : acceptedPhotos;
    $('portraitStyle').hidden = main.querySelector('label[for=portraitStyle]').hidden = separate;
    const source = $('portraitSource');
    const groupPlaces = guestPhoto && groupGuestPhoto();
    if (separate && source.parentElement !== $('seatPhotos')) $('seatPhotos').append(source);
    if (groupPlaces && source.nextElementSibling !== $('groupGuestAssignments')) $('groupGuestAssignments').before(source);
    if (!separate && !groupPlaces && source.previousElementSibling !== $('arrangeSeats')) $('arrangeSeats').after(source);
    if (separate) $('portraitSubmit').disabled = converting || !seatsReady();
    $('seatedRevealField').hidden = !seatedStyle;
    $('seatedRevealNotice').hidden = !seatedStyle || !$('seatedReveal').checked || converting ||
      !portraitDraft || !!portraitDraft.route.seatedReveal;
    const centerToPlace = photoOpen && !selected.widePortrait && !groupPhoto && !converting && portraitDraft?.hasFace && photoPlaces;
    if (guestPhoto || centerToPlace) refreshPhotoPlaces();
    $('portraitPlaceField').hidden = groupPlaces || (!guestPhoto && !centerToPlace);
    if (guestPhoto && $('portraitForm').firstElementChild!==$('portraitPlaceField')) $('portraitForm').prepend($('portraitPlaceField'));
    if (!guestPhoto && $('portraitStatus').nextElementSibling!==$('portraitPlaceField')) $('portraitStatus').after($('portraitPlaceField'));
    $('previewPlacePortrait').hidden = !centerToPlace;
    $('portraitPlaceLabel').textContent = guestPhoto ? 'Whose place?' : 'Draw this face in a guest’s place';
    const objectPhoto = guestPhoto && $('guestPhotoKind').value === 'object';
    $('guestPhotoKindField').hidden = !guestPhoto;
    const groupOption = $('guestPhotoKind').querySelector('[value=groupPlaces]');
    groupOption.hidden = groupOption.disabled = !catalog?.places || catalog.places.filter(Boolean).length < 2;
    $('groupGuestAssignments').hidden = !groupPlaces || !assignmentScan;
    if (groupPlaces) {
      assignments.setGuests(book.active, catalog.places);
      const problem = assignments.check();
      $('groupGuestGuide').textContent = problem;
      $('groupGuestGuide').hidden = !problem;
      $('portraitSubmit').disabled = !assignmentScan || converting || !!problem || $('sourceFrame').classList.contains('framing');
    }
    $('objectNameField').hidden = !objectPhoto;
    const nameField=$('portraitNameField');
    if (guestPhoto && nameField.previousElementSibling!==$('guestPhotoKindField')) $('guestPhotoKindField').after(nameField);
    if (!guestPhoto && nameField.parentElement!==$('portraitPlaceField')) $('previewPlacePortrait').before(nameField);
    nameField.hidden = !(centerToPlace || (guestPhoto && !objectPhoto && !groupPlaces));
    const frameField=$('guestPortraitFrameField');
    if (frameField.previousElementSibling!==nameField) nameField.after(frameField);
    frameField.hidden = nameField.hidden && !groupPlaces;
    const backgroundChoice = objectPhoto && hasIsolatedSubject;
    $('objectBackgroundField').hidden = !backgroundChoice;
    $('photoExamples').hidden = objectPhoto || separate || prepared || groupPlaces || !hasPhotoExamples;
    $('portraitMode').hidden = guestPhoto;
    $('portraitSubmit').textContent = groupPlaces ? 'Preview portraits in the guest places' :
      guestPhoto ? 'Preview in '+book.active[Number($('portraitPlace').value)].name+'’s place' :
      separate ? 'Preview seated portraits' : prepared ? 'Preview portrait' : 'Preview photo';
    $('photoSummary').textContent = middle ? 'Draw from a guest photo' : 'Use a guest photo';
    const soloPhoto = photoOpen && !groupPhoto && !prepared;
    const widePhoto = scene.layout==='portrait' || photoZone()===wideCenter;
    const groupTrace = groupEngraving && groupPhoto && !!portraitDraft?.selectedFaces;
    const canTrace = portraitEndpoint && widePhoto && !!$('portraitFile').files.length &&
      (groupTrace || soloPhoto && portraitDraft?.hasFace && portraitDraft.route.interleaved);
    $('portraitHairField').hidden=!canTrace;
    const offerTrace=(traceNose || traceBrows || traceSmile || traceEyes) && soloPhoto && !portraitDraft && !!$('portraitFile').files.length &&
      widePhoto && supportsPhotoShadows() &&
      ['auto','shadow'].includes($('soloStyle').value) && ($('photoCaption').disabled || !$('photoCaption').value.trim());
    $('photoTraceSubmit').hidden=$('photoTraceHint').hidden=!offerTrace;
    $('photoTraceSubmit').disabled=converting;
    if (offerTrace) {
      $('portraitSubmit').textContent='Preview on this phone';
      $('photoTraceHint').textContent='The garden laptop traces the '+availableFeatures+', then discards the photo.'+
        (hairWoodcut ? ' You can compare a woodcut if the hair has room for it.' : '');
    }
    if (canTrace) {
      const trace=portraitDraft.trace;
      $('portraitHair').disabled=converting || !!trace?.unchanged;
      const firstAction=groupTrace ? 'Preview group engraving on garden laptop' : photoTraceAction;
      const alternate=groupTrace ? 'Show group engraving' : 'Show traced '+trace?.features;
      $('portraitHair').textContent=trace?.measured
        ? (portraitDraft.route!==trace.original ? 'Show first drawing' : alternate) : firstAction;
      const offerGroupHair=groupTrace && groupHair && !!trace?.measured;
      $('portraitLongHair').hidden=!trace?.longHair && !offerGroupHair;
      $('portraitLongHair').disabled=converting;
      $('portraitLongHair').textContent=offerGroupHair ? (trace.longHair ? (portraitDraft.route===trace.longHair ?
        'Show group engraving' : 'Show two-sided long hair') : 'Trace long hair on both sides') :
        trace?.longHair && portraitDraft.route===trace.longHair ? 'Show close-up' : 'Show full hair';
      $('portraitFlowing').hidden=!trace?.flowingHair;
      $('portraitFlowing').textContent=trace?.flowingHair && portraitDraft.route===trace.flowingHair ? 'Show open engraving' : 'Follow the hair direction';
      if (cheekButton) {
        cheekButton.hidden=!cheekPrint || !soloPhoto || photoZone()!==wideCenter ||
          Math.abs(2*centerRadius(wideCenter)*radiusMM-632.8)>.01 || Math.abs(groove*radiusMM-7)>.001 ||
          !!trace?.cheeksUnavailable;
        cheekButton.disabled=converting;
        cheekButton.textContent=trace?.cheeks && portraitDraft.route===trace.cheeks ? 'Show open engraving' : 'Engrave cheek shadows';
      }
      if (rakeButton) {
        const fitsPair=pairRake && groupTrace && portraitDraft.selectedFaces.length===2 &&
          photoZone()===wideCenter && Math.abs(2*centerRadius(wideCenter)*radiusMM-632.8)<.01 &&
          Math.abs(groove*radiusMM-7)<.001;
        rakeButton.hidden=!trace?.rake && !(fitsPair && trace?.measured && !trace.rakeUnavailable);
        rakeButton.disabled=converting;
        rakeButton.textContent=trace?.rake && portraitDraft.route===trace.rake ? 'Show open engraving' : 'Shade with the rake';
      }
      $('portraitWoodcut').hidden=!trace?.woodcut;
      $('portraitWoodcut').textContent=trace?.woodcut && portraitDraft.route===trace.woodcut ? 'Show open engraving' : 'Show woodcut hair';
      $('portraitHairNote').textContent=trace?.message || (groupTrace
        ? 'Sends this photo to the garden laptop to engrave the '+portraitDraft.selectedFaces.length+' selected faces. It then discards the photo.'
        : 'Sends this photo to the garden laptop. It discards the photo after tracing.');
      if (offerGroupHair && !trace.longHair && !converting) {
        $('portraitHairNote').textContent+=rakeButton && !rakeButton.hidden && !trace.rake
          ? ' Preparing another group style sends the photo to the garden laptop again.'
          : ' Tracing long hair sends the photo to the garden laptop again.';
      }
    }
    const progressivePortrait = zone === 'center' && !!portraitDraft?.route.interleaved;
    const fill = localPlace && planned.route.fill;
    const addition = localPlace && planned.route.addFrom && decorations[proposed[planned.route.place]];
    const onlyAdditions = visits?.every(part=>part.addFrom);
    const earlyGuest = localPlace && !!(planned.route.earlyFrom || planned.route.customReveal);
    const opening = middle && openSubject && current.some((id,i)=>id!==openSubject && proposed[i]===openSubject);
    const halfway = progressivePortrait || progressiveBorder || fill;
    $('middleStageLabel').textContent = visits || earlyGuest || addition || refreshOne ||
      (progressiveBorder && (sources || familyBorder || (borderMoment && !borderMoment.halfway))) ? 'In progress' : halfway ? 'Halfway' : 'Cleared';
    $('lastStageLabel').textContent = addition || onlyAdditions ? 'Added' : fill || directFills ? 'Drawn' : opening ? 'Open' : 'Redrawn';
    const besideDrawing = $('shownComposition');
    const guestComparison = localPlace || visits || wholeMiddle;
    besideDrawing.hidden = !seatEdit && !canReveal && !guestComparison && !backgroundChoice && !(portraitDraft && photoOpen);
    for (const [control,visible] of [[$('groupStyles'),groupPhoto],[$('soloStyles'),soloPhoto]]) {
      if (visible && portraitDraft) {
        if (control.parentElement !== besideDrawing) besideDrawing.prepend(control);
      } else if (control.parentElement !== $('portraitForm')) $('portraitMode').after(control);
      control.hidden = !visible;
    }
    const compare = $('compareStages');
    const compareHere = seatEdit || progressivePortrait || canReveal || guestComparison;
    if (compareHere && compare.parentElement !== besideDrawing) besideDrawing.append(compare);
    if (!compareHere && compare.parentElement === besideDrawing) $('centerPhoto').after(compare);
    const captionElement = main.querySelector('.caption');
    const nearDrawing=singleBorder || guestComparison || (sources && progressiveBorder);
    if (nearDrawing && captionElement.parentElement !== besideDrawing) besideDrawing.append(captionElement);
    if (!nearDrawing && captionElement.parentElement === besideDrawing) $('error').after(captionElement);
    $('centerPhoto').hidden = !(zone==='center' || (middle && photoPlaces));
    showFraming();
    $('keep').textContent = nameOnly ? 'Save guest name' : middle && sameArt && proposedPeople ?
      'Keep guest' : attached ? 'Queue this drawing' : opening ? 'Keep this change' : 'Keep this drawing';
    if (restoring) $('keep').textContent=attached ? 'Queue return to guest places' : 'Bring back guest places';
    if (planned?.route.guestBorderSeat) $('keep').textContent=(attached ? 'Queue ' : 'Keep ')+
      book.active[planned.route.guestBorderSeat.place].name+'’s border drawing';
    if (middle && planned?.route.placePhoto==='group') {
      $('keep').textContent = attached ? 'Queue guest portraits' : 'Keep guest portraits';
    } else if (middle && planned?.route.placePhoto) {
      const slot=localRoute.place, recipient=book.active[slot].name;
      const label=labels[proposed[slot]], face=planned.route.placePhoto==='face';
      const title=face && label?.startsWith('Portrait of ') ? label.replace(/^Portrait/,'portrait')+' for '+recipient :
        recipient+(face ? '’s portrait' : '’s drawing');
      $('keep').textContent=(attached ? 'Queue ' : 'Keep ')+title;
    }
    $('keep').hidden = stage !== 'redrawn' || (zone === 'center' && converting); $('reset').hidden = !kept || attached || !!selected.widePortrait;
    const interests=planned?.drawingInterests;
    $('drawingInterestsField').hidden = !middle || stage!=='redrawn' || !interests;
    const interestText=interests?.text || '';
    if ($('drawingInterests').value!==interestText) $('drawingInterests').value=interestText;
    $('reset').textContent = book?.personalized ? 'Restore starting drawing' : 'Start over';
    hideDownloads();
    let image = original;
    if (!before && !sameArt) {
      const seg = planned.route.segments;
      const borderHalf=planned.route.borderDrawingHalfway;
      const complete=planned.route.filePaths || (planned.route.firstOrnament || borderHalf!==undefined ? seg :
        planned.route.guestBorderOrder==='progressive' ? [planned.route.path] : null);
      if (!planned.clear && (stage === 'cleared' || !complete)) {
        if (borderHalf!==undefined) planned.clear=replaySand(bed,complete,borderHalf);
        else if (borderMoment) planned.clear=replaySand(bed,complete,borderMoment.endIndex);
        else if (moment) planned.clear=replaySand(bed,planned.route.filePaths,moment.endIndex);
        else planned.clear=replaySand(bed,visits ? planned.route.filePaths.slice(0,visits[0].count) : seg.slice(0,2));
      }
      if (stage === 'cleared') {
        planned.clearImage ??= renderer.image(planned.clear);
        image = planned.clearImage;
      } else {
        if (!planned.end) {
          planned.end = complete ? replaySand(bed,complete) :
            replaySand(planned.clear,seg.slice(2));
          planned.endImage = renderer.image(planned.end);
        }
        image = planned.endImage;
        $('downloads').hidden = !planned.route.path || (zone === 'center' && converting);
      }
    }
    const ids = before ? current : proposed;
    const designIndex=before ? selected[zone] : nextDesign();
    const borderArt=zone==='outer' && designIndex===guestBorderIndex &&
      (before ? selected.guestBorder : planned?.route.guestBorder || selected.guestBorder);
    const design = zone === 'middle' ? people(ids, (!before && proposedPeople) || book.active) :
      borderArt ? guestBorderTitle+' · '+borderArt.filter(Boolean).map(art=>art.label).join(' / ') :
      scene.zones[zone].names[designIndex];
    const borderName = zone === 'outer' && borderPicker && (before ? selected.borderGuest : $('borderGuest').value.trim());
    const title = zone === 'center' ? (before ? keptPortrait : planned?.route.featuredGuest?.title || portraitDraft?.title) || design :
      borderName ? borderName+' · '+design : design;
    const preserved = zone==='outer' && selected.widePortrait ? 'The wide portrait stays on display.' :
      zoneCount === 3 ? 'The other two zones are still on display.' :
      zone === 'center' ? 'The border is still on display.' : 'The center is still on display.';
    let caption = title;
    if (stage === 'cleared') {
      let progress = halfway ? 'Halfway through the ball’s travel. ' : titles[zone] + ' cleared. ';
      if (borderMoment && planned.route.guestBorder) {
        const art=planned.route.guestBorder;
        const finished=borderMoment.finished.map(m=>art[m.place].label);
        if (borderMoment.halfway) progress='Halfway through the ball’s travel. '+(finished.length ?
          finished.join(' / ')+(finished.length===1 ? ' is' : ' are')+' finished. ' : 'No guest drawing has finished yet. ');
        else progress='At '+Math.round(100*borderMoment.first.fraction)+'% of the ball’s travel, '+
          art[borderMoment.first.place].label+' is the first finished guest drawing. ';
      } else if (progressiveBorder) {
        const {halfwayFinished,ornaments} = planned.route;
        const noun = {'Thai roof peaks':'roof peaks', 'Lotus buds':'buds', 'Autumn leaves':'leaves'}[design] || 'sections';
        const early=borderMoment && !borderMoment.halfway;
        if (early) progress='At '+Math.round(100*borderMoment.first.fraction)+'% of the ball’s travel, ';
        progress+=(early ? 1 : halfwayFinished)+' of '+ornaments+' '+noun+' complete. ';
      }
      caption = progress+preserved;
    }
    const place = middle ? planned?.route.place : undefined;
    if (Number.isInteger(place) && !before) {
      const guests = proposedPeople || book.active;
      if (stage === 'cleared') {
        const fraction=planned?.route.progressFraction;
        const when=Number.isFinite(fraction) ? 'At '+Math.round(fraction*100)+'% of the ball’s travel, ' : '';
        const progress = singleMoments ? guests[place].name+' · '+moment.label+'. Shown at '+Math.round(100*moment.fraction)+'% of the ball’s travel.' :
          addition ? when+'the '+addition.detail+' is taking shape on '+guests[place].name+'’s '+addition.subject+'.' :
          earlyGuest ? when+guests[place].name+'’s new drawing is taking shape.' :
          fill ? 'Halfway through '+guests[place].name+'’s drawing.' : book.active[place].name+'’s place cleared.';
        const others = book.active.filter((_,i)=>i!==place && current[i]!==openSubject);
        const neighbors = people(others.map(p=>p.subject),others);
        caption = progress+' The center and border stay visible'+(neighbors ? ' with '+neighbors+'.' : '. The other places remain open.');
      } else {
        const change = addition ? 'The '+addition.detail+' was added to the existing '+addition.subject+'.' :
          fill ? guests[place].name+'’s drawing was added to the open place.' :
          proposed[place]===openSubject ? guests[place].name+'’s place is open.' : 'Only '+guests[place].name+'’s place changed.';
        caption = title+'. '+change+' The center and border stay visible.';
      }
    } else if (visits && !before) {
      const guests = proposedPeople || book.active;
      if (stage==='cleared') {
        const place=moment ? moment.place : visits[0].place;
        const title=guests[place].name+' · '+labels[proposed[place]]+'. ';
        if (moment) {
          const when='At '+Math.round(100*moment.fraction)+'% of the ball’s travel, ';
          const detail=visits.find(part=>part.place===place)?.addFrom && decorations[proposed[place]];
          const action=detail ? 'the '+detail.detail+(moment.forming ? ' is taking shape on the existing ' : ' has been added to the existing ')+detail.subject+'.' :
            moment.forming ? 'the new drawing is taking shape as this place clears.' :
            proposed[place]===openSubject ? 'this place is clear.' : 'this drawing is finished.';
          caption=title+when+action+' The center and border stay visible.';
        } else caption=title+'The other guest places still show their starting sand. The center and border stay visible.';
      } else {
        caption = title+'. '+(onlyAdditions ? 'The decorations were added to the existing drawings.' :
          directFills ? 'The open places filled directly.' :
          'The guest places changed one at a time.')+' The center and border stay visible.';
      }
    } else if (wholeMiddle && !before) {
      const count = proposed.filter(id=>id!==openSubject).length;
      const redraw = ['','the guest drawing','both guest drawings','all three guest drawings'][count];
      caption = stage==='cleared' ? 'The whole middle ring is clear. The ball will redraw '+redraw+'.' :
        title+'. The ball clears the whole middle ring and redraws '+redraw+'.';
      caption += ' The center and border stay visible.';
    } else if (opening && stage==='redrawn' && proposed.every(id=>id===openSubject)) {
      caption = title+'. All three places are open. The center and border stay visible.';
    } else if (middle && stage==='redrawn' && !sameArt) {
      caption = title+'. This change clears and redraws the whole guest ring. The center and border stay visible.';
    }
    if (zone==='center') {
      if (!before && planned?.route.featuredGuest) {
        const guest=book.active[planned.route.featuredGuest.slot];
        const facing=catalog.geometry.faceEdge ? ' It faces '+guest.name+'’s chair.' : '';
        caption=(stage==='cleared' ? 'Center cleared.' : title+' in the center.'+facing)+
          ' The guest ring and border stay on display.';
      }
      if (before && selected.widePortrait) caption=keptPortrait+'. '+(wideMixer ? 'The drawing' : 'The portrait')+' spans the center and guest places. The border stays on display.';
      if (!before && planned?.route.centerMode==='widePortrait') {
        caption=stage==='cleared' ? (progressivePortrait ? (wideMixer ? 'The stand mixer' : 'The portrait')+' takes shape as the center and guest places clear.' :
          'The center and guest places are clear for the portrait.') : title+' across the center and guest places.';
        caption+=' The border stays on display.';
      }
      if (!before && restoring) caption=stage==='cleared' ? 'The portrait has cleared. The border stays on display.' :
        scene.zones.center.names[0]+' and the guest places are back. '+people(current,book.active)+'. The border stays on display.';
    }
    if (zone==='outer' && selected.widePortrait && stage!=='cleared') caption=title+'. The wide portrait stays across the center and guest places.';
    if (!before && planned?.route.guestBorderSeat) {
      const {place}=planned.route.guestBorderSeat, person=book.active[place].name;
      caption=stage==='cleared' ? (refreshOne ? planned.route.guestBorder[place].label+' is partly drawn.' :
        person+'’s part of the border is clear.') :
        planned.route.guestBorder[place].label+'. Only '+person+'’s part of the border changed.';
      caption+=' The other border drawings and '+(selected.widePortrait ? 'the wide portrait' : 'the center and guest places')+' stay on display.';
    }
    $('sand').src = image;
    $('sand').alt = caption;
    captionElement.textContent = caption +
      (middle && sameArt && proposedPeople && !before ? '. The drawing already matches.' : '');
    if (room?.changed && !room.writing) room.showConflict();
  }
  $('zoom').onclick = $('guestZoom').onclick = () => { enlarged=!enlarged; showFraming(); };
  $('guestRedraw').onchange = () => {
    if ($('guestRedrawField').hidden) return;
    const localRoute = planned.localRoute || planned.route;
    const drawingInterests = planned.drawingInterests;
    if ($('guestRedraw').value === 'ring') {
      const route = OasisRingPlanner.plan(catalog,proposed,custom);
      if (localRoute.placePhoto) route.placePhoto = localRoute.placePhoto;
      planned = {route,localRoute,drawingInterests};
    } else planned = {route:localRoute,drawingInterests};
    show();
  };
  $('guestMoment').onchange = () => {
    if (stage!=='cleared' || (!planned?.route.moments && !planned?.route.progressMoments && !planned?.route.firstOrnament)) return;
    const picker=$('guestMoment');
    if (picker.selectedIndex<0) { picker.selectedIndex=planned.momentIndex; return; }
    planned.momentIndex=picker.selectedIndex;
    delete planned.clear;
    delete planned.clearImage;
    show();
  };
  $('nextSeat').onclick = () => { viewingSeat++; showSeatView(); };
  $('chairView').onclick = () => { chairView=!chairView; showSeatView(); };
  function clearError() { $('error').hidden=true; $('error').textContent=''; }
  function report(e) { $('error').textContent=e.message; $('error').hidden=false; }
  function editBorder() {
    borderEdited=true; planned=null; clearError();
    stage='original'; radio('stage',stage).checked=true; show();
  }
  $('borderDesign').onchange = () => { $('editBorderPlace').checked=false; $('borderOrder').value='progressive'; editBorder(); };
  $('editBorderPlace').onchange = () => { $('borderGuest').value=selected.borderGuest; editBorder(); };
  $('borderPlace').onchange = editBorder;
  $('borderSubject').oninput = () => { $('borderSaved').value=''; editBorder(); };
  $('borderSaved').onchange = () => { $('borderSubject').value=labels[$('borderSaved').value] || ''; editBorder(); };
  $('borderGuest').oninput = editBorder;
  $('borderOrder').onchange = () => { borderEdited=true; planned=null; clearError(); show(); };
  $('borderForm').onsubmit = event => {
    event.preventDefault();
    if (zone !== 'outer' || !borderPicker || $('borderPreview').disabled) return;
    clearError(); borderEdited=true; planned=null;
    stage='redrawn'; radio('stage',stage).checked=true; show();
    const bowl=$('sand').closest('.bowl');
    if (bowl.getBoundingClientRect().bottom<0) bowl.scrollIntoView({block:'start'});
  };
  for (const input of main.querySelectorAll('input[name=stage],input[name=zone]')) {
    input.addEventListener('change', () => {
      clearError();
      if (input.name === 'zone') {
        if (input.value==='middle' && selected.widePortrait) { radio('zone',zone).checked=true; return; }
        suggestionVersion++;
        if (zone==='outer' && ['#example-lek-border','#border'].includes(location.hash)) {
          const url=new URL(location.href); url.hash=''; history.replaceState(null,'',url);
        }
        if (converting) cancelPhoto('Choose Preview photo to try again.');
        if ((zone==='middle' || input.value==='middle') && ($('centerPhoto').open || planned?.route.placePhoto)) {
          if (guestPhotoPanel || planned?.route.placePhoto) resetPhoto();
          $('centerPhoto').open=false;
          stage='original'; radio('stage',stage).checked=true;
        }
        if (zone === 'middle' && proposedPeople) {
          proposedPeople = null; proposed = defaultSuggestion(); dirtyInput = peopleBox.open;
          stage = 'original'; radio('stage',stage).checked = true;
        }
        if (planned?.route.featuredGuest || (borderPicker && (zone==='outer' || input.value==='outer'))) {
          stage='original'; radio('stage',stage).checked=true;
        }
        zone = input.value; enlarged = false; planned = null; clearRoomFiles();
      } else stage = input.value;
      show();
    });
  }
  function addFiles(details, files, handles) {
    const links = details.querySelector('div');
    for (const file of files) {
      const link = document.createElement('a');
      link.href = URL.createObjectURL(new Blob([file.text], {type:'text/plain'}));
      handles.push(link.href);
      link.download = file.name;
      link.textContent = file.name;
      links.append(link);
    }
  }
  const setupUrls = [];
  const setup = $('setupFiles');
  setup.hidden = !scene.live.setup?.length;
  const mm = value => Number(value.toFixed(2));
  $('tableDimensions').textContent = 'Drawing area ' + (2*radiusMM/25.4).toFixed(1) +
    ' inches across (' + mm(radiusMM) + ' mm radius). Groove width ' + mm(groove*radiusMM) + ' mm.' +
    (Number.isFinite(trackingMarginMM) ? ' Allows ' + mm(trackingMarginMM) + ' mm on either side if the ball drifts.' : '');
  setup.ontoggle = async () => {
    if (!setup.open || setupUrls.length) return;
    const list = setup.querySelector('div');
    try {
      const files = attached ? await room.files('setup') : exampleSetup ? [...scene.live.setup,...exampleSetup] : scene.live.setup;
      if (editorClosed || !setup.open || setupUrls.length) return;
      list.textContent = '';
      addFiles(setup, files.map(file => ({...file, name:scene.layout + '-' + file.name})), setupUrls);
    } catch { if (setup.open) list.textContent = 'Could not load the starting layout files.'; }
  };
  function motionFiles(targetZone=zone, route=planned.route) {
    if (route.files) return route.files;
    const prefix = targetZone === 'middle' ? 'guest-ring' : targetZone === 'outer' ? 'border' :
      route.featuredGuest ? 'center-guest' : portraitDraft ? 'center-portrait' : 'center';
    return OasisRingPlanner.files(route.path, prefix);
  }
  function roomMotion(targetZone,route) {
    const motion = {zone:targetZone,files:motionFiles(targetZone,route)};
    if (route.guestBorder) motion.guestBorder=true;
    if (route.guestBorderOrder==='progressive') motion.guestBorderOrder='progressive';
    if (route.guestBorderSeat) motion.guestBorderSeat=route.guestBorderSeat;
    if (route.centerMode) motion.centerMode=route.centerMode;
    if (route.includesCenterRake) motion.includesCenterRake=true;
    if (route.parts) motion.parts=route.parts;
    if (route.tour) motion.tour=true;
    if (Number.isInteger(route.place)) motion.place=route.place;
    if (route.fill) motion.fill=true;
    if (route.shortFill) motion.shortFill=route.shortFill;
    if (route.addFrom) motion.addFrom=route.addFrom;
    if (route.earlyFrom) motion.earlyFrom=route.earlyFrom;
    if (route.customReveal) motion.customReveal=route.customReveal;
    return motion;
  }
  $('downloads').addEventListener('toggle', () => {
    if ($('downloads').open && planned?.route.path && !urls.length) addFiles($('downloads'), motionFiles(), urls);
  });
  const roomFiles = $('roomFiles'), roomUrls = [];
  let fileRequest = 0;
  function clearRoomFiles() {
    fileRequest++;
    roomFiles.open = false;
    roomUrls.splice(0).forEach(url => URL.revokeObjectURL(url));
    roomFiles.querySelector('div').replaceChildren();
  }
  roomFiles.hidden = !room;
  roomFiles.ontoggle = async () => {
    if (!room || !roomFiles.open) return;
    const request = ++fileRequest, list = roomFiles.querySelector('div');
    roomUrls.splice(0).forEach(url => URL.revokeObjectURL(url));
    list.textContent = 'Loading…';
    try {
      const files = await room.files(zone);
      if (request !== fileRequest || !main.isConnected) return;
      list.textContent = files.length ? '' : attached ? 'No saved drawing files for this zone yet.' : 'The starting layout is still on display in this zone.';
      addFiles(roomFiles, files, roomUrls);
    } catch { if (request === fileRequest) list.textContent = 'Could not load the drawing files.'; }
  };

  function singleGuestPlace() {
    if (zone==='middle' && stage==='redrawn' && !proposedPeople && !dirtyInput && !converting && planned?.route.placePhoto!=='group')
      return planned?.route.place;
  }

  function mergeGuestDrawing(latest, draft, motion) {
    const place=motion.place;
    if (latest.widePortrait || latest.edition!==scene.live.edition || latest.ids[place]!==current[place]) return null;
    const shapes={...latest.custom}, names={...latest.labels};
    const roster=new RingGuestBook(latest.ids);
    roster.restore(latest.guestBook,latest.ids);
    const owner=roster.active[place], originalOwner=book.active[place];
    if (owner.name!==originalOwner.name || GuestArt.guestInterest(owner)!==GuestArt.guestInterest(originalOwner)) return null;
    const same=(a,b)=>JSON.stringify(a)===JSON.stringify(b);
    const old=current[place];
    if (!same(shapes[old],custom[old]) || (shapes[old] && names[old]!==labels[old])) return null;
    let id=draft.ids[place];
    const path=draft.custom[id], name=draft.labels[id];
    if (path) {
      if (shapes[id] && (!same(shapes[id],path) || names[id]!==name)) {
        // Each phone numbers its own photo and sketch previews.
        if (!id.startsWith('sketch-')) return null;
        let n=1;
        while (Object.hasOwn(shapes,'sketch-'+n)) n++;
        id='sketch-'+n;
      }
      shapes[id]=path; names[id]=name;
    }
    const ids=latest.ids.slice(); ids[place]=id;
    const route=OasisRingPlanner.planChange(catalog,latest.ids,ids,shapes);
    if (route.place!==place || !!route.fill!==!!motion.fill || route.addFrom!==motion.addFrom ||
        !same(motionFiles('middle',route),motion.files)) return null;
    // Replay the exact approved trip on today's sand, including shared access grooves.
    const previous=Float32Array.from(atob(latest.bed),b=>b.charCodeAt(0)/170-1);
    const height=replaySand(previous,route.filePaths || route.segments);
    roster.keep(null,ids);
    const selections={center:latest.center,outer:latest.outer,borderGuest:latest.borderGuest,portraitSeats:latest.portraitSeats};
    if (latest.guestBorder) selections.guestBorder=latest.guestBorder;
    if (scene.live.guestBorderSeat===true && latest.guestBorderGrain) selections.guestBorderGrain=latest.guestBorderGrain;
    const merged=snapshot(height,selections,latest.portrait,ids,roster,false,shapes,names,
      Object.keys(latest.custom),latest.drawingInterests || {});
    const sourceId=draft.ids[place], requested=draft.drawingInterests?.[sourceId] || '';
    if (eligibleDrawingName(id,name) && requested!==drawingInterest(sourceId))
      setDrawingInterest(merged,id,requested);
    return merged;
  }

  async function keepDrawing(manual = true) {
    if (zone === 'center' && converting) return false;
    if (selected.widePortrait && (zone==='middle' || (zone==='center' && !planned?.route.centerMode))) return false;
    const nameOnly = borderNameOnly();
    if (stage !== 'redrawn' || (!planned?.end && !nameOnly && !(zone === 'middle' && proposedPeople && sameRing()))) return false;
    const borderSources=planned?.route.guestBorder, borderSeat=planned?.route.guestBorderSeat;
    if (borderSources) {
      const expected=borderSeat ? selected.guestBorder.slice() : guestBorderSources();
      if (borderSeat) expected[borderSeat.place]=guestDrawingSource(borderSeat.place,borderSeat.subject);
      if (!sameGuestBorder(expected,borderSources)) {
        editBorder(); report(Error('A guest drawing changed. Preview the border again.')); return false;
      }
    }
    const nextBed = planned?.end ?? bed, nextImage = planned?.endImage ?? original;
    const drawings = zone === 'middle' ? proposed.slice() : current;
    const roster = book?.copy();
    const selections = {...selected};
    if (zone === 'center') selections.portraitSeats = portraitDraft?.seats;
    let portrait = keptPortrait;
    if (zone === 'middle') roster.keep(proposedPeople, drawings);
    else if (zone === 'center' && (portraitDraft || planned?.route.featuredGuest)) {
      portrait = planned.route.featuredGuest?.title || portraitDraft.title;
      if (planned.route.centerMode==='widePortrait') selections.widePortrait=true;
    }
    else {
      selections[zone] = nextDesign();
      if (zone === 'center') {
        portrait = '';
        if (planned?.route.centerMode==='restoreGuests') {
          selections.center=0;
          delete selections.widePortrait;
        }
      }
      if (zone === 'outer' && borderPicker) {
        selections.borderGuest = borderSeat ? selected.borderGuest : $('borderGuest').value.trim();
        if (borderSources) {
          selections.guestBorder=borderSources;
          if (!borderSeat && scene.live.guestBorderSeat===true)
            selections.guestBorderGrain=planned.route.guestBorderOrder==='progressive' ? 'fluted' : 'spiral';
        } else if (selections.outer!==guestBorderIndex) {
          delete selections.guestBorder;
          delete selections.guestBorderGrain;
        }
      }
    }
    const state = snapshot(nextBed, selections, portrait, drawings, roster);
    const interests = manual && zone==='middle' && planned?.drawingInterests;
    if (interests && interests.text!==drawingInterest(interests.id)) {
      try { setDrawingInterest(state,interests.id,interests.text); }
      catch (error) { report(error); $('drawingInterests').focus(); return false; }
    }
    if (room) {
      const motion = !nameOnly && planned?.route.path ? roomMotion(zone,planned.route) : undefined;
      const merge = manual && Number.isInteger(singleGuestPlace()) ?
        latest=>mergeGuestDrawing(latest,state,motion) : null;
      const saved = await room.save(state,motion,false,merge);
      if (!saved) return false;
      if (saved.state!==state) {
        applyGarden(saved.state);
        rotation?.changed();
        return true;
      }
    } else remember(state);
    if (manual && zone === 'middle') {
      book.active.forEach((person,i) => {
        const next = roster.active[i];
        if (person.name !== next.name || person.interest !== next.interest || current[i] !== drawings[i]) rotation?.forget(i);
      });
    }
    restoreDrawings(state);
    bed = nextBed; original = nextImage; keptPortrait = portrait;
    Object.assign(selected,selections);
    if (!selections.guestBorder) delete selected.guestBorder;
    if (!selections.guestBorderGrain) delete selected.guestBorderGrain;
    if (!selections.widePortrait) delete selected.widePortrait;
    const keptRequestInCenter=zone==='center' && planned?.requestInCenter;
    if (zone === 'middle') {
      if (planned?.route.placePhoto) {
        draftPhotoIds=[];  // The saved guest book now owns these paths.
        resetPhoto();
      }
      if (libraryExample || ['#example-telescope','#example-heart-initials','#example-guitar-books','#example-comet-telescope','#example-alex-guitar','#example-thomas-guitar','#example-electric-guitar','#example-two-books','#example-acorn','#example-harvest-pear','#example-harvest-wheat','#example-crescent-roll','#example-harvest-basket','#example-oven-mitt','#example-desk-lamp','#example-pumpkin-pie','#example-lattice-pie','#example-pilgrim-hat','#example-lotus-leaf','#example-roast-turkey'].includes(location.hash)) {
        const url = new URL(location.href); url.hash = 'guests'; history.replaceState(null, '', url);
      }
      Object.assign(book,roster);
      if (proposedPeople) guestFocus = -1;
      current = drawings; proposedPeople = null;
      peopleBox.open = false; guestForm.refresh();
    } else if (zone === 'center') resetPhoto();
    else if (zone === 'outer' && borderPicker) {
      resetBorderForm();
      if (borderSeat) { $('editBorderPlace').checked=true; $('borderPlace').value=String(borderSeat.place); }
      if (location.hash === '#example-lek-border') {
        const url=new URL(location.href); url.hash='border'; history.replaceState(null,'',url);
      }
    }
    if (zone==='middle' || keptRequestInCenter) {
      if (keptRequestInCenter) guestFocus=-1;
      proposed=defaultSuggestion();
      $('idea').value=''; $('target').value=''; resetSketch(); dirtyInput=false;
    }
    kept=true; clearRoomFiles();
    // Start the next change on the same height grid that the other phones received.
    if (room) { restore(state); original=renderer.image(bed); }
    planned = null; stage = 'original'; radio('stage',stage).checked = true;
    show();
    return true;
  }
  $('keep').onclick = () => keepDrawing();
  $('drawingInterests').oninput = () => {
    if (!planned?.drawingInterests) return;
    planned.drawingInterests.text=$('drawingInterests').value;
    clearError();
  };

  function applyGarden(state, preserveInput = false) {
    guestFocus = -1;
    const targetName = preserveInput && $('target').value !== '' && book?.active[Number($('target').value)]?.name;
    offeredPhoto=null; wideSuggestionVersion=null;
    const requestedArea=$('portraitArea').value;
    const hadBorderPlace=preserveInput && editingBorderPlace();
    restore(state);
    const removedBorder=hadBorderPlace && selected.outer!==guestBorderIndex;
    if (selected.widePortrait && zone==='middle') {
      zone='center'; radio('zone',zone).checked=true;
      peopleBox.open=false; $('changingGarden').open=false;
      preserveInput=false;
    } else if (preserveInput && !selected.widePortrait && wideCenter) $('portraitArea').value=requestedArea;
    const changedPhotoPlace = preserveInput && requestedPhoto && !samePhotoPlace(requestedPhoto);
    if (!preserveInput || !borderEdited || removedBorder) resetBorderForm();
    original=renderer.image(bed);
    proposedPeople=null;
    if (!preserveInput) peopleBox.open=false;
    guestForm?.refresh(preserveInput);
    if (preserveInput) {
      const slot = targetName ? book.active.findIndex(person => person.name === targetName) : -1;
      $('target').value = slot >= 0 ? String(slot) : '';
      if (changedPhotoPlace) resetPhoto();
      else {
        portraitDraft=null; clearSource();
        cancelPhoto('Preview the photo again on the latest garden.');
        if (separatePhotos()) showSeatPhotos();
        if (groupGuestPhoto()) {
          if (assignmentScan) showAssignmentSource();
          else inspectAssignmentPhoto();
        }
      }
    } else {
      resetPhoto(); $('idea').value=''; $('target').value=''; resetSketch();
    }
    clearRoomFiles(); clearError(); proposed=defaultSuggestion();
    if (changedPhotoPlace) report(Error('The requested place changed. Check the guest and preview your suggestion again.'));
    if (removedBorder) report(Error('The guest border was replaced. Choose Guest drawings to make another one.'));
    dirtyInput=preserveInput && !!(peopleBox.open || $('idea').value.trim() || paths.length);
    planned=null; stage='original'; radio('stage',stage).checked=true;
    show();
  }
  $('reset').onclick = async () => {
    let state = null;
    if (book?.personalized) {
      const roster = book.copy();
      roster.resetDrawing(defaults);
      const fresh = Float32Array.from(atob(scene.live.bed), b => b.charCodeAt(0)/170-1);
      state = snapshot(fresh,{center:0,outer:0},'',defaults,roster,true);
    }
    if (room) { if (!await room.save(state)) return; }
    else remember(state);
    applyGarden(state);
    rotation?.changed();
  };

  function cancelPhoto(message) {
    photoRequest++;
    converting = false;
    $('portraitSubmit').disabled = separatePhotos() ? !seatsReady() : !samplePhoto && !$('portraitFile').files.length;
    $('portraitStatus').textContent = message;
  }
  function clearSource() {
    resetObjectBackground();
    displayFaces(null,null,false);
    $('portraitSource').hidden=true; $('portraitSource').open=false;
    $('sourceImage').removeAttribute('src');
    if (sourceUrl) URL.revokeObjectURL(sourceUrl);
    sourceUrl=''; sourceFile=null;
  }
  function resetObjectBackground() {
    hasIsolatedSubject = false;
    $('includeBackground').checked = false;
  }
  function usePhotoSource(file) {
    if (sourceFile!==file) {
      clearSource(); sourceFile=file;
      GuestPhoto.uprightPhoto(file).then(upright=>{
        if(sourceFile!==file)return;
        if(sourceUrl)URL.revokeObjectURL(sourceUrl);
        sourceUrl=URL.createObjectURL(upright); $('sourceImage').src=sourceUrl;
      });
    }
    $('portraitSource').hidden=false;
  }
  function showPhotoSource(file,result,group=false,object=false) {
    const keepOpen=$('portraitSource').open;
    usePhotoSource(file);
    $('portraitSource').querySelector('summary').textContent = object ? 'Frame the subject in your photo' : group ? 'Choose people in the source photo' : 'Choose a face in the source photo';
    const needsFrame = object ? !objectFrame && !result.hasIsolatedSubject : group ? result.facesDetected<2 : result.facesDetected!==1;
    $('portraitSource').open=keepOpen || needsFrame || !!(group && result.distantFace && !groupFaces);
    displayFaces(result,object ? result.objectFrame : faceChoice,group,groupFaces,object);
    hasIsolatedSubject = object && !objectFrame && result.hasIsolatedSubject === true;
    if (!hasIsolatedSubject) $('includeBackground').checked = false;
  }
  function seatDescription(faces) {
    const inches=2*centerRadius(photoZone())*radiusMM/25.4;
    const widths = faces.map(face=>face.headWidth * inches / 2);
    const small = Math.min(...widths).toFixed(1), large = Math.max(...widths).toFixed(1);
    const size = small === large ? small : small+' to '+large;
    const order = separatePhotos() || seatOrder ? 'Your seating order runs clockwise from the near edge.' :
      'Starting at the near edge, they follow the photo from left to right, clockwise.';
    return 'The faces are about '+size+' inches across. '+order;
  }
  function refreshPhotoPlaces() {
    const select=$('portraitPlace');
    const slots=book.active.map((person,i)=>({person,i})).filter(({i})=>catalog.places[i]);
    if (select.length===slots.length && slots.every(({person,i},k)=>select.options[k].value===String(i) && select.options[k].text===person.name)) return;
    const previousName=select.selectedOptions[0]?.text;
    select.replaceChildren(...slots.map(({person,i})=>new Option(person.name,String(i))));
    const preferred=slots.find(({person})=>person.name===previousName) || slots.find(({i})=>current[i]===openSubject) || slots[0];
    select.value=String(preferred.i);
  }
  async function loadPhotoTools(object,currentRequest) {
    await new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve)));
    if (!currentRequest()) return false;
    function load(id) {
      const script=document.createElement('script');
      script.textContent=document.getElementById(id).textContent; document.head.append(script); script.remove();
    }
    // Objects and paper drawings don't need the face detector or landmark model.
    if (!object && !window.GuestFaceStages) load('portraitModels');
    if (!window.GuestPhoto) load('portraitTools');
    return true;
  }
  async function readPhoto(file,options,request,entries) {
    if (!await loadPhotoTools(options.object,()=>request===photoRequest)) return;
    return entries ? GuestPhoto.fromSeatPhotos(entries,options) : GuestPhoto.fromFile(file,options);
  }
  async function readPreparedPortrait(file,diameterMm,grooveMm) {
    const invalid='Choose a prepared portrait file (.oasisportrait).';
    if (!file.size || file.size>4*1024*1024) throw Error(invalid);
    let data;
    try { data=JSON.parse(await file.text()); } catch { throw Error(invalid); }
    return checkedPreparedPortrait(data,diameterMm,grooveMm);
  }
  function checkedPreparedPortrait(data,diameterMm,grooveMm) {
    const invalid='Choose a prepared portrait file (.oasisportrait).';
    if (data?.format!=='oasis-prepared-portrait-v1' ||
        ![data.diameterMm,data.grooveMm].every(n=>Number.isFinite(n) && n>0)) throw Error(invalid);
    if (Math.abs(data.diameterMm-diameterMm)>.01 || Math.abs(data.grooveMm-grooveMm)>.01) {
      throw Error('This drawing fits a '+(data.diameterMm/25.4).toFixed(1)+'-inch center with a '+data.grooveMm+
        ' mm groove. Choose the matching portrait area or prepare the photo for this table.');
    }
    const kinds=['head','eye','glasses','smile','bridge','hairline','nose','brow','shade'];
    function points(line,limit=diameterMm/2) {
      return Array.isArray(line) && line.length>=2 && line.length<=32000 && line.every(p=>
        Array.isArray(p) && p.length===2 && p.every(Number.isFinite) && Math.hypot(...p)<=limit);
    }
    if (data.includesCenterRake!==undefined && (data.includesCenterRake!==true || data.points===undefined)) throw Error(invalid);
    if (data.points!==undefined) {
      if (data.marks!==undefined || !points(data.points,1+1e-8)) throw Error(invalid);
      return {points:data.points, includesCenterRake:data.includesCenterRake===true};
    }
    if (!Array.isArray(data.marks) || !data.marks.length || data.marks.length>600) throw Error(invalid);
    // Rebuild the drawing using the table's own planner. Only photographic
    // marks cross this boundary; the file cannot supply a motion or an erase.
    const shadowMarks=data.marks.map((mark,i)=>{
      if (!mark || !kinds.includes(mark.kind) || typeof mark.closed!=='boolean' || !points(mark.points) ||
          (mark.lids!==undefined && (mark.kind!=='eye' || !points(mark.lids))) ||
          (mark.noseBase!==undefined && (mark.kind!=='nose' || mark.closed || !points(mark.noseBase) ||
            data.marks[i+1]?.kind!=='nose' || data.marks[i+1].closed || data.marks[i+1].noseBase!==undefined)) ||
          (mark.rim!==undefined && (mark.kind!=='glasses' || !points(mark.rim))) ||
          (mark.opening!==undefined && (mark.kind!=='smile' || !points(mark.opening)))) throw Error(invalid);
      const clean={kind:mark.kind,closed:mark.closed,points:mark.points};
      if (mark.lids) clean.lids=mark.lids;
      if (mark.rim) clean.rim=mark.rim;
      if (mark.noseBase) clean.noseBase=mark.noseBase;
      if (mark.opening) clean.opening=mark.opening;
      if (mark.facialHair===true) clean.facialHair=true;
      if (mark.chinStrand===true) clean.chinStrand=true;
      return clean;
    });
    return {shadowMarks};
  }
  function showPortraitRoute(draft,route) {
    const trace=draft.trace, woodcut=route===trace.woodcut;
    draft.route=route;
    const groupLocks=route===trace.longHair && !!draft.selectedFaces;
    draft.title=route===trace.cheeks ? trace.title+' · Cheek shadows' : route===trace.rake ? trace.title+' · Shaded with the rake' : route===trace.flowingHair ? trace.title+' · Flowing hair' : groupLocks ? 'Group engraving · '+draft.selectedFaces.length+' faces · Two-sided long hair' :
      route===trace.longHair ? trace.title+' · Full hair' : woodcut ? trace.title+' · Woodcut hair' :
      draft.selectedFaces && route===trace.measured ? 'Group engraving · '+draft.selectedFaces.length+' faces' : trace.title;
    trace.message=route===trace.cheeks ? 'The rake follows the photographed cheek and jaw shadows as it clears the center.' :
      route===trace.rake ? 'The rake draws the shadows and clears the center in one pass.' :
      route===trace.flowingHair ? trace.flowingStrokes+' strokes follow the direction of the hair.' :
      groupLocks ? 'Showing the selected faces with '+trace.locks+' long hair strokes across both sides.' :
      route===trace.longHair ? 'Showing the full length of the photographed hair.' : woodcut ? 'Woodcut hair · '+trace.strokes+' strokes.' :
      route===trace.original ? 'Showing the first drawing.' : draft.selectedFaces ?
      'Showing the engraving of the '+draft.selectedFaces.length+' selected faces.' : 'Showing the '+trace.features+' traced from the photo.';
    planned={route};
    stage='redrawn'; radio('stage',stage).checked=true;
  }
  $('portraitLongHair').onclick=()=>{
    const draft=portraitDraft, trace=draft?.trace;
    if(converting || !trace || $('portraitLongHair').hidden)return;
    if (!trace.longHair) { tracePortrait('longHair'); return; }
    showPortraitRoute(draft,draft.route===trace.longHair ? trace.measured || trace.original : trace.longHair);
    show();
  };
  $('portraitFlowing').onclick=()=>{
    const draft=portraitDraft, trace=draft?.trace;
    if(converting || !trace?.flowingHair)return;
    showPortraitRoute(draft,draft.route===trace.flowingHair ? trace.measured || trace.original : trace.flowingHair);
    show();
  };
  rakeButton?.addEventListener('click',()=>{
    const draft=portraitDraft, trace=draft?.trace;
    if(converting || !trace || rakeButton.hidden)return;
    if(!trace.rake){tracePortrait('pairRake');return;}
    showPortraitRoute(draft,draft.route===trace.rake ? trace.measured || trace.original : trace.rake);
    show();
  });
  cheekButton?.addEventListener('click',()=>{
    const draft=portraitDraft;
    if (!draft || converting || cheekButton.hidden) return;
    if (!draft.trace?.cheeks) {tracePortrait('cheeks'); return;}
    const trace=draft.trace;
    showPortraitRoute(draft,draft.route===trace.cheeks ? trace.measured || trace.original : trace.cheeks);
    show();
  });
  $('portraitWoodcut').onclick=()=>{
    const draft=portraitDraft, trace=draft?.trace;
    if(converting || !trace?.woodcut)return;
    showPortraitRoute(draft,draft.route===trace.woodcut ? trace.measured || trace.original : trace.woodcut);
    show();
  };
  async function tracePortrait(style='') {
    const groupLocks=style==='longHair', shadePair=style==='pairRake', cheeks=style==='cheeks';
    const draft=portraitDraft, file=$('portraitFile').files[0];
    if (!draft || !file || converting || $('portraitHairField').hidden) return;
    const trace=draft.trace ||= {original:draft.route,title:draft.title};
    if (groupLocks && (!groupHair || !draft.selectedFaces || !trace.measured)) return;
    if (shadePair && (!pairRake || draft.selectedFaces?.length!==2 || !trace.measured)) return;
    if (cheeks && (!cheekPrint || cheekButton.hidden || draft.selectedFaces)) return;
    if (!style && trace.measured) {
      showPortraitRoute(draft,draft.route===trace.original ? trace.measured : trace.original);
      show(); return;
    }
    const request=++photoRequest, center=photoZone();
    const diameterMm=2*centerRadius(center)*radiusMM, grooveMm=groove*radiusMM;
    const faces=draft.selectedFaces;
    const selection=faces ? {faces,...(groupLocks && {groupLocks:true}),...(shadePair && {rakePrint:true})} : {face:faceChoice,
      ...(cheeks && {cheekPrint:true}),
      ...(!cheeks && rakePrint && center===wideCenter && Math.abs(diameterMm-632.8)<.01 && Math.abs(grooveMm-7)<.001 && {rakePrint:true}),
      ...(traceNose && {traceNose:true}),...(traceBrows && {traceBrows:true}),
      ...(traceSmile && {traceSmile:true}),...(traceEyes && {traceEyes:true}),
      ...(!cheeks && fullHair && {longHair:true}),...(!cheeks && hairWoodcut && {hairWoodcut:true}),...(!cheeks && flowingHair && {flowingHair:true})};
    const current=()=>request===photoRequest && portraitDraft===draft && $('portraitFile').files[0]===file && !editorClosed;
    const timeout=new AbortController(), timer=setTimeout(()=>timeout.abort(),135000);
    converting=true; $('portraitSubmit').disabled=true;
    trace.message='Tracing on the garden laptop…'; show();
    try {
      const upload=await GuestPhoto.laptopPhoto(file);
      if (!current()) return;
      const response=await fetch(portraitEndpoint,{method:'POST',mode:'same-origin',redirect:'error',
        signal:timeout.signal,headers:{'Content-Type':upload.type || 'application/octet-stream',
          'X-Oasis-Portrait':JSON.stringify({layout:scene.layout,diameterMm,grooveMm,...selection})},body:upload});
      if (!current()) return;
      if (response.status===429) throw Error('The garden laptop is tracing another photo. You can try again.');
      if (response.status===413) throw Error('Choose a smaller copy for the garden laptop.');
      if (response.status===415) throw Error('The garden laptop accepts still JPEG, PNG and WebP photos.');
      if (faces && response.status===422) throw Error(groupLocks ? 'The long hair could not fit on both sides at this size.' :
        'The laptop could not engrave every selected face clearly at this size.');
      if (!response.ok) throw Error('The garden laptop could not trace this photo.');
      const result=await response.json();
      if (!current()) return;
      const drawing=checkedPreparedPortrait(result.drawing,diameterMm,grooveMm);
      const print=cheeks ? 'cheekPrint' : 'rakePrint';
      if ((cheeks || rakePrint) && center===wideCenter && result[print]?.applied===true) {
        const prepared=checkedPreparedPortrait(result[print+'Drawing'],diameterMm,grooveMm);
        if (prepared.includesCenterRake) {
          const candidate=OasisRingPlanner.preparedPhoto(center,prepared.points,scene.live,true);
          if (candidate.includesCenterRake) {
            candidate.centerMode='widePortrait';
            if (cheeks) trace.cheeks=candidate;
            else trace.rake=candidate;
          }
        }
      }
      if (cheeks) {
        if (!trace.cheeks) {
          trace.cheeksUnavailable=true;
          throw Error('There is too little separate cheek shadow to engrave at this size.');
        }
        showPortraitRoute(draft,trace.cheeks);
        return;
      }
      if (faces) {
        if (result.method!=='group-engraving' || result.people!==faces.length) {
          throw Error('The garden laptop could not confirm every selected face.');
        }
        if (shadePair) {
          if (!trace.rake) {
            trace.rakeUnavailable=true;
            throw Error('There is too little separate shadow detail for this pair at this size.');
          }
          showPortraitRoute(draft,trace.rake);
        } else if (groupLocks) {
          if (!Number.isSafeInteger(result.locks) || result.locks<1) throw Error('The laptop could not confirm the hair strokes.');
          trace.longHair=shadowRoute(drawing);
          trace.locks=result.locks;
          showPortraitRoute(draft,trace.longHair);
        } else {
          trace.measured=shadowRoute(drawing);
          showPortraitRoute(draft,trace.measured);
        }
        return;
      }
      if (!['ordinary-outline','ordinary-shadows','measured-hair'].includes(result.method)) {
        throw Error('The garden laptop returned an unreadable drawing.');
      }
      const features=[result.method==='measured-hair' && 'hair', traceNose && result.nose?.applied===true && 'nose',
        traceBrows && result.brows?.applied===true && (result.brows.count===1 ? 'one eyebrow' : 'eyebrows'),
        traceSmile && result.smile?.applied===true && 'smile',traceSmile && result.smile?.moustache===true && 'moustache',
        traceEyes && result.eyes?.applied===true && 'eyes'].filter(Boolean);
      function shadowRoute(prepared) {
        if (!prepared.shadowMarks) throw Error('The garden laptop returned an unreadable drawing.');
        const route=OasisRingPlanner.shadowPhoto(center,prepared.shadowMarks,scene.live);
        if (center===wideCenter) route.centerMode='widePortrait';
        return route;
      }
      if (fullHair && result.longHair?.applied===true) {
        trace.longHair=shadowRoute(checkedPreparedPortrait(result.longHairDrawing,diameterMm,grooveMm));
      }
      if (flowingHair && result.flowingHair?.applied===true) {
        trace.flowingHair=shadowRoute(checkedPreparedPortrait(result.flowingHairDrawing,diameterMm,grooveMm));
        trace.flowingStrokes=result.flowingHair.strokes;
      }
      if (hairWoodcut && result.woodcut?.applied===true) {
        trace.woodcut=shadowRoute(checkedPreparedPortrait(result.woodcutDrawing,diameterMm,grooveMm));
        trace.strokes=result.woodcut.strokes;
      }
      if (features.length) {
        trace.features=featureNames.format(features);
        trace.measured=shadowRoute(drawing); showPortraitRoute(draft,trace.measured);
      } else {
        trace.unchanged=true;
        trace.message='The extra lines did not fit clearly at this size. Showing the first drawing.';
      }
    } catch (error) {
      if (current()) trace.message=(error.name==='AbortError' ? 'The garden laptop took too long.' :
        error instanceof TypeError ? 'The garden laptop could not be reached.' : error.message)+
        (style ? ' Your current drawing is still here.' : ' Your first drawing is ready.');
    } finally {
      clearTimeout(timer);
      if (current()) {converting=false; $('portraitSubmit').disabled=false; show();}
    }
  }
  $('portraitHair').onclick=()=>tracePortrait();
  function separatePhotos() { return zone === 'center' && $('portraitMode').value === 'separate'; }
  function unreadablePhoto() {
    if (!heicEndpoint || !$('centerPhoto').open) return null;
    const file=separatePhotos() ? seatPhotos[seatPhotoIndex]?.file : $('portraitFile').files[0];
    return window.GuestPhoto?.needsHeicReader?.(file) ? file : null;
  }
  function showHeicOption() {
    const file=unreadablePhoto();
    $('openHeic').hidden=!file;
    $('openHeic').disabled=!!file && openingHeic===file;
  }
  async function openHeic(submitter) {
    const file=unreadablePhoto(), seat=separatePhotos() && seatPhotos[seatPhotoIndex];
    if (!file || openingHeic===file) return;
    const request=photoRequest, current=()=>!editorClosed && request===photoRequest && unreadablePhoto()===file;
    const controller=new AbortController(), timer=setTimeout(()=>controller.abort(),90000);
    openingHeic=file; showHeicOption();
    $('portraitStatus').textContent='Opening this photo on the garden laptop…';
    try {
      const response=await fetch(heicEndpoint,{method:'POST',mode:'same-origin',redirect:'error',
        headers:{'Content-Type':'image/heic'},body:file,signal:controller.signal});
      if (!current()) return;
      if (!response.ok) {
        const result=await response.json();
        throw Error(result.error || 'The garden laptop could not open this photo.');
      }
      const bytes=await response.blob();
      if (!current()) return;
      if (bytes.type!=='image/jpeg') throw Error('The laptop did not return a readable photo.');
      const jpeg=new File([bytes],file.name.replace(/\.[^.]+$/,'')+'.jpg',{type:'image/jpeg'});
      laptopJpegs.add(jpeg);
      if (seat) {
        seat.file=jpeg; seat.error=null; editSeats(); await inspectSeat(seat);
      } else {
        const files=new DataTransfer(); files.items.add(jpeg);
        $('portraitFile').files=files.files;
        if (groupGuestPhoto()) await inspectAssignmentPhoto();
        else $('portraitForm').requestSubmit(submitter);
      }
    } catch (error) {
      if (current()) $('portraitStatus').textContent=error.message || 'The garden laptop could not open this photo.';
    } finally {
      clearTimeout(timer);
      if (openingHeic===file) openingHeic=null;
      if (!editorClosed) showHeicOption();
    }
  }
  $('openHeic').onclick=()=>openHeic($('portraitSubmit'));
  function groupGuestPhoto() { return zone === 'middle' && $('guestPhotoKind').value === 'groupPlaces'; }
  function showAssignmentSource() {
    usePhotoSource($('portraitFile').files[0]);
    $('portraitSource').querySelector('summary').textContent = 'Numbered faces in your photo';
    $('portraitSource').open = true;
    assignments.markSource(displayFaces, assignmentScan);
  }
  async function inspectAssignmentPhoto() {
    assignmentScan = null;
    assignments.reset();
    const file = $('portraitFile').files[0];
    show();
    if (!file) return;
    const request = ++photoRequest;
    const current = () => request===photoRequest && !editorClosed && groupGuestPhoto();
    $('portraitStatus').textContent = 'Finding faces in the group photo…';
    try {
      if (!await loadPhotoTools(false,current)) return;
      const scan = await GuestPhoto.inspectSeatPhoto(file);
      if (!current()) return;
      assignmentScan = scan;
      assignments.detected(scan.detectedFaces);
      showAssignmentSource();
      $('portraitStatus').textContent = laptopJpegs.has(file) ? 'Choose faces from the JPEG returned by the garden laptop.' :
        'The photo stays on this device.';
    } catch (error) {
      if (current()) $('portraitStatus').textContent = error.message || 'Could not read this photo.';
    }
    if (current()) show();
  }
  function seatsReady() {
    return seatPhotos.length >= 2 && seatPhotos.every(seat=>seat.face) && $('frameFace').getAttribute('aria-pressed') !== 'true';
  }
  function showSeatPhotos(refreshSource=true) {
    showHeicOption();
    const seat = seatPhotos[seatPhotoIndex], select = $('seatPhotoList');
    $('seatPhotoControls').hidden = !seat;
    select.replaceChildren(...seatPhotos.map(({file,face},i)=>
      new Option('Seat '+(i+1)+' · '+file.name+(face ? '' : ' · choose a face'),String(i))));
    select.selectedIndex = seatPhotoIndex;
    $('seatPhotoEarlier').disabled = seatPhotoIndex === 0;
    $('seatPhotoLater').disabled = seatPhotoIndex >= seatPhotos.length-1;
    if (refreshSource && !seat?.scan) clearSource();
    else if (refreshSource) {
      const {scan,face} = seat, boxes = scan.detectedFaces;
      const index = face ? boxes.findIndex(b=>b.x===face.x && b.y===face.y && b.w===face.w) : -1;
      usePhotoSource(seat.file);
      $('portraitSource').querySelector('summary').textContent = 'Face for seat '+(seatPhotoIndex+1);
      $('portraitSource').open = true;
      displayFaces({...scan,faceBoxes:boxes,includedFaces:[]},index >= 0 ? index : face || -1,false);
      if (!boxes.length) $('faceHelp').textContent = face ? 'The frame marks the face for this seat.' : 'Frame the face for this seat.';
    }
    if (!portraitDraft && !converting) {
      $('portraitStatus').textContent = seat?.error || (seat && !seat.scan ? 'Finding faces in this photo…' :
        seat && !seat.face ? 'Choose a face for seat '+(seatPhotoIndex+1)+'.' :
        seatPhotos.length < 2 ? 'Choose at least two photos for the seated portrait.' :
        !seatsReady() ? 'Choose a face for each seat before previewing.' :
        seatPhotos.some(s=>laptopJpegs.has(s.file)) ? 'The selected faces are ready for a preview on this phone.' :
        'The photos stay on this device.');
    }
    $('portraitSubmit').disabled = converting || !seatsReady();
  }
  function editSeats() {
    viewingSeat=0;
    editPhoto(true);
    showSeatPhotos();
  }
  async function inspectSeat(seat) {
    const current = () => !editorClosed && seatPhotos.includes(seat);
    try {
      if (!await loadPhotoTools(false,current)) return;
      const scan = await GuestPhoto.inspectSeatPhoto(seat.file);
      if (!current()) return;
      seat.scan = scan;
      if (scan.detectedFaces.length === 1) {
        const {x,y,w} = scan.detectedFaces[0]; seat.face = {x,y,w};
      }
    } catch (error) {
      if (!current()) return;
      seat.error = error.message || 'Could not read this photo. Replace it or remove the seat.';
    }
    if (separatePhotos() && $('centerPhoto').open) showSeatPhotos(seatPhotos[seatPhotoIndex]===seat);
  }
  function chooseSeatPhoto(input,replace) {
    const file = input.files[0];
    if (!file) return;
    input.value='';
    if (!replace) seatPhotoIndex = seatPhotos.length;
    const seat = {file,face:null,scan:null};
    seatPhotos[seatPhotoIndex] = seat;
    editSeats();
    inspectSeat(seat);
  }
  $('seatPhotoFile').onchange = () => chooseSeatPhoto($('seatPhotoFile'),false);
  $('replaceSeatPhotoFile').onchange = () => chooseSeatPhoto($('replaceSeatPhotoFile'),true);
  $('seatPhotoReplace').onclick = () => $('replaceSeatPhotoFile').click();
  $('frameFace').addEventListener('click', () => {
    if (groupGuestPhoto()) {
      if ($('sourceFrame').classList.contains('framing')) editPhoto(true);
      else show();
      return;
    }
    if (!separatePhotos()) return;
    if ($('frameFace').getAttribute('aria-pressed') === 'true') editPhoto(true);
    $('portraitSubmit').disabled = converting || !seatsReady();
  });
  $('sourceFrame').addEventListener('pointercancel', () => { if (groupGuestPhoto()) show(); });
  $('seatPhotoList').onchange = () => {
    seatPhotoIndex = $('seatPhotoList').selectedIndex;
    showSeatPhotos();
  };
  function moveSeat(direction) {
    const next=seatPhotoIndex+direction;
    if (next<0 || next>=seatPhotos.length) return;
    const [seat]=seatPhotos.splice(seatPhotoIndex,1);
    seatPhotos.splice(next,0,seat);
    seatPhotoIndex=next;
    editSeats();
  }
  $('seatPhotoEarlier').onclick = () => moveSeat(-1);
  $('seatPhotoLater').onclick = () => moveSeat(1);
  $('seatPhotoRemove').onclick = () => {
    seatPhotos.splice(seatPhotoIndex,1);
    seatPhotoIndex=Math.max(0,Math.min(seatPhotoIndex,seatPhotos.length-1));
    editSeats();
  };
  function clearExampleLink() {
    if (!['#example-group','#example-portrait','#example-faces','#example-shadows','#photo-shadows','#prepared-portrait',
          '#example-group-shadows','#group-shadows','#seated-group'].includes(location.hash)) return;
    const url = new URL(location.href);
    url.hash = 'photos';
    history.replaceState(null, '', url);
  }
  function resetPhoto() {
    clearExampleLink();
    discardDraftPhoto();
    if (zone==='middle') {
      proposed=defaultSuggestion(); proposedPeople=null; planned=null; guestFocus=-1;
      dirtyInput=false; stage='original'; radio('stage',stage).checked=true;
    }
    guestPhotoPanel=false; requestedPhoto=null;
    assignmentScan=null; assignments.reset();
    seatPhotos=[]; seatPhotoIndex=0;
    faceChoice=null; groupFaces=null; seatOrder=null; objectFrame=null;
    $('guestPhotoKind').value='face'; $('objectName').value=''; $('portraitName').value='';
    $('guestPortraitFrame').value='bust';
    $('photoCaption').value='';
    $('portraitArea').value=selected.widePortrait ? 'wide' : 'center';
    portraitDraft=null; samplePhoto=null; clearSource(); $('portraitFile').value=''; $('portraitMode').value='one'; $('portraitStyle').value='heads';
    $('soloStyle').value='auto'; $('seatedReveal').checked=false;
    $('centerPhoto').open=false;
    cancelPhoto('The photo is converted on this device.');
  }
  function editPhoto(keepSource=false) {
    if (!keepSource) clearSource();
    discardDraftPhoto();
    portraitDraft=null; planned=null; stage='original'; radio('stage',stage).checked=true;
    if (zone==='middle') { proposed=current.slice(); proposedPeople=null; guestFocus=-1; dirtyInput=false; }
    cancelPhoto('The photo is converted on this device.');
    show();
  }
  $('portraitArea').onchange = () => {
    if (selected.widePortrait) $('portraitArea').value='wide';
    if (!supportsPhotoShadows() && $('portraitStyle').value==='shadows') $('portraitStyle').value='faces';
    if (!supportsPhotoShadows() && $('soloStyle').value==='shadow') $('soloStyle').value='head';
    if (portraitDraft || converting) $('portraitForm').requestSubmit();
    else editPhoto(true);
  };
  $('restoreGuests').onclick = () => {
    if (!selected.widePortrait || zone!=='center') return;
    resetPhoto(); clearError();
    planned=null; stage='original'; radio('stage',stage).checked=true;
    try {
      const route=OasisRingPlanner.restoreGuests(scene,current,custom,0);
      route.centerMode='restoreGuests';
      planned={route}; stage='redrawn'; radio('stage',stage).checked=true;
      show();
    } catch (error) { show(); report(error); }
  };
  function previewFeaturedGuest(slot,id) {
    const art=id && guestDrawingSource(slot,id);
    const requestInCenter=zone==='middle' || planned?.requestInCenter;
    zone='center'; radio('zone',zone).checked=true; enlarged=false; clearRoomFiles();
    resetPhoto(); clearError(); planned=null; stage='original';
    try {
      if (id) {
        if (!art?.points) throw Error('Choose a drawing currently in the guest ring.');
        const geometry=catalog.geometry, angle=geometry.faceEdge ? geometry.angles[slot]+Math.PI/2 : 0;
        const route=OasisRingPlanner.guestInCenter(scene.zones.center,art.points,angle,groove);
        const label=[...art.label];
        route.featuredGuest={slot,id,title:label.length<=180 ? art.label : label.slice(0,179).join('')+'…'};
        planned={route,requestInCenter}; stage='redrawn';
      }
      radio('stage',stage).checked=true;
      show();
    } catch (error) { radio('stage',stage).checked=true; show(); report(error); }
  }
  $('featureGuest').onchange = () => {
    if (zone!=='center' || selected.widePortrait) return;
    const choice=$('featureGuest').value, slot=Number(choice);
    previewFeaturedGuest(slot,choice==='' ? null : current[slot]);
  };
  $('featureRequest').onclick = () => {
    const id=featureRequestId();
    if (!id) return;
    suggestionVersion++;
    previewFeaturedGuest(guestFocus,id);
    const bowl=$('sand').closest('.bowl');
    if (planned && bowl.getBoundingClientRect().bottom<0) bowl.scrollIntoView({block:'start'});
  };
  $('portraitMode').onchange = () => {
    // The prepared drawing has its own format. Do not pass it to the photo decoder.
    const file=samplePhoto || $('portraitFile').files[0];
    if (file && ($('portraitMode').value==='prepared') !== /\.oasisportrait$|\.json$/i.test(file.name)) {
      samplePhoto=null; $('portraitFile').value=''; faceChoice=null; groupFaces=null;
    }
    clearExampleLink(); $('seatedReveal').checked=false; editPhoto();
    if (separatePhotos()) showSeatPhotos();
  };
  $('guestPhotoKind').onchange = () => {
    $('portraitName').value='';
    $('guestPortraitFrame').value=groupGuestPhoto() ? 'head' : 'bust';
    assignmentScan=null; assignments.reset();
    requestedPhoto=null; clearExampleLink(); faceChoice=null; objectFrame=null; editPhoto();
    if (groupGuestPhoto()) inspectAssignmentPhoto();
  };
  $('objectName').oninput = () => editPhoto(true);
  $('portraitName').oninput = () => { if (zone==='middle') editPhoto(true); };
  $('photoCaption').oninput = () => editPhoto(true);
  $('guestPortraitFrame').onchange = () => {
    if (zone==='middle' && (converting || planned?.route.placePhoto)) $('portraitForm').requestSubmit();
  };
  $('includeBackground').onchange = () => $('portraitForm').requestSubmit();
  $('portraitFile').onchange = () => {
    if(sourceFile || samplePhoto || converting)$('photoCaption').value='';
    if (sourceFile || samplePhoto || converting) $('portraitName').value=requestedPhoto?.person || '';
    if (sourceFile || samplePhoto || converting) $('seatedReveal').checked=false;
    clearExampleLink(); samplePhoto=null; faceChoice=null; groupFaces=null; seatOrder=null; objectFrame=null; editPhoto();
    if (groupGuestPhoto()) inspectAssignmentPhoto();
  };
  $('portraitPlace').onchange = () => {
    if (zone!=='middle') return;
    if (requestedPhoto) {
      const slot=Number($('portraitPlace').value);
      requestedPhoto={...requestedPhoto,slot,guest:book.active[slot].name,from:null};
    }
    if (converting || planned?.route.placePhoto) $('portraitForm').requestSubmit();
    else show();
  };
  $('portraitStyle').onchange = $('soloStyle').onchange = $('seatedReveal').onchange = () => {
    clearExampleLink();
    if (!separatePhotos() && $('portraitStyle').value!=='seats') $('seatedReveal').checked=false;
    if (portraitDraft || converting) $('portraitForm').requestSubmit();
    else if (separatePhotos()) editSeats();
    else editPhoto();
  };
  const examples = {one:'sampleOne', group:'sampleGroup', faces:'sampleFaces'};
  function openSample(key, style = key === 'faces' ? 'faces' : 'pose') {
    $('photoCaption').value='';
    $('portraitName').value=requestedPhoto?.person || '';
    faceChoice=null; groupFaces=null; seatOrder=null; $('seatedReveal').checked=false;
    const bytes = Uint8Array.from(atob(scene.live.examples[key]), ch => ch.charCodeAt(0));
    samplePhoto = new File([bytes], key + '.jpg', {type:'image/jpeg'});
    $('portraitFile').value = ''; $('portraitMode').value = key === 'one' ? 'one' : 'group';
    $('portraitStyle').value = style === 'shadows' && !supportsPhotoShadows() ? 'faces' : style;
    editPhoto(); $('portraitForm').requestSubmit();
  }
  for (const [key, id] of Object.entries(examples)) {
    const data = scene.live.examples?.[key], button = $(id);
    button.hidden = !data;
    if (!data) continue;
    button.onclick = () => openSample(key);
  }
  $('centerPhoto').ontoggle = () => {
    if (zone==='middle') {
      suggestionVersion++;
      if (!$('centerPhoto').open && converting) cancelPhoto('Preview the photo to try again.');
      if ($('centerPhoto').open) {
        guestPhotoPanel=true;
        peopleBox.open=false;
        refreshPhotoPlaces();
        const target=requestedPhoto ? String(requestedPhoto.slot) : $('target').value;
        if (target!=='' && catalog.places[Number(target)]) $('portraitPlace').value=target;
        guestFocus=-1; proposedPeople=null; proposed=current.slice(); planned=null; dirtyInput=false;
        stage='original'; radio('stage',stage).checked=true;
      } else {
        const returningToRequest = !!requestedPhoto;
        if (guestPhotoPanel) resetPhoto();
        if (sameRing() && !proposedPeople) proposed=defaultSuggestion();
        if (returningToRequest) dirtyInput=true;
      }
      show();
      return;
    }
    if (zone!=='center') return;
    if ($('centerPhoto').open && planned?.route.featuredGuest) {
      planned=null; stage='original'; radio('stage',stage).checked=true;
    }
    if (!$('centerPhoto').open) $('seatedReveal').checked=false;
    if (!$('centerPhoto').open && (converting || portraitDraft)) editPhoto();
    else {
      show();
      if ($('centerPhoto').open && separatePhotos()) showSeatPhotos();
    }
  };
  $('portraitForm').onsubmit = async event => {
    event.preventDefault();
    const file=samplePhoto || $('portraitFile').files[0];
    const separate=separatePhotos();
    if (separate ? !seatsReady() : !file) return;
    if (zone==='middle') {
      if (groupGuestPhoto()) await previewAssignedPortraits();
      else await previewGuestPhoto();
      return;
    }
    if (zone!=='center') return;
    peopleBox.open=false;
    const request = ++photoRequest, group = separate || $('portraitMode').value === 'group';
    const prepared=$('portraitMode').value==='prepared';
    const groupShadows = group && !separate && $('portraitStyle').value === 'shadows';
    const groupStyle = separate ? 'seats' : groupShadows ? 'faces' : group ? $('portraitStyle').value : 'pose';
    const revealSeats = groupStyle==='seats' && $('seatedReveal').checked;
    const center=photoZone(), wide=center===wideCenter;
    const diameter=2*centerRadius(center);
    const portraitDiameterGrooves=diameter/groove, portraitDiameterMm=diameter*radiusMM;
    const captionName=$('photoCaption').disabled?'':$('photoCaption').value.trim();
    const automatic=!group && !prepared && $('soloStyle').value==='auto';
    const preferShadows=group ? groupShadows : $('soloStyle').value==='shadow' || (automatic && !captionName);
    const shadowSize=supportsPhotoShadows(), useShadows=prepared || (preferShadows && shadowSize);
    // Only conventional portraits share the same completely cleared midpoint.
    const previousRoute = portraitDraft?.route;
    const cleared = previousRoute && (previousRoute.centerMode==='widePortrait')===wide &&
      !previousRoute.interleaved && planned?.route === previousRoute ? planned : null;
    converting=true; $('portraitSubmit').disabled=true; show();
    $('portraitStatus').textContent = prepared ? 'Opening the prepared portrait…' : useShadows ? 'Tracing the shadows in the photo…' :
      ['faces','heads','seats'].includes(groupStyle) ? 'Arranging the faces…' : 'Finding the outlines in the photo…';
    try {
      const closeUp=group ? groupStyle==='heads' : automatic || $('soloStyle').value==='head';
      let route, caption, shadowNotice='';
      const options={group,groupStyle,foregroundFirst:group,portraitDiameterGrooves,portraitTrackingGrooves,face:faceChoice,groupFaces,seatOrder,
        fitShadowMarks:marks=>{route=OasisRingPlanner.shadowPhoto(center,marks,scene.live);},
        portraitFraming:closeUp ? 'framedHead' : undefined,portraitStyle:useShadows ? 'shadow' : 'line',portraitDiameterMm};
      let result=prepared ? {hasPortrait:true,facesDetected:1,
        ...await readPreparedPortrait(file,portraitDiameterMm,groove*radiusMM)} :
        await readPhoto(file,options,request,separate ? seatPhotos.map(({file,face})=>({file,face})) : undefined);
      if (request!==photoRequest || zone!=='center') return;
      if (revealSeats && result.groupStyle==='seats') route=OasisRingPlanner.seatedPhoto(center,result,scene.live);
      if (!route && useShadows && result.shadowMarks?.length) {
        try {
          const selection = group ? {faces:result.includedFaces.map((_,i)=>i)} : undefined;
          route=OasisRingPlanner.shadowPhoto(center,result.shadowMarks,scene.live,selection);
        }
        catch (error) { if (prepared) throw error; shadowNotice=error.message; }
      }
      // A rejected shadow plan contains a bust as its legacy fallback. Use the
      // selected person's full close-up when the guest asked for automatic fitting.
      if (automatic && useShadows && !route && result.hasPortrait) {
        result=await readPhoto(file,{...options,portraitStyle:'line'},request);
        if (request!==photoRequest || zone!=='center') return;
      }
      if (!separate && !prepared) showPhotoSource(file,result,group);
      if(captionName){
        if(!result.hasPortrait)throw Error('Choose or frame a face before adding a name under it.');
        caption=await GuestPortraitCaption.fit(result.points,captionName,groove/centerRadius(center));
        if(request!==photoRequest || zone!=='center')return;
      }
      if (!route && prepared && result.includesCenterRake) {
        route=OasisRingPlanner.preparedPhoto(center,result.points,scene.live,true);
      }
      if (!route) route=OasisRingPlanner.photo(center,caption?.points || result.points);
      if (wide) route.centerMode='widePortrait';
      const n=result.facesDetected;
      const together = result.groupStyle === 'faces' || result.groupStyle === 'heads' && n>1;
      const seats = result.groupStyle === 'seats' ? result.seatFaces.length : undefined;
      const count = n + (n === 1 ? ' face' : ' faces');
      const title = prepared ? 'Prepared portrait' : !result.hasPortrait ? 'Photo outlines' : group ? 'Group portrait · ' + count + (seats ? ' around the table' : route.interleaved ? ' in shadow' : together ? ' together' : '') :
        route.interleaved ? 'Guest portrait · photo shadows' : 'Guest portrait';
      portraitDraft={route,title:caption ? title+' · '+caption.label : title,seats,hasFace:result.hasPortrait && !prepared}; planned={route};
      if (groupEngraving && group && !separate && groupStyle==='heads' && !caption && shadowSize &&
          result.hasPortrait && [2,3,4].includes(result.includedFaces.length)) {
        portraitDraft.selectedFaces=result.includedFaces.map(({x,y,w})=>({x,y,w}));
      }
      if (cleared && !route.interleaved) Object.assign(planned,{clear:cleared.clear,clearImage:cleared.clearImage});
      stage='redrawn'; radio('stage',stage).checked=true;
      $('portraitStatus').textContent = route.includesCenterRake ? 'The portrait clears and draws the center in one pass.' :
        prepared && result.includesCenterRake ? 'The center will be cleared before this portrait.' :
        prepared ? 'The prepared portrait fits this center.' :
        !result.hasPortrait ? 'No face detected. Showing the outlines of the photo.' :
        (automatic && !route.interleaved || result.groupStyle === 'heads' && n === 1) ? 'Showing one face in close-up.' :
        groupStyle !== 'pose' && n === 1 ? 'One face ' + (groupFaces ? 'selected' : 'found') + '. Showing the original pose.' :
        seats ? seatDescription(result.seatFaces) :
        together ? count + ' arranged together in the center.' :
        group ? count + (groupFaces ? ' selected.' : ' found.') + ' Check the drawing before keeping it.' : 'Showing one person.';
      if (route.seatedReveal) $('portraitStatus').textContent='The faces take shape as the center clears. '+seatDescription(result.seatFaces);
      else if (route.interleaved && !route.includesCenterRake) $('portraitStatus').textContent=group ? 'The faces take shape as the old drawing clears.' : 'The face takes shape as the old drawing clears.';
      else if (!prepared && !automatic && preferShadows && result.hasPortrait && (!group || n > 1)) {
        const reason = !shadowSize ? 'This center is too small for separate shadow lines.' :
          shadowNotice || result.shadowReason || 'Too little shadow detail for this drawing.';
        const depiction = group ? (together ? 'Showing ' + (n === 2 ? 'both' : 'all ' + n) + ' faces in close-up.' : 'Showing the original group pose.') : 'Showing the outline.';
        $('portraitStatus').textContent = reason + ' ' + depiction;
      }
      if(group && result.distantFace && !groupFaces){
        $('portraitStatus').textContent+= ' Starting with '+n+' of '+result.faceBoxes.length+' faces. You can include the smaller face in the photo below.';
      }
      if(caption){
        $('portraitStatus').textContent+=' The sand will read “'+caption.label+'”.';
        if(caption.scale<1)$('portraitStatus').textContent+=' The portrait is '+Math.round(caption.scale*100)+'% of its size without the name.';
      }
      converting = false; show();
      const bowl = $('sand').closest('.bowl');
      const laptopPreview=event.submitter===$('photoTraceSubmit');
      if ((laptopPreview || event.submitter===$('portraitSubmit')) && bowl.getBoundingClientRect().bottom < 0) {
        bowl.scrollIntoView({block:'start'});
      }
      if (laptopPreview) {
        if ($('portraitHairField').hidden) $('portraitStatus').textContent+=laptopJpegs.has(file)
          ? ' The phone used the JPEG returned by the garden laptop.' : ' The photo stayed on this phone.';
        else if (result.facesDetected===1 || faceChoice!==null) await tracePortrait();
        else $('portraitStatus').textContent='Tap the face you want, then choose “'+photoTraceAction+'”.';
      }
    } catch(e) {
      if (request!==photoRequest) return;
      portraitDraft=null; planned=null; stage='original'; radio('stage',stage).checked=true;
      converting=false; show();
      $('portraitStatus').textContent=e.message || 'Could not read the photo.';
      if (event.submitter===$('photoTraceSubmit') && unreadablePhoto()) await openHeic(event.submitter);
    } finally {
      if (request===photoRequest) { converting=false; $('portraitSubmit').disabled=separate && !seatsReady(); }
    }
  };

  function resolve(text) {
    if (catalog?.subjects.temple_popup_book && popupBookRequest(text)) {
      return {id:'temple_popup_book',label:labels.temple_popup_book,singleSubject:true};
    }
    const native = GuestArt.catalogIdea(text, manifest);
    if (native) {
      const words = GuestArt.normalize(text);
      for (const [family,variant] of Object.entries(styles)) {
        if ((native !== family && native !== variant) || !labels[variant]) continue;
        const specific = words.includes(GuestArt.normalize(labels[variant])) ||
          words.includes(GuestArt.normalize(variant)) || (family === 'books' && words.includes('stack of books')) ||
          (family === 'pumpkin' && /\b(?:leafy|ribbed|field|five lobe) pumpkins?\b/.test(words)) ||
          (family === 'phage' && /\b(?:faceted|original) (?:bacterio)?phages?\b/.test(words)) ||
          (family === 'dna' && words.split(' ').includes('open')) ||
          (family === 'paper_crane' && words.includes('original'));
        if (!specific) return {id:native, label:labels[native], family};
      }
      return {id:native, label:labels[native]};
    }
    const symbol = GuestArt.glyphIdea(text);
    if (!symbol) return null;
    const id = 'symbol-' + Array.from(symbol.glyph, c => c.codePointAt(0).toString(16)).join('-');
    return {id, label:symbol.label, glyph:symbol.glyph};
  }
  const relationWords = {above:'above', below:'below', beside:'beside', behind:'behind', lean:'leaning against'};
  function subjectName(text) {
    return GuestArt.normalize(text).replace(/^(?:(?:please )?(?:draw|make|add) )?(?:(?:a|an|the|my) )?/, '') || text.trim();
  }
  function relationIn(text, single) {
    // “Telescope on a tripod” and “tennis racquet and ball” each name one drawing.
    if (single?.singleSubject) return null;
    if (single && single.id !== 'guitar_books' &&
        (subjectName(text) === GuestArt.normalize(single.label) || GuestArt.wholeSubject(text,single.id,manifest))) return null;
    return GuestArt.parsePair(text,true);
  }
  // Preserve spelling and combining marks, including Thai vowels and tones.
  // Only a complete saved name can replace the normal suggestion match.
  function drawingNameKey(label) {
    return label.normalize('NFC').trim().toLowerCase().replace(/\s+/gu,' ');
  }
  function requestSubject(text) {
    return text.trim().replace(/^(?:please\s+)?(?:draw|make|add|sketch)\s+/iu,'')
      .replace(/^(?:a|an|the)\s+/iu,'').trim();
  }
  function popupBookRequest(text) {
    // A book or a rooftop on its own, or a request for a particular placement,
    // still uses the ordinary subject or two-drawing path.
    if (!/\bbook\b/i.test(text)) return false;
    if (/['’]/u.test(text)) {
      const owners=book.people.map(person=>literalName(person.name)).sort((a,b)=>b.length-a.length);
      const possessive=new RegExp("(?:^|\\s)(?:"+owners.join('|')+")['’]s?\\s+",'giu');
      text=text.normalize('NFC').replace(possessive,' ');
    }
    return popupBookNames.test(GuestArt.normalize(requestSubject(text)));
  }
  function literalName(name) {
    return name.normalize('NFC').replace(/[.*+?^${}()|[\]\\]/g,'\\$&');
  }
  function portraitPerson(text) {
    const subject=requestSubject(text).replace(/^saved\s+/iu,'');
    if (/^(?:my\s+)?portrait$/iu.test(subject)) return '';
    const of=/^portrait\s+of\s+(.+)$/iu.exec(subject);
    const owner=/^(.+?)['’]s?\s+portrait$/iu.exec(subject);
    const person=(of || owner)?.[1].trim();
    return person && !GuestArt.parsePair(person,true) ? person : null;
  }
  function sameInk(a,b) {
    return a === b || (a.length === b.length && a.every(([x,y],i)=>x===b[i][0] && y===b[i][1]));
  }
  function sameDrawing(id,art) {
    return id===art.id || (custom[id] && custom[art.id] &&
      drawingNameKey(labels[id])===drawingNameKey(art.label) && sameInk(custom[id],custom[art.id]));
  }
  function refreshSavedPicker() {
    const drawings = keptDrawings();
    if (listedDrawings === drawings) return;
    listedDrawings = drawings;
    const groups = new Map();
    for (const art of drawings) {
      const key = drawingNameKey(art.label);
      if (!groups.has(key)) groups.set(key,[]);
      groups.get(key).push(art);
    }
    savedPicker.replaceChildren(new Option('Choose a saved drawing…',''));
    for (const versions of groups.values()) {
      versions.forEach(({id,label},i) => {
        const text = versions.length > 1 ? label+' ('+(i+1)+' of '+versions.length+')' : label;
        savedPicker.add(new Option(text,id));
      });
    }
    savedPicker.hidden = !drawings.length;
  }
  function refreshAdditions() {
    const select=$('guestAddition'), pick=$('target').value, options=[];
    for (const [place,base] of current.entries()) {
      if (pick && Number(pick)!==place) continue;
      for (const id of Object.keys(catalog.places?.[place]?.additions?.[base] || {})) {
        const art=decorations[id];
        if (art) options.push(new Option(book.active[place].name+' · Add a '+art.detail,place+'-'+id));
      }
    }
    select.hidden=!options.length;
    const prior=Array.from(select.options).slice(1);
    if (prior.length!==options.length || options.some((option,i)=>option.value!==prior[i].value || option.text!==prior[i].text))
      select.replaceChildren(new Option('Add to a drawing on the table…',''),...options);
  }
  $('guestAddition').onchange = () => {
    const select=$('guestAddition'), [place,id]=select.value.split('-'), art=decorations[id];
    if (!art) return;
    $('idea').value='Add a '+art.detail+' to '+book.active[place].name+'’s '+art.subject;
    select.value='';
    $('idea').dispatchEvent(new Event('input'));
    $('guestEditor').requestSubmit();
  };
  if (catalog?.pairMotifs) {
    const outline = id => catalog.pairMotifs[id] && OasisRingPlanner.unpack(catalog.pairMotifs[id]);
    GuestArt.thanksgivingPicker($('thanksgivingDrawings'),manifest,outline,art => {
      editingSuggestion();
      try {
        let guest;
        if ($('target').value === '') {
          const text = $('idea').value.trim();
          const req = GuestArt.splitRequest(text,book.active);
          if (namedGuestRequests(text) || (req.recipient && !req.guest))
            throw Error('Choose a guest for this Thanksgiving drawing.');
          guest = req.guest;
        }
        const slot = address({guest},[],art.id);
        previewGuestChoices([{slot,art}]);
        const bowl = $('sand').closest('.bowl');
        if (bowl.getBoundingClientRect().bottom < 0) bowl.scrollIntoView({block:'start'});
      } catch (error) { report(error); }
    },'sand');
  }
  function savedRequest(text, stock, {side, mayBePair=false} = {}) {
    const entire = drawingNameKey(text);
    const subject = entire.replace(/^(?:please )?(?:draw|make|add|sketch) /u,'');
    const bare = subject.replace(/^(?:a|an|the|my) /u,'');
    const explicit = bare.startsWith('saved ');
    const keys = explicit ? [bare.slice(6)] : [...new Set([entire,subject,bare])];
    const person=portraitPerson(bare);
    // Preserve exact saved titles first. A named face can also be requested
    // as “Lek's portrait”, or simply “Lek” if there is no stock drawing.
    const alias=person ?? (!stock && !mayBePair ? keys.at(-1) : '');
    const portraitKey=alias && 'portrait of '+alias;
    if (portraitKey && !keys.includes(portraitKey)) keys.push(portraitKey);
    for (const key of keys) {
      // A reviewed library reference can arrive after a guest kept their own
      // drawing under this name. Preserve that guest's previous lookup.
      if (!explicit && stock && !catalog.librarySubjects?.includes(stock.id) && [stock.label,stock.id,stock.family].some(s=>s && drawingNameKey(s)===key)) continue;
      const matches = keptDrawings().filter(art=>drawingNameKey(art.label)===key);
      const chosen=side && pairChoices?.text===$('idea').value && pairChoices[side];
      if (chosen && chosen.key===key) {
        const same=matches.find(art=>sameInk(custom[art.id],chosen.points));
        if (same) return same;
        if (!matches.length) throw Error('The selected version of “'+key+'” is no longer saved.');
      }
      if (matches.length === 1 && chosen?.key!==key) return matches[0];
      if (matches.length) {
        if (side) {
          if (pairChoices?.text!==$('idea').value) pairChoices={text:$('idea').value};
          pairChoices.pending={side,key};
        }
        savedPicker.value='';
        savedPicker.focus();
        if (side && matches.length===1) throw Error('The saved version of “'+matches[0].label+'” changed. Choose it again.');
        if (side) throw Error('You have '+matches.length+' drawings called “'+matches[0].label+'”. Choose a version for this request.');
        throw Error('You have '+matches.length+' drawings called “'+matches[0].label+'”. Choose a saved drawing to preview one.');
      }
    }
    if (explicit && !mayBePair) throw Error('That drawing is not in the saved guest drawings.');
    return null;
  }
  function pairParts(text, single) {
    const initial=relationIn(text,single);
    if (!initial) return null;
    // A complete saved title can itself contain “beside” or “and”. Hide that title
    // from the ordinary relation parser, then take both operands from the original.
    const words=drawingNameKey(text);
    let start=0, end=words.length;
    for (const art of keptDrawings()) {
      const name=drawingNameKey(art.label);
      if (!GuestArt.parsePair(name,true)) continue;
      const i=words.indexOf(name), j=words.length-name.length;
      if (i>=0 && !/[\p{L}\p{M}\p{N}]/u.test(words.charAt(i+name.length)) &&
          /^(?:(?:please )?(?:draw|make|add|sketch) )?(?:(?:a|an|the|my) )?(?:saved )?$/u.test(words.slice(0,i)))
        start=Math.max(start,i+name.length);
      if (j>0 && words.endsWith(name) && !/[\p{L}\p{M}\p{N}]/u.test(words[j-1])) end=Math.min(end,j);
    }
    if ((!start && end===words.length) || start>=end) return initial;
    const masked='x'.repeat(start)+words.slice(start,end)+'x'.repeat(words.length-end);
    const parts=GuestArt.parsePair(masked,true);
    return parts ? {...parts,left:words.slice(0,parts.left.length),right:words.slice(words.length-parts.right.length)} : initial;
  }
  function requestedArt(text, {chooseOperands=false, guestChoice='', allowWholePicture=false}={}) {
    const single=resolve(text), parts=pairParts(text,single);
    const saved=savedRequest(text,single,{mayBePair:!!parts,side:guestChoice});
    if (saved) return saved;
    const wording=requestSubject(text);
    const mix=/^(?:please\s+)?(?:combine|mix|blend)\s+(?:(?:the\s+)?interests?\s+of\s+(.+)|(.+?)\s+interests?)$/iu.exec(wording);
    if (mix) return combinedInterests(mix[1] || mix[2]);
    if (single?.singleSubject) return single;
    if (!catalog.subjects.temple_popup_book && popupBookRequest(text)) {
      const roof=resolve('Thai rooftop'), pages=resolve('open book');
      if (!roof || !pages) throw Error('This garden needs drawings for both the rooftop and the book.');
      return composePair(roof,pages,'beside');
    }
    if (!parts) {
      if (portraitPerson(text)!==null) return null;
      if (GuestArt.separatedSubjects(text,manifest)) {
        $('sketch').open=true;
        throw Error('Choose a placement such as “above” or “beside”, or sketch the two subjects together below.');
      }
      return single;
    }
    const {left,right} = parts;
    function operand(words,side) {
      const choice=chooseOperands && (guestChoice ? guestChoice+'-'+side : side);
      const stock=portraitPerson(words)===null ? resolve(words) : null, art=savedRequest(words,stock,{side:choice});
      return art ? {...art,points:custom[art.id]} : stock;
    }
    const a=operand(left,'left'), b=operand(right,'right');
    // A guest can bring a reference for the whole scene. Keep likenesses on the photo path.
    const wholePicture=allowWholePicture && left && right && !/\bportraits?\b/iu.test(text) &&
      !book.people.some(p=>[left,right].some(words=>drawingNameKey(requestSubject(words))===drawingNameKey(p.name)));
    function nested(words,art) {
      return !art?.points && !art?.singleSubject &&
        (relationIn(words,art) || GuestArt.separatedSubjects(words,manifest));
    }
    if (nested(left,a) || nested(right,b)) {
      if (wholePicture) return null;
      $('sketch').open=true;
      throw Error('Use two subjects in one place, or sketch the whole group below.');
    }
    if (!a || !b) {
      if (wholePicture) {
        const connector=drawingNameKey(text).slice(drawingNameKey(left).length,-drawingNameKey(right).length).trim();
        if ((a || b) && !['and','with',',',';','&'].includes(connector)) {
          return {pendingPair:{known:a || b,missing:requestSubject(a ? right : left),
            missingFirst:!a,relation:parts.relation}};
        }
        return null;
      }
      $('sketch').open=true;
      const missing = (a ? right : left).trim();
      throw Error((missing ? 'I couldn’t match “'+missing+'”. ' : 'Name both subjects. ')+
        'Try another word or sketch the two together below.');
    }
    return composePair(a,b,parts.relation);
  }
  function combinedInterests(sources) {
    const whole=book.find(sources);
    let people;
    if (whole) people=[whole];
    else {
      // A guest may be called “Rose and June”. Look for a division where
      // both complete names are in the book, including guests away from the ring.
      const divisions=[];
      for (const join of sources.matchAll(/\s+and\s+|\s*&\s*/giu)) {
        const left=sources.slice(0,join.index).trim(), right=sources.slice(join.index+join[0].length).trim();
        const a=book.find(left), b=book.find(right);
        divisions.push({left,right,a,b});
      }
      const matches=divisions.filter(({a,b})=>a && b);
      if (matches.length>1) throw Error('Those names match more than one pair. Use one guest’s interests or name the drawings.');
      if (!matches.length) {
        const known=divisions.find(({a,b})=>a || b);
        const missing=(known ? (known.a ? known.right : known.left) : sources).replace(/['’]s?$/iu,'');
        throw Error('I couldn’t find “'+missing+'” in the guest book. Add their name and interests first.');
      }
      const {a,b}=matches[0];
      people=a===b ? [a] : [a,b];
    }
    const ideas=people.map(person=>{
      const list=ideasFor(GuestArt.guestInterest(person));
      if (!list.length) throw Error('There is no drawing for '+person.name+'’s interests yet. Add an interest or name a drawing.');
      return list;
    });
    const first=ideas[0][0], second=ideas.length===2 ? ideas[1][0] : ideas[0].find(art=>art.id!==first.id);
    if (!second) throw Error('Choose a second guest or name a second drawing to combine with '+first.label+'.');
    const ids=[first.id,second.id];
    if (catalog.subjects.temple_popup_book && ids.some(id=>id==='books_open' || id==='books') &&
        ids.some(id=>id==='temple_gable' || id==='temple')) {
      return {id:'temple_popup_book',label:labels.temple_popup_book};
    }
    const operand=art=>isKeptDrawing(art.id) ? {...art,points:custom[art.id]} : art;
    return composePair(operand(first),operand(second),'beside');
  }
  function composePair(a,b,placement) {
    if ((a.family || a.id) === 'guitar' && (b.family || b.id) === 'books' &&
        placement === 'lean' && labels.guitar_books) {
      return {id:'guitar_books', label:labels.guitar_books, anchors:[b,a]};
    }
    const reverseAs = {right:'beside', front:'behind', below:'above'};
    const reversed = Object.hasOwn(reverseAs,placement);
    const relation = reversed ? reverseAs[placement] : placement;
    const [first,second] = reversed ? [b,a] : [a,b];
    const handmade=first.points || second.points;
    const id = handmade ? null : 'pair-'+relation+'-'+first.id+'__'+second.id;
    function name(art,initial) {
      if (art.points) return art.label;
      const label=art.label === 'Guest drawing' ? art.glyph : art.label;
      if (initial) return label[0].toUpperCase()+label.slice(1);
      if (/^(?:Thai|Thailand|Aztec|Hunt|T\. rex|Velociraptor)\b|^[A-Z]{2}/.test(label)) return label;
      return label[0].toLowerCase()+label.slice(1);
    }
    const label = name(first,true)+' '+relationWords[relation]+' '+name(second,false);
    if (id?.length > 160 || [...label].length > 180) {
      $('sketch').open=true;
      throw Error('Choose shorter symbols, or sketch the two subjects together below.');
    }
    if (handmade) {
      let points;
      try { points=OasisRingPlanner.pair(catalog,first,second,relation); }
      catch (error) { $('sketch').open=true; throw error; }
      const prior=Object.keys(custom).find(key=>eligibleDrawingName(key,labels[key])===drawingNameKey(label) &&
        sameInk(custom[key],points));
      return {id:prior || null,label,points,anchors:[b,a]};
    }
    return {id,label,first,second,relation,anchors:[b,a]};
  }
  function sameSubject(id, art) {
    return art && (sameDrawing(id,art) || (art.family && (id === art.family || id === styles[art.family])));
  }
  function address(req,anchors = [], newSubject) {
    const pick = $('target').value;
    const named = req.guest ? book.active.indexOf(req.guest) : -1;
    let from = -1;
    if (req.from) {
      const name = subjectName(req.from);
      const precise = drawingNameKey(req.from).replace(/^(?:a|an|the|my) /u,'');
      const exact = current.filter(id => id.startsWith('sketch-') ?
        drawingNameKey(labels[id]).replace(/^(?:a|an|the|my) /u,'')===precise : subjectName(labels[id])===name);
      // A saved sketch can have any name, including words like "above".
      // A generic stock name can refer to either engraving on the sand.
      const match = exact.length ? (exact.some(id=>catalog.subjects[id]) ? resolve(req.from) : null) :
        requestedArt(req.from);
      const hits = current.map((id,i) => exact.includes(id) || sameSubject(id,match) ? i : -1).filter(i=>i>=0);
      if (!hits.length) throw Error('That drawing is no longer in the guest ring.');
      if (hits.length > 1 && pick === '' && named < 0) throw Error('Two guests have that drawing. Choose the guest you mean.');
      from = hits.includes(Number(pick)) && pick !== '' ? Number(pick) : hits.includes(named) ? named : hits[0];
    }
    const targets = [pick === '' ? -1 : Number(pick), named, from].filter(i => i >= 0);
    if (!targets.length) {
      for (const anchor of anchors) {
        const hits = current.map((id,i)=>sameSubject(id,anchor) ? i : -1).filter(i=>i>=0);
        if (hits.length>1) throw Error('Two guests have that drawing. Choose the guest you mean.');
        if (hits.length) return hits[0];
      }
    }
    if (!targets.length && newSubject) {
      const musician=GuestArt.musicGuest(book.active,newSubject,manifest);
      if (musician) return book.active.indexOf(musician);
    }
    if (!targets.length && newSubject !== undefined && openSubject) {
      // An unnamed request can take a vacant place. Keep existing drawings on
      // display, preferring the guest whose stated interests match the request.
      const vacant = current.map((id,i)=>id===openSubject ? i : -1).filter(i=>i>=0);
      if (vacant.length) {
        const match = vacant.find(i=>ideasFor(GuestArt.guestInterest(book.active[i]))
          .some(idea=>idea.id===newSubject || anchors.some(art=>sameSubject(idea.id,art))));
        return match ?? vacant[0];
      }
    }
    if (!targets.length) throw Error('Choose a guest, or add their name to the suggestion.');
    if (!targets.every(i => i === targets[0])) throw Error('The guest and drawing point to different places. Choose the intended guest.');
    return targets[0];
  }

  // Start the contour at a point on the subject itself, so no lead-in is cut through it.
  function closedPath(lines, options) {
    const entry = lines.flat().reduce((far,p) => p[1] > far[1] ? p : far);
    return GuestArt.manageStrokes(lines,entry,options);
  }
  function editingSuggestion() {
    suggestionVersion++;
    if (requestedPhoto) resetPhoto();
    clearError();
    dirtyInput = true; proposedPeople = null;
    planned = null; stage = 'original'; radio('stage',stage).checked = true;
    show();
  }
  function resetSketch() {
    paths.length = 0; stroke = null; paintPad(); $('sketch').open = false;
  }
  function readSketch(label,slot) {
    const lines = paths.map(GuestArt.sketchStroke).filter(line => line.length > 1);
    if (!lines.length) throw Error('Draw a stroke in the sketch pad first.');
    const path=closedPath(lines,{joinEdges:true,pointLimit:8000,
      finish:points=>OasisRingPlanner.fitsGuestTravel(points,slot,catalog.geometry) ? points : null});
    return customDrawing(path,label || 'Guest sketch');
  }
  function customDrawing(path,label) {
    while (Object.hasOwn(custom,'sketch-' + (sketchNumber+1))) sketchNumber++;
    const id = 'sketch-' + (++sketchNumber);
    custom[id] = path;
    return {id,label};
  }
  function discardDraftPhoto() {
    for (const id of draftPhotoIds) { delete custom[id]; delete labels[id]; }
    draftPhotoIds=[];
  }
  function readGuestPhoto(file, face, request, object=false) {
    return readPhoto(file,{face,object,objectFrame,includeBackground:object && $('includeBackground').checked,
      portraitFraming:object ? undefined : $('guestPortraitFrame').value,
      portraitDiameterGrooves:2*catalog.geometry.scale/scene.live.groove,portraitTrackingGrooves},request);
  }
  function guestPhotoArt(result, person, slot, object=false, pair=null) {
    if (object && result.points.length<4) throw Error(result.message || 'Frame a subject with a clearer outline.');
    if (!object && !result.hasPortrait) throw Error('Frame a face in the source photo to preview it in this place.');
    // The converter starts and returns at its own rim. Each guest place connects
    // the outermost point of the drawing to its rail.
    let points=result.points.slice(1,-1);
    if (pair) {
      const traced={label:pair.missing,points,generated:true};
      const first=pair.missingFirst ? traced : pair.known;
      const second=pair.missingFirst ? pair.known : traced;
      points=composePair(first,second,pair.relation).points;
    }
    const label=object ? $('objectName').value.trim() || 'Photo drawing' :
      person ? 'Portrait of '+person : 'Portrait from photo';
    const previous=current[slot];
    if (labels[previous]===label && JSON.stringify(custom[previous])===JSON.stringify(points)) return previous;
    const art=customDrawing(points,label);
    labels[art.id]=label;
    draftPhotoIds.push(art.id);
    return art.id;
  }
  async function previewAssignedPortraits() {
    const file=$('portraitFile').files[0];
    if (selected.widePortrait || !file || !assignmentScan || assignments.check() || $('sourceFrame').classList.contains('framing')) return;
    const chosen=assignments.selected();
    editPhoto(true);
    const request=++photoRequest;
    converting=true; show();
    $('portraitStatus').textContent='Fitting the faces to their guest places…';
    try {
      const next=current.slice();
      for (const {slot,face,person} of chosen) {
        const result=await readGuestPhoto(file,face,request);
        if (request!==photoRequest) return;
        next[slot]=guestPhotoArt(result,person,slot);
      }
      if (!draftPhotoIds.length) throw Error('Those portraits are already in the selected places.');
      const route=OasisRingPlanner.planChange(catalog,current,next,custom,true);
      route.placePhoto='group';
      enlarged=false; clearRoomFiles(); converting=false;
      $('portraitStatus').textContent='Showing portraits for '+chosen.map(a=>book.active[a.slot].name).join(' / ')+'.';
      previewRing(next,null,route);
      const bowl=$('sand').closest('.bowl');
      if (bowl.getBoundingClientRect().bottom<0) bowl.scrollIntoView({block:'start'});
    } catch (error) {
      if (request===photoRequest) { discardDraftPhoto(); $('portraitStatus').textContent=error.message; }
    } finally {
      if (request===photoRequest) { converting=false; show(); }
    }
  }
  async function previewGuestPhoto() {
    if (selected.widePortrait) return;
    const file=samplePhoto || $('portraitFile').files[0], slot=Number($('portraitPlace').value);
    const origin=zone, direct=zone==='middle';
    const object=direct && $('guestPhotoKind').value==='object';
    const person=object ? '' : $('portraitName').value.trim().replace(/\s+/gu,' ').normalize('NFC');
    if (!file || !catalog?.places?.[slot] || (!direct && (zone!=='center' || !portraitDraft?.hasFace))) return;
    discardDraftPhoto();
    const request=++photoRequest;
    if (direct) {
      proposed=current.slice(); proposedPeople=null; planned=null;
      stage='original'; radio('stage',stage).checked=true;
    }
    converting=true; $('portraitSubmit').disabled=true; show();
    $('portraitStatus').textContent=object ? 'Tracing the subject for this place…' : 'Fitting the face to the guest ring…';
    try {
      const result=await readGuestPhoto(file,faceChoice,request,object);
      if (request!==photoRequest || zone!==origin) return;
      if (direct) showPhotoSource(file,result,false,object);
      if (person && faceChoice===null && result.facesDetected>1) {
        $('portraitSource').open=true;
        $('faceBoxes').querySelector('button')?.focus();
        throw Error('Tap '+person+' in the source photo to choose the face for this portrait.');
      }
      // A replacement file chosen by the guest depicts their entire requested scene.
      const pair=object && file===requestedPhoto?.generatedFile ? requestedPhoto.pair : null;
      const id=guestPhotoArt(result,person,slot,object,pair), label=labels[id];
      if (id===current[slot]) throw Error('This '+(object ? 'drawing' : 'portrait')+' is already in that guest’s place.');
      const next=current.slice(); next[slot]=id;
      const route=guestChange(next);
      if (route.place!==slot) {
        throw Error('This photo would require clearing the whole guest ring.');
      }
      zone='middle'; radio('zone',zone).checked=true;
      peopleBox.open=false; enlarged=false; clearRoomFiles(); converting=false;
      route.placePhoto=object ? 'object' : 'face';
      if (direct) {
        $('portraitStatus').textContent=(object || person ? 'Showing '+label+' in ' : 'Showing the selected face in ')+book.active[slot].name+'’s place.';
      } else {
        draftPhotoIds=[];  // Move the draft from the center editor to the guest editor.
        resetPhoto();
        draftPhotoIds=[id];
      }
      previewRing(next,null,route);
      const bowl=$('sand').closest('.bowl');
      if ((!direct || !$('portraitSource').open) && bowl.getBoundingClientRect().bottom<0) bowl.scrollIntoView({block:'start'});
    } catch (error) {
      if (request===photoRequest) { discardDraftPhoto(); $('portraitStatus').textContent=error.message; }
    } finally {
      if (request===photoRequest) { converting=false; $('portraitSubmit').disabled=false; show(); }
    }
  }
  $('previewPlacePortrait').onclick = previewGuestPhoto;
  function prepareArt(art) {
    if (!art.id && art.points) art.id=customDrawing(art.points,art.label).id;
    if (art.first && !custom[art.id]) {
      try { custom[art.id] = OasisRingPlanner.pair(catalog,art.first,art.second,art.relation); }
      catch (error) { $('sketch').open=true; throw error; }
    }
    if (art.glyph && !custom[art.id]) custom[art.id] = closedPath(GuestArt.glyphStrokes(art.glyph));
    labels[art.id] ??= art.label;
  }
  function previewRing(next, lineup, route=current.every((id,i)=>id===next[i]) ? null : guestChange(next)) {
    clearError();
    const changes = next.map((id,i) => id !== current[i] ? i : -1).filter(i => i >= 0);
    guestFocus = changes.length === 1 ? changes[0] : -1;
    proposed = next; proposedPeople = lineup; planned = route && {route};
    if (planned && guestFocus>=0) {
      const id=next[guestFocus];
      if (custom[id] && eligibleDrawingName(id,labels[id])) {
        planned.drawingInterests={id,text:drawingInterest(id)};
      }
    }
    dirtyInput = false; stage = 'redrawn'; radio('stage',stage).checked = true;
    show();
  }
  function previewGuests(active, art) {
    prepareArt(art);
    previewRing(active.map(p => p.subject), active);
  }
  let telescopeExample = initial && location.hash === '#example-telescope' && !!catalog?.subjects.telescope;
  peopleBox.ontoggle = () => {
    if (!book) return;
    suggestionVersion++;
    resetSketch(); guestForm.updateSketch();
    if (zone !== 'middle') return;
    clearError(); proposedPeople = null; proposed = defaultSuggestion(); planned = null;
    dirtyInput = peopleBox.open || !!$('idea').value.trim();
    stage = 'original'; radio('stage',stage).checked = true; show();
    if (peopleBox.open && telescopeExample) {
      telescopeExample = false; guestForm.previewTelescope();
    }
  };
  $('idea').oninput = () => { savedPicker.value=''; pairChoices=null; editingSuggestion(); };
  $('target').onchange = editingSuggestion;
  savedPicker.onchange = () => {
    editingSuggestion();
    if (!savedPicker.value) return;
    try {
      if (pairChoices?.text===$('idea').value && pairChoices.pending) {
        const {side,key}=pairChoices.pending;
        const art=keptDrawings().find(d=>d.id===savedPicker.value);
        if (!art || drawingNameKey(art.label)!==key) throw Error('Choose a version of “'+key+'” for this request.');
        pairChoices[side]={key,points:custom[art.id]};
        pairChoices.pending=null; savedPicker.value='';
        $('guestEditor').requestSubmit();
        return;
      }
      // Carry the named guest or replacement across when choosing between
      // two versions. The resolved destination stays visible in the form.
      const req = GuestArt.splitRequest($('idea').value.trim(),book.active);
      if (!req.guest && /\sfor\s+[^,]+$/i.test(req.to)) throw Error('Choose someone in the guest ring.');
      const slot = address(req,[],savedPicker.value);
      $('target').value=String(slot); $('idea').value=''; $('sketch').open=false;
      $('guestEditor').requestSubmit();
    } catch (e) { report(e); }
  };

  function samePhotoPlace(intent) {
    if (book.active[intent.slot]?.name!==intent.guest) return false;
    const from=intent.from, id=current[intent.slot];
    return !from || (id===from.id && labels[id]===from.label &&
      JSON.stringify(custom[id])===JSON.stringify(from.path));
  }
  function showSuggestionSources() {
    $('wideSuggestion').hidden=$('guestEditor').hidden || wideSuggestionVersion!==suggestionVersion;
    const offered=!$('guestEditor').hidden && offeredPhoto?.version===suggestionVersion;
    $('suggestionPhoto').hidden=!offered;
    const generate=$('generateSuggestion');
    generate.hidden=!offered || !phraseEndpoint || offeredPhoto.person!==undefined;
    generate.disabled=!!offeredPhoto?.generating;
    if (!generate.hidden) generate.textContent='Generate a preview for '+offeredPhoto.guest;
    const status=$('phraseStatus');
    status.textContent=offeredPhoto?.phraseMessage || '';
    status.hidden=generate.hidden || !status.textContent;
  }
  function offerSuggestionPhoto(req,version,pair=null) {
    $('sketch').open=true;
    if (!photoPlaces || !req.to.trim()) return false;
    const words=requestSubject(req.to);
    if (!words) return false;
    const slot=address(req,pair ? [pair.known] : [],null);
    if (!catalog.places[slot]) return false;
    const person=portraitPerson(words) ?? book.people.find(p=>drawingNameKey(p.name)===drawingNameKey(words))?.name;
    if (person && person.length>$('portraitName').maxLength) throw Error('Use a shorter name for this portrait.');
    const label=person===undefined ? words[0].toUpperCase()+words.slice(1) : person ? 'Portrait of '+person : 'Portrait';
    const tiedToDrawing=req.from || (!req.guest && $('target').value==='');
    const id=current[slot], from=tiedToDrawing ? {id,label:labels[id],path:custom[id]} : null;
    offeredPhoto={version,slot,guest:book.active[slot].name,label,from,person,pair};
    const button=$('suggestionPhoto');
    button.textContent='Draw “'+label+'” for '+offeredPhoto.guest+' from a photo';
    showSuggestionSources();
    if (!$('generateSuggestion').hidden && !paths.length) $('sketch').open=false;
    ($('generateSuggestion').hidden ? button : $('generateSuggestion')).focus();
    return true;
  }
  function currentPhotoOffer(intent) {
    return !editorClosed && intent && offeredPhoto===intent && intent.version===suggestionVersion &&
      !$('guestEditor').hidden && samePhotoPlace(intent);
  }
  function openSuggestionPhoto(intent,file) {
    resetPhoto();
    if (file) intent.generatedFile=file;
    requestedPhoto=intent; offeredPhoto=null;
    clearError();
    refreshPhotoPlaces();
    $('portraitPlace').value=String(requestedPhoto.slot);
    const face=requestedPhoto.person!==undefined;
    $('guestPhotoKind').value=face ? 'face' : 'object';
    if (face) $('portraitName').value=requestedPhoto.person;
    else $('objectName').value=requestedPhoto.label;
    const panel=$('centerPhoto'), field=$('portraitFile');
    if (file) {
      const transfer=new DataTransfer();
      transfer.items.add(file);
      field.files=transfer.files;
      field.dispatchEvent(new Event('change'));
      // Opening the photo panel selects the destination and resets its old
      // preview. Start the new preview after that normal transition finishes.
      panel.addEventListener('toggle',()=>{
        if (!editorClosed && panel.open && requestedPhoto===intent && field.files[0]===file)
          $('portraitForm').requestSubmit();
      },{once:true});
    }
    panel.open=true;
    show();
    if (!file) field.focus();
  }
  function previewWideMixer() {
    try {
      if (room?.changed) throw Error('The garden changed. Load the latest drawing and preview the mixer again.');
      const route=OasisRingPlanner.reviewedMixer(wideCenter,scene.live);
      resetPhoto();
      radio('zone','center').click();
      $('portraitArea').value='wide';
      portraitDraft={route,title:wideCenter.standMixer.label};
      planned={route,requestInCenter:true};
      stage='redrawn'; radio('stage',stage).checked=true;
      show();
      $('sand').closest('.bowl').scrollIntoView({block:'start'});
    } catch (error) { report(error); }
  }
  $('previewWideSuggestion').onclick = () => {
    if (wideSuggestionVersion===suggestionVersion && wideCenter?.standMixer && zone==='middle') previewWideMixer();
  };
  $('suggestionPhoto').onclick = () => {
    if (currentPhotoOffer(offeredPhoto)) openSuggestionPhoto(offeredPhoto);
  };
  $('generateSuggestion').onclick = async () => {
    const intent=offeredPhoto;
    if (!phraseEndpoint || !currentPhotoOffer(intent) || intent.person!==undefined || intent.generating) return;
    intent.generating=true;
    const subject=intent.pair?.missing || intent.label;
    intent.phraseMessage='Making “'+subject+'” on the drawing computer. This usually takes 1–3 minutes.';
    showSuggestionSources();
    try {
      const response=await fetch(phraseEndpoint,{method:'POST',headers:{'Content-Type':'application/json'},
        body:JSON.stringify({phrase:subject})});
      if (!response.ok) {
        const problem=await response.json().catch(()=>null);
        throw Error(problem?.error || 'The drawing computer could not make this preview. Try again.');
      }
      const png=await response.blob();
      if (!currentPhotoOffer(intent)) return;
      if (room.changed && !room.untouched(room.latest,intent.slot))
        throw Error('This guest’s place changed. Load the latest garden and preview the suggestion again.');
      if (png.type!=='image/png' || !png.size) throw Error('The drawing computer returned no picture. Try again.');
      openSuggestionPhoto(intent,new File([png],'guest-illustration.png',{type:png.type}));
    } catch (error) {
      if (currentPhotoOffer(intent)) intent.phraseMessage=error.message || 'Could not reach the drawing computer. Try again.';
    } finally {
      intent.generating=false;
      if (!editorClosed) showSuggestionSources();
    }
  };
  function offerOpenPlaces(req) {
    if (!openSubject) return false;
    const text = GuestArt.normalize(req.to);
    if (/^(?:(?:clear|open) (?:all (?:three )?(?:guest )?places|the guest places)|leave all (?:three )?(?:guest )?places open)$/.test(text)) {
      if (current.every(id=>id===openSubject)) throw Error('All three guest places are already open.');
      previewRing(current.map(()=>openSubject),null);
      return true;
    }
    const owner = /^(?:clear|open) (.+) place$/.exec(text)?.[1] || /^leave (.+) place open$/.exec(text)?.[1];
    if (!owner) return false;
    let guest = req.guest;
    if (!['my','this','the','that'].includes(owner)) {
      const named = book.active.find(person=>GuestArt.normalize(person.name)===owner);
      if (!named || (guest && guest!==named)) throw Error('Choose a guest who has a place in the ring.');
      guest = named;
    }
    const place = address({...req,guest});
    if (current[place]===openSubject) throw Error(book.active[place].name+'’s place is already open.');
    const drawings = current.slice();
    drawings[place] = openSubject;
    previewRing(drawings,null);
    return true;
  }
  $('openGuestPlaces').onclick = () => {
    $('idea').value = 'Open all three places';
    $('guestEditor').requestSubmit();
  };
  function initialHeartRequest(text) {
    const plain=text.trim().replace(/[.!?]+$/u,'').replace(/^(?:please\s+)?(?:draw|make|sketch|put|write)\s+/iu,'');
    const addressed=/^(.+?)\s+for\s+(.+)$/iu.exec(plain);
    const subject=addressed ? addressed[1] : plain;
    const heart=/^(?:a |the )?heart (?:with|containing|around) (.+?)(?: (?:inside|in it|in the middle|in the center))?$/iu.exec(subject) ||
      /^(.+?) (?:in|inside) (?:a |the )?heart$/iu.exec(subject);
    if (!heart) return null;
    const payload=heart[1].trim();
    const own=/^(?:my|their) initial$/iu.test(payload);
    const prefix=/^(?:(?:the|our|my|their) )?initials?\s+/iu;
    const letters=payload.replace(prefix,'');
    // Two ordinary lowercase words, or extra details after the initials,
    // belong to the general picture request. Never drop them to make a monogram.
    const pair=/^([a-z])(?:\s*(?:&|\+)\s*|\s+and\s+|\s+)([a-z])$/i.exec(letters);
    const compact=prefix.test(payload) ? /^[a-z]{1,2}$/i : /^(?:[a-zA-Z]|[A-Z]{2})$/;
    if (!own && !pair && !compact.test(letters)) return null;
    return {heart:true,ownInitial:own,words:own ? '' : (pair ? pair[1]+pair[2] : letters).toUpperCase(),
      recipient:addressed?.[2],quoted:false};
  }
  function letteringRequest(text) {
    const heart=initialHeartRequest(text);
    if (heart) return heart;
    const command = /^(?:please\s+)?write\b\s*(.*)$/iu.exec(text);
    if (!command) return null;
    let words = command[1].trim().replace(/^the\s+(?:word|words|name)\s+/i,'');
    // Quoted text is literal, including a word such as “for” inside a greeting.
    const quoted = /^["“'‘]/u.test(words);
    let recipient;
    if (quoted) {
      const parts = /^(?:"([^"]*)"|“([^”]*)”|'(.*?)'|‘(.*?)’)(?:\s+for\s+(.+))?[.!?]?$/iu.exec(words);
      if (!parts) throw Error('Close the quotation marks around the lettering. Add “for” and the guest’s name after them.');
      words = parts.slice(1,5).find(s=>s!==undefined).trim();
      recipient = parts[5];
    } else {
      const addressed = /^(.+)\s+for\s+(.+)$/iu.exec(words);
      if (addressed) { words=addressed[1].trim(); recipient=addressed[2]; }
    }
    if (!words) throw Error('Enter a name or short greeting to write.');
    return {words,recipient,quoted};
  }
  async function letterArt(request,version,namedGuest=null) {
    const {recipient,quoted} = request;
    let words = request.words;
    // Keep combining marks in names. A Thai tone mark can distinguish two guests.
    const nameKey = name => name.normalize('NFC').toLowerCase().trim();
    const findGuest = name => book.active.find(p=>nameKey(p.name)===nameKey(name));
    let guest = namedGuest || (recipient && (findGuest(recipient) || findGuest(recipient.replace(/[.!?]+$/u,''))));
    if (recipient && !guest) throw Error('Choose a guest who has a place in the ring.');
    const ownName = !quoted && /^(?:my|their) name$/iu.test(words);
    if (!guest && !ownName && !request.heart && $('target').value==='') guest=findGuest(words);
    const slot = address({from:'',guest}, [], ownName || request.ownInitial ? undefined : 'lettering');
    if (!catalog.places?.[slot])
      throw Error('Lettering needs a garden with individually changeable guest places.');
    if (ownName) words = book.active[slot].name;
    if (request.ownInitial) {
      const initial=Array.from(book.active[slot].name.trim())[0] || '';
      if (!/^[A-Za-z]$/.test(initial)) throw Error('Type an initial from A to Z for this heart.');
      words=initial.toUpperCase();
    }
    const options = {groove:scene.live.groove/catalog.geometry.scale};
    let design;
    if (request.heart) design=GuestLettering.inHeart(words,options);
    else if (/\p{Script=Thai}/u.test(words)) {
      const before = bed;
      const stale = () => version!==suggestionVersion || !main.isConnected || $('guestEditor').hidden;
      try { design = await GuestThaiLettering.design(words,options); }
      catch (error) { if (stale()) return; throw error; }
      if (stale()) return;
      if (before!==bed) throw Error('The garden changed. Preview the lettering again in the current drawing.');
    } else design = GuestLettering.design(words,options);
    if (!design.legible) throw Error(design.reason || 'Try a shorter greeting or initials so each letter has room.');
    const label = request.heart ? 'Heart with '+design.label : '“'+design.label+'”';
    const path = JSON.stringify(design.path);
    const matches = id => labels[id]===label && JSON.stringify(custom[id])===path;
    const previous = Object.keys(custom).find(matches);
    return {slot,art:previous ? {id:previous,label} : {label,points:design.path}};
  }
  async function previewLettering(request,version) {
    if ($('sketch').open && paths.some(line=>line.length>1))
      throw Error('Close the sketch to preview lettering, or preview your sketch with its own name.');
    const result=await letterArt(request,version);
    if(!result || version!==suggestionVersion)return;
    const {slot,art}=result, previous=art.id;
    if(previous===current[slot])throw Error('That lettering is already in this guest’s place.');
    prepareArt(art);
    const next = current.slice();
    next[slot] = art.id;
    try {
      const route = guestChange(next);
      if (route.place!==slot)
        throw Error('This lettering needs more space. Try a shorter greeting or initials.');
      previewRing(next,null,route);
    } catch (error) {
      if (!previous) { delete custom[art.id]; delete labels[art.id]; }
      throw error;
    }
  }
  function previewRequestedBorder(req) {
    if (!borderPicker) return false;
    const words = subjectName(req.to.replace(/^(?:please\s+)?(?:put|place)\s+/i,''));
    const fromBorder = /^(?:border|rim|outer ring)$/.test(subjectName(req.from));
    const named = /^(?:border|outer ring) of (.+)$/.exec(words) ||
      /^(.+?) (?:border|around (?:the )?(?:rim|edge|border|outer ring|table))$/.exec(words);
    if (!named && !fromBorder) return false;
    if (req.from && !fromBorder) throw Error('Choose the border itself to replace it.');
    if (paths.length && $('sketch').open) throw Error('Choose a guest place for the sketch, or close it to preview the border.');
    const wanted = named?.[1] || words;
    const aliases = {'autumn leaf':'autumn leaves', 'fall leaves':'autumn leaves', 'maple and oak leaves':'autumn leaves',
      'thai roofs':'thai roof peaks', 'wheat':'wheat garland', 'lotus':'lotus buds', 'waves':'crossing tides'};
    const guestDesign=hasGuestBorder && ['guest drawings','the guest drawings','guests drawings'].includes(wanted);
    const index = guestDesign ? guestBorderIndex : borders.findIndex(name=>GuestArt.normalize(name)===(aliases[wanted] || wanted));
    if (!guestDesign && index<0) throw Error('Choose one of these borders. '+[...borders,...(hasGuestBorder ? [guestBorderTitle] : [])].join(', ')+'.');
    const sources=guestDesign ? guestBorderSources() : null;
    if (sources && !sources.some(Boolean)) throw Error('Keep at least one guest drawing before making this border.');
    if (sources && sources.some(art=>art && !art.points)) throw Error('A guest drawing has no outline in this garden.');
    const selectedGuest = $('target').value==='' ? null : book.active[Number($('target').value)];
    if (selectedGuest && req.guest && selectedGuest!==req.guest)
      throw Error('The named guest and the selected guest differ. Choose the intended guest.');
    const owner = (req.guest || selectedGuest)?.name ?? selected.borderGuest;
    if (borderIsCurrent(index,sources) && owner===selected.borderGuest) throw Error('That border is already on display.');
    radio('zone','outer').click();
    $('editBorderPlace').checked=false;
    $('borderDesign').value=String(index); $('borderGuest').value=owner;
    $('borderOrder').value='progressive';
    // The border form now holds the editable preview, including its owner.
    $('idea').value=''; $('target').value=''; dirtyInput=false;
    editBorder(); $('borderForm').requestSubmit();
    return true;
  }
  function splitGuestRequest(text) {
    const req=GuestArt.splitRequest(text,book.active);
    if (req.recipient && !req.guest) return req;
    const simple=/^(?:please\s+)?add\s+(.+)$/iu.exec(req.to.trim());
    if (simple) {
      const detail=subjectName(simple[1]);
      const entry=Object.entries(decorations).find(([,art])=>art.details.includes(detail));
      if (entry) {
        if (!catalog.subjects[entry[0]]) throw Error('This addition is unavailable in this layout.');
        return {...req,decoration:entry[0],add:true};
      }
    }
    // “Book with a pencil” names the whole picture. “Add a pencil to the
    // book” or a named owner's drawing asks to keep the existing picture.
    const phrase=/^(?:(?:please\s+)?(add|put|place|draw|make)\s+)?(.+?)\s+(to|onto|on|over|above|beside|next to|across|resting on|with)\s+(.+)$/iu.exec(req.to.trim());
    if (!phrase) return req;
    const withDetail=phrase[3].toLowerCase()==='with' &&
      !Object.values(decorations).some(art=>art.details.includes(subjectName(phrase[2])));
    const detail=subjectName(withDetail ? phrase[4] : phrase[2]);
    let base=(withDetail ? phrase[2] : phrase[4]).trim();
    const owner=/^(.+?)['’]s?\s+(.+)$/iu.exec(base);
    if (owner) base=owner[2];
    const namedBase=subjectName(base).replace(/^(?:existing|current) /,'');
    const position=phrase[3].toLowerCase(), adding=/^(?:add|put|place)$/i.test(phrase[1] || '');
    const baseMatches=art=>art.subjects.includes(namedBase) || (labels[art.base] && namedBase===GuestArt.normalize(labels[art.base]));
    const entry=Object.entries(decorations).find(([,art])=>art.details.includes(detail) &&
      (['to','onto','on','with'].includes(position) || art.positions.includes(position)) && baseMatches(art));
    const add=!!owner || (!withDetail && adding);
    if (!entry) {
      const baseArt=Object.values(decorations).find(baseMatches);
      if (add && (owner || ['to','onto'].includes(position)) &&
          ((owner && adding) || baseArt || Object.values(decorations).some(art=>art.details.includes(detail))))
        throw Error('That decoration is unavailable for this drawing.'+(baseArt ? ' The '+baseArt.subject+' can take a '+baseArt.detail+'.' : ''));
      return req;
    }
    if (!add && keptDrawings().some(art=>drawingNameKey(art.label)===drawingNameKey(requestSubject(req.to)))) return req;
    if (!add && !withDetail && position!=='with' && !entry[1].positions.includes(position)) return req;
    const [id]=entry;
    if (!catalog.subjects[id]) throw Error('This decorated picture is unavailable in this layout.');
    if (owner) {
      const name=owner[1].trim(), guest=book.active.find(p=>drawingNameKey(p.name)===drawingNameKey(name));
      if (!guest) throw Error('There is no guest called “'+name+'” in the ring.');
      if (req.recipient && req.guest!==guest) throw Error('The named guests point to different places.');
      req.guest=guest; req.recipient=guest.name;
    }
    return {...req,decoration:id,add};
  }
  function decoratedChoice(req) {
    const {base,detail,subject}=decorations[req.decoration];
    const complete='Ask for “'+labels[req.decoration]+'” to draw the whole picture.';
    if (req.add && !req.guest && !req.from && $('target').value==='' && !current.includes(base)) {
      if (current.includes(req.decoration)) throw Error('The '+detail+' is already on the sand.');
      throw Error('There is no matching '+subject+' in the guest ring. '+complete);
    }
    const slot=address(req,req.add ? [{id:base}] : [],req.decoration);
    if (req.add && !catalog.places?.[slot]?.additions?.[current[slot]]?.[req.decoration]) {
      if (current[slot]===req.decoration) throw Error(book.active[slot].name+'’s '+subject+' already has a '+detail+'.');
      throw Error(book.active[slot].name+'’s place shows '+labels[current[slot]]+'. The '+detail+' needs “'+labels[base]+'” already on the sand. '+complete);
    }
    return {slot,art:{id:req.decoration,label:labels[req.decoration]},addition:req.add};
  }
  function namedGuestRequests(text) {
    // A conjunction within a drawing belongs to that guest. A list begins
    // only after a recipient has been identified. Keep complete saved
    // titles and names such as “Rose and June” together while scanning.
    if(!/[,;]|\s+and(?:\s|$)/iu.test(text))return null;
    const protectedNames=[...book.active.map(person=>person.name),...keptDrawings().map(art=>art.label)]
      .filter(name=>/[,;]|\band\b/iu.test(name));
    const names=protectedNames.sort((a,b)=>b.length-a.length).map(literalName).join('|');
    const separator=/\s*[,;]\s*(?:and(?:\s+|$))?|\s+and(?:\s+|$)/iu;
    const quoted=/“[^”]*”|"[^"]*"|‘[^’]*’|(?:^|\s)'[^']*'/u;
    const pattern=(names ? '(?:'+names+')(?![\\p{L}\\p{M}\\p{N}])|' : '')+
      quoted.source+'|('+separator.source+')';
    text=text.normalize('NFC');
    let start=0;
    const requests=[];
    for(const hit of text.matchAll(new RegExp(pattern,'giu'))) {
      if(!hit[1])continue;
      const req=splitGuestRequest(text.slice(start,hit.index).trim());
      if(!req.recipient)continue;
      requests.push(req);
      start=hit.index+hit[0].length;
    }
    if(!requests.length)return null;
    requests.push(splitGuestRequest(text.slice(start).trim()));
    return requests;
  }
  function checkGroupInputs() {
    if($('target').value!=='')throw Error('Choose “Guest named in the suggestion” to draw for several people.');
    if($('sketch').open && paths.some(line=>line.length>1))throw Error('Close the sketch to preview drawings for several guests.');
  }
  function previewFromInterests(text) {
    const words=GuestArt.normalize(text).replace(/^please /,'');
    const everyone=/^(?:(?:draw|make) )?(?:something|a picture|a drawing) for (?:everyone|everybody|each guest|every guest|all (?:three )?guests)$/.test(words);
    const openings=/^(?:fill(?: in)?|(?:draw|make) something for) (?:all )?(?:the )?(?:open|empty) (?:places|seats)(?: from (?:their |guest )?interests)?$/.test(words);
    if ((!everyone && !openings) || GuestArt.splitRequest(text,book.active).guest) return false;
    checkGroupInputs();
    const slots=current.map((_,i)=>i).filter(i=>everyone || current[i]===openSubject);
    if (!slots.length) throw Error('Every guest place already has a drawing.');
    let plans=[[]];
    for (const slot of slots) {
      const guest=book.active[slot], ideas=ideasFor(GuestArt.guestInterest(guest));
      if (!ideas.length) throw Error('There is no drawing for '+guest.name+'’s interests yet. Add an interest under “Who’s in the garden?” or request a subject by name.');
      const at=ideas.findIndex(art=>sameDrawing(current[slot],art));
      // Start with the next matching subject if this guest already has one.
      const ranked=at>=0 && ideas.length>1 ? [...ideas.slice(at+1),...ideas.slice(0,at)] : ideas;
      // At most two other seats can claim a candidate. The three strongest
      // choices per guest suffice to find the most varied matching garden.
      plans=plans.flatMap(plan=>ranked.slice(0,current.length).map((art,rank)=>[...plan,{slot,art,rank}]));
    }
    let best, mostDifferent=-1, bestRank=Infinity;
    for (const plan of plans) {
      const ids=current.slice();
      let rank=0;
      for (const pick of plan) { ids[pick.slot]=pick.art.id; rank+=pick.rank; }
      const different=new Set(ids).size;
      if (different>mostDifferent || (different===mostDifferent && rank<bestRank)) {
        best=plan; mostDifferent=different; bestRank=rank;
      }
    }
    previewGuestChoices(best,openings);
    return true;
  }
  $('fillGuestPlaces').onclick = () => {
    $('target').value=''; $('idea').value='Fill the open places from interests';
    $('idea').dispatchEvent(new Event('input'));
    $('guestEditor').requestSubmit();
  };
  async function previewNamedGuests(requests,version) {
    checkGroupInputs();
    const places=new Set();
    const choices=[];
    for(const req of requests){
      if(!req.recipient)throw Error('Give each drawing a guest, for example “books for Alex”.');
      if(!req.guest)throw Error('There is no guest called “'+req.recipient+'” in the ring.');
      const slot=address(req);
      if(places.has(slot))throw Error('Choose one drawing for '+req.guest.name+'’s place.');
      places.add(slot);
      if(!req.to)throw Error('Name a drawing for '+req.guest.name+'.');
      if (req.decoration) { choices.push(decoratedChoice(req)); continue; }
      const lettering=letteringRequest(req.to);
      let art;
      if(lettering){
        const result=await letterArt(lettering,version,req.guest);
        if(!result || version!==suggestionVersion)return;
        art=result.art;
      } else if(openSubject && /^(?:(?:clear|open) (?:my|this|the) place|leave (?:my|this|the) place open)$/.test(GuestArt.normalize(req.to))){
        art={id:openSubject,label:labels[openSubject]};
      } else {
        art=req.to===req.guest.name ? alternate(ideasFor(GuestArt.guestInterest(req.guest)),current[slot]) :
          requestedArt(req.to,{chooseOperands:true,guestChoice:'guest-'+slot});
      }
      if(!art)throw Error('There is no drawing for “'+req.to+'” in '+req.guest.name+'’s request. Choose another subject or add it from a photo first.');
      choices.push({slot,art,lettering:!!lettering});
    }
    previewGuestChoices(choices);
  }
  function previewGuestChoices(choices,onlyOpen=false) {
    const next=current.slice();
    for(const {slot,art} of choices){
      if(sameDrawing(current[slot],art))continue;
      prepareArt(art);
      next[slot]=art.id;
    }
    if(next.every((id,i)=>id===current[i]))throw Error('Those drawings are already in the requested places.');
    const route=guestChange(next);
    for (const {slot,addition} of choices) {
      if (addition && (route.parts || [route]).find(part=>part.place===slot)?.addFrom!==current[slot])
        throw Error('This addition needs a route that keeps the existing drawing.');
    }
    if (onlyOpen && current.some(id=>id!==openSubject) && !route.fill && !route.parts?.every(part=>part.fill))
      throw Error('This layout would have to clear an occupied place. Choose another drawing for the open place.');
    if(!route.parts && route.place===undefined) {
      for(const {slot,lettering} of choices) {
        if(!lettering || current[slot]===next[slot])continue;
        const alone=current.slice(); alone[slot]=next[slot];
        if(guestChange(alone).place!==slot)throw Error('This lettering needs more space. Try a shorter greeting or initials.');
      }
    }
    previewRing(next,null,route);
  }
  $('guestEditor').onsubmit = async event => {
    event.preventDefault(); clearError();
    if (pairChoices) pairChoices.pending=null;
    const version = ++suggestionVersion;
    offeredPhoto=null; showSuggestionSources();
    try {
      const text = $('idea').value.trim();
      if (previewFromInterests(text)) return;
      const named=namedGuestRequests(text);
      if(named){ await previewNamedGuests(named,version); return; }
      const lettering = letteringRequest(text);
      if (lettering) { await previewLettering(lettering,version); return; }
      const req = splitGuestRequest(text);
      if (!req.guest && /\sfor\s+[^,]+$/i.test(req.to)) {
        throw Error('Choose someone in the ring, or add the guest under “Who’s in the garden?”.');
      }
      if (offerOpenPlaces(req) || previewRequestedBorder(req)) return;
      if (req.decoration && !($('sketch').open && paths.some(p=>p.length>1))) {
        previewGuestChoices([decoratedChoice(req)]); return;
      }
      const next = current.slice();
      let match, slot;
      if ($('sketch').open && paths.some(p=>p.length>1)) {
        const subject=resolve(req.to), parts=relationIn(req.to,subject);
        const anchors=parts ? [resolve(parts.right),resolve(parts.left)] : [];
        slot=address(req, anchors, subject?.id ?? null);
        match = readSketch(req.to,slot);
      } else if (req.guest && req.to === req.guest.name) {
        slot=address(req);
        match = alternate(ideasFor(GuestArt.guestInterest(req.guest)), current[slot]);
        if (!match) throw Error('Name another subject or sketch a new drawing for ' + req.guest.name + '.');
      } else {
        match = (!text && keptDrawings().find(art=>art.id===savedPicker.value)) ||
          requestedArt(req.to,{chooseOperands:true,allowWholePicture:true});
        if (!match || match.pendingPair) {
          if (!match && wideCenter?.standMixer && /^(?:kitchen )?stand[ -]mixer[.!?]?$/i.test(requestSubject(req.to))) {
            if (req.from || req.guest || $('target').value!=='') offerSuggestionPhoto(req,version);
            wideSuggestionVersion=version;
            showSuggestionSources(); $('previewWideSuggestion').focus();
            return;
          }
          if (offerSuggestionPhoto(req,version,match?.pendingPair)) return;
          throw Error('Sketch this idea below, or try a different word.');
        }
        slot=address(req,match.anchors,match.id);
      }
      const old = next[slot];
      if (sameDrawing(old,match)) {
        throw Error('That drawing is already in this guest’s place.');
      }
      prepareArt(match); next[slot] = match.id;
      previewRing(next, null);
    } catch(e) { report(e); }
  };
  function position(event) {
    const b = pad.getBoundingClientRect();
    const x=2*(event.clientX-b.left)/b.width-1, y=1-2*(event.clientY-b.top)/b.height;
    const scale=Math.max(1,Math.hypot(x,y)/.94);
    return [x/scale,y/scale];
  }
  function paintPad() {
    ink.clearRect(0,0,pad.width,pad.height);
    ink.lineWidth=4; ink.lineCap='round'; ink.lineJoin='round'; ink.strokeStyle='#665238';
    for (const line of paths) {
      ink.beginPath();
      line.forEach(([x,y],i) => {
        const a=(x+1)*pad.width/2, b=(1-y)*pad.height/2;
        if (i) ink.lineTo(a,b); else ink.moveTo(a,b);
      });
      ink.stroke();
    }
  }
  pad.onpointerdown = e => {
    if (stroke || paths.length>=24) return;
    editingSuggestion();
    pad.setPointerCapture(e.pointerId); stroke=[position(e)]; paths.push(stroke);
  };
  pad.onpointermove = e => {
    if (!stroke || !pad.hasPointerCapture(e.pointerId) || stroke.length>=700) return;
    stroke.push(position(e)); paintPad();
  };
  pad.onlostpointercapture = () => { stroke=null; };
  $('clearSketch').onclick = () => { editingSuggestion(); paths.length=0; stroke=null; paintPad(); };
  function openDrawing() {
    resetBorderForm();
    if (borderPicker && (familyBorder || ['#example-lek-border','#border'].includes(location.hash))) {
      zone='outer'; radio('zone',zone).checked=true;
      if (!familyBorder && location.hash === '#example-lek-border') {
        $('borderDesign').value='2'; $('borderGuest').value='Lek';
        borderEdited=selected.outer!==2 || selected.borderGuest!=='Lek';
        stage=borderEdited ? 'redrawn' : 'original'; radio('stage',stage).checked=true;
      }
    }
    const thomasExample = initial && location.hash === '#example-thomas-guitar' && book;
    const thomasPlace = thomasExample ? book.active.findIndex(person=>GuestArt.normalize(person.name)==='thomas') : -1;
    const electricExample = initial && location.hash === '#example-electric-guitar' && catalog?.subjects.electric_guitar;
    const booksExample = initial && location.hash === '#example-two-books' && catalog?.subjects.two_books;
    const alexPlace = initial && book ? book.active.findIndex(person=>GuestArt.normalize(person.name)==='alex') : -1;
    const player = electricExample && (GuestArt.musicGuest(book.active,'electric_guitar',manifest) ||
      (alexPlace>=0 && GuestArt.musicGuest([book.active[alexPlace]],'electric_guitar',manifest)));
    const guitarPlace = electricExample ? [book.active.indexOf(player), current.indexOf(catalog.openSubject), 0].find(slot=>slot>=0) : -1;
    const lekPlace = initial && book ? book.active.findIndex(person=>GuestArt.normalize(person.name)==='lek') : -1;
    const showHeart=initial && location.hash==='#example-heart-initials' && lekPlace>=0 && catalog?.places?.[lekPlace];
    const currentHeart=showHeart && labels[current[lekPlace]]==='Heart with BL' &&
      sameInk(custom[current[lekPlace]],GuestLettering.inHeart('BL',{groove:scene.live.groove/catalog.geometry.scale}).path);
    const preparedGuest=initial && location.hash.startsWith('#guest-drawing/') && book;
    const mixerExample=initial && location.hash==='#example-stand-mixer' && !!wideCenter?.standMixer;
    const sampleRequest = libraryExample ?
      {text:labels[exampleId],slot:alexPlace<0 ? 1 : alexPlace,id:exampleId,enlarge:true} : initial && {
      '#example-heart-initials':showHeart ? {text:'a heart with B and L inside',slot:lekPlace,id:currentHeart ? current[lekPlace] : undefined} : null,
      '#example-alex-guitar':alexPlace < 0 ? null : {text:'guitar',slot:alexPlace,id:preferred.guitar || 'guitar'},
      '#example-thomas-guitar':thomasPlace < 0 ? null : {text:'guitar',slot:thomasPlace,id:preferred.guitar || 'guitar'},
      '#example-electric-guitar':electricExample ? {text:'an electric guitar',slot:guitarPlace,id:'electric_guitar'} : null,
      '#example-two-books':booksExample ? {text:'a stack of two books',slot:alexPlace<0 ? 1 : alexPlace,id:'two_books'} : null,
      '#example-oven-mitt':catalog?.subjects.oven_mitt ? {text:'an oven mitt',slot:alexPlace<0 ? 1 : alexPlace,id:'oven_mitt',enlarge:true} : null,
      '#example-harvest-basket':catalog?.subjects.harvest_basket ? {text:'a basket of apples',slot:alexPlace<0 ? 1 : alexPlace,id:'harvest_basket',enlarge:true} : null,
      '#example-crescent-roll':catalog?.subjects.crescent_roll ? {text:'a crescent roll',slot:alexPlace<0 ? 1 : alexPlace,id:'crescent_roll',enlarge:true} : null,
      '#example-harvest-wheat':catalog?.subjects.harvest_wheat ? {text:'harvest wheat',slot:alexPlace<0 ? 1 : alexPlace,id:'harvest_wheat',enlarge:true} : null,
      '#example-harvest-pear':catalog?.subjects.harvest_pear ? {text:'a harvest pear',slot:alexPlace<0 ? 1 : alexPlace,id:'harvest_pear',enlarge:true} : null,
      '#example-desk-lamp':catalog?.subjects.desk_lamp ? {text:'an adjustable desk lamp',slot:alexPlace<0 ? 1 : alexPlace,id:'desk_lamp',enlarge:true} : null,
      '#example-acorn':catalog?.subjects.acorn ? {text:'an acorn',slot:alexPlace<0 ? 1 : alexPlace,id:'acorn',enlarge:true} : null,
      '#example-pumpkin-pie':catalog?.subjects.pumpkin_pie ? {text:'a slice of pumpkin pie with whipped cream',slot:1,id:'pumpkin_pie'} : null,
      '#example-lattice-pie':catalog?.subjects.lattice_pie ? {text:'a whole lattice pie',slot:1,id:'lattice_pie'} : null,
      '#example-pilgrim-hat':catalog?.subjects.pilgrim_hat ? {text:'a pilgrim hat with a buckle',slot:1,id:'pilgrim_hat'} : null,
      '#example-lotus-leaf':catalog?.subjects.lotus_blossom ? {text:'a lotus flower on a lily pad',slot:lekPlace<0 ? 2 : lekPlace,id:'lotus_blossom'} : null,
      '#example-roast-turkey':catalog?.subjects.roast_turkey ? {text:'a roast turkey on a platter',slot:1,id:'roast_turkey'} : null,
      '#example-dinner-candle':catalog?.subjects.dinner_candle ? {text:'a lit dinner candle in a holder',slot:1,id:'dinner_candle'} : null,
      '#example-mayflower':catalog?.subjects.mayflower_ship ? {text:'the Mayflower',slot:lekPlace<0 ? 2 : lekPlace,id:'mayflower_ship'} : null,
      '#example-coffee-grinder':catalog?.subjects.coffee_grinder ? {text:'a hand-cranked coffee grinder',slot:1,id:'coffee_grinder'} : null,
      '#example-caramel-apple':catalog?.subjects.caramel_apple ? {text:'a caramel apple on a stick',slot:1,id:'caramel_apple'} : null,
      '#example-guitar-books':{text:'a guitar leaning against my books',slot:alexPlace < 0 ? 1 : alexPlace,id:'guitar_books'},
      '#example-comet-telescope':{text:'a comet over a telescope',slot:0,id:'pair-above-symbol-2604__telescope'}
    }[location.hash];
    if (initial && !selected.widePortrait && (sampleRequest || mixerExample || preparedGuest || thomasExample || ['#guests','#people','#example-telescope','#changing-garden'].includes(location.hash)) && catalog) {
      zone='middle'; radio('zone',zone).checked=true;
      peopleBox.open = location.hash === '#people' || telescopeExample;
      $('changingGarden').open = location.hash === '#changing-garden';
    }
    const sample = initial && {'#example-portrait':'one','#example-group':'group','#example-faces':'faces',
      '#example-shadows':'one','#example-group-shadows':'group'}[location.hash];
    const openShadows = initial && location.hash==='#photo-shadows';
    const openPrepared = initial && location.hash==='#prepared-portrait';
    const openGroupShadows = initial && location.hash==='#group-shadows';
    const openSeats = initial && location.hash==='#seated-group';
    if (openShadows && supportsPhotoShadows()) $('soloStyle').value='shadow';
    if (openPrepared) $('portraitMode').value='prepared';
    if (openGroupShadows) { $('portraitMode').value='group'; $('portraitStyle').value=supportsPhotoShadows() ? 'shadows' : 'faces'; }
    if (openSeats) { $('portraitMode').value='group'; $('portraitStyle').value='seats'; }
    if (location.hash==='#photos' || openShadows || openPrepared || openGroupShadows || openSeats || sample || carriedPhoto) $('centerPhoto').open=true;
    show();
    if (mixerExample) {
      if (selected.widePortrait) {
        if (keptPortrait!==wideCenter.standMixer.label) previewWideMixer();
      } else {
        $('idea').value='a stand mixer'; $('guestEditor').requestSubmit();
      }
    } else if (preparedGuest && zone==='middle') {
      try {
        const encoded=location.hash.slice('#guest-drawing/'.length);
        if (encoded.length>640000) throw Error('This guest drawing is too large.');
        const bytes=Uint8Array.from(atob(encoded.replace(/-/g,'+').replace(/_/g,'/')),c=>c.charCodeAt(0));
        const art=JSON.parse(new TextDecoder('utf-8',{fatal:true}).decode(bytes));
        if (art?.format!=='oasis-guest-drawing-v1' || typeof art.name!=='string' || !art.name.trim() ||
            art.name.length>180 || typeof art.guest!=='string' || !art.guest.trim() || art.guest.length>80) throw Error('This guest drawing could not be opened.');
        const slot=book.active.findIndex(person=>drawingNameKey(person.name)===drawingNameKey(art.guest));
        if (slot<0) throw Error('This drawing needs '+art.guest+' in the guest ring.');
        OasisRingPlanner.checkCustomShape(art.points);
        if (!OasisRingPlanner.fitsGuestTravel(art.points,slot,catalog.geometry))
          throw Error('This drawing needs more room in the sand.');
        const label=art.name.trim(), existing=keptDrawings().find(kept=>kept.label===label && sameInk(custom[kept.id],art.points));
        enlarged=true;
        if (existing && existing.id===current[slot]) {
          proposed=current.slice(); guestFocus=slot; show();
        } else previewGuestChoices([{slot,art:existing || {label,points:art.points}}]);
      } catch (error) {
        report(error instanceof SyntaxError || error instanceof DOMException || error instanceof TypeError ?
          Error('This guest drawing could not be read. Reopen its original link.') : error);
      }
    } else if (sampleRequest && zone === 'middle') {
      const {text,slot,id} = sampleRequest;
      if (sampleRequest.enlarge) enlarged=true;
      $('idea').value = text + ' for ' + book.active[slot].name;
      if (current[slot] === id) { proposed=current.slice(); guestFocus=slot; show(); }
      else if (libraryExample) previewGuestChoices([{slot,art:{id,label:labels[id]}}]);
      else $('guestEditor').requestSubmit();
    } else if (carriedPhoto) {
      faceChoice=carriedPhoto.face ?? null; groupFaces=carriedPhoto.groupFaces ?? null;
      seatOrder=carriedPhoto.seatOrder ?? null;
      if (carriedPhoto.mode==='separate') {
        seatPhotos=carriedPhoto.seatPhotos;
        seatPhotoIndex=carriedPhoto.seatPhotoIndex;
      } else if (carriedPhoto.uploaded) {
        const transfer = new DataTransfer();
        transfer.items.add(carriedPhoto.file);
        $('portraitFile').files = transfer.files;
      } else samplePhoto = carriedPhoto.file;
      $('portraitMode').value = carriedPhoto.mode;
      $('portraitStyle').value = carriedPhoto.style === 'shadows' && !supportsPhotoShadows() ? 'faces' : carriedPhoto.style;
      $('soloStyle').value = carriedPhoto.soloStyle || 'auto';
      $('photoCaption').value = carriedPhoto.caption || '';
      $('seatedReveal').checked = !!carriedPhoto.seatedReveal;
      editPhoto();
      if (separatePhotos()) {
        showSeatPhotos();
        for (const seat of seatPhotos) if (!seat.scan && !seat.error) inspectSeat(seat);
      }
      if (carriedPhoto.preview && (!separatePhotos() || seatsReady())) $('portraitForm').requestSubmit();
    } else if (openPrepared) {
      // The private gallery can hand a prepared file to the normal preview in
      // the same tab. Opening the link directly leaves the file picker ready.
      let saved;
      try {
        saved=sessionStorage.getItem('oasis-prepared-portrait');
        sessionStorage.removeItem('oasis-prepared-portrait');
      } catch { /* The file picker also works when browser storage is disabled. */ }
      if (saved && saved.length<=4*1024*1024) {
        const transfer=new DataTransfer();
        transfer.items.add(new File([saved],'guest.oasisportrait',{type:'application/json'}));
        $('portraitFile').files=transfer.files;
        editPhoto(); $('portraitForm').requestSubmit();
      }
    } else if (openSeats && !$('sampleFaces').hidden) {
      openSample('faces','seats');
    } else if (sample && !$(examples[sample]).hidden) {
      if (location.hash === '#example-shadows') $('soloStyle').value='shadow';
      if (location.hash === '#example-portrait') $('soloStyle').value='line';
      openSample(sample,location.hash === '#example-group-shadows' ? 'shadows' : undefined);
    }
  }
  if (room) {
    room.watch((state, first, preserveInput, untouchedPlaces) => {
      if (first) {
        restore(state); original=renderer.image(bed); proposed=defaultSuggestion(); guestForm?.refresh();
        openDrawing();
      } else {
        applyGarden(state, preserveInput);
        rotation?.changed(untouchedPlaces);
      }
    }, pendingEdit, data => rotation?.onPlayback(data), singleGuestPlace);
  } else openDrawing();

  return function closeEditor() {
    editorClosed = true;
    room?.close(); clearRoomFiles(); rotation?.close();
    const upload = $('portraitFile').files[0];
    const file = upload || samplePhoto;
    const photo = (file || separatePhotos()) && zone === 'center' && $('centerPhoto').open ?
      {file, uploaded:!!upload, mode:$('portraitMode').value, style:$('portraitStyle').value, soloStyle:$('soloStyle').value,
       caption:$('photoCaption').value, seatedReveal:$('seatedReveal').checked,
       ...(separatePhotos() && {seatPhotos,seatPhotoIndex}),
       face:faceChoice, groupFaces, seatOrder, preview:!!portraitDraft || converting} : null;
    photoRequest++;
    hideDownloads();
    clearSource();
    setupUrls.forEach(url => URL.revokeObjectURL(url));
    return photo;
  };
}
