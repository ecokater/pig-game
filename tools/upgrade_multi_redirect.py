#!/usr/bin/env python3
"""Replace the hardest 450 levels with 2–3-arrow puzzles."""
import json
import os
import random
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from evaluate_levels import evaluate, shortest_method
from expand_to_1000 import arrow_composite
from generate_levels import TooLarge, canon_sig
from mechanize_levels import _raw_level
from rebuild_similar_levels import is_high_similarity, parse, sort_by_difficulty

SEED = 20260719
KEEP = 550
ADD = 450


def main():
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    path = os.path.join(root, 'levels.json')
    with open(path) as f:
        levels = json.load(f)
    if sum(len(level.get('redirects', [])) >= 2 for level in levels) >= ADD:
        print('Multi-Redirect upgrade already applied.')
        return
    kept_raw = levels[:KEEP]
    kept = [parse(level) for level in kept_raw]
    rows, pairs = evaluate(kept)
    assert not pairs
    accepted = [(row['level'], row['method']) for row in rows]
    canons = {canon_sig(level['pen'], level['queues'], level['redirects'], [])
              for level, _ in accepted}
    rng = random.Random(SEED)
    added = []
    attempts = 0
    while len(added) < ADD:
        attempts += 1
        progress = len(added) / ADD
        arrow_count = 2 if progress < 0.56 else 3
        n = rng.choice((10, 11, 12)) if arrow_count == 2 else rng.choice((12, 13, 14))
        base = arrow_composite(n, rng, arrow_count)
        if base is None:
            continue
        pen, queues, redirects, _ = base
        try:
            raw = _raw_level(pen, queues, redirects, [], 0)
        except (AssertionError, TooLarge, RecursionError):
            continue
        raw.pop('gates', None)
        candidate = parse(raw)
        sig = canon_sig(candidate['pen'], candidate['queues'],
                        candidate['redirects'], [])
        if sig in canons:
            continue
        method, _ = shortest_method(candidate)
        if any(is_high_similarity(candidate, method, other, other_method)
               for other, other_method in accepted):
            continue
        accepted.append((candidate, method))
        canons.add(sig)
        added.append(raw)
        if len(added) % 50 == 0:
            print(f'  multi-arrow {len(added)}/{ADD} attempts={attempts}', flush=True)
    combined, _ = sort_by_difficulty(kept_raw + added)
    with open(path, 'w') as f:
        json.dump(combined, f, indent=1)
    print(f'upgraded={ADD} attempts={attempts}')


if __name__ == '__main__':
    main()
