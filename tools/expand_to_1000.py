#!/usr/bin/env python3
"""Deterministically expand the curated set from 100 to 1000 levels.

All 900 added levels use a solution-critical Redirect gadget. Pig counts rise
from 7 to 14 and all expansion levels use zero slack. Every candidate is rejected online if it violates
the existing structural/method similarity thresholds.
"""
import json
import os
import random
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from evaluate_levels import (evaluate, sequence_similarity, shortest_method,
                             structural_similarity)
from generate_levels import (DIRS, TooLarge, _xform, add, build_walls,
                             canon_sig, solve)
from mechanize_levels import ARROW_PUZZLES, _raw_level, build_report
from rebuild_similar_levels import (clear_queues, is_high_similarity, parse,
                                    random_base, sort_by_difficulty)

TARGET_LEVELS = 1000
SEED = 20260718
MAX_ATTEMPTS = 500000


def _transform_specs(pen, queues, redirect_cell, redirect_dir, k):
    return ({_xform(c, k) for c in pen},
            [(_xform(c, k), _xform(d, k), n) for c, d, n in queues],
            {_xform(redirect_cell, k): _xform(redirect_dir, k)})


def arrow_composite(n, rng, arrow_count=1):
    """Attach 1–3 independent Redirect-required gadgets to a base puzzle."""
    if arrow_count < 1 or n - 3 * arrow_count < 2:
        return None
    base = random_base(n - 3 * arrow_count, rng)
    if base is None:
        return None
    pen, all_queues, _ = base
    redirects = {}
    for _ in range(arrow_count):
        attached = None
        for _try in range(40):
            gadget = {(x, y) for x in range(3) for y in range(2)}
            queues, cell, direction = rng.choice(ARROW_PUZZLES)
            gadget, queues, redirect = _transform_specs(
                gadget, queues, cell, direction, rng.randrange(8))
            placements = [(dx, dy) for dx in range(-8, 9)
                          for dy in range(-10, 11)]
            rng.shuffle(placements)
            for dx, dy in placements:
                shifted = {(x + dx, y + dy) for x, y in gadget}
                if shifted & pen:
                    continue
                adjacency = sum(1 for c in shifted for d in DIRS
                                if add(c, d) in pen)
                if adjacency != 1:
                    continue
                combined = pen | shifted
                xs, ys = [c[0] for c in combined], [c[1] for c in combined]
                if max(xs) - min(xs) + 1 > 8 or max(ys) - min(ys) + 1 > 10:
                    continue
                shifted_queues = [((c[0] + dx, c[1] + dy), d, count)
                                  for c, d, count in queues]
                combined_queues = all_queues + shifted_queues
                if not clear_queues(combined, combined_queues):
                    continue
                shifted_redirect = {(c[0] + dx, c[1] + dy): d
                                    for c, d in redirect.items()}
                attached = (combined, combined_queues, shifted_redirect)
                break
            if attached:
                break
        if attached is None:
            return None
        pen, all_queues, new_redirect = attached
        redirects.update(new_redirect)

    walls = build_walls(pen, [(c, d) for c, d, _ in all_queues])
    minimum = solve(pen, walls, all_queues, n + 8, redirects, [])
    if minimum is None:
        return None
    # Every arrow must matter independently, not merely the set as a whole.
    for cell in redirects:
        reduced = dict(redirects)
        reduced.pop(cell)
        if solve(pen, walls, all_queues, n + 8, reduced, []) == minimum:
            return None
    return pen, all_queues, redirects, minimum


def make_candidate(serial, rng):
    """Use higher pig/mechanism tiers as the expansion progresses."""
    progress = serial / 900.0
    if progress < 0.12:
        n = rng.choice((7, 8))
    elif progress < 0.28:
        n = rng.choice((8, 9))
    elif progress < 0.48:
        n = rng.choice((9, 10))
    elif progress < 0.68:
        n = rng.choice((10, 11))
    elif progress < 0.84:
        n = rng.choice((11, 12))
    else:
        n = rng.choice((13, 14))
    arrow_count = 1 if progress < 0.45 else (2 if progress < 0.78 else 3)
    base = arrow_composite(n, rng, arrow_count)
    if base is None:
        return None
    pen, queues, redirects, _ = base
    try:
        raw = _raw_level(pen, queues, redirects, [], 0)
        raw.pop('gates', None)
        return raw
    except (AssertionError, TooLarge, RecursionError):
        return None


