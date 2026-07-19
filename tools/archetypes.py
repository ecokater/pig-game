#!/usr/bin/env python3
"""八种玩法原型:每种有专属生成偏置 + 客观可判别的结构谓词。

问题诊断:同一个生成器撒 1000 关,统计上互不相同(D4+相似度都过),
但**体感上是同一种谜题**——全是"猜正确的放行顺序"。相似度指标挡得住
换皮,挡不住体验重复。

解法:把关卡按"玩法类型"分成八种原型,每种玩起来是不同的谜题:

  solo     独行侠  少猪 + 箭头走位,一笔画迷宫
  line     流水线  单开口深队,纯排序,泥坑当缓冲位
  cross    十字路口 两队垂直交汇,节拍交错
  pinwheel 风车    四向多开口,四面同时推进
  mirror   镜像    对称猪圈,看着就"被设计过"
  parking  泊车场  泥坑主导,先停半路当挡板再二段推
  jumbo    大小配  只有 1 格与 3 格猪,俄罗斯方块式填装
  swarm    挤爆了  小圈超深队零余量,极限装填

每种原型都构建在已验证的 construct_mixed(精确填满证明)之上,只是
偏置形状/体型/方向/机制,再用**客观谓词**筛出符合该类型的候选。
谓词写进验证器,逐关复核 arch 字段名副其实。
"""
import os
import random
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from add_mixed_pigs import construct_mixed, mixed_tiling, pick_quota
from generate_levels import (DIRS, _xform, add, build_walls, gen_shape,
                             norm_lens, rect, solve)
from rebuild_similar_levels import clear_queues

ARCH_NAMES = ['solo', 'line', 'cross', 'pinwheel', 'mirror', 'parking',
              'jumbo', 'swarm']


# ── 结构谓词(客观、快速、验证器复用)────────────────────────────────────────

def _dirs_perp(a, b):
    return a[0] * b[0] + a[1] * b[1] == 0


def has_mirror(pen):
    """猪圈是否有非平凡的镜像对称轴(水平/垂直/两条对角)。"""
    base = _norm(pen)
    for k in (4, 5, 6, 7):        # 四种镜像变换
        if _norm(_xform(c, k) for c in pen) == base:
            return True
    return False


def _norm(cells):
    cells = list(cells)
    mx = min(c[0] for c in cells)
    my = min(c[1] for c in cells)
    return frozenset((c[0] - mx, c[1] - my) for c in cells)


def classify(level):
    """返回该关卡满足的所有原型谓词集合(用于验证器复核 arch 名副其实)。
    level 是 rebuild_similar_levels.parse 后的 dict。"""
    pen = level['pen']
    queues = level['queues']
    redirects = level['redirects']
    muds = level['muds']
    lens_all = [norm_lens(q[2]) for q in queues]
    pigs = sum(len(l) for l in lens_all)
    max_depth = max(len(l) for l in lens_all)
    body_sizes = {x for l in lens_all for x in l}
    slack = level['steps'] - level['min']
    ok = set()
    if pigs <= 4 and len(redirects) >= 1:
        ok.add('solo')
    if len(queues) == 1 and max_depth >= 4:
        ok.add('line')
    if 2 <= len(queues) <= 3 and any(
            _dirs_perp(queues[i][1], queues[j][1])
            for i in range(len(queues)) for j in range(i + 1, len(queues))):
        ok.add('cross')
    if len(queues) >= 4:
        ok.add('pinwheel')
    if has_mirror(pen):
        ok.add('mirror')
    if len(muds) >= 2:
        ok.add('parking')
    if body_sizes and body_sizes <= {1, 3} and 1 in body_sizes and 3 in body_sizes:
        ok.add('jumbo')
    if pigs >= 9 and slack == 0 and max_depth >= 4:
        ok.add('swarm')
    return ok


