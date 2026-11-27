"""Place a photo's people together, retaining their head sizes, tilt, and relative positions.

MediaPipe supplies a shared foreground and individual face landmarks. The connected outlines
and their fill are routed by the same make_people builder used for individual portraits.
"""
import json
import math
import os
import time
import cv2
import numpy as np


def run(photo, out, bgr, faces, confidence, started):
    # photo2sand imports this on demand, after its shared constants/functions are defined.
    import photo2sand as p
    import make_people as people
    import brighten
    import sandsim
    import thrcommon

    h, w = bgr.shape[:2]
    bbox = lambda L: (np.ptp(L[:, 0]), np.ptp(L[:, 1]))
    mark = [(L, bbox(L)) for L, _ in faces]
    # On a group picture, too-small faces are often missed in the full frame. The segmentation
    # mask keeps those people in the silhouette even when we have no eye or nose landmarks.
    fg = confidence[p.CLS['bg']] < .45
    # Include shoulders but crop clutter below them, in the same coordinate space for every
    # subject. Keep every foreground component that touches a marked face or is larger than
    # one quarter of the smallest head, so a turned-away guest stays in the composition.
    n, labels, stats, _ = cv2.connectedComponentsWithStats(fg.astype(np.uint8))
    min_face_area = min((dx * dy for _, (dx, dy) in mark), default=h*w/18)
    remove = np.flatnonzero(stats[:, cv2.CC_STAT_AREA] < min_face_area*.25)
    fg &= ~np.isin(labels, remove)
    if not fg.any():
        raise ValueError('No people separated from the background. Choose a closer group photo.')
    yy, xx = np.nonzero(fg)
    left, right = int(xx.min()), int(xx.max()+1)
    top, bottom = int(yy.min()), int(yy.max()+1)
    if mark:
        shoulder = max(L[p.CHIN, 1] + .62*dy for L, (_,dy) in mark)
        bottom = min(bottom, max(top+1, math.ceil(shoulder)))
    # Actual radii of the visible pixel corners determine the common scale. This uses more
    # sand than fitting the rectangular photo's corners into the disc, especially for a row.
    fg[:top] = False
    fg[bottom:] = False
    yy, xx = np.nonzero(fg)
    cx, cy = (left+right)/2, (top+bottom)/2
    radius = np.hypot(xx-cx, yy-cy).max()
    scale = p.S*.966/max(radius, 1.)
    A = np.array([[scale,0,300-scale*cx],[0,scale,300-scale*cy]])
    def to_canvas(points):
        return np.asarray(points) @ A[:, :2].T + A[:, 2]
    def warp(mask):
        return cv2.warpAffine(mask.astype(np.uint8), A*p.F, (p.W,p.W), flags=cv2.INTER_NEAREST) > 0
    def feature(poly):
        mask = np.zeros((p.W,p.W), np.uint8)
        cv2.fillPoly(mask, [(np.asarray(poly)*p.F).astype(np.int32)], 1)
        return mask > 0

    shape = warp(fg)
    rm = int(p.GROOVE_U*p.F*.24) | 1
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (rm,rm))
    smooth = lambda m: cv2.morphologyEx(cv2.morphologyEx(m.astype(np.uint8), cv2.MORPH_OPEN, kernel),
                                        cv2.MORPH_CLOSE, kernel) > 0
    shape = smooth(shape)
    if not shape.any():
        raise ValueError('The subjects are too small for a readable drawing.')
    mapped=[to_canvas(L) for L, _ in mark]
    cut = np.zeros_like(shape)
    face = warp(confidence[p.CLS['face']] > .43) & shape
    hair = warp(confidence[p.CLS['hair']] > .45) & shape
    for L in mapped:
        # Retain the real jaw rather than allowing the neck to merge with the chin.
        face |= feature(L[p.OVAL]) & shape & ~hair
        face_width = np.ptp(L[p.OVAL, 0])
        if face_width < 5*p.GROOVE_U:
            continue
        for e in (p.EYE_A, p.EYE_B):
            center, ew, eh, angle = p.eye_info(L,e)
            cut |= feature(people.ellipse(tuple(center), max(ew*.41,.32*p.GROOVE_U),
                                           max(eh*.45,.25*p.GROOVE_U), angle))
        cut |= feature(L[p.LIPS_OUT])

    # Route among shoulders first. Enter from the point on the rim nearest a shoulder,
    # so the inevitable new groove is short and never crosses anyone's face.
    face = smooth(face & shape)
    hair = smooth(hair & ~face & shape)
    clothing = smooth(shape & ~face & ~hair)
    if clothing.sum() < 300: clothing, face = shape, np.zeros_like(shape)
    ys, xs = np.nonzero(clothing)
    phi = np.arctan2(ys/p.F-300,xs/p.F-300)
    # Bottom half if available; don't put the approach across the top of the group.
    score = np.hypot(xs/p.F-300, ys/p.F-300) - np.maximum(0, -np.sin(phi))*p.S
    k = int(np.argmax(score))
    angle = float(phi[k])
    start = (300+p.S*math.cos(angle),300+p.S*math.sin(angle))
    regs=[]
    for name, mask, levels, density in [('clothing',clothing,3,1.55),('face',face & ~cut,3,1.45),
                                        ('hair',hair,4,1.15)]:
        if mask.sum()>300:
            regs.append(dict(name=name, mask=mask.astype(np.uint8)*255, levels=levels, pitch=density))
    path,nloops=people.build(dict(regions=regs,start=start))
    count=p.write_thr(path,out+'.thr')
    pts=np.loadtxt(out+'.thr',comments='#',ndmin=2)
    dxy=np.column_stack((pts[:,1]*np.cos(pts[:,0]),pts[:,1]*np.sin(pts[:,0])))
    longest_step=float(np.linalg.norm(np.diff(dxy,axis=0),axis=1).max())
    if not (np.isfinite(pts).all() and count <= 11998 and pts[:,1].min() >= .01
            and pts[:,1].max() <= 1 and longest_step <= .025):
        os.unlink(out+'.thr')
        raise ValueError('This group exceeds the table drawing limits. Try a tighter crop.')
    im=sandsim.render(pts,size=900,real=True)
    preview=brighten.brighten(cv2.cvtColor(np.asarray(im),cv2.COLOR_RGB2BGR))
    cv2.imwrite(out+'_preview.jpg',preview,[cv2.IMWRITE_JPEG_QUALITY,92])
    overlay=bgr.copy()
    contours,_=cv2.findContours(fg.astype(np.uint8),cv2.RETR_EXTERNAL,cv2.CHAIN_APPROX_SIMPLE)
    cv2.drawContours(overlay,contours,-1,(80,210,130),2)
    for L,_ in faces:
        cv2.polylines(overlay,[L[p.OVAL].astype(np.int32)],True,(215,240,255),2)
    cv2.imwrite(out+'_debug.jpg',overlay)
    report=dict(photo=os.path.basename(photo),mode='group',faces_found=len(faces),points=count,
                loops=nloops,draw_minutes_est=round(thrcommon.est_minutes(pts),1),
                face_centres_in_drawing=[np.round((L[p.NOSE_TIP]-[300,300])/[p.S,-p.S],3).tolist() for L in mapped],
                geometry=dict(maximum_step=round(longest_step,4), min_radius=float(pts[:,1].min()),
                              max_radius=float(pts[:,1].max())),seconds=round(time.time()-started,1))
    with open(out+'.json','w') as f:
        json.dump(report,f,indent=1)
    return 0
