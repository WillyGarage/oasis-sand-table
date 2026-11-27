'use strict';
/* Sand table guest app. All data comes from /api/state (polled every 4 s). */
const $ = id => document.getElementById(id);
const esc = s => String(s).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const COLORS = [['Sunset','#e8743b'],['Gold','#e0b030'],['Leaf green','#5a9a5a'],['Sky','#4a90c8'],['Violet','#8a62b8'],['Rose','#d86a8a'],['Warm white','#f3e7c9'],['Teal','#2a9a98']];
const FLOW = ['who','photo','interests','color'];
const SCREENS = ['who','photo','interests','color','me','table','everyone','keep','host'];
const HASH = {keep:'keepsake'};
const PENDING_GIVE_UP_MS = 180000;   // drawings are made in the background; a spinner shows until one is ready

let S = null, sig = '', P = {}, IN = {};
let myId = +(localStorage.getItem('sandPersonId') || 0) || null;
let cur = '', welcome = false, whoMode = 'list', keepT = 0;
let netErr = false, flashT = null;

/* ---------- helpers ---------- */
function fmt(sec) {
  const d = new Date(sec * 1000); let h = d.getHours(); const m = d.getMinutes(), ap = h >= 12 ? 'pm' : 'am';
  h = h % 12 || 12; return h + ':' + (m < 10 ? '0' : '') + m + ' ' + ap;
}
function joinNames(n) { return n.length < 2 ? n.join('') : n.slice(0, -1).join(', ') + ' and ' + n[n.length - 1]; }
function initials(name) { return name.split(/\s+/).filter(Boolean).map(w => w[0]).join('').slice(0, 2).toUpperCase() || '?'; }
function faceUrl(p, n) { return '/img/face/' + p.id + '.jpg?' + (n ? 'n=' + n + '&' : '') + 'v=' + p.face_v; }
function iconUrl(i) { return '/img/icon/' + i.id + '.png?v=' + i.v; }
const SPIN = '<i class="spin in" role="img" aria-label="Being made"></i>';
function faceInner(p) { return p.faces > 0 ? (p.face_pending ? SPIN : '<img src="' + faceUrl(p) + '" alt="">') : esc(initials(p.name)); }
function thumb(p, cls) { return '<div class="th ' + (cls || '') + '">' + faceInner(p) + '</div>'; }
// an interest's picture, or a spinner in its place until the drawing exists
function iconImg(i, attrs) { return i.status === 'pending' && !pendingGaveUp(i) ? '<span class="icw" ' + (attrs || '') + '>' + SPIN + '</span>' : '<img ' + (attrs || '') + ' src="' + iconUrl(i) + '" alt="">'; }
function me() { return myId && P[myId] || null; }
function setMe(id) { myId = id; if (id) localStorage.setItem('sandPersonId', id); else localStorage.removeItem('sandPersonId'); }
function typing(el) { const a = document.activeElement; return !!(a && el && el.contains(a) && /^(INPUT|TEXTAREA)$/.test(a.tagName)); }
function flash(msg) {
  const b = $('banner'); b.dataset.flash = msg || '';
  clearTimeout(flashT); if (msg) flashT = setTimeout(() => { b.dataset.flash = ''; drawBanner(); }, 6000);
  drawBanner();
}
function drawBanner() {
  const b = $('banner'), f = b.dataset.flash;
  const er = S && S.table && S.table.erase;
  b.innerHTML = (netErr ? '<div class="bad">Can\'t reach the table right now. Trying again...</div>' : '') + (f ? '<div class="bad">' + esc(f) + '</div>' : '') +
    (er ? '<div class="note">' + (er.status === 'running' ? 'The table is being wiped clean. Drawings start again when it’s done.' : 'The table is about to be wiped clean. Drawings start again after that.') + '</div>' : '');
}

async function api(method, path, body, form) {
  const opt = {method, headers: {}};
  if (form) opt.body = form;
  else if (body !== undefined) { opt.headers['Content-Type'] = 'application/json'; opt.body = JSON.stringify(body); }
  let r;
  try { r = await fetch(path, opt); } catch (e) { const err = new Error('network'); err.network = true; throw err; }
  let data = null;
  if (r.status !== 204) { try { data = await r.json(); } catch (e) { data = null; } }
  if (!r.ok) { const err = new Error('http ' + r.status); err.status = r.status; err.data = data; throw err; }
  return data;
}
function failMsg(e, what) { return e.network ? "Couldn't reach the table. Check your signal and try again." : (what || 'Something went wrong') + '. Please try again.'; }

/* ---------- state ---------- */
function digest(s) { const c = Object.assign({}, s); delete c.now; return JSON.stringify(c); }
function adopt(s) {
  S = s; P = {}; IN = {};
  s.people.forEach(p => { P[p.id] = p; p.interests.forEach(i => { IN[i.id] = i; }); });
  if (myId && !P[myId]) { setMe(null); }
}
async function refresh(force) {
  try {
    const s = await api('GET', '/api/state');
    if (netErr) { netErr = false; drawBanner(); }
    $('bootErr').style.display = 'none';
    const d = digest(s);
    if (d !== sig || force) { sig = d; adopt(s); renderAll(); }
  } catch (e) {
    if (!netErr) { netErr = true; drawBanner(); }
    if (!S) showBootError();
  }
}
function showBootError() {
  if (S) return;
  $('bootErr').style.display = 'block';
}
setInterval(() => { if (!document.hidden) refresh(); }, 4000);
document.addEventListener('visibilitychange', () => { if (!document.hidden) refresh(); });

/* ---------- navigation ---------- */
function go(n) { if (location.hash === '#' + (HASH[n] || n)) show(n); else location.hash = HASH[n] || n; }
function fromHash() {
  const h = location.hash.slice(1), hit = SCREENS.find(n => (HASH[n] || n) === h);
  return hit || 'who';
}
window.addEventListener('hashchange', () => show(fromHash()));
function show(n) {
  if (!S) return;
  const m = me();
  if ((n === 'me' || n === 'keep') && !(m && m.joined)) n = 'who';
  if (FLOW.indexOf(n) > 0 && !m) n = 'who';
  if (n === 'color' && m && m.joined) n = 'me';
  if (cur !== n) { closePad(); $('body').scrollTop = 0; if (n === 'keep') keepT = Date.now(); }
  cur = n;
  document.querySelectorAll('.sc').forEach(e => e.classList.toggle('on', e.id === 's-' + n));
  if (n === 'photo') photoEnter();
  renderAll();
}
function renderAll() {
  if (!S || !cur) return;
  ({who: renderWho, photo: () => {}, interests: renderMine, color: renderColor, me: renderMe, table: renderTable,
    everyone: renderEveryone, keep: renderKeep, host: renderHost})[cur]();
  renderNav(); drawBanner();
}
function nextOf(n) { return {who: 'photo', photo: 'interests', interests: 'color'}[n]; }
function prevOf(n) { return {photo: 'who', interests: 'photo', color: 'interests'}[n]; }
function renderNav() {
  const m = me(), nav = $('nav');
  if (m && m.joined) {
    const act = cur === 'table' || cur === 'everyone' ? cur : cur === 'host' ? '' : 'me';
    nav.innerHTML = [['me', 'Me'], ['table', 'Table'], ['everyone', 'Everyone']].map(t =>
      '<button data-act="go" data-to="' + t[0] + '" class="' + (act === t[0] ? 'on' : '') + '">' + t[1] + '</button>').join('');
  } else if (FLOW.indexOf(cur) >= 0 && !(cur === 'who' && (!m || welcome))) {
    nav.innerHTML = '<button data-act="navBack"' + (cur === 'who' ? ' disabled' : '') + '>Back</button>' +
      '<button class="nx" data-act="navNext"' + (cur === 'who' && (!m || welcome) ? ' disabled' : '') + '>' + (cur === 'color' ? 'Add me' : 'Next') + '</button>';
  } else {
    const act = cur === 'table' || cur === 'everyone' || cur === 'who' ? cur : '';   // nobody picked yet: the menu, so the table and guest list stay one tap away
    nav.innerHTML = [['who', 'Who are you?'], ['table', 'Table'], ['everyone', 'Everyone']].map(t =>
      '<button data-act="go" data-to="' + t[0] + '" class="' + (act === t[0] ? 'on' : '') + '">' + t[1] + '</button>').join('');
  }
}

