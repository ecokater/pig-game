#!/usr/bin/env python3
"""
Pigpen Puzzle Level Generator — v5

DIFFICULTY MECHANISM:
- Pigs in DIFFERENT lanes can all move (high branching factor → random play makes mistakes)
- Cross-lane blocking: pig A's final cells sit in pig B's entry lane
  → must push A BEFORE B, or B gets permanently blocked mid-lane
- More cross-dependencies with tight budget → harder

GENERATORS:
1. cross_grid: W×H pen, some rows enter R/L, some cols enter D/U.
   Row pig's final cells fall in col pig's lane → cross-dependency.
2. linear_chain: N pigs in DIFFERENT rows/cols, but arranged so row 0
   is in col 1's lane, col 1 is in row 2's lane, etc.  Deep chain.
3. shaped (L-pen) for variety at medium difficulty.

Fixed seed 20260714.
"""

import random
import json
import sys
import os
from collections import deque

SEED = 20260714

R = (1, 0)
L = (-1, 0)
D = (0, 1)
U = (0, -1)
DIRS = [R, L, D, U]


def add(a, b):
    return (a[0] + b[0], a[1] + b[1])


def neg(d):
    return (-d[0], -d[1])


def ekey(a, b):
    return (min(a, b), max(a, b))


def build_walls(pen_set, openings):
    open_edges = set()
    for c, d in openings:
        open_edges.add(ekey(c, add(c, d)))
    walls = set()
    for c in pen_set:
        for d in DIRS:
            n = add(c, d)
            if n in pen_set:
                continue
            k = ekey(c, n)
            if k not in open_edges:
                walls.add(k)
    return walls


def solve(pen_set, walls, pigs_list, max_depth=50):
    dirs = [p[2] for p in pigs_list]
    init = tuple((p[0], p[1]) for p in pigs_list)

    def try_slide(state, i):
        occ = set()
        for j, (t, h) in enumerate(state):
            if j != i:
                occ.add(t)
                occ.add(h)
        t, h = state[i]
        d = dirs[i]
        moved = 0
        while True:
            n = add(h, d)
            if h in pen_set and n not in pen_set:
                break
            if ekey(h, n) in walls:
                break
            if n in occ:
                break
            t, h = h, n
            moved += 1
            if moved >= 100:
                return None
        if moved == 0:
            return None
        s = list(state)
        s[i] = (t, h)
        return tuple(s)

    def won(state):
        return all(t in pen_set and h in pen_set for t, h in state)

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
        if depth >= max_depth:
            continue
        for i in range(len(pigs_list)):
            ns = try_slide(state, i)
            if ns is not None and ns not in seen:
                seen[ns] = (state, i)
                q.append((ns, depth + 1))
    return None, None


def monte_carlo(pen_set, walls, pigs_list, budget, n_sims=2000, rng=None):
    if rng is None:
        rng = random.Random(42)
    dirs = [p[2] for p in pigs_list]
    n = len(pigs_list)

    def try_slide(state, i):
        occ = set()
        for j, (t, h) in enumerate(state):
            if j != i:
                occ.add(t)
                occ.add(h)
        t, h = state[i]
        d = dirs[i]
        moved = 0
        while True:
            nxt = add(h, d)
            if h in pen_set and nxt not in pen_set:
                break
            if ekey(h, nxt) in walls:
                break
            if nxt in occ:
                break
            t, h = h, nxt
            moved += 1
            if moved >= 100:
                break
        if moved == 0:
            return None
        s = list(state)
        s[i] = (t, h)
        return tuple(s)

    def won(state):
        return all(t in pen_set and h in pen_set for t, h in state)

    init = tuple((p[0], p[1]) for p in pigs_list)
    failures = 0
    for _ in range(n_sims):
        state = init
        steps = 0
        while steps < budget:
            movable = [i for i in range(n) if try_slide(state, i) is not None]
            if not movable:
                break
            i = rng.choice(movable)
            ns = try_slide(state, i)
            if ns is None:
                break
            state = ns
            steps += 1
            if won(state):
                break
        if not won(state):
            failures += 1
    return failures / n_sims


