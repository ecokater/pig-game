#!/usr/bin/env python3
"""Focused regression tests for Redirect and Mud rule semantics."""
import json
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from generate_levels import _slide


class MechanicsTest(unittest.TestCase):
    def test_mud_stops_slide_immediately(self):
        pen = {(0, 0), (1, 0), (2, 0), (3, 0)}
        acted, tail, head, direction, mask = _slide(
            pen, set(), set(), (-2, 0), (-1, 0), (1, 0),
            {}, {}, 0, {(1, 0)})
        self.assertTrue(acted)
        self.assertEqual((tail, head), ((0, 0), (1, 0)))
        self.assertEqual(direction, (1, 0))
        self.assertEqual(mask, 0)

    def test_mud_pig_continues_on_second_tap(self):
        pen = {(0, 0), (1, 0), (2, 0), (3, 0)}
        acted, tail, head, direction, _ = _slide(
            pen, set(), set(), (0, 0), (1, 0), (1, 0),
            {}, {}, 0, {(1, 0)})
        self.assertTrue(acted)
        self.assertEqual((tail, head), ((2, 0), (3, 0)))
        self.assertEqual(direction, (1, 0))

    def test_redirect_then_mud_in_one_slide(self):
        pen = {(0, 0), (0, 1), (0, 2), (0, 3)}
        acted, tail, head, direction, _ = _slide(
            pen, set(), set(), (-2, 0), (-1, 0), (1, 0),
            {(0, 0): (0, 1)}, {}, 0, {(0, 1)})
        self.assertTrue(acted)
        self.assertEqual((tail, head), ((0, 0), (0, 1)))
        self.assertEqual(direction, (0, 1))
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
        # 泥坑:中后段新机制,不碰教学开局与三箭头决赛段
        mud_ids = [i for i, level in enumerate(levels) if level.get('muds')]
        self.assertGreaterEqual(len(mud_ids), 250)
        self.assertGreaterEqual(mud_ids[0], 100)
        self.assertLess(mud_ids[-1], 900)
        self.assertGreaterEqual(
            sum(1 for level in levels
                if level.get('muds') and level.get('redirects')), 200)


if __name__ == '__main__':
    unittest.main()