/* ---------- 1 who ---------- */
function renderWho() {
  const m = me(), w = $('welcome');
  const showWelcome = welcome && m;
  w.style.display = showWelcome ? 'block' : 'none';
  if (showWelcome) {
    w.innerHTML = '<b style="font-size:1.15rem">Welcome back, ' + esc(m.name) + '.</b><br>' +
      '<button class="btn" style="margin:8px 0 2px" data-act="keepGoing">That\'s me, keep going</button>' +
      '<button class="link" data-act="switchMe">Not you? Switch</button>';
  }
  $('who-main').style.display = !showWelcome && whoMode === 'list' ? 'block' : 'none';
  $('who-new').style.display = !showWelcome && whoMode === 'new' ? 'block' : 'none';
  if (whoMode === 'list') renderPeople();
  checkName();
}
function renderPeople() {
  const box = $('plist'); if (typing(box)) return;
  const q = $('search').value.trim().toLowerCase();
  const list = S.people.slice().sort((a, b) => a.name.localeCompare(b.name)).filter(p => p.name.toLowerCase().includes(q));
  box.innerHTML = list.map(p => '<button class="person" data-act="pickPerson" data-id="' + p.id + '">' + thumb(p) + '<span>' + esc(p.name) + '</span></button>').join('') ||
    '<p class="sub">No one by that name yet. Tap "I’m not on the list".</p>';
}
function checkName() {
  const v = $('newname').value.trim(), t = $('taken');
  const hit = S.people.find(p => p.name.toLowerCase() === v.toLowerCase());
  if (hit) {
    t.style.display = 'block';
    t.innerHTML = 'There’s already ' + (/^[aeiou]/i.test(hit.name) ? 'an ' : 'a ') + '<b>' + esc(hit.name) + '</b> here. Add a last initial or nickname, like <b>' + esc(hit.name) + ' H.</b>';
  } else t.style.display = 'none';
  $('newgo').disabled = !v || !!hit;
}
function takenNotice(name) {
  const t = $('taken');
  t.style.display = 'block';
  t.innerHTML = 'There’s already ' + (/^[aeiou]/i.test(name) ? 'an ' : 'a ') + '<b>' + esc(name) + '</b> here. Add a last initial or nickname, like <b>' + esc(name) + ' H.</b>';
}

/* ---------- 2 photo ---------- */
const ph = {stage: 'up', cv: null, boxes: [], sel: [], busy: false};
let vendorP = null;
function setStage(s) {
  ph.stage = s;
  ['up', 'look', 'make', 'faces', 'none', 'sand'].forEach(k => { $('p-' + k).style.display = k === s ? 'block' : 'none'; });
}
function photoEnter() { if (ph.stage === 'look' || ph.stage === 'make') return; if (ph.stage !== 'faces' && ph.stage !== 'none') setStage('up'); }
function loadScript(src) {
  return new Promise((res, rej) => {
    const s = document.createElement('script'); s.src = src; s.onload = res; s.onerror = () => rej(new Error('load ' + src));
    document.head.appendChild(s);
  });
}
function loadVendor() {
  if (!vendorP) vendorP = (async () => {
    await loadScript('vendor/guest-landmarks.js');
    await loadScript('vendor/guest-face-verify.js');
    await window.loadGuestLandmarks();
  })().catch(e => { vendorP = null; throw e; });
  return vendorP;
}
async function readPhoto(file) {
  let src, w, h;
  try { src = await createImageBitmap(file, {imageOrientation: 'from-image'}); w = src.width; h = src.height; }
  catch (e) {
    src = await new Promise((res, rej) => { const im = new Image(), u = URL.createObjectURL(file); im.onload = () => res(im); im.onerror = () => rej(new Error('bad image')); im.src = u; });
    w = src.naturalWidth; h = src.naturalHeight;
  }
  const k = Math.min(1, 1600 / Math.max(w, h)), cv = document.createElement('canvas');
  cv.width = Math.max(1, Math.round(w * k)); cv.height = Math.max(1, Math.round(h * k));
  cv.getContext('2d').drawImage(src, 0, 0, cv.width, cv.height);
  return cv;
}
async function detectFaces(cv) {
  const W = cv.width, H = cv.height;
  let found = [];
  try {
    await loadVendor();
    const views = [[0, 0, W, H]];
    if (Math.min(W, H) >= 500) { const f = .6; [[0, 0], [1, 0], [0, 1], [1, 1]].forEach(q => views.push([q[0] * (1 - f) * W, q[1] * (1 - f) * H, f * W, f * H])); }
    for (const v of views) {
      let img = cv;
      if (v[2] !== W) { img = document.createElement('canvas'); img.width = Math.round(v[2]); img.height = Math.round(v[3]); img.getContext('2d').drawImage(cv, v[0], v[1], v[2], v[3], 0, 0, img.width, img.height); }
      const res = await window.GuestFaceVerify.scanPanorama(img);
      res.forEach(b => found.push({x: b.x + v[0], y: b.y + v[1], w: b.w, h: b.h, score: b.score}));
    }
  } catch (e) {
    console.warn('Face model unavailable', e);
    if ('FaceDetector' in window) {
      try {
        const r = await new window.FaceDetector({maxDetectedFaces: 12}).detect(cv);
        found = r.map(f => ({x: f.boundingBox.x + f.boundingBox.width / 2, y: f.boundingBox.y + f.boundingBox.height / 2, w: f.boundingBox.width, h: f.boundingBox.height, score: 1}));
      } catch (e2) { found = []; }
    }
  }
  found.sort((a, b) => b.score - a.score);
  const keep = [];
  found.forEach(b => { if (!keep.some(a => Math.hypot(a.x - b.x, a.y - b.y) < .5 * Math.min(a.w, b.w))) keep.push(b); });
  return keep.slice(0, 12).sort((a, b) => a.x - b.x);
}
async function handleFile(file) {
  if (!file) return;
  $('p-uperr').textContent = '';
  setStage('look');
  try {
    ph.cv = await readPhoto(file);
    ph.boxes = await detectFaces(ph.cv);
  } catch (e) {
    setStage('up'); $('p-uperr').textContent = "We couldn't open that photo. Try a different one."; return;
  }
  ph.sel = ph.boxes.length === 1 ? [0] : [];
  $('p-noneerr').textContent = '';
  if (!ph.boxes.length) { setStage('none'); return; }
  setStage('faces'); renderFaces();
}
function renderFaces() {
  const n = ph.boxes.length, W = ph.cv.width, H = ph.cv.height;
  $('faces-sub').textContent = n === 1 ? 'We found 1 face. Is that you?' : 'We found ' + n + ' faces. Tap the one that’s you. Pick two to be drawn side by side.';
  const url = ph.cv.toDataURL('image/jpeg', .8);
  $('photo').innerHTML = '<img src="' + url + '" alt="Your photo with the faces found">' + ph.boxes.map((b, i) => {
    const bw = b.w, bh = b.h, small = bw < W * .08;
    return '<div class="fb' + (ph.sel.includes(i) ? ' sel' : '') + (small ? ' sm' : '') + '" data-act="togFace" data-i="' + i + '" style="left:' + (b.x - bw / 2) / W * 100 + '%;top:' + (b.y - bh / 2) / H * 100 + '%;width:' + bw / W * 100 + '%;height:' + bh / H * 100 + '%"><b>' + (i + 1) + '</b></div>';
  }).join('');
  const s = ph.sel.length;
  $('pickline').textContent = s ? (s === 1 ? 'You picked face ' + (ph.sel[0] + 1) + '.' : 'You picked faces ' + ph.sel.map(x => x + 1).join(' and ') + '. You’ll be drawn side by side.') : 'Tap a face to pick it.';
  $('seesand').disabled = !s || ph.busy;
}
function cropSquare(cv, cx, cy, side) {
  const out = Math.min(800, Math.max(256, Math.round(side))), c = document.createElement('canvas');
  c.width = c.height = out;
  const x = c.getContext('2d'); x.fillStyle = '#e8dcb8'; x.fillRect(0, 0, out, out);
  x.drawImage(cv, cx - side / 2, cy - side / 2, side, side, 0, 0, out, out);
  return new Promise(res => c.toBlob(res, 'image/jpeg', .9));
}
function cropFace(cv, b) { return cropSquare(cv, b.x, b.y - .12 * b.w, 1.9 * b.w); }
async function uploadCrops(blobs) {
  const m = me(), f = new FormData();
  blobs.forEach((b, i) => f.append('face' + (i + 1), b, 'face' + (i + 1) + '.jpg'));
  await api('POST', '/api/people/' + m.id + '/faces', undefined, f);
  await refresh(true);
}
async function showSand() {
  if (ph.busy) return; ph.busy = true; $('seesand').disabled = true; $('p-facesbusy').textContent = '';
  setStage('make');
  try {
    const blobs = [];
    for (const i of ph.sel) blobs.push(await cropFace(ph.cv, ph.boxes[i]));
    await uploadCrops(blobs);
    afterPhoto();                     // the drawing is made in the background; nobody waits for it
  } catch (e) { setStage('faces'); renderFaces(); $('p-facesbusy').textContent = failMsg(e, "Couldn't send your photo"); }
  ph.busy = false; $('seesand').disabled = !ph.sel.length;
}
async function useMiddle() {
  if (ph.busy) return; ph.busy = true; $('p-noneerr').textContent = '';
  setStage('make');
  try {
    const cv = ph.cv, side = Math.min(cv.width, cv.height);
    await uploadCrops([await cropSquare(cv, cv.width / 2, cv.height / 2, side)]);
    afterPhoto();
  } catch (e) { setStage('none'); $('p-noneerr').textContent = failMsg(e, "Couldn't send your photo"); }
  ph.busy = false;
}
function sandStage(canPick) {
  const m = me(); if (!m) return;
  $('sandprev').innerHTML = m.faces > 1
    ? '<div class="two"><img class="round" src="' + faceUrl(m) + '" alt="Sand preview of face 1"><img class="round" src="' + faceUrl(m, 2) + '" alt="Sand preview of face 2"></div>'
    : '<img class="round" src="' + faceUrl(m) + '" alt="Sand preview">';
  $('sand-other').style.display = canPick ? '' : 'none';
  setStage('sand');
}
function afterPhoto() { const m = me(); setStage('up'); go(m && m.joined ? 'me' : 'interests'); }

