"""Bend the clearing turns under photographed cheek and jaw shadows."""
import cv2
import numpy as np

from wide_portrait_hair import FACE_OVAL, inner_distance, mask_for, pick_face
from wide_portrait_rake import save_raked_field

# Lower half of MediaPipe's face oval, in order from ear to ear.
JAW = [234, 93, 132, 58, 172, 136, 150, 149, 176, 148, 152,
       377, 400, 378, 379, 365, 397, 288, 361, 323, 454]


def cheek_displacement(photo, source, marks, translation):
    """Return the proposed X/Y offsets in mm and the crop's coordinate transform."""
    gray, meshes, _ = photo
    size = len(gray)
    scale = size / source['diameter']
    axes = np.array([scale, -scale])
    offset_mm = np.asarray(translation) if translation is not None else np.zeros(2)
    origin = size / 2 - offset_mm * axes
    groove = scale * source['width']

    def pixels(mark):
        return np.asarray(mark['points']) * axes + origin

    head = next((m for m in marks if m['kind'] == 'head'), None)
    eyes = [pixels(m).mean(axis=0) for m in marks if m['kind'] == 'eye']
    if len(eyes) != 2:
        eyes = [pixels(m).mean(axis=0) for m in marks if m['kind'] == 'glasses']
    mouth = next((pixels(m).mean(axis=0) for m in marks if m['kind'] == 'smile'), None)
    if head is None or len(eyes) != 2 or mouth is None:
        raise ValueError('The eyes and smile need to fit before the cheeks can be shaded.')
    mesh = pick_face(meshes, np.array([*sorted(eyes, key=lambda eye: eye[0]), mouth]))

    left, right = mesh[[468, 473]]
    span = np.linalg.norm(right - left)
    if span < 4 * groove:
        raise ValueError('The selected face has too little room for separate cheek shading.')
    across = (right - left) / span
    down = np.array([-across[1], across[0]])
    center = (left + right) / 2
    yy, xx = np.indices(gray.shape, dtype=np.float32)
    x = ((xx - center[0]) * across[0] + (yy - center[1]) * across[1]) / span
    y = ((xx - center[0]) * down[0] + (yy - center[1]) * down[1]) / span
    chin = (mesh[152] - center) @ down / span
    face = mask_for(gray.shape, mesh[FACE_OVAL]) & mask_for(gray.shape, pixels(head))
    cheeks = (face > 0) & (abs(x) > .26) & (y > .09) & (y < chin - .04)
    if cheeks.sum() < 12 * groove**2:
        raise ValueError('There is too little cheek visible in this crop.')

    # Use broad photographic tones and taper before other engraved features.
    smooth_gray = cv2.bilateralFilter(gray, 11, 21, 8).astype('float32')
    light = cv2.GaussianBlur(smooth_gray, (0, 0), .77 * groove)
    low, high = np.percentile(light[cheeks], [11, 78])
    if high - low < 18:
        raise ValueError('This photo has too little light and shadow across the cheeks.')
    protected = np.zeros(gray.shape, np.uint8)
    for mark in marks:
        if mark['kind'] != 'shade':
            line = np.rint(pixels(mark)).astype('int32')
            cv2.polylines(protected, [line], mark['closed'], 1, 1)
    darkness = np.clip((high - light) / (high - low), 0, 1)
    shade = cv2.GaussianBlur(darkness, (0, 0), .5 * groove)
    shade *= np.clip(inner_distance(cheeks) / (2 * groove), 0, 1)
    shade *= np.clip((inner_distance(1 - protected) / groove - 1.1) / 1.85, 0, 1)
    if (shade > .35).sum() < 5 * groove**2:
        raise ValueError('This cheek shadow is too small to engrave separately.')

    # Blend distance from the jaw with vertical distance along the tilted face.
    # Compress neighboring rake turns perpendicular to these contours in shadow.
    jawline = np.zeros(gray.shape, np.uint8)
    cv2.polylines(jawline, [np.rint(mesh[JAW]).astype('int32')], False, 1, 1)
    contour = (.68 * inner_distance(1 - jawline) - .54 * y * span) / scale + 5.3 * shade
    dy, dx = np.gradient(contour)
    norm = np.maximum(np.hypot(dx, dy), 1e-6)
    spacing_mm = 10.9
    phase = (contour / spacing_mm) % 1
    compressed = (np.tanh(8 * (phase - .5)) + np.tanh(4)) / (2 * np.tanh(4))
    offset = np.clip((compressed - phase) * spacing_mm * shade, -1.82, 1.82)
    field = np.dstack((offset * dx / norm, -offset * dy / norm)).astype('float32')
    return field, origin, axes


def save_cheek_print(page, source, marks, plan, photo, translation, directory):
    if (abs(source['radius'] - 420) > .001 or abs(source['diameter'] - 632.8) > .01
            or abs(source['width'] - 7) > .001):
        raise ValueError('Cheek shading needs the wide portrait area with a 7 mm groove.')
    if photo is None or not marks or not plan.get('events'):
        raise ValueError('The selected face could not be matched to a cheek shadow.')
    field, origin, axes = cheek_displacement(photo, source, marks, translation)
    saved = save_raked_field(page, source, plan, field, origin, axes, directory)
    return {**saved, 'applied': True}