def bbox_ok(pen_set, pigs_list, max_cols=10, max_rows=11):
    all_cells = list(pen_set) + [c for p in pigs_list for c in (p[0], p[1])]
    if not all_cells:
        return False
    xs = [c[0] for c in all_cells]
    ys = [c[1] for c in all_cells]
    return max(xs) - min(xs) + 1 <= max_cols and max(ys) - min(ys) + 1 <= max_rows


def place_waiting(pig_specs, pen_set, rng):
    """
    pig_specs: list of (opening_cell, outward_dir, entry_dir)
    Returns list of (tail, head, entry_dir) or None.
    """
    lane_map = {}
    for i, (oc, od, ed) in enumerate(pig_specs):
        lane_map.setdefault((oc, od), []).append(i)

    occupied = set()
    pig_positions = {}

    for (oc, od), group in lane_map.items():
        slot = 1
        for idx in group:
            placed = False
            for gap in range(slot, slot + 40):
                hw = (oc[0] + od[0] * gap, oc[1] + od[1] * gap)
                tw = add(hw, od)
                if (hw not in occupied and tw not in occupied
                        and hw not in pen_set and tw not in pen_set):
                    occupied.add(hw)
                    occupied.add(tw)
                    pig_positions[idx] = (tw, hw)
                    slot = gap + 1
                    placed = True
                    break
            if not placed:
                return None

    if len(pig_positions) != len(pig_specs):
        return None

    return [(pig_positions[i][0], pig_positions[i][1], pig_specs[i][2])
            for i in range(len(pig_specs))]


def finalize(pen_set, pig_specs, rng):
    """
    pig_specs: list of (opening_cell, outward_dir, entry_dir, final_tail, final_head)
    """
    n = len(pig_specs)

    # Unique openings
    seen_open = set()
    openings = []
    for oc, od, ed, ft, fh in pig_specs:
        key = (oc, od)
        if key not in seen_open:
            seen_open.add(key)
            openings.append((oc, od))

    # Validate final positions
    used = set()
    for oc, od, ed, ft, fh in pig_specs:
        if ft not in pen_set or fh not in pen_set:
            return None
        if ft in used or fh in used:
            return None
        used.add(ft)
        used.add(fh)

    # Place waiting pigs
    wait_specs = [(oc, od, ed) for oc, od, ed, ft, fh in pig_specs]
    wait_pigs = place_waiting(wait_specs, pen_set, rng)
    if wait_pigs is None:
        return None

    if not bbox_ok(pen_set, wait_pigs):
        return None

    for t, h, d in wait_pigs:
        if t in pen_set or h in pen_set:
            return None

    walls = build_walls(pen_set, openings)

    for t, h, d in wait_pigs:
        n_cell = add(h, d)
        if ekey(h, n_cell) in walls:
            return None

    min_steps, path = solve(pen_set, walls, wait_pigs)
    if min_steps is None:
        return None

    xs = [c[0] for c in pen_set]
    ys = [c[1] for c in pen_set]
    return {
        'pen_set': pen_set, 'openings': openings, 'pigs': wait_pigs,
        'walls': walls, 'min_steps': min_steps, 'n_pigs': n,
        'cols': max(xs) - min(xs) + 1, 'rows': max(ys) - min(ys) + 1,
    }


# ── CROSS-GRID GENERATOR ──────────────────────────────────────────────────────
#
# Key idea: Row pigs enter from left/right; column pigs enter from top/bottom.
# A ROW pig's final cells can lie on a COL pig's entry lane (same (x, row_y) cell).
# → Row pig MUST enter before col pig → genuine ordering constraint.
#
# For N rows and M cols:
#   - n_row_pigs enter horizontally (one per row, some rows may have multiple)
#   - n_col_pigs enter vertically (one per column)
#   - The column opening is at a row boundary (top or bottom)
#   - The row pig's final horizontal position includes some col_x => row pig blocks col pig

