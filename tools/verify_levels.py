#!/usr/bin/env python3
"""
Verify pigpen puzzle levels: BFS solver + MC failure rate.
Reads levels.json from the project root and verifies all 100 levels.

Slide rules (same semantics as main.gd):
- Pig slides in its direction until:
  1. head is inside pen AND next is outside pen  (one-way opening: can't exit)
  2. edge between head and next is a wall
  3. next is occupied by any other pig
- Moved 0 cells: not a valid move (no step consumed)

Bounding-box constraint: (pen cells + all pig initial cells) must fit in 10×11 grid.
"""

import json
import os
import sys
import random
from collections import deque

R, L, D, U = (1, 0), (-1, 0), (0, 1), (0, -1)

def ekey(a, b):
    return (min(a, b), max(a, b))

def add(a, b):
    return (a[0]+b[0], a[1]+b[1])

def build(level):
    pen = set(map(tuple, level["pen"]))
    open_edges = set()
    for opening in level["openings"]:
        c = tuple(opening[0]); d = tuple(opening[1])
        open_edges.add(ekey(c, add(c, d)))
    walls = set()
    DIRS = [R, L, D, U]
    for c in pen:
        for d in DIRS:
            n = add(c, d)
            if n in pen:
                continue
            k = ekey(c, n)
            if k not in open_edges:
                walls.add(k)
    return pen, walls

def solve(level):
    pen, walls = build(level)
    raw_pigs = level["pigs"]
    pigs = [(tuple(map(int, p[0])), tuple(map(int, p[1])), tuple(map(int, p[2])))
            for p in raw_pigs]
    dirs = [p[2] for p in pigs]
    init = tuple((p[0], p[1]) for p in pigs)

    # Sanity checks
    cells = []
    for t, h in init:
        cells += [t, h]
    assert len(set(cells)) == len(cells), "overlapping start pigs"
    for i, (t, h) in enumerate(init):
        assert t not in pen and h not in pen, f"pig {i} starts inside pen"
        d = dirs[i]
        n = add(h, d)
        assert ekey(h, n) not in walls, f"pig {i} aimed at a wall (head={h} next={n})"

    def try_slide(state, i):
        occ = set()
        for j, (t, h) in enumerate(state):
            if j != i:
                occ.add(t); occ.add(h)
        t, h = state[i]
        d = dirs[i]
        moved = 0
        while True:
            n = add(h, d)
            if h in pen and n not in pen:   # one-way: can't exit
                break
            if ekey(h, n) in walls:
                break
            if n in occ:
                break
            t, h = h, n
            moved += 1
            assert moved < 100, "infinite slide detected"
        if moved == 0:
            return None
        s = list(state); s[i] = (t, h)
        return tuple(s)

    def won(state):
        return all(t in pen and h in pen for t, h in state)

    seen = {init: (None, None)}
    q = deque([(init, 0)])
    while q:
        state, depth = q.popleft()
        if won(state):
            path = []
            s = state
            while seen[s][0] is not None:
                prev, i = seen[s]
                path.append(i)
                s = prev
            return depth, list(reversed(path))
        if depth >= 50:
            continue
        for i in range(len(pigs)):
            ns = try_slide(state, i)
            if ns is not None and ns not in seen:
                seen[ns] = (state, i)
                q.append((ns, depth + 1))
    return None, None


def monte_carlo(level, budget, n_sims=2000, seed=42):
    pen, walls = build(level)
    raw_pigs = level["pigs"]
    pigs = [(tuple(map(int, p[0])), tuple(map(int, p[1])), tuple(map(int, p[2])))
            for p in raw_pigs]
    dirs = [p[2] for p in pigs]
    n = len(pigs)
    rng = random.Random(seed)

    def try_slide(state, i):
        occ = set()
        for j, (t, h) in enumerate(state):
            if j != i:
                occ.add(t); occ.add(h)
        t, h = state[i]; d = dirs[i]; moved = 0
        while True:
            nx = add(h, d)
            if h in pen and nx not in pen: break
            if ekey(h, nx) in walls: break
            if nx in occ: break
            t, h = h, nx; moved += 1
            if moved >= 100: break
        if moved == 0: return None
        s = list(state); s[i] = (t, h); return tuple(s)

    def won(state):
        return all(t in pen and h in pen for t, h in state)

    init = tuple((p[0], p[1]) for p in pigs)
    failures = 0
    for _ in range(n_sims):
        state = init; steps = 0
        while steps < budget:
            movable = [i for i in range(n) if try_slide(state, i) is not None]
            if not movable: break
            i = rng.choice(movable)
            ns = try_slide(state, i)
            if ns is None: break
            state = ns; steps += 1
            if won(state): break
        if not won(state): failures += 1
    return failures / n_sims


def check_bbox(level, max_cols=10, max_rows=11):
    """Check bounding box constraint."""
    all_cells = list(map(tuple, level["pen"]))
    for p in level["pigs"]:
        all_cells.append(tuple(p[0]))
        all_cells.append(tuple(p[1]))
    xs = [c[0] for c in all_cells]
    ys = [c[1] for c in all_cells]
    cols = max(xs) - min(xs) + 1
    rows = max(ys) - min(ys) + 1
    return cols <= max_cols and rows <= max_rows, cols, rows


def main():
    script_dir = os.path.dirname(os.path.abspath(__file__))
    project_root = os.path.dirname(script_dir)
    levels_path = os.path.join(project_root, 'levels.json')

    if not os.path.exists(levels_path):
        print(f"ERROR: levels.json not found at {levels_path}", file=sys.stderr)
        sys.exit(1)

    with open(levels_path, 'r', encoding='utf-8') as f:
        levels = json.load(f)

    print(f"Verifying {len(levels)} levels from {levels_path}")
    print("=" * 80)
    print(f"{'#':<5} {'pigs':>4} {'min':>4} {'budget':>7} {'slack':>6} "
          f"{'mc_fail':>8} {'bbox':>8}  status")
    print("-" * 80)

    all_ok = True
    for idx, lv in enumerate(levels):
        name = f"L{idx+1:03d}"
        n_pigs = len(lv['pigs'])

        # Bounding box check
        bbox_pass, cols, rows = check_bbox(lv)
        if not bbox_pass:
            print(f"{name}: BBOX FAIL  {cols}x{rows} (max 10x11)")
            all_ok = False
            continue

        try:
            m, path = solve(lv)
        except AssertionError as e:
            print(f"{name}: INVALID - {e}")
            all_ok = False
            continue
        except Exception as e:
            print(f"{name}: ERROR - {e}")
            all_ok = False
            continue

        if m is None:
            print(f"{name}: UNSOLVABLE (budget={lv['steps']})")
            all_ok = False
        elif m > lv['steps']:
            print(f"{name}: STEPS TOO LOW  min={m}  budget={lv['steps']}  path={path}")
            all_ok = False
        else:
            slack = lv['steps'] - m
            # MC failure rate (fast, 500 sims during verify)
            mc = monte_carlo(lv, lv['steps'], n_sims=500, seed=idx * 17 + 42)
            bbox_str = f"{cols}x{rows}"
            print(f"{name}: OK  pigs={n_pigs:2d}  min={m:2d}  budget={lv['steps']:2d}  "
                  f"slack={slack}  mc_fail={mc:6.1%}  bbox={bbox_str}")

    print("=" * 80)
    if all_ok:
        print(f"ALL {len(levels)} LEVELS OK")
    else:
        print("SOME LEVELS FAILED")
        sys.exit(1)


if __name__ == '__main__':
    main()
