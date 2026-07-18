#!/usr/bin/env python3
"""Deterministically weave Redirect puzzles into the 100-level seed set.

The chosen overlays are not decorative: every accepted mechanism changes the
shortest solution (or turns an otherwise impossible layout into a solvable one).
"""
import json
import os

from generate_levels import (DIRS, add, analyze, build_walls, canon_sig,
                             norm_lens, ray_cells, solve)


ARROW_PUZZLES = [
    ([((0, 0), (-1, 0), 1), ((0, 0), (0, -1), 2)], (0, 1), (1, 0)),
    ([((0, 0), (-1, 0), 1), ((0, 1), (-1, 0), 2)], (2, 1), (0, -1)),
    ([((0, 0), (-1, 0), 1), ((2, 0), (0, -1), 2)], (2, 1), (-1, 0)),
    ([((0, 0), (-1, 0), 1), ((2, 1), (1, 0), 2)], (0, 1), (0, -1)),
    ([((0, 0), (-1, 0), 1), ((0, 0), (0, -1), 1),
      ((0, 1), (0, 1), 1)], (0, 1), (1, 0)),
]


COMBO_PUZZLES = [
    ([((0, 2), (0, 1), 2), ((3, 1), (1, 0), 2),
      ((0, 2), (-1, 0), 2)], (0, 0), (1, 0), ((2, 1), (3, 1))),
    ([((3, 2), (0, 1), 1), ((0, 0), (-1, 0), 2),
      ((3, 1), (1, 0), 2), ((3, 2), (1, 0), 1)],
     (0, 1), (0, 1), ((2, 1), (3, 1))),
    ([((3, 0), (1, 0), 1), ((0, 2), (0, 1), 1),
      ((0, 2), (-1, 0), 2), ((3, 0), (0, -1), 2)],
     (3, 1), (-1, 0), ((0, 1), (0, 2))),
    ([((3, 0), (0, -1), 3), ((0, 1), (-1, 0), 1),
      ((2, 0), (0, -1), 1), ((3, 0), (1, 0), 1)],
     (3, 2), (-1, 0), ((2, 0), (2, 1))),
    ([((3, 2), (1, 0), 2), ((3, 1), (1, 0), 1),
      ((0, 2), (0, 1), 2), ((1, 2), (0, 1), 1)],
     (0, 0), (1, 0), ((2, 2), (3, 2))),
]


def _normalize(pen, queues, redirects, gates):
    cells = list(pen)
    for c, d, count in queues:
        cells.extend(ray_cells(c, d, count))
    min_x = min(c[0] for c in cells)
    min_y = min(c[1] for c in cells)

    def sh(c):
        return (c[0] - min_x, c[1] - min_y)

    return (sorted(sh(c) for c in pen),
            [(sh(c), d, n) for c, d, n in queues],
            {sh(c): d for c, d in redirects.items()},
            [(sh(a), sh(b)) for a, b in gates])


def _raw_level(pen, queues, redirects, gates, slack=2):
    walls = build_walls(pen, [(c, d) for c, d, _ in queues])
    minimum = solve(pen, walls, queues, redirects=redirects, gate_edges=gates)
    assert minimum is not None
    analysis = analyze(pen, walls, queues, minimum + slack, redirects, gates)
    assert analysis is not None
    pen, queues, redirects, gates = _normalize(
        pen, queues, redirects, gates)
    return {
        'steps': minimum + slack,
        'min': minimum,
        'pen': [list(c) for c in pen],
        'queues': [[list(c), list(d), n] for c, d, n in queues],
        'redirects': [[list(c), list(d)] for c, d in sorted(redirects.items())],
        'gates': [[list(a), list(b)] for a, b in gates],
    }


def _decode(level):
    pen = set(map(tuple, level['pen']))
    queues = [(tuple(c), tuple(d), n) for c, d, n in level['queues']]
    return pen, queues


def apply_mechanics(levels):
    """Return a mechanism-enhanced copy of a base 100-level list."""
    levels = [dict(lv) for lv in levels]

    # L003-L007: Redirect teaching set. Each layout is impossible without its arrow.
    pen_3 = {(x, y) for x in range(3) for y in range(2)}
    for index, (queues, cell, direction) in zip(range(2, 7), ARROW_PUZZLES):
        levels[index] = _raw_level(pen_3, queues, {cell: direction}, [])

    # L024-L028: second Redirect set on larger boards.
    pen_6 = {(x, y) for x in range(4) for y in range(3)}
    for index, (queues, cell, direction, gate) in zip(
            range(23, 28), COMBO_PUZZLES):
        levels[index] = _raw_level(pen_6, queues, {cell: direction}, [], 1)

    # Normalize optional fields so consumers and signatures see an explicit schema.
    for level in levels:
        level.setdefault('redirects', [])
        level.setdefault('gates', [])

    signatures = []
    for level in levels:
        pen, queues = _decode(level)
        redirects = {tuple(c): tuple(d) for c, d in level['redirects']}
        gates = [tuple(sorted((tuple(a), tuple(b))))
                 for a, b in level.get('gates', [])]
        signatures.append(canon_sig(pen, queues, redirects, gates))
    assert len(set(signatures)) == len(levels), 'mechanized levels contain D4 duplicates'
    return levels


def build_report(levels):
    """Build metrics from the final data, after mechanisms are present."""
    lines = [
        '#    pigs min bud qu op rd gt  p_win  crit dcp    paths  pen',
        '-' * 72,
    ]
    for i, level in enumerate(levels):
        pen, queues = _decode(level)
        redirects = {tuple(c): tuple(d) for c, d in level['redirects']}
        gates = [tuple(sorted((tuple(a), tuple(b))))
                 for a, b in level.get('gates', [])]
        walls = build_walls(pen, [(c, d) for c, d, _ in queues])
        metrics = analyze(
            pen, walls, queues, level['steps'], redirects, gates)
        assert metrics is not None
        xs, ys = [c[0] for c in pen], [c[1] for c in pen]
        width, height = max(xs) - min(xs) + 1, max(ys) - min(ys) + 1
        q_lens = [norm_lens(q[2]) for q in queues]
        lines.append(
            f"L{i + 1:03d} {sum(len(l) for l in q_lens):4d} "
            f"{level['min']:3d} {level['steps']:3d} "
            f"{max(len(l) for l in q_lens):2d} {len(queues):2d} "
            f"{len(redirects):2d} {len(gates):2d} "
            f"{metrics['p_win'] * 100:6.2f} {metrics['crit']:4d} "
            f"{metrics['decep']:3d} "
            f"{min(metrics['n_paths'], 99999999):8d}  {width}x{height}")
    return '\n'.join(lines) + '\n'


def main():
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    path = os.path.join(root, 'levels.json')
    with open(path) as f:
        levels = json.load(f)
    levels = apply_mechanics(levels)
    with open(path, 'w') as f:
        json.dump(levels, f, indent=1)
    with open(os.path.join(root, 'tools', 'levels_report.txt'), 'w') as f:
        f.write(build_report(levels))
    print('Applied Redirect to L003-L007 and L024-L028.')


if __name__ == '__main__':
    main()