def gen_cross_grid(rng, W, H, n_rows, n_cols, pigs_per_row=1, pigs_per_col=1):
    """
    W×H rectangular pen.
    n_rows rows enter horizontally (R or L), pigs_per_row pigs each.
    n_cols cols enter vertically (D or U), pigs_per_col pigs each.
    Cross-dependencies: row pig's final cells are in col pig's lane.
    """
    if W < 2 or H < 2:
        return None
    total_needed = n_rows * pigs_per_row + n_cols * pigs_per_col
    if total_needed < 2 or W * H < total_needed * 2:
        return None
    if W > 9 or H > 10:
        return None

    pen_set = set((x, y) for x in range(W) for y in range(H))

    for attempt in range(100):
        rows = list(range(H))
        cols = list(range(W))
        rng.shuffle(rows)
        rng.shuffle(cols)

        active_rows = rows[:n_rows]
        active_cols = cols[:n_cols]

        pig_specs = []
        used_cells = set()
        ok = True

        # Place row pigs
        for row_y in active_rows:
            entry_dir = rng.choice([R, L])
            outward = neg(entry_dir)
            if entry_dir == R:
                opening_col = 0
                # pigs stack right-to-left: pig 0 goes to (W-1, W-2), pig 1 to (W-3, W-4), ...
                pairs = [(W - 2 - 2*k, W - 1 - 2*k) for k in range(pigs_per_row)]
            else:
                opening_col = W - 1
                pairs = [(1 + 2*k, 2*k) for k in range(pigs_per_row)]

            oc = (opening_col, row_y)
            if add(oc, outward) in pen_set:
                ok = False
                break

            for tail_x, head_x in pairs[:pigs_per_row]:
                if tail_x < 0 or head_x < 0 or tail_x >= W or head_x >= W:
                    ok = False
                    break
                tc = (tail_x, row_y)
                hc = (head_x, row_y)
                if tc not in pen_set or hc not in pen_set:
                    ok = False
                    break
                if tc in used_cells or hc in used_cells:
                    ok = False
                    break
                pig_specs.append((oc, outward, entry_dir, tc, hc))
                used_cells.add(tc)
                used_cells.add(hc)

        if not ok:
            continue

        # Place col pigs
        for col_x in active_cols:
            entry_dir = rng.choice([D, U])
            outward = neg(entry_dir)
            if entry_dir == D:
                opening_row = 0
                pairs = [(H - 2 - 2*k, H - 1 - 2*k) for k in range(pigs_per_col)]
            else:
                opening_row = H - 1
                pairs = [(1 + 2*k, 2*k) for k in range(pigs_per_col)]

            oc = (col_x, opening_row)
            if add(oc, outward) in pen_set:
                ok = False
                break

            for tail_y, head_y in pairs[:pigs_per_col]:
                if tail_y < 0 or head_y < 0 or tail_y >= H or head_y >= H:
                    ok = False
                    break
                tc = (col_x, tail_y)
                hc = (col_x, head_y)
                if tc not in pen_set or hc not in pen_set:
                    ok = False
                    break
                if tc in used_cells or hc in used_cells:
                    ok = False
                    break
                pig_specs.append((oc, outward, entry_dir, tc, hc))
                used_cells.add(tc)
                used_cells.add(hc)

        if not ok or len(pig_specs) < 2:
            pig_specs.clear()
            used_cells.clear()
            continue

        result = finalize(pen_set, pig_specs, rng)
        if result:
            return result
        pig_specs.clear()
        used_cells.clear()

    return None


# ── EXPLICIT DEPENDENCY CHAIN ─────────────────────────────────────────────────
#
# Build a chain of length N:
#   pig_0 enters row_0 from left → final pos includes col_1_x
#   pig_1 enters col_1 from top → final pos includes (col_1_x, row_2_y) ... blocked by pig_0
#   pig_2 enters row_2 from right → final pos includes col_3_x ... blocked by pig_1
#   ...
# This creates an alternating row-col chain with depth N.

