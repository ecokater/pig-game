extends Node2D
## 主场景:反向 Arrow Puzzle,共 1000 关(队列版)。
## 每个开口外是一条 FIFO 猪队:只有队首的猪能被点击释放进圈,
## 进圈后沿固定方向滑到底;后面的猪自动补位。
## 屏幕上每队最多显示 2 头,其余收纳成 🐷×n 徽章(不可点击)。
## 在限定步数内让所有小猪全部进圈则过关。
##
## Meta 层(状态在 Meta 单例):红心体力、金币、三星评级、连胜、
## 道具(撤销/提示/+2步)、步数耗尽续关、皮肤、每日奖励。

const VIEW := Vector2(1024.0, 1280.0)
const PLAY_AREA := Rect2(16.0, 170.0, 992.0, 1050.0)
const BASE_CELL := 150.0
const PROGRESS_CFG := "user://progress.cfg"
const VISIBLE_PIGS := 2   # 每个开口外可见的排队猪数,与生成器一致

const PigScript := preload("res://scripts/pig.gd")
const BearScript := preload("res://scripts/bear.gd")
const PenRendererScript := preload("res://scripts/pen_renderer.gd")

const BEAR_TEX := preload("res://art/bear.svg")
const CLOUD_TEX := preload("res://art/cloud.svg")
const CROSS_TEX := preload("res://art/cross.svg")

static var level_index := 0
static var progress_applied := false  # 存档只在本次运行首次进场时应用

## 测试开关:true 时选关面板解锁全部关卡(不影响存档)。发布前改回 false。
const UNLOCK_ALL := true

var levels: Array = []
var cell_size := BASE_CELL
var grid_origin := Vector2.ZERO
var max_steps := 0
var min_steps := 0         # 本关最优步数(星级评价用)
var moves_made := 0

var pen_cells: Array = []
var queues: Array = []     # [{cell, dir, count}] 开口队列定义
var openings: Array = []   # [圈内格子, 朝外方向](供绘制)

var pigs: Array = []       # 所有猪节点
var queue_all: Array = []  # 每个开口的猪节点原始顺序(队首在前,不变)
var badges: Array = []     # 每个开口的 🐷×n 徽章 Label
var occupied := {}         # Vector2i -> pig(仅圈内猪 + 可见等待猪)
var walls := {}            # 边键 -> true
var wall_list: Array = []  # [圈内格子, 朝外方向],供绘制
var redirects := {}        # Vector2i -> Vector2i，猪头进入该格后改向
var muds := {}             # Vector2i -> true，猪头进泥坑当场停下(再点可继续)
var cellset := {}
var steps_left := 0
var game_over := false
var animating := false
var bear: Node2D

var _undo_stack: Array = []

# 滑行轨迹预览(悬停在猪上时显示完整路径与落点)
var _preview_pig: Node2D = null
var _preview_cells: Array = []   # 头经过的格子
var _preview_end: Array = []     # [落点尾格, 落点头格]
var _overlay: Node2D             # 预览绘制层(盖在猪圈和猪之上)

# 死局感知:每步后用限额求解器检测,无解时示警(不惩罚,只提示)
var _doomed := false
var _dfs_nodes := 0
var _dfs_budget := 0
var _dfs_overflow := false
const DOOM_BUDGET := 30000
const HINT_BUDGET := 120000

# 求解全部在后台线程跑(决赛段状态空间大,主线程会冻结数秒到分钟级)
var _solver_thread: Thread = null
var _solver_abort := false     # 线程内的 _dfs 定期检查,置位后尽快退出
var _solver_gen := 0           # 局面代数:移动/撤销/加步都会 +1,过期结果丢弃
var _doom_dirty := false       # 求解器忙时收到的死局复查请求,空闲后补跑

# 官方解线回放:levels.json 携带每关一条已验证的最短解;
# 玩家沿最优线走时,"提示"瞬时响应,不需要实时求解
var solution: Array = []       # [[0,qi] 释放队列 | [1,x,y] 点头格在(x,y)的猪]
var _history: Array = []       # 本关已执行移动(同编码),撤销时回退

var _title: Label
var _steps_label: Label
var _hearts_label: Label
var _coins_label: Label
var _streak_label: Label
var _panel: CenterContainer
var _select_panel: ColorRect
var _shop_panel: ColorRect
var _shop_box: VBoxContainer
var _result_label: Label
var _btn: Button
var _btn2: Button
var _btn_mode := "retry"   # advance / retry / continue
var _undo_btn: Button
var _hint_btn: Button
var _steps_btn: Button
var _toast_label: Label
var _grass: PackedVector2Array = PackedVector2Array()
var _ui_font: SystemFont


# ---------- 进度持久化 ----------

static func _load_progress() -> int:
	var cfg := ConfigFile.new()
	if cfg.load(PROGRESS_CFG) == OK:
		return int(cfg.get_value("progress", "max_unlocked", 0))
	return 0


static func _save_progress(max_unlocked: int) -> void:
	var cfg := ConfigFile.new()
	cfg.set_value("progress", "max_unlocked", max_unlocked)
	cfg.save(PROGRESS_CFG)


# ---------- 关卡读取 ----------

static func _parse_v2i_array(arr: Array) -> Array:
	var result: Array = []
	for item in arr:
		result.append(Vector2i(int(item[0]), int(item[1])))
	return result


static func _load_levels_from_json() -> Array:
	var fa := FileAccess.open("res://levels.json", FileAccess.READ)
	if fa == null:
		push_error("无法打开 res://levels.json")
		return []
	var text := fa.get_as_text()
	fa.close()

	var raw = JSON.parse_string(text)
	if raw == null or not (raw is Array):
		push_error("levels.json 解析失败")
		return []

	var result: Array = []
	for lv_raw in raw:
		var lv: Dictionary = lv_raw
		var parsed_queues: Array = []
		for q in lv["queues"]:
			# 第三项:int(旧格式,全 2 格猪)或体长序列(如 [3,2,1],队首在前)
			var lens: Array = []
			if q[2] is Array:
				for x in q[2]:
					lens.append(int(x))
			else:
				for _k in int(q[2]):
					lens.append(2)
			parsed_queues.append({
				"cell": Vector2i(int(q[0][0]), int(q[0][1])),
				"dir": Vector2i(int(q[1][0]), int(q[1][1])),
				"lens": lens,
			})
		var parsed_redirects: Array = []
		for r in lv.get("redirects", []):
			parsed_redirects.append([
				Vector2i(int(r[0][0]), int(r[0][1])),
				Vector2i(int(r[1][0]), int(r[1][1])),
			])
		var parsed_sol: Array = []
		for mv in lv.get("sol", []):
			parsed_sol.append(mv)
		result.append({
			"steps": int(lv["steps"]),
			"min": int(lv.get("min", lv["steps"])),
			"pen": _parse_v2i_array(lv["pen"]),
			"queues": parsed_queues,
			"redirects": parsed_redirects,
			"muds": _parse_v2i_array(lv.get("muds", [])),
			"sol": parsed_sol,
		})
	return result


