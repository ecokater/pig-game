#!/usr/bin/env python3
"""Focused regression tests for Redirect rule semantics."""
import json
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from generate_levels import _slide


class MechanicsTest(unittest.TestCase):
    def test_redirect_turns_during_same_slide(self):
        pen = {(0, 0), (0, 1), (1, 0), (1, 1)}
        acted, tail, head, direction, mask = _slide(
            pen, set(), set(), (-2, 0), (-1, 0), (1, 0),
            {(0, 0): (0, 1)}, {}, 0)
        self.assertTrue(acted)
        self.assertEqual((tail, head), ((0, 0), (0, 1)))
        self.assertEqual(direction, (0, 1))
        self.assertEqual(mask, 0)

    def test_multiple_redirects_in_one_slide(self):
        pen = {(0, 0), (0, 1), (1, 1), (2, 1)}
        acted, tail, head, direction, mask = _slide(
            pen, set(), set(), (-2, 0), (-1, 0), (1, 0),
            {(0, 0): (0, 1), (0, 1): (1, 0)}, {}, 0)
        self.assertTrue(acted)
        self.assertEqual((tail, head), ((1, 1), (2, 1)))
        self.assertEqual(direction, (1, 0))
        self.assertEqual(mask, 0)

    def test_final_set_has_mechanic_progression_after_sorting(self):
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        with open(os.path.join(root, 'levels.json')) as f:
            levels = json.load(f)
        redirect_ids = [i for i, level in enumerate(levels)
                        if level.get('redirects')]
        self.assertEqual(len(levels), 1000)
        self.assertFalse(any('gates' in level for level in levels))
        self.assertGreaterEqual(len(redirect_ids), 900)
        self.assertGreaterEqual(sum(len(level.get('redirects', [])) >= 2
                                    for level in levels), 450)
        late = levels[900:]
        self.assertGreaterEqual(sum(bool(level.get('redirects')) for level in late), 95)
        self.assertTrue(all(len(level.get('redirects', [])) == 3
                            for level in late))


if __name__ == '__main__':
    unittest.main()
