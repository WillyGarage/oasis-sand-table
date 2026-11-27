// Send a continuous center, border or whole-tray drawing from a phone to the measured Mini.
(() => {
  'use strict';
  const device = '95878d6310836abdf12f3927';
  const calibration = {l:.46, ef:.30283, b1:.000613592, b2:.000122718, phi0:2.31486, a:.000552233,
    a1:.000306796, k:.0000613592, rmax:.905, emarg:.05, th0:0};
  // Completed, photographed drawings on this Mini, from the seven gables through the musical note.
  const photographed = new Map([
    ['ca89163524fe9c46f4ca017b4ffc644cabdcfa2c474f7caa68d14abe6db1198b','portrait'],
    ['c667cb933ebc7d1360072d2c26dc34a0630996b16aded43f89052f4da0d05b83','blank'],
    ['0f7de46ec69855fffcde021ec7144e35b1b65986bccf5f69ba310d7f3df3219b','phage'],
    ['61c8e44642013af68f50ef17cf31fca0c00df066482da1c4ecea8deea3e2b3ed','blank'],
    ['a6f46889606d3fd373e346f7d8af8a63251f42758002074064f7259580147f1d','guitar'],
    ['a1a759434a86d62e07f04f3c621303539fb3fadd22af07f4932759931218a502','guitar-note']
  ]);
  const kinds = ['frame','phage','guitar','photo','book','book-pencil','whole-portrait'];
  const drawingNames = {frame:'seven-roof border',phage:'phage in the center',guitar:'guitar in the center',photo:'photo in the center',
    book:'open book', 'book-pencil':'pencil on the open book', 'whole-portrait':'whole-table portrait'};
  const namespace = 'da139eab3ff605da2e2a72e7'; // SHA-256("oasis-mini/seven-roof-center/v1"), first 96 bits.
  const dock = -Math.PI/2, turn = 2*Math.PI;
  const previews = new WeakSet();
  let offered = null, sending = false;
  function calibrated(status) {
    return status?.device_id===device && status.fw==='v8.17' && status.steps_rev===11378 && status.home_steps===10700 &&
      Object.entries(calibration).every(([key,value])=>status.cal?.[key]===value);
  }
  function encodedKind(id, count) {
    if (typeof id!=='string' || !/^[0-9a-f]{64}$/.test(id) || !id.startsWith(namespace) ||
        parseInt(id.slice(34,38),16)!==count || count<2 || count>12000) return;
    return kinds.find((_,i)=>id.slice(24,26)===hex(i,2));
  }
  function center(status) {
    if (status.receipt?.state!=='complete') return;
    const id = status.receipt.id;
    const kind = encodedKind(id,status.pattern_points);
    return photographed.get(id) || (kind==='whole-portrait' ? undefined : kind==='frame' ? 'unknown' : kind);
  }
  function finishedWholePortrait(status) {
    return calibrated(status) && status.state==='idle' && status.receipt?.state==='complete' &&
      encodedKind(status.receipt.id,status.pattern_points)==='whole-portrait';
  }
  function recognized(status) { return calibrated(status) && !!center(status); }
  function hex(number,width) { return number.toString(16).padStart(width,'0'); }
  function runId(kind,rev,count) {
    // getRandomValues also works on the Mini's plain HTTP address. Each press has its own receipt.
    const random = Array.from(crypto.getRandomValues(new Uint8Array(13)),n=>hex(n,2)).join('');
    return namespace+hex(kinds.indexOf(kind),2)+hex(Number(rev),8)+hex(count,4)+random;
  }
  function angleGap(a,b) {
    const delta=a-b;
    return Math.abs(delta-turn*Math.round(delta/turn));
  }
  function atRim(s) { return Number.isFinite(s.theta) && Number.isFinite(s.rho) && Math.abs(s.rho-1)<=.001; }
  function available(s) {
    return s.homed===1 && s.fault===0 && s.paused===0 && s.auto===0 && s.boot_pending===0 &&
      Array.isArray(s.queue) && !s.queue.length;
  }
  function canPrepareWhole(s, g) {
    return calibrated(s) && available(s) && atRim(s) && s.state==='idle' &&
      !['staged','running'].includes(s.receipt?.state) && g?.pending===false && g.evolving===false;
  }
  async function request(path, options) {
    const response = await fetch(path,{cache:'no-store',redirect:'error',...options});
    if (!response.ok) throw Error('The Mini declined the request. Check the table and preview again.');
    return response;
  }
  async function observe() {
    const g = await (await request('/guest-state')).json();
    const s = await (await request('/status')).json();
    if (!calibrated(s)) throw Error('This drawing needs the measured Oasis Mini and its original calibration.');
    if (typeof g.rev!=='string' || !/^(0|[1-9]\d{0,9})$/.test(g.rev) || Number(g.rev)>0xffffffff ||
        !s.receipt || typeof s.receipt.id!=='string' ||
        !(s.receipt.state==='none' ? s.receipt.id==='' :
          ['staged','running','complete','failed'].includes(s.receipt.state) && /^[0-9a-fA-F]{64}$/.test(s.receipt.id)))
      throw Error('The Mini could not confirm the current drawing.');
    if (!available(s) || g.pending!==false || g.evolving!==false)
      throw Error('The Mini must be ready, with no other drawing or automatic changes scheduled.');
    return {s,rev:g.rev};
  }
  function stagedJob(s,rev) {
    if (!calibrated(s) || !available(s) || s.state!=='idle' || s.receipt?.state!=='staged' || !atRim(s)) return;
    const id=s.receipt.id, count=s.pattern_points, kind=encodedKind(id,count);
    if (!kind || String(parseInt(id.slice(26,34),16))!==rev || (!['frame','whole-portrait'].includes(kind) && angleGap(s.theta,dock)>.002)) return;
    return {id,kind,rev,count,theta:s.theta,rho:s.rho};
  }
  function matchesStaged(s,rev,job) {
    const staged = stagedJob(s,rev);
    return !!staged && staged.id===job.id && staged.theta===job.theta && staged.rho===job.rho;
  }
  function prepared(s,rev) {
    offered = stagedJob(s,rev) || null;
    return offered ? drawingNames[offered.kind] : null;
  }
  function stagedError(s,rev) {
    const name=prepared(s,rev);
    if (!name) return Error('Another drawing is prepared. Use the page that requested it.');
    const error = Error('The '+name+' is prepared. Choose Start to draw it.');
    error.canResume = true;
    error.receipt = s.receipt.id;
    return error;
  }
  async function preview(mode='center') {
    if (!['center','frame','whole-portrait'].includes(mode)) throw Error('Unknown drawing area.');
    const {s,rev} = await observe();
    if (s.receipt.state==='staged') throw stagedError(s,rev);
    if (s.state!=='idle' || s.receipt.state==='running') throw Error('The Mini is drawing. Preview again when it finishes.');
    if (!atRim(s)) throw Error('The ball must be at the rim before preparing this drawing.');
    if (mode==='center') {
      if (!center(s)) throw Error('The Mini cannot confirm the seven roofs. Prepare the border first.');
      if (angleGap(s.theta,dock)>.002) throw Error('The center drawing starts at the six-o’clock rim dock.');
    }
    const snapshot = Object.freeze({mode,device,rev,receipt:s.receipt.id,receiptState:s.receipt.state,
      center:center(s)||'unknown',theta:s.theta,rho:s.rho});
    previews.add(snapshot);
    return snapshot;
  }
  function checkedCount(text,snapshot,kind) {
    if (typeof text!=='string' || text.length>600000) throw Error('The drawing file could not be read.');
    const lines = text.split('\n');
    if (lines.at(-1)==='') lines.pop();
    if (lines.length<2 || lines.length>12000) throw Error('This drawing must fit in one Mini file (12,000 points).');
    let prior;
    for (const line of lines) {
      const row = /^(-?\d+(?:\.\d+)?) +(-?\d+(?:\.\d+)?)\r?$/.exec(line);
      if (line.length>47 || !row) throw Error('A point in the drawing could not be read.');
      const theta = Number(row[1]), rho = Number(row[2]);
      if (!Number.isFinite(theta) || rho<0 || rho>1 || (prior && Math.abs(theta-prior.theta)>Math.PI+.00002))
        throw Error('The drawing contains an invalid turn or radius.');
      if (!prior && (angleGap(theta,snapshot.theta)>.002 || Math.abs(rho-snapshot.rho)>.001))
        throw Error('The drawing must start at the ball’s current position.');
      if (kind==='frame') {
        if (rho<.73945) throw Error('The border would cross into the center drawing.');
      } else if (kind==='whole-portrait') {
        if (prior && Math.abs(theta-prior.theta)>.0551) throw Error('The inward portrait contains an unexpected turn.');
      } else if (prior && Math.max(rho,prior.rho)>.66054 &&
          (angleGap(theta,dock)>.00003 || angleGap(prior.theta,dock)>.00003))
        throw Error('The path would cross the seven roofs.');
      prior = {theta,rho};
    }
    if (Math.abs(prior.rho-1)>.00002 || angleGap(prior.theta,dock)>.00002)
      throw Error('The drawing must return to the six-o’clock rim dock.');
    return lines.length;
  }
  function started(s,job) {
    if (s.receipt.id!==job.id || s.pattern_points!==job.count) return false;
    return (s.receipt.state==='running' && ['drawing','moving'].includes(s.state)) ||
      (s.receipt.state==='complete' && s.state==='idle' && atRim(s) && angleGap(s.theta,dock)<=.002);
  }
  async function start(job,observed) {
    if (started(observed.s,job)) return {state:observed.s.receipt.state,receipt:job.id};
    if (!matchesStaged(observed.s,observed.rev,job)) throw Error('The prepared drawing changed. Preview again.');
    try {
      await request('/play',{method:'POST',body:'',headers:{'X-Oasis-Run':job.id,'X-Oasis-Device':device}});
    } catch { /* A lost reply can follow a successful start. Read the receipt before deciding. */ }
    let {s,rev} = await observe();
    // Acknowledgement and motion run on different cores. Do not submit /play again in that handoff.
    for (let i=0;i<3 && s.receipt.id===job.id && s.receipt.state==='running' && s.state==='idle';i++) {
      await new Promise(resolve=>setTimeout(resolve,50));
      ({s,rev}=await observe());
    }
    if (started(s,job)) {
      offered=null;
      return {state:s.receipt.state,receipt:job.id};
    }
    if (matchesStaged(s,rev,job)) throw stagedError(s,rev);
    throw Error('The Mini could not confirm the drawing started. Check the sand before trying again.');
  }
  async function draw(snapshot,text,kind) {
    if (sending) throw Error('A drawing request is already in progress.');
    const mode = ['frame','whole-portrait'].includes(kind) ? kind : 'center';
    if (!previews.has(snapshot) || !kinds.includes(kind) || snapshot.mode!==mode)
      throw Error('Preview this drawing on the Mini before starting it.');
    if (kind==='book-pencil' && snapshot.center!=='book') throw Error('Draw the open book in the center before adding the pencil.');
    sending = true;
    try {
      const count = checkedCount(text,snapshot,kind);
      if (kind!=='photo' && kind!=='whole-portrait') {
        const routes=window.GuestCenterRoutes;
        const checked=kind==='frame' ? await routes.frame(snapshot.theta) : await routes.stock(kind);
        if (checked.text!==text) throw Error('The drawing file does not match the selected picture.');
      }
      const {s,rev} = await observe();
      if (rev!==snapshot.rev || s.receipt.id!==snapshot.receipt || s.receipt.state!==snapshot.receiptState ||
          s.state!=='idle' || s.theta!==snapshot.theta || s.rho!==snapshot.rho)
        throw Error('The sand changed after this preview. Preview again before drawing.');
      const id = runId(kind,rev,count);
      const job = {id,kind,rev,count,theta:s.theta,rho:s.rho};
      const headers = {'Content-Type':'application/octet-stream','X-Oasis-Run':id,'X-Guest-Rev':rev,'X-Oasis-Device':device};
      if (snapshot.receiptState==='complete') headers['X-Oasis-Previous']=snapshot.receipt;
      let uploaded;
      try { uploaded = await (await request('/thr',{method:'POST',headers,body:text})).json(); }
      catch {
        const current = await observe();
        if (matchesStaged(current.s,current.rev,job)) throw stagedError(current.s,current.rev);
        throw Error('The Mini could not confirm the upload. Check the table and preview again.');
      }
      if (uploaded?.points!==count || uploaded.skipped!==0) {
        throw Error('The Mini did not accept every point in the drawing.');
      }
      return await start(job,await observe());
    } finally { sending=false; }
  }
  async function resume() {
    if (sending || !offered) throw Error('Preview the prepared drawing before starting it.');
    const job=offered;
    sending=true;
    try { return await start(job,await observe()); }
    finally { sending=false; }
  }
  window.GuestCenterPlay = Object.freeze({recognized,finishedWholePortrait,prepared,canPrepareWhole,preview,draw,resume});
})();