func _ready() -> void:
	levels = _load_levels_from_json()
	if levels.is_empty():
		push_error("levels.json 为空或解析失败,退出")
		return

	if not progress_applied:
		progress_applied = true
		level_index = _load_progress()
	level_index = clampi(level_index, 0, levels.size() - 1)

	_ui_font = SystemFont.new()
	_ui_font.font_names = PackedStringArray(
		["PingFang SC", "Hiragino Sans GB", "Heiti SC", "Microsoft YaHei", "Arial"])

	var rng := RandomNumberGenerator.new()
	rng.seed = 20260714
	for i in 60:
		_grass.append(Vector2(rng.randf_range(30, VIEW.x - 30), rng.randf_range(160, VIEW.y - 30)))

	_load_level(levels[level_index])

	var pen: Node2D = PenRendererScript.new()
	pen.setup(self)
	add_child(pen)

	_spawn_pigs()
	_spawn_bear()

	_overlay = PreviewOverlay.new()
	_overlay.main = self
	add_child(_overlay)

	_build_ui()

	if Meta.daily_pending:
		var got: int = Meta.claim_daily()
		_toast("每日奖励:+%d🪙 · 提示×1" % got)
		_refresh_topbar()
		_refresh_boosters()


# ---------- 关卡装载 ----------

func _ray_cells(c: Vector2i, d: Vector2i, lens: Array) -> Array:
	## 开口在圈外需要的净空格:可见槽位(按队首两头猪体长)+ 徽章格
	var need := 0
	for k in mini(VISIBLE_PIGS, lens.size()):
		need += int(lens[k])
	if lens.size() > VISIBLE_PIGS:
		need += 1
	var cells: Array = []
	for k in range(1, need + 1):
		cells.append(c + d * k)
	return cells


func _load_level(lv: Dictionary) -> void:
	pen_cells = lv["pen"]
	queues = lv["queues"]
	max_steps = lv["steps"]
	min_steps = lv["min"]
	redirects.clear()
	for r in lv.get("redirects", []):
		redirects[r[0]] = r[1]
	muds.clear()
	for m in lv.get("muds", []):
		muds[m] = true
	solution = lv.get("sol", [])
	_history = []
	steps_left = max_steps
	moves_made = 0

	openings = []
	for q in queues:
		openings.append([q["cell"], q["dir"]])

	cellset.clear()
	for c in pen_cells:
		cellset[c] = true
	_build_walls()

	# 自适应格子大小并居中(猪圈 + 可见排队槽位 + 徽章格)
	var minc := Vector2i(99, 99)
	var maxc := Vector2i(-99, -99)
	var all_cells: Array = pen_cells.duplicate()
	for q in queues:
		all_cells.append_array(_ray_cells(q["cell"], q["dir"], q["lens"]))
	for c in all_cells:
		minc = Vector2i(mini(minc.x, c.x), mini(minc.y, c.y))
		maxc = Vector2i(maxi(maxc.x, c.x), maxi(maxc.y, c.y))
	var cols := maxc.x - minc.x + 1
	var rows := maxc.y - minc.y + 1
	cell_size = floorf(minf(BASE_CELL,
			minf(PLAY_AREA.size.x / cols, PLAY_AREA.size.y / rows)))
	var total := Vector2(cols, rows) * cell_size
	grid_origin = PLAY_AREA.position + (PLAY_AREA.size - total) / 2.0 \
			- Vector2(minc) * cell_size


func _edge_key(a: Vector2i, b: Vector2i) -> String:
	if b.x < a.x or (b.x == a.x and b.y < a.y):
		var t := a
		a = b
		b = t
	return "%d,%d|%d,%d" % [a.x, a.y, b.x, b.y]


func _build_walls() -> void:
	walls.clear()
	wall_list.clear()
	var open_set := {}
	for o in openings:
		open_set[_edge_key(o[0], o[0] + o[1])] = true
	for c in pen_cells:
		for d in [Vector2i(1, 0), Vector2i(-1, 0), Vector2i(0, 1), Vector2i(0, -1)]:
			if cellset.has(c + d):
				continue
			var k := _edge_key(c, c + d)
			if open_set.has(k):
				continue
			walls[k] = true
			wall_list.append([c, d])


func _spawn_pigs() -> void:
	for qi in queues.size():
		var q: Dictionary = queues[qi]
		var c: Vector2i = q["cell"]
		var d: Vector2i = q["dir"]
		var lens: Array = q["lens"]
		var lane: Array = []
		var offset := 1
		for k in lens.size():
			var body: Array = []
			for j in int(lens[k]):
				body.append(c + d * (offset + j))
			offset += int(lens[k])
			var pig: Node2D = PigScript.new()
			pig.setup(self, body, -d, Meta.skin_tint())
			pig.entered = false
			pig.qi = qi
			pig.visible = k < VISIBLE_PIGS
			add_child(pig)
			pigs.append(pig)
			lane.append(pig)
		queue_all.append(lane)

		# 🐷×n 徽章(收纳看不见的排队猪)
		var badge := Label.new()
		badge.horizontal_alignment = HORIZONTAL_ALIGNMENT_CENTER
		badge.vertical_alignment = VERTICAL_ALIGNMENT_CENTER
		badge.add_theme_font_override("font", _ui_font)
		badge.add_theme_font_size_override("font_size", int(cell_size * 0.42))
		badge.add_theme_color_override("font_color", Color(0.32, 0.18, 0.08))
		badge.add_theme_color_override("font_outline_color", Color(1, 1, 1, 0.9))
		badge.add_theme_constant_override("outline_size", int(cell_size * 0.08))
		badge.size = Vector2(cell_size * 2.0, cell_size)
		var vis_cells := 0
		for k in mini(VISIBLE_PIGS, lens.size()):
			vis_cells += int(lens[k])
		var bc: Vector2i = c + d * (vis_cells + 1)
		badge.position = cell_center(bc) - badge.size / 2.0
		add_child(badge)
		badges.append(badge)

	_rebuild_occupied()
	_update_badges()


func _waiting_list(qi: int) -> Array:
	## 某开口仍在排队的猪(队首在前);进圈的总是队首,剩下的是原顺序后缀
	var out: Array = []
	for pig in queue_all[qi]:
		if not pig.entered:
			out.append(pig)
	return out


func _rebuild_occupied() -> void:
	occupied.clear()
	for pig in pigs:
		if pig.entered or pig.visible:
			for cc in pig.cells:
				occupied[cc] = pig


