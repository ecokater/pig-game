#!/usr/bin/env python3
"""Difficulty and similarity evaluation for the final Pigpen level set.

Difficulty uses exact search metrics. Similarity deliberately combines layout
resemblance with a D4-invariant shortest-solution method trace, so a reskin or a
rotated board with the same reasoning pattern is still detected.
"""
import argparse
import json
import math
import os
import sys
from collections import Counter, deque

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from generate_levels import (DIRS, _xform, add, analyze, build_walls, q_moves,
                             q_won)

HIGH_SIMILARITY = 0.86
HIGH_METHOD = 0.92


def load_levels(path=None):
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    with open(path or os.path.join(root, 'levels.json')) as f:
        raw = json.load(f)
    out = []
    for level in raw:
        out.append({
            'steps': int(level['steps']), 'min': int(level['min']),
            'pen': set(map(tuple, level['pen'])),
            'queues': [(tuple(c), tuple(d), int(n))
                       for c, d, n in level['queues']],
            'redirects': {tuple(c): tuple(d)
                          for c, d in level.get('redirects', [])},
            'gates': [tuple(sorted((tuple(a), tuple(b))))
                      for a, b in level.get('gates', [])],
            'raw': level,
        })
    return out


def _counter_diff(after, before):
    return list((Counter(after) - Counter(before)).elements())


def transition_token(level, state, nxt):
    """D4-invariant description of one move on a shortest solution."""
    entered, counts, gate_mask = state
    ne, nc, ng = nxt
    released = sum(nc) < sum(counts)
    added = _counter_diff(ne, entered)
    removed = _counter_diff(entered, ne)
    new_pig = added[0] if added else None
    old_pig = removed[0] if removed else None
    turned = bool(old_pig and new_pig and old_pig[2] != new_pig[2])
    if released and new_pig:
        qi = next(i for i in range(len(counts)) if nc[i] < counts[i])
        turned = new_pig[2] != (-level['queues'][qi][1][0],
                                -level['queues'][qi][1][1])
        start_head = add(level['queues'][qi][0], level['queues'][qi][1])
    elif old_pig:
        start_head = old_pig[1]
    else:
        start_head = new_pig[1] if new_pig else (0, 0)
    distance = (abs(new_pig[1][0] - start_head[0])
                + abs(new_pig[1][1] - start_head[1])) if new_pig else 0
    dist_bucket = min(distance, 3)
    fully_inside = bool(new_pig and new_pig[0] in level['pen']
                        and new_pig[1] in level['pen'])
    return ('Q' if released else 'P', 'R' if turned else '-', str(dist_bucket),
            'I' if fully_inside else 'X')


def shortest_method(level):
    walls = build_walls(level['pen'], [(c, d) for c, d, _ in level['queues']])
    init = ((), tuple(q[2] for q in level['queues']), 0)
    queue = deque([init])
    parent = {init: None}
    action = {}
    won = None
    while queue:
        state = queue.popleft()
        if q_won(level['pen'], state):
            won = state
            break
        for nxt in q_moves(level['pen'], walls, level['queues'], state,
                           level['redirects'], level['gates']):
            if nxt not in parent:
                parent[nxt] = state
                action[nxt] = transition_token(level, state, nxt)
                queue.append(nxt)
    if won is None:
        raise ValueError('unsolvable level')
    trace = []
    while parent[won] is not None:
        trace.append(action[won])
        won = parent[won]
    trace.reverse()
    return tuple(trace), len(parent)


def difficulty(level, metrics, search_states):
    """Monotone score: scale, exact risk, reasoning depth, and mechanisms."""
    pigs = sum(q[2] for q in level['queues'])
    scarcity = max(0.0, 3.0 - math.log10(1 + metrics['n_paths']))
    return round(
        1.35 * pigs + 0.75 * level['min']
        + 3.2 * (1.0 - metrics['p_win'])
        + 0.55 * metrics['crit'] + 0.28 * metrics['decep']
        + 0.45 * (max(q[2] for q in level['queues']) - 1)
        + 0.45 * scarcity + 0.18 * math.log10(1 + search_states)
        + 0.35 * len(level['redirects']), 3)


def _normalized_shape(pen, transform):
    cells = [_xform(c, transform) for c in pen]
    min_x = min(x for x, _ in cells)
    min_y = min(y for _, y in cells)
    return {(x - min_x, y - min_y) for x, y in cells}


def _shape_variants(level):
    variants = level.get('_d4_shapes')
    if variants is None:
        variants = tuple(_normalized_shape(level['pen'], k) for k in range(8))
        level['_d4_shapes'] = variants
    return variants