/* ---------- 3 interests ---------- */
const MAX_LABEL = 40, MAX_STROKES = 40, MAX_POINTS = 4000, MAX_PER_STROKE = 300;
let editing = null, editVal = '', editErr = '', removing = null, inflight = [], seen = {}, pendT = null, minelistHtml = '';
let padTarget = null, padFixed = false, padBusy = false;
function pendingGaveUp(i) {
  const k = i.id + ':' + i.v;
  if (!seen[k]) seen[k] = Date.now();
  return Date.now() - seen[k] >= PENDING_GIVE_UP_MS;
}
function sharedLine(i) {
  const n = i.shared_with || [];
  return n.length ? joinNames(n) + (n.length === 1 ? ' likes' : ' like') + ' this too' : '';
}
// "Also into sports: Diego (soccer) and Ana (tennis)", one line per theme, everybody listed (Bill: never "and N more")
function relatedLines(i, prefix) {
  const by = {};
  (i.related || []).forEach(r => { (by[r.theme] = by[r.theme] || []).push(r); });
  return Object.keys(by).map(t => {
    const p = by[t].map(r => r.name + ' (' + r.label + ')');
    return prefix + ' ' + t + ': ' + joinNames(p);
  });
}
function makingRow(text) { return '<div class="mine"><div class="spin"></div><span>' + text + '</span></div>'; }
function renderMine() {
  const m = me(); if (!m) return;
  const box = $('minelist'); if (typing(box)) return;
  clearTimeout(pendT);
  let wait = 0;
  const making = m.interests.filter(i => i.status === 'pending' && !pendingGaveUp(i)).length + inflight.length;
  const makingText = making > 1 ? 'Making drawings...' : 'Making a drawing...';
  let h = m.interests.map(i => {
    if (i.status === 'pending' && !pendingGaveUp(i)) {
      wait = Math.max(wait, PENDING_GIVE_UP_MS - (Date.now() - seen[i.id + ':' + i.v]));
      return '<div class="mine col"><div class="mtop"><span class="icw big">' + SPIN + '</span><div class="mtxt"><div class="mname">' + esc(i.label) + '</div>' +
        '<div class="shared">Making its drawing. You can carry on.</div></div></div></div>';
    }
    const mine = i.source === 'sketch', sh = sharedLine(i);
    if (editing === i.id) {
      return '<div class="mine col"><div class="mtop"><img src="' + iconUrl(i) + '" alt=""><div class="mtxt"><label class="lbl" for="edit">New name</label>' +
        '<input type="text" id="edit" maxlength="' + MAX_LABEL + '" value="' + esc(editVal) + '" autocomplete="off"></div></div>' +
        (editErr ? '<div class="err">' + esc(editErr) + '</div>' : '<div class="hint">' + (mine ? 'Your drawing stays, only the name changes.' : 'A new name gets a new drawing.') + '</div>') +
        '<div class="macts"><button class="btn" data-act="saveEdit" data-id="' + i.id + '">Save</button>' +
        '<button class="btn sec" data-act="cancelEdit">Cancel</button></div></div>';
    }
    if (removing === i.id) {
      return '<div class="mine col"><div class="mtop"><img src="' + iconUrl(i) + '" alt=""><div class="mtxt"><b class="mname">Remove ' + esc(i.label) + '?</b><div class="hint">Its drawing goes away too.</div></div></div>' +
        '<div class="macts"><button class="btn sec del" data-act="rmYes" data-id="' + i.id + '">Yes, remove</button>' +
        '<button class="btn sec" data-act="rmNo">Keep it</button></div></div>';
    }
    return '<div class="mine col"><div class="mtop"><img src="' + iconUrl(i) + '" alt=""><div class="mtxt"><div class="mname">' + esc(i.label) + (mine ? '<span class="own">your drawing</span>' : '') + '</div>' +
      (sh ? '<div class="shared">' + esc(sh) + '</div>' : '') +
      relatedLines(i, 'Also into').map(l => '<div class="shared rel">' + esc(l) + '</div>').join('') + '</div></div>' +
      '<div class="macts3"><button class="mb" data-act="editRow" data-id="' + i.id + '">Rename</button>' +
      '<button class="mb" data-act="openPad" data-id="' + i.id + '">' + (mine ? 'Redraw' : 'Draw it myself') + '</button>' +
      '<button class="mb rm" data-act="rmRow" data-id="' + i.id + '">Remove</button></div></div>';
  }).join('');
  inflight.forEach(() => { h += makingRow(makingText); });
  if (!m.interests.length && !inflight.length) h = '<p class="empty">Nothing here yet. Add what you like and it becomes a little drawing on the table.</p>';
  if (h !== minelistHtml) { minelistHtml = h; box.innerHTML = h; }
  if (wait) pendT = setTimeout(() => { if (cur === 'interests') renderMine(); }, wait + 50);
  const has = m.interests.length || inflight.length;
  $('i-done').innerHTML = !has ? '' : m.joined ? '<button class="btn" data-act="go" data-to="me">Done</button>'
    : (!inflight.length ? '<button class="btn" data-act="go" data-to="color">Next: pick a light color</button>' : '');
}
/* "computers, AI, music" is three interests: split on commas, semicolons and line breaks only (never "and" or
   spaces), trim, drop empties and anything already in the list (case-insensitive). Returns the new ones and the repeats. */
