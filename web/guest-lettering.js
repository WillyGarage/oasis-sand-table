// Original single-line lettering for the sand ball. Coordinates use one lowercase
// letter height as the unit. The bracketed strokes return over their own groove,
// e.g. a t's crossbar: the pen never takes a shortcut through the letter.
window.GuestLettering = (() => {
  const lowercase = {
    a:[.86,'M 0 .08 Q .12 .15 .17 .56 Q .2 .98 .51 1 Q .77 1 .75 .66 Q .72 .17 .44 .08 Q .1 .01 .16 .53 Q .19 .98 .52 1 Q .71 1 .75 .84 L .74 .21 Q .75 -.04 .86 .10'],
    b:[.86,'M 0 .08 Q .22 .34 .33 .92 Q .52 1.64 .36 1.68 Q .11 1.67 .12 .92 L .14 .08 Q .21 .5 .39 .8 Q .62 1.14 .78 .93 Q .98 .64 .68 .25 Q .47 -.02 .17 .11 Q .5 -.05 .86 .15'],
    c:[.76,'M 0 .08 Q .12 .24 .19 .57 Q .35 1.15 .68 .96 Q .74 .92 .68 .79 Q .62 .98 .47 .94 Q .2 .87 .17 .41 Q .12 -.15 .55 .06 Q .68 .11 .76 .22'],
    d:[.93,'M 0 .08 Q .13 .17 .18 .56 Q .23 .99 .52 1 Q .82 1 .75 .65 Q .68 .18 .42 .08 Q .12 0 .17 .5 Q .23 1.01 .52 1 Q .7 1 .76 .85 L .91 1.63 L .77 .24 Q .75 -.05 .93 .13'],
    e:[.77,'M 0 .08 Q .23 .31 .47 .51 Q .89 .87 .58 .98 Q .32 1.07 .19 .65 Q -.01 .06 .36 .04 Q .61 .02 .77 .23'],
    f:[.66,'M 0 .08 Q .18 .33 .29 1.02 Q .39 1.66 .63 1.65 Q .86 1.6 .6 1.26 Q .41 1.01 .28 .9 L .15 -.49 Q .13 -.67 .06 -.61 Q -.04 -.42 .12 -.16 Q .28 .07 .47 .2 L .66 .2'],
    g:[.92,'M 0 .08 Q .13 .15 .18 .56 Q .24 1.02 .54 1 Q .81 1 .74 .63 Q .68 .19 .42 .07 Q .12 -.01 .18 .51 Q .23 .98 .53 1 Q .75 1 .76 .84 L .65 -.28 Q .6 -.68 .34 -.65 Q .11 -.61 .35 -.37 Q .56 -.14 .92 .15'],
    h:[.94,'M 0 .08 Q .24 .4 .34 .99 Q .5 1.66 .34 1.68 Q .14 1.65 .13 .9 L .12 .06 Q .22 .58 .47 .86 Q .8 1.2 .79 .78 L .75 .25 Q .7 -.03 .94 .15'],
    i:[.49,'M 0 .08 Q .13 .28 .24 .77 L .29 .95 Q .19 1.02 .26 1.14 Q .35 1.24 .4 1.12 Q .43 1.02 .29 .95 L .23 .28 Q .18 -.06 .49 .16'],
    j:[.56,'M 0 .08 Q .17 .24 .34 .76 L .41 1.04 Q .49 1.08 .44 .91 L .27 -.3 Q .19 -.7 -.01 -.65 Q -.15 -.59 .02 -.38 Q .21 -.15 .56 .16'],
    k:[.90,'M 0 .08 Q .21 .35 .33 .99 Q .48 1.66 .32 1.68 Q .13 1.66 .13 .91 L .12 .06 Q .24 .59 .53 .88 Q .83 1.17 .73 .83 Q .66 .65 .35 .51 Q .58 .54 .66 .28 Q .75 -.06 .9 .15'],
    l:[.54,'M 0 .08 Q .23 .43 .35 1.01 Q .51 1.72 .31 1.68 Q .1 1.63 .1 .81 Q .09 -.09 .37 .07 Q .46 .1 .54 .21'],
    m:[1.28,'M 0 .08 Q .15 .29 .23 .9 L .17 .08 Q .29 .63 .47 .85 Q .71 1.12 .67 .72 L .6 .09 Q .76 .67 .96 .88 Q 1.21 1.11 1.14 .69 L 1.09 .24 Q 1.05 -.03 1.28 .15'],
    n:[.90,'M 0 .08 Q .16 .3 .24 .91 L .17 .08 Q .33 .68 .54 .89 Q .84 1.14 .76 .72 L .71 .24 Q .67 -.03 .9 .15'],
    o:[.87,'M 0 .08 Q .16 .19 .2 .56 Q .24 .99 .53 1 Q .88 1.02 .77 .54 Q .66 .04 .39 .06 Q .1 .07 .2 .56 Q .24 .99 .53 1 Q .88 1.02 .77 .54 Q .74 .33 .65 .22 Q .73 .08 .87 .17'],
    p:[.89,'M 0 .08 Q .18 .35 .27 .94 L .11 -.6 L .21 .31 Q .32 .76 .54 .92 Q .85 1.1 .8 .68 Q .76 .26 .49 .1 Q .26 -.04 .21 .16 Q .54 -.02 .89 .17'],
    q:[.97,'M 0 .08 Q .13 .17 .18 .56 Q .24 1.01 .54 1 Q .83 1 .75 .64 Q .68 .18 .41 .07 Q .12 -.01 .18 .52 Q .23 1 .54 1 Q .74 1 .76 .85 L .64 -.54 Q .8 -.33 .9 -.46 Q .96 -.63 .75 -.46 Q .62 -.29 .76 -.04 Q .84 .08 .97 .15'],
    r:[.74,'M 0 .08 Q .17 .32 .25 .75 Q .31 1.05 .43 .99 Q .52 .9 .36 .76 Q .52 .74 .65 .85 Q .52 .63 .48 .35 Q .4 -.02 .74 .16'],
    s:[.76,'M 0 .08 Q .2 .35 .41 .79 Q .5 1.07 .62 .98 Q .71 .89 .52 .78 Q .36 .66 .52 .5 Q .83 .19 .54 .05 Q .33 -.06 .18 .1 Q .46 0 .76 .18'],
    t:[.65,'M 0 .08 Q .2 .36 .32 .95 L .41 1.44 L .33 .90 [ L .07 .88 ] [ L .67 .95 ] L .24 .28 Q .17 -.06 .5 .09 L .65 .21'],
    u:[.94,'M 0 .08 Q .15 .26 .25 .91 L .17 .34 Q .12 -.12 .43 .13 Q .65 .32 .79 .93 L .71 .28 Q .65 -.02 .94 .17'],
    v:[.88,'M 0 .08 Q .14 .31 .23 .93 Q .27 1 .26 .81 L .24 .29 Q .23 -.07 .44 .13 Q .64 .32 .75 .73 Q .85 1.04 .69 .97 Q .57 .84 .7 .71 Q .82 .68 .91 .78'],
    w:[1.29,'M 0 .08 Q .16 .29 .24 .92 L .19 .32 Q .15 -.08 .4 .12 Q .58 .32 .7 .9 L .64 .33 Q .6 -.08 .86 .14 Q 1.05 .36 1.14 .76 Q 1.24 1.07 1.09 .96 Q .99 .84 1.12 .74 Q 1.22 .7 1.31 .79'],
    x:[.93,'M 0 .08 Q .13 .05 .22 .17 L .48 .52 [ Q .32 .79 .15 .98 ] [ Q .63 .77 .83 .99 ] Q .65 .2 .79 .1 Q .87 .06 .93 .17'],
    y:[.98,'M 0 .08 Q .13 .27 .25 .93 L .17 .35 Q .12 -.12 .43 .13 Q .68 .36 .8 .94 L .63 -.31 Q .57 -.68 .31 -.66 Q .13 -.61 .34 -.38 Q .56 -.14 .98 .17'],
    z:[.80,'M 0 .08 Q .16 .5 .3 .76 Q .44 1.04 .66 .93 Q .77 .82 .49 .5 L .24 .27 Q .58 .51 .69 .27 Q .79 .06 .55 -.25 Q .28 -.59 .14 -.48 Q .08 -.32 .39 -.13 Q .65 .05 .8 .16']
  };

  // Capitals have an open entrance and a foot that can carry the next letter.
  const capitals = {
    A:[1.12,'M 0 .04 Q .19 .02 .34 .53 L .73 1.58 L .88 .56 [ L .35 .56 ] L .97 .16 Q 1.02 .03 1.12 .16'],
    B:[1.06,'M 0 .08 Q .12 .06 .19 .19 L .22 1.51 Q .85 1.65 .91 1.27 Q .96 .91 .25 .78 Q 1.06 .86 .98 .41 Q .91 -.03 .21 .08 Q .61 -.06 1.06 .14'],
    C:[1.00,'M .92 1.21 Q 1.05 1.59 .69 1.54 Q .13 1.48 .12 .59 Q .1 -.17 .66 .08 Q .88 .18 1 .34'],
    D:[1.13,'M .02 .07 Q .13 .07 .2 .2 L .24 1.51 Q .97 1.66 1.01 .93 Q 1.09 .08 .21 .08 Q .67 -.02 1.13 .14'],
    E:[.94,'M .92 1.37 Q .68 1.69 .38 1.43 Q -.05 1.04 .57 .85 Q .02 .73 .14 .29 Q .26 -.15 .94 .18'],
    F:[.91,'M 0 .08 Q .24 -.02 .31 .31 L .4 .86 [ L .77 .88 ] L .48 1.49 [ Q .2 1.5 .08 1.4 ] [ Q .69 1.59 .99 1.5 ] L .31 .31 Q .35 -.04 .91 .14'],
    G:[1.08,'M .98 1.25 Q 1 1.61 .65 1.52 Q .09 1.37 .14 .51 Q .16 -.14 .61 .11 Q .82 .26 .88 .69 L .62 .65 L .88 .69 L .86 .15 Q .87 .01 1.08 .14'],
    H:[1.10,'M 0 .06 Q .13 .04 .2 .18 L .23 1.52 L .21 .78 L .87 .82 L .92 1.55 L .82 .22 Q .8 -.01 1.1 .14'],
    I:[.70,'M .07 1.41 Q .34 1.57 .71 1.48 Q .49 1.52 .43 1.47 L .32 .19 Q .3 .05 .09 .05 Q .38 -.02 .7 .17'],
    J:[.88,'M .12 1.39 Q .47 1.57 .94 1.46 Q .71 1.49 .64 1.45 L .5 .26 Q .42 -.26 .13 -.09 Q -.03 .02 .07 .24 Q .05 -.17 .39 -.04 Q .61 .04 .88 .18'],
    K:[1.12,'M 0 .07 Q .14 .03 .2 .21 L .24 1.52 L .2 .12 L .21 .69 L .97 1.52 L .36 .82 L .79 .25 Q .94 -.04 1.12 .15'],
    L:[1.04,'M .02 .16 Q .33 .33 .6 1.11 Q .78 1.68 .5 1.57 Q .23 1.47 .25 .76 Q .24 .22 .12 .07 Q .35 .16 .67 .06 Q .9 -.02 1.04 .21'],
    M:[1.37,'M 0 .06 Q .11 .05 .19 .23 L .33 1.49 L .62 .46 L 1.12 1.51 L 1.09 .19 Q 1.11 -.01 1.37 .15'],
    N:[1.13,'M 0 .06 Q .12 .04 .17 .24 L .26 1.5 L .83 .15 L .99 1.53 L .84 .22 Q .84 .01 1.13 .16'],
    O:[1.12,'M .54 .08 Q .1 .03 .13 .69 Q .16 1.47 .62 1.53 Q 1.13 1.59 1.01 .81 Q .91 .13 .54 .08 Q .83 .03 1.12 .16'],
    P:[.99,'M 0 .06 Q .14 .05 .2 .22 L .26 1.5 Q .93 1.67 .95 1.25 Q .97 .83 .23 .74 L .2 .22 Q .27 -.07 .99 .16'],
    Q:[1.17,'M .55 .08 Q .1 .03 .14 .74 Q .2 1.49 .64 1.53 Q 1.1 1.55 1.02 .82 Q .95 .14 .55 .08 L .65 .24 Q .88 -.13 1.17 .13'],
    R:[1.12,'M 0 .07 Q .13 .04 .2 .2 L .25 1.51 Q .91 1.67 .95 1.25 Q .98 .84 .24 .76 Q .51 .77 .66 .45 L .83 .18 Q .97 -.03 1.12 .16'],
    S:[1.02,'M .97 1.31 Q .79 1.65 .45 1.48 Q .05 1.26 .39 .96 L .69 .72 Q 1.15 .34 .71 .11 Q .34 -.1 .11 .19 Q .03 .32 .17 .37 Q .05 .22 .31 .1 Q .61 -.03 1.02 .17'],
    T:[1.19,'M 0 .15 Q .13 -.05 .33 .11 Q .47 .22 .5 .64 L .59 1.48 [ Q .29 1.52 .04 1.39 ] [ Q .82 1.58 1.07 1.49 ] L .5 .64 Q .43 -.08 .83 .08 L 1.03 .18'],
    U:[1.13,'M .06 1.44 Q .23 1.56 .25 1.46 L .16 .49 Q .14 -.12 .51 .06 Q .79 .24 .93 1.49 L .83 .25 Q .8 -.04 1.13 .16'],
    V:[1.12,'M .03 1.42 Q .25 1.65 .29 1.37 L .44 .06 Q .84 .69 1.02 1.39 Q 1.07 1.62 .94 1.46 Q .79 1.01 .59 .49 Q .55 .05 1.12 .16'],
    W:[1.47,'M .04 1.42 Q .24 1.62 .27 1.4 L .3 .09 Q .63 .58 .76 1.18 L .84 .1 Q 1.19 .69 1.34 1.43 Q 1.39 1.59 1.27 1.42 Q 1.1 .87 .97 .59 Q .82 .09 1.47 .17'],
    X:[1.05,'M 0 .11 Q .33 .33 .56 .78 [ L .96 1.52 ] [ L .1 1.45 ] L .9 .14 Q .94 .04 1.05 .15'],
    Y:[1.09,'M .04 1.44 Q .21 1.62 .3 1.36 L .53 .75 L .99 1.52 L .53 .75 L .43 .19 Q .42 -.03 .75 .08 L 1.09 .17'],
    Z:[1.07,'M .08 1.37 Q .4 1.61 .98 1.46 L .1 .09 Q .35 .24 .7 .09 Q .92 -.01 1.07 .19']
  };

  const letters = {...lowercase, ...capitals};
  const glyphCache = new Map();
  const minimumGrooves = 4.2;

  // A heart leaves a small window for its inscription. Upright capitals keep
  // the two bowls of B and the simple foot of L open at dinner-table size.
  const initials = {
    A:[.76,'M 0 0 L .17 .43 [ L .59 .43 ] L .38 1 L .76 0'],
    B:[.68,'M 0 0 L 0 1 L .31 1 Q .65 1 .65 .76 Q .65 .53 .32 .53 L 0 .53 L .32 .53 Q .70 .53 .70 .27 Q .70 0 .33 0 L 0 0'],
    C:[.70,'M .68 .87 Q .53 1 .36 1 Q 0 1 0 .5 Q 0 0 .36 0 Q .56 0 .70 .15'],
    D:[.72,'M 0 0 L 0 1 L .24 1 Q .72 1 .72 .5 Q .72 0 .24 0 L 0 0'],
    E:[.63,'M .63 1 L 0 1 L 0 .52 [ L .49 .52 ] L 0 0 L .63 0'],
    F:[.63,'M .63 1 L 0 1 L 0 .52 [ L .49 .52 ] L 0 0'],
    G:[.72,'M .69 .86 Q .51 1 .36 1 Q 0 1 0 .5 Q 0 0 .38 0 Q .58 0 .70 .10 L .70 .47 L .40 .47'],
    H:[.70,'M 0 0 L 0 .5 [ L 0 1 ] L .70 .5 [ L .70 1 ] L .70 0'],
    I:[.43,'M 0 1 L .215 1 [ L .43 1 ] L .215 0 [ L 0 0 ] L .43 0'],
    J:[.60,'M .60 1 L .60 .27 Q .60 0 .31 0 Q .07 0 0 .25'],
    K:[.70,'M 0 0 L 0 .40 [ L 0 1 ] L .17 .56 [ L .67 1 ] L .70 0'],
    L:[.63,'M 0 1 L 0 0 L .63 0'],
    M:[.91,'M 0 0 L 0 1 L .455 .32 L .91 1 L .91 0'],
    N:[.73,'M 0 0 L 0 1 L .73 0 L .73 1'],
    O:[.73,'M .365 0 Q 0 0 0 .5 Q 0 1 .365 1 Q .73 1 .73 .5 Q .73 0 .365 0'],
    P:[.67,'M 0 0 L 0 1 L .30 1 Q .67 1 .67 .73 Q .67 .47 .30 .47 L 0 .47'],
    Q:[.76,'M .76 0 L .51 .24 L .67 .08 Q .51 0 .36 0 Q 0 0 0 .5 Q 0 1 .36 1 Q .72 1 .72 .5 Q .72 .23 .67 .08'],
    R:[.70,'M 0 0 L 0 1 L .30 1 Q .67 1 .67 .73 Q .67 .47 .30 .47 [ L 0 .47 ] L .70 0'],
    S:[.66,'M .64 .85 Q .51 1 .32 1 Q .04 1 .04 .76 Q .04 .59 .34 .51 Q .65 .43 .65 .25 Q .65 0 .33 0 Q .11 0 0 .16'],
    T:[.75,'M 0 1 L .375 1 [ L .75 1 ] L .375 0'],
    U:[.72,'M 0 1 L 0 .31 Q 0 0 .36 0 Q .72 0 .72 .31 L .72 1'],
    V:[.78,'M 0 1 L .39 0 L .78 1'],
    W:[.96,'M 0 1 L .21 0 L .48 .67 L .75 0 L .96 1'],
    X:[.73,'M 0 1 L .365 .5 [ L .73 1 ] [ L 0 0 ] L .73 0'],
    Y:[.74,'M 0 1 L .37 .51 [ L .74 1 ] L .37 0'],
    Z:[.69,'M 0 1 L .69 1 L 0 0 L .69 0']
  };
  const initialCache=new Map();

  // Subdivide the drawn curves, including their extrema. Exact duplicate
  // coordinates make it possible to leave a word over its own strokes.
  function glyph(char,monogram=false) {
    const cache=monogram ? initialCache : glyphCache;
    if (cache.has(char)) return cache.get(char);
    const [advance, marks] = (monogram ? initials : letters)[char], tokens = marks.split(/\s+/);
    const points = [];
    let branch, i = 0;
    function pair() { return [+tokens[i++], +tokens[i++]]; }
    while (i < tokens.length) {
      const command = tokens[i++];
      if (command === '[') { branch = points.length - 1; continue; }
      if (command === ']') { points.push(...points.slice(branch, -1).reverse()); continue; }
      const next = pair();
      if (command === 'Q') {
        const a = points.at(-1), end = pair();
        const length = Math.hypot(a[0]-next[0], a[1]-next[1]) + Math.hypot(end[0]-next[0], end[1]-next[1]);
        const steps = Math.max(3, Math.ceil(length / .13));
        for (let k=1; k<=steps; k++) {
          const t=k/steps, s=1-t;
          points.push([s*s*a[0]+2*s*t*next[0]+t*t*end[0], s*s*a[1]+2*s*t*next[1]+t*t*end[1]]);
        }
      } else {
        points.push(next);
      }
    }
    const result={advance, points:monogram ? points : points.map(([x,y])=>[x+.12*y, y])};
    cache.set(char,result);
    return result;
  }

  function bounds(points) {
    let left=Infinity, right=-Infinity, low=Infinity, high=-Infinity;
    for (const [x,y] of points) {
      left=Math.min(left,x); right=Math.max(right,x); low=Math.min(low,y); high=Math.max(high,y);
    }
    return [left,low,right,high];
  }

  function letterRun(text) {
    const points=[], glyphs=[];
    let x=0;
    for (const char of text) {
      if (char === ' ') { x+=.69; continue; }
      const source=glyph(char), ink=source.points.map(([u,v])=>[u+x,v]);
      // A capital C, S, etc. normally begins near its upper right. When it
      // follows another letter, enter via its lower-left contour and trace
      // that same contour to its high start instead of cutting across the face.
      if (points.length && (ink[0][1]>.4 || ink[0][0]-x>.35)) {
        let entry=0, score=Infinity;
        for (let i=0;i<ink.length;i++) {
          const cost=(ink[i][0]-x)+Math.abs(ink[i][1]-.12)*1.7;
          if (cost<score) { score=cost; entry=i; }
        }
        points.push(...ink.slice(1,entry+1).reverse());
      }
      points.push(...ink);
      glyphs.push({char, points:ink});
      x+=source.advance+.055;
    }
    return {points, glyphs, bounds:bounds(points)};
  }

  // A hyphen joins the facing edges of its two runs at mid-height. Both
  // approaches follow existing letters. The space above and below the dash
  // stays clear, as it would between letters on paper.
  function dashPort(points, right, y=.52) {
    let best;
    for(let i=1;i<points.length;i++) {
      const a=points[i-1], b=points[i];
      if (a[1]===b[1] || (a[1]-y)*(b[1]-y)>0) continue;
      const x=a[0]+(b[0]-a[0])*(y-a[1])/(b[1]-a[1]);
      if (!best || (right?x>=best.x:x<best.x)) best={x,i,point:[x,y]};
    }
    return best;
  }

  function hyphenatedRow(text) {
    const trailing=text.endsWith('-');
    const runs=(trailing?text.slice(0,-1):text).split('-').map(letterRun);
    if (runs.length===1 && !trailing) return runs[0];
    const points=[], glyphs=[];
    let previousEnd=null, rightEdge=0;
    for (const [i,run] of runs.entries()) {
      const left=i?dashPort(run.points,false):null;
      const right=(i<runs.length-1 || trailing)?dashPort(run.points,true):null;
      const shift=left?Math.max(previousEnd[0]+.68-left.x,rightEdge+.08-run.bounds[0]):0;
      for (const p of new Set(run.points)) p[0]+=shift;
      if (left) {
        const entry=[left.x+shift,.52];
        points.push(entry,...loopErasedWalk(run.points.slice(0,left.i)).reverse());
        glyphs.push({char:'-',points:[previousEnd,entry]});
      }
      points.push(...run.points);
      glyphs.push(...run.glyphs);
      if (right) {
        previousEnd=[right.x+shift,.52];
        points.push(...loopErasedWalk(run.points.slice(right.i)).reverse(),previousEnd);
      }
      if (trailing && i===runs.length-1) {
        const tip=[previousEnd[0]+.68,.52];
        points.push(tip);
        glyphs.push({char:'-',points:[previousEnd,tip]});
      }
      rightEdge=run.bounds[2]+shift;
    }
    return {points,glyphs,bounds:bounds(points)};
  }

  function row(text) {
    if (!text.endsWith('!')) return hyphenatedRow(text);
    const r=hyphenatedRow(text.slice(0,-1)), port=dashPort(r.points,true,.72);
    const end=r.points.at(-1), x=Math.max(r.bounds[2]+.34,end[0]+.4);
    // The ball reaches the dot on a low underline. It reaches the upright
    // from the preceding letter. This leaves a real break between the two
    // components even though the complete inscription is one continuous path.
    const dot=[];
    const floor=r.bounds[1], leftEnd=r.bounds[0]+.18*(r.bounds[2]-r.bounds[0]);
    let start=0, lowest=Infinity;
    for (const [i,p] of r.points.entries()) {
      if (p[0]<=leftEnd && p[1]<lowest) { start=i; lowest=p[1]; }
    }
    const anchor=r.points[start];
    const dotY=.04;
    for (let i=0;i<=18;i++) {
      const angle=-Math.PI/2+i*Math.PI/9;
      dot.push([x+.10*Math.cos(angle),dotY+.10*Math.sin(angle)]);
    }
    const underline=[anchor], bottom=floor-.47;
    function cubic(c1,c2,end) {
      const a=underline.at(-1);
      for (let i=1;i<=12;i++) {
        const t=i/12, s=1-t;
        underline.push(a.map((value,j)=>s*s*s*value+3*s*s*t*c1[j]+3*s*t*t*c2[j]+t*t*t*end[j]));
      }
    }
    // Descend under the first letter before traversing the complete word.
    // The last upward turn lies beyond its rightmost edge, clear of g/y tails.
    const width=x-anchor[0];
    cubic([anchor[0],floor-.15],[anchor[0],bottom+.09],[anchor[0]+.2,bottom]);
    cubic([anchor[0]+width*.28,bottom-.17],[x-width*.25,bottom-.17],[x-.16,bottom]);
    cubic([x+.02,bottom+.05],[x,dotY-.21],[x,dotY-.10]);
    const shaft=[[x+.04,.72],[x+.23,1.68]];
    const toFoot=loopErasedWalk(r.points.slice(start)).reverse();
    const toPort=loopErasedWalk(r.points.slice(port.i)).reverse();
    r.points.push(...toFoot,...underline,...dot,...underline.slice().reverse(),...toFoot.slice().reverse(),...toPort,port.point,...shaft);
    r.glyphs.push({char:'!',points:shaft,strokes:[shaft,dot]});
    r.bounds=bounds(r.points);
    return r;
  }

  function loopErasedWalk(points) {
    const walk=[], seen=new Map();
    const key=p=>Math.round(p[0]*1e7)+','+Math.round(p[1]*1e7);
    for (const p of points) {
      const k=key(p);
      if (seen.has(k)) {
        while (walk.length>seen.get(k)+1) seen.delete(key(walk.pop()));
      } else {
        seen.set(k,walk.length);
        walk.push(p);
      }
    }
    return walk;
  }

  function layout(lines) {
    const rows=lines.map(row);
    let baseline=0;
    for (const [i,r] of rows.entries()) {
      if (i) baseline=rows[i-1].bounds[1]-r.bounds[3]-.47;
      const center=(r.bounds[0]+r.bounds[2])/2;
      // Glyphs and their line share these arrays, so each point is moved once.
      for (const p of new Set(r.points)) { p[0]-=center; p[1]+=baseline; }
      r.bounds=bounds(r.points);
    }
    const path=rows[0].points.slice();
    if (rows.length===2) {
      // The lower line is engraved from right to left. Its letters have their
      // ordinary orientation. The one joining stroke curls around the outside
      // of both line endings, never through a letter or its descending tail.
      const top=rows[0], lower=rows[1], a=path.at(-1), b=lower.points.at(-1);
      const outer=Math.max(top.bounds[2],lower.bounds[2])+.28;
      for (let step=1;step<=24;step++) {
        const t=step/24, s=1-t;
        path.push([s*s*s*a[0]+3*s*t*outer+t*t*t*b[0],
                   s*s*s*a[1]+3*s*s*t*(a[1]+.08)+3*s*t*t*(b[1]-.02)+t*t*t*b[1]]);
      }
      path.push(...lower.points.slice(0,-1).reverse());
    }
    const box=bounds(path), cx=(box[0]+box[2])/2, cy=(box[1]+box[3])/2;
    let radius=0;
    for (const [x,y] of path) radius=Math.max(radius,Math.hypot(x-cx,y-cy));
    const scale=.965/radius;
    const place=([x,y])=>[(x-cx)*scale,(y-cy)*scale];
    const back=loopErasedWalk(path).slice(0,-1).reverse();
    return {lines, scale, path:path.concat(back).map(place), glyphs:rows.flatMap((r,line)=>
      r.glyphs.map(({char,points,strokes})=>{
        const ink=points.map(place);
        if (strokes) {
          const parts=strokes.map(stroke=>stroke.map(place));
          return {char,line,points:ink,strokes:parts,bounds:bounds(parts.flat())};
        }
        return {char,line,points:ink,bounds:bounds(ink)};
      }))};
  }

  function design(text, {groove,singleLine=false}={}) {
    if (!Number.isFinite(groove) || groove<=0) throw Error('This garden is missing its groove width.');
    if (typeof text!=='string') throw Error('Enter a name or a short greeting.');
    const label=text.trim().replace(/\s+/g,' ');
    if (!label) throw Error('Enter a name or a short greeting.');
    if (!/^[A-Za-z]+(?:[ -][A-Za-z]+)*!?$/.test(label)) {
      throw Error('Use A to Z, spaces, a hyphen between letters, or an exclamation mark at the end.');
    }
    if (label.length>40) throw Error('Use up to 40 letters and spaces for a short greeting.');
    let best=layout([label]);
    for (let i=1;!singleLine && i<label.length-1;i++) {
      if (label[i]!==' ' && label[i]!=='-') continue;
      const end=label[i]==='-'?i+1:i;
      const pair=layout([label.slice(0,end),label.slice(i+1)]);
      // A small gain does not justify breaking a natural one-line greeting.
      if (pair.scale>best.scale*(best.lines.length===1?1.06:1)) best=pair;
    }
    const xHeightGrooves=best.scale/groove;
    const legible=xHeightGrooves>=minimumGrooves && best.path.length<=8000;
    return {...best,label,xHeightGrooves,minimumGrooves,legible,
      reason:legible?'':'That would make the letters too small for this place. Try a shorter greeting or initials.'};
  }
  function inHeart(text,{groove}) {
    if (!/^[A-Z]{1,2}$/.test(text)) throw Error('Choose one or two initials from A to Z for the heart.');
    // Both lobes have the same crown. Their central cleft stays above the
    // capitals. The tapered lower half gives the ball an entrance at the tip.
    const side=[[0,-.96]];
    function curve(a,b,end) {
      const start=side.at(-1);
      for (let i=1;i<=24;i++) {
        const t=i/24,s=1-t;
        side.push([0,1].map(k=>s**3*start[k]+3*s*s*t*a[k]+3*s*t*t*b[k]+t**3*end[k]));
      }
    }
    curve([-.19,-.67],[-.89,-.25],[-.93,.26]);
    curve([-.98,.71],[-.50,.92],[-.24,.75]);
    curve([-.13,.69],[-.06,.59],[0,.49]);
    const outlineScale=.97/Math.max(...side.map(p=>Math.hypot(...p)));
    const heart=side.concat(side.slice(0,-1).reverse().map(([x,y])=>[-x,y]))
      .map(([x,y])=>[outlineScale*x,outlineScale*y]);
    const caps=Array.from(text,char=>glyph(char,true)),gap=.32;
    const width=caps.reduce((w,g)=>w+g.advance,0)+(caps.length-1)*gap;
    const height=Math.min(.70,1.17/width);
    // A lone upright can meet the frame at its foot, leaving space between
    // the letter's top and the notch. A pair fills the broader band above.
    const centerY=caps.length===1 ? -.09 : .04;
    let x=-width/2;
    const letters=caps.map(cap=>{
      const ink=cap.points.map(([u,v])=>[(x+u)*height,(v-.5)*height+centerY]);
      x+=cap.advance+gap;
      return ink;
    });
    const legible=height>=minimumGrooves*groove;
    const path=GuestArt.manageStrokes([heart,...letters],heart[0],{joinEdges:true});
    return {label:text,legible,path,heart,letters,capHeightGrooves:height/groove,
      reason:legible?'':'These initials are too small for this place. Try a single initial.'};
  }
  // Each capital stays rigid on its own tangent to the Mini's lower rim.
  // The inward spiral can visit these letters individually, leaving gaps.
  function rimName(text,groove) {
    if(!/^[a-z]+(?: [a-z]+)*$/i.test(text))return null;
    const label=text.toUpperCase(), height=4.65*groove, radius=1-1.85*groove;
    const spacing=.38, midRadius=radius-height/2;
    const letters=Array.from(label,ch=>ch===' ' ? {advance:.58} : glyph(ch,true));
    const width=height*(letters.reduce((sum,l)=>sum+l.advance,0)+(letters.length-1)*spacing);
    if(width/(2*midRadius)>1.15)return null;
    let next=-width/2;
    const strokes=[];
    for(const {points,advance} of letters){
      const angle=(next+advance*height/2)/midRadius;
      next+=height*(advance+spacing);
      if(!points)continue;
      const nx=Math.sin(angle),ny=-Math.cos(angle);
      const ink=points.map(([x,y])=>{
        const along=(x-advance/2)*height, r=radius-y*height;
        return [r*nx-along*ny,r*ny+along*nx];
      });
      // Open capitals must return over the engraving. Closing them directly
      // would draw a diagonal across letters such as L.
      strokes.push({normal:[nx,ny], path:ink.concat(ink.slice(1,-1).reverse())});
    }
    return {label,strokes,topRadius:radius-height};
  }
  return {design,inHeart,rimName};
})();
