#!/usr/bin/env python3
"""Weave 1-cell piglets and 3-cell long pigs into the level set.

体型规则(与运行时一致):
  - 小猪占 1 格,灵活补缝,改变奇偶性;
  - 长猪占 3 格,蛇形跟随,过箭头后弯着身子停下,只能进"正在腾出的尾格";
  - 队列的第三项从 int 变为体长序列(如 [3,2,1],队首在前);旧 int 仍兼容。

替换 300 关,分三个阶段(全部生成-精确验证,免费构造 + BFS/DP):
  1. 教学段 ~12 关:小盘、无箭头无泥坑、步数余量 2,难度分自然落在前段;
  2. 中段 ~178 关:16-24 格、混编 + 箭头/泥坑组合,难度低于旧决赛线;
  3. 新决赛段 ~110 关:24-30 格、混编 + 多箭头 (+泥坑),难度 ≥ 43,
     把整套关卡的难度上限推过旧的 44.565。

每个候选:体长合法、恰好填满、净空不冲突、箭头/泥坑必须改变最优解、
D4 规范签名唯一、结构+解法相似度全对全低于阈值。完成后按难度全局重排。
"""
import json
import os
import random
import sys
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from evaluate_levels import difficulty, evaluate, report, shortest_method
from generate_levels import (DIRS, TooLarge, add, analyze, build_walls,
                             canon_sig, gen_shape, neg, solve, topo_depth)
from rebuild_similar_levels import clear_queues, is_high_similarity, parse

SEED = 20260723
OLD_MAX = 44.565

PHASES = [
    # (数量, 格数范围, 最大件数, 箭头概率, 泥坑概率, 余量选项, 难度窗口)
    ('intro', 12, (8, 12), 6, 0.0, 0.0, (2,), (0.0, 25.0)),
    ('mid', 178, (14, 22), 11, 0.7, 0.35, (0, 1), (22.0, 43.0)),
    ('finale', 110, (24, 30), 14, 1.0, 0.8, (0,), (41.0, 99.0)),
]


