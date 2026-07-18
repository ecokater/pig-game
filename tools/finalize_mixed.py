#!/usr/bin/env python3
"""Regenerate reports and the audit for the mixed-body 1000-level set.

add_mixed_pigs.py 已把排序后的 levels.json 落盘,但报告写入在旧的
write_reports 上崩了(它假设队列第三项是整数)。本脚本只做收尾:
全量评测 → 断言难度非递减、相似对为 0 → 写报告与 mixed_audit.json。
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from add_mixed_pigs import OLD_MAX, SEED
from add_mud import write_reports
from evaluate_levels import evaluate, load_levels


def main():
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    levels = load_levels()
    print('final evaluation…', flush=True)
    rows, pairs = evaluate(levels)
    assert not pairs, f'{len(pairs)} similarity pairs remain'
    scores = [row['difficulty'] for row in rows]
    assert all(a <= b for a, b in zip(scores, scores[1:])), '难度未按非递减排序'
    write_reports(root, rows, pairs)

    with open(os.path.join(root, 'levels.json')) as f:
        sorted_raws = json.load(f)
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
