extends SceneTree
## 无头冒烟测试:加载主场景,模拟点击每个可点的猪,捕获运行时报错。
## 用法:Godot --headless --path . -s res://tests/smoke_tap.gd

func _init() -> void:
	call_deferred("_run")


func _run() -> void:
	var scene := load("res://main.tscn")
	var main = scene.instantiate()
	root.add_child(main)
	await process_frame
	await process_frame
	print("SMOKE: level=", main.level_index + 1, " pigs=", main.pigs.size(),
			" queues=", main.queues.size())
	var taps := 0
	for pig in main.pigs:
		if pig.visible and not main.game_over:
			main._tap_pig(pig)
			taps += 1
			for i in 30:
				await process_frame
			if taps >= 3:
				break
	print("SMOKE: taps=", taps, " steps_left=", main.steps_left,
			" game_over=", main.game_over)
	print("SMOKE_TAP_OK")
	quit(0)
