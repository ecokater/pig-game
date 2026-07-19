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

    def test_final_set_is_archetype_balanced(self):
        """原型体系的最终集不变量(取代旧的强制箭头节奏断言)。"""
        from collections import Counter
        from archetypes import ARCH_NAMES
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        with open(os.path.join(root, 'levels.json')) as f:
            levels = json.load(f)
        self.assertEqual(len(levels), 1000)
        self.assertFalse(any('gates' in level for level in levels))
        # 每关都有合法原型标签,八种均衡出现
        archs = [level.get('arch') for level in levels]
        self.assertTrue(all(a in ARCH_NAMES for a in archs))
        counts = Counter(archs)
        self.assertEqual(set(counts), set(ARCH_NAMES))
        self.assertGreaterEqual(min(counts.values()), 80)
        # 机制自然分布(不强制数量,只要都有存在感)
        self.assertGreaterEqual(
            sum(bool(level.get('redirects')) for level in levels), 100)
        self.assertGreaterEqual(
            sum(bool(level.get('muds')) for level in levels), 200)
        mixed = [level for level in levels
                 if any(not isinstance(q[2], int) and set(q[2]) != {2}
                        for q in level['queues'])]
        self.assertGreaterEqual(len(mixed), 400)
        # 每关都带官方解线,长度等于最优步数
        self.assertTrue(all(len(level.get('sol', [])) == level['min']
                            for level in levels))


if __name__ == '__main__':
    unittest.main()