# ── 每原型的生成配置 ──────────────────────────────────────────────────────────
# cells:格数范围  arrow_p:弯道箭头概率  mud_p:泥坑概率  slacks:步数余量
# quota:体型策略 mixed/jumbo/std  pen:形状来源  align:construct 对齐偏好

ARCH_CFG = {
    'solo':     dict(cells=(4, 9),   arrow_p=1.0, mud_p=0.35, slacks=(1, 2),
                     quota='mixed', pen='blob'),
    'line':     dict(cells=(6, 13),  arrow_p=0.0, mud_p=0.6, slacks=(0, 1, 2),
                     quota='mixed', pen='column'),
    'cross':    dict(cells=(8, 18),  arrow_p=0.4, mud_p=0.4, slacks=(0, 1, 2),
                     quota='mixed', pen='blob'),
    'pinwheel': dict(cells=(14, 22), arrow_p=0.6, mud_p=0.4, slacks=(0, 1),
                     quota='mixed', pen='wide'),
    'mirror':   dict(cells=(8, 22),  arrow_p=0.3, mud_p=0.3, slacks=(0, 1, 2),
                     quota='mixed', pen='sym'),
    'parking':  dict(cells=(10, 22), arrow_p=0.3, mud_p=1.0, slacks=(0, 1),
                     quota='mixed', pen='blob'),
    'jumbo':    dict(cells=(9, 22),  arrow_p=0.5, mud_p=0.4, slacks=(0, 1),
                     quota='jumbo', pen='blob'),
    'swarm':    dict(cells=(20, 24), arrow_p=0.0, mud_p=0.5, slacks=(0,),
                     quota='mixed', pen='tall'),
}


def _jumbo_quota(rng, total):
    """只用 1 格与 3 格猪,恰好填满:total = 3*n3 + n1,两者都 ≥1。"""
    lo = 1
    hi = (total - 1) // 3
    if hi < 1:
        return None
    n3 = rng.randint(lo, hi)
    n1 = total - 3 * n3
    if n1 < 1:
        return None
    return (n3, n1, 0)


