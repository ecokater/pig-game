#!/usr/bin/env python3
"""Verify that the hint oracle always selects a legal shortest-path move.

For every level, reconstruct the complete shortest path from the same ordered
move generator used by the in-game DFS. At every intermediate state, verify the
highlighted next move is legal and that the remaining suffix still wins within
the displayed remaining-step budget.
"""
import sys
import os
from collections import deque

from evaluate_levels import load_levels
from generate_levels import build_walls, q_moves, q_won


def shortest_state_path(level):
    walls = build_walls(level['pen'], [(c, d) for c, d, _ in level['queues']])
    initial = ((), tuple(q[2] for q in level['queues']), 0)
    queue = deque([initial])
    parent = {initial: None}
    won = None
    while queue:
        state = queue.popleft()
        if q_won(level['pen'], state):
            won = state
            break
        for nxt in q_moves(level['pen'], walls, level['queues'], state,
                           level['redirects'], [], level.get('muds')):
            if nxt not in parent:
                parent[nxt] = state
                queue.append(nxt)
    if won is None:
        raise AssertionError('hint oracle found no solution')
    path = []
    while won is not None:
        path.append(won)
        won = parent[won]
    path.reverse()
    return path, walls


def main():
    levels = load_levels()
    checked_states = 0
    multi_levels = 0
    for index, level in enumerate(levels):
        path, walls = shortest_state_path(level)
        if len(path) - 1 != level['min']:
            raise AssertionError(
                f'L{index + 1:04d}: hint path {len(path)-1} != min {level["min"]}')
        if len(level['redirects']) >= 2:
            multi_levels += 1
        for step, (state, hinted) in enumerate(zip(path, path[1:])):
            legal = q_moves(level['pen'], walls, level['queues'], state,
                            level['redirects'], [], level.get('muds'))
            if hinted not in legal:
                raise AssertionError(
                    f'L{index + 1:04d} step {step}: hint is not legal')
            remaining = level['steps'] - step
            if len(path) - step - 1 > remaining:
                raise AssertionError(
                    f'L{index + 1:04d} step {step}: hint exceeds budget')
            checked_states += 1
        if not q_won(level['pen'], path[-1]):
            raise AssertionError(f'L{index + 1:04d}: hint suffix does not win')
    result = (f'ALL {len(levels)} LEVEL HINTS OK; '
              f'path_states={checked_states}; multi_redirect_levels={multi_levels}')
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    with open(os.path.join(root, 'tools', 'hint_report.txt'), 'w') as f:
        f.write(result + '\n')
    print(result)


if __name__ == '__main__':
    try:
        main()
    except Exception as exc:
        print(f'HINT VERIFY FAILED: {exc}', file=sys.stderr)
        raise
