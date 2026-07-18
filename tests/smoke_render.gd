extends SceneTree
## 带渲染冒烟:真实输入事件走 悬停→点击 全链路(含 PreviewOverlay._draw)。
## 用法:Godot --path . -s res://tests/smoke_render.gd

func _init() -> void:
	call_deferred("_run")


func _run() -> void:
	var scene := load("res://main.tscn")
	var main = scene.instantiate()
	root.add_child(main)
	for i in 8:
		await process_frame

	var taps := 0
	for round in 3:
		var target = null
		for pig in main.pigs:
			if pig.visible and not main.game_over:
				target = pig
				break
		if target == null:
			break
		var pos: Vector2 = target.position
		var mm := InputEventMouseMotion.new()
		mm.position = pos
		Input.parse_input_event(mm)
		for i in 25:
			await process_frame
		var mb := InputEventMouseButton.new()
		mb.button_index = MOUSE_BUTTON_LEFT
		mb.pressed = true
		mb.position = pos
		Input.parse_input_event(mb)
		taps += 1
		for i in 60:
			await process_frame
	print("SMOKE_RENDER taps=", taps, " steps_left=", main.steps_left)
	print("SMOKE_RENDER_OK")
	quit(0)
