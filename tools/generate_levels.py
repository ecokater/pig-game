#!/usr/bin/env python3
"""
小猪进圈 · 100 关生成器 v4(队列模型 + 8×10 猪圈 + D4 全变换去重)

与 v3 的区别:
- 队列模型:每个开口是一条 FIFO 猪队(数量不限)。只有队首的猪可以被点击
  释放进圈;其余的猪自动排队补位,不占棋盘格。游戏里排不下的用 🐷×n 徽章
  收纳显示。被收纳(未现身)的猪不可点击 —— 分析模型与游戏行为完全一致。
- 猪圈本体 bbox ≤ 8 宽 × 10 高(竖屏),圈外只需要给可见槽位留出直线净空。
- 去重:每关按 D4 群(旋转 90/180/270 + 四种镜像)取规范签名,100 关两两
  不同;另要求"玩法特征"(形状类 + 猪数 + 开口数 + 队列构成)全局唯一,
  保证每一关玩起来都有差异。
- 难度依旧全部来自精确状态空间分析(p_win / crit / decep / paths),无抽样。

用法:python3 tools/generate_levels.py
输出:../levels.json 与 levels_report.txt
"""
import json
import math
import os
import random
from collections import deque, defaultdict

SEED = 20260716
DIRS = [(1, 0), (-1, 0), (0, 1), (0, -1)]

# 猪圈本体尺寸上限(宽 × 高)
PEN_MAX_W, PEN_MAX_H = 8, 10

# 每个开口在圈外可见的排队猪数;之后的猪收纳进 🐷×n 徽章(与游戏一致)
VISIBLE_PIGS = 2

# 猪数曲线:每个猪数是一个"世界",单调不减
PIG_CURVE = ([2] * 2 + [3] * 5 + [4] * 7 + [5] * 9 + [6] * 11 + [7] * 12
             + [8] * 13 + [9] * 12 + [10] * 11 + [11] * 9 + [12] * 9)
assert len(PIG_CURVE) == 100

# 每个世界:学习关占比(p_win=1)与步数余量集合
LEARN_FRAC = {2: 0.5, 3: 0.8, 4: 0.45, 5: 0.35, 6: 0.27,
              7: 0.17, 8: 0.15, 9: 0.08, 10: 0.09, 11: 0.0, 12: 0.0}
WORLD_SLACKS = {2: (3,), 3: (3,), 4: (3, 2), 5: (2,), 6: (2, 1),
                7: (1,), 8: (1,), 9: (1, 0), 10: (1, 0), 11: (0,), 12: (0,)}

POOL_TARGET = {2: 30, 3: 110, 4: 110, 5: 100, 6: 100, 7: 100,
               8: 100, 9: 90, 10: 90, 11: 70, 12: 70}

# 状态空间保险丝:精确分析超过该状态数的候选直接弃用(保证每关都可精确验证)
DP_STATE_CAP = 3_000_000
BFS_NODE_CAP = 2_000_000

# 前 8 关(全局关位)的形状教学偏好
TUTORIAL_PREF = {
    0: {'rect'}, 1: {'notch'}, 2: {'rect'}, 3: {'T', 'L'},
    4: {'L', 'notch'}, 5: {'rect', 'T'}, 6: {'plus', 'U', 'T'},
    7: {'U', 'plus', 'stairs', 'L', 'notch'},
}


def add(a, b):
    return (a[0] + b[0], a[1] + b[1])


def neg(d):
    return (-d[0], -d[1])


def ekey(a, b):
    return (min(a, b), max(a, b))


# ── 规则内核(与游戏内 GDScript 完全一致)────────────────────────────────────
# 关卡 = 猪圈 pen_set + 开口队列 queues=[(entry_cell, out_dir, count)]
# 状态 = (已入场猪的 (tail, head, move_dir) 有序元组, 各队列剩余数)
# 合法移动:
#   1. 释放某队列的队首猪:在开口外 (c+2d, c+d) 生成、沿 -d 滑入,至少走 1 格;
#   2. 点击已入场的猪(含跨在开口上的),沿其固定方向再滑,至少走 1 格。
# 胜利 = 所有队列清空 且 所有已入场猪完全在圈内。

