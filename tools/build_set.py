#!/usr/bin/env python3
"""按玩法原型从零组装 1000 关(替代单一生成器 + 事后变异的老流水线)。

流程:
  1. 并行为八种原型各生成一大批候选;每个候选都经精确分析(可解、p_win>0)、
     体型合法、恰好填满、机制非装饰;
  2. D4 全变换去重 + 结构/解法相似度贪心去重(全局唯一玩法体验);
  3. 按原型均衡配额选出 1000 关,按精确难度分**严格非递减**排序;
     在等难度处就近交换,尽量让相邻两关原型不同(不破坏单调性);
  4. 每关写 arch 原型标签;导出官方解线 sol;写报告与审计。

用法:python3 tools/build_set.py [--pool N] [--seconds S]
"""
import argparse
import json
import multiprocessing as mp
import os
import random
import sys
import time
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from archetypes import ARCH_NAMES, classify, generate
from evaluate_levels import difficulty, shortest_method
from generate_levels import TooLarge, analyze, build_walls, canon_sig
from rebuild_similar_levels import is_high_similarity, parse

TOTAL = 1000
SEED = 20260727


def _gen_unit(args):
    """并行 worker:为单个原型在时限内生成合法且已分析的候选。"""
    arch, seed, seconds, cap = args
    rng = random.Random(seed)
    out = []
    t0 = time.time()
    while time.time() - t0 < seconds and len(out) < cap:
        raw = generate(arch, rng)
        if raw is None:
            continue
        cand = parse(raw)
        walls = build_walls(cand['pen'],
                            [(c, d) for c, d, _ in cand['queues']])
        try:
            m = analyze(cand['pen'], walls, cand['queues'], cand['steps'],
                        cand['redirects'], [], cand['muds'])
        except TooLarge:
            continue
        if m is None:
            continue
        try:
            method, states = shortest_method(cand)
        except ValueError:
            continue
        raw['arch'] = arch
        out.append({
            'raw': raw, 'arch': arch,
            'diff': difficulty(cand, m, states), 'method': method,
            'canon': canon_sig(cand['pen'], cand['queues'], cand['redirects'],
                               [], cand['muds']),
        })
    return out


