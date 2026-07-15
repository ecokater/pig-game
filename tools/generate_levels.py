#!/usr/bin/env python3
"""
小猪进圈 · 100 关生成器 v2(重视玩家体验的版本)

与 v1 的区别:
- 通用多联骨牌构造:猪圈形状库(矩形/L/T/U/十字/阶梯/缺角),
  随机骨牌平铺 → 每只猪选进入方向 → 车道依赖图(无环才收) → BFS 终审;
- 人类难度模型:猪数 + 依赖链深度 + 蒙特卡洛失败率 + 余量,不再单看失败率
  (2 只猪失败率 50% 对人类是秒懂题,10 只猪 40% 反而难);
- 分段曲线:猪数 2→10 单调爬升,段内按失败率升序;
- 多样性:相邻关卡不允许重复形状签名,前 8 关是各引入一个新概念的教学序列。

用法:python3 tools/generate_levels.py   (在 tools/ 或项目根均可)
输出:../levels.json 与 ../tools/levels_report.txt
"""
import json
import os
import random
from collections import deque, defaultdict

SEED = 20260714
DIRS = [(1, 0), (-1, 0), (0, 1), (0, -1)]

# 猪数曲线:第 i 关(0 起)的猪数;单调不减。
# 每个猪数段是一个"世界":段内难度走一遍 易→难 的小弧线,段间整体抬升。
# 2 猪只有 4 格形状,变化空间极小,只放 2 关避免重复感;
# 低猪数段收短(它们撑不起长曲线),中后期段加长。
PIG_CURVE = [2] * 2 + [3] * 6 + [4] * 8 + [5] * 12 + [6] * 16 \
    + [7] * 18 + [8] * 18 + [9] * 10 + [10] * 10
assert len(PIG_CURVE) == 100

# 每个猪数段(世界)的节奏:
# 学习期占比(失败率目标 0,练结构)→ 陷阱期(失败率从陷阱簇下沿爬到段顶)
# 学习期不能长于池里"零风险且形状各异"的候选量,否则会被迫重复形状
LEARN_FRAC = {2: 0.5, 3: 0.6, 4: 0.5, 5: 0.4, 6: 0.25,
              7: 0.17, 8: 0.11, 9: 0.1, 10: 0.0}
BAND_HI = {2: 0.5, 3: 0.5, 4: 0.6, 5: 0.65, 6: 0.75,
           7: 0.85, 8: 0.9, 9: 0.95, 10: 1.0}

# 每关需要的候选数量(按猪数)
POOL_TARGET = {2: 40, 3: 100, 4: 130, 5: 150, 6: 160,
               7: 160, 8: 160, 9: 120, 10: 120}

MC_SIMS = 300          # 选关阶段的模拟局数(最终 verify 脚本会用更多局复验)
MAX_COLS, MAX_ROWS = 10, 11


def add(a, b):
    return (a[0] + b[0], a[1] + b[1])


def neg(d):
    return (-d[0], -d[1])


def ekey(a, b):
    return (min(a, b), max(a, b))


def allowed_slacks(i):
    """步数余量:每关允许在小集合里挑,选关时用它微调难度贴合目标曲线。
    前松后紧,最后 10 关必须最优解。"""
    if i < 8:
        return (3,)
    if i < 16:
        return (3, 2)
    if i < 44:
        return (2, 1)
    if i < 80:
        return (1,)
    if i < 90:
        return (1, 0)
    return (0,)