def build_walls(pen_set, openings):
    open_edges = set()
    for c, d in openings:
        open_edges.add(ekey(c, add(c, d)))
    walls = set()
    for c in pen_set:
        for d in DIRS:
            nb = add(c, d)
            if nb in pen_set:
                continue
            k = ekey(c, nb)
            if k not in open_edges:
                walls.add(k)
    return walls


def _slide(pen_set, walls, occ, t, h, m):
    """从 (t,h) 沿 m 滑到底;occ 为其他猪占格。返回 (moved, t, h)。"""
    moved = 0
    while moved < 100:
        nxt = add(h, m)
        if h in pen_set and nxt not in pen_set:
            break
        if ekey(h, nxt) in walls:
            break
        if nxt in occ:
            break
        t, h = h, nxt
        moved += 1
    return moved, t, h


def q_moves(pen_set, walls, queues, state):
    """枚举当前状态的所有合法移动,返回 [(新状态)]。
    state = (entered, counts):entered = ((t,h,m), ...) 排序元组。"""
    entered, counts = state
    occ = set()
    for t, h, m in entered:
        occ.add(t)
        occ.add(h)
    results = []

    # 1. 释放各队列的队首猪
    for qi, (c, d, total) in enumerate(queues):
        if counts[qi] == 0:
            continue
        h0 = add(c, d)
        t0 = add(h0, d)
        if h0 in occ or t0 in occ:
            continue
        m = neg(d)
        moved, t, h = _slide(pen_set, walls, occ, t0, h0, m)
        if moved == 0:
            continue
        ne = tuple(sorted(entered + ((t, h, m),)))
        nc = counts[:qi] + (counts[qi] - 1,) + counts[qi + 1:]
        results.append((ne, nc))

    # 2. 已入场的猪再滑
    for i, (t, h, m) in enumerate(entered):
        occ2 = occ - {t, h}
        moved, nt, nh = _slide(pen_set, walls, occ2, t, h, m)
        if moved == 0:
            continue
        ne = tuple(sorted(entered[:i] + entered[i + 1:] + ((nt, nh, m),)))
        results.append((ne, counts))
    return results


def q_won(pen_set, state):
    entered, counts = state
    if any(counts):
        return False
    return all(t in pen_set and h in pen_set for t, h, m in entered)


def solve(pen_set, walls, queues, max_depth=60):
    """BFS 最短解;返回 最优步数 或 None。"""
    init = ((), tuple(q[2] for q in queues))
    seen = {init}
    q = deque([(init, 0)])
    while q:
        state, depth = q.popleft()
        if q_won(pen_set, state):
            return depth
        if depth >= max_depth:
            continue
        if len(seen) > BFS_NODE_CAP:
            return None
        for ns in q_moves(pen_set, walls, queues, state):
            if ns not in seen:
                seen.add(ns)
                q.append((ns, depth + 1))
    return None


# ── 精确难度分析(全状态空间,无抽样)─────────────────────────────────────────

class TooLarge(Exception):
    pass


