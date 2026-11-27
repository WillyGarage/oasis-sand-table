"""The model's drawing square is a framing suggestion, not a crop."""
import json
import unittest

from phrase_drawing import radial_png, radial_request, reference_png, separate_blades


class PhraseDrawingTests(unittest.TestCase):
    def test_repeated_parts_are_rotated_around_the_requested_center(self):
        fixed = "M 50 52 L 50 90"
        model = {"hub": [50, 30], "unit": [{"path": "M 50 30 L 60 29 L 67 23 Z"}],
                 "strokes": [{"path": fixed}]}
        manual = [fixed, "M 50 30 L 60 29 L 67 23 Z", "M 50 30 L 51 40 L 57 47 Z",
                  "M 50 30 L 40 31 L 33 37 Z", "M 50 30 L 49 20 L 43 13 Z"]
        self.assertEqual(radial_png(json.dumps(model), 4), reference_png(manual))

    def test_optional_rotation_preserves_other_requests(self):
        for words, count in (("Four-bladed paper pinwheel on a stick", 4),
                             ("a six-spoked wagon wheel", 6), ("a flower with 5 petals", 5),
                             ("a pinwheel with four folded paper blades", 4)):
            self.assertEqual(radial_request(words)[0], count)
        for words in ("two blades on a pair of scissors", "a tabletop fan", "a wheelbarrow",
                      "a flower with five petals on a six-spoked wheel", "a flower beside two blades of grass",
                      "four blades of grass beside a fan"):
            self.assertIsNone(radial_request(words))

    def test_adjoining_blades_have_an_open_gap_in_sand(self):
        import numpy as np
        tiled = np.array([[0, 0], [28, 0], [0, -28], [0, 0]], dtype=float)
        hub = np.zeros(2)
        fitted, = separate_blades([tiled], hub, 4)
        np.testing.assert_allclose(fitted[[0, -1]], [[0, 0], [0, 0]])
        tips = fitted[1:3]
        radii = np.linalg.norm(tips, axis=1)
        self.assertAlmostEqual(max(radii), 28)
        self.assertLess(min(radii), 20)
        angle = np.degrees(np.arccos((tips[0] @ tips[1]) / np.prod(radii)))
        self.assertGreater(90-angle, 25)
        narrow = np.array([[0, 0], [28, 0], [25, -5], [0, 0]], dtype=float)
        np.testing.assert_array_equal(separate_blades([narrow], hub, 4)[0], narrow)

    def test_invalid_repeated_unit(self):
        for hub, unit in (([50, 30], []), ([20], [{"path": "M 1 3 L 4 5"}]), ([50, 50], [None])):
            with self.assertRaisesRegex(ValueError, "invalid hub or repeated part"):
                radial_png(json.dumps({"hub": hub, "unit": unit, "strokes": []}), 6)

    def test_part_extending_past_right_edge(self):
        # The local model put the end of a tilted lamp shade at x=105.
        self.assertEqual(reference_png(['M 75 26 L 85 25', 'M 85 25 L 95 15 L 105 35 L 95 45 Z']),
                         reference_png(['M 55 26 L 65 25', 'M 65 25 L 75 15 L 85 35 L 75 45 Z']))

    def test_nonfinite_coordinate(self):
        with self.assertRaisesRegex(ValueError, 'invalid coordinate'):
            reference_png(['M 20 20 L '+('9'*400)+' 50'])

    def test_negative_coordinates(self):
        self.assertEqual(reference_png(['M -5 15 Q 0 5 10 15 L 5 30 Z']),
                         reference_png(['M 5 15 Q 10 5 20 15 L 15 30 Z']))


if __name__ == '__main__':
    unittest.main()