def expand(levels):
    if len(levels) != 100:
        raise ValueError(f'expected 100 seed levels, got {len(levels)}')
    rng = random.Random(SEED)
    for level in levels:
        level.pop('gates', None)
    parsed = [parse(level) for level in levels]
    rows, pairs = evaluate(parsed)
    if pairs:
        raise ValueError('seed set still contains over-similar pairs')
    accepted = [(row['level'], row['method']) for row in rows]
    used_canons = {canon_sig(p['pen'], p['queues'], p['redirects'], p['gates'])
                   for p, _ in accepted}
    added = []
    attempts = 0
    similarity_rejects = 0
    while len(added) < TARGET_LEVELS - 100 and attempts < MAX_ATTEMPTS:
        attempts += 1
        raw = make_candidate(len(added), rng)
        if raw is None:
            continue
        candidate = parse(raw)
        signature = canon_sig(candidate['pen'], candidate['queues'],
                              candidate['redirects'], candidate['gates'])
        if signature in used_canons:
            continue
        try:
            method, _ = shortest_method(candidate)
        except ValueError:
            continue
        if any(is_high_similarity(candidate, method, other, other_method)
               for other, other_method in accepted):
            similarity_rejects += 1
            continue
        accepted.append((candidate, method))
        used_canons.add(signature)
        added.append(raw)
        if len(added) % 50 == 0:
            print(f'  added {len(added)}/900 (attempts {attempts})', flush=True)
    if len(added) != 900:
        raise RuntimeError(f'only generated {len(added)} expansion levels')
    combined = levels + added
    sorted_levels, mapping = sort_by_difficulty(combined)
    audit = {
        'seed': SEED, 'seed_levels': 100, 'added_levels': len(added),
        'attempts': attempts, 'similarity_rejects': similarity_rejects,
        'old_to_new': [{'old': old, 'new': new, 'difficulty': score}
                       for old, new, score in mapping],
    }
    return sorted_levels, audit


def assert_late_game_requirements(levels):
    parsed = [parse(level) for level in levels]
    rows, pairs = evaluate(parsed)
    scores = [row['difficulty'] for row in rows]
    assert not pairs
    assert all(a <= b for a, b in zip(scores, scores[1:]))
    late = levels[700:]
    redirects = sum(bool(level.get('redirects')) for level in late)
    gates = sum(bool(level.get('gates')) for level in levels)
    assert redirects >= 285, redirects
    assert gates == 0, gates
    assert scores[700] >= 33.0, scores[700]
    return {'difficulty_min': scores[0], 'difficulty_l701': scores[700],
            'difficulty_max': scores[-1], 'late_redirects': redirects,
            'total_gates': gates,
            'high_similarity_pairs': len(pairs)}


def main():
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    path = os.path.join(root, 'levels.json')
    with open(path) as f:
        levels = json.load(f)
    if len(levels) == TARGET_LEVELS:
        if not any('gates' in level for level in levels):
            print('Already expanded: 1000 Gate-free levels.')
            return
        audit_path = os.path.join(root, 'tools', 'expansion_audit.json')
        with open(audit_path) as f:
            old_audit = json.load(f)
        mapping = {item['old']: item['new'] for item in old_audit['old_to_new']}
        levels = [levels[mapping[i] - 1] for i in range(1, 101)]
    # Strip legacy Gate state and tighten seed slack before similarity cleanup.
    cleaned = []
    for level in levels:
        parsed = parse(level)
        raw = _raw_level(parsed['pen'], parsed['queues'], parsed['redirects'], [],
                         min(level['steps'] - level['min'], 1))
        raw.pop('gates', None)
        cleaned.append(raw)
    from rebuild_similar_levels import rebuild
    cleaned, _, _ = rebuild(cleaned, random.Random(SEED - 1))
    for level in cleaned:
        level.pop('gates', None)
    levels, audit = expand(cleaned)
    requirements = assert_late_game_requirements(levels)
    audit['requirements'] = requirements
    with open(path, 'w') as f:
        json.dump(levels, f, indent=1)
    with open(os.path.join(root, 'tools', 'levels_report.txt'), 'w') as f:
        f.write(build_report(levels))
    with open(os.path.join(root, 'tools', 'expansion_audit.json'), 'w') as f:
        json.dump(audit, f, indent=2)
    print(json.dumps(requirements, ensure_ascii=False))


if __name__ == '__main__':
    main()
