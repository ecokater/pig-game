# Pigpen Puzzle 项目交接说明

更新时间：2026-07-17

## 1. 项目现状

这是一个 Godot 4 竖屏益智游戏，共 1000 关。基础规则：

- 猪有三种体型：1 格小猪 / 2 格标准猪 / 3 格长猪，身体沿头的路径蛇形跟随
  （长猪过箭头会弯身）；头不可进自己身体中段（正在腾出的尾格可以）；
- 点击一只可操作的猪后，它沿当前方向持续滑动，直到被边界、栅栏或其他猪阻挡；
  滑行 90 步封顶视为非法移动（模型与运行时一致,杜绝箭头走马灯）；
- 每个入口外是 FIFO 猪队（体型可混编），只有队首可点击，后续猪自动补位；
- 所有猪完全进入猪圈即胜利（总身体格数恰好等于圈格数）；
- 有步数预算、三星评价、撤销、提示、加步、体力、金币、连胜和皮肤系统。

当前棋盘机制有两个：**Redirect 转向箭头**与 **Mud 泥坑**。Gate 栅栏门机制已经
从游戏运行时、渲染和最终关卡数据中移除。

运行时还有两个"手感/公平性"系统（不改变规则,只改变信息呈现）：

- **滑行轨迹预览**：悬停在可点的猪上时,`PreviewOverlay` 绘制这一步头部经过的
  格子、转弯点与最终落点投影;
- **死局感知**：每次局面变化后用限额(DOOM_BUDGET=30000 节点)DFS 复查,
  确认无解则步数标签变红、熊放大提醒并弹一次 toast;超限则视为未知、不提示。
  该检查只提示不惩罚,撤销/加步/续关后自动复查解除。

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

## 2b. Mud 泥坑规则

- `levels.json` 中 `muds` 是格子列表,必须在圈内且不与箭头同格;
- 猪头滑入泥坑格后**当场停下**(同一次滑行终止),再点该猪一次则从泥坑继续滑;
- 泥坑是唯一能让猪停在"半路"的手段,可用来故意占道,代价是额外一步;
- `tools/add_mud.py`(种子 20260721)向 L151–L900 难度带的 300 关编入 1–2 个
  泥坑,逐关复算保证泥坑改变最优解(装饰性泥坑被拒),保持步数余量不变,
  在线重查 D4 签名与相似度,难度分不越过 L901 的分数线;
- 铺设后全量重排:泥坑首现 L121、最深 L896;293 关箭头+泥坑复合、113 关双泥坑;
  三箭头决赛段(L901–L1000)不含泥坑,`finale_untouched=true`(见
  `tools/mud_audit.json`)。

## 3. 关键运行时代码

- `scripts/main.gd`
  - 读取 `levels.json`；
  - 维护猪、队列、占用格、墙、箭头和泥坑；
  - `_tap_pig()` 执行真实连续滑动、箭头转向与泥坑急停；
  - `_solve_from_current()` / `_dfs()` 是提示与死局感知共用的实时求解器,
    带节点预算(提示 HINT_BUDGET=400000,死局检查 DOOM_BUDGET=30000),
    超限置 `_dfs_overflow`,调用方把 null+overflow 视为"未知"而非"无解";
  - `_update_preview()` + 内部类 `PreviewOverlay` 绘制悬停轨迹预览;
  - `_update_doom()` 在每步/撤销/加步/续关后复查死局并联动 UI;
  - 提示状态包含猪尾格、头格、方向及各队剩余数量；
  - `_state_key()` 包含方向，避免多箭头下把不同朝向错误合并。
- `scripts/pig.gd`
  - 分节身体渲染(pig_head.svg + pig_body.svg,支持 1/2/3 格与弯身);
  - `slide_snapshots()` 按逐步身体快照做折线跟随动画;
  - 节点自身停在原点,身段子精灵摆世界坐标;wiggle 偏移整体,celebrate
    通过 boost 系数与呼吸动画兼容。
