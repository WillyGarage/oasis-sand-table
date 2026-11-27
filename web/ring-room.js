// The private gallery has no room endpoint. The shared server adds its own same-origin marker.
class RingRoom {
  constructor(layout, main) {
    this.url = document.querySelector('meta[name=oasis-room]').content + '/' + layout;
    this.attached = document.querySelector('meta[name=oasis-table-layout]')?.content === layout;
    this.table = main.querySelector('#tablePlayback');
    this.table.hidden = !this.attached;
    this.controls = main.querySelector('.controls');
    this.notice = main.querySelector('#roomNotice');
    this.message = main.querySelector('#roomStatus');
    this.reload = main.querySelector('#roomReload');
    this.revision = null;
    this.changed = false;
    this.writing = false;
    this.readNumber = 0;
    this.events = new AbortController();
  }

  status(text = '', reload = false) {
    this.notice.hidden = !text;
    this.message.textContent = text;
    this.reload.hidden = !reload;
  }

  conflict(latest = null, retryable = true) {
    this.changed = true;
    this.latest = latest;
    this.rejectedPlace = retryable ? null : this.guestPlace?.();
    this.showConflict();
  }

  showConflict() {
    const place = this.guestPlace?.();
    const independent = place !== this.rejectedPlace && this.untouched(this.latest, place);
    this.status(independent ? 'Another guest changed their place. You can still keep this drawing.' :
      'Another phone changed the garden. Load it to preview your edit again.', !independent);
  }

  async snapshot(response) {
    if (!response.ok) throw Error();
    const data = await response.json();
    const marks = response.headers.get('X-Oasis-Place-Revisions');
    if (/^\d+,\d+,\d+$/.test(marks)) data.placeRevisions = marks.split(',').map(Number);
    return data;
  }

  untouched(latest, place) {
    const touched = latest?.placeRevisions?.[place];
    return Number.isInteger(place) && Number.isSafeInteger(touched) && touched <= this.revision &&
      latest.revision > this.revision && latest.state && !latest.state.starting;
  }

  async read(force) {
    if (this.writing || this.events.signal.aborted) return;
    const request = ++this.readNumber;
    const initial = this.revision === null;
    const headers = !initial && !force ? {'If-None-Match':'"' + this.revision + '"'} : {};
    try {
      const response = await fetch(this.url, {headers, cache:'no-store', signal:this.events.signal});
      if (this.readNumber !== request || this.events.signal.aborted) return;
      if (response.status === 304) { this.status(); return; }
      const data = await this.snapshot(response);
      if (this.readNumber !== request || this.events.signal.aborted) return;
      if (!initial && !force && this.pending()) { this.conflict(data); return; }
      const untouchedPlaces = data.placeRevisions?.map((_,i) => this.untouched(data,i));
      this.apply(data.state, initial, force && !initial && this.pending(), untouchedPlaces);
      this.revision = data.revision;
      this.changed = false;
      this.latest = null;
      this.controls.inert = false;
      this.status();
    } catch {
      if (this.readNumber === request && !this.events.signal.aborted) {
        this.status('Could not load the shared garden.', true);
      }
    }
  }

  async readPlayback() {
    if (!this.attached || !this.onPlayback || this.events.signal.aborted || document.hidden) return;
    const request=++this.playbackRead;
    let data=null;
    try {
      const url=new URL('../playback',new URL(this.url,document.baseURI));
      const response=await fetch(url,{cache:'no-store',signal:this.events.signal});
      if (response.ok) data=await response.json();
    } catch { /* Wait for a fresh status before proposing an automatic drawing. */ }
    if (request!==this.playbackRead || this.events.signal.aborted) return;
    const name={center:'center',middle:'guest ring',outer:'border',setup:'starting layout'};
    const zone=name[data?.drawing?.zone] || 'drawing';
    const queued=data?.queued > 0 ? ' · ' + data.queued + ' queued' : '';
    const states={
      idle: data?.ready ? 'Table ready' : 'Waiting for the table',
      queued:'Next on the table · '+zone,
      drawing:'Drawing the '+zone+(data?.parts>1 ? ' · part '+data.part+' of '+data.parts : ''),
      hold:'On display · '+Math.max(0, Math.ceil(data?.holdSeconds || 0))+' seconds left',
      paused:'Table paused', blocked:'Table needs attention'
    };
    const message=data && Object.hasOwn(states,data.state) ? states[data.state]+queued : 'Table status unavailable';
    const detail=['paused','blocked'].includes(data?.state) && data.reason ? ' · '+data.reason : '';
    this.table.querySelector('#tableStatus').textContent=message+detail;
    const last=data?.lastCompleted;
    if (data) this.table.querySelector('#tableFinished').textContent=last ?
      'Last finished on the table · '+(name[last.zone] || 'drawing')+' (change '+last.revision+')' :
      'No completed change recorded yet.';
    this.onPlayback(data);
  }

  watch(apply, pending, onPlayback, guestPlace) {
    this.apply = apply;
    this.pending = pending;
    this.onPlayback = onPlayback;
    this.guestPlace = guestPlace;
    this.playbackRead = 0;
    this.controls.inert = true;
    this.status('Opening the shared garden…');
    this.reload.onclick = () => this.read(true);
    const poll = async () => {
      if (!document.hidden && !this.changed) await this.read(false);
      if (this.attached) await this.readPlayback();
      if (!this.events.signal.aborted) this.timer = setTimeout(poll, 2000);
    };
    poll();
  }

  async save(state, motion, automatic=false, merge=null) {
    if (this.changed && !merge) { this.conflict(this.latest); return false; }
    if (this.writing || this.revision === null || this.events.signal.aborted) return false;
    this.writing = this.controls.inert = true;
    this.readNumber++;
    this.status('Saving to the shared garden…');
    try {
      let latest = this.latest, revision = this.revision, candidate = state;
      // Always save against one revision. Only a definite conflict can retry a write.
      for (let attempt=0; attempt<4; attempt++) {
        if (latest) {
          candidate = this.untouched(latest,motion?.place) && merge?.(latest.state);
          if (!candidate) { this.conflict(latest,false); return false; }
          revision = latest.revision;
        }
        const response = await fetch(this.url, {
          method:'PUT', headers:{'Content-Type':'application/json'},
          body:JSON.stringify({revision, state:candidate, motion, automatic:automatic || undefined}), signal:this.events.signal
        });
        if (response.status!==409) {
          if (!response.ok) throw Error();
          this.revision = (await response.json()).revision;
          this.changed = false; this.latest = null;
          this.status();
          return !this.events.signal.aborted && {state:candidate};
        }
        if (!merge) { if (!automatic) this.conflict(); return false; }
        latest = await this.snapshot(await fetch(this.url,{cache:'no-store',signal:this.events.signal}));
      }
      this.conflict(latest); return false;
    } catch {
      if (!this.events.signal.aborted) this.status('Could not confirm the save. Your preview is still here.');
      return false;
    } finally { this.writing = this.controls.inert = false; }
  }

  async files(zone) {
    const response = await fetch(this.url + '/drawings/' + zone, {cache:'no-store', signal:this.events.signal});
    if (!response.ok) throw Error('Could not load the drawing files.');
    return (await response.json()).files;
  }

  close() {
    this.events.abort();
    clearTimeout(this.timer);
  }
}
