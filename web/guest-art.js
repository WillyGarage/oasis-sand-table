// Convert a guest's idea or sketch into a continuous drawing, entirely on their phone.
window.GuestArt = (() => {
  const tau = 2 * Math.PI;
  const shortTurn = a => Math.atan2(Math.sin(a), Math.cos(a));
  const clamp = (x, lo, hi) => Math.max(lo, Math.min(hi, x));
  const dist = (a, b) => Math.hypot(a[0]-b[0], a[1]-b[1]);
  const normalize = text => String(text).toLowerCase().replace(/['’]s\b/g, '').replace(/[^\p{L}\p{N}]+/gu, ' ').trim();
  const alexInterest = 'Teaching and playing guitar';
  function guestInterest(person) {
    // Older guest books stored the original starter wording alongside the drawings.
    return normalize(person.name)==='alex' && person.interest==='Teaching' ? alexInterest : person.interest;
  }
  const objectAliases = {
    rolling_pin:["wooden rolling pin","baker’s rolling pin","baker's rolling pin"],
    paint_roller:[],
    binoculars:["pair of binoculars"],
    traffic_cone:["road cone"],
    pineapple_with_ring:['pineapple with a cut ring','pineapple with a slice','pineapple with a ring','pineapple with a pineapple ring','pineapple beside a cut ring'],
    oven_mitt:['oven mitt','quilted oven mitt','oven glove','quilted oven glove','kitchen oven mitt','baking mitt'],
    harvest_basket:['harvest basket','harvest apple basket','apple basket','basket of apples','orchard apple basket','woven basket of apples'],
    crescent_roll:['crescent roll','crescent dinner roll','buttery crescent roll','croissant','butter croissant'],
    harvest_wheat:['harvest wheat','golden wheat','ripe wheat','wheat','autumn wheat','thanksgiving wheat',
      'stalk of wheat','wheat stalk','ear of wheat','head of wheat','single stalk of wheat'],
    harvest_pear:['pear','ripe pear','bartlett pear','autumn pear','fall pear','thanksgiving pear',
      'cut pear','halved pear','half a pear','half of a pear','pear half','pear cut in half','pear sliced in half',
      'halved bartlett pear','halved harvest pear','bartlett pear cut in half','pear with two seeds'],
    desk_lamp:['desk lamp','adjustable desk lamp','articulated desk lamp','swing arm desk lamp',
      'desk lamp with two hinged arms and a tilted shade','adjustable desk lamp with two hinged arms and a tilted shade'],
    acorn:['single acorn','oak nut'],
    acorn_oak:['oak leaf and acorn','acorn and oak leaf','acorn with an oak leaf',
      'acorn and an oak leaf','oak leaf with an acorn','oak leaf and an acorn'],
    pumpkin_pie:['slice of pumpkin pie','piece of pumpkin pie','wedge of pumpkin pie','pumpkin pie slice'],
    lattice_pie:['whole lattice pie','lattice apple pie','whole lattice apple pie','whole apple pie with a lattice crust',
      'whole pie with a lattice crust','lattice top pie','lattice topped pie','lattice crust pie'],
    roast_turkey:['roasted turkey','whole roast turkey','whole roasted turkey','oven roasted turkey',
      ...['turkey','thanksgiving turkey','roast turkey','roasted turkey','whole turkey','whole roast turkey','whole roasted turkey'].flatMap(bird=>
        ['on a platter','on a serving platter','on a plate','on an oval platter'].map(place=>bird+' '+place))],
    caramel_apple:['candy apple','candied apple','toffee apple','taffy apple','caramel dipped apple',
      'apple dipped in caramel','apple coated in caramel', ...['caramel apple','candy apple','candied apple','toffee apple','taffy apple'].flatMap(apple=>
        ['on a stick','on a wooden stick'].map(stick=>apple+' '+stick))],
    dinner_candle:['dinner candle','lit dinner candle','thanksgiving table candle','lit thanksgiving candle',
      'lit candle in a chamberstick', ...['candle','lit candle','dinner candle','lit dinner candle'].flatMap(candle=>
        ['in a holder','in a handled holder','in a candleholder','in a holder with a handle'].map(holder=>candle+' '+holder))],
    mayflower_ship:['mayflower sailing ship','pilgrim ship','pilgrims ship'],
    pilgrim_hat:['buckled pilgrim hat','pilgrim hat with a buckle','pilgrim hat with a buckled band',
      'thanksgiving pilgrim hat','thanksgiving pilgrim hat with a buckle','pilgrim hat with a buckle on the band'],
    lotus_blossom:['lotus flower','lotus blossom on a leaf','lotus flower on a leaf',
      ...['lotus','lotus flower','lotus blossom'].flatMap(flower=>
        ['on a lily pad','floating on a lily pad','on a round leaf','above a round leaf'].map(place=>flower+' '+place))],
    electric_guitar:['solid body electric guitar','solid body guitar','electric six string'],
    two_books:['two stacked books','pair of books','stack of two books',
      'two hardcovers','2 books','2 stacked books','stack of 2 books'],
    birdhouse:['bird house','nesting box','nest box'], anvil:['blacksmith’s anvil'],
    rocking_chair:['rocker chair'], washing_machine:['front loading washer','front load washer'],
    cooking_pot:['stockpot','stock pot','stew pot'],
    coffee_grinder:['hand-cranked coffee grinder','hand crank coffee grinder','manual coffee grinder','hand coffee mill','hand-cranked coffee mill'],
    cornucopia:['horn of plenty','harvest cornucopia'], maple_leaf:['autumn maple leaf','fall maple leaf'],
    wishbone:['wish bone','turkey wishbone','turkey wish bone'], gravy_boat:['sauce boat'],
    turkey_leg:['turkey drumstick','roast turkey leg','roasted turkey leg','roast turkey drumstick',
      'roasted turkey drumstick','thanksgiving turkey leg']
  };
  const objectNames = new Map(Object.entries(objectAliases).flatMap(([id,names])=>
    [id,...names].map(name=>[normalize(name),id])));
  // The existing full stack contains three volumes, even in a small guest place.
  for (const count of ['three', '3']) {
    for (const name of [count+' books',count+' stacked books','stack of '+count+' books'])
      objectNames.set(name,'books');
  }
  const aliases = {
    ...objectAliases,
    phage: ['bacteriophage','bacteriophages','phages','microbiologist'],
    phage_faceted: ['faceted phage'],
    books: ['stack of books','book','classroom','teacher','teaches','teaching'],
    temple: ['thai rooftop','temple roof','thai temple','rooftop','thailand','thai'],
    pumpkin: ['leafy pumpkin'], pumpkin_ribbed: ['ribbed pumpkin','field pumpkin','five-lobe pumpkin'],
    guitar: ['acoustic guitar','guitarist'], hotpot:['hot pot'], hunt:['family name'],
    rocket:['spacecraft'], trex:['t rex','tyrannosaurus'], raptor:['velociraptor'],
    paper_crane:['origami crane','origami bird','paper bird','folded crane','original folded paper bird','original paper crane'],
    origami_crane:['spread wing paper crane','paper crane with folded wings'],
    chef_hat:['baker’s hat','chef’s toque','toque'],
    caravan:['travel trailer','camper trailer','camping caravan'],
    indian_corn:['corn on the cob','sweet corn','ear of sweet corn','corn cob','harvest corn','corn']
  };
  function includesPhrase(sentence, phrase) {
    if (!phrase) return false;
    const input = ' '+normalize(sentence)+' ';
    return [phrase, phrase+'s', phrase+'es'].some(word => input.includes(' '+word+' '));
  }
  function splitRequest(s, roster){
    const swap=s.match(/(?:\breplace|\bswap|\bswitch|\bchange)\s+(.+?)\s+(?:with|for|to|into)\s+(.+)/i);
    const instead=s.match(/(.+?)\s+(?:instead of|in place of|replacing)\s+(.+)/i);
    const req={from:'',to:s};
    if(swap){req.from=swap[1];req.to=swap[2];}
    else if(instead){req.from=instead[2];req.to=instead[1];}
    const addressed=req.to.match(/^(?:(.+)\s+)?for\s+(.+)$/i);
    if(addressed){
      req.recipient=addressed[2].trim();
      const key=name=>name.normalize('NFC').toLowerCase().replace(/[^\p{L}\p{M}\p{N}]+/gu,' ').trim();
      req.guest=roster.find(p=>key(p.name)===key(req.recipient));
      if(req.guest){
        const subject=(addressed[1] || '').trim();
        const generic=/^(?:(?:draw|make)\s+)?(?:something|(?:a\s+)?(?:drawing|picture))$/i;
        req.to=generic.test(subject)?req.guest.name:subject;
      }
    }
    return req;
  }
  const pairRelations = [
    ['lean', /\b(?:leaning (?:against|on)|propped (?:against|on))\b/i],
    ['beside', /\b(?:next to|alongside|beside|to the left of)\b/i],
    ['right', /\bto the right of\b/i],
    ['above', /\b(?:on top of|over|above)\b/i],
    ['below', /\b(?:under|beneath|below)\b/i],
    ['behind', /\bbehind\b/i],
    ['beside', /\b(?:with|and)\b/i]
  ];
  const ringRelations = [['lean', /\b(?:lean(?:ing|ed)?|rest(?:ing|ed)?|propp(?:ed|ing))(?:\s+up)?\s+(?:against|on)\b/i],
    ...pairRelations, ['front', /\bin front of\b/i],
    ['above', /\b(?:atop|on)\b/i], ['beside', /[,;&]/]];
  function parsePair(text, strict = false) {
    for (const [relation, pattern] of strict ? ringRelations : pairRelations) {
      const m = pattern.exec(text);
      if (!m) continue;
      const left = text.slice(0,m.index).trim(), right = text.slice(m.index+m[0].length).trim();
      // “A brass cooking pot engraved with initials” needs its own picture.
      // “A cooking pot beside a birdhouse” has two complete catalog operands.
      if (hasObjectDetails(left) || hasObjectDetails(right)) return null;
      if ((left && right) || strict) return {left,right,relation};
    }
    return null;
  }
  function preferredSubject(id, manifest) {
    if (manifest.preferredSubjects?.[id]) return manifest.preferredSubjects[id];
    if (id==='paper_crane' && Object.hasOwn(manifest.subjects,'origami_crane')) return 'origami_crane';
    return id === 'dna' && Object.hasOwn(manifest.subjects, 'dna_open') ? 'dna_open' : id;
  }
  function subjectWords(text) {
    const words=normalize(text).replace(/^(?:(?:please )?(?:draw|make|add|sketch) )?(?:(?:an?|the|my) )?/,'');
    // The bare flower name and the longer request “person in lotus position”
    // describe different subjects. Preserve the latter for the guest drawing lookup.
    if (words==='lotus') return 'lotus blossom';
    // A bare Mayflower names the ship at dinner. Leave explicit flower requests intact.
    return words==='mayflower' ? 'mayflower ship' : words;
  }
  function subjectMatch(text, words) {
    // A compound such as “knitting machine” names the device. Matching only
    // its activity would substitute a ball of yarn and discard the machine.
    if (/\b[\p{L}\p{N}]+ machines?\b/u.test(words))
      return term => /\bmachines?\b/.test(term) && includesPhrase(text,term);
    return term => includesPhrase(text,term);
  }
  function whippedPumpkinSlice(words) {
    return /^(?:(?:slice|wedge|piece) of )?pumpkin pie(?: slice)? (?:with|topped with) (?:a (?:dollop|swirl) of )?(?:whipped cream|whip cream)(?: on top)?$/.test(words);
  }
  function describedObject(text) {
    const words = ' '+subjectWords(text)+' ';
    // Keep a requested flag or passenger with its ship when the stock ship lacks it.
    if (/\bmayflower\b/.test(words) && !/\b(?:flowers?|blossoms?|blooms?|plants?)\b/.test(words)) return true;
    // A request such as "two closed books" asks for a different drawing
    // from the stack with its upper volume open.
    if (/\b(?:2|two) (?:[\p{L}]+ ){1,3}books\b/u.test(words)) return true;
    for (const name of objectNames.keys()) {
      if (words.includes(' '+name+' ') || words.includes(' '+name+'s ') || words.includes(' '+name+'es ')) return true;
    }
    return false;
  }
  function hasObjectDetails(text) {
    const words = subjectWords(text);
    return !objectNames.has(words) && !whippedPumpkinSlice(words) && describedObject(text);
  }
  function wholeSubject(text, id, manifest) {
    const subject = manifest.subjects[id];
    if (!subject) return false;
    const words = subjectWords(text);
    if (id==='pumpkin_pie' && whippedPumpkinSlice(words)) return true;
    return [id,subject.label || subject,...(aliases[id] || [])].some(term=>normalize(term)===words);
  }
  function thanksgivingIdeas(manifest) {
    const acorn = Object.hasOwn(manifest.subjects,'acorn') ? 'acorn' : 'acorn_oak';
    return ['turkey','pumpkin_pie','pumpkin','indian_corn',acorn,'cornucopia','maple_leaf','wishbone','gravy_boat','turkey_leg','lattice_pie','pilgrim_hat','roast_turkey','dinner_candle','caramel_apple','mayflower_ship','desk_lamp','harvest_pear','harvest_wheat','crescent_roll','harvest_basket','oven_mitt','pineapple_with_ring',...(manifest.thanksgivingExtras || [])]
      .map(id=>preferredSubject(id,manifest))
      .filter(id=>Object.hasOwn(manifest.subjects,id))
      .map(id=>({id,label:manifest.subjects[id].label || manifest.subjects[id]}));
  }
  function thanksgivingPicker(details, manifest, outline, preview, displayId) {
    const choices = details.querySelector('div');
    for (const art of thanksgivingIdeas(manifest)) {
      const points = outline(art.id);
      if (!points?.length) continue;
      const canvas = document.createElement('canvas');
      canvas.width = canvas.height = 132;
      canvas.setAttribute('aria-hidden','true');
      const ink = canvas.getContext('2d');
      ink.setTransform(63,0,0,-63,66,66);
      ink.strokeStyle = '#684c37';
      ink.lineWidth = .045;
      ink.lineJoin = ink.lineCap = 'round';
      ink.beginPath();
      ink.moveTo(...points[0]);
      for (let i=1; i<points.length; i++) ink.lineTo(...points[i]);
      ink.stroke();

      const button = document.createElement('button');
      button.type = 'button';
      button.setAttribute('aria-label','Preview '+art.label);
      button.setAttribute('aria-controls',displayId);
      button.append(canvas,art.label);
      button.onclick = () => preview(art);
      choices.append(button);
    }
    details.hidden = !choices.childElementCount;
  }
  function catalogIdea(text, manifest, preferStyle=true) {
    const words = subjectWords(text);
    if (manifest.subjects.pumpkin_pie && whippedPumpkinSlice(words)) return 'pumpkin_pie';
    const object = objectNames.get(words);
    if (object && manifest.subjects[object]) return object;
    if (object==='acorn' && manifest.subjects.acorn_oak) return 'acorn_oak';
    // A specified extra feature needs its own picture. A pair is resolved
    // by its two operands by the guest planner.
    if (describedObject(text)) return '';
    const matches = subjectMatch(text,words);
    let best = '', bestLength = 0;
    for (const [id, data] of Object.entries(manifest.subjects)) {
      for (const alias of [id,data.label,...(aliases[id]||[])]) {
        const term = normalize(alias);
        if (term.length>bestLength && matches(term)) { best=id; bestLength=term.length; }
      }
    }
    // Requests for a particular original shape take priority over the automatic
    // choice for a small place.
    if ((best==='phage' && /\boriginal (?:bacterio)?phages?\b/.test(normalize(text))) ||
        (best==='books' && includesPhrase(text,'stack of books')) ||
        (best==='pumpkin' && includesPhrase(text,'leafy pumpkin')) ||
        (best==='paper_crane' && /\boriginal (?:folded paper bird|paper crane)\b/.test(words))) return best;
    return preferStyle ? preferredSubject(best, manifest) : best;
  }

  // The Unicode names are indexed at build time. Glyphs come from the device's emoji font.
  const glyphNames = {"watch":"⌚","hourglass":"⌛","black sun with rays":"☀","cloud":"☁","umbrella":"☂","snowman":"☃","comet":"☄","black star":"★","white star":"☆","lightning":"☇","thunderstorm":"☈","sun":"☉","ascending node":"☊","descending node":"☋","conjunction":"☌","opposition":"☍","black telephone":"☎","white telephone":"☏","ballot box":"☐","ballot box with check":"☑","ballot box with x":"☒","saltire":"☓","umbrella with rain drops":"☔","hot beverage":"☕","white shogi piece":"☖","black shogi piece":"☗","shamrock":"☘","reversed rotated floral heart bullet":"☙","black left pointing index":"☚","black right pointing index":"☛","white left pointing index":"☜","white up pointing index":"☝","white right pointing index":"☞","white down pointing index":"☟","skull and crossbones":"☠","caution sign":"☡","radioactive sign":"☢","biohazard sign":"☣","caduceus":"☤","ankh":"☥","orthodox cross":"☦","chi rho":"☧","cross of lorraine":"☨","cross of jerusalem":"☩","star and crescent":"☪","farsi symbol":"☫","adi shakti":"☬","hammer and sickle":"☭","peace symbol":"☮","yin yang":"☯","trigram for heaven":"☰","trigram for lake":"☱","trigram for fire":"☲","trigram for thunder":"☳","trigram for wind":"☴","trigram for water":"☵","trigram for mountain":"☶","trigram for earth":"☷","wheel of dharma":"☸","white frowning face":"☹","white smiling face":"☺","black smiling face":"☻","white sun with rays":"☼","first quarter moon":"☽","last quarter moon":"☾","mercury":"☿","female sign":"♀","earth":"♁","male sign":"♂","jupiter":"♃","saturn":"♄","uranus":"♅","neptune":"♆","pluto":"♇","aries":"♈","taurus":"♉","gemini":"♊","cancer":"♋","leo":"♌","virgo":"♍","libra":"♎","scorpius":"♏","sagittarius":"♐","capricorn":"♑","aquarius":"♒","pisces":"♓","white chess king":"♔","white chess queen":"♕","white chess rook":"♖","white chess bishop":"♗","white chess knight":"♘","white chess pawn":"♙","black chess king":"♚","black chess queen":"♛","black chess rook":"♜","black chess bishop":"♝","black chess knight":"♞","black chess pawn":"♟","black spade suit":"♠","white heart suit":"♡","white diamond suit":"♢","black club suit":"♣","white spade suit":"♤","black heart suit":"♥","black diamond suit":"♦","white club suit":"♧","hot springs":"♨","quarter note":"♩","eighth note":"♪","beamed eighth notes":"♫","beamed sixteenth notes":"♬","music flat sign":"♭","music natural sign":"♮","music sharp sign":"♯","west syriac cross":"♰","east syriac cross":"♱","universal recycling symbol":"♲","black universal recycling symbol":"♻","recycled paper symbol":"♼","partially recycled paper symbol":"♽","permanent paper sign":"♾","wheelchair symbol":"♿","die face 1":"⚀","die face 2":"⚁","die face 3":"⚂","die face 4":"⚃","die face 5":"⚄","die face 6":"⚅","white circle with dot right":"⚆","white circle with two dots":"⚇","black circle with white dot right":"⚈","black circle with two white dots":"⚉","monogram for yang":"⚊","monogram for yin":"⚋","digram for greater yang":"⚌","digram for lesser yin":"⚍","digram for lesser yang":"⚎","digram for greater yin":"⚏","white flag":"⚐","black flag":"⚑","hammer and pick":"⚒","anchor":"⚓","crossed swords":"⚔","staff of aesculapius":"⚕","scales":"⚖","alembic":"⚗","flower":"⚘","gear":"⚙","staff of hermes":"⚚","atom symbol":"⚛","fleur de lis":"⚜","outlined white star":"⚝","three lines converging right":"⚞","three lines converging left":"⚟","warning sign":"⚠","high voltage sign":"⚡","doubled female sign":"⚢","doubled male sign":"⚣","interlocked female and male sign":"⚤","male and female sign":"⚥","male with stroke sign":"⚦","male with stroke and male and female sign":"⚧","vertical male with stroke sign":"⚨","horizontal male with stroke sign":"⚩","medium white circle":"⚪","medium black circle":"⚫","medium small white circle":"⚬","marriage symbol":"⚭","divorce symbol":"⚮","unmarried partnership symbol":"⚯","coffin":"⚰","funeral urn":"⚱","neuter":"⚲","ceres":"⚳","pallas":"⚴","juno":"⚵","vesta":"⚶","chiron":"⚷","black moon lilith":"⚸","sextile":"⚹","semisextile":"⚺","quincunx":"⚻","sesquiquadrate":"⚼","soccer ball":"⚽","baseball":"⚾","squared key":"⚿","white draughts man":"⛀","white draughts king":"⛁","black draughts man":"⛂","black draughts king":"⛃","snowman without snow":"⛄","sun behind cloud":"⛅","rain":"⛆","black snowman":"⛇","thunder cloud and rain":"⛈","turned white shogi piece":"⛉","turned black shogi piece":"⛊","white diamond in square":"⛋","crossing lanes":"⛌","disabled car":"⛍","ophiuchus":"⛎","pick":"⛏","car sliding":"⛐","helmet with white cross":"⛑","circled crossing lanes":"⛒","chains":"⛓","no entry":"⛔","alternate one way left way traffic":"⛕","black two way left way traffic":"⛖","white two way left way traffic":"⛗","black left lane merge":"⛘","white left lane merge":"⛙","drive slow sign":"⛚","heavy white down pointing triangle":"⛛","left closed entry":"⛜","squared saltire":"⛝","falling diagonal in white circle in black square":"⛞","black truck":"⛟","restricted left entry 1":"⛠","restricted left entry 2":"⛡","heavy circle with stroke and two dots above":"⛣","pentagram":"⛤","right handed interlaced pentagram":"⛥","left handed interlaced pentagram":"⛦","inverted pentagram":"⛧","black cross on shield":"⛨","shinto shrine":"⛩","church":"⛪","castle":"⛫","historic site":"⛬","gear without hub":"⛭","gear with handles":"⛮","mountain":"⛰","umbrella on ground":"⛱","fountain":"⛲","flag in hole":"⛳","ferry":"⛴","sailboat":"⛵","square four corners":"⛶","skier":"⛷","ice skate":"⛸","person with ball":"⛹","tent":"⛺","japanese bank symbol":"⛻","headstone graveyard symbol":"⛼","fuel pump":"⛽","cup on black square":"⛾","white flag with horizontal middle black stripe":"⛿","black safety scissors":"✀","upper blade scissors":"✁","black scissors":"✂","lower blade scissors":"✃","white scissors":"✄","white heavy check mark":"✅","telephone location sign":"✆","tape drive":"✇","airplane":"✈","envelope":"✉","raised fist":"✊","raised hand":"✋","victory hand":"✌","writing hand":"✍","lower right pencil":"✎","pencil":"✏","upper right pencil":"✐","white nib":"✑","black nib":"✒","check mark":"✓","heavy check mark":"✔","multiplication x":"✕","heavy multiplication x":"✖","ballot x":"✗","heavy ballot x":"✘","outlined greek cross":"✙","heavy greek cross":"✚","open centre cross":"✛","heavy open centre cross":"✜","latin cross":"✝","shadowed white latin cross":"✞","outlined latin cross":"✟","maltese cross":"✠","star of david":"✡","four teardrop spoked asterisk":"✢","four balloon spoked asterisk":"✣","heavy four balloon spoked asterisk":"✤","four club spoked asterisk":"✥","black four pointed star":"✦","white four pointed star":"✧","sparkles":"✨","stress outlined white star":"✩","circled white star":"✪","open centre black star":"✫","black centre white star":"✬","outlined black star":"✭","heavy outlined black star":"✮","pinwheel star":"✯","shadowed white star":"✰","heavy asterisk":"✱","open centre asterisk":"✲","eight spoked asterisk":"✳","eight pointed black star":"✴","eight pointed pinwheel star":"✵","six pointed black star":"✶","eight pointed rectilinear black star":"✷","heavy eight pointed rectilinear black star":"✸","twelve pointed black star":"✹","sixteen pointed asterisk":"✺","teardrop spoked asterisk":"✻","open centre teardrop spoked asterisk":"✼","heavy teardrop spoked asterisk":"✽","six petalled black and white florette":"✾","black florette":"✿","white florette":"❀","eight petalled outlined black florette":"❁","circled open centre eight pointed star":"❂","heavy teardrop spoked pinwheel asterisk":"❃","snowflake":"❄","tight trifoliate snowflake":"❅","heavy chevron snowflake":"❆","sparkle":"❇","heavy sparkle":"❈","balloon spoked asterisk":"❉","eight teardrop spoked propeller asterisk":"❊","heavy eight teardrop spoked propeller asterisk":"❋","cross mark":"❌","shadowed white circle":"❍","negative squared cross mark":"❎","lower right drop shadowed white square":"❏","upper right drop shadowed white square":"❐","lower right shadowed white square":"❑","upper right shadowed white square":"❒","black question mark ornament":"❓","white question mark ornament":"❔","white exclamation mark ornament":"❕","black diamond minus white x":"❖","heavy exclamation mark symbol":"❗","light vertical bar":"❘","medium vertical bar":"❙","heavy vertical bar":"❚","heavy single turned comma quotation mark ornament":"❛","heavy single comma quotation mark ornament":"❜","heavy double turned comma quotation mark ornament":"❝","heavy double comma quotation mark ornament":"❞","heavy low single comma quotation mark ornament":"❟","heavy low double comma quotation mark ornament":"❠","curved stem paragraph sign ornament":"❡","heavy exclamation mark ornament":"❢","heavy heart exclamation mark ornament":"❣","heavy black heart":"❤","rotated heavy black heart bullet":"❥","floral heart":"❦","rotated floral heart bullet":"❧","medium left parenthesis ornament":"❨","medium right parenthesis ornament":"❩","medium flattened left parenthesis ornament":"❪","medium flattened right parenthesis ornament":"❫","medium left pointing angle bracket ornament":"❬","medium right pointing angle bracket ornament":"❭","heavy left pointing angle quotation mark ornament":"❮","heavy right pointing angle quotation mark ornament":"❯","heavy left pointing angle bracket ornament":"❰","heavy right pointing angle bracket ornament":"❱","light left tortoise shell bracket ornament":"❲","light right tortoise shell bracket ornament":"❳","medium left curly bracket ornament":"❴","medium right curly bracket ornament":"❵","dingbat negative circled digit one":"❶","dingbat negative circled digit two":"❷","dingbat negative circled digit three":"❸","dingbat negative circled digit four":"❹","dingbat negative circled digit five":"❺","dingbat negative circled digit six":"❻","dingbat negative circled digit seven":"❼","dingbat negative circled digit eight":"❽","dingbat negative circled digit nine":"❾","dingbat negative circled number ten":"❿","dingbat circled sans serif digit one":"➀","dingbat circled sans serif digit two":"➁","dingbat circled sans serif digit three":"➂","dingbat circled sans serif digit four":"➃","dingbat circled sans serif digit five":"➄","dingbat circled sans serif digit six":"➅","dingbat circled sans serif digit seven":"➆","dingbat circled sans serif digit eight":"➇","dingbat circled sans serif digit nine":"➈","dingbat circled sans serif number ten":"➉","dingbat negative circled sans serif digit one":"➊","dingbat negative circled sans serif digit two":"➋","dingbat negative circled sans serif digit three":"➌","dingbat negative circled sans serif digit four":"➍","dingbat negative circled sans serif digit five":"➎","dingbat negative circled sans serif digit six":"➏","dingbat negative circled sans serif digit seven":"➐","dingbat negative circled sans serif digit eight":"➑","dingbat negative circled sans serif digit nine":"➒","dingbat negative circled sans serif number ten":"➓","heavy wide headed rightwards arrow":"➔","heavy plus sign":"➕","heavy minus sign":"➖","heavy division sign":"➗","heavy south east arrow":"➘","heavy rightwards arrow":"➙","heavy north east arrow":"➚","drafting point rightwards arrow":"➛","heavy round tipped rightwards arrow":"➜","triangle headed rightwards arrow":"➝","heavy triangle headed rightwards arrow":"➞","dashed triangle headed rightwards arrow":"➟","heavy dashed triangle headed rightwards arrow":"➠","black rightwards arrow":"➡","three d top lighted rightwards arrowhead":"➢","three d bottom lighted rightwards arrowhead":"➣","black rightwards arrowhead":"➤","heavy black curved downwards and rightwards arrow":"➥","heavy black curved upwards and rightwards arrow":"➦","squat black rightwards arrow":"➧","heavy concave pointed black rightwards arrow":"➨","right shaded white rightwards arrow":"➩","left shaded white rightwards arrow":"➪","back tilted shadowed white rightwards arrow":"➫","front tilted shadowed white rightwards arrow":"➬","heavy lower right shadowed white rightwards arrow":"➭","heavy upper right shadowed white rightwards arrow":"➮","notched lower right shadowed white rightwards arrow":"➯","curly loop":"➰","notched upper right shadowed white rightwards arrow":"➱","circled heavy white rightwards arrow":"➲","white feathered rightwards arrow":"➳","black feathered south east arrow":"➴","black feathered rightwards arrow":"➵","black feathered north east arrow":"➶","heavy black feathered south east arrow":"➷","heavy black feathered rightwards arrow":"➸","heavy black feathered north east arrow":"➹","teardrop barbed rightwards arrow":"➺","heavy teardrop shanked rightwards arrow":"➻","wedge tailed rightwards arrow":"➼","heavy wedge tailed rightwards arrow":"➽","open outlined rightwards arrow":"➾","double curly loop":"➿","cyclone":"🌀","foggy":"🌁","closed umbrella":"🌂","night with stars":"🌃","sunrise over mountains":"🌄","sunrise":"🌅","cityscape at dusk":"🌆","sunset over buildings":"🌇","rainbow":"🌈","bridge at night":"🌉","water wave":"🌊","volcano":"🌋","milky way":"🌌","earth globe europe africa":"🌍","earth globe americas":"🌎","earth globe asia australia":"🌏","globe with meridians":"🌐","new moon symbol":"🌑","waxing crescent moon symbol":"🌒","first quarter moon symbol":"🌓","waxing gibbous moon symbol":"🌔","full moon symbol":"🌕","waning gibbous moon symbol":"🌖","last quarter moon symbol":"🌗","waning crescent moon symbol":"🌘","crescent moon":"🌙","new moon with face":"🌚","first quarter moon with face":"🌛","last quarter moon with face":"🌜","full moon with face":"🌝","sun with face":"🌞","glowing star":"🌟","shooting star":"🌠","thermometer":"🌡","black droplet":"🌢","white sun":"🌣","white sun with small cloud":"🌤","white sun behind cloud":"🌥","white sun behind cloud with rain":"🌦","cloud with rain":"🌧","cloud with snow":"🌨","cloud with lightning":"🌩","cloud with tornado":"🌪","fog":"🌫","wind blowing face":"🌬","hot dog":"🌭","taco":"🌮","burrito":"🌯","chestnut":"🌰","seedling":"🌱","evergreen tree":"🌲","deciduous tree":"🌳","palm tree":"🌴","cactus":"🌵","hot pepper":"🌶","tulip":"🌷","cherry blossom":"🌸","rose":"🌹","hibiscus":"🌺","sunflower":"🌻","blossom":"🌼","ear of maize":"🌽","ear of rice":"🌾","herb":"🌿","four leaf clover":"🍀","maple leaf":"🍁","fallen leaf":"🍂","leaf fluttering in wind":"🍃","mushroom":"🍄","tomato":"🍅","aubergine":"🍆","grapes":"🍇","melon":"🍈","watermelon":"🍉","tangerine":"🍊","lemon":"🍋","banana":"🍌","pineapple":"🍍","red apple":"🍎","green apple":"🍏","pear":"🍐","peach":"🍑","cherries":"🍒","strawberry":"🍓","hamburger":"🍔","slice of pizza":"🍕","meat on bone":"🍖","poultry leg":"🍗","rice cracker":"🍘","rice ball":"🍙","cooked rice":"🍚","curry and rice":"🍛","steaming bowl":"🍜","spaghetti":"🍝","bread":"🍞","french fries":"🍟","roasted sweet potato":"🍠","dango":"🍡","oden":"🍢","sushi":"🍣","fried shrimp":"🍤","fish cake with swirl design":"🍥","soft ice cream":"🍦","shaved ice":"🍧","ice cream":"🍨","doughnut":"🍩","cookie":"🍪","chocolate bar":"🍫","candy":"🍬","lollipop":"🍭","custard":"🍮","honey pot":"🍯","shortcake":"🍰","bento box":"🍱","pot of food":"🍲","cooking":"🍳","fork and knife":"🍴","teacup without handle":"🍵","sake bottle and cup":"🍶","wine glass":"🍷","cocktail glass":"🍸","tropical drink":"🍹","beer mug":"🍺","clinking beer mugs":"🍻","baby bottle":"🍼","fork and knife with plate":"🍽","bottle with popping cork":"🍾","popcorn":"🍿","ribbon":"🎀","wrapped present":"🎁","birthday cake":"🎂","jack o lantern":"🎃","christmas tree":"🎄","father christmas":"🎅","fireworks":"🎆","firework sparkler":"🎇","balloon":"🎈","party popper":"🎉","confetti ball":"🎊","tanabata tree":"🎋","crossed flags":"🎌","pine decoration":"🎍","japanese dolls":"🎎","carp streamer":"🎏","wind chime":"🎐","moon viewing ceremony":"🎑","school satchel":"🎒","graduation cap":"🎓","heart with tip on the left":"🎔","bouquet of flowers":"🎕","military medal":"🎖","reminder ribbon":"🎗","musical keyboard with jacks":"🎘","studio microphone":"🎙","level slider":"🎚","control knobs":"🎛","beamed ascending musical notes":"🎜","beamed descending musical notes":"🎝","film frames":"🎞","admission tickets":"🎟","carousel horse":"🎠","ferris wheel":"🎡","roller coaster":"🎢","fishing pole and fish":"🎣","microphone":"🎤","movie camera":"🎥","cinema":"🎦","headphone":"🎧","artist palette":"🎨","top hat":"🎩","circus tent":"🎪","ticket":"🎫","clapper board":"🎬","performing arts":"🎭","video game":"🎮","direct hit":"🎯","slot machine":"🎰","billiards":"🎱","game die":"🎲","bowling":"🎳","flower playing cards":"🎴","musical note":"🎵","multiple musical notes":"🎶","saxophone":"🎷","guitar":"🎸","musical keyboard":"🎹","trumpet":"🎺","violin":"🎻","musical score":"🎼","running shirt with sash":"🎽","tennis racquet and ball":"🎾","ski and ski boot":"🎿","basketball and hoop":"🏀","chequered flag":"🏁","snowboarder":"🏂","runner":"🏃","surfer":"🏄","sports medal":"🏅","trophy":"🏆","horse racing":"🏇","american football":"🏈","rugby football":"🏉","swimmer":"🏊","weight lifter":"🏋","golfer":"🏌","racing motorcycle":"🏍","racing car":"🏎","cricket bat and ball":"🏏","volleyball":"🏐","field hockey stick and ball":"🏑","ice hockey stick and puck":"🏒","table tennis paddle and ball":"🏓","snow capped mountain":"🏔","camping":"🏕","beach with umbrella":"🏖","building construction":"🏗","house buildings":"🏘","cityscape":"🏙","derelict house building":"🏚","classical building":"🏛","desert":"🏜","desert island":"🏝","national park":"🏞","stadium":"🏟","house building":"🏠","house with garden":"🏡","office building":"🏢","japanese post office":"🏣","european post office":"🏤","hospital":"🏥","bank":"🏦","automated teller machine":"🏧","hotel":"🏨","love hotel":"🏩","convenience store":"🏪","school":"🏫","department store":"🏬","factory":"🏭","izakaya lantern":"🏮","japanese castle":"🏯","european castle":"🏰","white pennant":"🏱","black pennant":"🏲","waving white flag":"🏳","waving black flag":"🏴","rosette":"🏵","black rosette":"🏶","label":"🏷","badminton racquet and shuttlecock":"🏸","bow and arrow":"🏹","amphora":"🏺","rat":"🐀","mouse":"🐁","ox":"🐂","water buffalo":"🐃","cow":"🐄","tiger":"🐅","leopard":"🐆","rabbit":"🐇","cat":"🐈","dragon":"🐉","crocodile":"🐊","whale":"🐋","snail":"🐌","snake":"🐍","horse":"🐎","ram":"🐏","goat":"🐐","sheep":"🐑","monkey":"🐒","rooster":"🐓","chicken":"🐔","dog":"🐕","pig":"🐖","boar":"🐗","elephant":"🐘","octopus":"🐙","spiral shell":"🐚","bug":"🐛","ant":"🐜","honeybee":"🐝","lady beetle":"🐞","fish":"🐟","tropical fish":"🐠","blowfish":"🐡","turtle":"🐢","hatching chick":"🐣","baby chick":"🐤","front facing baby chick":"🐥","bird":"🐦","penguin":"🐧","koala":"🐨","poodle":"🐩","dromedary camel":"🐪","bactrian camel":"🐫","dolphin":"🐬","mouse face":"🐭","cow face":"🐮","tiger face":"🐯","rabbit face":"🐰","cat face":"🐱","dragon face":"🐲","spouting whale":"🐳","horse face":"🐴","monkey face":"🐵","dog face":"🐶","pig face":"🐷","frog face":"🐸","hamster face":"🐹","wolf face":"🐺","bear face":"🐻","panda face":"🐼","pig nose":"🐽","paw prints":"🐾","chipmunk":"🐿","eyes":"👀","eye":"👁","ear":"👂","nose":"👃","mouth":"👄","tongue":"👅","white up pointing backhand index":"👆","white down pointing backhand index":"👇","white left pointing backhand index":"👈","white right pointing backhand index":"👉","fisted hand sign":"👊","waving hand sign":"👋","ok hand sign":"👌","thumbs up sign":"👍","thumbs down sign":"👎","clapping hands sign":"👏","open hands sign":"👐","crown":"👑","womans hat":"👒","eyeglasses":"👓","necktie":"👔","t shirt":"👕","jeans":"👖","dress":"👗","kimono":"👘","bikini":"👙","womans clothes":"👚","purse":"👛","handbag":"👜","pouch":"👝","mans shoe":"👞","athletic shoe":"👟","high heeled shoe":"👠","womans sandal":"👡","womans boots":"👢","footprints":"👣","bust in silhouette":"👤","busts in silhouette":"👥","boy":"👦","girl":"👧","man":"👨","woman":"👩","family":"👪","man and woman holding hands":"👫","two men holding hands":"👬","two women holding hands":"👭","police officer":"👮","woman with bunny ears":"👯","bride with veil":"👰","person with blond hair":"👱","man with gua pi mao":"👲","man with turban":"👳","older man":"👴","older woman":"👵","baby":"👶","construction worker":"👷","princess":"👸","japanese ogre":"👹","japanese goblin":"👺","ghost":"👻","baby angel":"👼","extraterrestrial alien":"👽","alien monster":"👾","imp":"👿","skull":"💀","information desk person":"💁","guardsman":"💂","dancer":"💃","lipstick":"💄","nail polish":"💅","face massage":"💆","haircut":"💇","barber pole":"💈","syringe":"💉","pill":"💊","kiss mark":"💋","love letter":"💌","ring":"💍","gem stone":"💎","kiss":"💏","bouquet":"💐","couple with heart":"💑","wedding":"💒","beating heart":"💓","broken heart":"💔","two hearts":"💕","sparkling heart":"💖","growing heart":"💗","heart with arrow":"💘","blue heart":"💙","green heart":"💚","yellow heart":"💛","purple heart":"💜","heart with ribbon":"💝","revolving hearts":"💞","heart decoration":"💟","diamond shape with a dot inside":"💠","electric light bulb":"💡","anger symbol":"💢","bomb":"💣","sleeping symbol":"💤","collision symbol":"💥","splashing sweat symbol":"💦","droplet":"💧","dash symbol":"💨","pile of poo":"💩","flexed biceps":"💪","dizzy symbol":"💫","speech balloon":"💬","thought balloon":"💭","white flower":"💮","hundred points symbol":"💯","money bag":"💰","currency exchange":"💱","heavy dollar sign":"💲","credit card":"💳","banknote with yen sign":"💴","banknote with dollar sign":"💵","banknote with euro sign":"💶","banknote with pound sign":"💷","money with wings":"💸","chart with upwards trend and yen sign":"💹","seat":"💺","personal computer":"💻","briefcase":"💼","minidisc":"💽","floppy disk":"💾","optical disc":"💿","dvd":"📀","file folder":"📁","open file folder":"📂","page with curl":"📃","page facing up":"📄","calendar":"📅","tear off calendar":"📆","card index":"📇","chart with upwards trend":"📈","chart with downwards trend":"📉","bar chart":"📊","clipboard":"📋","pushpin":"📌","round pushpin":"📍","paperclip":"📎","straight ruler":"📏","triangular ruler":"📐","bookmark tabs":"📑","ledger":"📒","notebook":"📓","notebook with decorative cover":"📔","closed book":"📕","open book":"📖","green book":"📗","blue book":"📘","orange book":"📙","books":"📚","name badge":"📛","scroll":"📜","memo":"📝","telephone receiver":"📞","pager":"📟","fax machine":"📠","satellite antenna":"📡","public address loudspeaker":"📢","cheering megaphone":"📣","outbox tray":"📤","inbox tray":"📥","package":"📦","e mail symbol":"📧","incoming envelope":"📨","envelope with downwards arrow above":"📩","closed mailbox with lowered flag":"📪","closed mailbox with raised flag":"📫","open mailbox with raised flag":"📬","open mailbox with lowered flag":"📭","postbox":"📮","postal horn":"📯","newspaper":"📰","mobile phone":"📱","mobile phone with rightwards arrow at left":"📲","vibration mode":"📳","mobile phone off":"📴","no mobile phones":"📵","antenna with bars":"📶","camera":"📷","camera with flash":"📸","video camera":"📹","television":"📺","radio":"📻","videocassette":"📼","film projector":"📽","portable stereo":"📾","prayer beads":"📿","twisted rightwards arrows":"🔀","clockwise rightwards and leftwards open circle arrows":"🔁","clockwise rightwards and leftwards open circle arrows with circled one overlay":"🔂","clockwise downwards and upwards open circle arrows":"🔃","anticlockwise downwards and upwards open circle arrows":"🔄","low brightness symbol":"🔅","high brightness symbol":"🔆","speaker with cancellation stroke":"🔇","speaker":"🔈","speaker with one sound wave":"🔉","speaker with three sound waves":"🔊","battery":"🔋","electric plug":"🔌","left pointing magnifying glass":"🔍","right pointing magnifying glass":"🔎","lock with ink pen":"🔏","closed lock with key":"🔐","key":"🔑","lock":"🔒","open lock":"🔓","bell":"🔔","bell with cancellation stroke":"🔕","bookmark":"🔖","link symbol":"🔗","radio button":"🔘","back with leftwards arrow above":"🔙","end with leftwards arrow above":"🔚","on with exclamation mark with left right arrow above":"🔛","soon with rightwards arrow above":"🔜","top with upwards arrow above":"🔝","no one under eighteen symbol":"🔞","keycap ten":"🔟","fire":"🔥","electric torch":"🔦","wrench":"🔧","hammer":"🔨","nut and bolt":"🔩","hocho":"🔪","pistol":"🔫","microscope":"🔬","telescope":"🔭","crystal ball":"🔮","six pointed star with middle dot":"🔯","trident emblem":"🔱","black square button":"🔲","white square button":"🔳","large red circle":"🔴","large blue circle":"🔵","large orange diamond":"🔶","large blue diamond":"🔷","small orange diamond":"🔸","small blue diamond":"🔹","up pointing red triangle":"🔺","down pointing red triangle":"🔻","up pointing small red triangle":"🔼","down pointing small red triangle":"🔽","lower right shadowed white circle":"🔾","upper right shadowed white circle":"🔿","circled cross pommee":"🕀","cross pommee with half circle below":"🕁","cross pommee":"🕂","notched left semicircle with three dots":"🕃","notched right semicircle with three dots":"🕄","white latin cross":"🕆","heavy latin cross":"🕇","celtic cross":"🕈","om symbol":"🕉","dove of peace":"🕊","kaaba":"🕋","mosque":"🕌","synagogue":"🕍","menorah with nine branches":"🕎","bowl of hygieia":"🕏","clock face one oclock":"🕐","clock face two oclock":"🕑","clock face three oclock":"🕒","clock face four oclock":"🕓","clock face five oclock":"🕔","clock face six oclock":"🕕","clock face seven oclock":"🕖","clock face eight oclock":"🕗","clock face nine oclock":"🕘","clock face ten oclock":"🕙","clock face eleven oclock":"🕚","clock face twelve oclock":"🕛","clock face one thirty":"🕜","clock face two thirty":"🕝","clock face three thirty":"🕞","clock face four thirty":"🕟","clock face five thirty":"🕠","clock face six thirty":"🕡","clock face seven thirty":"🕢","clock face eight thirty":"🕣","clock face nine thirty":"🕤","clock face ten thirty":"🕥","clock face eleven thirty":"🕦","clock face twelve thirty":"🕧","right speaker":"🕨","right speaker with one sound wave":"🕩","right speaker with three sound waves":"🕪","bullhorn":"🕫","bullhorn with sound waves":"🕬","ringing bell":"🕭","book":"🕮","candle":"🕯","mantelpiece clock":"🕰","black skull and crossbones":"🕱","no piracy":"🕲","hole":"🕳","man in business suit levitating":"🕴","sleuth or spy":"🕵","dark sunglasses":"🕶","spider":"🕷","spider web":"🕸","joystick":"🕹","man dancing":"🕺","left hand telephone receiver":"🕻","telephone receiver with page":"🕼","right hand telephone receiver":"🕽","white touchtone telephone":"🕾","black touchtone telephone":"🕿","telephone on top of modem":"🖀","clamshell mobile phone":"🖁","back of envelope":"🖂","stamped envelope":"🖃","envelope with lightning":"🖄","flying envelope":"🖅","pen over stamped envelope":"🖆","linked paperclips":"🖇","black pushpin":"🖈","lower left pencil":"🖉","lower left ballpoint pen":"🖊","lower left fountain pen":"🖋","lower left paintbrush":"🖌","lower left crayon":"🖍","left writing hand":"🖎","turned ok hand sign":"🖏","raised hand with fingers splayed":"🖐","reversed raised hand with fingers splayed":"🖑","reversed thumbs up sign":"🖒","reversed thumbs down sign":"🖓","reversed victory hand":"🖔","reversed hand with middle finger extended":"🖕","raised hand with part between middle and ring fingers":"🖖","white down pointing left hand index":"🖗","sideways white left pointing index":"🖘","sideways white right pointing index":"🖙","sideways black left pointing index":"🖚","sideways black right pointing index":"🖛","black left pointing backhand index":"🖜","black right pointing backhand index":"🖝","sideways white up pointing index":"🖞","sideways white down pointing index":"🖟","sideways black up pointing index":"🖠","sideways black down pointing index":"🖡","black up pointing backhand index":"🖢","black down pointing backhand index":"🖣","black heart":"🖤","desktop computer":"🖥","keyboard and mouse":"🖦","three networked computers":"🖧","printer":"🖨","pocket calculator":"🖩","black hard shell floppy disk":"🖪","white hard shell floppy disk":"🖫","soft shell floppy disk":"🖬","tape cartridge":"🖭","wired keyboard":"🖮","one button mouse":"🖯","two button mouse":"🖰","three button mouse":"🖱","trackball":"🖲","old personal computer":"🖳","hard disk":"🖴","screen":"🖵","printer icon":"🖶","fax icon":"🖷","optical disc icon":"🖸","document with text":"🖹","document with text and picture":"🖺","document with picture":"🖻","frame with picture":"🖼","frame with tiles":"🖽","frame with an x":"🖾","black folder":"🖿","folder":"🗀","open folder":"🗁","card index dividers":"🗂","card file box":"🗃","file cabinet":"🗄","empty note":"🗅","empty note page":"🗆","empty note pad":"🗇","note":"🗈","note page":"🗉","note pad":"🗊","empty document":"🗋","empty page":"🗌","empty pages":"🗍","document":"🗎","page":"🗏","pages":"🗐","wastebasket":"🗑","spiral note pad":"🗒","spiral calendar pad":"🗓","desktop window":"🗔","minimize":"🗕","maximize":"🗖","overlap":"🗗","clockwise right and left semicircle arrows":"🗘","cancellation x":"🗙","increase font size symbol":"🗚","decrease font size symbol":"🗛","compression":"🗜","old key":"🗝","rolled up newspaper":"🗞","page with circled text":"🗟","stock chart":"🗠","dagger knife":"🗡","lips":"🗢","speaking head in silhouette":"🗣","three rays above":"🗤","three rays below":"🗥","three rays left":"🗦","three rays right":"🗧","left speech bubble":"🗨","right speech bubble":"🗩","two speech bubbles":"🗪","three speech bubbles":"🗫","left thought bubble":"🗬","right thought bubble":"🗭","left anger bubble":"🗮","right anger bubble":"🗯","mood bubble":"🗰","lightning mood bubble":"🗱","lightning mood":"🗲","ballot box with ballot":"🗳","ballot script x":"🗴","ballot box with script x":"🗵","ballot bold script x":"🗶","ballot box with bold script x":"🗷","light check mark":"🗸","ballot box with bold check":"🗹","world map":"🗺","mount fuji":"🗻","tokyo tower":"🗼","statue of liberty":"🗽","silhouette of japan":"🗾","moyai":"🗿","grinning face":"😀","grinning face with smiling eyes":"😁","face with tears of joy":"😂","smiling face with open mouth":"😃","smiling face with open mouth and smiling eyes":"😄","smiling face with open mouth and cold sweat":"😅","smiling face with open mouth and tightly closed eyes":"😆","smiling face with halo":"😇","smiling face with horns":"😈","winking face":"😉","smiling face with smiling eyes":"😊","face savouring delicious food":"😋","relieved face":"😌","smiling face with heart shaped eyes":"😍","smiling face with sunglasses":"😎","smirking face":"😏","neutral face":"😐","expressionless face":"😑","unamused face":"😒","face with cold sweat":"😓","pensive face":"😔","confused face":"😕","confounded face":"😖","kissing face":"😗","face throwing a kiss":"😘","kissing face with smiling eyes":"😙","kissing face with closed eyes":"😚","face with stuck out tongue":"😛","face with stuck out tongue and winking eye":"😜","face with stuck out tongue and tightly closed eyes":"😝","disappointed face":"😞","worried face":"😟","angry face":"😠","pouting face":"😡","crying face":"😢","persevering face":"😣","face with look of triumph":"😤","disappointed but relieved face":"😥","frowning face with open mouth":"😦","anguished face":"😧","fearful face":"😨","weary face":"😩","sleepy face":"😪","tired face":"😫","grimacing face":"😬","loudly crying face":"😭","face with open mouth":"😮","hushed face":"😯","face with open mouth and cold sweat":"😰","face screaming in fear":"😱","astonished face":"😲","flushed face":"😳","sleeping face":"😴","dizzy face":"😵","face without mouth":"😶","face with medical mask":"😷","grinning cat face with smiling eyes":"😸","cat face with tears of joy":"😹","smiling cat face with open mouth":"😺","smiling cat face with heart shaped eyes":"😻","cat face with wry smile":"😼","kissing cat face with closed eyes":"😽","pouting cat face":"😾","crying cat face":"😿","weary cat face":"🙀","slightly frowning face":"🙁","slightly smiling face":"🙂","upside down face":"🙃","face with rolling eyes":"🙄","face with no good gesture":"🙅","face with ok gesture":"🙆","person bowing deeply":"🙇","see no evil monkey":"🙈","hear no evil monkey":"🙉","speak no evil monkey":"🙊","happy person raising one hand":"🙋","person raising both hands in celebration":"🙌","person frowning":"🙍","person with pouting face":"🙎","person with folded hands":"🙏","rocket":"🚀","helicopter":"🚁","steam locomotive":"🚂","railway car":"🚃","high speed train":"🚄","high speed train with bullet nose":"🚅","train":"🚆","metro":"🚇","light rail":"🚈","station":"🚉","tram":"🚊","tram car":"🚋","bus":"🚌","oncoming bus":"🚍","trolleybus":"🚎","bus stop":"🚏","minibus":"🚐","ambulance":"🚑","fire engine":"🚒","police car":"🚓","oncoming police car":"🚔","taxi":"🚕","oncoming taxi":"🚖","automobile":"🚗","oncoming automobile":"🚘","recreational vehicle":"🚙","delivery truck":"🚚","articulated lorry":"🚛","tractor":"🚜","monorail":"🚝","mountain railway":"🚞","suspension railway":"🚟","mountain cableway":"🚠","aerial tramway":"🚡","ship":"🚢","rowboat":"🚣","speedboat":"🚤","horizontal traffic light":"🚥","vertical traffic light":"🚦","construction sign":"🚧","police cars revolving light":"🚨","triangular flag on post":"🚩","door":"🚪","no entry sign":"🚫","smoking symbol":"🚬","no smoking symbol":"🚭","put litter in its place symbol":"🚮","do not litter symbol":"🚯","potable water symbol":"🚰","non potable water symbol":"🚱","bicycle":"🚲","no bicycles":"🚳","bicyclist":"🚴","mountain bicyclist":"🚵","pedestrian":"🚶","no pedestrians":"🚷","children crossing":"🚸","mens symbol":"🚹","womens symbol":"🚺","restroom":"🚻","baby symbol":"🚼","toilet":"🚽","water closet":"🚾","shower":"🚿","bath":"🛀","bathtub":"🛁","passport control":"🛂","customs":"🛃","baggage claim":"🛄","left luggage":"🛅","triangle with rounded corners":"🛆","prohibited sign":"🛇","circled information source":"🛈","boys symbol":"🛉","girls symbol":"🛊","couch and lamp":"🛋","sleeping accommodation":"🛌","shopping bags":"🛍","bellhop bell":"🛎","bed":"🛏","place of worship":"🛐","octagonal sign":"🛑","shopping trolley":"🛒","stupa":"🛓","pagoda":"🛔","hindu temple":"🛕","hut":"🛖","elevator":"🛗","hammer and wrench":"🛠","shield":"🛡","oil drum":"🛢","motorway":"🛣","railway track":"🛤","motor boat":"🛥","up pointing military airplane":"🛦","up pointing airplane":"🛧","up pointing small airplane":"🛨","small airplane":"🛩","northeast pointing airplane":"🛪","airplane departure":"🛫","airplane arriving":"🛬","satellite":"🛰","oncoming fire engine":"🛱","diesel locomotive":"🛲","passenger ship":"🛳","scooter":"🛴","motor scooter":"🛵","canoe":"🛶","sled":"🛷","flying saucer":"🛸","skateboard":"🛹","auto rickshaw":"🛺","pickup truck":"🛻","roller skate":"🛼","circled cross formee with four dots":"🤀","circled cross formee with two dots":"🤁","circled cross formee":"🤂","left half circle with four dots":"🤃","left half circle with three dots":"🤄","left half circle with two dots":"🤅","left half circle with dot":"🤆","left half circle":"🤇","downward facing hook":"🤈","downward facing notched hook":"🤉","downward facing hook with dot":"🤊","downward facing notched hook with dot":"🤋","pinched fingers":"🤌","white heart":"🤍","brown heart":"🤎","pinching hand":"🤏","zipper mouth face":"🤐","money mouth face":"🤑","face with thermometer":"🤒","nerd face":"🤓","thinking face":"🤔","face with head bandage":"🤕","robot face":"🤖","hugging face":"🤗","sign of the horns":"🤘","call me hand":"🤙","raised back of hand":"🤚","left facing fist":"🤛","right facing fist":"🤜","handshake":"🤝","hand with index and middle fingers crossed":"🤞","i love you hand sign":"🤟","face with cowboy hat":"🤠","clown face":"🤡","nauseated face":"🤢","rolling on the floor laughing":"🤣","drooling face":"🤤","lying face":"🤥","face palm":"🤦","sneezing face":"🤧","face with one eyebrow raised":"🤨","grinning face with star eyes":"🤩","grinning face with one large and one small eye":"🤪","face with finger covering closed lips":"🤫","serious face with symbols covering mouth":"🤬","smiling face with smiling eyes and hand covering mouth":"🤭","face with open mouth vomiting":"🤮","shocked face with exploding head":"🤯","pregnant woman":"🤰","breast feeding":"🤱","palms up together":"🤲","selfie":"🤳","prince":"🤴","man in tuxedo":"🤵","mother christmas":"🤶","shrug":"🤷","person doing cartwheel":"🤸","juggling":"🤹","fencer":"🤺","modern pentathlon":"🤻","wrestlers":"🤼","water polo":"🤽","handball":"🤾","diving mask":"🤿","wilted flower":"🥀","drum with drumsticks":"🥁","clinking glasses":"🥂","tumbler glass":"🥃","spoon":"🥄","goal net":"🥅","rifle":"🥆","first place medal":"🥇","second place medal":"🥈","third place medal":"🥉","boxing glove":"🥊","martial arts uniform":"🥋","curling stone":"🥌","lacrosse stick and ball":"🥍","softball":"🥎","flying disc":"🥏","croissant":"🥐","avocado":"🥑","cucumber":"🥒","bacon":"🥓","potato":"🥔","carrot":"🥕","baguette bread":"🥖","green salad":"🥗","shallow pan of food":"🥘","stuffed flatbread":"🥙","egg":"🥚","glass of milk":"🥛","peanuts":"🥜","kiwifruit":"🥝","pancakes":"🥞","dumpling":"🥟","fortune cookie":"🥠","takeout box":"🥡","chopsticks":"🥢","bowl with spoon":"🥣","cup with straw":"🥤","coconut":"🥥","broccoli":"🥦","pie":"🥧","pretzel":"🥨","cut of meat":"🥩","sandwich":"🥪","canned food":"🥫","leafy green":"🥬","mango":"🥭","moon cake":"🥮","bagel":"🥯","smiling face with smiling eyes and three hearts":"🥰","yawning face":"🥱","smiling face with tear":"🥲","face with party horn and party hat":"🥳","face with uneven eyes and wavy mouth":"🥴","overheated face":"🥵","freezing face":"🥶","ninja":"🥷","disguised face":"🥸","face with pleading eyes":"🥺","sari":"🥻","lab coat":"🥼","goggles":"🥽","hiking boot":"🥾","flat shoe":"🥿","crab":"🦀","lion face":"🦁","scorpion":"🦂","turkey":"🦃","unicorn face":"🦄","eagle":"🦅","duck":"🦆","bat":"🦇","shark":"🦈","owl":"🦉","fox face":"🦊","butterfly":"🦋","deer":"🦌","gorilla":"🦍","lizard":"🦎","rhinoceros":"🦏","shrimp":"🦐","squid":"🦑","giraffe face":"🦒","zebra face":"🦓","hedgehog":"🦔","sauropod":"🦕","t rex":"🦖","cricket":"🦗","kangaroo":"🦘","llama":"🦙","peacock":"🦚","hippopotamus":"🦛","parrot":"🦜","raccoon":"🦝","lobster":"🦞","mosquito":"🦟","microbe":"🦠","badger":"🦡","swan":"🦢","mammoth":"🦣","dodo":"🦤","sloth":"🦥","otter":"🦦","orangutan":"🦧","skunk":"🦨","flamingo":"🦩","oyster":"🦪","beaver":"🦫","bison":"🦬","seal":"🦭","guide dog":"🦮","probing cane":"🦯","emoji component red hair":"🦰","emoji component curly hair":"🦱","emoji component bald":"🦲","emoji component white hair":"🦳","bone":"🦴","leg":"🦵","foot":"🦶","tooth":"🦷","superhero":"🦸","supervillain":"🦹","safety vest":"🦺","ear with hearing aid":"🦻","motorized wheelchair":"🦼","manual wheelchair":"🦽","mechanical arm":"🦾","mechanical leg":"🦿","cheese wedge":"🧀","cupcake":"🧁","salt shaker":"🧂","beverage box":"🧃","garlic":"🧄","onion":"🧅","falafel":"🧆","waffle":"🧇","butter":"🧈","mate drink":"🧉","ice cube":"🧊","bubble tea":"🧋","standing person":"🧍","kneeling person":"🧎","deaf person":"🧏","face with monocle":"🧐","adult":"🧑","child":"🧒","older adult":"🧓","bearded person":"🧔","person with headscarf":"🧕","person in steamy room":"🧖","person climbing":"🧗","person in lotus position":"🧘","mage":"🧙","fairy":"🧚","vampire":"🧛","merperson":"🧜","elf":"🧝","genie":"🧞","zombie":"🧟","brain":"🧠","orange heart":"🧡","billed cap":"🧢","scarf":"🧣","gloves":"🧤","coat":"🧥","socks":"🧦","red gift envelope":"🧧","firecracker":"🧨","jigsaw puzzle piece":"🧩","test tube":"🧪","petri dish":"🧫","dna double helix":"🧬","compass":"🧭","abacus":"🧮","fire extinguisher":"🧯","toolbox":"🧰","brick":"🧱","magnet":"🧲","luggage":"🧳","lotion bottle":"🧴","spool of thread":"🧵","ball of yarn":"🧶","safety pin":"🧷","teddy bear":"🧸","broom":"🧹","basket":"🧺","roll of paper":"🧻","bar of soap":"🧼","sponge":"🧽","receipt":"🧾","nazar amulet":"🧿","neutral chess king":"🨀","neutral chess queen":"🨁","neutral chess rook":"🨂","neutral chess bishop":"🨃","neutral chess knight":"🨄","neutral chess pawn":"🨅","white chess knight rotated forty five degrees":"🨆","black chess knight rotated forty five degrees":"🨇","neutral chess knight rotated forty five degrees":"🨈","white chess king rotated ninety degrees":"🨉","white chess queen rotated ninety degrees":"🨊","white chess rook rotated ninety degrees":"🨋","white chess bishop rotated ninety degrees":"🨌","white chess knight rotated ninety degrees":"🨍","white chess pawn rotated ninety degrees":"🨎","black chess king rotated ninety degrees":"🨏","black chess queen rotated ninety degrees":"🨐","black chess rook rotated ninety degrees":"🨑","black chess bishop rotated ninety degrees":"🨒","black chess knight rotated ninety degrees":"🨓","black chess pawn rotated ninety degrees":"🨔","neutral chess king rotated ninety degrees":"🨕","neutral chess queen rotated ninety degrees":"🨖","neutral chess rook rotated ninety degrees":"🨗","neutral chess bishop rotated ninety degrees":"🨘","neutral chess knight rotated ninety degrees":"🨙","neutral chess pawn rotated ninety degrees":"🨚","white chess knight rotated one hundred thirty five degrees":"🨛","black chess knight rotated one hundred thirty five degrees":"🨜","neutral chess knight rotated one hundred thirty five degrees":"🨝","white chess turned king":"🨞","white chess turned queen":"🨟","white chess turned rook":"🨠","white chess turned bishop":"🨡","white chess turned knight":"🨢","white chess turned pawn":"🨣","black chess turned king":"🨤","black chess turned queen":"🨥","black chess turned rook":"🨦","black chess turned bishop":"🨧","black chess turned knight":"🨨","black chess turned pawn":"🨩","neutral chess turned king":"🨪","neutral chess turned queen":"🨫","neutral chess turned rook":"🨬","neutral chess turned bishop":"🨭","neutral chess turned knight":"🨮","neutral chess turned pawn":"🨯","white chess knight rotated two hundred twenty five degrees":"🨰","black chess knight rotated two hundred twenty five degrees":"🨱","neutral chess knight rotated two hundred twenty five degrees":"🨲","white chess king rotated two hundred seventy degrees":"🨳","white chess queen rotated two hundred seventy degrees":"🨴","white chess rook rotated two hundred seventy degrees":"🨵","white chess bishop rotated two hundred seventy degrees":"🨶","white chess knight rotated two hundred seventy degrees":"🨷","white chess pawn rotated two hundred seventy degrees":"🨸","black chess king rotated two hundred seventy degrees":"🨹","black chess queen rotated two hundred seventy degrees":"🨺","black chess rook rotated two hundred seventy degrees":"🨻","black chess bishop rotated two hundred seventy degrees":"🨼","black chess knight rotated two hundred seventy degrees":"🨽","black chess pawn rotated two hundred seventy degrees":"🨾","neutral chess king rotated two hundred seventy degrees":"🨿","neutral chess queen rotated two hundred seventy degrees":"🩀","neutral chess rook rotated two hundred seventy degrees":"🩁","neutral chess bishop rotated two hundred seventy degrees":"🩂","neutral chess knight rotated two hundred seventy degrees":"🩃","neutral chess pawn rotated two hundred seventy degrees":"🩄","white chess knight rotated three hundred fifteen degrees":"🩅","black chess knight rotated three hundred fifteen degrees":"🩆","neutral chess knight rotated three hundred fifteen degrees":"🩇","white chess equihopper":"🩈","black chess equihopper":"🩉","neutral chess equihopper":"🩊","white chess equihopper rotated ninety degrees":"🩋","black chess equihopper rotated ninety degrees":"🩌","neutral chess equihopper rotated ninety degrees":"🩍","white chess knight queen":"🩎","white chess knight rook":"🩏","white chess knight bishop":"🩐","black chess knight queen":"🩑","black chess knight rook":"🩒","black chess knight bishop":"🩓","xiangqi red general":"🩠","xiangqi red mandarin":"🩡","xiangqi red elephant":"🩢","xiangqi red horse":"🩣","xiangqi red chariot":"🩤","xiangqi red cannon":"🩥","xiangqi red soldier":"🩦","xiangqi black general":"🩧","xiangqi black mandarin":"🩨","xiangqi black elephant":"🩩","xiangqi black horse":"🩪","xiangqi black chariot":"🩫","xiangqi black cannon":"🩬","xiangqi black soldier":"🩭","ballet shoes":"🩰","one piece swimsuit":"🩱","briefs":"🩲","shorts":"🩳","thong sandal":"🩴","drop of blood":"🩸","adhesive bandage":"🩹","stethoscope":"🩺","yo yo":"🪀","kite":"🪁","parachute":"🪂","boomerang":"🪃","magic wand":"🪄","pinata":"🪅","nesting dolls":"🪆","ringed planet":"🪐","chair":"🪑","razor":"🪒","axe":"🪓","diya lamp":"🪔","banjo":"🪕","military helmet":"🪖","accordion":"🪗","long drum":"🪘","coin":"🪙","carpentry saw":"🪚","screwdriver":"🪛","ladder":"🪜","hook":"🪝","mirror":"🪞","window":"🪟","plunger":"🪠","sewing needle":"🪡","knot":"🪢","bucket":"🪣","mouse trap":"🪤","toothbrush":"🪥","headstone":"🪦","placard":"🪧","rock":"🪨","fly":"🪰","worm":"🪱","beetle":"🪲","cockroach":"🪳","potted plant":"🪴","wood":"🪵","feather":"🪶","anatomical heart":"🫀","lungs":"🫁","people hugging":"🫂","blueberries":"🫐","bell pepper":"🫑","olive":"🫒","flatbread":"🫓","tamale":"🫔","fondue":"🫕","teapot":"🫖"};
  const synonyms = {
    'astronomy':'telescope', 'astronomer':'telescope', 'baking':'birthday cake', 'baker':'bread',
    'sailor':'sailboat','sailing':'sailboat','chef':'cooking','cooking':'cooking','hiking':'mountain',
    'football':'american football','soccer':'soccer ball','pianist':'musical keyboard','piano':'musical keyboard',
    'violinist':'violin','ukulele':'guitar','cycling':'bicycle','biking':'bicycle','cyclist':'bicycle',
    'runner':'person running','running':'runner','dancer':'dancer','cat':'cat','dog':'dog','mountains':'mountain',
    'gardening':'seedling','gardener':'seedling','sunflower':'sunflower','honeybee':'honeybee','bee':'honeybee',
    'skier':'skier','skiing':'skier','ski':'skier','photographer':'camera','photography':'camera',
    'computer science':'personal computer','programmer':'personal computer','pilot':'airplane',
    'sewing':'sewing needle','knitter':'yarn','knitting':'yarn','potter':'amphora',
    'basketball':'basketball and hoop','baseball':'baseball','swimming':'swimmer','swimmer':'swimmer',
    'astronaut':'rocket','pizza':'slice of pizza','chess':'black chess pawn'
  };
  const glyphEntries = Object.entries(glyphNames).sort((a,b)=>b[0].length-a[0].length);
  const subjectTerms = new WeakMap();
  function separatedSubjects(text, manifest) {
    // A longer description such as “a birdhouse carved into a violin case”
    // can mention another known noun without asking for two drawings.
    if (hasObjectDetails(text)) return false;
    let terms = subjectTerms.get(manifest);
    if (!terms) {
      const names = [...Object.keys(glyphNames), ...Object.keys(synonyms).filter(key=>glyphNames[synonyms[key]])];
      for (const [id,data] of Object.entries(manifest.subjects)) names.push(id,data.label,...(aliases[id]||[]));
      terms = new Set();
      for (const name of names) {
        const word = normalize(name);
        for (const ending of ['', 's', 'es']) terms.add(word+ending);
      }
      subjectTerms.set(manifest,terms);
    }
    // Match each object's longest complete name, so “fishing pole and fish” counts once.
    // A word between two names can describe a placement the planner doesn't understand.
    const words = text.toLowerCase().replace(/['’]s\b/g,'').match(/\p{Extended_Pictographic}(?:\uFE0F|\p{Emoji_Modifier})?(?:\u200d\p{Extended_Pictographic}(?:\uFE0F|\p{Emoji_Modifier})?)*|[\p{L}\p{N}]+/gu) || [];
    let previousEnd = -1;
    for (let i=0; i<words.length; i++) {
      let end=words.length;
      while (end>i && !terms.has(words.slice(i,end).join(' '))) end--;
      if (end===i && /\p{Extended_Pictographic}/u.test(words[i])) end++;
      if (end===i) continue;
      if (previousEnd>=0 && i>previousEnd) return true;
      previousEnd=end;
      i=end-1;
    }
    return false;
  }
  function glyphIdea(text) {
    const direct = String(text).match(/\p{Extended_Pictographic}(?:\uFE0F|\p{Emoji_Modifier})?(?:\u200d\p{Extended_Pictographic}(?:\uFE0F|\p{Emoji_Modifier})?)*/u);
    if (direct) return {glyph:direct[0],label:glyphEntries.find(e=>e[1]===direct[0].replace(/\uFE0F/g,''))?.[0]||'Guest drawing'};
    if (hasObjectDetails(text)) return null;
    const subject=subjectWords(text);
    if (['music','music notes','musical notes'].includes(subject)) return {glyph:glyphNames['beamed eighth notes'],label:'Musical notes'};
    if (subject==='music note') return {glyph:glyphNames['musical note'],label:'Musical note'};
    const matches = subjectMatch(text,subject);
    for (const [alias,name] of Object.entries(synonyms)) {
      if (matches(alias) && glyphNames[name]) return {glyph:glyphNames[name],label:name};
    }
    for (const [name,glyph] of glyphEntries) {
      if (matches(name)) return {glyph,label:name};
    }
    return null;
  }
  // Each row is a named interest and the actual objects we can put in sand.
  // The first is the clearest reading; the others give the host a choice.
  const interestThemes = [
    ['bacteriophage|phage', ['phage', 'dna', 'microscope']],
    ['microbiology|microbiologist', ['microscope', 'phage']],
    ['genetics|geneticist|molecular biology', ['dna', 'microscope']],
    ['teacher|teaching|teaches|educator|classroom', ['books', 'classroom', 'pencil']],
    ['reading|reader|librarian|book club|literature', ['books', 'open book']],
    ['thailand|bangkok|thai architecture|thai heritage|thai temple', ['temple', 'thailand', 'elephant']],
    ['electric guitar|electric guitarist', ['electric_guitar', 'beamed eighth notes']],
    ['guitar|guitarist', ['guitar', 'beamed eighth notes']],
    ['violin|violinist|fiddle', ['violin', 'beamed eighth notes']],
    ['piano|pianist|keyboard player', ['musical keyboard', 'beamed eighth notes']],
    ['music|musician|songwriter|jazz', ['beamed eighth notes', 'guitar']],
    ['astronomy|astronomer|stargazing|stargazer|astrophotography|astrophotographer|night sky|telescope', ['telescope', 'ringed planet', 'comet']],
    ['spaceflight|space exploration|astronaut|rocketry', ['rocket', 'ringed planet']],
    ['cinema|filmmaking|filmmaker|movies|movie buff', ['clapper', 'clapper_alt', 'movie camera']],
    ['photography|photographer|taking photos', ['camera', 'camera with flash']],
    ['cooking|chef|cook|culinary', ['cooking', 'bowl with spoon']],
    ['baking|baker|bakes', ['bread', 'pie']],
    ['pie baking|thanksgiving baking', ['pumpkin_pie', 'chef_hat']],
    ['origami|paper folding', ['paper_crane']],
    ['caravanning|trailer camping', ['caravan']],
    ['gardening|gardener|growing plants|houseplants|horticulture', ['seedling', 'potted plant']],
    ['birdwatching|birdwatcher|bird watching|birding', ['bird', 'feather']],
    ['hiking|hiker|backpacking', ['mountain', 'hiking boot']],
    ['camping|camper', ['tent', 'camping']],
    ['skiing|skier', ['skier', 'mountain']],
    ['sailing|sailor', ['sailboat', 'anchor']],
    ['fishing|angler', ['fishing pole and fish', 'fish']],
    ['cycling|cyclist|biking', ['bicycle']],
    ['tennis', ['tennis racquet and ball']],
    ['golf|golfer|golfing', ['flag in hole', 'golfer']],
    ['painting|painter|watercolor|watercolour', ['artist palette', 'lower left paintbrush']],
    ['knitting|knitter|crochet', ['ball of yarn']],
    ['pottery|potter|ceramics', ['amphora']],
    ['programming|programmer|coding|software development', ['personal computer', 'wired keyboard']],
    ['dancing|dancer|dance', ['dancer']],
    ['film reel', ['clapper_alt']],
    ['dinosaur|paleontology|paleontologist', ['trex', 'raptor']],
    ['chess', ['black chess knight', 'black chess rook', 'black chess pawn']]
  ];
  const interestLabels = {'beamed eighth notes':'Musical notes', 'cooking':'Frying pan',
    'lower left paintbrush':'Paintbrush', 'flag in hole':'Golf flag', 'artist palette':'Artist’s palette',
    'personal computer':'Laptop', 'tennis racquet and ball':'Tennis racquet and ball'};

  // Keep combining marks in names and segment Thai even when a bio has no spaces.
  let thaiWords;
  function keptWords(text) {
    const clean = text.normalize('NFKC').toLowerCase().replace(/['’]s\b/gu, '').replace(/[^\p{L}\p{M}\p{N}]+/gu, ' ');
    if (/\p{Script=Thai}/u.test(clean) && typeof Intl.Segmenter === 'function') {
      thaiWords ||= new Intl.Segmenter('th',{granularity:'word'});
      return [...thaiWords.segment(clean)].filter(part => part.isWordLike).map(part => part.segment);
    }
    return clean.trim().split(/\s+/u).filter(Boolean);
  }
  function interestPlural(word) {
    if (!/^\p{Script=Latin}+$/u.test(word)) return word;
    if (/[^aeiou]y$/u.test(word)) return word.slice(0,-1)+'ies';
    return word+(/(?:s|x|z|ch|sh)$/u.test(word) ? 'es' : 's');
  }
  // A biography often names the person doing an activity. Keep these
  // equivalents narrow: someone can like astronomy without taking photos.
  const activities = new Map();
  for (const [activity, person] of Object.entries({
    botany:'botanist', teaching:'teacher', hiking:'hiker', astronomy:'astronomer',
    photography:'photographer', gardening:'gardener', guitar:'guitarist', music:'musician',
    microbiology:'microbiologist', genetics:'geneticist'
  })) {
    activities.set(person,activity);
    activities.set(interestPlural(person),activity);
  }
  const activityWord = word => activities.get(word) || word;
  function keptInterestIdeas(interest, kept) {
    const positive = [], negative = [];
    const boundaries = /[,;.!?\n]|\b(?:but|however|yet)\b|แต่|\band\s+(?=(?:(?:he|she|they|i)\s+)?(?:likes?|loves?|enjoys?|collects?|studies|plays?)\b)/iu;
    for (const clause of interest.replace(/\bnot (?:only|just)\b/giu,'').split(boundaries)) {
      const denied = /\b(?:not|never|no|without|instead of|rather than|avoid(?:s|ing)?|isn['’]t|doesn['’]t|don['’]t|dislikes?|hates?)\b|ไม่/u.exec(clause.toLowerCase());
      positive.push(...keptWords(denied ? clause.slice(0,denied.index) : clause), '');
      if (denied) negative.push(...keptWords(clause.slice(denied.index+denied[0].length)), '');
    }
    function position(words, phrase) {
      if (!phrase.length) return Infinity;
      const index = words.findIndex((_,i) => phrase.every((word,j) => {
        const actual = words[i+j];
        return actual===word || (actual && j===phrase.length-1 &&
          (interestPlural(actual)===word || interestPlural(word)===actual));
      }));
      return index<0 ? Infinity : index;
    }
    const groups = new Map(), ideas = [];
    const positiveActivities = positive.map(activityWord);
    for (const entry of kept) {
      if (!entry?.id || typeof entry.label !== 'string') continue;
      const name = keptWords(entry.label), key = name.join(' ');
      if (!key) continue;
      const group = groups.get(key) || new Map();
      group.set(entry.id,entry); groups.set(key,group);
    }
    for (const [key, group] of groups) {
      const name = key.split(' '), named = position(positive,name);
      // A more general positive tag cannot override an explicitly rejected
      // subject, e.g. “likes botany but not oak” for the Meadow oak.
      if (Number.isFinite(position(negative,name)) ||
          (!Number.isFinite(named) && Number.isFinite(position(negative,name.slice(-1))))) continue;
      const matches = [];
      for (const {id,label,interests} of group.values()) {
        const tags = (Array.isArray(interests) ? interests : [interests])
          .filter(value=>typeof value==='string').flatMap(value=>value.split(','));
        const hits = tags.map(keptWords).map(tag=>({at:position(positiveActivities,tag.map(activityWord)),length:tag.length}))
          .filter(hit=>Number.isFinite(hit.at));
        matches.push({id,label,hits});
      }
      const candidates = [];
      for (const item of matches) {
        // A shared label or tag cannot choose between two different drawings.
        const unique = item.hits.filter(hit=>!matches.some(m=>m!==item &&
          m.hits.some(other=>other.at===hit.at && other.length>=hit.length)));
        const first = Math.min(group.size===1 ? named : Infinity,...unique.map(hit=>hit.at));
        if (Number.isFinite(first)) candidates.push({id:item.id,label:item.label,first});
      }
      if (candidates.length===1) ideas.push(candidates[0]);
    }
    return ideas.sort((a,b)=>a.first-b.first).map(({id,label})=>({id,label}));
  }

  function interestIdeas(interest, manifest, kept = []) {
    if (typeof interest !== 'string' || !interest.trim()) return [];
    const subjects = manifest?.subjects || {};
    const native = {preferredSubjects:manifest?.preferredSubjects,subjects:Object.fromEntries(Object.entries(subjects).map(([id, value]) =>
      [id, {label:typeof value === 'string' ? value : value.label}]))};
    const choices = new Map();
    function offer(item, rank) {
      if (!item) return;
      const existing = choices.get(item.id);
      if (!existing || rank < existing.rank) choices.set(item.id, {item, rank});
    }
    function symbol(glyph, name) {
      return {id:'symbol-' + Array.from(glyph, c => c.codePointAt(0).toString(16)).join('-'),
        label:interestLabels[name] || name.charAt(0).toUpperCase() + name.slice(1), glyph};
    }
    function idea(name) {
      if (name === 'open book' && native.subjects.books_open) name = 'books_open';
      name = preferredSubject(name, native);
      if (Object.hasOwn(native.subjects, name)) return {id:name, label:native.subjects[name].label};
      if (Object.hasOwn(glyphNames, name)) return symbol(glyphNames[name], name);
    }
    if (Array.isArray(kept) && kept.length) for (const item of keptInterestIdeas(interest,kept)) offer(item,-1);
    // Separate interests before ranking. An explicitly stated second hobby
    // comes ahead of extra drawings suggested by the first hobby.
    for (const raw of interest.replace(/\bt\.\s*rex/giu, 't rex').split(/[,;.!?]|\b(?:and|but|also)\b/iu)) {
      const positive = raw.replace(/\b(?:not only|not just)\b/giu,'')
        .split(/\b(?:not|never|isn['’]t|doesn['’]t|don['’]t|dislikes?|hates?)\b/iu)[0];
      const words = normalize(positive);
      for (const match of positive.matchAll(/\p{Extended_Pictographic}(?:\uFE0F|\p{Emoji_Modifier})?(?:\u200d\p{Extended_Pictographic}(?:\uFE0F|\p{Emoji_Modifier})?)*/gu)) {
        const result = glyphIdea(match[0]);
        offer(symbol(result.glyph, result.label), 0);
      }
      if (!words) continue;
      for (const [terms, drawings] of interestThemes) {
        if (terms.split('|').some(term => includesPhrase(words, term))) {
          drawings.forEach((name, index) => offer(idea(name), index));
        }
      }
      const direct = catalogIdea(words, native);
      // Hunt is the family's name drawing. A mention of hunting or a guest's
      // surname does not make that crest an interest.
      if (direct && (direct !== 'hunt' || words === 'hunt' || includesPhrase(words, 'family name'))) {
        offer({id:direct,label:native.subjects[direct].label}, 0);
      }
      for (const [term, name] of Object.entries(synonyms)) {
        if (includesPhrase(words, term)) offer(idea(name), 1);
      }
      // Accept the literal name of any other drawable symbol. Requiring the
      // whole object phrase keeps e.g. "knot theory" from becoming a rope.
      const object = words.replace(/^.*?\b(?:collects?|enjoys?|loves?|likes?|plays?|studies|interested in)\s+/u, '')
        .replace(/^(?:a|an|the)\s+/u, '');
      const exact = [object, object.replace(/es$/, ''), object.replace(/s$/, '')]
        .find(name => Object.hasOwn(glyphNames, name));
      if (exact && !direct) offer(idea(exact), 0);
    }
    return [...choices.values()].sort((a, b) => a.rank - b.rank).map(choice => choice.item);
  }

  function musicGuest(people, subject, manifest) {
    // The two editors encode phone symbols differently; use the Unicode code point.
    const id=String(subject).replace(/^glyph-/, 'symbol-');
    const guitar=['guitar','guitar_silhouette','electric_guitar','guitar_note','guitar_books','symbol-1f3b8'];
    const notes=['symbol-2669','symbol-266a','symbol-266b','symbol-266c','symbol-1f3b5','symbol-1f3b6','symbol-1f3bc'];
    if (!guitar.includes(id) && !notes.includes(id)) return;
    const candidates=people.map(person=>({person,ideas:interestIdeas(guestInterest(person),manifest).map(idea=>idea.id)}));
    const preferred = id==='electric_guitar' ? candidates.filter(p=>p.ideas.includes(id)) : [];
    const related = preferred.length ? preferred : candidates.filter(p=>p.ideas.some(idea=>
      guitar.includes(idea) || (notes.includes(id) && notes.includes(idea))));
    return related.length===1 ? related[0].person : undefined;
  }
  function outline(mask, n) {
    // Directed grid edges keep each black region on the same side of its outlines.
    const edges = new Map(), stride=n+1;
    function add(a,b){if(!edges.has(a))edges.set(a,[]);edges.get(a).push(b)}
    for(let y=0;y<n;y++)for(let x=0;x<n;x++){
      if(!mask[y*n+x])continue;
      const a=y*stride+x,b=a+1,c=b+stride,d=a+stride;
      if(!y||!mask[(y-1)*n+x])add(a,b);
      if(x===n-1||!mask[y*n+x+1])add(b,c);
      if(y===n-1||!mask[(y+1)*n+x])add(c,d);
      if(!x||!mask[y*n+x-1])add(d,a);
    }
    const lines=[];
    while(edges.size) {
      const start=edges.keys().next().value;
      let cur=start, p=[];
      do {
        p.push([cur%stride,Math.floor(cur/stride)]);
        const choices=edges.get(cur);
        if(!choices)break;
        const next=choices.pop(); if(!choices.length)edges.delete(cur); cur=next;
      }while(cur!==start);
      if(p.length<12)continue;
      p.push(p[0]);
      let area=0;
      for(let i=1;i<p.length;i++)area+=p[i-1][0]*p[i][1]-p[i][0]*p[i-1][1];
      if(Math.abs(area)<34)continue;
      // Round pixel staircase corners a little before they reach the ball.
      const m=p.length-1, smooth=[];
      for(let i=0;i<m;i+=2){
        const a=p[(i+m-1)%m],b=p[i],c=p[(i+1)%m];
        smooth.push([(a[0]+2*b[0]+c[0])/4,(a[1]+2*b[1]+c[1])/4]);
      }
      smooth.push(smooth[0]);lines.push({line:smooth, area:Math.abs(area)});
    }
    return lines.sort((a,b)=>b.area-a.area);
  }
  function glyphStrokes(glyph) {
    const n=64, c=document.createElement('canvas');c.width=c.height=n;
    const ctx=c.getContext('2d',{willReadFrequently:true});
    ctx.font='50px "Apple Color Emoji","Segoe UI Emoji","Noto Color Emoji",sans-serif';
    ctx.textAlign='center';ctx.textBaseline='middle';ctx.fillText(glyph,32,34);
    const pixels=ctx.getImageData(0,0,n,n).data, mask=new Uint8Array(n*n), dark=new Uint8Array(n*n);
    let lo=255,hi=0;
    for(let i=0;i<mask.length;i++)if(pixels[4*i+3]>130){
      mask[i]=1;const lum=.299*pixels[4*i]+.587*pixels[4*i+1]+.114*pixels[4*i+2];lo=Math.min(lo,lum);hi=Math.max(hi,lum);
    }
    // An inset contour gives broad, solid shapes some texture in real sand.
    const inner=new Uint8Array(mask.length);
    for(let y=4;y<n-4;y++)for(let x=4;x<n-4;x++){
      const k=y*n+x;inner[k]=mask[k]&&[-4,4,-4*n,4*n,-3*n+3,3*n-3,-3*n-3,3*n+3].every(d=>mask[k+d]);
    }
    let paths=outline(mask,n).slice(0,4);
    if(hi-lo>35){
      for(let i=0;i<mask.length;i++)dark[i]=mask[i] && (.299*pixels[4*i]+.587*pixels[4*i+1]+.114*pixels[4*i+2]<lo+(hi-lo)*.36);
      const details=outline(dark,n).filter(p=>p.area>65 && p.area < (paths[0]?.area||0)*.65).slice(0,4);
      paths=paths.concat(details.length?details:outline(inner,n).slice(0,2));
    } else paths=paths.concat(outline(inner,n).slice(0,2));
    if(!paths.length)throw Error('This device could not render that symbol. Use the sketch pad to draw it.');
    const points=paths.flatMap(p=>p.line), xs=points.map(p=>p[0]),ys=points.map(p=>p[1]),
      cx=(Math.min(...xs)+Math.max(...xs))/2,cy=(Math.min(...ys)+Math.max(...ys))/2,
      radius=Math.max(...points.map(p=>Math.hypot(p[0]-cx,p[1]-cy)));
    return paths.map(p=>p.line.map(([x,y])=>[(x-cx)*.89/radius,(cy-y)*.89/radius]));
  }
  // Work with the guest's actual straight segments after smoothing the touch
  // samples. Group consecutive segments so separated parts of long strokes
  // can be ruled out without comparing every edge on the two lines.
  function strokeBlocks(ring, edgeCount) {
    const blocks=[];
    for(let start=0;start<edgeCount;start+=16){
      const end=Math.min(edgeCount,start+16);
      let left=Infinity, right=-Infinity, bottom=Infinity, top=-Infinity;
      for(let i=start;i<=end;i++){
        const [x,y]=ring[i%ring.length];
        left=Math.min(left,x); right=Math.max(right,x);
        bottom=Math.min(bottom,y); top=Math.max(top,y);
      }
      blocks.push({start,end,left,right,bottom,top});
    }
    return blocks;
  }
  function closestStrokeEdges(a, b, blocksA, blocksB, from, best) {
    if(best?.d===0)return best;
    function keep(i,u,j,v,d) {
      if(!best || d<best.d)best={from,i:(i+u)%a.length,j:(j+v)%b.length,d};
    }
    function project(p,q,dx,dy,len) {
      return len ? clamp(((p[0]-q[0])*dx+(p[1]-q[1])*dy)/len,0,1) : 0;
    }
    for(const groupA of blocksA)for(const groupB of blocksB){
      const xGap=Math.max(0,groupA.left-groupB.right,groupB.left-groupA.right);
      const yGap=Math.max(0,groupA.bottom-groupB.top,groupB.bottom-groupA.top);
      if(best && xGap*xGap+yGap*yGap>=best.d)continue;
      for(let i=groupA.start;i<groupA.end;i++){
        const p=a[i], p1=a[(i+1)%a.length], dx=p1[0]-p[0], dy=p1[1]-p[1], pp=dx*dx+dy*dy;
        for(let j=groupB.start;j<groupB.end;j++){
          const q=b[j], q1=b[(j+1)%b.length], ex=q1[0]-q[0], ey=q1[1]-q[1], qq=ex*ex+ey*ey;
          const rx=q[0]-p[0], ry=q[1]-p[1], cross=dx*ey-dy*ex;
          if(cross){
            const u=(rx*ey-ry*ex)/cross, v=(rx*dy-ry*dx)/cross;
            if(u>=0 && u<=1 && v>=0 && v<=1){
              keep(i,u,j,v,0);
              return best;
            }
          }
          // For disjoint or collinear segments the nearest pair includes an
          // endpoint. This also handles the single-point entry from the rim.
          for(let end=0;end<2;end++){
            const first=end?p1:p, second=end?q1:q;
            const v=project(first,q,ex,ey,qq), u=project(second,p,dx,dy,pp);
            keep(i,end,j,v,(q[0]+v*ex-first[0])**2+(q[1]+v*ey-first[1])**2);
            keep(i,u,j,end,(p[0]+u*dx-second[0])**2+(p[1]+u*dy-second[1])**2);
          }
          if(best.d===0)return best;
        }
      }
    }
    return best;
  }
  function manageStrokes(strokes,entry,{joinEdges=false,pointLimit=Infinity,finish=path=>path}={}){
    // The ball cannot lift. Join nearby lines and retrace each connection on the way out,
    // so the road out of a picture does not make a second scar across it.
    const rings=[[entry]], edgeCounts=[1];
    for(const line of strokes.filter(s=>s.length>1)){
      const closed=dist(line[0],line.at(-1))<.006;
      rings.push(closed?line.slice(0,-1):line.concat(line.slice(1,-1).reverse()));
      edgeCounts.push(line.length-1); // skip the duplicate return along open lines
    }
    const tooDetailed='This sketch has too much detail for one drawing. Try fewer strokes.';
    if(Number.isFinite(pointLimit)){
      // Even after removing zero-length joins, every original stroke edge
      // must be walked. Reject an impossible route before searching for joins.
      let minimum=1;
      for(const ring of rings)for(let i=0;i<ring.length;i++){
        if(dist(ring[i],ring[(i+1)%ring.length])>1e-8)minimum++;
      }
      if(minimum>pointLimit)throw Error(tooDetailed);
    }
    const blocks=joinEdges && rings.map((ring,i)=>strokeBlocks(ring,edgeCounts[i]));
    const sample=!joinEdges && rings.map(ring=>{
      const step=Math.max(1,Math.floor(ring.length/96)), result=[];
      for(let i=0;i<ring.length;i+=step)result.push(i);
      if(result.at(-1)!==ring.length-1)result.push(ring.length-1);
      return result;
    });
    const links=rings.map(()=>new Map()), cuts=rings.map(()=>new Set()), pending=new Set(rings.keys());
    pending.delete(0);
    const best=new Map();
    let current=0;
    while(pending.size){
      for(const target of pending){
        let link=best.get(target);
        if(joinEdges){
          link=closestStrokeEdges(rings[current],rings[target],blocks[current],blocks[target],current,link);
        } else for(const i of sample[current])for(const j of sample[target]){
          const a=rings[current][i],b=rings[target][j],dx=a[0]-b[0],dy=a[1]-b[1],d=dx*dx+dy*dy;
          if(!link||d<link.d)link={from:current,i,j,d};
        }
        best.set(target,link);
      }
      let closest=null;
      for(const target of pending)if(closest===null||best.get(target).d<best.get(closest).d)closest=target;
      const link=best.get(closest),parent=links[link.from];
      if(!parent.has(link.i))parent.set(link.i,[]);
      if(!Number.isInteger(link.i))cuts[link.from].add(link.i);
      if(!Number.isInteger(link.j))cuts[closest].add(link.j);
      parent.get(link.i).push([closest,link.j]);pending.delete(closest);current=closest;
    }
    const order=rings.map((ring,k)=>cuts[k].size ? [...ring.keys(),...cuts[k]].sort((a,b)=>a-b) : null);
    const result=[], inserted=[];
    function walk(index,start){
      const ring=rings[index], stops=order[index], count=stops?.length || ring.length;
      const begin=stops?stops.indexOf(start):start;
      const first=result.length;
      for(let n=0;n<count;n++){
        const ordinal=(begin+n)%count, at=stops?stops[ordinal]:ordinal;
        const i=Math.floor(at), t=at-i, a=ring[i], b=ring[(i+1)%ring.length];
        const point=t ? [a[0]+t*(b[0]-a[0]),a[1]+t*(b[1]-a[1])] : a;
        if(t){
          const end=t<.5?a:b;
          inserted.push({point,end,offset:dist(point,end)});
        }
        result.push(point);
        for(const [child,j] of links[index].get(at)||[]){walk(child,j);result.push(point);}
      }
      result.push(result[first]);
    }
    walk(0,0);
    // The fitted ring and the Mini also limit the interpolated motor path.
    // Let the destination check its actual export before accepting a join.
    const tryFit=path=>path.length<=pointLimit ? finish(path) : null;
    let accepted=tryFit(result);
    if(accepted)return accepted;

    // Near the player's limit, omit redundant stops at touching strokes.
    // If a drawing still overflows, move the cheapest fractional joins back
    // to original vertices one at a time. Every finger stroke stays intact.
    const moved=new Map();
    function compact(){
      const path=[];
      for(const original of result){
        const point=moved.get(original) || original;
        if(!path.length || dist(point,path.at(-1))>1e-10)path.push(point);
      }
      return path;
    }
    accepted=tryFit(compact());
    for(const cut of inserted.sort((a,b)=>a.offset-b.offset)){
      if(accepted)return accepted;
      moved.set(cut.point,cut.end);
      accepted=tryFit(compact());
    }
    if(accepted)return accepted;
    // At a hard travel limit even the choice of which strokes to connect
    // matters. Keep a previously playable drawing if its vertex route fits.
    if(joinEdges){
      accepted=tryFit(manageStrokes(strokes,entry));
      if(accepted)return accepted;
    }
    throw Error(tooDetailed);
  }
  function sketchStroke(points) {
    const p=points.filter((v,i)=>!i||dist(v,points[i-1])>.001);
    if(p.length<2)return [];
    // Ramer–Douglas–Peucker suppresses touch jitter and preserves intentional corners.
    const tol2=.012**2, keep=new Uint8Array(p.length);
    keep[0]=keep[p.length-1]=1;
    const pending=[[0,p.length-1]];
    while(pending.length){
      const [start,end]=pending.pop();
      const a=p[start],b=p[end],dx=b[0]-a[0],dy=b[1]-a[1],d2=dx*dx+dy*dy;
      let max=0,found=-1;
      for(let i=start+1;i<end;i++){
        const t=d2?clamp(((p[i][0]-a[0])*dx+(p[i][1]-a[1])*dy)/d2,0,1):0;
        const d=(p[i][0]-a[0]-t*dx)**2+(p[i][1]-a[1]-t*dy)**2;
        if(d>max){max=d;found=i;}
      }
      if(max>=tol2){
        keep[found]=1;
        pending.push([start,found],[found,end]);
      }
    }
    return p.filter((_,i)=>keep[i]);
  }
  function fromXY(xys, pointLimit=Infinity) {
    if(xys.length<2)throw Error('Draw a longer stroke first.');
    const out=[];let prev=null,theta=null;
    function add(x,y){
      const r=Math.hypot(x,y),a=r>1e-8?Math.atan2(y,x):theta||0;
      const next=theta===null?a:theta+shortTurn(a-theta),radius=clamp(r,.02,1);
      if(theta!==null&&Math.min(radius,out.at(-1)[1])<.06){
        const steps=Math.ceil(Math.abs(next-theta)/.12),start=out.at(-1)[1];
        for(let i=1;i<steps;i++)out.push([theta+(next-theta)*i/steps,start+(radius-start)*i/steps]);
      }
      theta=next;out.push([theta,radius]);
    }
    for(const p of xys){
      if(prev){const n=Math.ceil(dist(prev,p)/.018);
        for(let i=1;i<=n;i++){
          add(prev[0]+(p[0]-prev[0])*i/n,prev[1]+(p[1]-prev[1])*i/n);
          if(out.length>pointLimit)return null;
        }
      }else add(...p);
      prev=p;
    }
    return out;
  }
  function pathForStrokes(strokes, slot, options) {
    const [cx,cy]=slot.center, r=slot.radius, a=slot.angle, entry=[Math.cos(a),Math.sin(a)];
    return manageStrokes(strokes,entry,{...options,finish(points){
      const p=points.map(([x,y])=>[cx+r*x,cy+r*y]);
      return fromXY([entry,...p,entry],options?.pointLimit);
    }});
  }
  function slotMotif(source,slot){
    const xy=source.map(([t,r])=>[(r*Math.cos(t)-slot.center[0])/slot.radius,(r*Math.sin(t)-slot.center[1])/slot.radius]);
    const start=xy.findIndex(p=>Math.hypot(...p)<=1.0001);
    return xy.slice(start,xy.length-start);
  }
  function pairedPath(idA,idB,relation,slot,index,manifest){
    function localPath(id){
      const source=manifest.subjects[id]?.paths[index];
      if(source)return [slotMotif(source,slot)];
      const code=id.slice(6).split('_').map(c=>parseInt(c,16));
      if(!id.startsWith('glyph-')||!code.length)throw Error('This pair cannot be drawn together yet.');
      return glyphStrokes(String.fromCodePoint(...code));
    }
    let anchors=[[-.44,0],[.44,0]],size=.48,tilt=0;
    if(relation==='above'||relation==='below')anchors=relation==='above'?[[0,.43],[0,-.43]]:[[0,-.43],[0,.43]];
    if(relation==='behind')anchors=[[.32,.27],[-.28,-.2]];
    if(relation==='lean'){anchors=[[.36,.08],[-.34,-.12]];size=.5;tilt=.25;}
    const strokes=[];
    for(const [j,id] of [idA,idB].entries()){
      const [cx,cy]=anchors[j],c=Math.cos(j===0?tilt:0),s=Math.sin(j===0?tilt:0);
      for(const stroke of localPath(id))strokes.push(stroke.map(([x,y])=>{
        const p=[cx+size*(c*x-s*y),cy+size*(s*x+c*y)];
        if(Math.hypot(...p)>1.0002)throw Error('This pair extends outside its place in the sand.');
        return p;
      }));
    }
    return pathForStrokes(strokes,slot);
  }
  function pathForPhoto(points,slot){
    const first=points[0], gate=slot.angle;
    const photoGate=Math.atan2(first[1],first[0]);
    if(slot.radius===1)return fromXY(points);
    // Approach the photo on the outer edge of its own area; a chord here would scar the face.
    const delta=shortTurn(photoGate-gate), n=Math.max(1,Math.ceil(Math.abs(delta)/.05));
    const arc=Array.from({length:n+1},(_,i)=>[Math.cos(gate+delta*i/n),Math.sin(gate+delta*i/n)]);
    const region=[...arc,...points,...arc.reverse()].map(([x,y])=>[slot.center[0]+slot.radius*x,slot.center[1]+slot.radius*y]);
    const entry=[Math.cos(gate),Math.sin(gate)];
    return fromXY([entry,...region,entry]);
  }
  // Segments use unwrapped radians. Keep turns inside each segment; only translate whole turns on joins.
  function join(out,path){
    if(!path?.length)return;
    let off=0;
    if(out.length){
      const [end,er]=out.at(-1),[start,sr]=path[0], delta=shortTurn(start-end);
      if(Math.abs(er-1)>.015||Math.abs(sr-1)>.015)throw Error('A path is missing its entry on the rim.');
      for(let i=1,n=Math.ceil(Math.abs(delta)/.045);i<=n;i++)out.push([end+delta*i/n,1]);
      off=tau*Math.round((end+delta-start)/tau);
    }
    for(const [t,r] of path){if(!Number.isFinite(t)||!Number.isFinite(r)||r<0||r>1.00005)throw Error('This drawing extends beyond the table.');
      const last=out.at(-1);if(!last||Math.abs(last[0]-t-off)>.000001||Math.abs(last[1]-r)>.000001)out.push([t+off,Math.min(1,r)]);
    }
  }
  function buffer(path){
    if(path.length<2||path.length>12000)throw Error('This drawing is too detailed for the Mini. Try one fewer subject or a simpler sketch.');
    const data=new DataView(new ArrayBuffer(path.length*8));
    path.forEach(([t,r],i)=>{data.setFloat32(i*8,t,true);data.setFloat32(i*8+4,r,true)});
    return data.buffer;
  }
  return {alexInterest,guestInterest,musicGuest,splitRequest,parsePair,separatedSubjects,catalogIdea,wholeSubject,glyphIdea,interestIdeas,thanksgivingIdeas,thanksgivingPicker,slotMotif,glyphStrokes,pathForStrokes,pathForPhoto,manageStrokes,sketchStroke,normalize,join,buffer,pairedPath};
})();