def shape_similarity(a, b):
    # Cache all normalized variants. Independent min-corner normalization means
    # the 64 anchor combinations are not reducible to eight relative transforms.
    av, bv = _shape_variants(a), _shape_variants(b)
    return max(len(sa & sb) / len(sa | sb) for sa in av for sb in bv)


def _multiset_similarity(a, b):
    ca, cb = Counter(a), Counter(b)
    common = sum((ca & cb).values())
    total = max(sum(ca.values()), sum(cb.values()), 1)
    return common / total


def structural_similarity(a, b):
    shape = shape_similarity(a, b)
    queues = _multiset_similarity(
        [q[2] for q in a['queues']], [q[2] for q in b['queues']])
    mechanics = 1.0 - min(1.0,
        abs(len(a['redirects']) - len(b['redirects'])) / 2.0)
    scale = 1.0 - min(1.0, abs(len(a['pen']) - len(b['pen']))
                      / max(len(a['pen']), len(b['pen']), 1))
    return 0.50 * shape + 0.25 * queues + 0.15 * mechanics + 0.10 * scale


def sequence_similarity(a, b):
    """Normalized Levenshtein similarity of method tokens."""
    if not a and not b:
        return 1.0
    prev = list(range(len(b) + 1))
    for i, x in enumerate(a, 1):
        cur = [i]
        for j, y in enumerate(b, 1):
            cur.append(min(cur[-1] + 1, prev[j] + 1,
                           prev[j - 1] + (x != y)))
        prev = cur
    return 1.0 - prev[-1] / max(len(a), len(b), 1)


def evaluate(levels):
    rows = []
    for i, level in enumerate(levels):
        walls = build_walls(level['pen'],
                            [(c, d) for c, d, _ in level['queues']])
        metrics = analyze(level['pen'], walls, level['queues'], level['steps'],
                          level['redirects'], level['gates'])
        method, states = shortest_method(level)
        rows.append({'index': i, 'level': level, 'metrics': metrics,
                     'method': method, 'states': states,
                     'difficulty': difficulty(level, metrics, states)})
    pairs = []
    for i in range(len(rows)):
        for j in range(i + 1, len(rows)):
            structural = structural_similarity(levels[i], levels[j])
            method = sequence_similarity(rows[i]['method'], rows[j]['method'])
            combined = 0.48 * structural + 0.52 * method
            high = (combined >= HIGH_SIMILARITY
                    or (method >= HIGH_METHOD and structural >= 0.68))
            if high:
                pairs.append({'a': i, 'b': j, 'structural': structural,
                              'method': method, 'combined': combined})
    pairs.sort(key=lambda p: p['combined'], reverse=True)
    return rows, pairs


def report(rows, pairs):
    lines = [
        '# 关卡难度与相似度评测', '',
        '阈值：综合相似度 >= %.2f，或解法 >= %.2f 且结构 >= 0.68。'
        % (HIGH_SIMILARITY, HIGH_METHOD), '',
        '| 关卡 | 难度 | 猪 | 最优 | p_win | crit | decep | Redirect |',
        '|---:|---:|---:|---:|---:|---:|---:|---:|',
    ]
    for row in rows:
        level, m = row['level'], row['metrics']
        lines.append('| %03d | %.3f | %d | %d | %.4f | %d | %d | %d |'
                     % (row['index'] + 1, row['difficulty'],
                        sum(q[2] for q in level['queues']), level['min'],
                        m['p_win'], m['crit'], m['decep'],
                        len(level['redirects'])))
    lines += ['', '## 超阈值相似关卡', '']
    if not pairs:
        lines.append('无。')
    else:
        lines += ['| A | B | 结构 | 解法 | 综合 |', '|---:|---:|---:|---:|---:|']
        for p in pairs:
            lines.append('| %03d | %03d | %.3f | %.3f | %.3f |'
                         % (p['a'] + 1, p['b'] + 1, p['structural'],
                            p['method'], p['combined']))
    return '\n'.join(lines) + '\n'


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--json')
    parser.add_argument('--report')
    args = parser.parse_args()
    levels = load_levels(args.json)
    rows, pairs = evaluate(levels)
    text = report(rows, pairs)
    if args.report:
        with open(args.report, 'w') as f:
            f.write(text)
    print('levels=%d high_similarity_pairs=%d difficulty=%.3f..%.3f'
          % (len(rows), len(pairs), min(r['difficulty'] for r in rows),
             max(r['difficulty'] for r in rows)))
    for p in pairs[:20]:
        print('L%03d-L%03d structural=%.3f method=%.3f combined=%.3f'
              % (p['a'] + 1, p['b'] + 1, p['structural'], p['method'],
                 p['combined']))


if __name__ == '__main__':
    main()
