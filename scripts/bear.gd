extends Node2D
## 熊:平时在指定角落游荡(纯装饰),失败时由主场景驱动扑向小猪。

var region := Rect2(820, 920, 180, 290)
var chasing := false

var _target := Vector2.ZERO
var _speed := 55.0


func _ready() -> void:
	_pick_target()


func _pick_target() -> void:
	_target = Vector2(
		randf_range(region.position.x, region.end.x),
		randf_range(region.position.y, region.end.y))


func _process(delta: float) -> void:
	if chasing:
		return
	var d := _target - position
	if d.length() < 10.0:
		_pick_target()
		return
	position += d.normalized() * _speed * delta
	rotation = lerp_angle(rotation, d.angle() + PI / 2.0, 4.0 * delta)
