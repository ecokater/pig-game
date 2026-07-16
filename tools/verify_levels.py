#!/usr/bin/env python3
"""
逐关复验 levels.json(队列模型,与游戏 GDScript 同一套规则):

硬性检查(任一失败则退出码非 0):
  1. 猪圈连通,本体 bbox ≤ 8 宽 × 10 高;
  2. 猪总格数恰好填满猪圈(sum(2×队列) == |pen|);
  3. 圈外净空:各开口的可见槽位 + 徽章格不压猪圈、互不重叠;
  4. BFS 可解,最优步数 == 存档 min ≤ 步数预算;
  5. 精确胜率 p_win > 0(全状态空间 DP,非抽样);
  6. D4 全变换(旋转 90/180/270 + 镜像)规范签名全部关卡两两不同。
  7. Redirect / 泥坑必须改变最优解，禁止装饰性机制；泥坑必须在圈内且
     不与箭头同格；最终数据不得含 Gate。

难度与相似度终检:
  使用 evaluate_levels.py 的最终评分检查严格非递减，并要求超阈值相似对为 0。

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
        if 'gates' in lv:
            raise ValueError("最终关卡数据禁止包含 Gate 字段")
        levels.append({
            'steps': lv['steps'],
            'min': lv['min'],
            'pen': [tuple(c) for c in lv['pen']],
            'queues': [(tuple(c), tuple(d), int(n)) for c, d, n in lv['queues']],
            'redirects': {tuple(c): tuple(d) for c, d in lv.get('redirects', [])},
            'muds': set(map(tuple, lv.get('muds', []))),
            'gates': [],
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
    canons = {}
    for i, lv in enumerate(levels):
        pen_set = set(lv['pen'])
        queues = lv['queues']
        redirects = lv['redirects']
        gates = [tuple(sorted(g)) for g in lv['gates']]
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

        # 机制格合法性
        muds = lv['muds']
        for c, d in redirects.items():
            if c not in pen_set or d not in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                errs.append("箭头位置或方向非法")
        for c in muds:
            if c not in pen_set:
                errs.append("泥坑必须在圈内")
            if c in redirects:
                errs.append("泥坑与箭头不能同格")
        for a, b in gates:
            if (a not in pen_set or b not in pen_set
                    or abs(a[0] - b[0]) + abs(a[1] - b[1]) != 1):
                errs.append("门必须位于两个相邻圈内格之间")

        sig = canon_sig(pen_set, queues, redirects, gates, muds)
        if sig in canons:
            errs.append(f"与 L{canons[sig]+1:03d} 旋转/镜像同构")
        canons[sig] = i

        # 可解性与精确分析
        walls = build_walls(pen_set, [(c, d) for c, d, _ in queues])
        min_steps = solve(pen_set, walls, queues, redirects=redirects,
                          gate_edges=gates, muds=muds)
        a = None
        if min_steps is None:
            errs.append("BFS 无解")
        elif min_steps != lv['min']:
            errs.append(f"最优 {min_steps} != 存档 {lv['min']}")
        elif min_steps > lv['steps']:
            errs.append(f"最优 {min_steps} > 预算 {lv['steps']}")
        else:
            # 机制必须参与解法，禁止只摆一个不影响路径的装饰物。
            if redirects:
                without_redirect = solve(
                    pen_set, walls, queues, redirects={}, gate_edges=gates,
                    muds=muds)
                if without_redirect == min_steps:
                    errs.append("箭头未改变最优解")
            if muds:
                without_mud = solve(
                    pen_set, walls, queues, redirects=redirects,
                    gate_edges=gates, muds=set())
                if without_mud == min_steps:
                    errs.append("泥坑未改变最优解")
            if gates:
                without_gate = solve(
                    pen_set, walls, queues, redirects=redirects, gate_edges=[],
                    muds=muds)
                if without_gate is None or without_gate >= min_steps:
                    errs.append("门未形成额外开门接力")
            try:
                a = analyze(pen_set, walls, queues, lv['steps'], redirects,
                            gates, muds)
            except TooLarge:
                errs.append("状态空间超限")
            if a is None and not errs:
                errs.append("p_win=0(预算内不可解)")

        max_q = max(cnt for _, _, cnt in queues)
        if a is not None:
            diff = (1.2 * n + 3.0 * (1 - a['p_win']) + 0.5 * a['crit']
                    + 0.25 * a['decep'] + 0.5 * (max_q - 1))
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
    from evaluate_levels import evaluate, load_levels as load_evaluation_levels
    ranked, similar_pairs = evaluate(load_evaluation_levels())
    scores = [row['difficulty'] for row in ranked]
    if any(a > b for a, b in zip(scores, scores[1:])):
        print("失败:最终难度分没有按非递减顺序排列")
        all_ok = False
    if similar_pairs:
        print(f"失败:仍有 {len(similar_pairs)} 对超阈值相似关卡")
        all_ok = False
    if all_ok:
        print(f"难度有序 {scores[0]:.3f} -> {scores[-1]:.3f}; "
              "超阈值相似对 0")
    if all_ok and len(canons) == len(levels):
        print(f"ALL {len(levels)} LEVELS OK(含 D4 旋转/镜像全查重)")
        sys.exit(0)
    print("存在失败项")
    sys.exit(1)


if __name__ == '__main__':
    main()