def generate_pool(seconds, per_arch_cap):
    workers = max(2, min(8, mp.cpu_count() - 1))
    # 每个原型切成多个工作单元喂满进程池,不同 seed 保证不撞
    units = []
    for ai, arch in enumerate(ARCH_NAMES):
        for k in range(workers):
            units.append((arch, SEED + 1000 * ai + k, seconds,
                          per_arch_cap // workers + 1))
    with mp.get_context('fork').Pool(workers) as pool:
        results = pool.map(_gen_unit, units, chunksize=1)
    pool_by_arch = defaultdict(list)
    for batch in results:
        for c in batch:
            pool_by_arch[c['arch']].append(c)
    return pool_by_arch


def dedup(pool_by_arch):
    """D4 去重 + 相似度贪心去重。按难度交错处理以保留多样性。"""
    # 交错所有原型的候选,难度升序穿插
    for arch in pool_by_arch:
        pool_by_arch[arch].sort(key=lambda c: c['diff'])
    streams = [list(pool_by_arch[a]) for a in ARCH_NAMES]
    order = []
    idx = [0] * len(streams)
    while any(idx[i] < len(streams[i]) for i in range(len(streams))):
        for i in range(len(streams)):
            if idx[i] < len(streams[i]):
                order.append(streams[i][idx[i]])
                idx[i] += 1

    accepted = []
    seen_canon = set()
    for c in order:
        if c['canon'] in seen_canon:
            continue
        cand = parse(c['raw'])   # 解析一次并缓存,复用 D4 形状缓存
        if any(is_high_similarity(cand, c['method'], a['parsed'],
                                  a['method']) for a in accepted):
            continue
        c['parsed'] = cand
        seen_canon.add(c['canon'])
        accepted.append(c)
    return accepted


def select_balanced(accepted):
    """按原型均衡配额选出 TOTAL 关:短缺原型全取,富余原型按难度均匀抽样。"""
    by_arch = defaultdict(list)
    for c in accepted:
        by_arch[c['arch']].append(c)
    for a in by_arch:
        by_arch[a].sort(key=lambda c: c['diff'])

    quota = {a: TOTAL // len(ARCH_NAMES) for a in ARCH_NAMES}
    # 先把短缺原型的名额匀给富余原型
    deficit = 0
    rich = []
    for a in ARCH_NAMES:
        have = len(by_arch.get(a, []))
        if have < quota[a]:
            deficit += quota[a] - have
            quota[a] = have
        else:
            rich.append(a)
    while deficit > 0 and rich:
        share = max(1, deficit // len(rich))
        for a in list(rich):
            room = len(by_arch[a]) - quota[a]
            add = min(share, room, deficit)
            quota[a] += add
            deficit -= add
            if len(by_arch[a]) - quota[a] <= 0:
                rich.remove(a)
            if deficit <= 0:
                break

    chosen = []
    for a in ARCH_NAMES:
        items = by_arch.get(a, [])
        q = quota[a]
        if q >= len(items):
            chosen.extend(items)
        elif q == 1:
            chosen.append(items[len(items) // 2])
        else:
            # 沿难度轴均匀抽样,避免只取某一段
            for k in range(q):
                chosen.append(items[round(k * (len(items) - 1) / (q - 1))])
    return chosen


def arrange(chosen):
    """按难度非递减排序;在等难度块内交换,尽量打散相邻同原型。"""
    chosen.sort(key=lambda c: c['diff'])
    n = len(chosen)
    swaps = 0
    for i in range(1, n):
        if chosen[i]['arch'] != chosen[i - 1]['arch']:
            continue
        # 在与 i 难度完全相同的邻域里找一个可换、且换后不产生新相邻冲突的
        for j in range(i + 1, n):
            if chosen[j]['diff'] != chosen[i]['diff']:
                break
            if (chosen[j]['arch'] != chosen[i - 1]['arch']
                    and (j + 1 >= n
                         or chosen[j + 1]['arch'] != chosen[i]['arch'])
                    and chosen[j - 1]['arch'] != chosen[i]['arch']):
                chosen[i], chosen[j] = chosen[j], chosen[i]
                swaps += 1
                break
    adjacent = sum(1 for i in range(1, n)
                   if chosen[i]['arch'] == chosen[i - 1]['arch'])
    return chosen, swaps, adjacent


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--seconds', type=float, default=90.0,
                    help='每个工作单元的生成时限')
    ap.add_argument('--cap', type=int, default=200,
                    help='每原型候选上限')
    args = ap.parse_args()
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

    print('并行生成候选池…', flush=True)
    t0 = time.time()
    pool_by_arch = generate_pool(args.seconds, args.cap)
    for a in ARCH_NAMES:
        print(f'  {a:9s} {len(pool_by_arch.get(a, [])):4d}', flush=True)
    print(f'  生成用时 {time.time() - t0:.0f}s', flush=True)

    print('去重(D4 + 相似度)…', flush=True)
    accepted = dedup(pool_by_arch)
    by = defaultdict(int)
    for c in accepted:
        by[c['arch']] += 1
    print('  去重后:' + '  '.join(f'{a}={by[a]}' for a in ARCH_NAMES),
          flush=True)
    if len(accepted) < TOTAL:
        raise SystemExit(f'去重后仅 {len(accepted)} 关 < {TOTAL},'
                         f'加大 --seconds/--cap 重来')

    chosen = select_balanced(accepted)
    if len(chosen) < TOTAL:
        # 均衡后仍不足则用剩余候选补齐(仍按难度)
        picked = set(id(c) for c in chosen)
        extra = sorted((c for c in accepted if id(c) not in picked),
                       key=lambda c: c['diff'])
        chosen += extra[:TOTAL - len(chosen)]
    chosen = chosen[:TOTAL]

    chosen, swaps, adjacent = arrange(chosen)
    print(f'排序完成:等难度交换 {swaps} 次,残留相邻同原型 {adjacent} 处',
          flush=True)

    levels = [c['raw'] for c in chosen]
    path = os.path.join(root, 'levels.json')
    with open(path, 'w') as f:
        json.dump(levels, f, indent=1)

    print('导出官方解线…', flush=True)
    import export_solutions
    export_solutions.main()

    scores = [c['diff'] for c in chosen]
    counts = defaultdict(int)
    for c in chosen:
        counts[c['arch']] += 1
    audit = {
        'seed': SEED, 'levels': len(levels),
        'archetype_counts': {a: counts[a] for a in ARCH_NAMES},
        'difficulty_min': scores[0], 'difficulty_max': scores[-1],
        'monotonic': all(a <= b for a, b in zip(scores, scores[1:])),
        'adjacent_same_arch': adjacent,
    }
    with open(os.path.join(root, 'tools', 'archetype_audit.json'), 'w') as f:
        json.dump(audit, f, indent=2)
    print(json.dumps(audit, ensure_ascii=False))


if __name__ == '__main__':
    main()
