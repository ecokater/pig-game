#!/usr/bin/env python3
"""
逐关复验 levels.json(与游戏 GDScript 同一套滑动规则):

硬性检查(任一失败则退出码非 0):
  1. BFS 可解,最优步数 ≤ 步数预算;
  2. 包围盒 ≤ 10×11(屏幕适配);
  3. 初始猪格互不重叠且全在圈外;
  4. 精确胜率 p_win > 0(对整个状态空间做 DP,非抽样)。

难度复验(报告输出):
  p_win / 关键抉择数 crit / 欺骗深度 decep / 可通关序列数 paths / 难度分 diff,
  并检查每个"世界"(同猪数段)内难度分大体递增(局部小回落只警告)。

用法:python3 tools/verify_levels.py
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from generate_levels import (   # noqa: E402
    build_walls, solve, analyze, MAX_COLS, MAX_ROWS)


def load_levels():
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    with open(os.path.join(root, 'levels.json')) as f:
        raw = json.load(f)
    levels = []
    for lv in raw:
        levels.append({
            'steps': lv['steps'],
            'pen': [tuple(c) for c in lv['pen']],
            'openings': [(tuple(c), tuple(d)) for c, d in lv['openings']],
            'pigs': [(tuple(t), tuple(h), tuple(d)) for t, h, d in lv['pigs']],
        })
    return levels


def main():
    levels = load_levels()
    print(f"复验 {len(levels)} 关(精确状态空间分析)……")
    print("#    pigs  min bud  p_win  crit dcp    paths  diff  bbox  状态")
    print("-" * 70)

    all_ok = True
    prev_diff = {}
    warns = []
    for i, lv in enumerate(levels):
        pen_set = set(lv['pen'])
        pigs = lv['pigs']
        walls = build_walls(pen_set, lv['openings'])
        errs = []

        # 初始位置合法性
        cells = [c for p in pigs for c in (p[0], p[1])]
        if len(set(cells)) != len(cells):
            errs.append("初始猪格重叠")
        if any(c in pen_set for c in cells):
            errs.append("有猪初始在圈内")

        # 包围盒
        allc = list(pen_set) + cells
        xs = [c[0] for c in allc]
        ys = [c[1] for c in allc]
        cols = max(xs) - min(xs) + 1
        rows = max(ys) - min(ys) + 1
        if cols > MAX_COLS or rows > MAX_ROWS:
            errs.append(f"包围盒超限 {cols}x{rows}")

        # 可解性与精确分析
        min_steps, _ = solve(pen_set, walls, pigs)
        a = None
        if min_steps is None:
            errs.append("BFS 无解")
        elif min_steps > lv['steps']:
            errs.append(f"最优 {min_steps} > 预算 {lv['steps']}")
        else:
            a = analyze(pen_set, walls, pigs, lv['steps'])
            if a is None:
                errs.append("p_win=0(预算内不可解)")

        n = len(pigs)
        if a is not None:
            diff = (1.4 * n + 3.0 * (1 - a['p_win']) + 0.5 * a['crit']
                    + 0.25 * a['decep'])
            # 世界内难度回落检查(容忍 0.75 的局部波动)
            if n in prev_diff and diff < prev_diff[n] - 0.75:
                warns.append(f"L{i+1:03d} 难度分回落 "
                             f"{prev_diff[n]:.2f}->{diff:.2f}")
            prev_diff[n] = max(diff, prev_diff.get(n, 0.0))
            print(f"L{i+1:03d} {n:4d} {min_steps:4d} {lv['steps']:3d} "
                  f"{a['p_win']*100:6.2f} {a['crit']:4d} {a['decep']:3d} "
                  f"{min(a['n_paths'], 99999999):8d} {diff:5.2f}  "
                  f"{cols}x{rows}  {'OK' if not errs else ';'.join(errs)}")
        else:
            print(f"L{i+1:03d} {n:4d}  --  {lv['steps']:3d} "
                  f"{'':>28s} {cols}x{rows}  {';'.join(errs)}")
        if errs:
            all_ok = False

    print("-" * 70)
    for w in warns:
        print("警告:", w)
    if all_ok:
        print(f"ALL {len(levels)} LEVELS OK")
        sys.exit(0)
    print("存在失败项")
    sys.exit(1)


if __name__ == '__main__':
    main()
