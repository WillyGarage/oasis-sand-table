'use strict';
(() => {
  const $=id=>document.getElementById(id), art=window.GuestArt;
  const blank=()=>['','',''];
  const freshRoster=()=>[
    {name:'Thomas',interest:'Bacteriophages',subject:'phage',on:true},
    {name:'Alex',interest:art.alexInterest,subject:'books',on:true},
    {name:'Lek',interest:'Thailand',subject:'temple',on:true}
  ];
  function stored(key,fallback){try{return JSON.parse(localStorage.getItem(key))||fallback}catch{return fallback}}
  function remember(key,value){try{localStorage.setItem(key,JSON.stringify(value))}catch{}}
  let roster=stored('oasis-guest-roster-v1',freshRoster());
  roster.forEach(p=>{p.interest=art.guestInterest(p)});
  let custom=stored('oasis-guest-art-v1',{}), tab='people', strokes=[], activeStroke=null, photo=null;
  let faceChoice=null, groupFaces=null, previewRequest=0;
  const displayFaces=window.guestFacePicker?.($('photo'), face=>{
    faceChoice=face; changePhotoChoice();
  }, choices=>{
    groupFaces=choices; changePhotoChoice();
  }) || (()=>{});
  function changePhotoChoice(){
    photo=null; $('soloSmile').value='original'; $('largerFaces').checked=$('spaceEyes').checked=$('groupHair').checked=$('savedDetails').checked=$('photoFringe').checked=false; invalidate(); preview();
  }
  let manifest, status=null, state=null, plan=null, activePlan=null, pendingSend=false, buildNumber=0, seenBusy=false, selectedTarget='auto';
  let reference=null;
  let preparedCenterName=null, localPreparedReceipt=null;
  const savedParts=[null,null,null];
  let peopleRevision=null, photoCompleted=stored('oasis-guest-full-photo-v1',null);
  const cap=s=>s?s[0].toUpperCase()+s.slice(1):'';
  const message=(id,s)=>{$(id).textContent=s||'';};
  const slug=s=>art.normalize(s).replace(/[^a-z0-9 ]/g,'').replace(/ +/g,'-').slice(0,20);
  const glyphId=g=>'glyph-'+Array.from(g).map(c=>c.codePointAt(0).toString(16)).join('_');
  const defaultPhotoTarget={center:[0,0],radius:1,angle:-Math.PI/2};
  function resolveIdea(text) {
    const catalog=art.catalogIdea(text,manifest); if(catalog)return catalog;
    const g=art.glyphIdea(text);
    if(g){const id=glyphId(g.glyph);return id.length<=40?id:'';}
    const words=' '+art.normalize(text)+' ';
    const person=roster.find(p=>p.subject&&words.includes(' '+art.normalize(p.name)+' '));
    return person?.subject||'';
  }
  function glyph(slug){
    if(!/^glyph-[0-9a-f_]+$/.test(slug))return '';
    try{return String.fromCodePoint(...slug.slice(6).split('_').map(x=>parseInt(x,16)))}catch{return ''}
  }
  const relationCode={beside:'s',above:'a',below:'b',behind:'h',lean:'l'};
  const relationLabel={beside:'beside',above:'above',below:'below',behind:'behind',lean:'leaning against'};
  function encodePart(id){
    if(manifest.subjects[id])return id;
    if(glyph(id))return 'u'+id.slice(6).split('_').map(h=>parseInt(h,16).toString(36)).join('-');
    throw Error('This combination needs two named drawings or symbols.');
  }
  function pairId(a,b,relation){
    const id='pair_'+relationCode[relation]+'_'+encodePart(a)+'__'+encodePart(b);
    if(id.length>40)throw Error('These two symbols have too many parts for one place. Try simpler symbols.');
    return id;
  }
  function decodePair(id){
    const m=id.match(/^pair_([sabhl])_(.+)__(.+)$/);
    if(!m)return null;
    function part(code){
      if(manifest.subjects[code])return code;
      if(!/^u[0-9a-z]+(?:-[0-9a-z]+)*$/.test(code))return '';
      return 'glyph-'+code.slice(1).split('-').map(n=>parseInt(n,36).toString(16)).join('_');
    }
    const a=part(m[2]),b=part(m[3]),relation=Object.keys(relationCode).find(k=>relationCode[k]===m[1]);
    return a&&b&&relation?{a,b,relation}:null;
  }
  function label(id){
    if(!id)return 'Empty';
    const pair=decodePair(id);
    if(pair)return label(pair.a)+' '+relationLabel[pair.relation]+' '+label(pair.b).toLowerCase();
    if(manifest.subjects[id])return manifest.subjects[id].label;
    if(custom[id])return custom[id].name;
    const g=glyph(id);if(g)return cap(art.glyphIdea(g)?.label||g);
    return cap(id.replace(/^(sketch|photo)-/,'').replace(/-[0-9a-z]{1,7}$/,'').replace(/[-_]/g,' '));
  }
  function keepCustom(name,source,points,kind){
    const simplified=points.map(line=>line.map(([x,y])=>[+x.toFixed(4),+y.toFixed(4)]));
    let hash=2166136261;
    for(const ch of JSON.stringify([name,source,simplified]))hash=Math.imul(hash^ch.charCodeAt(0),16777619);
    const id=kind+'-'+(slug(name)||'guest')+'-'+(hash>>>0).toString(36);
    // Re-previewing a drawing reuses its ID. Never discard a guest's chosen art or art on the table.
    custom={...stored('oasis-guest-art-v1',{}),...custom};
    custom[id]={name,source,points:simplified};
    const keep=new Set([id,...roster.map(p=>p.subject),...allSlots()]);
    for(const old of Object.keys(custom)){
      if(Object.keys(custom).length<=12)break;
      if(!keep.has(old))delete custom[old];
    }
    remember('oasis-guest-art-v1',custom);return id;
  }
  function allSlots(){return state?.known?[...state.slots]:blank()}
  const seatsKey='oasis-guest-places-v1';
  function seatOwners(saved=stored(seatsKey,null)){
    if(state?.known&&saved?.rev===state.rev&&saved.ids?.join(',')===state.slots.join(',')&&saved.names?.length===3)return [...saved.names];
    // A second phone can identify the unmodified starting order from its three unique drawings.
    const original=roster.filter(p=>p.on);
    if(!saved && state?.known && original.length===3 && new Set(state.slots).size===3 &&
        original.every((p,i)=>p.subject && state.slots[i]===p.subject))return original.map(p=>p.name);
    return null;
  }
  function rememberSeats(p,receipt){
    // The Mini increments its revision once more on finishing the accepted drawing.
    const rev=receipt.pending?String((Number(receipt.rev)+1)>>>0):receipt.rev;
    remember(seatsKey,{rev,ids:p.ids,names:p.names});
  }
  function mergePeople(shared){
    if(!Array.isArray(shared.people))throw Error('Unexpected guest list from the table.');
    peopleRevision=String(shared.rev);
    let changed=false;
    for(const p of shared.people){
      if(!p||typeof p.name!=='string'||typeof p.interest!=='string')continue;
      const interest=art.guestInterest(p);
      const local=roster.find(q=>art.normalize(q.name)===art.normalize(p.name));
      const portable=manifest.subjects[p.subject]||glyph(p.subject||'');
      const subject=portable?p.subject:(local?.interest===interest&&custom[local.subject]?local.subject:resolveIdea(interest));
      if(!local){roster.push({name:p.name,interest,subject,on:false});changed=true;}
      else if(local.subject!==subject||local.interest!==interest||local.name!==p.name){
        Object.assign(local,{name:p.name,interest,subject});changed=true;
      }
    }
    if(changed){
      remember('oasis-guest-roster-v1',roster);renderRoster();
      if(tab==='people'&&plan)invalidate();
    }
  }
  const themes=window.GuestThemes({
    context:()=>({manifest,state,plan,roster,tab,label,seatOwners,sending:pendingSend}),read,refresh,onError:s=>message('error',s)
  });
  const centerSelected=()=>tab==='center'||(tab==='photo'&&$('photoTarget').value==='center');
  const centerEffect='The Mini clears the center and draws the new picture inside the seven roofs.';
  const frameEffect='The Mini clears the outer ring and draws seven roofs. The existing center stays in the sand and is omitted from this preview.';
  const pencilEffect='The Mini follows the existing book to add the pencil. The book and seven roofs stay in the sand.';
  function centerHelp(kind){
    return kind==='frame'?frameEffect:kind==='book-pencil'?pencilEffect:centerEffect;
  }
  function showPrepared(name){
    const button=$('resumeCenter');
    button.textContent=name?'Start the prepared '+name:'Start the prepared drawing';
    const differentPhoto=tab==='photo' && $('file').files.length &&
      (!localPreparedReceipt || status?.receipt?.id!==localPreparedReceipt);
    button.hidden=!name || differentPhoto || !(name==='whole-table portrait' ? tab==='photo' && $('photoTarget').value==='full' : centerSelected()) || pendingSend;
  }
  const enabled=()=>manifest&&state?.partProtocol===2&&status&&!state.pending&&status.state==='idle'&&!status.fault&&status.homed&&!status.auto&&!status.queue?.length;
  const canNamePortrait=()=>tab==='photo' && !reference && $('photoMode').value!=='whole' &&
    ['full','center'].includes($('photoTarget').value);
  const inwardPicker=$('inwardPortrait');
  const canDrawInward=()=>!!inwardPicker && canNamePortrait() && $('photoTarget').value==='full' &&
    ($('photoMode').value==='one' || ($('photoMode').value==='group' && $('file').files.length>0)) && $('centerHead').checked;
  const inwardSelected=()=>canDrawInward() && inwardPicker.value!=='standard';
  async function loadInwardTools(){
    if(!window.GuestInwardPortrait)await import('./guest-inward-portrait.js?v=8');
  }
  const directPlan=p=>p?.mode==='center' || p?.mode==='inward';
  const canEnlargeTrio=()=>inwardSelected() && $('photoMode').value==='group' &&
    photo?.count===3 && photo.largerFaceContours && !$('photoName').value.trim();
  function trioHairContours() {
    if(!inwardSelected() || $('photoMode').value!=='group' || photo?.count!==3 || $('photoName').value.trim())return null;
    return canEnlargeTrio() && $('largerFaces').checked ? photo.largerHairContours : photo.hairContours;
  }
  function readyButtons(){
    if(inwardPicker)$('inwardField').hidden=!canDrawInward();
    $('centerHeadField').hidden=!canNamePortrait();
    $('headLabel').textContent=$('photoMode').value==='group' ? 'Close up on faces' : 'Head only';
    $('photoNameField').hidden=!canNamePortrait();
    $('largerFacesField').hidden=!canEnlargeTrio();
    $('groupHairField').hidden=!trioHairContours();
    $('spaceEyesField').hidden=!(canEnlargeTrio() && $('largerFaces').checked && photo.canSeparateEyes);
    $('savedDetailsField').hidden=!(inwardSelected() && $('photoMode').value==='one' && photo?.reviewedPortrait && $('soloSmile').value==='open');
    $('soloSmileField').hidden=!(inwardSelected() && $('photoMode').value==='one' && photo?.soloSmile);
    $('soloSmile').querySelector('option[value=open]').hidden=!photo?.soloSmile?.open;
    $('photoFringeField').hidden=!(inwardSelected() && $('photoMode').value==='one' && photo?.fringe &&
      ['engraved','quiet-engraved'].includes(inwardPicker.value) &&
      !($('savedDetails').checked && $('soloSmile').value==='open' && photo.reviewedPortrait));
    $('photoPartField').hidden=!(inwardSelected() && $('photoMode').value==='one' &&
      ['engraved','quiet-engraved'].includes(inwardPicker.value) && photo?.partedHair);
    const pair=canNamePortrait() && !inwardSelected() && $('photoTarget').value==='full' && $('photoMode').value==='group' &&
      $('centerHead').checked && !$('photoName').value.trim();
    const style=$('pairSmile').checked && photo?.smiles || photo;
    $('pairEyesField').hidden=!(pair && style?.pairEyePoints);
    $('pairSmileField').hidden=!(pair && photo?.smiles);
    $('previewButton').disabled=!manifest||!state||buildingPreview||pendingSend;
    $('useReference').disabled=$('previewButton').disabled;
    $('draw').disabled=pendingSend||!enabled()||!plan||plan.mode==='inward-draft'||state.rev!==plan.rev;
    themes.render();
    if(centerSelected())$('evolution').hidden=true;
  }
  function invalidate(preservePrepared){
    buildNumber++;previewRequest++;buildingPreview=false;plan=null;
    if(preservePrepared!==true)localPreparedReceipt=null;
    $('useReference').hidden=true;
    $('previewButton').removeAttribute('aria-busy');$('sourceFrame').inert=$('faceActions').inert=false;
    $('draw').disabled=true;showPrepared(preparedCenterName);
    message('error','');message('message','');if(manifest)show(null);
  }
  function chooseTab(name){
    tab=name;
    if(name!=='photo')endReference();
    if(tab==='center')$('photoTarget').value='center';
    document.querySelectorAll('[data-tab]').forEach(b=>b.setAttribute('aria-pressed',b.dataset.tab===tab));
    ['people','request','photo','center'].forEach(n=>$(n).hidden=n!==tab);
    invalidate();
  }
  function endReference(){
    if(!reference)return;
    reference=null;referenceLabels();targets();
  }
  function referenceLabels(){
    $('referenceSubject').hidden=!reference;
    $('referenceSubject').textContent=reference ? reference.name+(reference.guest?' for '+reference.guest.name:'') : '';
    $('photoTraceLabel').textContent=reference?'Tracing mode':'People in the photo';
    $('photoPlaceLabel').textContent=reference?'Guest place':'Size in the sand';
    $('photoCropHint').hidden=!!reference;
  }
  function renderRoster(){
    $('roster').replaceChildren();
    roster.forEach(p=>{
      const l=document.createElement('label'),c=document.createElement('input'),n=document.createElement('span'),i=document.createElement('small');
      l.className='person';c.type='checkbox';c.checked=p.on;n.textContent=p.name;i.textContent=p.interest;n.append(i);l.append(c,n);$('roster').append(l);
      c.onchange=()=>{
        if(c.checked&&roster.filter(q=>q.on).length>=3){c.checked=false;message('error','Choose up to three people at once.');return;}
        p.on=c.checked;remember('oasis-guest-roster-v1',roster);invalidate();};
    });
  }
  function targets(){
    $('freshRow').hidden=!state?.known;
    if(!state?.known)$('freshSand').checked=false;
    const ids=allSlots(), p=$('photoTarget').value;
    for(const [select,first,val] of [[$('target'),'Choose from the request','auto'],
      [$('photoTarget'),reference?'Choose a guest place…':'Whole table',reference?'':'full']]){
      select.replaceChildren(new Option(first,val));
      if(select===$('photoTarget')&&!reference)select.add(new Option('Center · keep the seven roofs','center'));
      ids.forEach((id,i)=>select.add(new Option(manifest.slots[i].label+' · '+label(id),String(i))));
    }
    $('target').value=selectedTarget;
    $('photoTarget').value=reference ? (reference.rev===state?.rev?p:'') : (p||'full');
    if(reference)reference.rev=state?.rev;
  }
  function findInScene(text,ids){
    const words=art.normalize(text), id=resolveIdea(text);
    // A place saved before the spread-wing drawing still answers to its earlier name.
    const original=id==='origami_crane' && ids.includes('paper_crane') ? art.catalogIdea(text,manifest,false) : '';
    const matches=ids.map((x,i)=>x&&(x===id||x===original||art.normalize(label(x))===words||x===slug(words))?i:-1).filter(i=>i!==-1);
    if(matches.length>1)throw Error('That subject appears twice. Choose its place below the request.');
    return matches.length?matches[0]:-1;
  }
  function namedPlace(guest,ids){
    const saved=stored(seatsKey,null),owners=seatOwners(saved);
    if(owners)return owners.indexOf(guest.name);
    // Older phones recorded only the artwork. Recognize the original roster
    // layout, but never treat one familiar subject in a changed scene as its owner.
    const original=roster.filter(p=>p.on);
    if(!saved&&ids.every((id,i)=>id===(original[i]?.subject||''))){
      const i=original.indexOf(guest);
      if(i>=0&&ids[i]&&ids.indexOf(ids[i])===ids.lastIndexOf(ids[i]))return i;
    }
    return -1;
  }
  function targetFor(req,ids){
    if(selectedTarget!=='auto')return Number(selectedTarget);
    if(req.from){
      const person=roster.find(p=>art.normalize(p.name)===art.normalize(req.from));
      const i=person?namedPlace(person,ids):findInScene(req.from,ids);
      if(i<0)throw Error('That subject is not in this scene. Choose its place below the request.');
      return i;
    }
    if(req.guest){
      const i=namedPlace(req.guest,ids);
      if(i>=0)return i;
    }
    const i=ids.indexOf('');
    if(i>=0)return i;
    throw Error('The three places are filled. Pick the subject to replace under “Place in the picture.”');
  }
  function bodyFor(id,i) {
    if(manifest.subjects[id])return manifest.subjects[id].paths[i];
    const pair=decodePair(id);
    if(pair)return art.pairedPath(pair.a,pair.b,pair.relation,manifest.slots[i],i,manifest);
    const g=glyph(id);
    if(g)return art.pathForStrokes(art.glyphStrokes(g),manifest.slots[i]);
    if(custom[id]?.source==='photo')return art.pathForPhoto(custom[id].points[0],manifest.slots[i]);
    if(custom[id])return art.pathForStrokes(custom[id].points,manifest.slots[i],
                        custom[id].source==='sketch-v2' ? {joinEdges:true,pointLimit:12000} : undefined);
    return null;
  }
  function sandPath(id,slot){
    const part=savedParts[slot];
    if(part&&part.id===id&&part.rev===state?.rev)return part.points;
    return bodyFor(id,slot);
  }
  async function fetchSandPaths(s){
    if(s.partProtocol!==2||!s.known||s.pending)return false;
    let loaded=false;
    await Promise.all(s.slots.map(async(id,i)=>{
      if(!id||manifest.subjects[id]||savedParts[i]?.rev===s.rev)return;
      try {
        const response=await read('/guest-part?'+new URLSearchParams({slot:i,rev:s.rev}));
        const bytes=new DataView(await response.arrayBuffer()),n=bytes.byteLength/8;
        if(!Number.isInteger(n)||n<2||n>12000)return;
        const points=[];
        for(let j=0;j<n;j++){
          const theta=bytes.getFloat32(j*8,true),rho=bytes.getFloat32(j*8+4,true);
          if(!Number.isFinite(theta)||!Number.isFinite(rho)||rho<0||rho>1)return;
          points.push([theta,rho]);
        }
        savedParts[i]={id,rev:s.rev,points};loaded=true;
      } catch { /* The scene may have changed while the phone was reading this part. */ }
    }));
    return loaded;
  }
  function draft(mode,ids,parts,heading,explanation){
    // Keep each native rim-to-rim component intact. Another phone can change one subject
    // while the table supplies the exact saved paths for the rest of the scene.
    const counts=mode==='photo'?null:ids.map((_,i)=>parts[i]?.length||0);
    const segments=parts.filter(Boolean);
    if(!segments.length)throw Error('Choose at least one subject.');
    const body=new Blob(segments.map(art.buffer),{type:'application/octet-stream'});
    const rendered=ids.map((id,i)=>parts[i]||(id&&state.known&&id===state.slots[i]?sandPath(id,i):null));
    return {mode,ids,counts,body,path:mode==='photo'?parts[0]:null,rendered,heading,explanation,rev:state.rev,
      names:(mode==='edit'&&seatOwners())||blank()};
  }
  function freshPeople(){
    const people=roster.filter(p=>p.on);
    if(!people.length)throw Error('Choose at least one person.');
    const ids=blank(),render=[];
    people.forEach((p,i)=>{
      const id=p.subject||resolveIdea(p.interest);
      if(!id)throw Error('There is no drawing for '+p.name+'’s idea yet. Open Suggestion to sketch it.');
      ids[i]=id;
    });
    const names=ids.map((_,i)=>people[i]?.name||'');
    if(state.known&&!$('freshSand').checked){
      const changes=ids.map((id,i)=>id!==state.slots[i]?i:-1).filter(i=>i>=0);
      if(!changes.length)throw Error('These subjects are already on the sand. Use Suggestion to change one.');
      if(changes.length===1&&ids[changes[0]]){
        const i=changes[0];return {...changeSlot(allSlots(),i,ids[i],bodyFor(ids[i],i)),names};
      }
    }
    people.forEach((p,i)=>{
      render[i]=sandPath(ids[i],i);
      if(!render[i])throw Error('Sketch '+p.name+'’s idea again on this device.');
    });
    return {...draft('fresh',ids,render,'Draw for the room','Clears the whole table, then draws these subjects.'),names};
  }
  function requestPlan(picked){
    const text=$('idea').value.trim(), req=art.splitRequest(text,roster), ids=allSlots();
    if(picked){
      const guest=selectedTarget==='auto' ? req.guest : null;
      if(selectedTarget==='auto' && ((req.recipient && !guest) || art.splitRequest(req.to,roster).recipient))
        throw Error('Choose a place for this Thanksgiving drawing.');
      return {...requestAt(ids,targetFor(req,ids),picked.id,guest),keepSketch:true};
    }
    if(!text&&!strokes.length)throw Error('Enter a suggestion or draw a sketch first.');
    let index, id;
    const native=art.catalogIdea(req.to,manifest);
    const pair=art.wholeSubject(req.to,native,manifest) ? null : art.parsePair(req.to);
    const usingSketch=strokes.length&&$('sketch').open;
    const list=req.to.split(/,|\s+and\s+/i).map(s=>s.trim()).filter(Boolean);
    const offerReference=()=> {
      $('useReference').hidden=false;
      $('sketch').open=true;
      throw Error('Sketch “'+req.to+'” or choose a reference picture.');
    };
    if(!usingSketch&&list.length>=3){
      if((req.guest || selectedTarget!=='auto') && (!req.recipient || req.guest))offerReference();
      if(list.length!==3||req.from||list.some(s=>art.parsePair(s)))throw Error('Use up to three subjects for a new scene, or change one place at a time.');
      const next=list.map(resolveIdea),paths=[];
      if(next.some(id=>!id))throw Error('One of those subjects needs a sketch. Add it separately using the sketch pad.');
      next.forEach((id,i)=>{paths[i]=bodyFor(id,i);if(!paths[i])throw Error('Sketch this guest’s subject on this device first.');});
      return draft('fresh',next,paths,'Draw this scene','Clears the whole table and draws the three requested subjects.');
    }
    if(usingSketch){
      const lines=strokes.map(art.sketchStroke).filter(p=>p.length>=2);
      if(!lines.length)throw Error('Draw a longer stroke first.');
      id=keepCustom(req.to||'Guest sketch','sketch-v2',lines,'sketch');
      const match=roster.find(p=>!p.subject&&art.normalize(p.interest)===art.normalize(req.to));
      if(match){match.subject=id;remember('oasis-guest-roster-v1',roster);}
    } else if(pair){
      const a=resolveIdea(pair.left), b=resolveIdea(pair.right);
      if(!a||!b){
        if(pair.left && pair.right && (!req.recipient || req.guest))offerReference();
        $('sketch').open=true;
        throw Error('I couldn’t match “'+(!a?pair.left:pair.right)+'”. Sketch the two subjects together or use a different word.');
      }
      if(!req.from&&!req.guest&&selectedTarget==='auto'){
        const anchor=findInScene(pair.right,ids);
        if(anchor>=0)index=anchor;
      }
      if(a==='guitar'&&b==='books'&&pair.relation==='lean')id='guitar_books';
      else id=pair.relation==='right'?pairId(b,a,'beside'):pairId(a,b,pair.relation);
    } else id=native || resolveIdea(req.to);
    if(!id){
      if(!strokes.length)$('sketch').open=true;
      if(req.to && list.length===1 && !/[;,]/.test(req.to) && (!req.recipient||req.guest)){
        offerReference();
      }
      throw Error('Sketch “'+req.to+'” below, or add an emoji to your request.');
    }
    let guest=req.guest;
    if(index===undefined && !req.from && !req.recipient && selectedTarget==='auto'){
      const owners=seatOwners(), attending=roster.filter(p=>p.on || owners?.includes(p.name));
      guest=art.musicGuest(attending,id,manifest);
      if(guest){
        const known=namedPlace(guest,ids), starter=attending.indexOf(guest);
        if(known>=0)index=known;
        else if(starter<ids.length && !ids[starter] && !owners?.[starter])index=starter;
      }
    }
    index??=targetFor(req,ids);
    return requestAt(ids,index,id,guest);
  }
  function requestAt(ids,index,id,guest,points=bodyFor(id,index)){
    const p=changeSlot(ids,index,id,points);
    if(guest&&!p.names[index]&&!p.names.includes(guest.name))p.names[index]=guest.name;
    return p;
  }
  function changeSlot(ids,index,id,points){
    const existing=ids[index], fresh=!state.known;
    if(!fresh&&id===existing)throw Error(label(id)+' is already in that place.');
    if(!points?.length)throw Error('This subject needs a drawing on this device before it can be added.');
    ids[index]=id;const rendered=[];rendered[index]=points;
    const heading=existing?'Replace '+label(existing):'Draw '+label(id);
    const explanation=fresh?'Clears the whole table to start a new scene.':existing?
      'Clears the whole table with the fine spiral, then redraws the scene with '+label(id)+' in place of '+label(existing)+'.':
      'Draws '+label(id)+' in the empty '+manifest.slots[index].label.toLowerCase()+' place. The other subjects stay on the sand.';
    return draft(fresh?'fresh':'edit',ids,rendered,heading,explanation);
  }
  async function centerPlan(kind,points,title){
    const player=window.GuestCenterPlay,routes=window.GuestCenterRoutes;
    if(!player||!routes)throw Error('The center drawing tools could not load. Refresh this page to try again.');
    const frame=kind==='frame';
    const snapshot=Object.freeze(await (frame?player.preview('frame'):player.preview()));
    if(kind==='book-pencil' && snapshot.center!=='book')throw Error(snapshot.center==='book-pencil'?
      'The pencil is already on the open book.':'Draw the open book in the center before adding the pencil.');
    const [route,border]=frame ? [await routes.frame(snapshot.theta),null] : await Promise.all([
      kind==='photo'?routes.photo(points):routes.stock(kind),routes.border()
    ]);
    return {mode:'center',kind,snapshot,text:route.text,path:route.preview,border,ids:[],rev:snapshot.rev,
      heading:frame?'Draw the seven-roof border':kind==='book-pencil'?'Add the pencil':'Draw '+title+' in the center',explanation:centerHelp(kind)};
  }
  async function photoPlan(serial){
    const f=$('file').files[0];
    if(reference&&!/^[012]$/.test($('photoTarget').value))throw Error('Choose a guest place for this reference picture.');
    if(!f)throw Error('Choose a photo first.');
    if(!window.GuestPhoto)throw Error('The photo tools could not load. Refresh this page to try again.');
    const mode=$('photoMode').value,group=mode!=='one',spot=$('photoTarget').value;
    const closeUp=canNamePortrait() && $('centerHead').checked ? spot : null;
    const inward=inwardSelected();
    const separateEyes=!!(inward && group && $('largerFaces').checked && $('spaceEyes').checked && !$('photoName').value.trim());
    if(inward)await loadInwardTools();
    if(!photo||photo.file!==f||photo.mode!==mode||photo.closeUp!==closeUp||(inward&&!photo.tracedInward)||photo.separateEyes!==separateEyes){
      const options={group,whole:mode==='whole',foregroundFirst:mode==='group',face:faceChoice,groupFaces};
      if(closeUp){
        if(group)options.groupStyle='heads';
        options.portraitFraming=spot==='center' ? 'framedHead' : 'head';
        options.portraitDiameterGrooves=await GuestCenterRoutes.photoDiameterGrooves(spot);
        options.compactBeardGrain=spot==='center' && !group;
        options.inwardContours=inward;
        options.separateCrowdedEyes=separateEyes;
        options.tracePairEyes=options.tracePairSmiles=spot==='full' && group;
      }
      const result=await window.GuestPhoto.fromFile(f,options);
      if(serial!==buildNumber) return null;
      photo={file:f,mode,closeUp,separateEyes,canSeparateEyes:result.canSeparateEyes,tracedInward:inward,points:result.points,inwardContours:result.inwardContours,inwardHair:result.inwardHair,largerFaceContours:result.largerFaceContours,largerHairContours:result.largerHairContours,hairContours:result.hairContours,partedHair:result.partedHair,fringe:result.fringe,soloSmile:result.soloSmile,reviewedPortrait:result.reviewedPortrait,pairEyePoints:result.pairEyePoints,smiles:result.smiles,hasPortrait:result.hasPortrait,found:result.faceBoxes?.length,count:result.includedFaces?.length??result.facesDetected,name:mode==='whole'?'Photo':group?'Group photo':'Portrait'};
      displayFaces(mode==='whole'||!result.includedFaces?null:result,faceChoice,group,groupFaces);
    }
    const name=canNamePortrait() ? $('photoName').value.trim() : '';
    const drawing=!name && $('pairSmile').checked && photo.smiles ? photo.smiles : photo;
    const selectedPoints=style=>!name && $('pairEyes').checked && style.pairEyePoints || style.points;
    let points=selectedPoints(drawing),caption;
    if(name){
      if(!photo.hasPortrait)throw Error('Choose or frame a face before adding a name.');
      const lettering=/\p{Script=Thai}/u.test(name) ? './guest-thai-lettering.js' : './guest-lettering.js?v=2';
      try {
        await Promise.all([import('./guest-portrait-caption.js?v=2'), import(lettering)]);
      } catch {
        throw Error('The name tools could not load. Refresh the page and try again.');
      }
      if(serial!==buildNumber)return null;
    }
    if(name && !inward){
      const groove=2/await GuestCenterRoutes.photoDiameterGrooves(spot);
      const needsRoom=spot==='center' ? 'The name and portrait need more room. Try initials, choose Whole table, or leave the name blank.' :
        'The name and portrait need more room. Try initials or leave the name blank.';
      try {
        caption=await GuestPortraitCaption.fit(points,name,groove);
      } catch(error){
        if(!error.message.startsWith('There is too little room'))throw error;
        throw Error(needsRoom);
      }
      if(serial!==buildNumber)return null;
      // Keep the frame off the close crop's hair, including the new stroke from its entrance.
      if(closeUp==='center' && photo.count===1){
        const crown=Math.max(...caption.portrait.map(([,y])=>y));
        if(caption.points[1][1]>crown-1.5*groove || caption.portrait.some(p=>Math.hypot(...p)>1-1.5*groove+1e-8))
          throw Error(needsRoom);
      }
      points=caption.points;
    }
    const ids=allSlots();
    let p;
    if(spot==='center'){
      p=await centerPlan('photo',points,'this '+photo.name.toLowerCase());
    } else if(inward){
      if(!photo.inwardContours)throw Error(group ? 'Choose fewer faces for this inward portrait, or choose Clear, then draw for the whole group.' :
        'Choose or frame one face before drawing it during the inward erase.');
      const occupied=status.state!=='idle' || status.paused || state.pending ||
        ['running','staged'].includes(status.receipt?.state);
      const snapshot=occupied ? null : await GuestCenterPlay.preview('whole-portrait');
      const opening=snapshot?.theta ?? -Math.PI/2;
      const quietFace=inwardPicker.value==='quiet-engraved';
      const engraved=quietFace || inwardPicker.value==='engraved';
      const fringe=!group && $('photoFringe').checked && photo.fringe;
      const hair=fringe ? [...photo.inwardHair,fringe] : !group && photo.partedHair && $('photoPart').checked ? photo.partedHair : photo.inwardHair;
      const enlarged=canEnlargeTrio() && $('largerFaces').checked;
      const hairOutline=$('groupHair').checked && trioHairContours();
      const smile=!group && photo.soloSmile?.[$('soloSmile').value];
      const savedDetails=smile && $('soloSmile').value==='open' && $('savedDetails').checked && photo.reviewedPortrait;
      const faces=savedDetails || smile || hairOutline || (enlarged ? photo.largerFaceContours : photo.inwardContours);
      const contours=engraved && !savedDetails ? faces.concat(hair) : faces;
      const several=group && photo.count>1;
      const style={quietFace,keepScale:several};
      let route;
      try {
        route=name ? await GuestInwardPortrait.namedPlan(contours,opening,name,style) :
          GuestInwardPortrait.plan(contours,opening,style);
      } catch(error){
        if(hairOutline && /single-pass limit|too many lines/.test(error.message))
          throw Error('These hair outlines exceed one inward pass. Uncheck Trace the hair outline to use the original drawing.');
        if(separateEyes && /single-pass limit|too many lines/.test(error.message))
          throw Error('This portrait exceeds one inward pass. Uncheck Leave space between the eye and nose to try the longer bridge.');
        if(enlarged && /single-pass limit|too many lines/.test(error.message))
          throw Error('The larger faces exceed one inward pass. Uncheck Give smaller faces more room to preview the original sizes.');
        throw error;
      }
      p={...route,mode:snapshot?'inward':'inward-draft',kind:'whole-portrait',snapshot,rev:snapshot?.rev,ids:[],
        preview:GuestInwardPortrait.preview(route.path,480),
        heading:'Draw this inward portrait',explanation:several ? 'The ball draws '+(photo.count===2?'both faces':'all three faces')+' as it clears the tray inward, then follows the nearest portrait back to the rim.' : 'The ball draws the face as it clears the whole tray inward, then follows the head outline back to the rim.'};
      if(savedDetails)p.explanation+=' The saved tracing follows the raised hair, dark eyes and nose from the earlier Mini drawing.';
      if(smile)p.explanation+=$('soloSmile').value==='open' ? ' The smile follows both photographed corners and the open space between the lips.' : ' One stroke follows the lower edge of the photographed smile.';
      else if(hairOutline)p.explanation+=' The outer hair follows the photograph.';
      if(fringe && engraved && !savedDetails)p.explanation+=' A separate groove follows the photographed hairline.';
      else if(!savedDetails && !smile && !hairOutline && engraved && !photo.inwardHair.length)p.explanation+=' No separate hair grooves fit this crop.';
      if(name)p.explanation+=' '+route.inscription;
      if(!snapshot){
        p.heading='Waiting for the Mini';
        p.explanation='You can change this portrait while the Mini is busy. The preview will update from the rim before you start it.'+
          (name?' '+route.inscription:'');
      }
      const seconds=GuestInwardPortrait.estimatedSeconds(route.path,status);
      if(seconds>0)p.explanation+=' About '+Math.max(1,Math.round(seconds/60))+' min from start to finish.';
    } else if(spot==='full'){
      function tablePath(style,chosen){
        const path=art.pathForPhoto(chosen,defaultPhotoTarget);
        if(path.length<=12000 || chosen!==style.pairEyePoints)return path;
        style.pairEyePoints=null;
        return art.pathForPhoto(style.points,defaultPhotoTarget);
      }
      let path=tablePath(drawing,points);
      if(path.length>12000 && drawing===photo.smiles){
        photo.smiles=null;
        path=tablePath(photo,selectedPoints(photo));
      }
      p=draft('photo',blank(),[path],'Draw this '+photo.name.toLowerCase(),'Clears the whole table and draws the photo across it.');
    } else {
      const n=Number(spot),id=keepCustom(reference?.name||photo.name,'photo',[points],'photo');
      p=requestAt(ids,n,id,reference?.guest,art.pathForPhoto(points,manifest.slots[n]));
    }
    if(caption)p.explanation+=' With “'+caption.label+'” below the portrait.';
    if(mode==='group' && !groupFaces && photo.found>photo.count){
      p.explanation+=' Starting with '+photo.count+' of '+photo.found+' faces. You can include the smaller face above.';
    } else if(mode==='group')p.explanation+=' '+photo.count+' '+(photo.count===1?'face':'faces')+
      (groupFaces?' selected.':' found.')+' Check everyone is in the preview.';
    return p;
  }
  let buildingPreview=false,readingPreviewState=0;
  async function preview(picked){
    if(pendingSend)return;
    $('useReference').hidden=true;
    const request=++previewRequest,serial=++buildNumber;
    readingPreviewState=request;
    plan=null;$('draw').disabled=true;$('resumeCenter').hidden=true;
    buildingPreview=true;$('previewButton').setAttribute('aria-busy','true');
    $('sourceFrame').inert=$('faceActions').inert=true;
    readyButtons();
    try{
      await refresh();
      if(readingPreviewState===request)readingPreviewState=0;
      if(serial!==buildNumber)return;
      if(!state)throw Error('Could not reach the table for a current preview.');
      const rev=state.rev;
      message('error','');message('message','');
      const p=tab==='people'?freshPeople():tab==='request'?requestPlan(picked):tab==='photo'?await photoPlan(serial):
        await centerPlan($('centerSubject').value,null,{guitar:'a guitar',phage:'a phage',book:'an open book'}[$('centerSubject').value]);
      if(serial===buildNumber&&directPlan(p))await refresh();
      if(serial!==buildNumber)return;
      if(!state || (p.mode!=='inward-draft' && (p.rev!==state.rev ||
        (directPlan(p)?!centerStillCurrent(p.snapshot,state,status):rev!==state.rev))))
        throw Error('The table changed. Preview the drawing again.');
      plan=p;show(plan);
      if(picked){
        const panel=$('drawing').closest('.preview');
        if(panel.getBoundingClientRect().top>=innerHeight)panel.scrollIntoView({block:'start'});
      }
    }catch(e){if(serial===buildNumber){show(null);message('error',e.message);
      if(e.canResume&&window.GuestCenterPlay?.resume)showPrepared(preparedCenterName||'drawing');}}
    finally{if(request===previewRequest){
      buildingPreview=false;$('previewButton').removeAttribute('aria-busy');
      $('sourceFrame').inert=$('faceActions').inert=false;readyButtons();
    }}
  }
  function show(p){
    const protectedCenter=centerSelected();
    if(!p&&state?.pending&&!protectedCenter)p=activePlan;
    const completedPhoto=!p&&state?.photo;
    const ids=p?p.ids:allSlots(), cv=$('drawing'),ctx=cv.getContext('2d'), w=cv.width, mid=w/2,r=w*.465;
    cv.closest('.preview').classList.toggle('center-preview',protectedCenter);
    $('centerHelp').hidden=!!p&&protectedCenter;
    cv.hidden=protectedCenter&&!p;
    if(cv.hidden){
      $('key').replaceChildren();$('previewHeading').textContent='Sand preview';
      $('effect').textContent='';$('draw').textContent='Draw in the center';readyButtons();return;
    }
    ctx.clearRect(0,0,w,w);
    const sand=ctx.createRadialGradient(mid*.68,mid*.5,10,mid,mid,r*1.4);
    sand.addColorStop(0,'#f3e9d5');sand.addColorStop(1,'#d7c39e');
    ctx.fillStyle=sand;ctx.strokeStyle='#bcaa8b';ctx.lineWidth=2;ctx.beginPath();ctx.arc(mid,mid,r+2,0,2*Math.PI);ctx.fill();ctx.stroke();
    const full=p?.mode==='photo' || !!p?.preview;
    // Shade the measured groove width, using its height change across an oblique light.
    // Merging paths into one mask also lets tight features merge the way they do in sand.
    const mask=document.createElement('canvas');mask.width=mask.height=w;
    const groove=r*.042, floor=mask.getContext('2d',{willReadFrequently:true});
    floor.lineWidth=groove*.65;floor.lineJoin='round';floor.lineCap='round';
    floor.strokeStyle='white';floor.filter='blur('+groove*.24+'px)';
    let hasGrooves=false;
    function trace(path){
      hasGrooves=true;floor.beginPath();
      path.forEach(([t,rho],j)=>{const x=mid+r*rho*Math.cos(t),y=mid-r*rho*Math.sin(t);
        if(j)floor.lineTo(x,y);else floor.moveTo(x,y);
      });
      floor.stroke();
    }
    function lightGrooves(){
      if(!hasGrooves)return;
      const depth=floor.getImageData(0,0,w,w).data, frame=ctx.getImageData(0,0,w,w),pixels=frame.data;
      const dx=Math.max(1,Math.round(groove*.33)),dy=Math.max(1,Math.round(groove*.16)),shift=4*(dy*w+dx);
      for(let y=dy;y<w-dy;y++)for(let x=dx;x<w-dx;x++){
        const k=(y*w+x)*4;
        if(!pixels[k+3])continue;
        const shade=(depth[k+3-shift]-depth[k+3+shift])*.24-depth[k+3]*.062;
        pixels[k]+=shade;pixels[k+1]+=shade;pixels[k+2]+=shade;
      }
      ctx.putImageData(frame,0,0);
    }
    function drawInward(canvas){
      ctx.save();ctx.beginPath();ctx.arc(mid,mid,r,0,2*Math.PI);ctx.clip();
      ctx.drawImage(canvas,mid-r,mid-r,r*2,r*2);ctx.restore();
    }
    if(p?.mode==='center'){if(p.border)trace(p.border);trace(p.path);}
    else if(p?.preview)drawInward(p.preview);
    else if(full)trace(p.path);
    else if(completedPhoto){
      if(photoCompleted?.run && photoCompleted.run===status.receipt?.id && window.GuestInwardPortrait){
        photoCompleted.preview??=GuestInwardPortrait.preview(photoCompleted.path,480);
        drawInward(photoCompleted.preview);
      }else if(photoCompleted?.rev===state.rev)trace(photoCompleted.path);
      else {ctx.font='22px Georgia,serif';ctx.textAlign='center';ctx.fillStyle='#745f3e';ctx.fillText('Guest photo',mid,mid);}
    }
    else manifest.slots.forEach((s,i)=>{
      const id=ids[i], path=p?.rendered[i]||(id?sandPath(id,i):null);
      if(path){trace(path);return;}
      ctx.beginPath();ctx.setLineDash([7,10]);ctx.lineWidth=1;ctx.strokeStyle='#a29375';ctx.arc(mid+r*s.center[0],mid-r*s.center[1],r*s.radius,0,2*Math.PI);ctx.stroke();ctx.setLineDash([]);
      if(id){ctx.font='19px sans-serif';ctx.textAlign='center';ctx.fillStyle='#625338';ctx.fillText(label(id).slice(0,25),mid+r*s.center[0],mid-r*s.center[1]);}
    });
    lightGrooves();
    $('previewHeading').textContent=p?.mode==='inward-draft'?'Portrait preview on this phone':state?.pending?'Drawing in progress':p?'Sand preview':completedPhoto?'Photo on the sand':state?.known?'Current scene':'New scene';
    $('key').replaceChildren();
    if(!full)ids.forEach((id,i)=>{
      if(!id)return;const li=document.createElement('li'),small=document.createElement('small');small.textContent=manifest.slots[i].label;
      li.append(document.createTextNode(label(id)+' '),small);$('key').append(li);
    });
    $('effect').textContent=p?p.explanation:completedPhoto?'A guest photo fills the table. Starting a new scene clears it.':state?.known?'Choose a suggestion to change one part of the scene.':'Preview a drawing before sending it to the sand.';
    $('draw').textContent=p?p.heading:'Draw this scene';readyButtons();
  }
  async function read(url,opts){const r=await fetch(url,{cache:'no-store',...opts});if(!r.ok)throw Error((await r.text()).trim()||'The table could not finish that request.');return r}
  let refreshing=null;
  function centerStillCurrent(snapshot,s,d){
    return s.rev===snapshot.rev && d.device_id===snapshot.device &&
      d.receipt?.id===snapshot.receipt && d.receipt.state===snapshot.receiptState &&
      d.state==='idle' && d.homed && !d.paused && !d.fault && !d.auto && !d.queue?.length &&
      !s.pending && !s.evolving && !d.boot_pending && Math.abs(d.rho-snapshot.rho)<.001 &&
      Math.abs(Math.atan2(Math.sin(d.theta-snapshot.theta),Math.cos(d.theta-snapshot.theta)))<.002;
  }
  async function refresh(){
    if(refreshing)return refreshing;
    refreshing=(async()=>{
      try{
        const [d,s]=await Promise.all([read('/status').then(r=>r.json()),read('/guest-state').then(r=>r.json())]);
        if(!Array.isArray(s.slots)||s.slots.length!==3||typeof s.rev!=='string')throw Error('Unexpected scene state.');
        if(!s.known&&!s.pending&&window.GuestCenterPlay?.finishedWholePortrait?.(d)){
          s.photo=true;
          if(photoCompleted?.run===d.receipt.id)await loadInwardTools().catch(()=>{});
        }
        const changed=!state||s.rev!==state.rev||s.known!==state.known||s.slots.join(',')!==state.slots.join(',')||!!s.photo!==!!state.photo;
        status=d;state=s;
        const gotParts=manifest&&await fetchSandPaths(s);
        if(manifest&&(peopleRevision===null||String(s.peopleRev)!==peopleRevision)){
          try{mergePeople(await read('/guest-people').then(r=>r.json()));}
          catch{/* A failed roster lookup can be retried without losing the table status. */}
        }
        if(s.photo&&activePlan?.mode==='photo'){
          photoCompleted={rev:s.rev,path:activePlan.path.map(([t,r])=>[+t.toFixed(5),+r.toFixed(5)])};
          remember('oasis-guest-full-photo-v1',photoCompleted);
        }else if(!s.photo&&!s.pending&&photoCompleted&&!(photoCompleted.run && photoCompleted.run===d.receipt?.id)){
          photoCompleted=null;remember('oasis-guest-full-photo-v1',null);
        }
        message('status',s.partProtocol!==2?'The table needs the new guest drawing software':s.pending?(d.paused?'Drawing paused':'Drawing in the sand…'):d.fault?'Table needs attention':
          d.state!=='idle'?'Table is busy':d.auto?'Drawing by itself':!d.homed?'Find home on the Oasis page':'Table ready');
        if(s.pending)seenBusy=true;
        const outdated=directPlan(plan)&&!centerStillCurrent(plan.snapshot,s,d);
        if((changed&&manifest)||outdated){
          // A newly requested preview starts with this fresh reading. A later
          // change, after route construction starts, invalidates its result.
          const composing=plan?.mode==='inward-draft' || (buildingPreview&&inwardSelected());
          if(!composing && (!readingPreviewState||readingPreviewState!==previewRequest))invalidate(true);
          targets();
          if(outdated&&!pendingSend)message('error','The table changed. Preview your drawing again.');}
        else if(gotParts&&manifest&&!plan)show(null);
        if(window.GuestCenterPlay?.prepared&&!pendingSend){
          preparedCenterName=window.GuestCenterPlay.prepared(d,s.rev);
          showPrepared(preparedCenterName);
        }
        if(seenBusy&&!s.pending){seenBusy=false;activePlan=null;message('message',s.known?'The scene is ready for another suggestion.':s.photo?'The photo is on the sand.':'The table is idle.');}
        // Rebuild from the actual dock and receipt once. Starting the portrait
        // still takes an explicit tap, even when two phones have drafts open.
        if(plan?.mode==='inward-draft' && GuestCenterPlay.canPrepareWhole(d,s)){
          const draft=plan;
          setTimeout(()=>{if(plan===draft)preview();},0);
        }
      }catch(e){
        state=null;status=null;preparedCenterName=null;showPrepared(null);
        message('status','Table unavailable');$('draw').disabled=true;
      }
      finally{readyButtons();refreshing=null;}
    })();return refreshing;
  }
  async function draw(){
    if(pendingSend||!plan||plan.mode==='inward-draft')return;
    const p=plan;pendingSend=true;readyButtons();message('error','');
    try{
      await refresh();
      if(plan!==p||!enabled()||state.rev!==p.rev)throw Error('The table changed. Preview the scene again when it is ready.');
      if(directPlan(p)){
        plan=null;
        const result=await window.GuestCenterPlay.draw(p.snapshot,p.text,p.kind);
        if(p.mode==='inward'){
          photoCompleted={run:result.receipt,path:p.path};
          remember('oasis-guest-full-photo-v1',photoCompleted);photoCompleted.preview=p.preview;
        }
        await refresh();
        message('message',result.state==='complete'?'The drawing is finished.':'The Mini started the drawing. You can close this page.');
        return;
      }
      const headers={'Content-Type':'application/octet-stream','X-Guest-Rev':p.rev,'X-Guest-Mode':p.mode,'X-Guest-Slots':p.ids.join(',')};
      if(p.counts)headers['X-Guest-Counts']=p.counts.join(',');
      const choices=themes.choicesForSubmission(p);
      const receipt=await read('/guest-draw',{method:'POST',headers,body:p.body}).then(r=>r.json());
      rememberSeats(p,receipt);
      endReference();
      plan=null;activePlan=p;
      let nextMessage=state.evolving&&!choices?'The table accepted the drawing. Automatic changes are off for this picture.':'The table accepted the drawing. You can close this page.';
      if(choices){
        try{rememberSeats(p,await themes.arm(receipt.rev,choices));nextMessage='The table will draw this scene and keep changing it. You can close this page.';}
        catch(e){nextMessage='The table accepted the drawing. Automatic changes could not start: '+e.message;}
      }
      themes.started();
      if(tab==='request'&&strokes.length&&!p.keepSketch){strokes=[];activeStroke=null;paintPad();$('sketch').open=false;}
      await refresh();
      message('message',nextMessage);
    }catch(e){message('error',e.message);
      if(directPlan(p)){
        localPreparedReceipt=e.canResume ? e.receipt : null;
        plan=null;preparedCenterName=e.canResume&&window.GuestCenterPlay?.resume?(preparedCenterName||'drawing'):null;
      }}
    finally{pendingSend=false;readyButtons();showPrepared(preparedCenterName);}
  }
  $('resumeCenter').onclick=async()=>{
    if(pendingSend||$('resumeCenter').hidden)return;
    pendingSend=true;$('resumeCenter').hidden=true;readyButtons();
    try{
      const result=await window.GuestCenterPlay.resume();
      preparedCenterName=null;
      await refresh();message('error','');
      message('message',result.state==='complete'?'The drawing is finished.':'The Mini started the prepared drawing. You can close this page.');
    }catch(e){message('error',e.message);if(!e.canResume)preparedCenterName=null;}
    finally{pendingSend=false;readyButtons();showPrepared(preparedCenterName);}
  };
  $('addGuest').onsubmit=async e=>{
    e.preventDefault();
    const name=$('personName').value.trim(),interest=$('personIdea').value.trim();
    if(!name||!interest||!manifest)return;
    const existing=roster.find(q=>art.normalize(q.name)===art.normalize(name));
    const selected=existing?existing.on:roster.filter(p=>p.on).length<3;
    const inferred=resolveIdea(interest);
    const subject=manifest.subjects[inferred]||glyph(inferred)?inferred:'';
    const submit=$('addGuest').querySelector('button');
    submit.disabled=true;
    try {
      const body=new URLSearchParams({name,interest,subject});
      const response=await read('/guest-people',{method:'POST',body});
      mergePeople(await response.json());
      const person=roster.find(q=>art.normalize(q.name)===art.normalize(name));
      if(!person)throw Error('The table did not save this guest.');
      person.on=selected;
      remember('oasis-guest-roster-v1',roster);renderRoster();invalidate();$('addGuest').reset();$('addBox').open=false;
      if(!person.subject){chooseTab('request');$('idea').value=interest;$('sketch').open=true;message('error','Sketch '+name+'’s subject, then preview it to add it to their guest profile on this device.');}
    }catch(err){message('error',err.message);}
    finally{submit.disabled=false;}
  };
  $('sketch').ontoggle=()=>{if(strokes.length)invalidate()};
  $('idea').oninput=invalidate;$('freshSand').onchange=invalidate;$('target').onchange=()=>{selectedTarget=$('target').value;invalidate()};
  $('photoTarget').onchange=invalidate;
  $('photoName').oninput=invalidate;
  $('centerHead').onchange=invalidate;
  inwardPicker?.addEventListener('change',invalidate);
  $('photoFringe').onchange=$('savedDetails').onchange=$('soloSmile').onchange=$('groupHair').onchange=$('spaceEyes').onchange=$('largerFaces').onchange=$('photoPart').onchange=$('pairEyes').onchange=$('pairSmile').onchange=()=>{invalidate();preview();};
  $('photoMode').onchange=()=>{photo=null;$('soloSmile').value='original';$('largerFaces').checked=$('spaceEyes').checked=$('groupHair').checked=$('savedDetails').checked=$('photoFringe').checked=false;displayFaces(null);invalidate();};
  $('centerSubject').onchange=()=>{
    $('centerHelp').textContent=centerHelp($('centerSubject').value);
    invalidate();
  };
  $('centerPhotoButton').onclick=()=>{$('photoTarget').value='center';chooseTab('photo');};
  $('useReference').onclick=()=>{
    const req=art.splitRequest($('idea').value.trim(),roster);
    let place='';
    if(!state?.photo || selectedTarget!=='auto'){
      try{place=String(targetFor(req,allSlots()));}catch{/* The guest can choose the place in the photo form. */}
    }
    const name=cap(req.to.replace(/^(?:(?:please )?(?:draw|make|sketch) )?(?:(?:an?|the) )?/i,'').trim()) || req.to;
    reference={name,guest:req.guest,rev:state?.rev};
    chooseTab('photo');targets();
    $('photoMode').value='whole';$('photoTarget').value=place;
    $('file').value='';$('file').dispatchEvent(new Event('change'));
    referenceLabels();
    if(!place)message('error','Choose a guest place for this reference picture.');
    $(place?'file':'photoTarget').focus();
  };
  let photoUrl='';
  $('file').onchange=async ()=>{
    photo=null;faceChoice=null;groupFaces=null;$('soloSmile').value='original';$('photoName').value='';$('pairEyes').checked=true;$('pairSmile').checked=false;$('photoPart').checked=false;$('largerFaces').checked=$('spaceEyes').checked=$('groupHair').checked=$('savedDetails').checked=$('photoFringe').checked=false;displayFaces(null);
    invalidate();
    if(photoUrl)URL.revokeObjectURL(photoUrl);
    photoUrl='';
    const f=$('file').files[0];
    $('photoImage').removeAttribute('src');
    $('sourceFrame').hidden=!f;
    if(f){
      const upright=await GuestPhoto.uprightPhoto(f);
      if($('file').files[0]!==f)return;
      photoUrl=URL.createObjectURL(upright);
      $('photoImage').src=photoUrl;
    }
  };
  const pad=$('pad'),ink=pad.getContext('2d');
  function padPoint(e){const r=pad.getBoundingClientRect();const x=2*(e.clientX-r.left)/r.width-1,y=1-2*(e.clientY-r.top)/r.height;
    return [Math.max(-1,Math.min(1,x))*.64,Math.max(-1,Math.min(1,y))*.64];}
  function paintPad(){
    ink.clearRect(0,0,pad.width,pad.height);ink.strokeStyle='#645435';ink.lineWidth=4;ink.lineCap=ink.lineJoin='round';
    for(const s of strokes){ink.beginPath();s.forEach(([x,y],i)=>{const px=(x/.64+1)*150,py=(1-y/.64)*150;if(i)ink.lineTo(px,py);else ink.moveTo(px,py)});ink.stroke();}
  }
  pad.onpointerdown=e=>{if(activeStroke||strokes.length>=25)return;pad.setPointerCapture(e.pointerId);activeStroke=[padPoint(e)];strokes.push(activeStroke);invalidate();paintPad()};
  pad.onpointermove=e=>{if(!activeStroke||activeStroke.length>=3000)return;const p=padPoint(e),last=activeStroke.at(-1);if(Math.hypot(last[0]-p[0],last[1]-p[1])>.006){activeStroke.push(p);paintPad();}};
  pad.onpointerup=pad.onpointercancel=()=>{activeStroke=null};
  $('clearSketch').onclick=()=>{strokes=[];activeStroke=null;paintPad();invalidate()};
  $('previewButton').onclick=()=>preview();$('draw').onclick=draw;
  document.querySelectorAll('[data-tab]').forEach(b=>b.onclick=()=>chooseTab(b.dataset.tab));
  let userInteracted=false;
  for(const event of ['pointerdown','keydown'])document.addEventListener(event,()=>{userInteracted=true;},{once:true,capture:true});
  async function load(){
    try{manifest=await read('/lib/guest-paths.json').then(r=>r.json());if(manifest.version!==1||manifest.slots.length!==3)throw Error('Unexpected drawing catalog.');
      art.thanksgivingPicker($('thanksgivingDrawings'),manifest,
        id=>art.slotMotif(manifest.subjects[id].paths[0],manifest.slots[0]),preview,'drawing');
      renderRoster();await refresh();targets();
      if(userInteracted){if(!plan&&!buildingPreview)show(null);}
      else if(preparedCenterName){
        if(preparedCenterName==='whole-table portrait'){
          $('photoTarget').value='full';chooseTab('photo');
        }else chooseTab('center');
        message('message','A drawing has been prepared on the Mini.');
      }
      else if(status&&window.GuestCenterPlay?.recognized(status))chooseTab('center');
      else if(state?.known||state?.photo)chooseTab('request');else if(state)await preview();else show(null);
      setInterval(refresh,3500);
    }catch(e){message('error','Could not load the drawing catalog. Refresh to try again.');}
  }
  load();
})();
