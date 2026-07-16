#!/usr/bin/env python3
"""
逐关复验 levels.json(队列模型,与游戏 GDScript 同一套规则):

硬性检查(任一失败则退出码非 0):
  1. 猪圈连通,本体 bbox ≤ 8 宽 × 10 高;
  2. 猪总格数恰好填满猪圈(sum(2×队列) == |pen|);
  3. 圈外净空:各开口的可见槽位 + 徽章格不压猪圈、互不重叠;
  4. BFS 可解,最优步数 == 存档 min ≤ 步数预算;
  5. 精确胜率 p_win > 0(全状态空间 DP,非抽样);
  6. D4 全变换(旋转 90/180/270 + 镜像)规范签名 100 关两两不同。

难度复验(报告输出):
  p_win / crit / decep / paths / 难度分,检查各世界内难度大体递增。

用法:python3 tools/verify_levels.py
"""
import json
import os
import sys
from collections import deque

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from generate_levels import (   # noqa: E402
    build_walls, solve, analyze, canon_sig, ray_cells, add,
    PEN_MAX_W, PEN_MAX_H, TooLarge)


def load_levels():
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    with open(os.path.join(root, 'levels.json')) as f:
        raw = json.load(f)
    levels = []
    for lv in raw:
        levels.append({
            'steps': lv['steps'],
            'min': lv['min'],
            'pen': [tuple(c) for c in lv['pen']],
            'queues': [(tuple(c), tuple(d), int(n)) for c, d, n in lv['queues']],
        })
    return levels


def connected(pen_set):
    start = next(iter(pen_set))
    seen = {start}
    q = deque([start])
    while q:
        c = q.popleft()
        for d in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            nb = add(c, d)
            if nb in pen_set and nb not in seen:
                seen.add(nb)
                q.append(nb)
    return len(seen) == len(pen_set)


def main():
    levels = load_levels()
    print(f"复验 {len(levels)} 关(队列模型,精确状态空间分析)……")
    print("#    pigs  min bud qu op  p_win  crit dcp    paths  diff  pen   状态")
    print("-" * 76)

    all_ok = True
    prev_diff = {}
    warns = []
    canons = {}
    for i, lv in enumerate(levels):
        pen_set = set(lv['pen'])
        queues = lv['queues']
        n = sum(cnt for _, _, cnt in queues)
        errs = []

        # 连通性与本体尺寸
        if not connected(pen_set):
            errs.append("猪圈不连通")
        xs = [c[0] for c in pen_set]
        ys = [c[1] for c in pen_set]
        pw = max(xs) - min(xs) + 1
        ph = max(ys) - min(ys) + 1
        if pw > PEN_MAX_W or ph > PEN_MAX_H:
            errs.append(f"猪圈超限 {pw}x{ph}")

        # 恰好填满
        if 2 * n != len(pen_set):
            errs.append(f"猪格数 {2*n} != 圈格数 {len(pen_set)}")

        # 圈外净空
        used = set()
        for c, d, cnt in queues:
            for cell in ray_cells(c, d, cnt):
                if cell in pen_set:
                    errs.append("槽位压到猪圈")
                    break
                if cell in used:
                    errs.append("槽位互相重叠")
                    break
                used.add(cell)

        # D4 全变换查重
        sig = canon_sig(pen_set, queues)
        if sig in canons:
            errs.append(f"与 L{canons[sig]+1:03d} 旋转/镜像同构")
        canons[sig] = i

        # 可解性与精确分析
        walls = build_walls(pen_set, [(c, d) for c, d, _ in queues])
        min_steps = solve(pen_set, walls, queues)
        a = None
        if min_steps is None:
            errs.append("BFS 无解")
        elif min_steps != lv['min']:
            errs.append(f"最优 {min_steps} != 存档 {lv['min']}")
        elif min_steps > lv['steps']:
            errs.append(f"最优 {min_steps} > 预算 {lv['steps']}")
        else:
            try:
                a = analyze(pen_set, walls, queues, lv['steps'])
            except TooLarge:
                errs.append("状态空间超限")
            if a is None and not errs:
                errs.append("p_win=0(预算内不可解)")

        max_q = max(cnt for _, _, cnt in queues)
        if a is not None:
            diff = (1.2 * n + 3.0 * (1 - a['p_win']) + 0.5 * a['crit']
                    + 0.25 * a['decep'] + 0.5 * (max_q - 1))
            if n in prev_diff and diff < prev_diff[n] - 0.9:
                warns.append(f"L{i+1:03d} 难度分回落 "
                             f"{prev_diff[n]:.2f}->{diff:.2f}")
            prev_diff[n] = max(diff, prev_diff.get(n, 0.0))
            print(f"L{i+1:03d} {n:4d} {min_steps:4d} {lv['steps']:3d} "
                  f"{max_q:2d} {len(queues):2d} {a['p_win']*100:6.2f} "
                  f"{a['crit']:4d} {a['decep']:3d} "
                  f"{min(a['n_paths'], 99999999):8d} {diff:5.2f}  "
                  f"{pw}x{ph}  {'OK' if not errs else ';'.join(errs)}")
        else:
            print(f"L{i+1:03d} {n:4d}  --  {lv['steps']:3d} "
                  f"{'':>34s} {pw}x{ph}  {';'.join(errs)}")
        if errs:
            all_ok = False

    print("-" * 76)
    for w in warns:
        print("警告:", w)
    if all_ok and len(canons) == len(levels):
        print(f"ALL {len(levels)} LEVELS OK(含 D4 旋转/镜像全查重)")
        sys.exit(0)
    print("存在失败项")
    sys.exit(1)


if __name__ == '__main__':
    main()
