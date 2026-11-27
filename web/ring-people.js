// The book remembers everyone who has had a drawing. Three people fit in the ring at once.
class RingGuestBook {
  constructor(defaults) {
    this.restore(null, defaults);
  }

  startingPeople(drawings) {
    return ['Thomas','Alex','Lek'].map((name, i) => ({
      name, interest:['Bacteriophages',GuestArt.alexInterest,'Thailand'][i], subject:drawings[i]
    }));
  }

  restore(saved, drawings, available = () => true) {
    this.people = this.startingPeople(drawings);
    this.active = this.people.slice();
    this.personalized = false;
    if (!saved || !Array.isArray(saved.people) || !Array.isArray(saved.active) || saved.active.length !== 3) return;
    const index = new Map();
    for (const person of saved.people) {
      if (!person || typeof person.name !== 'string' || typeof person.interest !== 'string' ||
          typeof person.subject !== 'string' || !available(person.subject)) return;
      const key = GuestArt.normalize(person.name);
      if (!key || index.has(key)) return;
      index.set(key, person);
    }
    const active = saved.active.map(key => index.get(key));
    if (new Set(active).size !== 3 || active.some((p,i) => !p || p.subject !== drawings[i])) return;
    this.people = [...index.values()];
    this.active = active;
    this.personalized = true;
  }

  resetDrawing(drawings) {
    const people = this.startingPeople(drawings).map(person => this.find(person.name) || person);
    this.active = people;
    this.keep(null, drawings);
  }

  saved() {
    if (!this.personalized) return undefined;
    return {people:this.people, active:this.active.map(p => GuestArt.normalize(p.name))};
  }

  copy() {
    // keep() replaces guest records, so a proposed book can share its existing records.
    const other = new RingGuestBook(this.active.map(person => person.subject));
    other.people = this.people.slice();
    other.active = this.active.slice();
    other.personalized = this.personalized;
    return other;
  }

  find(name) {
    const key = GuestArt.normalize(name);
    return this.people.find(p => GuestArt.normalize(p.name) === key);
  }

  preview(person, slot) {
    const active = this.active.slice();
    const oldSlot = active.indexOf(this.find(person.name));
    if (oldSlot >= 0 && oldSlot !== slot) active[oldSlot] = active[slot];
    active[slot] = person;
    return active;
  }

  keep(active, drawings) {
    // Make a new book only after the guest keeps the preview. Displaced people retain their last drawing.
    if (active) this.personalized = true;
    this.active = (active || this.active).map((p, i) => {
      const old = this.find(p.name), next = {...p, subject:drawings[i]};
      if (old) this.people[this.people.indexOf(old)] = next;
      else this.people.push(next);
      return next;
    });
  }
}

function bindRingPeople(main, book, manifest, {labels, openSubject, ideasFor, edit, preview, readSketch, resetSketch, report}) {
  const $ = id => main.querySelector('#' + id);
  const box = $('peopleBox'), pick = $('personPick'), place = $('personPlace'), drawing = $('personDrawing');
  const name = $('personName'), interest = $('personInterest');
  let choices = new Map();

  function updateSketch() {
    const sketch = $('sketch');
    if (box.open && drawing.value === 'sketch') {
      $('personSketch').append(sketch);
      sketch.open = true;
    } else {
      $('suggestionActions').before(sketch);
    }
  }
  function renderChoices() {
    const person = book.find(pick.value);
    const remembered = person && GuestArt.guestInterest(person) === interest.value.trim() ? person.subject : '';
    const ideas = ideasFor(interest.value);
    choices = new Map();
    drawing.replaceChildren();
    function group(title, items) {
      const options = document.createElement('optgroup');
      options.label = title;
      for (const art of items) {
        if (choices.has(art.id)) continue;
        choices.set(art.id, art);
        options.append(new Option(art.label, art.id));
      }
      if (options.childElementCount) drawing.append(options);
    }
    if (remembered) group('Last drawing', [{id:remembered, label:labels[remembered]}]);
    group('From their interests', ideas);
    if (!ideas.length && !remembered) drawing.add(new Option('Choose a drawing', ''), 0);
    group('Other drawings', Object.entries(manifest.subjects).map(([id, item]) => ({id, label:item.label})));
    if (openSubject) group('Guest place', [{id:openSubject,label:labels[openSubject]}]);
    drawing.add(new Option('Sketch a drawing…', 'sketch'));
    drawing.value = remembered || ideas[0]?.id || '';
    updateSketch();
  }
  function refresh(preserveInput = false) {
    const draft = preserveInput && box.open &&
      {guest:pick.value, name:name.value, interest:interest.value, slot:place.value, subject:drawing.value};
    pick.replaceChildren(new Option('Someone new', ''));
    for (const person of book.people) pick.add(new Option(person.name, GuestArt.normalize(person.name)));
    const positions = ['Lower left', 'Lower right', 'Top'];
    place.replaceChildren(...book.active.map((p, i) => new Option(positions[i] + ' · ' + p.name, String(i))));
    pick.value = draft?.guest || '';
    name.value = draft?.name || ''; name.readOnly = !!pick.value; interest.value = draft?.interest || '';
    if (draft) place.value = draft.slot;
    renderChoices();
    if (draft && (choices.has(draft.subject) || draft.subject === 'sketch')) {
      drawing.value = draft.subject; updateSketch();
    }
    const target = $('target');
    target.replaceChildren(new Option('Guest named in the suggestion', ''),
      ...book.active.map((p, i) => new Option(p.name, String(i))));
    const alex = book.active.find(person=>GuestArt.normalize(person.name)==='alex');
    $('idea').placeholder = alex ? 'A guitar for '+alex.name : 'A violin for '+book.active[0].name;
  }
  pick.onchange = () => {
    const person = book.find(pick.value);
    name.value = person?.name || ''; name.readOnly = !!person;
    interest.value = person ? GuestArt.guestInterest(person) : '';
    const slot = book.active.indexOf(person);
    if (slot >= 0) place.value = String(slot);
    resetSketch(); renderChoices(); edit();
  };
  interest.oninput = () => { renderChoices(); edit(); };
  name.oninput = place.onchange = edit;
  drawing.onchange = () => { updateSketch(); edit(); };
  $('personForm').onsubmit = event => {
    event.preventDefault();
    try {
      const personName = name.value.trim(), topic = interest.value.trim();
      if (!GuestArt.normalize(personName) || !topic) throw Error('Enter a name and an interest.');
      const known = book.find(personName);
      if (known && known !== book.find(pick.value)) throw Error('Choose ' + known.name + ' from the guest book to update their drawing.');
      const art = drawing.value === 'sketch' ? readSketch(topic,Number(place.value)) : choices.get(drawing.value);
      if (!art) throw Error('Choose a drawing or sketch what you have in mind.');
      const active = book.preview({name:personName, interest:topic, subject:art.id}, Number(place.value));
      preview(active, art);
    } catch (e) { report(e); }
  };
  refresh();
  function previewTelescope() {
    const known = book.find('Bill');
    if (known) {
      pick.value = GuestArt.normalize(known.name);
      pick.onchange();
    } else {
      name.value = 'Bill'; interest.value = 'Stargazing';
      renderChoices();
    }
    drawing.value = 'telescope';
    $('personForm').requestSubmit();
  }
  return {refresh, updateSketch, previewTelescope};
}