def gen_chain(rng, W, H, chain_len):
    """
    Alternating row-col chain of length chain_len.
    chain_len=1: just 1 pig (trivial), chain_len=2: A blocks B, chain_len=3: A→B→C, etc.
    """
    if W < 2 or H < 2 or chain_len < 2:
        return None
    if W > 9 or H > 10:
        return None
    pen_set = set((x, y) for x in range(W) for y in range(H))

    for attempt in range(150):
        pig_specs = []
        used = set()

        # Chain alternates: row, col, row, col, ...
        rows = list(range(H))
        cols = list(range(W))
        rng.shuffle(rows)
        rng.shuffle(cols)

        ok = True
        for step in range(chain_len):
            is_row = (step % 2 == 0)
            if is_row:
                if not rows:
                    ok = False
                    break
                row_y = rows.pop(0)
                entry_dir = rng.choice([R, L])
                outward = neg(entry_dir)
                if entry_dir == R:
                    oc = (0, row_y)
                    # Choose final position that includes a later col_x
                    # final head is the rightmost cell in this row not used
                    avail_x = [x for x in range(W - 1, -1, -1)
                                if (x, row_y) not in used and (x, row_y) in pen_set]
                    if len(avail_x) < 2:
                        ok = False
                        break
                    head_x = avail_x[0]
                    tail_x = avail_x[1]
                else:
                    oc = (W - 1, row_y)
                    avail_x = [x for x in range(0, W)
                                if (x, row_y) not in used and (x, row_y) in pen_set]
                    if len(avail_x) < 2:
                        ok = False
                        break
                    head_x = avail_x[0]
                    tail_x = avail_x[1]

                if add(oc, outward) in pen_set:
                    ok = False
                    break
                tc = (tail_x, row_y)
                hc = (head_x, row_y)
                if tc in used or hc in used:
                    ok = False
                    break
                pig_specs.append((oc, outward, entry_dir, tc, hc))
                used.add(tc)
                used.add(hc)
            else:
                if not cols:
                    ok = False
                    break
                col_x = cols.pop(0)
                entry_dir = rng.choice([D, U])
                outward = neg(entry_dir)
                if entry_dir == D:
                    oc = (col_x, 0)
                    avail_y = [y for y in range(H - 1, -1, -1)
                                if (col_x, y) not in used and (col_x, y) in pen_set]
                    if len(avail_y) < 2:
                        ok = False
                        break
                    head_y = avail_y[0]
                    tail_y = avail_y[1]
                else:
                    oc = (col_x, H - 1)
                    avail_y = [y for y in range(0, H)
                                if (col_x, y) not in used and (col_x, y) in pen_set]
                    if len(avail_y) < 2:
                        ok = False
                        break
                    head_y = avail_y[0]
                    tail_y = avail_y[1]

                if add(oc, outward) in pen_set:
                    ok = False
                    break
                tc = (col_x, tail_y)
                hc = (col_x, head_y)
                if tc in used or hc in used:
                    ok = False
                    break
                pig_specs.append((oc, outward, entry_dir, tc, hc))
                used.add(tc)
                used.add(hc)

        if not ok or len(pig_specs) < 2:
            continue

        result = finalize(pen_set, pig_specs, rng)
        if result and result['n_pigs'] >= 2:
            return result

    return None


# ── L-SHAPED PEN ──────────────────────────────────────────────────────────────

