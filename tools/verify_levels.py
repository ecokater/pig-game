#!/usr/bin/env python3
"""Verify pigpen puzzle levels: BFS for min moves under slide rules."""
from collections import deque

R, L, D, U = (1, 0), (-1, 0), (0, 1), (0, -1)

def ekey(a, b):
    return (min(a, b), max(a, b))

def build(level):
    pen = set(map(tuple, level["pen"]))
    open_edges = set()
    for c, d in level["openings"]:
        c = tuple(c); d = tuple(d)
        open_edges.add(ekey(c, (c[0]+d[0], c[1]+d[1])))
    walls = set()
    for c in pen:
        for d in (R, L, D, U):
            n = (c[0]+d[0], c[1]+d[1])
            if n in pen:
                continue
            k = ekey(c, n)
            if k not in open_edges:
                walls.add(k)
    return pen, walls

def solve(level):
    pen, walls = build(level)
    pigs = [(tuple(t), tuple(h), tuple(d)) for t, h, d in level["pigs"]]
    dirs = [p[2] for p in pigs]
    init = tuple((p[0], p[1]) for p in pigs)

    # sanity: waiting cells disjoint, outside pen, aimed at an opening
    cells = []
    for (t, h) in init:
        cells += [t, h]
    assert len(set(cells)) == len(cells), "overlapping start pigs"
    for i, (t, h) in enumerate(init):
        assert t not in pen and h not in pen, f"pig {i} starts inside"
        d = dirs[i]
        n = (h[0]+d[0], h[1]+d[1])
        # 头前方要么直接是开口,要么是圈外通道(允许隔着外部格排队)
        assert ekey(h, n) not in walls, f"pig {i} aimed at a wall"

    def try_slide(state, i):
        occ = set()
        for j, (t, h) in enumerate(state):
            if j != i:
                occ.add(t); occ.add(h)
        t, h = state[i]
        d = dirs[i]
        moved = 0
        while True:
            n = (h[0]+d[0], h[1]+d[1])
            if h in pen and n not in pen:   # one-way: can't exit
                break
            if ekey(h, n) in walls:
                break
            if n in occ:
                break
            t, h = h, n
            moved += 1
            assert moved < 50
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
        for i in range(len(pigs)):
            ns = try_slide(state, i)
            if ns is not None and ns not in seen:
                seen[ns] = (state, i)
                q.append((ns, depth + 1))
    return None, None


