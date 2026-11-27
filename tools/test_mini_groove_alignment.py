"""The optional camera alignment uses distinct opening grooves spread across the Mini."""
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

import cv2
import numpy as np

from mini_bed_preview import disk
from mini_groove_alignment import groove_alignment
from mini_inward_preview import aligned_groove_light, signed_replay


class OpeningGrooveAlignmentTest(unittest.TestCase):
    def test_recovers_small_similarity_at_registered_photo_sizes(self):
        for size in (390, 780, 1040):
            with self.subTest(size=size):
                scale = size / 780
                rng = np.random.default_rng(23)
                raw = rng.normal(size=(size, size)).astype(np.float32)
                relief = cv2.GaussianBlur(raw, (0, 0), 2.4*scale)
                model = 130 + 16 * relief / relief.std()
                matrix = cv2.getRotationMatrix2D(((size-1)/2, (size-1)/2), .45, .989)
                matrix[:, 2] += scale * np.array((2.1, -1.75))
                photo = cv2.warpAffine(model, matrix, (size, size))
                x, y = disk(model.shape)
                valid = np.hypot(x, y) < .92
                result = groove_alignment(model, photo, valid)
                self.assertIsNotNone(result)
                corners = np.float32([[[0, 0], [0, size], [size, 0], [size, size]]])
                error = cv2.transform(corners, result) - cv2.transform(corners, matrix)
                self.assertLess(np.linalg.norm(error, axis=2).max(), .35 * scale)

    def test_blank_parallel_repeated_intersections_and_single_local_feature(self):
        size = 390
        y, x = np.indices((size, size), dtype=np.float32)
        waves = 8 * np.sin(2*np.pi*x/6)
        checkered = waves + 9 * np.cos(2*np.pi*y/6)
        concentrated = np.zeros_like(x)
        concentrated[92:130, 253:278] = checkered[92:130, 253:278]
        for name, model in (('blank', np.zeros_like(x)), ('parallel', waves),
                            ('repeated crossings', checkered), ('single cluster', concentrated)):
            with self.subTest(name=name):
                # Include two competing identical offsets in the search range.
                photo = np.roll(model, (2, 2), axis=(0, 1))
                valid = np.hypot(x-size/2, y-size/2) < .46*size
                self.assertIsNone(groove_alignment(model, photo, valid))

    def test_no_support_preserves_the_exact_input_prediction(self):
        size = 390
        y, x = np.indices((size, size), dtype=np.float32)
        prior = np.sin(x/3)
        current = np.cos(y/3)
        opening = np.full_like(prior, 135)
        baseline = (125 + 15 * current).astype(np.uint8)
        result = aligned_groove_light(opening, (0, 1), prior, current, np.ones_like(prior), baseline)
        np.testing.assert_array_equal(result, baseline)

    def test_signed_cli_matches_the_frozen_pair_and_preserves_its_uncorrected_preview(self):
        # The original camera files stay outside git. A worktree can point
        # this test at the Mini's local captures, without copying the photos.
        tool = Path(__file__).resolve().with_name('mini_inward_preview.py')
        captures = Path(os.environ.get('OASIS_CAPTURE_DIR', tool.parents[1] / 'captures'))
        previous = captures / 'mini-thomas-moustache-real/physical'
        boardwalk = captures / 'mini-inward-family-pair/real/physical'
        frozen = captures / 'mini-feature-light/mini-inward-family-pair'
        if not (frozen / 'aligned.png').is_file():
            self.skipTest('The local held-out boardwalk captures are unavailable.')
        base = cv2.imread(str(frozen / 'base.png'), cv2.IMREAD_GRAYSCALE)
        aligned = cv2.imread(str(frozen / 'aligned.png'), cv2.IMREAD_GRAYSCALE)
        expected = cv2.addWeighted(base, .5, aligned, .5, 0)
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'predicted.png'
            command = [sys.executable, str(tool), '--signed-only', '--previous', str(previous/'submitted.thr'),
                       '--opening', str(previous/'after-full-b-rect.png'), '--drawing', str(boardwalk/'submitted.thr'),
                       '--out', str(path)]
            for option, reference in [('--photographic-ripples', base), ('--align-photo-grooves', expected)]:
                with self.subTest(option=option):
                    subprocess.run([*command, option], check=True, capture_output=True)
                    image = cv2.imread(str(path), cv2.IMREAD_GRAYSCALE)
                    np.testing.assert_array_equal(image, reference)

    def test_requires_the_complete_signed_drawing_and_its_opening(self):
        route = np.array([[0, 1], [.01, 1]])
        with self.assertRaisesRegex(ValueError, 'complete signed drawing'):
            signed_replay(route, route, 2, align_photo_grooves=True)
        with self.assertRaisesRegex(ValueError, 'complete signed drawing'):
            signed_replay(route, route, 1, opening=np.zeros((390, 390)), align_photo_grooves=True)


if __name__ == '__main__':
    unittest.main()
