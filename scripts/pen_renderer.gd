extends Node2D
## 绘制猪圈:地板、栅栏、开口处向外斜开的门板、桩子。
## 尺寸随主场景的 cell_size 缩放。

var main: Node2D


func setup(m: Node2D) -> void:
	main = m


func _draw() -> void:
	if main == null:
		return
	var cell: float = main.cell_size
	var s: float = cell / 150.0

	# 地板
	for c in main.pen_cells:
		var pos: Vector2 = main.grid_origin + Vector2(c) * cell
		var shade := Color("#f7d84b") if (c.x + c.y) % 2 == 0 else Color("#f2cd35")
		draw_rect(Rect2(pos + Vector2(3, 3) * s, Vector2(cell, cell) - Vector2(6, 6) * s), shade)
		draw_rect(Rect2(pos + Vector2(3, 3) * s, Vector2(cell, cell) - Vector2(6, 6) * s),
				Color("#d9b427"), false, 3.0 * s)

	# 改向箭头：铺在格子中央，不遮挡猪圈边界。
	for c in main.redirects:
		_draw_redirect(c, main.redirects[c], s)

	# 泥坑：猪头进坑当场停下，再点一次继续走。
	for c in main.muds:
		_draw_mud(c, s)

	var posts := {}

	# 栅栏
	for w in main.wall_list:
		var pts := _edge_points(w[0], w[1])
		_draw_bar(pts[0], pts[1], s)
		posts[pts[0]] = true
		posts[pts[1]] = true

	# 开口:两根向外斜开的门板
	for o in main.openings:
		var pts := _edge_points(o[0], o[1])
		var out := Vector2(o[1])
		var along: Vector2 = (pts[1] - pts[0]).normalized()
		_draw_bar(pts[0], pts[0] + (out - along).normalized() * 66.0 * s, s)
		_draw_bar(pts[1], pts[1] + (out + along).normalized() * 66.0 * s, s)
		posts[pts[0]] = true
		posts[pts[1]] = true

	# 桩子
	for p in posts:
		draw_rect(Rect2(p - Vector2(14, 14) * s, Vector2(28, 28) * s), Color("#8f4d15"))
		draw_rect(Rect2(p - Vector2(10, 10) * s, Vector2(20, 20) * s), Color("#d97a2c"))


func _edge_points(c: Vector2i, d: Vector2i) -> Array:
	var cell: float = main.cell_size
	var base: Vector2 = main.grid_origin + Vector2(c) * cell
	if d == Vector2i(1, 0):
		return [base + Vector2(cell, 0), base + Vector2(cell, cell)]
	if d == Vector2i(-1, 0):
		return [base, base + Vector2(0, cell)]
	if d == Vector2i(0, 1):
		return [base + Vector2(0, cell), base + Vector2(cell, cell)]
	return [base, base + Vector2(cell, 0)]


func _draw_bar(a: Vector2, b: Vector2, s: float) -> void:
	draw_line(a, b, Color("#8f4d15"), 24.0 * s)
	draw_line(a, b, Color("#e0862d"), 15.0 * s)


func _draw_mud(c: Vector2i, s: float) -> void:
	var center: Vector2 = main.cell_center(c)
	draw_colored_polygon(_ellipse(center, 56.0 * s, 42.0 * s), Color("#8a5a2b"))
	draw_colored_polygon(_ellipse(center + Vector2(0, 3) * s, 42.0 * s, 30.0 * s),
			Color("#6e4620"))
	for off in [Vector2(-18, -8), Vector2(14, -14), Vector2(4, 12)]:
		draw_circle(center + off * s, 5.5 * s, Color("#a9743c"))


func _ellipse(center: Vector2, rx: float, ry: float) -> PackedVector2Array:
	var pts := PackedVector2Array()
	for i in 22:
		var a := TAU * i / 22.0
		pts.append(center + Vector2(cos(a) * rx, sin(a) * ry))
	return pts


func _draw_redirect(c: Vector2i, d: Vector2i, s: float) -> void:
	var center: Vector2 = main.cell_center(c)
	var forward := Vector2(d).normalized()
	var side := Vector2(-forward.y, forward.x)
	var tip := center + forward * 48.0 * s
	var neck := center + forward * 9.0 * s
	var back := center - forward * 42.0 * s
	var pts := PackedVector2Array([
		tip, neck + side * 34.0 * s, neck + side * 15.0 * s,
		back + side * 15.0 * s, back - side * 15.0 * s,
		neck - side * 15.0 * s, neck - side * 34.0 * s,
	])
	draw_colored_polygon(pts, Color("#2f9fb3"))
	var outline := pts.duplicate()
	outline.append(pts[0])
	draw_polyline(outline, Color("#176170"), 5.0 * s, true)

