#!/usr/bin/env python3
"""Generate theta-rho patterns for the Oasis Mini (and any Sisyphus-style sand table).

Output is a .thr file: one "<theta> <rho>" pair per line, theta in radians (absolute,
monotonic - the ball's arm angle, winding up over many turns), rho the normalized
radius 0.0 (center) .. 1.0 (rim). This is the de-facto standard understood by
Sandify, dune-weaver and Sisyphus. Whether the Oasis player wants exactly this
(vs rho scaled to a step count, or theta wrapped) is being confirmed from the
firmware; the generator keeps theta absolute and rho in 0..1 so it's easy to rescale.

Patterns here are ours (math), nothing from Grounded. Usage:
    thr_gen.py spiral   out.thr [--loops 40]
    thr_gen.py star     out.thr [--points 5 --layers 60]
    thr_gen.py rose     out.thr [--k 7 --loops 1]
    thr_gen.py heart    out.thr            # a single heart outline, centered
Run with no args for a quick self-test that prints stats for each.
"""
import argparse, math

def _write(path, pts):
    # clamp rho into [0,1]; keep full precision on theta
    with open(path, "w") as f:
        for th, r in pts:
            f.write(f"{th:.5f} {max(0.0,min(1.0,r)):.5f}\n")
    return len(pts)

def spiral(loops=40, step_deg=2.0):
    pts=[]; n=int(loops*360/step_deg)
    for i in range(n+1):
        th=math.radians(i*step_deg); r=i/n
        pts.append((th,r))
    # wind back in to leave the ball at center
    for i in range(n, -1, -1):
        th=math.radians((2*n-i)*step_deg) if False else math.radians(i*step_deg)+2*math.pi*loops
        pts.append((th, i/n))
    return pts

def rose(k=7, loops=1, step_deg=0.5):
    pts=[]; n=int(loops*360/step_deg)
    for i in range(n+1):
        th=math.radians(i*step_deg); r=abs(math.cos(k*th))
        pts.append((th,r))
    return pts

def star(points=5, layers=60, step_deg=1.0):
    # a star polygon traced repeatedly while slowly growing, giving a dense star field
    pts=[]; n=int(layers*360/step_deg)
    for i in range(n+1):
        th=math.radians(i*step_deg)
        # radius oscillates between inner/outer to make points
        phase=(th*points)%(2*math.pi)
        tip=abs(math.cos(phase/2))**3
        r=(0.15+0.85*tip)*(i/n)
        pts.append((th,r))
    return pts

def heart(step_deg=1.0, turns_in=8):
    # classic heart curve mapped to polar, drawn once, with a spiral in and out
    pts=[]
    # spiral out to the heart's scale
    for i in range(int(turns_in*360/step_deg)+1):
        th=math.radians(i*step_deg); pts.append((th, (i/(turns_in*360/step_deg))*0.2))
    base=pts[-1][0]
    N=720
    for i in range(N+1):
        t=2*math.pi*i/N
        x=16*math.sin(t)**3
        y=13*math.cos(t)-5*math.cos(2*t)-2*math.cos(3*t)-math.cos(4*t)
        r=math.hypot(x,y)/17.0
        th=base+math.atan2(y,x)+ (2*math.pi if math.atan2(y,x)<0 else 0)
        pts.append((th, r))
    return pts

BUILDERS={"spiral":spiral,"rose":rose,"star":star,"heart":heart}

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("pattern", nargs="?", choices=list(BUILDERS))
    ap.add_argument("out", nargs="?")
    ap.add_argument("--loops", type=int, default=40)
    ap.add_argument("--points", type=int, default=5)
    ap.add_argument("--layers", type=int, default=60)
    ap.add_argument("--k", type=int, default=7)
    a=ap.parse_args()
    if not a.pattern:
        for name,fn in BUILDERS.items():
            pts=fn()
            ths=[p[0] for p in pts]; rs=[p[1] for p in pts]
            print(f"{name:7s} {len(pts):5d} pts  theta {min(ths):.1f}..{max(ths):.1f} rad  rho {min(rs):.2f}..{max(rs):.2f}")
        return
    if a.pattern=="spiral": pts=spiral(a.loops)
    elif a.pattern=="rose": pts=rose(a.k)
    elif a.pattern=="star": pts=star(a.points,a.layers)
    else: pts=heart()
    print("wrote", _write(a.out, pts), "points to", a.out)

if __name__=="__main__": main()