def gen_L_pen(rng, W1, H1, arm_w, arm_h, n_rows, n_cols):
    """L-shaped pen with mixed row/col entries."""
    pen_set = set((x, y) for x in range(W1) for y in range(H1))
    for x in range(arm_w):
        for y in range(H1, H1 + arm_h):
            pen_set.add((x, y))

    xs = [c[0] for c in pen_set]
    ys = [c[1] for c in pen_set]
    if max(xs) - min(xs) + 1 > 8 or max(ys) - min(ys) + 1 > 9:
        return None
    if len(pen_set) < (n_rows + n_cols) * 2:
        return None

    W = max(xs) + 1
    H = max(ys) + 1

    for attempt in range(80):
        pig_specs = []
        used = set()
        all_rows = sorted(set(c[1] for c in pen_set))
        all_cols = sorted(set(c[0] for c in pen_set))
        rng.shuffle(all_rows)
        rng.shuffle(all_cols)

        ok = True
        for row_y in all_rows[:n_rows]:
            row_xs = sorted(c[0] for c in pen_set if c[1] == row_y)
            if len(row_xs) < 2:
                continue
            min_x, max_x = row_xs[0], row_xs[-1]
            entry_dir = rng.choice([R, L])
            outward = neg(entry_dir)
            if entry_dir == R:
                oc = (min_x, row_y)
                tc = (max_x - 1, row_y)
                hc = (max_x, row_y)
            else:
                oc = (max_x, row_y)
                tc = (min_x + 1, row_y)
                hc = (min_x, row_y)
            if add(oc, outward) in pen_set:
                continue
            if tc in used or hc in used or tc not in pen_set or hc not in pen_set:
                continue
            pig_specs.append((oc, outward, entry_dir, tc, hc))
            used.add(tc)
            used.add(hc)

        for col_x in all_cols[:n_cols]:
            col_ys = sorted(c[1] for c in pen_set if c[0] == col_x)
            if len(col_ys) < 2:
                continue
            min_y, max_y = col_ys[0], col_ys[-1]
            entry_dir = rng.choice([D, U])
            outward = neg(entry_dir)
            if entry_dir == D:
                oc = (col_x, min_y)
                tc = (col_x, max_y - 1)
                hc = (col_x, max_y)
            else:
                oc = (col_x, max_y)
                tc = (col_x, min_y + 1)
                hc = (col_x, min_y)
            if add(oc, outward) in pen_set:
                continue
            if tc in used or hc in used or tc not in pen_set or hc not in pen_set:
                continue
            pig_specs.append((oc, outward, entry_dir, tc, hc))
            used.add(tc)
            used.add(hc)

        if len(pig_specs) < 2:
            continue

        result = finalize(pen_set, pig_specs, rng)
        if result:
            return result

    return None


# ── CANDIDATE GENERATION ──────────────────────────────────────────────────────

