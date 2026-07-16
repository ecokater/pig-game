#!/usr/bin/env python3
"""Weave the Mud mechanic into the mid/high band of the 1000-level set.

Mud cell: a pig whose head enters it stops on the spot; tapping the pig again
resumes the slide. This gives the player deliberate mid-lane parking — a new
verb on top of Redirect turning.

Constraints per mutated level (all enforced online, exact search only):
  - 1–2 mud cells inside the pen, never on a Redirect cell;
  - the level stays solvable and the optimum CHANGES vs. the mud-free board
    (decorative mud is rejected);
  - step slack is preserved (steps = new min + old slack);
  - the D4 canonical signature stays globally unique;
  - structural + method similarity stays below the evaluation thresholds
    against every other level;
  - the new difficulty stays below level 901's score, so the triple-arrow
    finale (L901–L1000) keeps its crown after the final re-sort.

The pass targets levels 151–900, then re-sorts all 1000 by the final
difficulty score and rewrites levels.json plus the evaluation reports.
"""
import json
import os
import random
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from evaluate_levels import (difficulty, evaluate, report, shortest_method,
                             load_levels as _unused_load)
from generate_levels import TooLarge, analyze, build_walls, canon_sig, solve
from rebuild_similar_levels import is_high_similarity, parse

SEED = 20260721
BAND_LO, BAND_HI = 150, 900   # 0 起下标:可变异区间 [150, 900) → L151–L900
TARGET = 300                  # 目标泥坑关数
TRIES_PER_LEVEL = 80


def write_reports(root, rows, pairs):
    with open(os.path.join(root, 'tools', 'levels_evaluation_after.md'), 'w') as f:
        f.write(report(rows, pairs))
    lines = ['#    pigs min bud qu op rd md  p_win  crit dcp    paths  difficulty',
             '-' * 80]
    for row in rows:
        level, metrics = row['level'], row['metrics']
        lines.append(
            f"L{row['index'] + 1:04d} "
            f"{sum(q[2] for q in level['queues']):4d} "
            f"{level['min']:3d} {level['steps']:3d} "
            f"{max(q[2] for q in level['queues']):2d} "
            f"{len(level['queues']):2d} {len(level['redirects']):2d} "
            f"{len(level.get('muds') or ()):2d} "
            f"{metrics['p_win'] * 100:6.2f} {metrics['crit']:4d} "
            f"{metrics['decep']:3d} "
            f"{min(metrics['n_paths'], 99999999):8d} "
            f"{row['difficulty']:8.3f}")
    with open(os.path.join(root, 'tools', 'levels_report.txt'), 'w') as f:
        f.write('\n'.join(lines) + '\n')


def main():
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    path = os.path.join(root, 'levels.json')
    with open(path) as f:
        raws = json.load(f)
    if any(raw.get('muds') for raw in raws):
        print('Mud pass already applied.')
        return

    print('baseline evaluation…', flush=True)
    parsed = [parse(raw) for raw in raws]
    rows, pairs = evaluate(parsed)
    assert not pairs, f'{len(pairs)} similarity pairs before mud pass'
    methods = [row['method'] for row in rows]
    ceiling = rows[BAND_HI]['difficulty']
    canons = {}
    for i, level in enumerate(parsed):
        canons[canon_sig(level['pen'], level['queues'], level['redirects'],
                         level['gates'], level['muds'])] = i

    rng = random.Random(SEED)
    order = list(range(BAND_LO, BAND_HI))
    rng.shuffle(order)
    added = []
    for index in order:
        if len(added) >= TARGET:
            break
        level = parsed[index]
        pen = level['pen']
        queues = level['queues']
        redirects = level['redirects']
        slack = level['steps'] - level['min']
        walls = build_walls(pen, [(c, d) for c, d, _ in queues])
        candidates = sorted(set(pen) - set(redirects))
        n_mud = 1 if len(added) < TARGET * 2 // 5 else rng.choice((1, 2, 2))
        if len(candidates) < n_mud:
            continue
        for _ in range(TRIES_PER_LEVEL):
            muds = set(rng.sample(candidates, n_mud))
            new_min = solve(pen, walls, queues, redirects=redirects,
                            gate_edges=[], muds=muds)
            if new_min is None or new_min == level['min'] \
                    or new_min > level['min'] + 4:
                continue
            steps_new = new_min + slack
            try:
                metrics = analyze(pen, walls, queues, steps_new,
                                  redirects, [], muds)
            except TooLarge:
                continue
            if metrics is None:
                continue
            sig = canon_sig(pen, queues, redirects, [], muds)
            owner = canons.get(sig)
            if owner is not None and owner != index:
                continue
            raw_new = dict(raws[index])
            raw_new['min'] = new_min
            raw_new['steps'] = steps_new
            raw_new['muds'] = [list(c) for c in sorted(muds)]
            candidate = parse(raw_new)
            try:
                method, states = shortest_method(candidate)
            except ValueError:
                continue
            score = difficulty(candidate, metrics, states)
            if score >= ceiling - 1e-9:
                continue
            if any(j != index and is_high_similarity(
                    candidate, method, parsed[j], methods[j])
                   for j in range(len(parsed))):
                continue
            old_sig = canon_sig(level['pen'], level['queues'],
                                level['redirects'], level['gates'],
                                level['muds'])
            canons.pop(old_sig, None)
            canons[sig] = index
            raws[index] = raw_new
            parsed[index] = candidate
            methods[index] = method
            added.append(index)
            if len(added) % 25 == 0:
                print(f'  mudded {len(added)}/{TARGET}', flush=True)
            break

    print(f'mud levels added: {len(added)}', flush=True)
    assert len(added) >= TARGET * 4 // 5, '泥坑覆盖不足'

    print('final evaluation + re-sort…', flush=True)
    rows2, pairs2 = evaluate(parsed)
    assert not pairs2, f'{len(pairs2)} similarity pairs after mud pass'
    ranked = sorted(rows2, key=lambda row: (row['difficulty'], row['index']))
    sorted_raws = [row['level']['raw'] for row in ranked]
    for new_index, row in enumerate(ranked):
        row['index'] = new_index
    with open(path, 'w') as f:
        json.dump(sorted_raws, f, indent=1)
    write_reports(root, ranked, pairs2)

    scores = [row['difficulty'] for row in ranked]
    mud_positions = [i for i, raw in enumerate(sorted_raws) if raw.get('muds')]
    combo = sum(1 for raw in sorted_raws
                if raw.get('muds') and raw.get('redirects'))
    audit = {
        'seed': SEED, 'levels': len(sorted_raws),
        'mud_levels': len(mud_positions),
        'mud_first_level': mud_positions[0] + 1 if mud_positions else None,
        'mud_last_level': mud_positions[-1] + 1 if mud_positions else None,
        'mud_and_redirect_levels': combo,
        'double_mud_levels': sum(
            1 for raw in sorted_raws if len(raw.get('muds', [])) >= 2),
        'difficulty_min': scores[0], 'difficulty_max': scores[-1],
        'high_similarity_pairs': 0,
        'finale_untouched': all(not raw.get('muds')
                                for raw in sorted_raws[-100:]),
    }
    with open(os.path.join(root, 'tools', 'mud_audit.json'), 'w') as f:
        json.dump(audit, f, indent=2)
    print(json.dumps(audit, ensure_ascii=False))


if __name__ == '__main__':
    main()
