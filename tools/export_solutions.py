#!/usr/bin/env python3
"""把每关的一条最短解导出进 levels.json 的 "sol" 字段。

动机:决赛段状态空间在 GDScript 里实时求解要几十秒。游戏内"提示"改为
官方解线回放——玩家沿最优线走时瞬时响应;偏离后才回退到后台 DFS。

编码(与游戏 main.gd 一致):
  [0, qi]     释放第 qi 条队列的队首猪;
  [1, x, y]   点击当前头格在 (x, y) 的已入场猪,让它再滑。

解线由 verify_hints.shortest_state_path 的确定性 BFS 生成,并由
verify_hints.py 在每次全量验证时复核(合法、最短、编码一致)。
"""
import json
import multiprocessing as mp
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from collections import Counter
from evaluate_levels import load_levels
from verify_hints import shortest_state_path


def encode_move(state, nxt):
    """把状态转移编码为游戏可执行的移动描述。"""
    entered, counts = state[0], state[1]
    ne, nc = nxt[0], nxt[1]
    if nc != counts:
        qi = next(i for i in range(len(counts)) if nc[i] < counts[i])
        return [0, qi]
    removed = list((Counter(entered) - Counter(ne)).elements())
    old_head = removed[0][0][0]
    return [1, old_head[0], old_head[1]]


def solution_for(item):
    index, level = item
    path, _ = shortest_state_path(level)
    return [encode_move(a, b) for a, b in zip(path, path[1:])]


def main():
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    path = os.path.join(root, 'levels.json')
    levels = load_levels()
    with mp.get_context('fork').Pool(
            max(2, min(8, mp.cpu_count() - 1))) as pool:
        sols = pool.map(solution_for, list(enumerate(levels)), chunksize=8)
    with open(path) as f:
        raws = json.load(f)
    assert len(raws) == len(sols)
    for raw, sol in zip(raws, sols):
        assert len(sol) == raw['min'], "解线长度必须等于最优步数"
        raw['sol'] = sol
    with open(path, 'w') as f:
        json.dump(raws, f, indent=1)
    print(f"已写入 {len(raws)} 关的官方解线(均为最短解)")


if __name__ == '__main__':
    main()