function splitInterests(text, have) {
  const seen = new Set((have || []).map(x => x.toLowerCase())), out = [], dup = [];
  text.split(/[,;\n\r]+/).forEach(p => {
    p = p.replace(/\s+/g, ' ').trim();
    if (!p) return;
    if (seen.has(p.toLowerCase())) { if (!dup.some(d => d.toLowerCase() === p.toLowerCase())) dup.push(p); return; }
    seen.add(p.toLowerCase()); out.push(p);
  });
  return {out, dup};
}
function haveLabels() { const m = me(); return (m ? m.interests.map(i => i.label) : []).concat(inflight); }
function dupMsg(dup) { return 'You already have ' + joinNames(dup) + '.'; }
function updateCount() {
  const seg = $('itext').value.split(/[,;\n\r]+/).pop().trim().length, c = $('i-cnt');
  c.textContent = seg >= 32 ? seg + ' of ' + MAX_LABEL + ' letters' : '';
  c.classList.toggle('over', seg > MAX_LABEL);
}
async function addInterest() {
  const m = me(), inp = $('itext'), v = inp.value.trim(), err = $('i-err');
  if (!m) return;
  if (!v) { err.textContent = ''; inp.focus(); return; }
  const {out: parts, dup} = splitInterests(v, haveLabels());
  if (parts.some(p => p.length > MAX_LABEL)) { err.textContent = 'Keep each one to ' + MAX_LABEL + ' letters or fewer.'; inp.focus(); return; }
  if (!parts.length) { err.textContent = dupMsg(dup); inp.focus(); return; }
  err.textContent = dup.length ? dupMsg(dup) : '';
  inp.value = dup.join(', '); updateCount(); inp.focus();
  inflight = inflight.concat(parts); renderMine();
  const failed = []; let msg = '';
  for (const label of parts) {
    try { await api('POST', '/api/people/' + m.id + '/interests', {label}); }
    catch (e) { failed.push(label); msg = e.status === 400 ? 'That one didn’t work. Try a shorter word or two.' : failMsg(e, "Couldn't add that"); }
  }
  inflight = inflight.filter(x => !parts.includes(x));
  if (failed.length) { inp.value = failed.concat(inp.value ? inp.value.split(', ') : []).join(', '); err.textContent = msg; updateCount(); }
  await refresh(true); renderMine();
}
async function saveEdit(id) {
  const i = IN[id], el = $('edit'), v = (el ? el.value : editVal).replace(/\s+/g, ' ').trim();
  if (!v || !i || v === i.label) { editing = null; editErr = ''; renderMine(); return; }
  const m = me();
  if (m && m.interests.some(x => x.id !== id && x.label.toLowerCase() === v.toLowerCase())) { editVal = v; editErr = 'You already have ' + v + '.'; renderMine(); return; }
  try { await api('PATCH', '/api/interests/' + id, {label: v}); }
  catch (e) { editVal = v; editErr = failMsg(e, "Couldn't change that"); renderMine(); return; }
  editing = null; editErr = '';
  await refresh(true); renderMine();
}
async function rmYes(id) {
  removing = null;
  try { await api('DELETE', '/api/interests/' + id); } catch (e) { flash(failMsg(e, "Couldn't remove that")); }
  await refresh(true); renderMine();
}