def make_fail_targets(pool):
    """算出 100 关的目标失败率。
    每段:前 LEARN_FRAC 是学习期(目标 0);之后是陷阱期,
    目标从该段候选池里实测的陷阱簇下沿(非零失败率的 20 分位)爬到段顶。
    候选池的失败率天然两极(无死锁≈0%,有死锁≈50%+),
    与其硬凑不存在的中间值,不如让节奏贴合分布。"""
    targets = [0.0] * 100
    for n in set(PIG_CURVE):
        slots = [j for j in range(100) if PIG_CURVE[j] == n]
        m = len(slots)
        fails = sorted(
            cand['mc'][sl]
            for cand in pool[n]
            for j in slots for sl in allowed_slacks(j)
            if cand['mc'][sl] > 0.15)
        trap_lo = fails[len(fails) // 5] if fails else 0.5
        hi = max(BAND_HI[n], trap_lo)
        learn = round(m * LEARN_FRAC[n])
        for k, j in enumerate(slots):
            if k < learn:
                targets[j] = 0.0
            elif m - learn <= 1:
                targets[j] = hi
            else:
                targets[j] = trap_lo + (hi - trap_lo) * (k - learn) / (m - learn - 1)
    return targets


# ── 求解与模拟(规则与游戏内 GDScript 完全一致)─────────────────────────────

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


def _try_slide(pen_set, walls, dirs, state, i):
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
            return None
    if moved == 0:
        return None
    s = list(state)
    s[i] = (t, h)
    return tuple(s)


def solve(pen_set, walls, pigs_list, max_depth=50):
    dirs = [p[2] for p in pigs_list]
    init = tuple((p[0], p[1]) for p in pigs_list)

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
            ns = _try_slide(pen_set, walls, dirs, state, i)
            if ns is not None and ns not in seen:
                seen[ns] = (state, i)
                q.append((ns, depth + 1))
    return None, None


def monte_carlo(pen_set, walls, pigs_list, budget, n_sims, rng):
    dirs = [p[2] for p in pigs_list]
    n = len(pigs_list)
    init = tuple((p[0], p[1]) for p in pigs_list)

    def won(state):
        return all(t in pen_set and h in pen_set for t, h in state)

    failures = 0
    for _ in range(n_sims):
        state = init
        steps = 0
        while steps < budget:
            moves = []
            for i in range(n):
                ns = _try_slide(pen_set, walls, dirs, state, i)
                if ns is not None:
                    moves.append(ns)
            if not moves:
                break
            state = rng.choice(moves)
            steps += 1
            if won(state):
                break
        if not won(state):
            failures += 1
    return failures / n_sims


def bbox_of(pen_set, pigs_list):
    cells = list(pen_set) + [c for p in pigs_list for c in (p[0], p[1])]
    xs = [c[0] for c in cells]
    ys = [c[1] for c in cells]
    return max(xs) - min(xs) + 1, max(ys) - min(ys) + 1


# ── 形状库 ────────────────────────────────────────────────────────────────────

def rect(w, h, x0=0, y0=0):
    return {(x0 + x, y0 + y) for x in range(w) for y in range(h)}


def gen_shape(rng, target_cells):
    """随机生成一个 target_cells 格的猪圈形状,返回 (类名, 格子集合) 或 None。"""
    cls = rng.choice(['rect', 'rect', 'L', 'T', 'U', 'plus', 'stairs', 'notch'])
    cells = None
    if cls == 'rect':
        opts = [(w, target_cells // w) for w in range(2, 7)
                if target_cells % w == 0 and 2 <= target_cells // w <= 6]
        if not opts:
            return None
        w, h = rng.choice(opts)
        cells = rect(w, h)
    elif cls == 'notch':
        # 矩形咬掉一个 2 格角
        opts = [(w, (target_cells + 2) // w) for w in range(3, 7)
                if (target_cells + 2) % w == 0 and 2 <= (target_cells + 2) // w <= 6]
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
        # 咬掉整条边会退化成小矩形,必须仍占满原包围盒
        if cells:
            xs = [c[0] for c in cells]
            ys = [c[1] for c in cells]
            if max(xs) - min(xs) + 1 != w or max(ys) - min(ys) + 1 != h:
                return None
    elif cls == 'L':
        for _ in range(20):
            w, h = rng.randint(2, 5), rng.randint(2, 4)
            rest = target_cells - w * h
            if rest <= 0:
                continue
            opts = [(aw, rest // aw) for aw in range(2, w + 1)
                    if rest % aw == 0 and 1 <= rest // aw <= 3]
            if not opts:
                continue
            aw, ah = rng.choice(opts)
            cells = rect(w, h) | rect(aw, ah, 0, h)
            break
    elif cls == 'T':
        for _ in range(20):
            bw = rng.choice([4, 5, 6])
            bh = rng.randint(1, 3)
            rest = target_cells - bw * bh
            if rest <= 0 or rest % 2 != 0:
                continue
            sh = rest // 2
            if not 1 <= sh <= 3:
                continue
            off = (bw - 2) // 2
            cells = rect(bw, bh) | rect(2, sh, off, bh)
            break
    elif cls == 'U':
        for _ in range(20):
            w = rng.randint(4, 6)
            h = rng.randint(3, 4)
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
        for steps in (2, 3):
            for sw in (3, 4):
                if steps * sw * 2 == target_cells:
                    cells = set()
                    for k in range(steps):
                        cells |= rect(sw, 2, k, k * 2)
                    break
            if cells:
                break
    if cells is None or len(cells) != target_cells:
        return None
    xs = [c[0] for c in cells]
    ys = [c[1] for c in cells]
    w, h = max(xs) - min(xs) + 1, max(ys) - min(ys) + 1
    if w > 6 or h > 7:
        return None
    return f"{cls}-{w}x{h}", cells


# ── 骨牌平铺与依赖构造 ─────────────────────────────────────────────────────────

def random_tiling(cells, rng):
    """随机完美骨牌平铺(带回溯);返回 [(a,b),...] 或 None。"""
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
    """Kahn 拓扑排序;返回依赖链深度(最长路节点数),有环返回 None。"""
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
    """给平铺里的每只骨牌选进入方向,建停靠/借道依赖图,无环则返回
    (pig_specs, chain_depth);pig_specs 供 finalize 使用。"""
    cover = {}
    for i, (a, b) in enumerate(tiling):
        cover[a] = i
        cover[b] = i
    n = len(tiling)

    for _ in range(dir_tries):
        specs = []
        for (a, b) in tiling:
            if a[0] == b[0]:
                d = rng.choice([(0, 1), (0, -1)])
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
        pig_specs = [(s['entry'], neg(s['d']), s['d'], s['tail'], s['head'])
                     for s in specs]
        return pig_specs, chain
    return None


# ── 等候位与关卡定型 ──────────────────────────────────────────────────────────

def place_waiting(pig_specs, pen_set, rng):
    lane_map = {}
    for i, (oc, od, ed, ft, fh) in enumerate(pig_specs):
        lane_map.setdefault((oc, od), []).append(i)

    occupied = set()
    pig_positions = {}
    for (oc, od), group in lane_map.items():
        slot = 1
        for idx in group:
            placed = False
            for gap in range(slot, slot + 20):
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
    return [(pig_positions[i][0], pig_positions[i][1], pig_specs[i][2])
            for i in range(len(pig_specs))]


def finalize(pen_set, pig_specs, rng):
    seen_open = set()
    openings = []
    for oc, od, ed, ft, fh in pig_specs:
        if (oc, od) not in seen_open:
            seen_open.add((oc, od))
            openings.append((oc, od))

    used = set()
    for oc, od, ed, ft, fh in pig_specs:
        if ft not in pen_set or fh not in pen_set or ft in used or fh in used:
            return None
        used.add(ft)
        used.add(fh)

    wait_pigs = place_waiting(pig_specs, pen_set, rng)
    if wait_pigs is None:
        return None
    for t, h, d in wait_pigs:
        if t in pen_set or h in pen_set:
            return None

    cols, rows = bbox_of(pen_set, wait_pigs)
    if cols > MAX_COLS or rows > MAX_ROWS:
        return None

    walls = build_walls(pen_set, openings)
    for t, h, d in wait_pigs:
        if ekey(h, add(h, d)) in walls:
            return None

    min_steps, _ = solve(pen_set, walls, wait_pigs)
    if min_steps is None:
        return None
    return {
        'pen_set': pen_set, 'openings': openings, 'pigs': wait_pigs,
        'walls': walls, 'min_steps': min_steps, 'n_pigs': len(pig_specs),
        'cols': cols, 'rows': rows,
    }


# ── 候选生成 ──────────────────────────────────────────────────────────────────

def generate_pool(rng):
    pool = defaultdict(list)   # n_pigs -> [candidate]
    attempts = 0
    max_attempts = 250000
    while attempts < max_attempts:
        attempts += 1
        if all(len(pool[n]) >= POOL_TARGET[n] for n in POOL_TARGET):
            break
        need = [n for n in POOL_TARGET if len(pool[n]) < POOL_TARGET[n]]
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
        pig_specs, chain = built
        cand = finalize(set(cells), pig_specs, rng)
        if cand is None:
            continue
        cand['cls'] = cls
        cand['chain'] = chain
        # 预算 0~3 各余量下的失败率,供选关时微调难度
        cand['mc'] = {}
        for sl in range(4):
            budget = cand['min_steps'] + sl
            cand['mc'][sl] = monte_carlo(
                cand['pen_set'], cand['walls'], cand['pigs'],
                budget, MC_SIMS, rng)
        pool[n].append(cand)
    return pool, attempts


# ── 选关:难度曲线 + 多样性 + 教学序列 ────────────────────────────────────────

# 前 8 关的形状偏好:每关引入一个新概念
# 0 认识点猪进圈;1 缺角圈初见"先后顺序";2-3 三猪矩形/T 形;
# 4 L 形;5 四猪依赖链;6 十字/凹形;7 综合
TUTORIAL_PREF = {
    0: {'rect'}, 1: {'notch'}, 2: {'rect'}, 3: {'T', 'L'},
    4: {'L', 'notch'}, 5: {'rect', 'T'}, 6: {'plus', 'U', 'T'},
    7: {'U', 'plus', 'stairs', 'L', 'notch'},
}


FAIL_CAP = 0.15   # 实选失败率最多超出目标这么多,防止难度悬崖


def pick_levels(pool, rng):
    targets = make_fail_targets(pool)
    chosen = []
    used = set()
    recent_sig = deque(maxlen=2)   # 形状签名(类名+尺寸)不许和前两关重复
    recent_cls = deque(maxlen=3)   # 形状类名尽量和前三关不同
    band_sigs = set()              # 同一猪数段内每种形状签名只出现一次
    band_n = None

    for i in range(100):
        n = PIG_CURVE[i]
        if n != band_n:
            band_n = n
            band_sigs = set()
        t = targets[i]

        def search(strict):
            best, best_key = None, None
            for idx, cand in enumerate(pool[n]):
                if (n, idx) in used:
                    continue
                cls_name = cand['cls'].split('-')[0]
                if strict:
                    if cand['cls'] in recent_sig or cand['cls'] in band_sigs:
                        continue
                    if i in TUTORIAL_PREF and cls_name not in TUTORIAL_PREF[i]:
                        continue
                    if 12 <= i and cand['chain'] < 2:
                        continue
                for sl in allowed_slacks(i):
                    fail = cand['mc'][sl]
                    if strict:
                        if fail > t + FAIL_CAP:
                            continue
                        if i == 0 and fail > 0.05:
                            continue   # 第 1 关必须零风险
                    key = abs(fail - t)
                    if not strict:
                        if cand['cls'] in recent_sig:
                            key += 0.5
                        if cand['cls'] in band_sigs:
                            key += 0.25
                        if fail > t + FAIL_CAP:
                            key += 0.4
                        if 12 <= i and cand['chain'] < 2:
                            key += 0.2
                    if cls_name in recent_cls:
                        key += 0.12
                    if 30 <= i and cand['chain'] >= 3:
                        key -= 0.03           # 中后期偏好深依赖链
                    key -= min(cand['chain'], 6) * 0.01
                    if best_key is None or key < best_key:
                        best_key = key
                        best = (idx, cand, sl)
            return best

        best = search(True)
        if best is None:
            best = search(False)
        if best is None:
            raise RuntimeError(f"第 {i+1} 关无候选(猪数 {n})")
        idx, cand, sl = best
        used.add((n, idx))
        recent_sig.append(cand['cls'])
        recent_cls.append(cand['cls'].split('-')[0])
        band_sigs.add(cand['cls'])
        chosen.append({'cand': cand, 'slack': sl, 'n': n})

    # 不做事后重排:目标曲线本身即段内升序,重排会破坏"防形状重复"的相邻性
    return chosen


# ── 输出 ──────────────────────────────────────────────────────────────────────

def normalize(cand):
    """坐标平移到非负,方便阅读(游戏内会自动居中,不影响逻辑)。"""
    cells = list(cand['pen_set']) + [c for p in cand['pigs'] for c in (p[0], p[1])]
    mx = min(c[0] for c in cells)
    my = min(c[1] for c in cells)

    def sh(c):
        return (c[0] - mx, c[1] - my)
    pen = sorted(sh(c) for c in cand['pen_set'])
    openings = [(sh(c), d) for c, d in cand['openings']]
    pigs = [(sh(t), sh(h), d) for t, h, d in cand['pigs']]
    return pen, openings, pigs


def main():
    rng = random.Random(SEED)
    print("生成候选池……")
    pool, attempts = generate_pool(rng)
    for n in sorted(pool):
        print(f"  {n} 猪:{len(pool[n])} 个候选")
    print(f"  共尝试 {attempts} 次")

    print("按难度曲线与多样性选取 100 关……")
    picked = pick_levels(pool, rng)

    levels_json = []
    report = ["#    pigs shape        min budget slack chain  fail   bbox",
              "-" * 66]
    for i, entry in enumerate(picked):
        cand, sl = entry['cand'], entry['slack']
        pen, openings, pigs = normalize(cand)
        budget = cand['min_steps'] + sl
        levels_json.append({
            'steps': budget,
            'pen': [list(c) for c in pen],
            'openings': [[list(c), list(d)] for c, d in openings],
            'pigs': [[list(t), list(h), list(d)] for t, h, d in pigs],
        })
        report.append(
            f"L{i+1:03d} {cand['n_pigs']:4d} {cand['cls']:<12s} "
            f"{cand['min_steps']:3d} {budget:6d} {sl:5d} {cand['chain']:5d} "
            f"{cand['mc'][sl]*100:5.1f}%  {cand['cols']}x{cand['rows']}")

    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    with open(os.path.join(root, 'levels.json'), 'w') as f:
        json.dump(levels_json, f, indent=1)
    with open(os.path.join(root, 'tools', 'levels_report.txt'), 'w') as f:
        f.write("\n".join(report) + "\n")
    print("\n".join(report[:14]))
    print(f"……(共 100 关)已写入 levels.json")


if __name__ == '__main__':
    main()
