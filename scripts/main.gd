extends Node2D
## 主场景:反向 Arrow Puzzle,共 100 关。
## 小猪占两格、在开口外等待,点击后沿固定方向滑入猪圈,
## 撞到栅栏或其他小猪即停下;开口只进不出。
## 在限定步数内全部进圈则过关。

const VIEW := Vector2(1024.0, 1280.0)
const PLAY_AREA := Rect2(16.0, 170.0, 992.0, 1050.0)
const BASE_CELL := 150.0
const PROGRESS_CFG := "user://progress.cfg"

const PigScript := preload("res://scripts/pig.gd")
const BearScript := preload("res://scripts/bear.gd")
const PenRendererScript := preload("res://scripts/pen_renderer.gd")

const PIG_TEX := preload("res://art/pig.svg")
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

var pen_cells: Array = []
var openings: Array = []   # [圈内格子, 朝外方向]
var pig_defs: Array = []   # [尾格, 头格, 前进方向]

var pigs: Array = []
var occupied := {}         # Vector2i -> pig
var walls := {}            # 边键 -> true
var wall_list: Array = []  # [圈内格子, 朝外方向],供绘制
var cellset := {}
var steps_left := 0
var game_over := false
var animating := false
var bear: Node2D

var _title: Label
var _steps_label: Label
var _panel: CenterContainer
var _select_panel: ColorRect
var _result_label: Label
var _btn: Button
var _advance_on_btn := false
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
	## 把 JSON 解析出的 [[x,y], ...] 转换成 Array[Vector2i]
	var result: Array = []
	for item in arr:
		result.append(Vector2i(int(item[0]), int(item[1])))
	return result


static func _parse_pig(raw: Array) -> Array:
	## raw = [[tx,ty],[hx,hy],[dx,dy]]  → [Vector2i, Vector2i, Vector2i]
	return [
		Vector2i(int(raw[0][0]), int(raw[0][1])),
		Vector2i(int(raw[1][0]), int(raw[1][1])),
		Vector2i(int(raw[2][0]), int(raw[2][1])),
	]


static func _parse_opening(raw: Array) -> Array:
	## raw = [[cx,cy],[dx,dy]]  → [Vector2i, Vector2i]
	return [
		Vector2i(int(raw[0][0]), int(raw[0][1])),
		Vector2i(int(raw[1][0]), int(raw[1][1])),
	]


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

		var parsed_openings: Array = []
		for o in lv["openings"]:
			parsed_openings.append(_parse_opening(o))

		var parsed_pigs: Array = []
		for p in lv["pigs"]:
			parsed_pigs.append(_parse_pig(p))

		result.append({
			"steps": int(lv["steps"]),
			"pen": _parse_v2i_array(lv["pen"]),
			"openings": parsed_openings,
			"pigs": parsed_pigs,
		})
	return result


func _ready() -> void:
	levels = _load_levels_from_json()
	if levels.is_empty():
		push_error("levels.json 为空或解析失败,退出")
		return

	# 读取进度并跳到已解锁的最高关(仅本次运行首次进场;
	# 之后「从头再玩」等手动切关不再被存档覆盖)
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
	_build_ui()


# ---------- 关卡装载 ----------

func _load_level(lv: Dictionary) -> void:
	pen_cells = lv["pen"]
	openings = lv["openings"]
	pig_defs = lv["pigs"]
	max_steps = lv["steps"]
	steps_left = max_steps

	cellset.clear()
	for c in pen_cells:
		cellset[c] = true
	_build_walls()

	# 自适应格子大小并居中(包含等候中的小猪)
	var minc := Vector2i(99, 99)
	var maxc := Vector2i(-99, -99)
	var all_cells: Array = pen_cells.duplicate()
	for def in pig_defs:
		all_cells.append(def[0])
		all_cells.append(def[1])
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
	for def in pig_defs:
		var pig: Node2D = PigScript.new()
		pig.main = self
		pig.tail = def[0]
		pig.head = def[1]
		pig.dir = def[2]
		var spr := Sprite2D.new()
		spr.name = "Sprite"
		spr.texture = PIG_TEX
		pig.add_child(spr)
		add_child(pig)
		pigs.append(pig)
		occupied[pig.tail] = pig
		occupied[pig.head] = pig


func _spawn_bear() -> void:
	bear = BearScript.new()
	var spr := Sprite2D.new()
	spr.name = "Sprite"
	spr.texture = BEAR_TEX
	spr.scale = Vector2(0.8, 0.8)
	bear.add_child(spr)
	# 挑一个不压到小猪和猪圈的角落游荡
	var corners := [Vector2(904, 1130), Vector2(120, 1130), Vector2(904, 280), Vector2(120, 280)]
	var pos: Vector2 = corners[0]
	for cand in corners:
		var clear := true
		for pig in pigs:
			if pig.hit_rect().grow(70.0).has_point(cand):
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


# ---------- 输入与移动 ----------

func _unhandled_input(event: InputEvent) -> void:
	if game_over or animating:
		return
	if event is InputEventMouseButton and event.pressed \
			and event.button_index == MOUSE_BUTTON_LEFT:
		var p := get_global_mouse_position()
		for pig in pigs:
			if pig.hit_rect().has_point(p):
				_tap_pig(pig)
				return


func _tap_pig(pig: Node2D) -> void:
	var moved := 0
	while moved < 64:
		var next: Vector2i = pig.head + pig.dir
		if is_inside(pig.head) and not is_inside(next):
			break  # 开口只进不出
		if walls.has(_edge_key(pig.head, next)):
			break
		if occupied.has(next):
			break
		occupied.erase(pig.tail)
		pig.tail = pig.head
		pig.head = next
		occupied[next] = pig
		moved += 1

	if moved == 0:
		pig.wiggle()
		return

	steps_left -= 1
	_update_steps_label()
	animating = true
	await pig.slide_to_cells(0.12 + 0.05 * moved)
	animating = false
	_check_state()