/* sketch pad: a full-screen sheet; the line looks like a groove drawn in sand */
const cv = $('cv'), cx = cv.getContext('2d');
let strokes = [], curStroke = null;
function padRender() {
  cx.clearRect(0, 0, 600, 600); cx.fillStyle = '#efe5c6'; cx.fillRect(0, 0, 600, 600);
  cx.lineCap = cx.lineJoin = 'round';
  [[2.5, '#fffdf0', 14], [0, '#b8a56f', 11], [0, '#86733f', 5.5]].forEach(pass => {
    cx.strokeStyle = pass[1]; cx.lineWidth = pass[2];
    strokes.forEach(s => {
      const q = s.map(p => [p[0] * 600 + pass[0], p[1] * 600 + pass[0]]);
      cx.beginPath(); cx.moveTo(q[0][0], q[0][1]);
      if (q.length === 1) cx.lineTo(q[0][0] + .1, q[0][1]);
      for (let k = 1; k < q.length - 1; k++) cx.quadraticCurveTo(q[k][0], q[k][1], (q[k][0] + q[k + 1][0]) / 2, (q[k][1] + q[k + 1][1]) / 2);
      if (q.length > 1) cx.lineTo(q[q.length - 1][0], q[q.length - 1][1]);
      cx.stroke();
    });
  });
}
function padSize() {
  const w = $('padwrap'), s = Math.max(150, Math.floor(Math.min(w.clientWidth, w.clientHeight)));
  cv.style.width = cv.style.height = s + 'px';
}
function padHint() {
  const name = $('pad-name').value.trim(), h = $('pad-hint');
  const need = !name && !strokes.length ? 'Add a name and draw something.' : !name ? 'Add a name to save it.' : !strokes.length ? 'Draw something to save it.' : '';
  if (!h.dataset.err) h.textContent = need;
  $('pad-use').disabled = padBusy || !!need; $('pad-undo').disabled = !strokes.length;
  $('pad-clear').disabled = !strokes.length;
}
function padErr(msg) { const h = $('pad-hint'); h.dataset.err = msg ? '1' : ''; h.classList.toggle('bad', !!msg); h.textContent = msg || ''; padHint(); }
function openPad(id, name) {
  padTarget = id || null; padFixed = !!id; padBusy = false; strokes = []; curStroke = null;
  const inp = $('pad-name'), i = id && IN[id];
  inp.value = i ? i.label : (name || ''); inp.readOnly = padFixed;
  $('pad-lbl').textContent = padFixed ? 'Drawing for' : 'What is it?';
  inp.classList.toggle('fixed', padFixed);
  padErr('');
  $('pad').classList.add('on'); padSize(); padRender(); padHint();
}
function closePad() { $('pad').classList.remove('on'); padTarget = null; curStroke = null; }
function padPos(e) { const r = cv.getBoundingClientRect(); return [Math.min(1, Math.max(0, (e.clientX - r.left) / r.width)), Math.min(1, Math.max(0, (e.clientY - r.top) / r.height))]; }
function padAdd(e) {
  const p = padPos(e), l = curStroke[curStroke.length - 1];
  if (Math.hypot(p[0] - l[0], p[1] - l[1]) < .004) return;
  curStroke.push(p);
}
cv.addEventListener('pointerdown', e => {
  e.preventDefault();
  if (document.activeElement && document.activeElement.blur) document.activeElement.blur();   // keyboard down, so the canvas stays visible
  if (curStroke) return;
  if (strokes.length >= MAX_STROKES) { padErr('That’s plenty of lines. Undo one, or tap Use my drawing.'); return; }
  if ($('pad-hint').dataset.err) padErr('');
  cv.setPointerCapture(e.pointerId);
  curStroke = [padPos(e)]; strokes.push(curStroke); padRender(); padHint();
});
cv.addEventListener('pointermove', e => {
  if (!curStroke) return;
  e.preventDefault();
  (e.getCoalescedEvents ? e.getCoalescedEvents() : [e]).forEach(ev => padAdd(ev.clientX === undefined ? e : ev));
  padRender();
});
['pointerup', 'pointercancel'].forEach(t => cv.addEventListener(t, () => { curStroke = null; }));
cv.addEventListener('touchmove', e => e.preventDefault(), {passive: false});
cv.addEventListener('contextmenu', e => e.preventDefault());
window.addEventListener('resize', () => { if ($('pad').classList.contains('on')) padSize(); });
function undoPad() { if (!strokes.length) return; strokes.pop(); curStroke = null; padErr(''); padRender(); padHint(); }
function clearPad() { strokes = []; curStroke = null; padErr(''); padRender(); padHint(); }
/* Douglas-Peucker with a growing tolerance until the line fits, so corners survive thinning. */
function rdp(pts, eps) {
  if (pts.length < 3) return pts;
  const a = pts[0], b = pts[pts.length - 1], dx = b[0] - a[0], dy = b[1] - a[1], L = Math.hypot(dx, dy);
  let dm = 0, im = 0;
  for (let k = 1; k < pts.length - 1; k++) {
    const d = L ? Math.abs(dy * (pts[k][0] - a[0]) - dx * (pts[k][1] - a[1])) / L : Math.hypot(pts[k][0] - a[0], pts[k][1] - a[1]);
    if (d > dm) { dm = d; im = k; }
  }
  if (dm <= eps) return [a, b];
  return rdp(pts.slice(0, im + 1), eps).slice(0, -1).concat(rdp(pts.slice(im), eps));
}
function thin(pts, max) {
  let eps = .0008;
  while (pts.length > max && eps < .5) { pts = rdp(pts, eps); eps *= 1.6; }
  if (pts.length > max) { const o = []; for (let k = 0; k < max; k++) o.push(pts[Math.round(k * (pts.length - 1) / (max - 1))]); pts = o; }
  if (pts.length === 1) pts = [pts[0], [Math.min(1, pts[0][0] + .003), pts[0][1]]];
  return pts.map(p => [Math.round(p[0] * 1000) / 1000, Math.round(p[1] * 1000) / 1000]);
}
function padStrokes() {
  const list = strokes.slice(0, MAX_STROKES), per = Math.max(2, Math.min(MAX_PER_STROKE, Math.floor((MAX_POINTS - 4) / list.length)));
  return list.map(s => thin(s, per));
}
async function donePad() {
  const name = $('pad-name').value.replace(/\s+/g, ' ').trim();
  if (padBusy || !name || !strokes.length) return;
  const m = me(), id = padTarget;
  if (!id && m && haveLabels().some(x => x.toLowerCase() === name.toLowerCase())) { padErr('You already have ' + name + '. Use another name.'); return; }
  padBusy = true; padErr(''); $('pad-use').textContent = 'Saving...'; padHint();
  try {
    const out = padStrokes();
    if (id) await api('PATCH', '/api/interests/' + id, {strokes: out});
    else await api('POST', '/api/people/' + m.id + '/interests', {label: name, strokes: out});
  } catch (e) {
    padBusy = false; $('pad-use').textContent = 'Use my drawing';
    padErr(e.status === 400 ? 'That one didn’t work. Try a different name or fewer lines.' : failMsg(e, "Couldn't save your drawing") + ' Your drawing is still here.');
    return;
  }
  padBusy = false; $('pad-use').textContent = 'Use my drawing';
  if (!id) { $('itext').value = ''; updateCount(); $('i-err').textContent = ''; }
  closePad(); await refresh(true); renderMine();
}

/* ---------- 4 colour + summary ---------- */
let chosenColor = undefined;
function renderColor() {
  const m = me(); if (!m) return;
  if (chosenColor === undefined) chosenColor = m.color;
  $('sw').innerHTML = COLORS.map((c, i) => '<button title="' + c[0] + '" aria-label="' + c[0] + '" class="' + (i === chosenColor ? 'on' : '') + '" style="background:' + c[1] + '" data-act="pickColor" data-i="' + i + '"></button>').join('');
  const n = m.interests.length;
  $('summary').innerHTML = '<div class="sumrow">' + thumb(m) + '<div><b style="font-size:1.2rem">' + esc(m.name) + '</b><div style="color:var(--dim);font-size:.88rem">' + (m.faces > 0 ? 'Face, name and ' : 'Name and ') + n + ' interest' + (n === 1 ? '' : 's') + '</div></div></div>' +
    '<div class="mini" style="gap:6px;margin-top:8px;flex-wrap:wrap">' + m.interests.map(x => iconImg(x, 'style="width:44px;height:44px" title="' + esc(x.label) + '"')).join('') + '</div>' +
    '<div style="margin-top:6px;font-size:.9rem">' + m.interests.map(x => esc(x.label)).join(', ') + '</div>' +
    '<div style="margin-top:8px;font-size:.9rem;display:flex;align-items:center;gap:8px">Light: <i style="width:18px;height:18px;border-radius:50%;display:inline-block;background:' + (chosenColor >= 0 && chosenColor != null ? COLORS[chosenColor][1] : '#ddd') + '"></i>' + (chosenColor >= 0 && chosenColor != null ? COLORS[chosenColor][0] : 'Any') + '</div>';
}
async function addMe() {
  const m = me(); if (!m) return;
  $('join-err').textContent = ''; $('joinbtn').disabled = true;
  try {
    await api('PATCH', '/api/people/' + m.id, {joined: true, color: chosenColor >= 0 && chosenColor != null ? chosenColor : null});
    chosenColor = undefined; await refresh(true); go('me');
  } catch (e) { $('join-err').textContent = failMsg(e, "Couldn't add you"); }
  $('joinbtn').disabled = false;
}

