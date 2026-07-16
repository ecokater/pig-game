#!/usr/bin/env python3
"""Rebuild every level participating in an over-similar pair, then sort.

The script is deterministic. It preserves pig count, step slack, and Redirect
presence for every replaced level. Legacy Gate parameters remain internal-only
for rebuilding older seed data; final output is Gate-free.
"""
import json
import os
import random
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from evaluate_levels import (HIGH_METHOD, HIGH_SIMILARITY, difficulty, evaluate,
                             sequence_similarity, shortest_method,
                             structural_similarity)
from generate_levels import (DIRS, TooLarge, add, analyze, build_walls,
                             canon_sig, construct, gen_shape, random_tiling,
                             ray_cells, solve)
from mechanize_levels import _raw_level, build_report

SEED = 20260717
MAX_ATTEMPTS_PER_LEVEL = 120000


def parse(raw):
    return {
        'steps': raw['steps'], 'min': raw['min'],
        'pen': set(map(tuple, raw['pen'])),
        'queues': [(tuple(c), tuple(d), int(n)) for c, d, n in raw['queues']],
        'redirects': {tuple(c): tuple(d)
                      for c, d in raw.get('redirects', [])},
        'gates': [tuple(sorted((tuple(a), tuple(b))))
                  for a, b in raw.get('gates', [])],
        'raw': raw,
    }


def random_partition(total, parts, rng):
    cuts = sorted(rng.sample(range(1, total), parts - 1))
    values, last = [], 0
    for cut in cuts + [total]:
        values.append(cut - last)
        last = cut
    rng.shuffle(values)
    return values


def clear_queues(pen, queues):
    used = set()
    for c, d, count in queues:
        for cell in ray_cells(c, d, count):
            if cell in pen or cell in used:
                return False
            used.add(cell)
    return True


def random_base(n, rng):
    shaped = gen_shape(rng, n * 2)
    if shaped is None:
        return None
    _, pen = shaped
    tiling = random_tiling(pen, rng)
    if tiling is None:
        return None
    built = construct(set(pen), tiling, rng)
    if built is None:
        return None
    queues, _, _ = built
    if not clear_queues(pen, queues):
        return None
    walls = build_walls(pen, [(c, d) for c, d, _ in queues])
    minimum = solve(pen, walls, queues)
    return (set(pen), queues, minimum) if minimum is not None else None


def random_arrow_base(n, rng):
    """Free queue construction finds layouts whose turn is genuinely required."""
    shaped = gen_shape(rng, n * 2)
    if shaped is None:
        return None
    _, pen = shaped
    pen = set(pen)
    boundary = [(c, d) for c in pen for d in DIRS if add(c, d) not in pen]
    parts = rng.randint(2, min(4, n))
    openings = rng.sample(boundary, parts)
    counts = random_partition(n, parts, rng)
    queues = [(c, d, counts[i]) for i, (c, d) in enumerate(openings)]
    if not clear_queues(pen, queues):
        return None
    walls = build_walls(pen, [(c, d) for c, d, _ in queues])
    cell = rng.choice(tuple(pen))
    directions = [d for d in DIRS if add(cell, d) in pen]
    if not directions:
        return None
    redirect = {cell: rng.choice(directions)}
    minimum = solve(pen, walls, queues, n + 8, redirect, [])
    if minimum is None:
        return None
    without = solve(pen, walls, queues, n + 8)
    if without == minimum:
        return None
    return pen, queues, minimum, redirect


def add_meaningful_gate(pen, queues, redirects, minimum, rng):
    walls = build_walls(pen, [(c, d) for c, d, _ in queues])
    edges = list({tuple(sorted((c, add(c, d))))
                  for c in pen for d in DIRS if add(c, d) in pen})
    rng.shuffle(edges)
    for edge in edges:
        gated = solve(pen, walls, queues, minimum + 5, redirects, [edge])
        if gated is not None and gated > minimum:
            return [edge], gated
    return None


