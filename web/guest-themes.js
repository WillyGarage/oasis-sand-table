// Guest-scene choices for autonomous changes. The table owns the clock and draws after phones leave.
window.GuestThemes = function({context,read,refresh,onError}){
  const $=id=>document.getElementById(id);
  const defaults={
    thomas:{interest:'Bacteriophages',ids:['phage','dna','rocket']},
    alex:{interest:window.GuestArt.alexInterest,ids:['books','guitar','clapper_alt','classroom']},
    lek:{interest:'Thailand',ids:['temple','elephant','hotpot','thailand']}
  };
  let key='',wanted=false,remoteOn=false,writing=false,mode='',currentIds=[],editable=[];
  function visibleSlots(){
    const {state,plan,tab,roster}=context(), selected=roster.filter(p=>p.on);
    if(!state)return [];
    if(state.evolving)return [0,1,2].map((_,i)=>(state.known&&state.slots[i])||(state.themes?.[i]||'').split(',')[0]||'');
    if(plan&&plan.mode!=='photo')return plan.ids;
    if(tab==='people'&&!state.pending){
      const ids=selected.map(p=>p.subject||'');while(ids.length<3)ids.push('');return ids;
    }
    return state.known?state.slots:[];
  }
  function initialList(current,person,manifest){
    if(!person)return [current];
    const art=window.GuestArt,starter=defaults[art.normalize(person.name)];
    const choices=starter?.interest===person.interest ? starter.ids :
      art.interestIdeas(person.interest,manifest).map(idea=>idea.id);
    return [...new Set([current,...choices])].filter(id=>manifest.subjects[id]).slice(0,8);
  }
  function render(){
    const c=context(),state=c.state,root=$('evolution'),ids=visibleSlots();
    const any=ids.some(id=>c.manifest?.subjects[id]);
    root.hidden=!state||state.partProtocol!==2||!c.manifest||(!state.evolving&&(c.tab==='photo'||!any||state.pending));
    if(root.hidden){wanted=false;remoteOn=false;key='';return;}
    const remote=!!state.evolving;
    if(remote!==remoteOn){wanted=false;key='';remoteOn=remote;}
    mode=remote?'remote':(state.known&&ids.join(',')===state.slots.join(',')&&!c.plan?'current':'draft');
    // A pending file could be either a whole photo or the old scene at this point; themes are authoritative while on.
    const ownerNames=remote ? c.seatOwners() : c.plan?.names ||
      (c.tab==='people' ? c.roster.filter(p=>p.on).map(p=>p.name) : c.seatOwners());
    const signature=JSON.stringify([ids,mode,remote?state.themes:null,state.peopleRev,ownerNames]);
    if(signature!==key){
      key=signature;currentIds=ids.slice();editable=[];
      const allSubjects=Object.keys(c.manifest.subjects), container=$('themeFields');container.replaceChildren();
      ids.forEach((id,i)=>{
        if(!id)return;
        if(!c.manifest.subjects[id]){
          const hold=document.createElement('p');hold.className='help';hold.textContent=c.label(id)+' will be drawn again in the '+c.manifest.slots[i].label.toLowerCase()+' place.';
          container.append(hold);return;
        }
        const owner=c.roster.find(p=>p.name===ownerNames?.[i]);
        const list=remote ? (state.themes?.[i]||'').split(',').filter(Boolean) :
          initialList(id,owner,c.manifest);
        const label=document.createElement('label');label.className='field';
        label.append(document.createTextNode(c.manifest.slots[i].label+' · '+(owner?owner.name:c.label(id))));
        const input=document.createElement('textarea');input.id='alternate'+i;
        input.value=list.map(c.label).join(', ');input.rows=Math.max(1,Math.ceil(input.value.length/35));input.placeholder='Drawing names, separated by commas';input.autocomplete='off';
        input.oninput=()=>{input.rows=Math.max(1,Math.min(7,Math.ceil(input.value.length/35)));$('applyThemes').hidden=!(remote||mode==='current')};
        label.append(input);container.append(label);editable.push(i);
      });
      const guide=document.createElement('details'),title=document.createElement('summary'),names=document.createElement('p');
      title.textContent='Available drawing names';names.className='help';names.textContent=allSubjects.map(c.label).join(', ')+'.';
      guide.append(title,names);container.append(guide);
      $('applyThemes').hidden=true;
    }
    $('keepChanging').checked=remote||wanted;
    $('keepChanging').disabled=writing||c.sending;
    $('applyThemes').disabled=writing||c.sending;
    $('themeDetails').hidden=!(remote||wanted);
    if(!remote){$('applyThemes').hidden=!(wanted&&mode==='current');$('applyThemes').textContent='Start changing the scene';}
    else $('applyThemes').textContent='Save drawing choices';
    const hold=Number(state.hold)||300,time=hold<90?hold+' seconds':Math.round(hold/60)+' min';
    $('evolveHint').textContent=remote?'After about '+time+' on display, the table clears the whole surface and redraws the scene with one new subject.':
      wanted?(mode==='current'?'Review the choices, then start changing the scene.':'After drawing, the table will clear the sand and draw the next variation on its own.'):
        'For each variation, the table clears the sand and draws the whole scene with one new subject.';
  }
  function lists(){
    const {manifest,label,state}=context();
    const result=['','',''];let alternate=false;
    for(const i of editable){
      const input=$('alternate'+i),values=input.value.split(',').map(v=>v.trim()).filter(Boolean),chosen=[];
      for(const name of values){
        const id=Object.keys(manifest.subjects).find(id=>id===name||window.GuestArt.normalize(label(id))===window.GuestArt.normalize(name))||
          window.GuestArt.catalogIdea(name,manifest);
        if(!id)throw Error('Choose a listed drawing for “'+name+'”.');
        if(!chosen.includes(id))chosen.push(id);
      }
      if(chosen.length){
        const actual=state.known?state.slots[i]:null;
        const present=mode==='remote'&&actual?actual:currentIds[i];
        if(!chosen.includes(present))chosen.unshift(present);
        if(chosen.length>8)throw Error('Use up to eight subjects for each place.');
        if(chosen.length>1)alternate=true;
      }
      result[i]=chosen.join(',');
    }
    if(!alternate)throw Error('Add at least one alternate drawing in Drawing choices.');
    return result;
  }
  async function post(on,rev,choices=['','','']){
    const body=new URLSearchParams({on:on?'1':'0',rev,a:choices[0],b:choices[1],c:choices[2]});
    const data=await read('/guest-evolve',{method:'POST',body}).then(r=>r.json());
    if(!!data.evolving!==on)throw Error('The table did not save the drawing choices.');
    return data;
  }
  async function toggle(){
    const {state}=context();
    if(!state)return;
    if(!$('keepChanging').checked&&!remoteOn){wanted=false;render();return;}
    if(!remoteOn){
      wanted=$('keepChanging').checked;render();if(wanted)$('themeDetails').open=true;return;
    }
    const on=$('keepChanging').checked;
    writing=true;
    try{
      if(!on){
        await refresh();
        const latest=context().state;
        if(!latest)throw Error('Could not reach the table.');
        if(latest.evolving)await post(false,latest.rev);
      }else await post(true,state.rev,lists());
      wanted=false;await refresh();
    }catch(e){
      onError(e.message);
      if(on)$('themeDetails').open=true;
    }finally{writing=false;render();}
  }
  $('keepChanging').onchange=toggle;
  $('applyThemes').onclick=async()=>{
    const {state}=context();
    if(!state||writing)return;
    writing=true;
    try{await post(true,state.rev,lists());wanted=false;await refresh();}
    catch(e){onError(e.message);}
    finally{writing=false;render();}
  };
  return {render,choicesForSubmission(p){
      const {state,manifest,roster}=context();
      if(p.mode==='photo'||(!wanted&&!state.evolving))return null;
      if(!state.evolving)return lists();
      // Retain custom subjects in the lineup while other places can change autonomously.
      const choices=(state.themes||['','','']).map((csv,i)=>{
        const id=p.ids[i],old=csv.split(',').filter(Boolean);
        if(!id||!manifest.subjects[id])return '';
        if(p.mode==='fresh'&&!old.includes(id)){
          const owner=roster.find(person=>person.name===p.names?.[i]);
          return owner?initialList(id,owner,manifest).join(','):'';
        }
        return old.length?[...new Set([id,...old])].slice(0,8).join(','):'';
      });
      return choices.some(csv=>csv.includes(','))?choices:null;
    },arm:(rev,choices)=>post(true,rev,choices),
    started(){wanted=false;key='';}};
};
