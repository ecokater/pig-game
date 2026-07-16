extends Node2D
## 小猪棋子:占两格(尾格+头格),朝向固定;负责动画与点击区域。

var main: Node2D
var tail: Vector2i
var head: Vector2i
var dir: Vector2i
var entered := false   # 已离开等待队列(进圈或跨在开口上)
var qi := -1           # 所属开口队列下标

var _base_scale := 1.06
var _phase := 0.0
var _wiggling := false

@onready var _sprite: Sprite2D = get_node("Sprite")


func _ready() -> void:
	_phase = randf() * TAU
	_base_scale = main.cell_size / 150.0 * 1.06
	rotation = Vector2(dir).angle() + PI / 2.0
	position = center_pos()


func _process(_delta: float) -> void:
	_sprite.scale = Vector2.ONE * _base_scale \
			* (1.0 + 0.025 * sin(Time.get_ticks_msec() / 140.0 + _phase))


func center_pos() -> Vector2:
	return (main.cell_center(tail) + main.cell_center(head)) / 2.0


func hit_rect() -> Rect2:
	var mn := Vector2(mini(tail.x, head.x), mini(tail.y, head.y))
	var sz := Vector2(absi(head.x - tail.x) + 1, absi(head.y - tail.y) + 1)
	return Rect2(main.grid_origin + mn * main.cell_size, sz * main.cell_size)


func slide_to_cells(dur: float) -> void:
	var tw := create_tween()
	tw.tween_property(self, "position", center_pos(), dur)\
		.set_trans(Tween.TRANS_QUAD).set_ease(Tween.EASE_OUT)
	await tw.finished


func flash() -> void:
	## 提示高亮:亮黄闪三下
	var tw := create_tween().set_loops(3)
	tw.tween_property(_sprite, "modulate", Color(1.6, 1.5, 0.6), 0.16)
	tw.tween_property(_sprite, "modulate", main.meta_tint(), 0.16)


func wiggle() -> void:
	if _wiggling:
		return
	_wiggling = true
	var base := position
	var tw := create_tween()
	tw.tween_property(self, "position", base + Vector2(dir) * 12.0, 0.08)
	tw.tween_property(self, "position", base, 0.14)
	await tw.finished
	_wiggling = false