def _pen_for(kind, rng, total):
    """按原型返回一个恰好 total 格的猪圈,或 None。所有猪圈须在尺寸软上限内。"""
    from generate_levels import _dims_ok
    if kind == 'column':
        # 1 格宽竖直走廊:纯单车道排序谜题
        pen = {(0, y) for y in range(total)}
        return pen if _dims_ok(pen) else None
    if kind == 'tall':
        # 窄高猪圈(2 宽),两列各一条深队列
        if total % 2:
            return None
        pen = rect(2, total // 2)
        return pen if _dims_ok(pen) else None
    shaped = gen_shape(rng, total)
    if shaped is None:
        return None
    _, pen = shaped
    if kind == 'wide':
        xs = [c[0] for c in pen]
        ys = [c[1] for c in pen]
        if max(xs) - min(xs) + 1 < 4 or max(ys) - min(ys) + 1 < 3:
            return None      # 风车要够宽,多开口才铺得开
    if kind == 'sym' and not has_mirror(pen):
        return None
    return set(pen)


def _raw_from(pen, queues, redirects, muds, minimum, slack):
    return {
        'steps': minimum + slack, 'min': minimum,
        'pen': [list(c) for c in sorted(pen)],
        'queues': [[list(c), list(d), list(lens)] for c, d, lens in queues],
        'redirects': [[list(c), list(d)]
                      for c, d in sorted(redirects.items())],
        'muds': [list(c) for c in sorted(muds)],
    }


def generate(name, rng):
    """尝试生成一个符合 name 原型的候选 raw(未做精确分析/相似度)。
    失败返回 None;调用方重试并做 analyze + 相似度 + 谓词复核。"""
    cfg = ARCH_CFG[name]
    total = rng.randint(*cfg['cells'])
    pen = _pen_for(cfg['pen'], rng, total)
    if pen is None:
        return None

    if cfg['quota'] == 'jumbo':
        quota = _jumbo_quota(rng, total)
    else:
        quota = pick_quota(rng, total, max_pieces=max(2, total))
    if quota is None:
        return None
    tiling = mixed_tiling(pen, rng, *quota)
    if tiling is None:
        return None

    want_arrows = 0
    if rng.random() < cfg['arrow_p']:
        want_arrows = rng.choice((1, 1, 2, 3))
    built = construct_mixed(pen, tiling, rng, want_arrows)
    if built is None:
        return None
    queues, _, redirects = built
    if not clear_queues(pen, queues):
        return None

    walls = build_walls(pen, [(c, d) for c, d, _ in queues])
    n_pieces = sum(len(lens) for _, _, lens in queues)
    base_min = solve(pen, walls, queues, max_depth=n_pieces + 2,
                     redirects=redirects)
    if base_min is None:
        return None
    # 非装饰:拿掉箭头后最优解必须改变
    if redirects and solve(pen, walls, queues, max_depth=base_min + 2,
                           redirects={}) == base_min:
        return None

    # parking 必须至少 2 个泥坑;其余按概率 0-1 个。泥坑必须改变最优解。
    want_mud = 2 if name == 'parking' else (1 if rng.random() < cfg['mud_p'] else 0)
    muds = set()
    minimum = base_min
    pool = sorted(set(pen) - set(redirects))
    for _ in range(want_mud):
        rng.shuffle(pool)
        added = False
        for cell in pool:
            if cell in muds:
                continue
            trial = muds | {cell}
            new_min = solve(pen, walls, queues, max_depth=minimum + 8,
                            redirects=redirects, muds=trial)
            if new_min is None or new_min == minimum:
                continue
            muds = trial
            minimum = new_min
            added = True
            break
        if not added:
            break
    if name == 'parking' and len(muds) < 2:
        return None

    # 加泥坑后再复核非装饰(与验证器一致):拿掉箭头/泥坑最优解都必须改变。
    # 泥坑会改变最优解,可能让原本必需的箭头变得多余。
    if redirects and solve(pen, walls, queues, max_depth=minimum + 2,
                           redirects={}, muds=muds) == minimum:
        return None
    if muds and solve(pen, walls, queues, max_depth=minimum + 2,
                      redirects=redirects, muds=set()) == minimum:
        return None

    slack = rng.choice(cfg['slacks'])
    raw = _raw_from(pen, queues, redirects, muds, minimum, slack)

    # 谓词复核:构造偏置不保证一定命中,靠这里筛
    from rebuild_similar_levels import parse
    if name not in classify(parse(raw)):
        return None
    return raw


# ── 吞吐自测:每原型限时生成,报速率与难度分布 ────────────────────────────────

def _throughput(seconds=8.0):
    import time
    from evaluate_levels import difficulty, shortest_method
    from generate_levels import TooLarge, analyze
    from rebuild_similar_levels import parse
    rng = random.Random(20260724)
    for name in ARCH_NAMES:
        t0 = time.time()
        got = []
        tries = 0
        while time.time() - t0 < seconds and len(got) < 30:
            tries += 1
            raw = generate(name, rng)
            if raw is None:
                continue
            cand = parse(raw)
            walls = build_walls(cand['pen'],
                                [(c, d) for c, d, _ in cand['queues']])
            try:
                m = analyze(cand['pen'], walls, cand['queues'], cand['steps'],
                            cand['redirects'], [], cand['muds'])
            except TooLarge:
                continue
            if m is None:
                continue
            method, states = shortest_method(cand)
            got.append(difficulty(cand, m, states))
        got.sort()
        rate = len(got) / max(1e-9, time.time() - t0)
        span = f"{got[0]:.1f}–{got[-1]:.1f}" if got else "—"
        print(f"{name:9s} 命中 {len(got):2d}/{tries:4d}  "
              f"{rate:4.1f}/s  难度 {span}")


if __name__ == '__main__':
    _throughput()
