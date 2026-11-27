// Coordinates here are pixels in the converter's decoded photo, also used for face landmarks.
function guestFacePicker(main, choose, chooseGroup, chooseObject, chooseSeats, editingSeats) {
  const el = id => main.querySelector('#' + id);
  const frame = el('sourceFrame'), layer = el('faceBoxes'), help = el('faceHelp'), toggle = el('frameFace');
  const source = el('portraitSource'), arrange = el('arrangeSeats'), distant=el('toggleDistantFace');
  let photo = null, group = false, object = false, choices = [], framing = false, start = null, outline = null;
  let seats = [], draft = null;
  const same = (a,b) => a.x === b.x && a.y === b.y && a.w === b.w;

  function place(node, {x,y,w}) {
    const width = photo.sourceWidth, height = photo.sourceHeight;
    Object.assign(node.style, {
      left:(x-w/2)/width*100+'%', top:(y-w/2)/height*100+'%',
      width:w/width*100+'%', height:w/height*100+'%'
    });
  }
  function smallFaceButton(included,count) {
    distant.textContent=included ? 'Leave out the smaller face' : 'Include the smaller face';
    distant.disabled=included && count===1;
  }
  function mode(on) {
    framing = on;
    start = null;
    outline?.remove(); outline = null;
    frame.classList.toggle('framing', on);
    if(distant){
      const face=group && photo?.distantFace;
      distant.hidden=!face || !!draft || on;
      if(!distant.hidden) {
        const included=photo.includedFaces.some(b=>same(b,face));
        smallFaceButton(included,photo.includedFaces.length);
        distant.onclick=()=>layer.querySelectorAll('button')[photo.faceBoxes.findIndex(b=>same(b,face))]?.click();
      }
    }
    if (draft) {
      toggle.removeAttribute('aria-pressed');
      toggle.textContent = 'Restart seating order';
      toggle.disabled = draft.length === 0;
      help.textContent = draft.length
        ? 'Going clockwise, tap the person in seat ' + (draft.length + 1) + ' of ' + seats.length + '.'
        : 'Tap the person in seat 1, by the stem at the bottom of the preview. Then go clockwise.';
      return;
    }
    toggle.disabled = false;
    toggle.setAttribute('aria-pressed', String(on));
    toggle.textContent = on ? 'Cancel framing' : object ? 'Frame the subject' : 'Frame a face';
    help.textContent = object ? (on ? 'Drag a square around the part you want to draw.' :
      'Frame one subject closely to leave out the background.') :
      on ? 'Drag a square around the face, from forehead to chin.' :
      (group ? 'Tap a box to include or leave out that person. Frame anyone without a box.' :
       photo?.faceBoxes.length > 1 ? 'Tap a face to draw that person.' : '');
  }
  function setDraft(next) {
    const changed = Boolean(next) !== Boolean(draft);
    draft = next;
    if (changed) editingSeats?.(Boolean(next));
  }
  function seatButtons() {
    if (!arrange) return;
    arrange.hidden = seats.length < 2;
    arrange.textContent = draft ? 'Cancel seating order' : 'Set seating order';
    arrange.setAttribute('aria-pressed', String(Boolean(draft)));
    layer.querySelectorAll('button').forEach((button,i) => {
      const item = choices[i], seat = draft ? draft.indexOf(i) + 1 : seats.findIndex(b=>same(b,item)) + 1;
      button.hidden = Boolean(draft && !item.included);
      button.disabled = Boolean(draft && (seat || !item.included));
      if (draft) {
        button.setAttribute('aria-pressed', String(Boolean(seat)));
        button.setAttribute('aria-label', seat ? 'Face ' + (i+1) + ', seat ' + seat :
          'Assign face ' + (i+1) + ' to seat ' + (draft.length+1));
      } else if (group) {
        button.setAttribute('aria-pressed', String(item.included));
        button.setAttribute('aria-label', 'Include face ' + (i+1));
      }
      button.replaceChildren();
      if (seat) {
        const badge = document.createElement('span');
        badge.className = 'face-seat-number'; badge.textContent = String(seat);
        badge.setAttribute('aria-hidden','true'); button.append(badge);
        button.setAttribute('aria-description','Seat ' + seat);
      } else button.removeAttribute('aria-description');
    });
  }
  function changeOrder(next) {
    setDraft(next); mode(false); seatButtons();
  }
  if (arrange && chooseSeats) {
    arrange.onclick = () => {
      if (seats.length < 2) return;
      if (draft) { changeOrder(null); return; }
      source.open = true;
      changeOrder([]);
      layer.querySelector('button:enabled')?.focus({preventScroll:true});
    };
    source.addEventListener('toggle', () => { if (!source.open && draft) changeOrder(null); });
    source.addEventListener('keydown', event => {
      if (draft && event.key === 'Escape') {
        event.preventDefault(); changeOrder(null); arrange.focus();
      }
    });
    main.addEventListener('change', event => {
      if (draft && event.target.matches('input[name=zone]') && event.target.value !== 'center') changeOrder(null);
    });
    el('portraitForm').addEventListener('submit', () => {
      if (seats.length) { seats = []; changeOrder(null); }
    });
  }
  function point(event) {
    const rect = frame.getBoundingClientRect();
    return [Math.max(0,Math.min(1,(event.clientX-rect.left)/rect.width))*photo.sourceWidth,
            Math.max(0,Math.min(1,(event.clientY-rect.top)/rect.height))*photo.sourceHeight];
  }
  function box(end) {
    const [a,b] = start, [x,y] = end;
    const size = Math.min(Math.max(Math.abs(x-a),Math.abs(y-b)), photo.sourceWidth, photo.sourceHeight);
    return {x:Math.max(size/2,Math.min(photo.sourceWidth-size/2,(a+x)/2)),
            y:Math.max(size/2,Math.min(photo.sourceHeight-size/2,(b+y)/2)), w:size};
  }
  toggle.onclick = () => { if (draft) changeOrder([]); else mode(!framing); };
  frame.onpointerdown = event => {
    if (!framing || !event.isPrimary || event.button !== 0) return;
    event.preventDefault(); frame.setPointerCapture(event.pointerId);
    start = point(event);
    outline = document.createElement('span'); outline.className = 'frame';
    layer.append(outline); place(outline,box(start));
  };
  frame.onpointermove = event => { if (start && event.isPrimary) place(outline,box(point(event))); };
  frame.onpointerup = event => {
    if (!start || !event.isPrimary) return;
    const face = box(point(event));
    mode(false);
    if (face.w < 18) {
      mode(true); help.textContent = object ? 'Drag a larger square around the subject.' : 'Drag a larger square around the face.';
    } else if (object) {
      chooseObject(face);
    } else if (group) {
      // Reframing a poorly fitted box should draw that person once.
      const overlaps = b => Math.hypot(b.x-face.x,b.y-face.y) < .35*Math.min(b.w,face.w);
      const replaced = choices.filter(b=>b.included && overlaps(b));
      const corrected = choices.map(b => overlaps(b) ? {...b,included:false} : b);
      const withoutExact = corrected.filter(b=>!same(b,face));
      chooseGroup([...withoutExact,face], replaced.length === 1 ? {from:replaced[0],to:face} : undefined);
    } else choose(face);
  };
  frame.onpointercancel = () => mode(false);

  return function display(result, choice, isGroup, previousGroup, isObject = false) {
    photo = result; group = isGroup; object = isObject;
    setDraft(null);
    seats = chooseSeats && group && result?.groupStyle === 'seats' ? result.seatFaces.map(s=>s.sourceBox) : [];
    mode(false); layer.replaceChildren(); el('faceActions').hidden = !result;
    if (!result) { choices = []; seatButtons(); return; }
    const candidates = [...result.faceBoxes];
    if (group) candidates.push(...(previousGroup || []).filter(b=>!candidates.some(a=>same(a,b))));
    choices = candidates.map(b=>({...b,included:result.includedFaces.some(a=>same(a,b))}));
    candidates.forEach((b,i) => {
      const included=group ? result.includedFaces.some(a=>same(a,b)) : i === (choice ?? 0);
      const button = document.createElement('button');
      button.type = 'button';
      button.setAttribute('aria-label', (group ? 'Include face ' : 'Draw face ')+(i+1));
      button.setAttribute('aria-pressed', String(included));
      button.onclick = () => {
        if (photo !== result) return;
        if (draft) {
          if (!included || draft.includes(i)) return;
          const ordered = [...draft,i];
          if (ordered.length < seats.length) {
            changeOrder(ordered);
            layer.querySelector('button:enabled')?.focus({preventScroll:true});
          } else {
            const boxes = ordered.map(index => {
              const {x,y,w} = choices[index];
              return {x,y,w};
            });
            changeOrder(null);
            chooseSeats(boxes);
          }
          return;
        }
        if (!group) return choose(i);
        const selected=choices[i].included;
        if (selected && choices.filter(item=>item.included).length === 1) {
          help.textContent = 'Frame another face before removing this one.';
          return;
        }
        // A second tap can arrive before the first portrait finishes rendering.
        // Apply it to the guest's latest selection on this photo.
        choices=choices.map((item,j)=>j===i ? {...item,included:!selected} : item);
        button.setAttribute('aria-pressed',String(!selected));
        if(distant && result.distantFace){
          const small=choices.find(item=>same(item,result.distantFace));
          smallFaceButton(small.included,choices.filter(item=>item.included).length);
        }
        chooseGroup(choices);
      };
      place(button,b); layer.append(button);
    });
    seatButtons();
    if (!group && choice && typeof choice === 'object') {
      const selected = document.createElement('span'); selected.className = 'frame';
      place(selected,choice); layer.append(selected);
    }
  };
}