def analyze(pen_set, walls, queues, budget):
    """返回 {p_win, n_paths, crit, decep} 或 None(预算内不可解);
    状态数超过 DP_STATE_CAP 抛 TooLarge。"""
    init = ((), tuple(q[2] for q in queues))

    moves_memo = {}

    def moves(state):
        r = moves_memo.get(state)
        if r is None:
            r = q_moves(pen_set, walls, queues, state)
            moves_memo[state] = r
            if len(moves_memo) > DP_STATE_CAP:
                raise TooLarge()
        return r

    won_memo = {}

    def won(state):
        r = won_memo.get(state)
        if r is None:
            r = q_won(pen_set, state)
            won_memo[state] = r
        return r

    dp_memo = {}

    def dp(state, r):
        key = (state, r)
        res = dp_memo.get(key)
        if res is not None:
            return res
        if won(state):
            res = (1.0, 1)
        elif r == 0:
            res = (0.0, 0)
        else:
            ms = moves(state)
            if not ms:
                res = (0.0, 0)
            else:
                p = 0.0
                np_ = 0
                for ns in ms:
                    sp, sn = dp(ns, r - 1)
                    p += sp
                    np_ += sn
                res = (p / len(ms), np_)
        dp_memo[key] = res
        return res

    play_memo = {}

    def maxplay(state, r):
        key = (state, r)
        res = play_memo.get(key)
        if res is not None:
            return res
        if won(state) or r == 0:
            res = 0
        else:
            ms = moves(state)
            res = 0 if not ms else 1 + max(maxplay(ns, r - 1) for ns in ms)
        play_memo[key] = res
        return res

    p_win, n_paths = dp(init, budget)
    if p_win <= 0.0:
        return None

    crit = 0
    decep = 0
    state, r = init, budget
    while not won(state):
        ms = moves(state)
        good, fatal = [], []
        for ns in ms:
            (good if dp(ns, r - 1)[0] > 0.0 else fatal).append(ns)
        if fatal:
            crit += 1
            decep = max(decep, max(maxplay(ns, r - 1) for ns in fatal))
        state = max(good, key=lambda ns: dp(ns, r - 1)[0])
        r -= 1
    return {'p_win': p_win, 'n_paths': n_paths, 'crit': crit, 'decep': decep}


def difficulty(cand, sl):
    """人类体感难度分:规模 + 依赖链 + 失败风险 + 抉择密度 + 死局隐蔽度
    + 解的稀缺度 + 排队深度。"""
    a = cand['an'][sl]
    u = math.log10(1 + a['n_paths'])
    return round(
        1.2 * cand['n_pigs']
        + 0.5 * cand['chain']
        + 3.0 * (1.0 - a['p_win'])
        + 0.5 * a['crit']
        + 0.25 * a['decep']
        + max(0.0, 2.5 - u)
        + 0.5 * (cand['max_queue'] - 1), 2)


# ── D4 变换与签名 ─────────────────────────────────────────────────────────────

def _xform(c, k):
    x, y = c
    if k == 0:
        return (x, y)
    if k == 1:
        return (-y, x)      # 旋转 90°
    if k == 2:
        return (-x, -y)     # 旋转 180°
    if k == 3:
        return (y, -x)      # 旋转 270°
    if k == 4:
        return (-x, y)      # 水平镜像
    if k == 5:
        return (x, -y)      # 垂直镜像
    if k == 6:
        return (y, x)       # 主对角镜像
    return (-y, -x)         # 副对角镜像


def canon_sig(pen_set, queues):
    """D4 八变换下的规范签名:任意两关(含彼此的旋转/镜像)都不同。"""
    best = None
    for k in range(8):
        pen = [_xform(c, k) for c in pen_set]
        qs = [(_xform(c, k), _xform(add(c, d), k), n) for c, d, n in queues]
        mx = min(c[0] for c in pen)
        my = min(c[1] for c in pen)
        pen_n = tuple(sorted((x - mx, y - my) for x, y in pen))
        qs_n = tuple(sorted(((c[0] - mx, c[1] - my),
                             (o[0] - mx, o[1] - my), n) for c, o, n in qs))
        sig = (pen_n, qs_n)
        if best is None or sig < best:
            best = sig
    return best


def play_sig(cand):
    """玩法特征签名(旋转无关):形状类 + 猪数 + 开口数 + 队列构成。
    全局唯一 → 每一关玩起来都有差异。"""
    profile = tuple(sorted((n for _, _, n in cand['queues']), reverse=True))
    return (cand['cls'], cand['n_pigs'], len(cand['queues']), profile)


# ── 形状库(bbox ≤ 8 宽 × 10 高)───────────────────────────────────────────────

def rect(w, h, x0=0, y0=0):
    return {(x0 + x, y0 + y) for x in range(w) for y in range(h)}


def _dims_ok(cells):
    xs = [c[0] for c in cells]
    ys = [c[1] for c in cells]
    return (max(xs) - min(xs) + 1 <= PEN_MAX_W
            and max(ys) - min(ys) + 1 <= PEN_MAX_H)


