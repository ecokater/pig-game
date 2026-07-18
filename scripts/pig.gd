extends Node2D
## 小猪棋子:1/2/3 格分节身体(头段 + 身段),头在前。
## 过箭头会弯身:每个身段跟随头走过的路径。负责动画与点击区域。
## 节点自身始终停在原点,身段子精灵直接摆在各自格子的世界坐标上;
## wiggle 通过临时偏移节点整体实现。

const HEAD_TEX := preload("res://art/pig_head.svg")
const BODY_TEX := preload("res://art/pig_body.svg")

var main: Node2D
var cells: Array = []      # Vector2i,头在前
var dir: Vector2i
var entered := false       # 已离开等待队列(进圈或跨在开口上)
var qi := -1               # 所属开口队列下标
var boost := 1.0           # 庆祝等外部缩放系数(呼吸动画每帧会覆盖 scale)

var _phase := 0.0
var _wiggling := false
var _segs: Array = []      # Sprite2D,与 cells 一一对应(0 = 头)


func setup(m: Node2D, cells_in: Array, dir_in: Vector2i, tint: Color) -> void:
	main = m
	cells = cells_in.duplicate()
	dir = dir_in
	for i in cells.size():
		var spr := Sprite2D.new()
		spr.texture = HEAD_TEX if i == 0 else BODY_TEX
		spr.modulate = tint
		add_child(spr)
		_segs.append(spr)


func _ready() -> void:
	_phase = randf() * TAU
	sync_pose()


func _process(_delta: float) -> void:
	var s: float = main.cell_size / 150.0 * 1.06 * boost \
			* (1.0 + 0.025 * sin(Time.get_ticks_msec() / 140.0 + _phase))
	for spr in _segs:
		spr.scale = Vector2.ONE * s


func length() -> int:
	return cells.size()


func head_cell() -> Vector2i:
	return cells[0]


func tail_cell() -> Vector2i:
	return cells[cells.size() - 1]


func set_tint(c: Color) -> void:
	for spr in _segs:
		spr.modulate = c


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


func _seg_rot(i: int, cs: Array, d: Vector2i) -> float:
	## 头段朝移动方向,身段朝向前一节
	var toward: Vector2i = d if i == 0 else cs[i - 1] - cs[i]
	return Vector2(toward).angle() + PI / 2.0


func sync_pose() -> void:
	for i in _segs.size():
		_segs[i].position = main.cell_center(cells[i])
		_segs[i].rotation = _seg_rot(i, cells, dir)


func tween_pose(dur: float) -> void:
	for i in _segs.size():
		var tw := create_tween()
		tw.tween_property(_segs[i], "position", main.cell_center(cells[i]), dur)\
			.set_trans(Tween.TRANS_QUAD).set_ease(Tween.EASE_OUT)
		_segs[i].rotation = _seg_rot(i, cells, dir)


func slide_snapshots(snaps: Array, dur: float) -> void:
	## snaps = [[cells 数组, dir], ...] 每一步一帧;分节沿折线跟随,
	## 头段转向时旋转,身段各自朝向前一节。
	if snaps.is_empty():
		return
	var part: float = dur / snaps.size()
	var tw := create_tween()
	for snap in snaps:
		var cs: Array = snap[0]
		var d: Vector2i = snap[1]
		tw.tween_property(_segs[0], "position", main.cell_center(cs[0]), part)\
			.set_trans(Tween.TRANS_LINEAR)
		tw.parallel().tween_property(_segs[0], "rotation",
				_seg_rot(0, cs, d), part * 0.7)
		for i in range(1, _segs.size()):
			tw.parallel().tween_property(_segs[i], "position",
					main.cell_center(cs[i]), part).set_trans(Tween.TRANS_LINEAR)
			tw.parallel().tween_property(_segs[i], "rotation",
					_seg_rot(i, cs, d), part * 0.7)
	await tw.finished
	sync_pose()


func celebrate() -> void:
	## 过关欢呼:整体弹跳缩放(经 boost,与呼吸动画兼容)
	var tw := create_tween().set_loops(3)
	tw.tween_property(self, "boost", 1.14, 0.15)
	tw.tween_property(self, "boost", 1.0, 0.15)


func flash() -> void:
	## 提示高亮:亮黄闪三下
	var tint: Color = main.meta_tint()
	var hot := Color(1.6, 1.5, 0.6)
	var tw := create_tween().set_loops(3)
	tw.tween_method(_set_seg_color, tint, hot, 0.16)
	tw.tween_method(_set_seg_color, hot, tint, 0.16)


func _set_seg_color(c: Color) -> void:
	for spr in _segs:
		spr.modulate = c


func wiggle() -> void:
	if _wiggling:
		return
	_wiggling = true
	var tw := create_tween()
	tw.tween_property(self, "position", Vector2(dir) * 12.0, 0.08)
	tw.tween_property(self, "position", Vector2.ZERO, 0.14)
	await tw.finished
	_wiggling = false
