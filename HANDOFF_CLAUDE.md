# Pigpen Puzzle 项目交接说明

更新时间：2026-07-16

## 1. 项目现状

这是一个 Godot 4 竖屏益智游戏，共 1000 关。基础规则：

- 每只猪占相邻两格；
- 点击一只可操作的猪后，它沿当前方向持续滑动，直到被边界、栅栏或其他猪阻挡；
- 每个入口外是 FIFO 猪队，只有队首可点击，后续猪自动补位；
- 所有猪完全进入猪圈即胜利；
- 有步数预算、三星评价、撤销、提示、加步、体力、金币、连胜和皮肤系统。

当前唯一新增棋盘机制是 **Redirect 转向箭头**。Gate 栅栏门机制已经从游戏运行时、
渲染和最终关卡数据中移除。

## 2. Redirect 规则

- `levels.json` 中 `redirects` 是多个 `[格子, 新方向]`；
- 猪头进入箭头格后，在同一次连续滑行中立刻改变方向；
- 一次滑行可以连续经过多个箭头；
- 运行时不限制一关的箭头数量；
- 当前生成器使用 1–3 个箭头；
- 多箭头构造器会逐个删除箭头复算，确保每个箭头都会影响最优解，而非装饰。

当前 1000 关箭头分布：

| 箭头数 | 关卡数 |
|---:|---:|
| 0 | 68 |
| 1 | 482 |
| 2 | 252 |
| 3 | 198 |

- 932/1000 关包含 Redirect；
- 450 关至少双箭头；
- 198 关为三箭头；
- 第 701–1000 关全部含箭头；
- 最后 100 关全部为三箭头。

## 3. 关键运行时代码

- `scripts/main.gd`
  - 读取 `levels.json`；
  - 维护猪、队列、占用格和墙；
  - `_tap_pig()` 执行真实连续滑动和箭头转向；
  - `_solve_from_current()` / `_dfs()` 是提示功能使用的实时求解器；
  - 提示状态包含猪尾格、头格、方向及各队剩余数量；
  - `_state_key()` 包含方向，避免多箭头下把不同朝向错误合并。
- `scripts/pig.gd`
  - 两格猪显示、点击区域和分段折线动画；
  - `slide_path()` 支持一次滑行中的多次转向。
- `scripts/pen_renderer.gd`
  - 绘制猪圈、栅栏、入口和所有 Redirect 箭头。
- `scripts/meta.gd`
  - 体力、金币、星级、连胜、道具、皮肤和每日奖励。

Gate 相关运行时代码已经删除，最终 `levels.json` 也完全不含 `gates` 字段。

## 4. 关卡数据格式

```json
{
  "steps": 14,
  "min": 14,
  "pen": [[0, 0], [0, 1]],
  "queues": [[[0, 0], [-1, 0], 2]],
  "redirects": [[[2, 3], [1, 0]], [[4, 3], [0, 1]]]
}
```

实际 `queues` 单项格式为：

```text
[入口圈内格 [x,y], 朝外方向 [dx,dy], 队列猪数]
```

`steps` 是步数预算，`min` 是精确 BFS 最短步数。

## 5. 1000 关生成流水线

主入口：

```bash
python3 tools/generate_levels.py
```

流水线组成：

1. `tools/generate_levels.py`
   - 构造 100 关基础候选；
   - 随机骨牌平铺、队列构造、精确求解和 D4 去重。
2. `tools/mechanize_levels.py`
   - 向基础教学关编入 Redirect。
3. `tools/rebuild_similar_levels.py`
   - 重做所有超过结构/解法相似度阈值的关卡端点；
   - 按精确难度分排序。
4. `tools/expand_to_1000.py`
   - 从 100 关扩展至 1000 关；
   - 新增关使用解法必需的 Redirect；
   - 后段提升到 13–14 猪、零步数余量。
5. `tools/upgrade_multi_redirect.py`
   - 将高难段 450 关替换为双/三箭头关；
   - 新候选仍需在线通过相似度检查。
6. `tools/finalize_arrow_1000.py`
   - 一次性生成最终难度报告、相似度报告和扩展审计。