func _relayout_queues(animate: bool) -> void:
	## 队列补位:进圈猪让出位置后,等待猪贴着开口重排;
	## 跨在开口上的猪(身体还占着圈外格)会把整队向外顶。
	for qi in queues.size():
		var q: Dictionary = queues[qi]
		var c: Vector2i = q["cell"]
		var d: Vector2i = q["dir"]
		var base := 1
		while true:
			var probe: Vector2i = c + d * base
			if occupied.has(probe) and occupied[probe].entered:
				base += 1
			else:
				break
		var waiting := _waiting_list(qi)
		var offset := base
		for k in waiting.size():
			var pig: Node2D = waiting[k]
			var body: Array = []
			for j in pig.length():
				body.append(c + d * (offset + j))
			offset += pig.length()
			pig.cells = body
			var was_hidden: bool = not pig.visible
			pig.visible = k < VISIBLE_PIGS
			if pig.visible and not was_hidden and animate:
				pig.tween_pose(0.15)
			else:
				pig.sync_pose()
	_rebuild_occupied()
	_update_badges()


func _update_badges() -> void:
	for qi in queues.size():
		var hidden := _waiting_list(qi).size() - VISIBLE_PIGS
		badges[qi].visible = hidden > 0
		if hidden > 0:
			badges[qi].text = "🐷×%d" % hidden


func _spawn_bear() -> void:
	bear = BearScript.new()
	var spr := Sprite2D.new()
	spr.name = "Sprite"
	spr.texture = BEAR_TEX
	spr.scale = Vector2(0.8, 0.8)
	bear.add_child(spr)
	var corners := [Vector2(904, 1130), Vector2(120, 1130), Vector2(904, 280), Vector2(120, 280)]
	var pos: Vector2 = corners[0]
	for cand in corners:
		var clear := true
		for pig in pigs:
			if pig.visible and pig.bounds_rect().grow(70.0).has_point(cand):
				clear = false
				break
		if clear and not _pen_rect().grow(70.0).has_point(cand):
			pos = cand
			break
	bear.region = Rect2(pos - Vector2(85, 85), Vector2(170, 170))
	bear.position = pos
	add_child(bear)


func _pen_rect() -> Rect2:
	var minc := Vector2i(99, 99)
	var maxc := Vector2i(-99, -99)
	for c in pen_cells:
		minc = Vector2i(mini(minc.x, c.x), mini(minc.y, c.y))
		maxc = Vector2i(maxi(maxc.x, c.x), maxi(maxc.y, c.y))
	return Rect2(grid_origin + Vector2(minc) * cell_size,
			Vector2(maxc - minc + Vector2i.ONE) * cell_size)


func cell_center(c: Vector2i) -> Vector2:
	return grid_origin + (Vector2(c) + Vector2(0.5, 0.5)) * cell_size


func is_inside(c: Vector2i) -> bool:
	return cellset.has(c)


func meta_tint() -> Color:
	return Meta.skin_tint()


# ---------- 输入与移动 ----------

func _unhandled_input(event: InputEvent) -> void:
	if game_over or animating:
		return
	if event is InputEventMouseButton and event.pressed \
			and event.button_index == MOUSE_BUTTON_LEFT:
		var p := get_global_mouse_position()
		for pig in pigs:
			if pig.visible and pig.hit_test(p):
				_tap_pig(pig)
				return


func _tap_pig(pig: Node2D) -> void:
	# 移动前快照:供撤销道具回滚,也用于滑行超限(箭头走马灯)时原地还原
	var snap := {"steps": steps_left, "moves": moves_made, "pigs": []}
	for pg in pigs:
		snap["pigs"].append([pg, pg.cells.duplicate(), pg.dir, pg.entered])

	var head_before: Vector2i = pig.cells[0]
	var was_waiting: bool = not pig.entered
	var moved := 0
	var snaps: Array = []
	while true:
		if moved >= 90:
			# 箭头走马灯:视为非法移动(与生成器内核一致),原地还原
			_restore_snapshot(snap)
			pig.wiggle()
			return
		var head: Vector2i = pig.cells[0]
		var next: Vector2i = head + pig.dir
		if is_inside(head) and not is_inside(next):
			break  # 开口只进不出
		if walls.has(_edge_key(head, next)):
			break
		if occupied.has(next):
			var other: Node2D = occupied[next]
			if other != pig:
				break
			if next != pig.tail_cell():
				break  # 自撞身体中段;正在腾出的尾格可以进
		occupied.erase(pig.tail_cell())
		pig.cells.pop_back()
		pig.cells.push_front(next)
		occupied[next] = pig
		moved += 1
		if redirects.has(next):
			pig.dir = redirects[next]
		snaps.append([pig.cells.duplicate(), pig.dir])
		if muds.has(next):
			break  # 泥坑:当场停下,再点一次才继续走

	if moved == 0:
		pig.wiggle()
		return
	_preview_pig = null
	_overlay.queue_redraw()

	_undo_stack.append(snap)
	if not pig.entered:
		pig.entered = true   # 队首进圈(或跨在开口上),离开等待队列

	# 记录移动(与官方解线同编码),供提示回放与撤销回退
	if was_waiting:
		_history.append([0, pig.qi])
	else:
		_history.append([1, head_before.x, head_before.y])
	_solver_gen += 1
	_solver_abort = true

	steps_left -= 1
	moves_made += 1
	_update_steps_label()
	animating = true
	await pig.slide_snapshots(snaps, 0.12 + 0.05 * moved)
	animating = false
	_relayout_queues(true)
	_check_state()
	if not game_over:
		_request_doom()


func _restore_snapshot(snap: Dictionary) -> void:
	for e in snap["pigs"]:
		var pg: Node2D = e[0]
		pg.cells = (e[1] as Array).duplicate()
		pg.dir = e[2]
		pg.entered = e[3]
	steps_left = snap["steps"]
	moves_made = snap["moves"]
	_rebuild_occupied()
	_relayout_queues(false)
	for pg in pigs:
		if pg.entered:
			pg.sync_pose()
	_update_steps_label()


func _all_inside() -> bool:
	for pig in pigs:
		for cc in pig.cells:
			if not is_inside(cc):
				return false
	return true


func _any_move_possible() -> bool:
	## 只考察可见的猪(被 🐷×n 收纳的猪本来就点不到)
	for pig in pigs:
		if not pig.visible:
			continue
		var head: Vector2i = pig.cells[0]
		var next: Vector2i = head + pig.dir
		if is_inside(head) and not is_inside(next):
			continue
		if walls.has(_edge_key(head, next)):
			continue
		if occupied.has(next):
			var other: Node2D = occupied[next]
			if other != pig or next != pig.tail_cell():
				continue
		return true
	return false


func _check_state() -> void:
	if game_over:
		return
	if _all_inside():
		_win()
	elif steps_left <= 0 or not _any_move_possible():
		_fail()


# ---------- 后台求解与死局感知 ----------
## 求解在后台线程执行,主线程零冻结。结果带"局面代数",过期即丢弃。
## 死局感知:确认无解就立刻示警,把"隐藏的欺骗深度"变成看得见的紧张感。