def generate_candidates(seed=SEED, target=600):
    rng = random.Random(seed)
    candidates = []

    def add_cand(result, slack_lo, slack_hi):
        if result is None:
            return
        if result['n_pigs'] < 2:
            return
        m = result['min_steps']
        n = result['n_pigs']
        slack = rng.randint(slack_lo, slack_hi)
        budget = m + slack
        mc = monte_carlo(result['pen_set'], result['walls'], result['pigs'],
                         budget, n_sims=300,
                         rng=random.Random(rng.randint(0, 999999)))
        candidates.append({
            'level': result, 'budget': budget, 'slack': slack,
            'mc_fail': mc, 'n_pigs': n, 'min_steps': m,
        })

    print("Generating candidates...", flush=True)

    # ── TRIVIAL (2 pigs, same opening, 0% fail) — for levels 1-10 ──
    # Just 1 row, 2 pigs queued from same side
    for _ in range(50):
        W = rng.randint(4, 7)
        H = rng.randint(1, 2)
        r = gen_cross_grid(rng, W, H, 1, 0, pigs_per_row=2, pigs_per_col=0)
        add_cand(r, 2, 3)

    # ── EASY (2 pigs, cross-lane, ~50% fail with budget min+1) ──
    for _ in range(80):
        W = rng.randint(3, 6)
        H = rng.randint(2, 5)
        r = gen_cross_grid(rng, W, H, 1, 1, pigs_per_row=1, pigs_per_col=1)
        add_cand(r, 1, 2)

    # 2-step chain
    for _ in range(80):
        W = rng.randint(3, 7)
        H = rng.randint(2, 5)
        r = gen_chain(rng, W, H, 2)
        add_cand(r, 1, 2)

    # ── EASY-MEDIUM (3-4 pigs, 1-2 cross deps) ──
    for _ in range(80):
        W = rng.randint(4, 7)
        H = rng.randint(2, 5)
        r = gen_cross_grid(rng, W, H, 2, 1, pigs_per_row=1, pigs_per_col=1)
        add_cand(r, 1, 2)

    for _ in range(80):
        W = rng.randint(4, 7)
        H = rng.randint(2, 5)
        r = gen_cross_grid(rng, W, H, 1, 2, pigs_per_row=1, pigs_per_col=1)
        add_cand(r, 1, 2)

    for _ in range(60):
        W = rng.randint(4, 8)
        H = rng.randint(3, 6)
        r = gen_chain(rng, W, H, 3)
        add_cand(r, 1, 2)

    # L-shaped medium
    for _ in range(60):
        r = gen_L_pen(rng, rng.randint(3, 5), rng.randint(2, 3),
                      rng.randint(1, 2), rng.randint(2, 3),
                      rng.randint(1, 2), rng.randint(1, 2))
        add_cand(r, 1, 2)

    # ── MEDIUM (4-6 pigs, multiple cross deps) ──
    for _ in range(80):
        W = rng.randint(4, 8)
        H = rng.randint(3, 7)
        r = gen_cross_grid(rng, W, H, 2, 2, pigs_per_row=1, pigs_per_col=1)
        add_cand(r, 1, 2)

    for _ in range(80):
        W = rng.randint(5, 8)
        H = rng.randint(3, 7)
        r = gen_cross_grid(rng, W, H, 3, 2, pigs_per_row=1, pigs_per_col=1)
        add_cand(r, 1, 2)

    for _ in range(80):
        W = rng.randint(5, 9)
        H = rng.randint(3, 7)
        r = gen_cross_grid(rng, W, H, 2, 3, pigs_per_row=1, pigs_per_col=1)
        add_cand(r, 1, 1)

    for _ in range(60):
        W = rng.randint(5, 9)
        H = rng.randint(4, 8)
        r = gen_chain(rng, W, H, 4)
        add_cand(r, 1, 1)

    # Row pigs with queuing + cross col
    for _ in range(80):
        W = rng.randint(5, 8)
        H = rng.randint(3, 6)
        r = gen_cross_grid(rng, W, H, 2, 2, pigs_per_row=2, pigs_per_col=1)
        add_cand(r, 1, 2)

    # ── HARD (6-8 pigs, many dependencies) ──
    for _ in range(80):
        W = rng.randint(5, 9)
        H = rng.randint(4, 8)
        r = gen_cross_grid(rng, W, H, 4, 3, pigs_per_row=1, pigs_per_col=1)
        add_cand(r, 1, 1)

    for _ in range(80):
        W = rng.randint(5, 9)
        H = rng.randint(4, 8)
        r = gen_cross_grid(rng, W, H, 3, 4, pigs_per_row=1, pigs_per_col=1)
        add_cand(r, 1, 1)

    for _ in range(80):
        W = rng.randint(6, 10)
        H = rng.randint(4, 9)
        r = gen_cross_grid(rng, W, H, 4, 4, pigs_per_row=1, pigs_per_col=1)
        add_cand(r, 0, 1)

    for _ in range(60):
        W = rng.randint(6, 10)
        H = rng.randint(5, 9)
        r = gen_chain(rng, W, H, 5)
        add_cand(r, 0, 1)

    for _ in range(60):
        W = rng.randint(6, 10)
        H = rng.randint(5, 9)
        r = gen_chain(rng, W, H, 6)
        add_cand(r, 0, 1)

    # ── VERY HARD (8-10 pigs) ──
    for _ in range(80):
        W = rng.randint(7, 10)
        H = rng.randint(5, 10)
        r = gen_cross_grid(rng, W, H, 5, 4, pigs_per_row=1, pigs_per_col=1)
        add_cand(r, 0, 1)

    for _ in range(80):
        W = rng.randint(7, 10)
        H = rng.randint(5, 10)
        r = gen_cross_grid(rng, W, H, 4, 5, pigs_per_row=1, pigs_per_col=1)
        add_cand(r, 0, 1)

    for _ in range(80):
        W = rng.randint(7, 10)
        H = rng.randint(5, 10)
        r = gen_cross_grid(rng, W, H, 5, 5, pigs_per_row=1, pigs_per_col=1)
        add_cand(r, 0, 1)

    for _ in range(60):
        W = rng.randint(7, 10)
        H = rng.randint(5, 10)
        r = gen_chain(rng, W, H, 7)
        add_cand(r, 0, 1)

    # Large multi-pig rows for 10-pig levels
    for _ in range(80):
        W = rng.randint(8, 10)
        H = rng.randint(5, 10)
        r = gen_cross_grid(rng, W, H, 3, 3, pigs_per_row=2, pigs_per_col=2)
        add_cand(r, 0, 1)

    print(f"Generated {len(candidates)} candidates.", flush=True)
    return candidates