固定种子主要为 `20260716`、`20260718`、`20260719`。

## 6. 难度评测

实现：`tools/evaluate_levels.py`。

精确指标：

- `min`：BFS 最短通关步数；
- `p_win`：预算内均匀随机选择合法操作的精确胜率；
- `crit`：最优路线上存在致命错误选项的关键决策点数；
- `decep`：走错后还可继续多少步才暴露死局；
- `paths`：预算内通关序列数；
- `search_states`：找到最短解前访问的状态数；
- 猪数、最深队列和 Redirect 数量。

最终难度严格非递减：

```text
L0001: 5.461
L0701: 34.885
L1000: 44.565
```

末关为 14 猪、14 步零余量、三箭头高难关。

## 7. 相似度评测

结构相似度：

- 枚举 D4：四种旋转和四种镜像；
- 比较形状 Jaccard、队列构成、Redirect 构成和棋盘规模。

解法相似度：

- 将确定性的最短解编码为：释放队首/再次移动、是否转向、移动距离档、是否完全入圈；
- 使用归一化 Levenshtein 相似度。

判定为过度相似：

```text
综合相似度 >= 0.86
或
解法相似度 >= 0.92 且结构相似度 >= 0.68
```

当前 1000 关全对全比较结果：**超阈值相似对为 0**。

详细方法：`tools/LEVEL_EVALUATION.md`。

## 8. 提示功能正确性

游戏提示不是预存答案，而是从当前局面实时执行 DFS：

- 返回的队首猪或圈内猪必须是当前合法动作；
- 递归只接受能在剩余步数内到达胜利的后继状态；
- 多箭头后的最终方向进入状态键；
- 玩家走入无解状态时提示“剩余步数内已无解”，不会给随机动作。

独立验证器：

```bash
python3 tools/verify_hints.py
```

当前审计结果：

```text
ALL 1000 LEVEL HINTS OK;
path_states=10172;
multi_redirect_levels=450
```

它会重建每关最短状态路径，逐步确认提示动作合法，且提示后的剩余路径不超过预算。
报告保存于 `tools/hint_report.txt`。

## 9. 当前完整验证结果

```bash
python3 tools/verify_levels.py
python3 tools/verify_hints.py
python3 -m unittest tools/test_mechanics.py
```

最近一次结果：

```text
ALL 1000 LEVELS OK (含 D4 旋转/镜像全查重)
难度有序 5.461 -> 44.565
超阈值相似对 0
ALL 1000 LEVEL HINTS OK
```

另已通过：

- `python3 -m py_compile tools/*.py`；
- 所有 GDScript 的 `gdparse` 语法解析；
- 多箭头连续转向单元测试。

## 10. 重要文件

- `levels.json`：最终 1000 关，约 1.2 MB；
- `tools/levels_evaluation_after.md`：最终逐关难度/相似度报告；
- `tools/levels_report.txt`：紧凑逐关指标；
- `tools/expansion_audit.json`：最终规模、箭头覆盖和难度审计；
- `tools/hint_report.txt`：提示正确性审计；
- `tools/LEVEL_EVALUATION.md`：评测方法定义；
- `README.md`：玩法和运行说明。

## 11. 已知注意事项 / 后续建议

1. 完整生成和全量验证较慢：1000 关全对全相似度比较约 50 万对，高难 14 猪关还会
   产生较大的精确状态空间；这是离线成本，不影响游戏运行。
2. Python 规则内核仍保留少量旧 Gate 参数作为生成工具兼容层，但最终数据、Godot
   运行时和 UI 均没有 Gate。若要彻底清理工具 API，可单独做一次无行为变化的重构。
3. `tools/generate_levels.py` 从零完整生成会很慢；日常验证优先运行 `verify_levels.py`。
4. 当前没有 Git 仓库，无法提供提交历史或 diff；接手前建议初始化 Git 并提交当前基线。
5. 当前环境没有 Godot 可执行文件，验证使用 GDScript 解析器和规则级测试；建议接手方
   在 Godot 4.2+ 中实际运行，重点观察多箭头连续转弯动画、1000 关选关面板滚动性能、
   以及高深队列在小屏设备上的可读性。
