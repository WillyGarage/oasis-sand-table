// Match numbered faces in one local photo to the guests around the middle ring.
function guestPhotoAssignments(main, edit) {
  const field = main.querySelector('#groupGuestAssignments');
  const rows = new Map();
  let faces = [];

  function updateChoices(row) {
    const previous = row.select.value;
    row.select.replaceChildren(new Option('Keep this place as it is', ''),
      ...faces.map((_, i) => new Option('Face ' + (i + 1), String(i))));
    row.select.value = previous && faces[Number(previous)] ? previous : '';
    row.select.disabled = !faces.length;
    row.name.hidden = row.nameLabel.hidden = !row.select.value;
  }
  function setGuests(guests, places) {
    for (const [slot, guest] of guests.entries()) {
      if (!places[slot]) continue;
      if (rows.get(slot)?.guest === guest.name) continue;
      const previous = rows.get(slot);
      const container = document.createElement('div');
      const label = document.createElement('label'), select = document.createElement('select');
      label.htmlFor = select.id = 'guestFace' + slot;
      label.textContent = guest.name + '’s place';
      const nameLabel = document.createElement('label'), name = document.createElement('input');
      nameLabel.htmlFor = name.id = 'guestFaceName' + slot;
      nameLabel.textContent = 'Person in the portrait (optional)';
      name.maxLength = 160; name.autocomplete = 'off';
      container.append(label, select, nameLabel, name);
      if (previous) previous.container.replaceWith(container);
      else field.append(container);
      const row = {container, select, name, nameLabel, guest:guest.name};
      rows.set(slot, row);
      updateChoices(row);
      select.onchange = () => {
        name.hidden = nameLabel.hidden = !select.value;
        name.value = '';
        edit();
      };
      name.oninput = edit;
    }
  }
  function reset() {
    faces = [];
    for (const row of rows.values()) { row.name.value = ''; updateChoices(row); }
  }
  function detected(boxes) {
    faces = boxes.map((box, index) => ({box, choice:index}));
    rows.forEach(updateChoices);
  }
  function frame(box) {
    // A second frame centered on the same person corrects their box in place.
    // Both the number on the photo and an existing seat assignment survive.
    let nearest = -1, distance = Infinity;
    faces.forEach(({box:other}, i) => {
      const d = Math.hypot(other.x-box.x, other.y-box.y);
      if (d < .35*Math.min(box.w, other.w) && d < distance) { nearest = i; distance = d; }
    });
    const item = {box, choice:box};
    if (nearest < 0) faces.push(item); else faces[nearest] = item;
    rows.forEach(updateChoices);
  }
  function markSource(display, scan) {
    display({...scan, faceBoxes:faces.map(item => item.box), includedFaces:[]}, -1, false);
    main.querySelectorAll('#faceBoxes button').forEach((button, i) => {
      const outline = document.createElement('span'), number = document.createElement('span');
      outline.className = 'numbered-face'; outline.style.cssText = button.style.cssText;
      number.className = 'face-seat-number'; number.textContent = i + 1;
      outline.append(number); button.replaceWith(outline);
    });
    main.querySelector('#faceHelp').textContent = 'Choose these face numbers beside the guest places. Frame a face to add it or correct its box.';
  }
  function selected() {
    const assignments = [];
    for (const [slot, {select, name}] of rows) {
      if (select.value === '') continue;
      const index = Number(select.value), person = name.value.trim().replace(/\s+/gu, ' ').normalize('NFC');
      assignments.push({slot, index, face:faces[index].choice, person});
    }
    return assignments;
  }
  function check() {
    const assignments = selected();
    if (new Set(assignments.map(a => a.index)).size !== assignments.length) return 'Choose a different face for each guest place.';
    return assignments.length < 2 ? 'Choose faces for at least two guest places.' : '';
  }
  return {setGuests, reset, detected, frame, markSource, selected, check};
}