def score_candidate(cand):
    n = cand['n_pigs']
    m = cand['min_steps']
    slack = cand['slack']
    mc = cand['mc_fail']
    # Primary: MC fail rate rounded to nearest 5% bucket (so 50% and 51% sort together)
    # Secondary: pig count and steps
    mc_bucket = round(mc * 20) / 20  # round to nearest 0.05
    return 100.0 * mc_bucket + 4.0 * n + 3.0 * m - 2.5 * slack


def select_100(candidates, seed=SEED):
    rng = random.Random(seed + 1)

    for c in candidates:
        c['score'] = score_candidate(c)

    # Sort: primary by mc_fail (exact), secondary by score
    candidates.sort(key=lambda c: (round(c['mc_fail'] * 20) / 20,
                                    4.0 * c['n_pigs'] + 3.0 * c['min_steps'] - 2.5 * c['slack']))
    n = len(candidates)
    print(f"Candidates: {n}, score range: {candidates[0]['score']:.2f}–{candidates[-1]['score']:.2f}",
          flush=True)

    if n < 100:
        print(f"ERROR: only {n} candidates!", flush=True)
        return candidates

    # Split candidates into groups by mc_fail level
    # Group: 0%, ~25%, ~50%, ~75%, ~90%, ~100%
    # We want levels 1-15 to be 0%, 16-40 to be ~25-50%, 41-65 to be ~50-75%,
    # 66-85 to be ~75-90%, 86-100 to be ~90-100%

    buckets = {
        '0': [c for c in candidates if c['mc_fail'] < 0.10],
        'low': [c for c in candidates if 0.10 <= c['mc_fail'] < 0.40],
        'mid': [c for c in candidates if 0.40 <= c['mc_fail'] < 0.70],
        'high': [c for c in candidates if 0.70 <= c['mc_fail'] < 0.90],
        'vhigh': [c for c in candidates if c['mc_fail'] >= 0.90],
    }
    for key in buckets:
        buckets[key].sort(key=lambda c: (c['mc_fail'], 4.0 * c['n_pigs'] + 3.0 * c['min_steps']))

    print(f"Buckets: 0%={len(buckets['0'])} low={len(buckets['low'])} "
          f"mid={len(buckets['mid'])} high={len(buckets['high'])} "
          f"vhigh={len(buckets['vhigh'])}", flush=True)

    # Assign positions to buckets:
    # L1-15: 0% fail (trivial)
    # L16-35: low (~25-50%)
    # L36-55: mid (~50-70%)
    # L56-75: high (~70-90%)
    # L76-100: vhigh (>90%)
    plan = [
        ('0', 15),
        ('low', 20),
        ('mid', 20),
        ('high', 20),
        ('vhigh', 25),
    ]

    selected = []
    for bucket_name, count in plan:
        pool = buckets[bucket_name]
        if len(pool) < count:
            # Fill with whatever is available, then pull from adjacent
            count = len(pool)
        if not pool:
            continue
        # Evenly space within the bucket
        indices_in_pool = [int(i * (len(pool) - 1) / max(count - 1, 1))
                           for i in range(count)]
        for idx in indices_in_pool:
            selected.append(pool[idx])

    # If we got fewer than 100, fill from full sorted list
    if len(selected) < 100:
        used_ids = set(id(c) for c in selected)
        extras = [c for c in candidates if id(c) not in used_ids]
        extras.sort(key=lambda c: c['score'])
        selected.extend(extras[:100 - len(selected)])

    # Sort final selection by score
    selected.sort(key=lambda c: (round(c['mc_fail'] * 20) / 20,
                                   4.0 * c['n_pigs'] + 3.0 * c['min_steps']))
    selected = selected[:100]

    # Apply budget curve
    for pos, cand in enumerate(selected):
        m = cand['min_steps']
        if pos < 20:
            slack = rng.randint(2, 3)
        elif pos < 50:
            slack = rng.randint(1, 2)
        elif pos < 80:
            slack = 1
        elif pos < 90:
            slack = 1 if (pos % 3 != 2) else 0
        else:
            # L91-95: slack=1, L96-100: slack=0
            slack = 1 if pos < 95 else 0
        cand['budget'] = m + slack
        cand['slack'] = slack

    return selected