/* ---------- 5 status ---------- */
/* While the table isn't drawing (clock "idle") nobody can know a time, only how many drawings come first. */
function isIdle() { return S.clock === 'idle'; }
function waitLine(m, who) {
  if (m.next_in == null) return null;
  // next_in counts turns that start before theirs; a turn that is waiting or in progress comes first too.
  const c = S.table && S.table.current, n = m.next_in + (c && !c.done && c.person_id !== m.id ? 1 : 0);
  if (n === 0) return who + ' turn is the next one';
  return who + ' turn comes after ' + n + ' more drawing' + (n === 1 ? '' : 's');
}
function renderMe() {
  const m = me(); if (!m) return;
  const noun = m.faces > 0 ? 'face' : 'name';
  // The turn being drawn (or waiting to be drawn) for this person: their zone is assigned, but not finished in sand.
  const cur0 = S.table && S.table.current, mine = !!(cur0 && !cur0.done && cur0.kind !== 'clear' && cur0.person_id === m.id);
  const drawnElsewhere = (m.zones || []).some(z => !mine || z !== cur0.zone);
  const onTable = !!m.zone && (!mine || drawnElsewhere);
  let t, t2 = '', head = null;
  if (mine && !drawnElsewhere && isIdle() && !(cur0.percent > 0)) { head = 'You’re up next'; t = 'Your turn is the next one.'; t2 = 'The table isn’t drawing right now.'; }
  else if (mine && !drawnElsewhere) { head = 'It’s your turn'; t = 'The table is drawing your ' + noun + ' now.'; }
  else if (isIdle() && !onTable && waitLine(m, 'Your')) { t = waitLine(m, 'Your'); t2 = 'The table isn’t drawing right now.'; }
  else if (onTable && m.next_at && m.next_zone === 'centre') t = 'You’re on the table. Your ' + noun + ' is featured in the middle next at about ' + fmt(m.next_at) + '.';
  else if (onTable) t = m.faces > 0 ? 'Your name and face are on the table now.' : 'Your name is on the table now.';
  else if (m.next_at) t = 'Your ' + noun + ' is featured next at about ' + fmt(m.next_at) + '. Once everyone has had a turn, it comes around again.';
  else t = 'You’re on the list. Your turn time will show up here shortly.';
  $('me-top').innerHTML = '<div class="th" style="width:90px;height:90px;margin:10px auto;font-size:1.6rem">' + faceInner(m) + '</div>' + (m.faces > 0 && m.face_pending ? '<p class="dim center" style="margin:-4px 0 6px">Making your sand drawing...</p>' : '') +
    '<h2>' + (head || (onTable ? 'You’re on the table' : 'You’re in the rotation')) + '</h2>' +
    '<p class="big" style="font-size:1.1rem;line-height:1.35">' + esc(t) + '</p>' +
    (t2 ? '<p class="sub">' + esc(t2) + '</p>' : '') +
    '<p class="sub">You don\'t have to wait here. Come back to this page any time to see how close you are.</p>';
  $('me-more').innerHTML = '<button class="btn sec" style="margin-top:0" data-act="go" data-to="photo">Change my photo</button>' +
    '<button class="btn sec" style="margin-top:0" data-act="go" data-to="interests">Change my interests</button>' +
    (m.featured > 0 || onTable ? '<button class="btn sec" style="margin-top:0" data-act="go" data-to="keep">My keepsake</button>' : '') +
    '<div class="center"><button class="link" data-act="switchMe2">Not ' + esc(m.name) + '? Switch</button></div>' +
    '<div class="hostlink"><button class="link" data-act="go" data-to="host">Host</button></div>';
}

/* ---------- 6 table ---------- */
function bigFace(p) {
  return p.faces > 0 && !p.face_pending ? '<img src="' + faceUrl(p) + '" alt="" style="width:110px;height:110px;border-radius:50%;background:var(--sand);box-shadow:0 1px 6px #0003;flex:none">'
    : '<div class="th" style="width:110px;height:110px;font-size:2rem">' + faceInner(p) + '</div>';
}
function miniIcons(ids) { return ids.map(id => IN[id]).filter(Boolean).slice(0, 3).map(i => iconImg(i)).join(''); }
function renderTable() {
  const t = S.table, cur_ = t && t.current;
  const idle = isIdle();
  $('simnote').innerHTML = idle ? '<div class="sim">The table isn’t drawing right now. This is the order it will draw in when it starts.</div>' : '';
  $('pausedbar').innerHTML = S.paused ? '<div class="paused"><b>The table is taking a short break.</b> It will pick up again soon.</div>' : '';
  const p = cur_ && P[cur_.person_id];
  if (cur_ && cur_.kind === 'clear') {
    const steps = cur_.steps || [], step = cur_.step || 0;
    $('nowcard').innerHTML = '<div class="card"><div class="big">Getting a spot ready</div>' +
      '<div class="prog"><i style="width:' + Math.max(0, Math.min(100, cur_.percent || 0)) + '%"></i></div><div style="display:flex;justify-content:space-between;gap:8px"><b>' + esc(steps[step] || '') + '</b><span>' + Math.round(cur_.percent || 0) + '% done</span></div></div>';
  } else if (!cur_ || !p) {
    $('nowcard').innerHTML = '<div class="card center"><b>Nobody is on the table yet.</b><div class="sub" style="margin:6px 0 0">Once people tap “Add me to the table”, they’ll show up here.</div></div>';
  } else {
    const steps = cur_.steps || [], step = cur_.step || 0;
    $('nowcard').innerHTML = '<div class="card"><div style="font-size:.8rem;color:var(--dim);text-transform:uppercase;letter-spacing:.06em">' + (idle && !(cur_.percent > 0) ? 'Up next' : 'Now featuring') + '</div>' +
      '<div class="sumrow" style="margin-top:6px">' + bigFace(p) + '<div style="min-width:0"><div class="big">' + esc(p.name) + '</div><div style="color:var(--dim);font-size:.9rem">' + (idle ? '' : 'Started ' + fmt(cur_.started_at)) + '</div></div></div>' +
      '<div class="prog"><i style="width:' + Math.max(0, Math.min(100, cur_.percent || 0)) + '%"></i></div><div style="display:flex;justify-content:space-between;gap:8px"><b>' + esc(steps[step] || '') + '</b><span>' + Math.round(cur_.percent || 0) + '% done</span></div>' +
      (cur_.done ? '<p class="sub" style="margin:8px 0 0">Next drawing starts at ' + fmt(t.hold_until) + '</p></div>'
        : '<ul class="steps">' + steps.map((s, k) => '<li class="' + (k < step ? 'd' : k === step ? 'n' : '') + '">' + esc(s) + '</li>').join('') + '</ul></div>');
  }
  const up = (t && t.upcoming) || [];
  $('uplist').innerHTML = up.filter(u => u.kind !== 'clear' && P[u.person_id]).map((u, k) => {
    const q = P[u.person_id];
    const you = q.id === myId;
    return '<div class="row' + (you ? ' you' : '') + '"><b style="width:18px;color:var(--dim)">' + (k + 1) + '</b>' + thumb(q) + '<div class="nm"><b>' + esc(q.name) + (you ? '<span class="tag">you</span>' : '') + '</b><div class="mini">' + miniIcons(u.interest_ids || []) + '</div></div>' + (idle ? '' : '<div class="tm">' + fmt(u.at) + '</div>') + '</div>';
  }).join('') || '<p class="sub">Nobody is coming up yet.</p>';
}