func _solver_busy() -> bool:
	return _solver_thread != null


func _start_solver(kind: String, budget: int) -> void:
	_solver_abort = false
	var ctx := {
		"kind": kind, "budget": budget, "gen": _solver_gen,
		"steps": steps_left,
	}
	var entered: Array = []
	var counts: Array = []
	for pig in pigs:
		if pig.entered:
			entered.append([pig.cells.duplicate(), pig.dir])
	for qi in queues.size():
		counts.append(_waiting_list(qi).size())
	entered.sort()
	ctx["entered"] = entered
	ctx["counts"] = counts
	_solver_thread = Thread.new()
	_solver_thread.start(_solver_main.bind(ctx))


func _solver_main(ctx: Dictionary) -> void:
	# 线程入口:只读棋盘常量(墙/箭头/泥坑仅在换关时变化,换关前会 join)
	_dfs_nodes = 0
	_dfs_budget = int(ctx["budget"])
	_dfs_overflow = false
	var visited := {}
	var seq = _dfs(ctx["entered"], ctx["counts"], int(ctx["steps"]), visited)
	call_deferred("_solver_done", ctx, seq, _dfs_overflow)


func _solver_done(ctx: Dictionary, seq: Variant, overflow: bool) -> void:
	if _solver_thread != null:
		_solver_thread.wait_to_finish()
		_solver_thread = null
	var fresh: bool = int(ctx["gen"]) == _solver_gen and not game_over
	if ctx["kind"] == "hint":
		_refresh_boosters()
		if fresh:
			_deliver_hint(seq, overflow)
	else:
		if fresh:
			_apply_doom(seq == null and not overflow)
	# 求解器忙时积压的死局复查,现在补跑
	if _doom_dirty and not _solver_busy() and not game_over:
		_doom_dirty = false
		_start_solver("doom", DOOM_BUDGET)


func _request_doom() -> void:
	if game_over:
		return
	if _solver_busy():
		_doom_dirty = true
		return
	_start_solver("doom", DOOM_BUDGET)


func _apply_doom(doomed_now: bool) -> void:
	if doomed_now and not _doomed:
		_toast("🐻 熊嗅到了危险……这条路走不通了,试试撤销")
		if bear != null:
			var tw := create_tween()
			tw.tween_property(bear, "scale", Vector2(1.25, 1.25), 0.16)
			tw.tween_property(bear, "scale", Vector2.ONE, 0.3)
	_doomed = doomed_now
	_steps_label.add_theme_color_override("font_color",
			Color(1.0, 0.42, 0.36) if _doomed else Color(1, 1, 0.75))


func _exit_tree() -> void:
	_solver_abort = true
	if _solver_thread != null:
		_solver_thread.wait_to_finish()
		_solver_thread = null


# ---------- 滑行轨迹预览 ----------
## 鼠标悬停(手机上为按住)在可点的猪上时,显示它这一步会经过的格子、
## 转向点和最终落点——箭头关不再靠脑内模拟。

func _process(_dt: float) -> void:
	_update_preview()


func _update_preview() -> void:
	if game_over or animating:
		if _preview_pig != null:
			_preview_pig = null
			_overlay.queue_redraw()
		return
	var p := get_global_mouse_position()
	var hover: Node2D = null
	for pig in pigs:
		if pig.visible and pig.hit_test(p):
			hover = pig
			break
	if hover == _preview_pig:
		return
	_preview_pig = hover
	_preview_cells.clear()
	_preview_end.clear()
	if hover != null:
		var occ := occupied.duplicate()
		for cc in hover.cells:
			occ.erase(cc)
		var cells: Array = hover.cells.duplicate()
		var m: Vector2i = hover.dir
		var moved := 0
		while moved < 90:
			var head: Vector2i = cells[0]
			var next: Vector2i = head + m
			if is_inside(head) and not is_inside(next):
				break
			if walls.has(_edge_key(head, next)):
				break
			if occ.has(next):
				break
			if cells.has(next) and next != cells[cells.size() - 1]:
				break
			cells.pop_back()
			cells.push_front(next)
			moved += 1
			_preview_cells.append(next)
			if redirects.has(next):
				m = redirects[next]
			if muds.has(next):
				break
		if moved > 0:
			_preview_end = cells
	_overlay.queue_redraw()


class PreviewOverlay extends Node2D:
	## 预览绘制层:路径圆点 + 落点双格投影,叠加在棋盘与猪之上。
	var main: Node2D

	func _draw() -> void:
		if main == null or main._preview_pig == null \
				or main._preview_end.is_empty():
			return
		var cell: float = main.cell_size
		for c in main._preview_cells:
			draw_circle(main.cell_center(c), cell * 0.07, Color(1, 1, 1, 0.55))
		for c2 in main._preview_end:
			var pos: Vector2 = main.grid_origin + Vector2(c2) * cell
			draw_rect(Rect2(pos + Vector2(7, 7) , Vector2(cell - 14, cell - 14)),
					Color(1, 1, 1, 0.24))
		var ph: Vector2i = main._preview_end[0]
		var hp: Vector2 = main.grid_origin + Vector2(ph) * cell
		draw_rect(Rect2(hp + Vector2(7, 7), Vector2(cell - 14, cell - 14)),
				Color(1, 1, 1, 0.9), false, 4.0)


# ---------- 道具:撤销 / 提示 / 加步 ----------

func _do_undo() -> void:
	if game_over or animating or _undo_stack.is_empty():
		return
	if not Meta.use_booster("undo"):
		_toast("金币不足")
		return
	var snap: Dictionary = _undo_stack.pop_back()
	_restore_snapshot(snap)
	if not _history.is_empty():
		_history.pop_back()
	_solver_gen += 1
	_solver_abort = true
	_preview_pig = null
	_overlay.queue_redraw()
	_refresh_topbar()
	_refresh_boosters()
	_request_doom()


func _do_hint() -> void:
	if game_over or animating:
		return
	# 1) 官方解线回放:玩家仍在最优线上 → 瞬时给下一手,零计算
	if _on_solution_line():
		var mv: Array = solution[_history.size()]
		if not Meta.use_booster("hint"):
			_toast("金币不足")
			return
		_flash_move(mv)
		_refresh_topbar()
		_refresh_boosters()
		return
	# 2) 偏离解线 → 后台求解,不冻结画面
	if _solver_busy():
		_toast("💡 还在计算中,稍等…")
		return
	_hint_btn.text = "💡 计算中…"
	_start_solver("hint", HINT_BUDGET)


func _on_solution_line() -> bool:
	if solution.is_empty() or _history.size() >= solution.size():
		return false
	for i in _history.size():
		var a: Array = _history[i]
		var b: Array = solution[i]
		if a.size() != b.size():
			return false
		for j in a.size():
			if int(a[j]) != int(b[j]):
				return false
	return true