def pick_quota(rng, total, max_pieces):
    """选 3 格 / 1 格猪的数量;其余为 2 格。至少一只非 2 格。"""
    for _ in range(40):
        n3 = rng.randint(0, min(4, total // 3))
        n1 = rng.randint(0, min(4, total - 3 * n3))
        rest = total - 3 * n3 - n1
        if rest < 0 or rest % 2:
            continue
        n_pieces = n3 + n1 + rest // 2
        if n3 + n1 == 0 or not 2 <= n_pieces <= max_pieces:
            continue
        return n3, n1, rest // 2
    return None


def mixed_tiling(cells, rng, n3, n1, n2):
    """把猪圈精确平铺成 n3 个 3 格直条 + n1 个单格 + n2 个 2 格直条。"""
    def bt(uncov, r3, r1, r2):
        if not uncov:
            return []
        c = min(uncov, key=lambda c: (
            sum(1 for d in DIRS if add(c, d) in uncov), rng.random()))
        options = []
        seen = set()
        for d in ((1, 0), (0, 1)):
            for length, rq in ((3, r3), (2, r2)):
                if rq <= 0:
                    continue
                for off in range(length):
                    seg = tuple(sorted(
                        add(c, (d[0] * (k - off), d[1] * (k - off)))
                        for k in range(length)))
                    if seg in seen:
                        continue
                    seen.add(seg)
                    if all(s in uncov for s in seg):
                        options.append(seg)
        if r1 > 0:
            options.append((c,))
        rng.shuffle(options)
        for seg in options:
            L = len(seg)
            rest = bt(uncov - set(seg), r3 - (L == 3), r1 - (L == 1),
                      r2 - (L == 2))
            if rest is not None:
                return rest + [seg]
        return None
    return bt(frozenset(cells), n3, n1, n2)


def construct_mixed(pen_set, tiling, rng, want_arrows=0, dir_tries=40):
    """给每块体型选方向,建停靠/借道依赖图;无环 ⇒ 按拓扑序逐头释放即可
    精确填满(与骨牌版 construct 同一套证明)。

    箭头内建于构造:选 want_arrows 块体型改走"L 形弯道"——从边界沿 d2 进,
    在转弯格 T 被箭头转向 d1,滑到自己的铺位。约束保证箭头与装填兼容:
    盖住 T 的体型必须与箭头同向(箭头对它透明),其他任何体型的头部路径
    若经过任一箭头格,方向也必须与该箭头一致。没有箭头时弯道猪根本进不来,
    箭头天生"改变最优解"。

    返回 (queues, chain, arrows);queues 的体长序列按释放顺序 = 深度降序。"""
    cover = {}
    for i, seg in enumerate(tiling):
        for c in seg:
            cover[c] = i
    n = len(tiling)

    for _ in range(dir_tries):
        # 对齐模式:同列(行)的同轴体型共享方向 → 共用开口深排队(难度杠杆)
        aligned = rng.random() < 0.6
        col_dir, row_dir = {}, {}
        specs = []
        for seg in tiling:
            if len(seg) == 1:
                d = rng.choice(DIRS)
                ordered = list(seg)
            else:
                horiz = seg[0][1] == seg[1][1]
                axis = (1, 0) if horiz else (0, 1)
                if aligned and horiz:
                    d = row_dir.setdefault(
                        seg[0][1], axis if rng.random() < 0.5 else neg(axis))
                elif aligned:
                    d = col_dir.setdefault(
                        seg[0][0], axis if rng.random() < 0.5 else neg(axis))
                else:
                    d = axis if rng.random() < 0.5 else neg(axis)
                ordered = sorted(seg, key=lambda c: c[0] * d[0] + c[1] * d[1])
            head = ordered[-1]
            rear = ordered[0]
            lane = []
            cur = add(rear, neg(d))
            while cur in pen_set:
                lane.append(cur)
                cur = add(cur, neg(d))
                if len(lane) > 20:
                    break
            entry = lane[-1] if lane else rear
            specs.append({'d': d, 'entry_dir': d, 'head': head, 'rear': rear,
                          'lane': lane, 'entry': entry, 'len': len(seg),
                          'cells': ordered})

        # ── 弯道改造:给部分体型加"转弯格箭头" ──
        arrows = {}
        if want_arrows:
            order = list(range(n))
            rng.shuffle(order)
            bent_cnt = 0
            for idx in order:
                if bent_cnt >= want_arrows:
                    break
                s = specs[idx]
                d1 = s['d']
                back = []
                cur = add(s['rear'], neg(d1))
                while cur in pen_set:
                    back.append(cur)
                    cur = add(cur, neg(d1))
                rng.shuffle(back)
                placed = False
                for T in back:
                    if T in arrows or cover[T] == idx:
                        continue
                    if specs[cover[T]]['d'] != d1:
                        continue   # 盖 T 者必须与箭头同向,箭头才对它透明
                    perp = [(d1[1], d1[0]), (-d1[1], -d1[0])]
                    rng.shuffle(perp)
                    for d2 in perp:
                        seg2 = []
                        cur2 = add(T, neg(d2))
                        while cur2 in pen_set:
                            seg2.append(cur2)
                            cur2 = add(cur2, neg(d2))
                        # seg1:rear 与 T 之间的原直线段
                        seg1 = []
                        cur1 = add(s['rear'], neg(d1))
                        while cur1 != T:
                            seg1.append(cur1)
                            cur1 = add(cur1, neg(d1))
                        entry = seg2[-1] if seg2 else T
                        s['lane'] = seg1 + [T] + seg2
                        s['entry'] = entry
                        s['entry_dir'] = d2
                        s['turn'] = T
                        arrows[T] = d1
                        placed = True
                        break
                    if placed:
                        break
                if placed:
                    bent_cnt += 1
            if bent_cnt < want_arrows:
                continue

        # 箭头一致性:任何体型的头部路径(车道 + 自身铺位)经过箭头格时,
        # 该段行进方向必须等于箭头方向,否则会被意外拐走。
        # 弯道猪自己的转弯格是预期转向,跳过检查。
        ok = True
        for i, s in enumerate(specs):
            turn = s.get('turn')
            marks = []
            if turn is not None:
                passed = False
                for c in reversed(s['lane']):   # 从入口向铺位方向走
                    marks.append((c, s['d'] if passed else s['entry_dir']))
                    if c == turn:
                        passed = True
            else:
                marks = [(c, s['d']) for c in s['lane']]
            marks += [(c, s['d']) for c in s['cells']]
            for c, mdir in marks:
                if c == turn:
                    continue
                if c in arrows and arrows[c] != mdir:
                    ok = False
                    break
            if not ok:
                break
        if not ok:
            continue

        edges = defaultdict(set)
        for i, s in enumerate(specs):
            beyond = add(s['head'], s['d'])
            if beyond in pen_set:
                blocker = cover[beyond]
                if blocker == i:
                    ok = False
                    break
                edges[blocker].add(i)      # 挡路者必须先就位
            for lc in s['lane']:
                j = cover[lc]
                if j != i:
                    edges[i].add(j)        # 借道:车道上的体型必须后进
        if not ok:
            continue
        chain = topo_depth(n, edges)
        if chain is None:
            continue

        lane_map = defaultdict(list)
        shared_bad = False
        for s in specs:
            key = (s['entry'], neg(s['entry_dir']))
            depth = len(s['lane'])
            lane_map[key].append((depth, s['len'], s['entry_dir'] != s['d']))
        for (c, od), items in lane_map.items():
            # 弯道猪不与其他猪共用开口(队内深度序对弯道无意义)
            if any(bent for _, _, bent in items) and len(items) > 1:
                shared_bad = True
                break
        if shared_bad:
            continue
        queues = []
        for (c, od), items in sorted(lane_map.items()):
            items.sort(key=lambda t: t[0], reverse=True)  # 最深的先释放
            queues.append((c, od, tuple(length for _, length, _ in items)))
        return queues, chain, arrows
    return None


def attach_mud(rng, pen, queues, walls, redirects, base_min, p_mud):
    """构造后变异:泥坑只截断滑行、不改路线,是安全的变异维度。"""
    muds = set()
    minimum = base_min
    if rng.random() < p_mud:
        pool = sorted(set(pen) - set(redirects))
        rng.shuffle(pool)
        for cell in pool[:12]:
            trial = muds | {cell}
            new_min = solve(pen, walls, queues, max_depth=minimum + 8,
                            redirects=redirects, muds=trial)
            if new_min is None or new_min == minimum:
                continue
            muds = trial
            minimum = new_min
            break
    return muds, minimum


def random_mixed_raw(rng, phase):
    name, _, cells_rng, max_pieces, p_arrow, p_mud, slacks, _ = phase
    total = rng.randint(*cells_rng)
    shaped = gen_shape(rng, total)
    if shaped is None:
        return None
    _, pen = shaped
    pen = set(pen)
    quota = pick_quota(rng, total, max_pieces)
    if quota is None:
        return None
    tiling = mixed_tiling(pen, rng, *quota)
    if tiling is None:
        return None
    want_arrows = 0
    if rng.random() < p_arrow:
        want_arrows = rng.choice((1, 1, 2)) if name != 'finale' \
            else rng.choice((1, 2, 2, 3))
    built = construct_mixed(pen, tiling, rng, want_arrows)
    if built is None:
        return None
    queues, _, redirects = built
    if not clear_queues(pen, queues):
        return None
    walls = build_walls(pen, [(c, d) for c, d, _ in queues])
    # 构造保证存在"每头一步"的 n 步解 → 深度上限剪枝
    n_pieces = sum(len(lens) for _, _, lens in queues)
    base_min = solve(pen, walls, queues, max_depth=n_pieces + 2,
                     redirects=redirects)
    if base_min is None:
        return None
    # 非装饰复核:拿掉箭头后最优解必须改变(弯道猪进不来,通常直接无解)
    if redirects and solve(pen, walls, queues, max_depth=base_min + 2,
                           redirects={}) == base_min:
        return None
    muds, minimum = attach_mud(rng, pen, queues, walls, redirects,
                               base_min, p_mud)
    slack = rng.choice(slacks)
    return {
        'steps': minimum + slack, 'min': minimum,
        'pen': [list(c) for c in sorted(pen)],
        'queues': [[list(c), list(d), list(lens)] for c, d, lens in queues],
        'redirects': [[list(c), list(d)]
                      for c, d in sorted(redirects.items())],
        'muds': [list(c) for c in sorted(muds)],
    }


def main():
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    path = os.path.join(root, 'levels.json')
    with open(path) as f:
        raws = json.load(f)
    if any(not isinstance(q[2], int) for raw in raws for q in raw['queues']):
        print('Mixed-pig pass already applied.')
        return

    parsed = [parse(raw) for raw in raws]

    # 预扫描:走马灯语义收紧后行为变化(通常无解)的旧关强制替换
    print('pre-scan for broken levels…', flush=True)
    forced = []
    for i, lv in enumerate(parsed):
        walls = build_walls(lv['pen'], [(c, d) for c, d, _ in lv['queues']])
        ms = solve(lv['pen'], walls, lv['queues'], redirects=lv['redirects'],
                   muds=lv['muds'])
        if ms != lv['min']:
            forced.append(i)
    print(f'  forced victims: {[i + 1 for i in forced]}', flush=True)

    print('baseline evaluation…', flush=True)
    forced_set = set(forced)
    healthy = [i for i in range(len(parsed)) if i not in forced_set]
    rows, pairs = evaluate([parsed[i] for i in healthy])
    assert not pairs
    methods = {}
    for row, gi in zip(rows, healthy):
        methods[gi] = row['method']
    canons = {}
    for i in healthy:
        lv = parsed[i]
        canons[canon_sig(lv['pen'], lv['queues'], lv['redirects'],
                         lv['gates'], lv['muds'])] = i

    total_targets = sum(p[1] for p in PHASES)
    victims = sorted({round(20 + i * 979 / (total_targets - 1))
                      for i in range(total_targets)} | forced_set)
    rng = random.Random(SEED)
    vi = 0
    replaced = 0
    extra = len(victims) - total_targets   # 强制受害者带来的溢出配额
    for phase in PHASES:
        name, want = phase[0], phase[1]
        if name == 'finale':
            want += extra
        lo, hi = phase[7]
        done = 0
        attempts = 0
        while done < want and vi < len(victims):
            attempts += 1
            if attempts > 250000:
                raise RuntimeError(f'{name}: 候选搜索耗尽')
            raw = random_mixed_raw(rng, phase)
            if raw is None:
                continue
            candidate = parse(raw)
            walls = build_walls(candidate['pen'],
                                [(c, d) for c, d, _ in candidate['queues']])
            try:
                metrics = analyze(candidate['pen'], walls, candidate['queues'],
                                  candidate['steps'], candidate['redirects'],
                                  [], candidate['muds'])
            except TooLarge:
                continue
            if metrics is None:
                continue
            sig = canon_sig(candidate['pen'], candidate['queues'],
                            candidate['redirects'], [], candidate['muds'])
            index = victims[vi]
            owner = canons.get(sig)
            if owner is not None and owner != index:
                continue
            try:
                method, states = shortest_method(candidate)
            except ValueError:
                continue
            score = difficulty(candidate, metrics, states)
            if not lo <= score < hi:
                continue
            if any(j != index and is_high_similarity(
                    candidate, method, parsed[j], other_method)
                   for j, other_method in methods.items()):
                continue
            old = parsed[index]
            canons.pop(canon_sig(old['pen'], old['queues'], old['redirects'],
                                 old['gates'], old['muds']), None)
            canons[sig] = index
            raws[index] = raw
            parsed[index] = candidate
            methods[index] = method
            vi += 1
            done += 1
            replaced += 1
            if done % 20 == 0:
                print(f'  {name} {done}/{want} attempts={attempts}',
                      flush=True)
        print(f'{name}: {done}/{want} 完成', flush=True)

    print(f'replaced={replaced}', flush=True)
    print('final evaluation + re-sort…', flush=True)
    rows2, pairs2 = evaluate(parsed)
    assert not pairs2, f'{len(pairs2)} similarity pairs after mixed pass'
    ranked = sorted(rows2, key=lambda row: (row['difficulty'], row['index']))
    sorted_raws = [row['level']['raw'] for row in ranked]
    for new_index, row in enumerate(ranked):
        row['index'] = new_index
    with open(path, 'w') as f:
        json.dump(sorted_raws, f, indent=1)

    from add_mud import write_reports
    write_reports(root, ranked, pairs2)

    scores = [row['difficulty'] for row in ranked]
    mixed_pos = [i for i, raw in enumerate(sorted_raws)
                 if any(not isinstance(q[2], int) and set(q[2]) != {2}
                        for q in raw['queues'])]
    audit = {
        'seed': SEED, 'levels': len(sorted_raws),
        'mixed_levels': len(mixed_pos),
        'mixed_first_level': mixed_pos[0] + 1,
        'mixed_in_last_100': sum(1 for i in mixed_pos if i >= 900),
        'piglet_pigs': sum(q[2].count(1) for raw in sorted_raws
                           for q in raw['queues']
                           if not isinstance(q[2], int)),
        'long_pigs': sum(q[2].count(3) for raw in sorted_raws
                         for q in raw['queues']
                         if not isinstance(q[2], int)),
        'difficulty_min': scores[0], 'difficulty_max': scores[-1],
        'old_difficulty_max': OLD_MAX,
        'levels_above_old_max': sum(1 for s in scores if s > OLD_MAX),
        'redirect_levels': sum(1 for raw in sorted_raws
                               if raw.get('redirects')),
        'mud_levels': sum(1 for raw in sorted_raws if raw.get('muds')),
        'high_similarity_pairs': 0,
    }
    with open(os.path.join(root, 'tools', 'mixed_audit.json'), 'w') as f:
        json.dump(audit, f, indent=2)
    print(json.dumps(audit, ensure_ascii=False))


if __name__ == '__main__':
    main()