/* ---------- 9 everyone ---------- */
/* One short pill per person, always visible: drawing now, on the table, the time, or how many drawings come first. */
function statusPill(p) {
  if (!p.joined) return ['off', 'Not joined yet'];
  const c = S.table && S.table.current, mine = !!(c && !c.done && c.kind !== 'clear' && c.person_id === p.id);
  if (mine && (S.clock === 'table' || c.percent > 0)) return ['now', 'Drawing now'];
  const elsewhere = (p.zones || []).some(z => !mine || z !== c.zone);
  if (p.zone && (!mine || elsewhere)) return ['on', 'On the table'];
  if (mine) return ['when', 'Next'];
  if (isIdle()) {
    if (p.next_in == null) return ['off', 'In the rotation'];
    const n = p.next_in + (c && !c.done ? 1 : 0);
    return ['when', n === 0 ? 'Next' : 'After ' + n + ' drawing' + (n === 1 ? '' : 's')];
  }
  if (p.next_at) return ['when', fmt(p.next_at)];
  return ['off', 'In the rotation'];
}
function renderEveryone() {
  const pins = (S.table || {}).pinned || [], pin = p => { const k = pins.indexOf(p.id); return k < 0 ? 1e6 : k; };   // host's chosen few come first
  const joined = S.people.filter(p => p.joined).sort((a, b) => pin(a) - pin(b) || (a.zone ? 0 : 1) - (b.zone ? 0 : 1) || (a.next_at || 9e12) - (b.next_at || 9e12) || a.name.localeCompare(b.name));
  const rest = S.people.filter(p => !p.joined).sort((a, b) => a.name.localeCompare(b.name));
  const head = (p, you) => { const pl = statusPill(p); return '<div class="top"><b>' + esc(p.name) + '</b>' + (you ? '<span class="tag">you</span>' : '') + '<span class="pill ' + pl[0] + '">' + pl[1] + '</span></div>'; };
  let h = joined.map(p => {
    const you = p.id === myId;
    const ints = p.interests.map(i => {
      const sh = i.shared_with || [];
      return '<span>' + iconImg(i) + '<div>' + esc(i.label) + (sh.length ? '<small class="sh">shared with ' + esc(joinNames(sh)) + '</small>' : '') +
        relatedLines(i, 'also into').map(l => '<small class="sh rel">' + esc(l) + '</small>').join('') + '</div></span>';
    }).join('');
    return '<div class="ev"><div class="row' + (you ? ' you' : '') + '">' + thumb(p) + '<div class="nm">' + head(p, you) + '<div class="ints">' + ints + '</div></div></div></div>';
  }).join('');
  h += rest.map(p => '<div class="ev"><div class="row">' + thumb(p) + '<div class="nm">' + head(p, false) + (p.faces || p.interests.length ? '' : '<small>Hasn’t added a photo or interests yet</small>') + '</div></div></div>').join('');
  $('evlist').innerHTML = h || '<p class="sub">Nobody is here yet.</p>';
}

/* ---------- 7 keepsake ---------- */
/* The picture is made on the server (sand-relief look, from what the table really drew). */
function keepUrl(m) { return '/img/keepsake/' + m.id + '.png?v=' + m.keepsake_v + (m.keepsake_v > 0 ? '' : '&t=' + keepT); }
function renderKeep() {
  const m = me(); if (!m) return;
  $('keep-h').textContent = m.name + '’s keepsake';
  $('keep-sub').textContent = m.keepsake_v > 0 ? 'The whole table right after your turn.' : 'The table as it is right now.';
  const im = $('keepimg'), url = keepUrl(m);
  if (im.getAttribute('src') !== url) im.src = url;
}
function saveKeep() {
  const m = me(); if (!m) return;
  const a = document.createElement('a'); a.href = keepUrl(m); a.download = 'my-sand-table.png';
  document.body.appendChild(a); a.click(); a.remove();
}

/* ---------- 8 host ---------- */
function renderHost() {
  const t = S.table || {}, cur_ = t.current, seenIds = new Set();
  $('pausetxt').textContent = S.paused ? 'Table is paused' : (isIdle() ? 'Not paused, but the table isn’t drawing right now' : 'Table is drawing');
  $('pausesw').textContent = S.paused ? 'Resume the table' : 'Pause the table';
  let h = '';
  if (cur_ && P[cur_.person_id]) {
    seenIds.add(cur_.person_id);
    h += '<div class="row" style="background:#f3f0e3"><b style="width:18px">1</b>' + thumb(P[cur_.person_id], 'sm') + '<div class="nm"><b>' + esc(P[cur_.person_id].name) + '</b><small>' + (isIdle() && !(cur_.percent > 0) ? 'Up next, ' : 'Featuring now, ') + Math.round(cur_.percent || 0) + '%</small></div></div>';
  }
  const rest = (t.upcoming || []).filter(u => P[u.person_id] && !seenIds.has(u.person_id) && seenIds.add(u.person_id));
  h += rest.map((u, i) => {
    const p = P[u.person_id];
    return '<div class="row hrow' + (p.id === myId ? ' you' : '') + '"><b style="width:18px">' + (i + 2) + '</b>' + thumb(p, 'sm') + '<div class="nm"><b>' + esc(p.name) + '</b>' + (isIdle() ? '' : '<small>' + fmt(u.at) + '</small>') + '</div>' +
      '<button class="ib" title="Move up" aria-label="Move ' + esc(p.name) + ' up" ' + (i === 0 ? 'disabled' : '') + ' data-act="mv" data-id="' + p.id + '" data-d="-1">&#9650;</button>' +
      '<button class="ib" title="Move down" aria-label="Move ' + esc(p.name) + ' down" ' + (i === rest.length - 1 ? 'disabled' : '') + ' data-act="mv" data-id="' + p.id + '" data-d="1">&#9660;</button>' +
      '<button class="ib rm" title="Remove" aria-label="Remove ' + esc(p.name) + '" data-act="rmq" data-id="' + p.id + '">&#10005;</button></div>';
  }).join('');
  $('hline').innerHTML = (h || '<p class="sub">Nobody has joined yet.</p>') + '<p class="sub" style="font-size:.82rem">After the last person it goes back to the first, over and over.</p>';
  renderErase(); renderArt(); renderGuests();
}
function renderErase() {
  const e = (S.table || {}).erase, way = d => d === 'in' ? 'spiral in, from the rim to the middle' : 'spiral out, from the middle to the rim';
  $('erasebox').innerHTML = !e
    ? '<div class="two2"><button class="btn sec" data-act="eraseAsk" data-d="in">Spiral in<small>rim to middle</small></button><button class="btn sec" data-act="eraseAsk" data-d="out">Spiral out<small>middle to rim</small></button></div>'
    : e.status === 'running'
      ? '<div class="notice warn"><b>Erasing the table now</b><br>' + way(e.dir).replace(/^s/, 'S') + '. The rotation starts again when it’s done.</div>'
      : '<div class="notice warn"><b>Erase requested</b><br>' + way(e.dir).replace(/^s/, 'S') + '. It starts when the table finishes the piece it is drawing.</div><button class="btn sec" data-act="eraseCancel">Cancel the erase</button>';
}
function renderArt() {
  const a = S.centre_art || [];
  $('artlist').innerHTML = a.length ? a.map(x => '<div class="cart' + (x.enabled ? '' : ' off') + '"><img src="/img/centre-art/' + encodeURIComponent(x.key) + '.png?s=120&v=' + x.v + '" alt="">' +
    '<div class="nm">' + esc(x.label) + '</div><button class="tg" role="switch" aria-checked="' + !!x.enabled + '" aria-label="' + esc(x.label) + '" data-act="togArt" data-k="' + esc(x.key) + '"></button></div>').join('')
    : "<p class=\"sub\">The table hasn't sent its Thanksgiving pictures yet.</p>";
}
function renderGuests() {
  const list = S.people.slice().sort((a, b) => a.name.localeCompare(b.name));
  const forced = ((S.table || {}).forced || []);
  $('glist').innerHTML = list.map(p => { const f = forced.some(x => x.person_id === p.id); return '<div class="grow">' + thumb(p, 'sm') + '<div class="nm"><b>' + esc(p.name) + '</b><small>' + (f ? 'In the middle next' : p.joined ? 'Joined' : 'Not joined yet') + '</small></div>' +
    '<div class="gacts">' + (p.joined ? '<button class="btn sec" ' + (f ? 'disabled ' : '') + 'aria-label="Feature ' + esc(p.name) + ' now" data-act="featNow" data-id="' + p.id + '">Feature now</button>' : '') +
    '<button class="btn sec del" aria-label="Remove ' + esc(p.name) + '" data-act="rmGuest" data-id="' + p.id + '">Remove</button></div></div>'; }).join('') || '<p class="sub">Nobody is on the list yet.</p>';
}
async function hostCall(method, path, body) {
  try { const s = await api(method, path, body); if (s && s.people) { sig = digest(s); adopt(s); renderAll(); } else await refresh(true); }
  catch (e) { flash(failMsg(e, "That didn't go through")); }
}
async function addNames() {
  const v = $('addnames').value.split(/\n|,/).map(s => s.trim()).filter(Boolean);
  if (!v.length) return;
  try {
    const r = await api('POST', '/api/people/bulk', {names: v});
    $('addmsg').innerHTML = '<div class="notice ok">Added ' + r.added + ' name' + (r.added === 1 ? '' : 's') + ' to the list.</div>';
    $('addnames').value = ''; await refresh(true);
  } catch (e) { $('addmsg').innerHTML = '<div class="err">' + esc(failMsg(e, "Couldn't add those names")) + '</div>'; }
}

