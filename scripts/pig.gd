extends Node2D
## 小猪棋子:1/2/3 格身体作为**一整只猪**用矢量绘制,不再分节拼精灵。
## 身体 = 沿各格中心的圆角胶囊(直身成长条,过箭头弯身成圆弧);
## 前端画猪头(吻部+眼睛+耳朵),后端画小卷尾。
## 逻辑格 cells(头在前)由 main.gd 读写;渲染点 _render_pts 是各格中心的
## 世界坐标,滑行时沿折线插值。节点自身停在原点(wiggle 时临时偏移整体)。

var main: Node2D
var cells: Array = []      # Vector2i,头在前
var dir: Vector2i
var entered := false       # 已离开等待队列(进圈或跨在开口上)
var qi := -1               # 所属开口队列下标
var boost := 1.0           # 庆祝等外部缩放系数

var _phase := 0.0
var _wiggling := false
var _render_pts: Array = []   # Vector2 世界坐标,与 cells 对应(0 = 头)
var _render_dir: Vector2i     # 头朝向(滑行中随关键帧更新)
var _tint := Color.WHITE      # 当前皮肤色(flash 时临时变亮黄)


func setup(m: Node2D, cells_in: Array, dir_in: Vector2i, tint: Color) -> void:
	main = m
	cells = cells_in.duplicate()
	dir = dir_in
	_render_dir = dir_in
	_tint = tint


func _ready() -> void:
	_phase = randf() * TAU
	sync_pose()


func _process(_delta: float) -> void:
	queue_redraw()   # 呼吸/庆祝靠每帧重绘(矢量绘制,开销很小)


func length() -> int:
	return cells.size()


func head_cell() -> Vector2i:
	return cells[0]


func tail_cell() -> Vector2i:
	return cells[cells.size() - 1]


func set_tint(c: Color) -> void:
	_tint = c
	queue_redraw()


func center_pos() -> Vector2:
	var acc := Vector2.ZERO
	for c in cells:
		acc += main.cell_center(c)
	return acc / cells.size()


func hit_test(p: Vector2) -> bool:
	for c in cells:
		var r := Rect2(main.grid_origin + Vector2(c) * main.cell_size,
				Vector2.ONE * main.cell_size)
		if r.has_point(p):
			return true
	return false


func bounds_rect() -> Rect2:
	var mn := Vector2(cells[0])
	var mx := Vector2(cells[0])
	for c in cells:
		mn = mn.min(Vector2(c))
		mx = mx.max(Vector2(c))
	return Rect2(main.grid_origin + mn * main.cell_size,
			(mx - mn + Vector2.ONE) * main.cell_size)


# ---------- 姿态与动画 ----------

func _cells_to_pts(cs: Array) -> Array:
	var pts: Array = []
	for c in cs:
		pts.append(main.cell_center(c))
	return pts


func sync_pose() -> void:
	_render_pts = _cells_to_pts(cells)
	_render_dir = dir
	queue_redraw()


func tween_pose(dur: float) -> void:
	var start := _render_pts.duplicate()
	var target := _cells_to_pts(cells)
	_render_dir = dir
	var tw := create_tween()
	tw.tween_method(func(t: float) -> void:
		_lerp_pts(start, target, t), 0.0, 1.0, dur)\
		.set_trans(Tween.TRANS_QUAD).set_ease(Tween.EASE_OUT)


func slide_snapshots(snaps: Array, dur: float) -> void:
	## snaps = [[cells 数组, dir], ...] 每步一帧;整只猪沿折线平滑跟随。
	if snaps.is_empty():
		return
	var frames: Array = [_render_pts.duplicate()]
	var dirs: Array = [_render_dir]
	for snap in snaps:
		frames.append(_cells_to_pts(snap[0]))
		dirs.append(snap[1])
	var n := snaps.size()
	var tw := create_tween()
	tw.tween_method(func(t: float) -> void:
		_apply_frame(frames, dirs, t), 0.0, float(n), dur)\
		.set_trans(Tween.TRANS_LINEAR)
	await tw.finished
	sync_pose()


func _apply_frame(frames: Array, dirs: Array, t: float) -> void:
	var seg := int(floor(t))
	if seg >= frames.size() - 1:
		_render_pts = (frames[frames.size() - 1] as Array).duplicate()
		_render_dir = dirs[dirs.size() - 1]
	else:
		_lerp_pts(frames[seg], frames[seg + 1], t - seg)
		_render_dir = dirs[seg + 1]
	queue_redraw()


func _lerp_pts(a: Array, b: Array, f: float) -> void:
	var pts: Array = []
	for i in a.size():
		pts.append((a[i] as Vector2).lerp(b[i], f))
	_render_pts = pts
	queue_redraw()


