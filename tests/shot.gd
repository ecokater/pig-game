extends SceneTree
## 渲染一个含长猪的关卡并截图,用于人工核对猪的外观。
## Godot --path . -s res://tests/shot.gd

func _init() -> void:
	call_deferred("_run")


func _run() -> void:
	var idx := 700
	if OS.get_cmdline_user_args().size() > 0:
		idx = int(OS.get_cmdline_user_args()[0])
	var ms := load("res://scripts/main.gd")
	ms.level_index = idx
	ms.progress_applied = true
	var main = load("res://main.tscn").instantiate()
	root.add_child(main)
	for i in 20:
		await process_frame
	var img := root.get_viewport().get_texture().get_image()
	img.save_png("/tmp/pig_shot_%d.png" % (idx + 1))
	print("SHOT L%d pigs=%d saved" % [idx + 1, main.pigs.size()])
	quit(0)