func _flash_move(mv: Array) -> void:
	if int(mv[0]) == 0:
		var waiting := _waiting_list(int(mv[1]))
		if not waiting.is_empty():
			waiting[0].flash()
	else:
		var head := Vector2i(int(mv[1]), int(mv[2]))
		for pig in pigs:
			if pig.entered and pig.cells[0] == head:
				pig.flash()
				break


func _deliver_hint(seq: Variant, overflow: bool) -> void:
	## 后台求解结果送达(仅当局面未变时调用)
	if seq == null or (seq as Array).is_empty():
		if overflow:
			_toast("局面太复杂,提示一时算不出来…先凭直觉走一步?")
		else:
			_toast("当前局面在剩余步数内已无解,试试撤销")
		return
	if not Meta.use_booster("hint"):
		_toast("金币不足")
		return
	var mv: Array = seq[0]
	if mv[0] == "q":
		var waiting := _waiting_list(int(mv[1]))
		if not waiting.is_empty():
			waiting[0].flash()
	else:
		for pig in pigs:
			if pig.entered and pig.cells == mv[1]:
				pig.flash()
				break
	_refresh_topbar()
	_refresh_boosters()


func _do_extra_steps() -> void:
	if game_over or animating:
		return
	if not Meta.use_booster("steps"):
		_toast("金币不足")
		return
	steps_left += 2
	_solver_gen += 1
	_solver_abort = true
	_update_steps_label()
	_refresh_topbar()
	_refresh_boosters()
	_request_doom()


# ---------- 实时求解(提示道具用) ----------
## 队列模型 DFS:状态 = (已入场猪 (tail,head,dir), 各队列剩余数)。
## 移动 = 释放某队队首 / 已入场猪再滑。找到第一条通关序列即返回。

func _solve_from_current(node_budget: int = HINT_BUDGET) -> Variant:
	var entered: Array = []
	var counts: Array = []
	for pig in pigs:
		if pig.entered:
			entered.append([pig.cells.duplicate(), pig.dir])
	for qi in queues.size():
		counts.append(_waiting_list(qi).size())
	entered.sort()
	_dfs_nodes = 0
	_dfs_budget = node_budget
	_dfs_overflow = false
	var visited := {}
	return _dfs(entered, counts, steps_left, visited)


func _sim_slide(cells_in: Array, m: Vector2i, occ: Dictionary) -> Array:
	var cells: Array = cells_in.duplicate()
	var moved := 0
	while true:
		if moved >= 90:
			return [false, cells, m]
		var head: Vector2i = cells[0]
		var next: Vector2i = head + m
		if is_inside(head) and not is_inside(next):
			break
		if walls.has(_edge_key(head, next)):
			break
		if occ.has(next):
			break
		if cells.has(next) and next != cells[cells.size() - 1]:
			break
		cells.pop_back()
		cells.push_front(next)
		moved += 1
		if redirects.has(next):
			m = redirects[next]
		if muds.has(next):
			break
	return [moved > 0, cells, m]


func _dfs(entered: Array, counts: Array, remaining: int,
		visited: Dictionary) -> Variant:
	var done := true
	for p in entered:
		for cc in p[0]:
			if not is_inside(cc):
				done = false
				break
		if not done:
			break
	if done:
		for c in counts:
			if c > 0:
				done = false
				break
	if done:
		return []
	if remaining <= 0:
		return null
	var key := _state_key(entered, counts)
	if int(visited.get(key, -1)) >= remaining:
		return null
	visited[key] = remaining
	_dfs_nodes += 1
	if _dfs_nodes > _dfs_budget or _solver_abort:
		_dfs_overflow = true
		return null

	var occ := {}
	for p in entered:
		for cc in p[0]:
			occ[cc] = true

	# 释放某队队首。体长取自关卡定义的静态体长序列(lens 队首在前):
	# 剩 counts[qi] 头时,下一头是第 lens.size()-counts[qi] 个。
	# 不能读活猪节点(_waiting_list)——本函数在后台线程跑,
	# 主线程随时在改 pig.entered,竞争会产生 -1 下标崩溃。
	for qi in counts.size():
		if counts[qi] == 0:
			continue
		var qlens: Array = queues[qi]["lens"]
		var length: int = int(qlens[qlens.size() - counts[qi]])
		var c: Vector2i = queues[qi]["cell"]
		var d: Vector2i = queues[qi]["dir"]
		var spawn: Array = []
		var blocked := false
		for j in length:
			var cellj: Vector2i = c + d * (1 + j)
			if occ.has(cellj):
				blocked = true
				break
			spawn.append(cellj)
		if blocked:
			continue
		var r := _sim_slide(spawn, -d, occ)
		if not r[0]:
			continue
		var ne := entered.duplicate(true)
		ne.append([r[1], r[2]])
		ne.sort()
		var nc := counts.duplicate()
		nc[qi] -= 1
		var sub = _dfs(ne, nc, remaining - 1, visited)
		if sub != null:
			var path: Array = sub
			path.insert(0, ["q", qi])
			return path

	# 已入场猪再滑
	for i in entered.size():
		var p: Array = entered[i]
		var occ2 := occ.duplicate()
		for cc in p[0]:
			occ2.erase(cc)
		var r := _sim_slide(p[0], p[1], occ2)
		if not r[0]:
			continue
		var ne := entered.duplicate(true)
		ne[i] = [r[1], r[2]]
		ne.sort()
		var sub = _dfs(ne, counts, remaining - 1, visited)
		if sub != null:
			var path: Array = sub
			path.insert(0, ["p", p[0]])
			return path
	return null


func _state_key(entered: Array, counts: Array) -> String:
	var s := ""
	for p in entered:
		for cc in p[0]:
			s += "%d,%d." % [cc.x, cc.y]
		s += "%d,%d;" % [p[1].x, p[1].y]
	s += "|"
	for c in counts:
		s += "%d," % c
	return s


# ---------- 胜负 ----------

func _win() -> void:
	game_over = true
	_title.text = "全部进圈！"
	for pig in pigs:
		pig.celebrate()

	# 星级:最优步数 3★,多 1 步 2★,过关 1★
	var star_cnt := 1
	if moves_made <= min_steps:
		star_cnt = 3
	elif moves_made <= min_steps + 1:
		star_cnt = 2
	var reward: Dictionary = Meta.record_win(level_index, star_cnt)

	var next_idx := level_index + 1
	var saved := _load_progress()
	if next_idx > saved:
		_save_progress(next_idx)

	await get_tree().create_timer(1.0).timeout
	var lines := "%s\n+%d🪙" % ["★".repeat(star_cnt) + "☆".repeat(3 - star_cnt), reward["coins"]]
	if int(reward["streak"]) >= 2:
		lines += "   🔥连胜 %d" % reward["streak"]
	if reward["bonus_booster"] != "":
		var names := {"undo": "撤销", "hint": "提示", "steps": "+2步"}
		lines += "\n连胜奖励:%s道具 ×1" % names[reward["bonus_booster"]]
	_btn_mode = "advance"
	if level_index >= levels.size() - 1:
		_result_label.text = "恭喜，全部通关！\n" + lines
		_btn.text = "从头再玩"
	else:
		_result_label.text = "过关啦！\n" + lines
		_btn.text = "下一关"
	_btn.disabled = false
	_btn2.visible = false
	_refresh_topbar()
	_panel.visible = true