func celebrate() -> void:
	var tw := create_tween().set_loops(3)
	tw.tween_property(self, "boost", 1.14, 0.15)
	tw.tween_property(self, "boost", 1.0, 0.15)


func flash() -> void:
	## 提示高亮:亮黄闪三下
	var skin: Color = main.meta_tint()
	var hot := Color(1.6, 1.5, 0.6)
	var tw := create_tween().set_loops(3)
	tw.tween_method(set_tint, skin, hot, 0.16)
	tw.tween_method(set_tint, hot, skin, 0.16)


func wiggle() -> void:
	if _wiggling:
		return
	_wiggling = true
	var tw := create_tween()
	tw.tween_property(self, "position", Vector2(dir) * 12.0, 0.08)
	tw.tween_property(self, "position", Vector2.ZERO, 0.14)
	await tw.finished
	_wiggling = false


# ---------- 绘制:一整只猪 ----------

func _draw() -> void:
	if _render_pts.is_empty() or main == null:
		return
	var cell: float = main.cell_size
	var breathe := 1.0 + 0.03 * sin(Time.get_ticks_msec() / 140.0 + _phase)
	var R := cell * 0.40 * boost * breathe

	var body := Color(1.0, 0.63, 0.72) * _tint
	var dark := Color(0.80, 0.42, 0.52) * _tint
	var belly := Color(1.0, 0.78, 0.85) * _tint

	var pts := _render_pts
	var face: Vector2 = Vector2(_render_dir)
	if pts.size() >= 2:
		face = (pts[0] - pts[1])
	if face.length() < 0.01:
		face = Vector2(_render_dir)
	face = face.normalized()
	var perp := Vector2(-face.y, face.x)

	# 后端小卷尾(长身才有),画在身体下面
	if pts.size() >= 2:
		var tail_back: Vector2 = (pts[pts.size() - 1] - pts[pts.size() - 2]).normalized()
		var troot: Vector2 = pts[pts.size() - 1] + tail_back * R * 0.7
		draw_arc(troot, R * 0.34, 0.0, TAU, 20, dark, R * 0.14, true)

	# 身体:深色描边胶囊 + 亮色胶囊 + 肚皮高光
	_draw_capsule(pts, R + 3.0, dark)
	_draw_capsule(pts, R, body)
	_draw_capsule(pts, R * 0.62, belly)

	var head: Vector2 = pts[0]

	# 耳朵(头后侧两只三角)
	for s in [1.0, -1.0]:
		var e0: Vector2 = head - face * R * 0.15 + perp * s * R * 0.5
		var tip: Vector2 = e0 + (perp * s * 0.5 - face * 0.2).normalized() * R * 0.7
		var w: Vector2 = face * R * 0.28
		draw_colored_polygon(PackedVector2Array([e0 - w, e0 + w, tip]), dark)

	# 吻部
	var snout: Vector2 = head + face * R * 0.5
	_draw_oval(snout, R * 0.5, R * 0.42, face.angle(), belly)
	for s in [1.0, -1.0]:
		draw_circle(snout + perp * s * R * 0.17 + face * R * 0.08, R * 0.07, dark)

	# 眼睛(白眼球 + 朝前的瞳孔)
	for s in [1.0, -1.0]:
		var eye: Vector2 = head + face * R * 0.02 + perp * s * R * 0.42
		draw_circle(eye, R * 0.2, Color.WHITE)
		draw_circle(eye + face * R * 0.06, R * 0.1, Color(0.15, 0.1, 0.12))


func _draw_capsule(pts: Array, r: float, col: Color) -> void:
	## 圆角胶囊 = 各点圆盘 ∪ 相邻点之间的矩形,直身成长条、弯身成圆弧。
	for p in pts:
		draw_circle(p, r, col)
	for i in range(pts.size() - 1):
		var a: Vector2 = pts[i]
		var b: Vector2 = pts[i + 1]
		var d: Vector2 = (b - a)
		if d.length() < 0.01:
			continue
		var n := Vector2(-d.y, d.x).normalized() * r
		draw_colored_polygon(PackedVector2Array([a + n, b + n, b - n, a - n]), col)


func _draw_oval(c: Vector2, a: float, b: float, ang: float, col: Color) -> void:
	var pts := PackedVector2Array()
	var ca := cos(ang)
	var sa := sin(ang)
	for i in 20:
		var t := TAU * i / 20.0
		var x := cos(t) * a
		var y := sin(t) * b
		pts.append(c + Vector2(x * ca - y * sa, x * sa + y * ca))
	draw_colored_polygon(pts, col)