/* ---------- actions ---------- */
const acts = {
  go: el => go(el.dataset.to),
  retry: () => refresh(true).then(() => { if (S) show(fromHash()); }),
  navBack: () => go(prevOf(cur)),
  navNext: () => { if (cur === 'color') addMe(); else go(nextOf(cur)); },
  whoNew: () => { whoMode = 'new'; $('newname').value = ''; $('newerr').textContent = ''; renderWho(); $('newname').focus(); },
  whoList: () => { whoMode = 'list'; renderWho(); },
  keepGoing: () => { welcome = false; const m = me(); go(m && m.joined ? 'me' : 'photo'); },
  switchMe: () => { welcome = false; whoMode = 'list'; renderWho(); renderNav(); },
  switchMe2: () => { setMe(null); welcome = false; whoMode = 'list'; go('who'); },
  pickPerson: el => {
    setMe(+el.dataset.id); welcome = false; chosenColor = undefined; ph.stage = 'up'; editing = null;
    const m = me(); go(m && m.joined ? 'me' : 'photo');
  },
  newDone: async () => {
    const v = $('newname').value.trim(); if (!v) return;
    $('newerr').textContent = ''; $('newgo').disabled = true;
    try {
      const p = await api('POST', '/api/people', {name: v});
      setMe(p.id); welcome = false; chosenColor = undefined; ph.stage = 'up'; whoMode = 'list';
      await refresh(true); go('photo');
    } catch (e) {
      if (e.status === 409) takenNotice((e.data && e.data.name) || v);
      else $('newerr').textContent = e.status === 400 ? 'That name doesn’t work. Use 1 to 30 characters.' : failMsg(e, "Couldn't add you");
      $('newgo').disabled = false;
    }
  },
  photoSkip: () => afterPhoto(),
  photoUp: () => { setStage('up'); $('file').value = ''; $('cam').value = ''; },
  photoFaces: () => { if (ph.boxes.length) { setStage('faces'); renderFaces(); } else setStage('up'); },
  photoDone: () => afterPhoto(),
  togFace: el => {
    const i = +el.dataset.i;
    ph.sel = ph.sel.includes(i) ? ph.sel.filter(x => x !== i) : ph.sel.concat(i).slice(-2);
    renderFaces();
  },
  showSand: showSand,
  useMiddle: useMiddle,
  addInterest: addInterest,
  editRow: el => { editing = +el.dataset.id; removing = null; editErr = ''; editVal = IN[editing] ? IN[editing].label : ''; renderMine(); const e = $('edit'); if (e) { e.focus(); e.select(); } },
  cancelEdit: () => { editing = null; editErr = ''; renderMine(); },
  saveEdit: el => saveEdit(+el.dataset.id),
  rmRow: el => { removing = +el.dataset.id; editing = null; renderMine(); },
  rmYes: el => rmYes(+el.dataset.id),
  rmNo: () => { removing = null; renderMine(); },
  openPad: el => openPad(+el.dataset.id),
  drawNew: () => { const v = $('itext').value.split(/[,;\n\r]+/)[0].replace(/\s+/g, ' ').trim().slice(0, MAX_LABEL); openPad(null, v); if (!v) $('pad-name').focus(); },
  undoPad: undoPad,
  clearPad: clearPad,
  closePad: closePad,
  donePad: donePad,
  pickColor: el => { chosenColor = +el.dataset.i; renderColor(); },
  addMe: addMe,
  saveKeep: saveKeep,
  togglePause: () => hostCall('POST', '/api/host/pause', {paused: !S.paused}),
  skipNow: () => hostCall('POST', '/api/host/skip'),
  mv: el => hostCall('POST', '/api/host/move', {person_id: +el.dataset.id, dir: +el.dataset.d}),
  rmq: el => { const p = P[+el.dataset.id]; if (p && confirm('Remove ' + p.name + ' from the table?')) hostCall('DELETE', '/api/people/' + p.id); },
  togArt: el => { const a = (S.centre_art || []).find(x => x.key === el.dataset.k); if (a) hostCall('POST', '/api/host/centre-art', {key: a.key, enabled: !a.enabled}); },
  featNow: el => { const p = P[+el.dataset.id]; if (p && confirm('Draw ' + p.name + ' in the middle next?')) hostCall('POST', '/api/host/feature', {person_id: p.id, zones: ['centre']}); },
  eraseAsk: el => { const d = el.dataset.d; if (confirm('Erase the whole table (' + (d === 'in' ? 'spiral in' : 'spiral out') + ')? Every drawing is wiped and the rotation starts again. It takes about 15 to 20 minutes.')) hostCall('POST', '/api/host/erase', {dir: d}); },
  eraseCancel: () => hostCall('POST', '/api/host/erase', {dir: null}),
  rmGuest: el => { const p = P[+el.dataset.id]; if (p && confirm('Remove ' + p.name + '? They come off the table and the list, and their photo and drawings are deleted.')) hostCall('DELETE', '/api/people/' + p.id); },
  addNames: addNames
};
document.addEventListener('click', e => {
  const el = e.target.closest('[data-act]');
  if (el && acts[el.dataset.act]) { if (el.disabled) return; acts[el.dataset.act](el); }
});
$('search').addEventListener('input', () => { if (S) renderPeople(); });
$('newname').addEventListener('input', () => { if (S) checkName(); });
$('itext').addEventListener('keydown', e => { if (e.key === 'Enter') { e.preventDefault(); addInterest(); } });
$('itext').addEventListener('input', () => { $('i-err').textContent = ''; updateCount(); });
$('iadd').addEventListener('pointerdown', e => e.preventDefault());   // keep the keyboard up so several can be typed in a row
$('pad-name').addEventListener('input', () => { if ($('pad-hint').dataset.err) padErr(''); else padHint(); });
$('pad-name').addEventListener('keydown', e => { if (e.key === 'Enter') { e.preventDefault(); e.target.blur(); } });
$('body').addEventListener('input', e => { if (e.target.id === 'edit') editVal = e.target.value; });
$('body').addEventListener('keydown', e => { if (e.target.id === 'edit' && e.key === 'Enter') saveEdit(editing); if (e.target.id === 'newname' && e.key === 'Enter' && !$('newgo').disabled) acts.newDone(); });
['file', 'cam'].forEach(id => $(id).addEventListener('change', e => { const f = e.target.files[0]; e.target.value = ''; handleFile(f); }));

/* ---------- boot ---------- */
(async function boot() {
  padRender();
  await refresh(true);
  if (!S) return;
  const h = location.hash.slice(1);
  welcome = !!me() && (h === '' || h === 'who');
  show(fromHash());
})();
if ('serviceWorker' in navigator) navigator.serviceWorker.register('/sw.js').catch(() => {});   // installable app (manifest.json + sw.js)