func _fail() -> void:
	game_over = true
	# 步数耗尽但仍有路可走 → 续关报价(Candy Crush 式)
	if steps_left <= 0 and _any_move_possible():
		_btn_mode = "continue"
		_result_label.text = "步数用完了！"
		_btn.text = "+2 步继续（%d🪙）" % Meta.CONTINUE_PRICE
		_btn.disabled = Meta.coins < Meta.CONTINUE_PRICE
		_btn2.text = "放弃"
		_btn2.visible = true
		_panel.visible = true
		return
	_do_fail()


func _do_fail() -> void:
	game_over = true
	Meta.record_fail()
	_refresh_topbar()
	_title.text = "糟糕…"
	var victim: Node2D = null
	for pig in pigs:
		if not pig.visible:
			continue
		for cc in pig.cells:
			if not is_inside(cc):
				victim = pig
				break
		if victim != null:
			break
	if victim != null and bear != null:
		bear.chasing = true
		var target: Vector2 = victim.center_pos()
		var tw := create_tween()
		tw.tween_property(bear, "rotation",
				(target - bear.position).angle() + PI / 2.0, 0.15)
		tw.tween_property(bear, "position", target, 0.7)\
			.set_trans(Tween.TRANS_QUAD).set_ease(Tween.EASE_IN)
		await tw.finished
		victim.visible = false
		bear.visible = false
		_spawn_cloud(target)
		_spawn_cross(target + Vector2(140, -60))
		await get_tree().create_timer(1.4).timeout
	_btn_mode = "retry"
	_result_label.text = "小猪被熊抓走了…"
	if Meta.can_play():
		_btn.text = "再试一次"
		_btn.disabled = false
	else:
		_btn.text = "❤ 回复中 %s" % Meta.heart_wait_text()
		_btn.disabled = true
	_btn2.visible = false
	_panel.visible = true


func _on_btn_pressed() -> void:
	match _btn_mode:
		"continue":
			if Meta.try_spend(Meta.CONTINUE_PRICE):
				game_over = false
				steps_left += 2
				_solver_gen += 1
				_solver_abort = true
				_panel.visible = false
				_update_steps_label()
				_refresh_topbar()
				_request_doom()
			return
		"advance":
			if level_index < levels.size() - 1:
				level_index += 1
			else:
				level_index = 0
		"retry":
			if not Meta.can_play():
				return
	get_tree().reload_current_scene()


func _on_btn2_pressed() -> void:
	# 放弃续关 → 走正常失败流程
	_panel.visible = false
	_do_fail()


# ---------- 特效 ----------

func _spawn_cloud(pos: Vector2) -> void:
	var s := Sprite2D.new()
	s.texture = CLOUD_TEX
	s.position = pos
	s.scale = Vector2(0.2, 0.2)
	add_child(s)
	var tw := create_tween()
	tw.tween_property(s, "scale", Vector2(1.3, 1.3), 0.25)\
		.set_trans(Tween.TRANS_BACK).set_ease(Tween.EASE_OUT)
	var wob := create_tween().set_loops(8)
	wob.tween_property(s, "rotation", 0.14, 0.09)
	wob.tween_property(s, "rotation", -0.14, 0.09)


func _spawn_cross(pos: Vector2) -> void:
	var s := Sprite2D.new()
	s.texture = CROSS_TEX
	s.position = pos
	s.scale = Vector2(0.1, 0.1)
	add_child(s)
	var tw := create_tween()
	tw.tween_interval(0.5)
	tw.tween_property(s, "scale", Vector2(1.0, 1.0), 0.25)\
		.set_trans(Tween.TRANS_BACK).set_ease(Tween.EASE_OUT)


# ---------- UI ----------

func _update_steps_label() -> void:
	_steps_label.text = "第 %d / %d 关 · 剩余步数：%d" % [level_index + 1, levels.size(), steps_left]


func _refresh_topbar() -> void:
	Meta.tick_hearts()
	var h := "❤ %d/%d" % [Meta.hearts, Meta.MAX_HEARTS]
	var wait := Meta.heart_wait_text()
	if wait != "":
		h += "（%s）" % wait
	_hearts_label.text = h
	_coins_label.text = "🪙 %d" % Meta.coins
	_streak_label.text = "🔥 %d" % Meta.streak
	_streak_label.visible = Meta.streak >= 2


func _refresh_boosters() -> void:
	_undo_btn.text = "↩ 撤销 %s" % Meta.booster_label("undo")
	_hint_btn.text = "💡 提示 %s" % Meta.booster_label("hint")
	_steps_btn.text = "➕ 2步 %s" % Meta.booster_label("steps")


func _toast(msg: String) -> void:
	_toast_label.text = msg
	_toast_label.modulate.a = 1.0
	var tw := create_tween()
	tw.tween_interval(1.8)
	tw.tween_property(_toast_label, "modulate:a", 0.0, 0.6)


