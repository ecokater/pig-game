extends SceneTree
## 压力冒烟:后台求解进行中连续快速点击/撤销,复现并守护线程竞争。
## 原始崩溃:求解线程读活猪节点,主线程同时改 entered → -1 下标。
## 用法:Godot --headless --path . -s res://tests/smoke_stress.gd

func _init() -> void:
	call_deferred("_run")


func _run() -> void:
	var main_script := load("res://scripts/main.gd")
	main_script.level_index = 986   # L987:死局检测最重的关卡之一
	main_script.progress_applied = true
	var scene := load("res://main.tscn")
	var main = scene.instantiate()
	root.add_child(main)
	await process_frame
	await process_frame

	var meta = root.get_node("Meta")
	meta.boosters["undo"] += 20   # 压测自补,不动玩家库存

	# 连续 10 次:点一头猪 → 只等动画帧,不等求解线程 → 立刻再点
	var taps := 0
	for round in 10:
		if main.game_over:
			break
		var target = null
		for pig in main.pigs:
			if pig.visible and not pig.entered:
				target = pig
				break
		if target == null:
			break
		main._tap_pig(target)
		taps += 1
		for i in 12:
			await process_frame
		# 隔一次做一次撤销,进一步搅动 entered 状态
		if round % 2 == 1 and not main.game_over:
			main._do_undo()
			for i in 6:
				await process_frame

	# 等后台求解排空
	var waited := 0
	while main._solver_busy() and waited < 3000:
		await process_frame
		waited += 1
	print("SMOKE_STRESS taps=", taps, " solver_drained=",
			not main._solver_busy(), " game_over=", main.game_over)
	print("SMOKE_STRESS_OK")
	quit(0)
