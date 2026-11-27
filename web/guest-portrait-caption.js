// Keep a photographed outline and a handwritten name on separate patches of
// sand. Coordinates are relative to the radius of the chosen portrait area.
window.GuestPortraitCaption = (() => {
  const noRoom='There is too little room for the name below this portrait. Try initials or leave the name blank.';
  // A support point can be approached from its outward direction without
  // crossing any other part of the outline. Use the shortest such approach.
  function entrance(points,upper) {
    let best;
    for(let step=0;step<=12;step++){
      const angle=(upper?1:-1)*Math.PI*step/12, dx=Math.cos(angle),dy=Math.sin(angle);
      let i=0,dot=-Infinity;
      points.forEach(([x,y],j)=>{const d=x*dx+y*dy;if(d>dot){dot=d;i=j;}});
      const [x,y]=points[i], distance=Math.sqrt(Math.max(0,1-x*x-y*y+dot*dot))-dot;
      if(!best||distance<best.distance)best={i,distance,gate:[x+distance*dx,y+distance*dy]};
    }
    const {i,gate}=best;
    return {i,gate,walk:[gate,...points.slice(i),...points.slice(0,i+1),gate]};
  }
  async function layout(ink,name,groove) {
    const thai=/\p{Script=Thai}/u.test(name);
    const lettering=thai?GuestThaiLettering:GuestLettering;
    let design=await lettering.design(name,{groove,singleLine:true});
    if(!design.legible)throw Error(noRoom);
    // Keep recognizable facial proportions and the lettering's own measured
    // minimum lowercase height. Leave an extra groove between ink and rim.
    const size=(design.minimumGrooves+.25)/design.xHeightGrooves;
    design=await lettering.design(name,{groove:groove/size,singleLine:true});
    if(!design.legible)throw Error(noRoom);
    const limit=1-groove, text=design.path.map(([x,y])=>[x*size,y*size]);
    let textY=-Infinity,top=-Infinity;
    for(const [x,y] of text){
      if(Math.abs(x)>=limit)throw Error(noRoom);
      textY=Math.max(textY,-Math.sqrt(limit*limit-x*x)-y);
      top=Math.max(top,y);
    }
    if(text.some(([x,y])=>Math.hypot(x,y+textY)>limit+1e-8))throw Error(noRoom);
    const floor=ink.reduce((y,p)=>Math.min(y,p[1]),Infinity);
    for(let pct=100;pct>=75;pct--){
      const scale=pct/100,shift=Math.max(0,textY+top+1.75*groove-floor*scale);
      const portrait=ink.map(([x,y])=>[x*scale,y*scale+shift]);
      if(portrait.some(([x,y])=>Math.hypot(x,y)>limit))continue;
      const lift=Math.min(3*groove,(floor*scale+shift-1.75*groove-top-textY)/2);
      const caption=text.map(([x,y])=>[x,y+textY+Math.max(0,lift)]);
      return {label:design.label,portrait,caption,scale,shift,letterGrooves:design.xHeightGrooves};
    }
    throw Error(noRoom);
  }
  async function fit(points,name,groove) {
    // Drop the original rim entrance before relocating the portrait.
    const fitted=await layout(points.slice(1,-1),name,groove);
    const face=entrance(fitted.portrait,true), word=entrance(fitted.caption,false);
    const a=Math.atan2(face.gate[1],face.gate[0]), b=Math.atan2(word.gate[1],word.gate[0]);
    const turn=Math.atan2(Math.sin(b-a),Math.cos(b-a)), n=Math.max(1,Math.ceil(Math.abs(turn)/.04));
    const rim=Array.from({length:n+1},(_,i)=>[Math.cos(a+turn*i/n),Math.sin(a+turn*i/n)]);
    return {...fitted,points:[...face.walk,...rim,...word.walk,...rim.reverse(),face.gate]};
  }
  return {fit,layout,entrance};
})();