func _build_ui() -> void:
	var ui := CanvasLayer.new()
	add_child(ui)

	_title = Label.new()
	_title.text = "把小猪全部赶进猪圈！"
	_style_label(_title, 52, Color.WHITE)
	_title.set_anchors_and_offsets_preset(Control.PRESET_TOP_WIDE)
	_title.offset_top = 20.0
	_title.offset_bottom = 92.0
	ui.add_child(_title)

	_steps_label = Label.new()
	_style_label(_steps_label, 38, Color(1, 1, 0.75))
	_steps_label.set_anchors_and_offsets_preset(Control.PRESET_TOP_WIDE)
	_steps_label.offset_top = 96.0
	_steps_label.offset_bottom = 148.0
	ui.add_child(_steps_label)
	_update_steps_label()

	var hint := Label.new()
	if not redirects.is_empty():
		hint.text = "蓝色箭头会改变滑行方向 · 先规划谁去触发！"
	else:
		hint.text = "点击队首的小猪送它进圈 · 顺序很重要！"
	_style_label(hint, 26, Color(1, 1, 1, 0.9))
	hint.set_anchors_and_offsets_preset(Control.PRESET_BOTTOM_WIDE)
	hint.offset_top = -50.0
	hint.offset_bottom = -10.0
	ui.add_child(hint)

	# ── 顶栏:红心 / 金币 / 连胜 ──
	_hearts_label = Label.new()
	_style_label(_hearts_label, 30, Color(1, 0.85, 0.85))
	_hearts_label.horizontal_alignment = HORIZONTAL_ALIGNMENT_LEFT
	_hearts_label.set_anchors_and_offsets_preset(Control.PRESET_TOP_LEFT)
	_hearts_label.offset_left = 178.0
	_hearts_label.offset_top = 28.0
	_hearts_label.offset_right = 470.0
	_hearts_label.offset_bottom = 72.0
	ui.add_child(_hearts_label)

	_coins_label = Label.new()
	_style_label(_coins_label, 30, Color(1, 0.95, 0.6))
	_coins_label.horizontal_alignment = HORIZONTAL_ALIGNMENT_RIGHT
	_coins_label.set_anchors_and_offsets_preset(Control.PRESET_TOP_RIGHT)
	_coins_label.offset_left = -300.0
	_coins_label.offset_top = 28.0
	_coins_label.offset_right = -22.0
	_coins_label.offset_bottom = 72.0
	ui.add_child(_coins_label)

	_streak_label = Label.new()
	_style_label(_streak_label, 30, Color(1, 0.7, 0.35))
	_streak_label.horizontal_alignment = HORIZONTAL_ALIGNMENT_RIGHT
	_streak_label.set_anchors_and_offsets_preset(Control.PRESET_TOP_RIGHT)
	_streak_label.offset_left = -300.0
	_streak_label.offset_top = 78.0
	_streak_label.offset_right = -22.0
	_streak_label.offset_bottom = 120.0
	ui.add_child(_streak_label)

	var timer := Timer.new()
	timer.wait_time = 1.0
	timer.autostart = true
	timer.timeout.connect(_refresh_topbar)
	ui.add_child(timer)

	# ── 道具栏 ──
	var bar := HBoxContainer.new()
	bar.alignment = BoxContainer.ALIGNMENT_CENTER
	bar.add_theme_constant_override("separation", 22)
	bar.set_anchors_and_offsets_preset(Control.PRESET_BOTTOM_WIDE)
	bar.offset_top = -156.0
	bar.offset_bottom = -62.0
	ui.add_child(bar)

	_undo_btn = _make_booster_btn(_do_undo)
	bar.add_child(_undo_btn)
	_hint_btn = _make_booster_btn(_do_hint)
	bar.add_child(_hint_btn)
	_steps_btn = _make_booster_btn(_do_extra_steps)
	bar.add_child(_steps_btn)
	_refresh_boosters()

	# ── 提示浮层 ──
	_toast_label = Label.new()
	_style_label(_toast_label, 32, Color(1, 1, 1))
	_toast_label.set_anchors_and_offsets_preset(Control.PRESET_TOP_WIDE)
	_toast_label.offset_top = 152.0
	_toast_label.offset_bottom = 200.0
	_toast_label.modulate.a = 0.0
	ui.add_child(_toast_label)

	# ── 结算面板 ──
	_panel = CenterContainer.new()
	_panel.set_anchors_and_offsets_preset(Control.PRESET_FULL_RECT)
	_panel.visible = false
	ui.add_child(_panel)

	var box := PanelContainer.new()
	var style := StyleBoxFlat.new()
	style.bg_color = Color(1, 1, 1, 0.96)
	style.set_corner_radius_all(28)
	style.set_content_margin_all(48.0)
	box.add_theme_stylebox_override("panel", style)
	_panel.add_child(box)

	var v := VBoxContainer.new()
	v.add_theme_constant_override("separation", 30)
	v.alignment = BoxContainer.ALIGNMENT_CENTER
	box.add_child(v)

	_result_label = Label.new()
	_style_label(_result_label, 48, Color(0.24, 0.16, 0.1))
	_result_label.add_theme_constant_override("outline_size", 0)
	v.add_child(_result_label)

	_btn = Button.new()
	_btn.custom_minimum_size = Vector2(420, 92)
	_btn.add_theme_font_override("font", _ui_font)
	_btn.add_theme_font_size_override("font_size", 36)
	_btn.pressed.connect(_on_btn_pressed)
	v.add_child(_btn)

	_btn2 = Button.new()
	_btn2.custom_minimum_size = Vector2(420, 72)
	_btn2.add_theme_font_override("font", _ui_font)
	_btn2.add_theme_font_size_override("font_size", 30)
	_btn2.visible = false
	_btn2.pressed.connect(_on_btn2_pressed)
	v.add_child(_btn2)

	var panel_sel := Button.new()
	panel_sel.text = "选关"
	panel_sel.custom_minimum_size = Vector2(420, 64)
	panel_sel.add_theme_font_override("font", _ui_font)
	panel_sel.add_theme_font_size_override("font_size", 28)
	panel_sel.pressed.connect(_toggle_select)
	v.add_child(panel_sel)

	# 左上角常驻选关按钮
	var sel_btn := Button.new()
	sel_btn.text = "☰ 选关"
	sel_btn.add_theme_font_override("font", _ui_font)
	sel_btn.add_theme_font_size_override("font_size", 28)
	sel_btn.set_anchors_and_offsets_preset(Control.PRESET_TOP_LEFT)
	sel_btn.offset_left = 18.0
	sel_btn.offset_top = 22.0
	sel_btn.offset_right = 160.0
	sel_btn.offset_bottom = 78.0
	sel_btn.pressed.connect(_toggle_select)
	ui.add_child(sel_btn)

	_build_select_panel(ui)
	_build_shop_panel(ui)
	_refresh_topbar()


func _make_booster_btn(action: Callable) -> Button:
	var b := Button.new()
	b.custom_minimum_size = Vector2(250, 86)
	b.add_theme_font_override("font", _ui_font)
	b.add_theme_font_size_override("font_size", 27)
	b.pressed.connect(action)
	return b