func _all_inside() -> bool:
	for pig in pigs:
		if not (is_inside(pig.tail) and is_inside(pig.head)):
			return false
	return true


func _any_move_possible() -> bool:
	for pig in pigs:
		var next: Vector2i = pig.head + pig.dir
		if is_inside(pig.head) and not is_inside(next):
			continue
		if not walls.has(_edge_key(pig.head, next)) and not occupied.has(next):
			return true
	return false


func _check_state() -> void:
	if game_over:
		return
	if _all_inside():
		_win()
	elif steps_left <= 0 or not _any_move_possible():
		_fail()


# ---------- 胜负 ----------

func _win() -> void:
	game_over = true
	_title.text = "全部进圈！"
	for pig in pigs:
		var tw := create_tween().set_loops(3)
		tw.tween_property(pig, "scale", Vector2(1.12, 1.12), 0.15)
		tw.tween_property(pig, "scale", Vector2.ONE, 0.15)

	# 保存进度
	var next_idx := level_index + 1
	var saved := _load_progress()
	if next_idx > saved:
		_save_progress(next_idx)

	await get_tree().create_timer(1.0).timeout
	_advance_on_btn = true
	if level_index >= levels.size() - 1:
		_result_label.text = "恭喜，全部通关！"
		_btn.text = "从头再玩"
	else:
		_result_label.text = "过关啦！"
		_btn.text = "下一关"
	_panel.visible = true


func _fail() -> void:
	game_over = true
	_title.text = "糟糕…"
	var victim: Node2D = null
	for pig in pigs:
		if not (is_inside(pig.tail) and is_inside(pig.head)):
			victim = pig
			break
	if victim != null and bear != null:
		bear.chasing = true
		var tw := create_tween()
		tw.tween_property(bear, "rotation",
				(victim.position - bear.position).angle() + PI / 2.0, 0.15)
		tw.tween_property(bear, "position", victim.position, 0.7)\
			.set_trans(Tween.TRANS_QUAD).set_ease(Tween.EASE_IN)
		await tw.finished
		victim.visible = false
		bear.visible = false
		_spawn_cloud(victim.position)
		_spawn_cross(victim.position + Vector2(140, -60))
		await get_tree().create_timer(1.4).timeout
	_advance_on_btn = false
	_result_label.text = "小猪被熊抓走了…"
	_btn.text = "再试一次"
	_panel.visible = true


func _on_btn_pressed() -> void:
	if _advance_on_btn:
		if level_index < levels.size() - 1:
			level_index += 1
		else:
			level_index = 0
	get_tree().reload_current_scene()


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
	hint.text = "点击小猪让它冲进猪圈 · 顺序很重要！"
	_style_label(hint, 28, Color(1, 1, 1, 0.9))
	hint.set_anchors_and_offsets_preset(Control.PRESET_BOTTOM_WIDE)
	hint.offset_top = -58.0
	hint.offset_bottom = -14.0
	ui.add_child(hint)

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
	v.add_theme_constant_override("separation", 34)
	v.alignment = BoxContainer.ALIGNMENT_CENTER
	box.add_child(v)

	_result_label = Label.new()
	_style_label(_result_label, 56, Color(0.24, 0.16, 0.1))
	_result_label.add_theme_constant_override("outline_size", 0)
	v.add_child(_result_label)

	_btn = Button.new()
	_btn.custom_minimum_size = Vector2(320, 96)
	_btn.add_theme_font_override("font", _ui_font)
	_btn.add_theme_font_size_override("font_size", 40)
	_btn.pressed.connect(_on_btn_pressed)
	v.add_child(_btn)

	var panel_sel := Button.new()
	panel_sel.text = "选关"
	panel_sel.custom_minimum_size = Vector2(320, 72)
	panel_sel.add_theme_font_override("font", _ui_font)
	panel_sel.add_theme_font_size_override("font_size", 32)
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
	head.text = "选择关卡（已解锁 %d / %d）" % [
		mini(unlocked + 1, levels.size()), levels.size()]
	_style_label(head, 40, Color(0.24, 0.16, 0.1))
	head.add_theme_constant_override("outline_size", 0)
	v.add_child(head)

	var scroll := ScrollContainer.new()
	scroll.custom_minimum_size = Vector2(910, 780)
	v.add_child(scroll)

	var grid := GridContainer.new()
	grid.columns = 10
	grid.add_theme_constant_override("h_separation", 8)
	grid.add_theme_constant_override("v_separation", 8)
	scroll.add_child(grid)

	for i in levels.size():
		var b := Button.new()
		b.text = str(i + 1)
		b.custom_minimum_size = Vector2(82, 70)
		b.add_theme_font_override("font", _ui_font)
		b.add_theme_font_size_override("font_size", 26)
		if i > unlocked:
			b.disabled = true
			b.text = "🔒"
		elif i == level_index:
			b.add_theme_color_override("font_color", Color("#d9781f"))
			b.add_theme_font_size_override("font_size", 30)
		b.pressed.connect(_goto_level.bind(i))
		grid.add_child(b)

	var close := Button.new()
	close.text = "关闭"
	close.custom_minimum_size = Vector2(200, 64)
	close.add_theme_font_override("font", _ui_font)
	close.add_theme_font_size_override("font_size", 30)
	close.pressed.connect(func() -> void: _select_panel.visible = false)
	var hb := HBoxContainer.new()
	hb.alignment = BoxContainer.ALIGNMENT_CENTER
	hb.add_child(close)
	v.add_child(hb)


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