def gen_shape(rng, target_cells):
    cls = rng.choice(['rect', 'rect', 'L', 'T', 'U', 'plus', 'stairs',
                      'notch', 'Z', 'H'])
    cells = None
    if cls == 'rect':
        opts = [(w, target_cells // w) for w in range(2, 9)
                if target_cells % w == 0 and 2 <= target_cells // w <= 10]
        if not opts:
            return None
        w, h = rng.choice(opts)
        cells = rect(w, h)
    elif cls == 'notch':
        opts = [(w, (target_cells + 2) // w) for w in range(3, 9)
                if (target_cells + 2) % w == 0
                and 2 <= (target_cells + 2) // w <= 10]
        if not opts:
            return None
        w, h = rng.choice(opts)
        cells = rect(w, h)
        horiz = rng.random() < 0.5
        corner = rng.choice([(0, 0), (w - 1, 0), (0, h - 1), (w - 1, h - 1)])
        cx, cy = corner
        if horiz:
            bx = cx if cx == 0 else cx - 1
            bite = {(bx, cy), (bx + 1, cy)}
        else:
            by = cy if cy == 0 else cy - 1
            bite = {(cx, by), (cx, by + 1)}
        cells -= bite
        if cells:
            xs = [c[0] for c in cells]
            ys = [c[1] for c in cells]
            if max(xs) - min(xs) + 1 != w or max(ys) - min(ys) + 1 != h:
                return None   # 咬掉整条边退化成矩形
    elif cls == 'L':
        for _ in range(20):
            w, h = rng.randint(2, 6), rng.randint(2, 6)
            rest = target_cells - w * h
            if rest <= 0:
                continue
            opts = [(aw, rest // aw) for aw in range(2, w + 1)
                    if rest % aw == 0 and 1 <= rest // aw <= 4]
            if not opts:
                continue
            aw, ah = rng.choice(opts)
            cells = rect(w, h) | rect(aw, ah, 0, h)
            break
    elif cls == 'T':
        for _ in range(20):
            bw = rng.choice([4, 5, 6, 7, 8])
            bh = rng.randint(1, 3)
            rest = target_cells - bw * bh
            if rest <= 0 or rest % 2 != 0:
                continue
            sh = rest // 2
            if not 1 <= sh <= 7:
                continue
            off = (bw - 2) // 2
            cells = rect(bw, bh) | rect(2, sh, off, bh)
            break
    elif cls == 'U':
        for _ in range(20):
            w = rng.randint(4, 8)
            h = rng.randint(3, 6)
            side = rng.randint(1, 2)
            nw = w - 2 * side
            if nw < 1:
                continue
            for nh in range(1, h - 1):
                if w * h - nw * nh == target_cells:
                    cells = rect(w, h) - rect(nw, nh, side, 0)
                    break
            if cells:
                break
    elif cls == 'plus':
        for arm in (1, 2):
            if 4 + 8 * arm == target_cells:
                c = arm
                cells = (rect(2, 2, c, c) | rect(2, arm, c, 0)
                         | rect(2, arm, c, c + 2) | rect(arm, 2, 0, c)
                         | rect(arm, 2, c + 2, c))
                break
    elif cls == 'stairs':
        for steps in (2, 3, 4):
            for sw in (3, 4):
                if steps * sw * 2 == target_cells:
                    cells = set()
                    for k in range(steps):
                        cells |= rect(sw, 2, k, k * 2)
                    break
            if cells:
                break
    elif cls == 'Z':
        for _ in range(20):
            w = rng.randint(3, 6)
            h = rng.randint(2, 4)
            if 2 * w * h != target_cells:
                continue
            off = rng.randint(1, min(3, w - 1))
            cells = rect(w, h) | rect(w, h, off, h)
            break
    elif cls == 'H':
        for _ in range(20):
            side_h = rng.randint(4, 8)
            bar_w = rng.randint(1, 3)
            if side_h % 2 == 0 and bar_w % 2 == 0:
                continue
            rest = target_cells - 4 * side_h
            if rest != bar_w * 2:
                continue
            mid = (side_h - 2) // 2
            cells = (rect(2, side_h) | rect(2, side_h, 2 + bar_w, 0)
                     | rect(bar_w, 2, 2, mid))
            break
    if cells is None or len(cells) != target_cells:
        return None
    # 随机转置增加竖 / 横形态变化(D4 去重不受影响,只是初始朝向)
    if rng.random() < 0.5:
        cells = {(y, x) for x, y in cells}
    if not _dims_ok(cells):
        return None
    xs = [c[0] for c in cells]
    ys = [c[1] for c in cells]
    w, h = max(xs) - min(xs) + 1, max(ys) - min(ys) + 1
    return f"{cls}-{min(w, h)}x{max(w, h)}", cells


# ── 骨牌平铺与依赖构造 ─────────────────────────────────────────────────────────

def random_tiling(cells, rng):
    def bt(uncov):
        if not uncov:
            return []
        c = min(uncov, key=lambda c: (
            sum(1 for d in DIRS if add(c, d) in uncov), rng.random()))
        nbrs = [add(c, d) for d in DIRS if add(c, d) in uncov]
        rng.shuffle(nbrs)
        for nb in nbrs:
            rest = bt(uncov - {c, nb})
            if rest is not None:
                return rest + [(c, nb)]
        return None
    return bt(frozenset(cells))


def topo_depth(n, edges):
    indeg = [0] * n
    for u in edges:
        for v in edges[u]:
            indeg[v] += 1
    q = deque(i for i in range(n) if indeg[i] == 0)
    depth = [1] * n
    seen = 0
    while q:
        u = q.popleft()
        seen += 1
        for v in edges.get(u, ()):
            depth[v] = max(depth[v], depth[u] + 1)
            indeg[v] -= 1
            if indeg[v] == 0:
                q.append(v)
    if seen < n:
        return None
    return max(depth)


def construct(pen_set, tiling, rng, dir_tries=40):
    """给每只骨牌选进入方向,建停靠/借道依赖图,无环则返回
    (queues, chain, max_queue)。对齐模式(同列/行共用方向 → 同开口排队)
    是队列玩法的主要来源,占 3/4 尝试。"""
    cover = {}
    for i, (a, b) in enumerate(tiling):
        cover[a] = i
        cover[b] = i
    n = len(tiling)

    for attempt in range(dir_tries):
        aligned = rng.random() < 0.75
        col_dir, row_dir = {}, {}
        specs = []
        for (a, b) in tiling:
            if a[0] == b[0]:
                if aligned:
                    d = col_dir.setdefault(a[0], rng.choice([(0, 1), (0, -1)]))
                else:
                    d = rng.choice([(0, 1), (0, -1)])
            else:
                if aligned:
                    d = row_dir.setdefault(a[1], rng.choice([(1, 0), (-1, 0)]))
                else:
                    d = rng.choice([(1, 0), (-1, 0)])
            head = max((a, b), key=lambda c: c[0] * d[0] + c[1] * d[1])
            tail = a if head == b else b
            lane = []
            cur = add(tail, neg(d))
            while cur in pen_set:
                lane.append(cur)
                cur = add(cur, neg(d))
                if len(lane) > 20:
                    break
            entry = lane[-1] if lane else tail
            specs.append({'d': d, 'tail': tail, 'head': head,
                          'lane': lane, 'entry': entry})

        edges = defaultdict(set)
        ok = True
        for i, s in enumerate(specs):
            beyond = add(s['head'], s['d'])
            if beyond in pen_set:
                blocker = cover[beyond]
                if blocker == i:
                    ok = False
                    break
                edges[blocker].add(i)      # 挡路者必须先就位
            for lc in s['lane']:
                j = cover[lc]
                if j != i:
                    edges[i].add(j)        # 借道:车道上的骨牌必须后进
        if not ok:
            continue
        chain = topo_depth(n, edges)
        if chain is None:
            continue

        # 汇成开口队列:入口格 + 朝外方向 + 数量
        lane_map = defaultdict(int)
        for s in specs:
            lane_map[(s['entry'], neg(s['d']))] += 1
        queues = [(c, d, cnt) for (c, d), cnt in sorted(lane_map.items())]
        return queues, chain, max(lane_map.values())
    return None


def ray_cells(c, d, count):
    """一个开口在圈外需要的净空格:可见槽位(每头猪 2 格)+ 徽章格。"""
    need = 2 * min(VISIBLE_PIGS, count) + (1 if count > VISIBLE_PIGS else 0)
    return [add(c, (d[0] * k, d[1] * k)) for k in range(1, need + 1)]


def finalize(pen_set, cls, queues, chain, max_queue, n_pigs):
    # 圈外净空:可见槽位互不重叠、不压猪圈
    used = set()
    for c, d, cnt in queues:
        for cell in ray_cells(c, d, cnt):
            if cell in pen_set or cell in used:
                return None
            used.add(cell)

    walls = build_walls(pen_set, [(c, d) for c, d, _ in queues])
    min_steps = solve(pen_set, walls, queues)
    if min_steps is None:
        return None

    xs = [c[0] for c in pen_set]
    ys = [c[1] for c in pen_set]
    return {
        'pen_set': pen_set, 'queues': queues, 'walls': walls,
        'min_steps': min_steps, 'n_pigs': n_pigs, 'cls': cls,
        'chain': chain, 'max_queue': max_queue,
        'pen_w': max(xs) - min(xs) + 1, 'pen_h': max(ys) - min(ys) + 1,
    }


# ── 候选生成 ──────────────────────────────────────────────────────────────────

def generate_pool(rng):
    pool = defaultdict(list)
    canon_seen = set()
    attempts = 0
    max_attempts = 400000
    while attempts < max_attempts:
        attempts += 1
        need = [n for n in POOL_TARGET if len(pool[n]) < POOL_TARGET[n]]
        if not need:
            break
        n = rng.choice(need)
        shaped = gen_shape(rng, n * 2)
        if shaped is None:
            continue
        cls, cells = shaped
        tiling = random_tiling(cells, rng)
        if tiling is None:
            continue
        built = construct(set(cells), tiling, rng)
        if built is None:
            continue
        queues, chain, max_queue = built
        cand = finalize(set(cells), cls, queues, chain, max_queue, n)
        if cand is None:
            continue
        # 候选池阶段就按 D4 规范签名查重,避免同构候选占位
        sig = canon_sig(cand['pen_set'], cand['queues'])
        if sig in canon_seen:
            continue
        # 精确难度分析(只算该世界会用到的余量);状态过大直接弃用
        cand['an'] = {}
        bad = False
        for sl in WORLD_SLACKS[n]:
            try:
                a = analyze(cand['pen_set'], cand['walls'], cand['queues'],
                            cand['min_steps'] + sl)
            except TooLarge:
                bad = True
                break
            if a is None:
                bad = True
                break
            cand['an'][sl] = a
        if bad:
            continue
        canon_seen.add(sig)
        cand['canon'] = sig
        pool[n].append(cand)
        done = sum(len(pool[k]) for k in pool)
        if done % 100 == 0:
            print(f"  …候选 {done}(尝试 {attempts})")
    return pool, attempts


# ── 选关:世界节奏 + 玩法特征唯一 + 排队配额 ───────────────────────────────────

def pick_levels(pool, rng):
    result = []          # [{cand, slack, n}]
    recent_sig = deque(maxlen=2)
    global_slot = 0
    used_play = set()    # 玩法特征全局唯一

    for n in sorted(set(PIG_CURVE)):
        m = PIG_CURVE.count(n)
        learn_cnt = round(m * LEARN_FRAC[n])
        slacks = WORLD_SLACKS[n]
        used_cand = set()
        world_sigs = set()

        def sig_ok(cand):
            return (cand['cls'] not in recent_sig
                    and cand['cls'] not in world_sigs
                    and play_sig(cand) not in used_play)

        def commit(cand, idx, sl):
            nonlocal global_slot
            used_cand.add(idx)
            world_sigs.add(cand['cls'])
            recent_sig.append(cand['cls'])
            used_play.add(play_sig(cand))
            result.append({'cand': cand, 'slack': sl, 'n': n})
            global_slot += 1

        # ── 学习关:p_win=1(可证明零风险),难度低者优先,兼顾教学形状 ──
        max_sl = max(slacks)
        learners = [(idx, c) for idx, c in enumerate(pool[n])
                    if c['an'][max_sl]['p_win'] >= 1.0]
        learn_cnt = min(learn_cnt, len({c['cls'] for _, c in learners}))

        def learn_key(item):
            idx, c = item
            pref = TUTORIAL_PREF.get(global_slot, None)
            cls_name = c['cls'].split('-')[0]
            pref_pen = 0 if (pref is None or cls_name in pref) else 1
            return (pref_pen, difficulty(c, max_sl), rng.random())

        for _ in range(learn_cnt):
            learners.sort(key=learn_key)
            pick = next(((idx, c) for idx, c in learners
                         if idx not in used_cand and sig_ok(c)), None)
            if pick is None:
                pick = next(((idx, c) for idx, c in learners
                             if idx not in used_cand
                             and play_sig(c) not in used_play), None)
            if pick is None:
                break
            commit(pick[1], pick[0], max_sl)

        # ── 陷阱关:按精确难度分升序铺开,覆盖易→难的分位点 ──
        variants = []
        for idx, c in enumerate(pool[n]):
            if idx in used_cand:
                continue
            for sl in slacks:
                a = c['an'][sl]
                if a['p_win'] < 1.0:
                    variants.append((difficulty(c, sl), idx, c, sl))
        variants.sort(key=lambda v: v[0])

        need_trap = m - len([e for e in result if e['n'] == n])
        picked_traps = []
        trap_sigs = set()
        if variants and need_trap > 0:
            K = len(variants)
            for j in range(need_trap):
                pos = round(j * (K - 1) / max(1, need_trap - 1))
                pick = None
                for off in range(K):
                    for p in (pos + off, pos - off):
                        if 0 <= p < K:
                            d_, idx, c, sl = variants[p]
                            if idx not in used_cand and sig_ok(c) \
                                    and c['cls'] not in trap_sigs:
                                pick = (d_, idx, c, sl)
                                break
                    if pick:
                        break
                if pick is None:
                    # 兜底:放开形状类约束,但玩法特征必须仍然唯一
                    for p in range(K):
                        d_, idx, c, sl = variants[p]
                        if idx not in used_cand \
                                and play_sig(c) not in used_play \
                                and c['cls'] not in recent_sig:
                            pick = (d_, idx, c, sl)
                            break
                if pick is None:
                    for p in range(K):
                        d_, idx, c, sl = variants[p]
                        if idx not in used_cand \
                                and play_sig(c) not in used_play:
                            pick = (d_, idx, c, sl)
                            break
                if pick is None:
                    raise RuntimeError(f"世界 {n}:陷阱关候选不足")
                used_cand.add(pick[1])
                trap_sigs.add(pick[2]['cls'])
                used_play.add(play_sig(pick[2]))
                picked_traps.append(pick)

        # 排队配额:5 猪以上世界至少 3 关有深排队(队列 ≥3,若候选存在)
        if n >= 5:
            have_q = sum(1 for d_, i_, c, s_ in picked_traps
                         if c['max_queue'] >= 3)
            if have_q < 3:
                q_vars = [v for v in variants
                          if v[2]['max_queue'] >= 3 and v[1] not in used_cand]
                repl = [t for t in picked_traps if t[2]['max_queue'] < 3]
                done_q = 0
                for qv in q_vars:
                    if done_q >= 3 - have_q or not repl:
                        break
                    # 逐个重查:前一个替换可能已占用同样的玩法特征
                    if play_sig(qv[2]) in used_play or qv[1] in used_cand:
                        continue
                    done_q += 1
                    victim = min(repl, key=lambda t: abs(t[0] - qv[0]))
                    repl.remove(victim)
                    picked_traps.remove(victim)
                    used_cand.discard(victim[1])
                    used_play.discard(play_sig(victim[2]))
                    used_cand.add(qv[1])
                    used_play.add(play_sig(qv[2]))
                    picked_traps.append(qv)

        # 贪心排序:难度升序,且每次优先取与前一关形状不同的候选
        picked_traps.sort(key=lambda t: t[0])
        prev_cls = result[-1]['cand']['cls'] if result else None
        remaining = picked_traps[:]
        while remaining:
            nxt = next((t for t in remaining if t[2]['cls'] != prev_cls),
                       remaining[0])
            remaining.remove(nxt)
            prev_cls = nxt[2]['cls']
            world_sigs.add(nxt[2]['cls'])
            recent_sig.append(nxt[2]['cls'])
            result.append({'cand': nxt[2], 'slack': nxt[3], 'n': n})
            global_slot += 1

    assert len(result) == 100, f"只选出 {len(result)} 关"
    return result


# ── 输出 ──────────────────────────────────────────────────────────────────────

def normalize(cand):
    """平移到原点(含圈外净空格),保证 JSON 坐标非负。"""
    cells = list(cand['pen_set'])
    for c, d, cnt in cand['queues']:
        cells += ray_cells(c, d, cnt)
    mx = min(c[0] for c in cells)
    my = min(c[1] for c in cells)

    def sh(c):
        return (c[0] - mx, c[1] - my)
    pen = sorted(sh(c) for c in cand['pen_set'])
    queues = [(sh(c), d, cnt) for c, d, cnt in cand['queues']]
    return pen, queues


def main():
    rng = random.Random(SEED)
    print("生成候选池(队列模型,含精确难度分析)……")
    pool, attempts = generate_pool(rng)
    for n in sorted(pool):
        nq = sum(1 for c in pool[n] if c['max_queue'] >= 3)
        print(f"  {n} 猪:{len(pool[n])} 个候选(深排队 {nq})")
    print(f"  共尝试 {attempts} 次")

    print("按世界节奏选取 100 关……")
    picked = pick_levels(pool, rng)

    # 全局唯一性终检
    canons = [e['cand']['canon'] for e in picked]
    plays = [play_sig(e['cand']) for e in picked]
    assert len(set(canons)) == 100, "存在 D4 同构关卡!"
    assert len(set(plays)) == 100, "存在玩法特征重复关卡!"

    levels_json = []
    report = ["#    pigs shape        min bud sl ch qu op  p_win  crit dcp"
              "    paths  diff  pen",
              "-" * 82]
    for i, entry in enumerate(picked):
        cand, sl = entry['cand'], entry['slack']
        pen, queues = normalize(cand)
        budget = cand['min_steps'] + sl
        a = cand['an'][sl]
        levels_json.append({
            'steps': budget,
            'min': cand['min_steps'],
            'pen': [list(c) for c in pen],
            'queues': [[list(c), list(d), cnt] for c, d, cnt in queues],
        })
        report.append(
            f"L{i+1:03d} {cand['n_pigs']:4d} {cand['cls']:<12s} "
            f"{cand['min_steps']:3d} {budget:3d} {sl:2d} {cand['chain']:2d} "
            f"{cand['max_queue']:2d} {len(cand['queues']):2d} "
            f"{a['p_win']*100:6.2f} {a['crit']:4d} {a['decep']:3d} "
            f"{min(a['n_paths'], 99999999):8d} "
            f"{difficulty(cand, sl):5.2f}  {cand['pen_w']}x{cand['pen_h']}")

    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    with open(os.path.join(root, 'levels.json'), 'w') as f:
        json.dump(levels_json, f, indent=1)
    with open(os.path.join(root, 'tools', 'levels_report.txt'), 'w') as f:
        f.write("\n".join(report) + "\n")
    print("\n".join(report[:14]))
    print("……(共 100 关)已写入 levels.json 与 tools/levels_report.txt")


if __name__ == '__main__':
    main()