func _build_select_panel(ui: CanvasLayer) -> void:
	var unlocked := levels.size() - 1 if UNLOCK_ALL else _load_progress()

	_select_panel = ColorRect.new()
	_select_panel.color = Color(0, 0, 0, 0.55)
	_select_panel.set_anchors_and_offsets_preset(Control.PRESET_FULL_RECT)
	_select_panel.visible = false
	_select_panel.gui_input.connect(func(ev: InputEvent) -> void:
		if ev is InputEventMouseButton and ev.pressed:
			_select_panel.visible = false)
	ui.add_child(_select_panel)

	var cc := CenterContainer.new()
	cc.set_anchors_and_offsets_preset(Control.PRESET_FULL_RECT)
	cc.mouse_filter = Control.MOUSE_FILTER_IGNORE
	_select_panel.add_child(cc)

	var box := PanelContainer.new()
	var style := StyleBoxFlat.new()
	style.bg_color = Color(1, 1, 1, 0.97)
	style.set_corner_radius_all(24)
	style.set_content_margin_all(30.0)
	box.add_theme_stylebox_override("panel", style)
	cc.add_child(box)

	var v := VBoxContainer.new()
	v.add_theme_constant_override("separation", 18)
	box.add_child(v)

	var head := Label.new()
	head.text = "选择关卡（已解锁 %d / %d · ★ %d）" % [
		mini(unlocked + 1, levels.size()), levels.size(), Meta.total_stars()]
	_style_label(head, 36, Color(0.24, 0.16, 0.1))
	head.add_theme_constant_override("outline_size", 0)
	v.add_child(head)

	var scroll := ScrollContainer.new()
	scroll.custom_minimum_size = Vector2(910, 740)
	v.add_child(scroll)

	var grid := GridContainer.new()
	grid.columns = 10
	grid.add_theme_constant_override("h_separation", 8)
	grid.add_theme_constant_override("v_separation", 8)
	scroll.add_child(grid)

	for i in levels.size():
		var b := Button.new()
		var s := Meta.level_stars(i)
		b.text = str(i + 1) + ("\n" + "★".repeat(s) if s > 0 else "")
		b.custom_minimum_size = Vector2(82, 74)
		b.add_theme_font_override("font", _ui_font)
		b.add_theme_font_size_override("font_size", 22)
		if i > unlocked:
			b.disabled = true
			b.text = "🔒"
		elif i == level_index:
			b.add_theme_color_override("font_color", Color("#d9781f"))
		b.pressed.connect(_goto_level.bind(i))
		grid.add_child(b)

	var hb := HBoxContainer.new()
	hb.alignment = BoxContainer.ALIGNMENT_CENTER
	hb.add_theme_constant_override("separation", 24)
	v.add_child(hb)

	var shop := Button.new()
	shop.text = "🐷 小猪装扮"
	shop.custom_minimum_size = Vector2(260, 64)
	shop.add_theme_font_override("font", _ui_font)
	shop.add_theme_font_size_override("font_size", 28)
	shop.pressed.connect(func() -> void:
		_select_panel.visible = false
		_populate_shop()
		_shop_panel.visible = true)
	hb.add_child(shop)

	var close := Button.new()
	close.text = "关闭"
	close.custom_minimum_size = Vector2(200, 64)
	close.add_theme_font_override("font", _ui_font)
	close.add_theme_font_size_override("font_size", 28)
	close.pressed.connect(func() -> void: _select_panel.visible = false)
	hb.add_child(close)


# ---------- 皮肤商店 ----------

func _build_shop_panel(ui: CanvasLayer) -> void:
	_shop_panel = ColorRect.new()
	_shop_panel.color = Color(0, 0, 0, 0.55)
	_shop_panel.set_anchors_and_offsets_preset(Control.PRESET_FULL_RECT)
	_shop_panel.visible = false
	_shop_panel.gui_input.connect(func(ev: InputEvent) -> void:
		if ev is InputEventMouseButton and ev.pressed:
			_shop_panel.visible = false)
	ui.add_child(_shop_panel)

	var cc := CenterContainer.new()
	cc.set_anchors_and_offsets_preset(Control.PRESET_FULL_RECT)
	cc.mouse_filter = Control.MOUSE_FILTER_IGNORE
	_shop_panel.add_child(cc)

	var box := PanelContainer.new()
	var style := StyleBoxFlat.new()
	style.bg_color = Color(1, 1, 1, 0.97)
	style.set_corner_radius_all(24)
	style.set_content_margin_all(34.0)
	box.add_theme_stylebox_override("panel", style)
	cc.add_child(box)

	_shop_box = VBoxContainer.new()
	_shop_box.add_theme_constant_override("separation", 16)
	box.add_child(_shop_box)


func _populate_shop() -> void:
	for child in _shop_box.get_children():
		child.queue_free()

	var head := Label.new()
	head.text = "小猪装扮（🪙 %d）" % Meta.coins
	_style_label(head, 36, Color(0.24, 0.16, 0.1))
	head.add_theme_constant_override("outline_size", 0)
	_shop_box.add_child(head)

	for id in Meta.SKINS:
		var info: Dictionary = Meta.SKINS[id]
		var row := HBoxContainer.new()
		row.add_theme_constant_override("separation", 20)
		_shop_box.add_child(row)

		var swatch := ColorRect.new()
		swatch.color = Color(1.0, 0.63, 0.72) * info["tint"]
		swatch.custom_minimum_size = Vector2(52, 52)
		row.add_child(swatch)

		var name_l := Label.new()
		name_l.text = info["name"]
		_style_label(name_l, 30, Color(0.24, 0.16, 0.1))
		name_l.add_theme_constant_override("outline_size", 0)
		name_l.custom_minimum_size = Vector2(240, 0)
		name_l.horizontal_alignment = HORIZONTAL_ALIGNMENT_LEFT
		row.add_child(name_l)

		var act := Button.new()
		act.custom_minimum_size = Vector2(220, 60)
		act.add_theme_font_override("font", _ui_font)
		act.add_theme_font_size_override("font_size", 26)
		if Meta.skin == id:
			act.text = "使用中"
			act.disabled = true
		elif Meta.owned_skins.has(id):
			act.text = "使用"
			act.pressed.connect(func() -> void:
				Meta.select_skin(id)
				_apply_skin()
				_populate_shop())
		else:
			act.text = "%d🪙" % int(info["price"])
			act.pressed.connect(func() -> void:
				if Meta.buy_skin(id):
					Meta.select_skin(id)
					_apply_skin()
					_refresh_topbar()
					_populate_shop()
				else:
					_toast("金币不足"))
		row.add_child(act)

	var close := Button.new()
	close.text = "关闭"
	close.custom_minimum_size = Vector2(200, 60)
	close.add_theme_font_override("font", _ui_font)
	close.add_theme_font_size_override("font_size", 28)
	close.pressed.connect(func() -> void: _shop_panel.visible = false)
	var hb := HBoxContainer.new()
	hb.alignment = BoxContainer.ALIGNMENT_CENTER
	hb.add_child(close)
	_shop_box.add_child(hb)


func _apply_skin() -> void:
	for pig in pigs:
		pig.set_tint(Meta.skin_tint())


func _toggle_select() -> void:
	_select_panel.visible = not _select_panel.visible


func _goto_level(i: int) -> void:
	level_index = i
	get_tree().reload_current_scene()


func _style_label(l: Label, size: int, color: Color) -> void:
	l.horizontal_alignment = HORIZONTAL_ALIGNMENT_CENTER
	l.add_theme_font_override("font", _ui_font)
	l.add_theme_font_size_override("font_size", size)
	l.add_theme_color_override("font_color", color)
	l.add_theme_color_override("font_outline_color", Color(0.15, 0.4, 0.1))
	l.add_theme_constant_override("outline_size", 10)


# ---------- 背景 ----------

func _draw() -> void:
	draw_rect(Rect2(Vector2.ZERO, VIEW), Color("#7bdd66"))
	for g in _grass:
		draw_line(g, g + Vector2(-5, -12), Color("#59c24a"), 4.0)
		draw_line(g, g + Vector2(6, -10), Color("#59c24a"), 4.0)
