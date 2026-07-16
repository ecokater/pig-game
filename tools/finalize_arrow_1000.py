#!/usr/bin/env python3
"""One-pass final reports and audit for the Gate-free 1000-level set."""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from evaluate_levels import evaluate, load_levels, report


def main():
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    levels_path = os.path.join(root, 'levels.json')
    with open(levels_path) as f:
        raw = json.load(f)
    assert len(raw) == 1000
    assert not any('gates' in level for level in raw)
    levels = load_levels(levels_path)
    rows, pairs = evaluate(levels)
    scores = [row['difficulty'] for row in rows]
    assert all(a <= b for a, b in zip(scores, scores[1:]))
    assert not pairs
    late = raw[700:]
    late_redirects = sum(bool(level.get('redirects')) for level in late)
    total_redirects = sum(bool(level.get('redirects')) for level in raw)
    multi_redirects = sum(len(level.get('redirects', [])) >= 2 for level in raw)
    triple_redirects = sum(len(level.get('redirects', [])) >= 3 for level in raw)
    assert late_redirects >= 285
    assert multi_redirects >= 450
    assert all(len(level.get('redirects', [])) == 3 for level in raw[-100:])
    assert scores[700] >= 33.0

    with open(os.path.join(root, 'tools', 'levels_evaluation_after.md'), 'w') as f:
        f.write(report(rows, pairs))
    lines = ['#    pigs min bud qu op rd  p_win  crit dcp    paths  difficulty',
             '-' * 78]
    for row in rows:
        level, metrics = row['level'], row['metrics']
        lines.append(
            f"L{row['index'] + 1:04d} "
            f"{sum(q[2] for q in level['queues']):4d} "
            f"{level['min']:3d} {level['steps']:3d} "
            f"{max(q[2] for q in level['queues']):2d} "
            f"{len(level['queues']):2d} {len(level['redirects']):2d} "
            f"{metrics['p_win'] * 100:6.2f} {metrics['crit']:4d} "
            f"{metrics['decep']:3d} "
            f"{min(metrics['n_paths'], 99999999):8d} "
            f"{row['difficulty']:8.3f}")
    with open(os.path.join(root, 'tools', 'levels_report.txt'), 'w') as f:
        f.write('\n'.join(lines) + '\n')
    audit = {
        'seed': 20260718, 'levels': len(raw),
        'total_redirects': total_redirects, 'total_gates': 0,
        'multi_redirect_levels': multi_redirects,
        'triple_redirect_levels': triple_redirects,
        'late_range': [701, 1000], 'late_redirects': late_redirects,
        'difficulty_min': scores[0], 'difficulty_l701': scores[700],
        'difficulty_max': scores[-1], 'high_similarity_pairs': 0,
    }
    with open(os.path.join(root, 'tools', 'expansion_audit.json'), 'w') as f:
        json.dump(audit, f, indent=2)
    print(json.dumps(audit, ensure_ascii=False))


if __name__ == '__main__':
    main()