LEVELS = [
    # 1: 2x2, 2 pigs, trivial
    dict(name="L1", steps=4,
         pen=[(x, y) for x in range(2) for y in range(2)],
         openings=[((0, 0), U), ((1, 0), U)],
         pigs=[((0, -2), (0, -1), D), ((1, -2), (1, -1), D)]),
    # 2: 3x2, 3 pigs, mild order
    dict(name="L2", steps=5,
         pen=[(x, y) for x in range(3) for y in range(2)],
         openings=[((0, 1), L), ((0, 0), U), ((2, 0), R)],
         pigs=[((-2, 1), (-1, 1), R), ((0, -2), (0, -1), D), ((4, 0), (3, 0), L)]),
    # 3: 4x2, 4 pigs
    dict(name="L3", steps=6,
         pen=[(x, y) for x in range(4) for y in range(2)],
         openings=[((3, 1), D), ((0, 0), L), ((0, 1), L), ((0, 0), U)],
         pigs=[((3, 3), (3, 2), U), ((-2, 0), (-1, 0), R),
               ((-2, 1), (-1, 1), R), ((0, -2), (0, -1), D)]),
    # 4: 3x3 with hole, 4 pigs
    dict(name="L4", steps=6,
         pen=[(x, y) for x in range(3) for y in range(3)],
         openings=[((0, 0), U), ((2, 0), R), ((1, 2), D), ((2, 2), D)],
         pigs=[((0, -2), (0, -1), D), ((4, 0), (3, 0), L),
               ((1, 4), (1, 3), U), ((2, 4), (2, 3), U)]),
    # 5: L-shape 10 cells, 5 pigs
    dict(name="L5", steps=7,
         pen=[(x, y) for x in range(3) for y in range(2)] + [(0, 2), (1, 2), (0, 3), (1, 3)],
         openings=[((2, 0), U), ((0, 0), L), ((0, 1), L), ((0, 3), D), ((1, 3), D)],
         pigs=[((2, -2), (2, -1), D), ((-2, 0), (-1, 0), R), ((-2, 1), (-1, 1), R),
               ((0, 5), (0, 4), U), ((1, 5), (1, 4), U)]),
    # 6: 4x3, 6 pigs (original level)
    dict(name="L6", steps=8,
         pen=[(x, y) for x in range(4) for y in range(3)],
         openings=[((0, 0), L), ((0, 2), L), ((1, 0), U), ((3, 0), U), ((0, 2), D), ((2, 2), D)],
         pigs=[((-2, 0), (-1, 0), R), ((-2, 2), (-1, 2), R), ((1, -2), (1, -1), D),
               ((3, -2), (3, -1), D), ((0, 4), (0, 3), U), ((2, 4), (2, 3), U)]),
    # 7: 4x3, 6 pigs, long dependency chain
    dict(name="L7", steps=7,
         pen=[(x, y) for x in range(4) for y in range(3)],
         openings=[((0, 0), L), ((0, 0), U), ((1, 0), U), ((0, 2), L), ((2, 2), D), ((3, 2), D)],
         pigs=[((-2, 0), (-1, 0), R), ((0, -2), (0, -1), D), ((1, -2), (1, -1), D),
               ((-2, 2), (-1, 2), R), ((2, 4), (2, 3), U), ((3, 4), (3, 3), U)]),
    # 8: 4x3 block + top-left arm (14 cells), 7 pigs
    dict(name="L8", steps=8,
         pen=[(0, 0), (1, 0)] + [(x, y) for x in range(4) for y in range(1, 4)],
         openings=[((0, 0), L), ((0, 3), D), ((0, 3), L), ((1, 3), D),
                   ((3, 1), R), ((2, 3), D), ((3, 3), D)],
         pigs=[((-2, 0), (-1, 0), R), ((0, 5), (0, 4), U), ((-2, 3), (-1, 3), R),
               ((1, 5), (1, 4), U), ((5, 1), (4, 1), L), ((2, 5), (2, 4), U),
               ((3, 5), (3, 4), U)]),
    # 9: plus shape (4x4 minus corners), 6 pigs
    dict(name="L9", steps=7,
         pen=[(1, 0), (2, 0), (0, 1), (1, 1), (2, 1), (3, 1),
              (0, 2), (1, 2), (2, 2), (3, 2), (1, 3), (2, 3)],
         openings=[((1, 0), L), ((2, 3), R), ((0, 1), L), ((0, 2), L),
                   ((0, 1), U), ((3, 1), U)],
         pigs=[((-1, 0), (0, 0), R), ((4, 3), (3, 3), L), ((-2, 1), (-1, 1), R),
               ((-2, 2), (-1, 2), R), ((0, -2), (0, -1), D), ((3, -1), (3, 0), D)]),
    # 10: 4x4, 8 pigs, deep chain
    dict(name="L10", steps=9,
         pen=[(x, y) for x in range(4) for y in range(4)],
         openings=[((0, 0), L), ((0, 1), L), ((0, 2), L), ((0, 3), L),
                   ((0, 0), U), ((1, 0), U), ((2, 3), D), ((3, 3), D)],
         pigs=[((-2, 0), (-1, 0), R), ((-2, 1), (-1, 1), R), ((-2, 2), (-1, 2), R),
               ((-2, 3), (-1, 3), R), ((0, -2), (0, -1), D), ((1, -2), (1, -1), D),
               ((2, 5), (2, 4), U), ((3, 5), (3, 4), U)]),
]

for lv in LEVELS:
    try:
        m, path = solve(lv)
    except AssertionError as e:
        print(f'{lv["name"]}: INVALID - {e}')
        continue
    if m is None:
        print(f'{lv["name"]}: UNSOLVABLE')
    else:
        ok = "OK " if m <= lv["steps"] else "STEPS TOO LOW"
        print(f'{lv["name"]}: min={m} budget={lv["steps"]} {ok} path={path}')