- `scripts/pen_renderer.gd`
  - 绘制猪圈、栅栏、入口、所有 Redirect 箭头和 Mud 泥坑。
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
  "redirects": [[[2, 3], [1, 0]], [[4, 3], [0, 1]]],
  "muds": [[1, 2]],
  "arch": "cross",
  "sol": [[0, 0], [1, 3, 2]]
}
```

实际 `queues` 单项格式为：

```text
[入口圈内格 [x,y], 朝外方向 [dx,dy], 队列猪数或体长序列]
```

第三项为 int 时表示"全部 2 格猪"(旧格式,仍兼容);为数组时是体长序列,
如 `[3,2,1]`,队首在前。`muds` 是泥坑格列表。`steps` 是步数预算,
`min` 是精确 BFS 最短步数。`arch` 是玩法原型标签(八种之一,验证器复核
名副其实)。`sol` 是官方最短解线(`[0,qi]`=释放第 qi 队队首;
`[1,x,y]`=点击头格在 (x,y) 的已入场猪),游戏内提示优先回放它。

## 5. 1000 关生成流水线（原型体系,当前主线）

**主入口(一步到位,从零组装 1000 关)**:

```bash
python3 tools/build_set.py --seconds 150 --cap 190
```

组成:

1. `tools/archetypes.py`
   - 八种玩法原型的生成配方(`generate`)与结构判别谓词(`classify`)。
     原型:solo/line/cross/pinwheel/mirror/parking/jumbo/swarm(见 README 表)。
   - 全部构建在 `add_mixed_pigs.construct_mixed`(精确填满证明)之上,
     只偏置形状/体型/方向/机制,再用 `classify` 谓词筛出符合的候选。
2. `tools/build_set.py`
   - 并行为八种原型各生成一大批候选(每个都经精确分析、非装饰机制复核);
   - D4 去重 + 结构/解法相似度贪心去重;
   - 每原型均衡配额(各 125 关),按难度分**严格非递减**排序,
     等难度处交换打散相邻同原型;
   - 每关写 `arch` 标签,调用 `export_solutions` 导出官方解线 `sol`,
     写 `tools/archetype_audit.json`。
   - 种子 `20260725`。

**旧的箭头/泥坑逐步流水线**(generate_levels → mechanize → rebuild_similar →
expand_to_1000 → upgrade_multi_redirect → finalize_arrow_1000 → add_mud →
add_mixed_pigs)已被 `build_set.py` 取代,脚本保留供参考;其中的规则内核
(`generate_levels.py` 的 `construct_mixed` 借道 `add_mixed_pigs`、`solve`、
`analyze`、`canon_sig` 等)仍是 `build_set` 的底座,不要删。

固定种子历史:`20260716/18/19/21/23`;原型体系为 `20260725`。

## 6. 难度评测

实现：`tools/evaluate_levels.py`。

精确指标：

- `min`：BFS 最短通关步数；
- `p_win`：预算内均匀随机选择合法操作的精确胜率；
- `crit`：最优路线上存在致命错误选项的关键决策点数；
- `decep`：走错后还可继续多少步才暴露死局；
- `paths`：预算内通关序列数；
- `search_states`：找到最短解前访问的状态数；
- 猪数、最深队列、Redirect 数量和 Mud 数量(难度项 +0.40×Mud数)。

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
报告保存于 `tools/hint_report.txt`。当前审计:`path_states=10632`。

## 9. 当前完整验证结果

```bash
python3 tools/verify_levels.py
python3 tools/verify_hints.py
python3 -m unittest tools/test_mechanics.py
```

最近一次结果（泥坑编入后,2026-07-17）：

```text
ALL 1000 LEVELS OK (含 D4 旋转/镜像全查重与泥坑非装饰检查)
难度有序 5.461 -> 44.565
超阈值相似对 0
ALL 1000 LEVEL HINTS OK; path_states=10632; multi_redirect_levels=450
unittest 6/6 OK(含泥坑急停、二次点击续走、箭头+泥坑链)
```

另已通过：

- `python3 -m py_compile tools/*.py`；
- 所有 GDScript 的 `gdparse` 语法解析；
- 多箭头连续转向单元测试。

## 10. 重要文件

- `levels.json`：最终 1000 关，约 1.2 MB；
- `tools/levels_evaluation_after.md`：最终逐关难度/相似度报告；
- `tools/levels_report.txt`：紧凑逐关指标（含 md 泥坑列）；
- `tools/expansion_audit.json`：箭头扩展阶段的规模与难度审计；
- `tools/mud_audit.json`：泥坑编入阶段的覆盖与决赛段保护审计；
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