def candidate_raw(n, slack, want_redirect, want_gate, rng):
    if want_redirect:
        base = random_arrow_base(n, rng)
        if base is None:
            return None
        pen, queues, minimum, redirects = base
    else:
        base = random_base(n, rng)
        if base is None:
            return None
        pen, queues, minimum = base
        redirects = {}
    gates = []
    if want_gate:
        result = add_meaningful_gate(
            pen, queues, redirects, minimum, rng)
        if result is None:
            return None
        gates, minimum = result
    try:
        return _raw_level(pen, queues, redirects, gates, slack)
    except (AssertionError, TooLarge, RecursionError):
        return None


def is_high_similarity(a, method_a, b, method_b):
    structural = structural_similarity(a, b)
    method = sequence_similarity(method_a, method_b)
    combined = 0.48 * structural + 0.52 * method
    return (combined >= HIGH_SIMILARITY
            or (method >= HIGH_METHOD and structural >= 0.68))


def rebuild(levels, rng):
    parsed = [parse(level) for level in levels]
    rows, pairs = evaluate(parsed)
    flagged = sorted({pair[key] for pair in pairs for key in ('a', 'b')})
    if not flagged:
        return levels, [], []

    accepted = [(parsed[i], rows[i]['method'])
                for i in range(len(levels)) if i not in flagged]
    used_canons = {
        canon_sig(item[0]['pen'], item[0]['queues'], item[0]['redirects'],
                  item[0]['gates']) for item in accepted
    }
    replacements = {}
    attempts_log = []
    for index in flagged:
        old = parsed[index]
        n = sum(q[2] for q in old['queues'])
        slack = old['steps'] - old['min']
        want_redirect = bool(old['redirects'])
        want_gate = bool(old['gates'])
        for attempt in range(1, MAX_ATTEMPTS_PER_LEVEL + 1):
            raw = candidate_raw(n, slack, want_redirect, want_gate, rng)
            if raw is None:
                continue
            candidate = parse(raw)
            sig = canon_sig(candidate['pen'], candidate['queues'],
                            candidate['redirects'], candidate['gates'])
            if sig in used_canons:
                continue
            try:
                method, _ = shortest_method(candidate)
            except ValueError:
                continue
            if any(is_high_similarity(candidate, method, other, other_method)
                   for other, other_method in accepted):
                continue
            replacements[index] = raw
            accepted.append((candidate, method))
            used_canons.add(sig)
            attempts_log.append((index + 1, attempt))
            print(f'  rebuilt L{index + 1:03d} after {attempt} attempts')
            break
        else:
            raise RuntimeError(f'L{index + 1:03d}: replacement search exhausted')

    rebuilt = [replacements.get(i, level) for i, level in enumerate(levels)]
    return rebuilt, flagged, attempts_log


def sort_by_difficulty(levels):
    parsed = [parse(level) for level in levels]
    rows, pairs = evaluate(parsed)
    assert not pairs, f'{len(pairs)} similarity pairs remain before sorting'
    ranked = sorted(rows, key=lambda row: (row['difficulty'], row['index']))
    sorted_levels = [row['level']['raw'] for row in ranked]
    mapping = [(row['index'] + 1, new + 1, row['difficulty'])
               for new, row in enumerate(ranked)]
    return sorted_levels, mapping


def main():
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    path = os.path.join(root, 'levels.json')
    with open(path) as f:
        levels = json.load(f)
    rebuilt, flagged, attempts = rebuild(levels, random.Random(SEED))
    sorted_levels, mapping = sort_by_difficulty(rebuilt)
    with open(path, 'w') as f:
        json.dump(sorted_levels, f, indent=1)
    with open(os.path.join(root, 'tools', 'levels_report.txt'), 'w') as f:
        f.write(build_report(sorted_levels))
    audit = {
        'seed': SEED,
        'rebuilt_original_levels': [i + 1 for i in flagged],
        'replacement_attempts': [{'level': i, 'attempts': n}
                                 for i, n in attempts],
        'old_to_new': [{'old': old, 'new': new, 'difficulty': score}
                       for old, new, score in mapping],
    }
    with open(os.path.join(root, 'tools', 'rebuild_audit.json'), 'w') as f:
        json.dump(audit, f, indent=2)
    print(f'rebuilt={len(flagged)} sorted={len(sorted_levels)}')


if __name__ == '__main__':
    main()