def to_json_level(cand):
    level = cand['level']
    budget = cand['budget']
    pen = sorted([[c[0], c[1]] for c in level['pen_set']])
    openings = [[[o[0][0], o[0][1]], [o[1][0], o[1][1]]] for o in level['openings']]
    pigs = [[[p[0][0], p[0][1]], [p[1][0], p[1][1]], [p[2][0], p[2][1]]]
            for p in level['pigs']]
    return {'steps': budget, 'pen': pen, 'openings': openings, 'pigs': pigs}


def write_report(selected, out_path):
    lines = [
        "Pigpen Puzzle -- Level Generation Report v5",
        "=" * 70,
        f"{'#':>3}  {'shape':>7}  {'pigs':>4}  {'min':>4}  {'budget':>6}  "
        f"{'slack':>5}  {'mc_fail':>8}  {'score':>7}",
        "-" * 70,
    ]
    for i, cand in enumerate(selected):
        lv = cand['level']
        lines.append(
            f"{i+1:>3}  {lv['cols']}x{lv['rows']:<4}  {cand['n_pigs']:>4}  "
            f"{cand['min_steps']:>4}  {cand['budget']:>6}  {cand['slack']:>5}  "
            f"{cand['mc_fail']:>8.1%}  {cand['score']:>7.2f}"
        )
    with open(out_path, 'w') as f:
        f.write('\n'.join(lines) + '\n')
    print(f"Report -> {out_path}", flush=True)


def main():
    print("=== Pigpen Level Generator v5 ===", flush=True)

    candidates = generate_candidates(seed=SEED, target=600)
    if len(candidates) < 100:
        print(f"ERROR: only {len(candidates)} candidates.", file=sys.stderr)
        sys.exit(1)

    selected = select_100(candidates, seed=SEED)

    print("Running final Monte-Carlo (2000 sims)...", flush=True)
    mc_rng = random.Random(SEED + 2)
    for i, cand in enumerate(selected):
        lv = cand['level']
        cand['mc_fail'] = monte_carlo(
            lv['pen_set'], lv['walls'], lv['pigs'],
            cand['budget'], n_sims=2000,
            rng=random.Random(mc_rng.randint(0, 999999))
        )
        if (i + 1) % 20 == 0:
            print(f"  {i+1}/100 done", flush=True)

    json_levels = [to_json_level(c) for c in selected]

    project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    json_path = os.path.join(project_root, 'levels.json')
    with open(json_path, 'w', encoding='utf-8') as f:
        json.dump(json_levels, f, ensure_ascii=False, indent=2)
    print(f"levels.json -> {json_path} ({len(json_levels)} levels)", flush=True)

    report_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'levels_report.txt')
    write_report(selected, report_path)

    print("\n=== Difficulty curve ===", flush=True)
    print(f"{'Band':>12}  {'pigs':>6}  {'min':>6}  {'slack':>6}  {'mc_fail':>16}",
          flush=True)
    for band in range(10):
        bl = selected[band * 10:(band + 1) * 10]
        pr = [c['n_pigs'] for c in bl]
        mr = [c['min_steps'] for c in bl]
        sr = [c['slack'] for c in bl]
        mcr = [c['mc_fail'] for c in bl]
        print(
            f"L{band*10+1:02d}-L{band*10+10:03d}  "
            f"{min(pr)}-{max(pr):2d}    "
            f"{min(mr)}-{max(mr):2d}    "
            f"{min(sr)}-{max(sr):2d}    "
            f"{min(mcr)*100:5.1f}%-{max(mcr)*100:.1f}%",
            flush=True
        )

    print("\nKey levels (1/25/50/75/100):", flush=True)
    for idx in [0, 24, 49, 74, 99]:
        c = selected[idx]
        print(f"  L{idx+1:3d}: pigs={c['n_pigs']} min={c['min_steps']} "
              f"budget={c['budget']} slack={c['slack']} mc_fail={c['mc_fail']:.1%}",
              flush=True)

    print(f"\nDone. {len(json_levels)} levels saved.", flush=True)


if __name__ == '__main__':
    main()
