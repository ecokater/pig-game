#!/usr/bin/env python3
"""Focused regression tests for Redirect / Mud / mixed-length pig semantics."""
import json
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from generate_levels import _slide


class MechanicsTest(unittest.TestCase):
    def test_redirect_turns_during_same_slide(self):
        pen = {(0, 0), (0, 1), (1, 0), (1, 1)}
        acted, cells, direction, mask = _slide(
            pen, set(), set(), ((-1, 0), (-2, 0)), (1, 0),
            {(0, 0): (0, 1)}, {}, 0)
        self.assertTrue(acted)
        self.assertEqual(cells, ((0, 1), (0, 0)))
        self.assertEqual(direction, (0, 1))
        self.assertEqual(mask, 0)

    def test_multiple_redirects_in_one_slide(self):
        pen = {(0, 0), (0, 1), (1, 1), (2, 1)}
        acted, cells, direction, mask = _slide(
            pen, set(), set(), ((-1, 0), (-2, 0)), (1, 0),
            {(0, 0): (0, 1), (0, 1): (1, 0)}, {}, 0)
        self.assertTrue(acted)
        self.assertEqual(cells, ((2, 1), (1, 1)))
        self.assertEqual(direction, (1, 0))
        self.assertEqual(mask, 0)

    def test_mud_stops_slide_immediately(self):
        pen = {(0, 0), (1, 0), (2, 0), (3, 0)}
        acted, cells, direction, mask = _slide(
            pen, set(), set(), ((-1, 0), (-2, 0)), (1, 0),
            {}, {}, 0, {(1, 0)})
        self.assertTrue(acted)
        self.assertEqual(cells, ((1, 0), (0, 0)))
        self.assertEqual(direction, (1, 0))
        self.assertEqual(mask, 0)

    def test_mud_pig_continues_on_second_tap(self):
        pen = {(0, 0), (1, 0), (2, 0), (3, 0)}
        acted, cells, direction, _ = _slide(
            pen, set(), set(), ((1, 0), (0, 0)), (1, 0),
            {}, {}, 0, {(1, 0)})
        self.assertTrue(acted)
        self.assertEqual(cells, ((3, 0), (2, 0)))
        self.assertEqual(direction, (1, 0))

    def test_redirect_then_mud_in_one_slide(self):
        pen = {(0, 0), (0, 1), (0, 2), (0, 3)}
        acted, cells, direction, _ = _slide(
            pen, set(), set(), ((-1, 0), (-2, 0)), (1, 0),
            {(0, 0): (0, 1)}, {}, 0, {(0, 1)})
        self.assertTrue(acted)
        self.assertEqual(cells, ((0, 1), (0, 0)))
        self.assertEqual(direction, (0, 1))

    def test_single_cell_piglet_slides(self):
        pen = {(0, 0), (1, 0), (2, 0)}
        acted, cells, direction, _ = _slide(
            pen, set(), set(), ((-1, 0),), (1, 0), {}, {}, 0)
        self.assertTrue(acted)
        self.assertEqual(cells, ((2, 0),))
        self.assertEqual(direction, (1, 0))

    def test_long_pig_bends_through_redirect(self):
        pen = {(0, 0), (0, 1), (0, 2), (1, 2), (2, 2)}
        acted, cells, direction, _ = _slide(
            pen, set(), set(), ((0, 0), (0, -1), (0, -2)), (0, 1),
            {(0, 2): (1, 0)}, {}, 0)
        self.assertTrue(acted)
        self.assertEqual(cells, ((2, 2), (1, 2), (0, 2)))
        self.assertEqual(direction, (1, 0))

    def test_long_pig_blocked_by_own_body_on_reverse(self):
        # 180° 回头箭头:3 格猪掉头时头撞上自己的身体中段,当场停下;
        # (2 格猪同场景允许原地翻转,是既有语义,此规则只约束更长的身体)
        pen = {(0, 0), (1, 0), (2, 0), (3, 0)}
        acted, cells, direction, _ = _slide(
            pen, set(), set(), ((2, 0), (1, 0), (0, 0)), (1, 0),
            {(3, 0): (-1, 0)}, {}, 0)
        self.assertTrue(acted)
        self.assertEqual(cells, ((3, 0), (2, 0), (1, 0)))
        self.assertEqual(direction, (-1, 0))

    def test_final_set_has_mechanic_progression_after_sorting(self):
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        with open(os.path.join(root, 'levels.json')) as f:
            levels = json.load(f)
        self.assertEqual(len(levels), 1000)
        self.assertFalse(any('gates' in level for level in levels))
        redirect_ids = [i for i, level in enumerate(levels)
                        if level.get('redirects')]
        self.assertGreaterEqual(len(redirect_ids), 800)
        self.assertGreaterEqual(sum(len(level.get('redirects', [])) >= 2
                                    for level in levels), 350)
        self.assertGreaterEqual(
            sum(bool(level.get('muds')) for level in levels), 200)
        mixed = [level for level in levels
                 if any(not isinstance(q[2], int) and set(q[2]) != {2}
                        for q in level['queues'])]
        self.assertGreaterEqual(len(mixed), 200)


if __name__ == '__main__':
    unittest.main()
