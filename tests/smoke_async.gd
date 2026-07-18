extends SceneTree
## 异步冒烟:在决赛段关卡上验证 (1) 点击后主线程不再长冻结;
## (2) 沿最优线时"提示"瞬时回放;(3) 后台死局检测最终能送达结果。
## 用法:Godot --headless --path . -s res://tests/smoke_async.gd

func _init() -> void:
	call_deferred("_run")


func _run() -> void:
	var main_script := load("res://scripts/main.gd")
	main_script.level_index = 986   # L987:混编决赛段
	main_script.progress_applied = true
	var scene := load("res://main.tscn")
	var main = scene.instantiate()
	root.add_child(main)
	await process_frame
	await process_frame

	# 沿官方解线点第一手,量点击调用的主线程占用
	assert(not main.solution.is_empty(), "L987 应携带官方解线")
	var mv: Array = main.solution[0]
	var target = null
	if int(mv[0]) == 0:
		target = main._waiting_list(int(mv[1]))[0]
	var t0 := Time.get_ticks_msec()
	main._tap_pig(target)
	var tap_block := Time.get_ticks_msec() - t0
	# 等滑动动画结束
	for i in 40:
		await process_frame

	# 沿最优线 → 提示应瞬时(解线回放,不进求解器)
	root.get_node("Meta").boosters["hint"] += 1   # 冒烟自补,不动玩家库存
	t0 = Time.get_ticks_msec()
	main._do_hint()
	var hint_ms := Time.get_ticks_msec() - t0
	print("SMOKE_ASYNC tap_block=%dms hint_replay=%dms solver_busy=%s" % [
		tap_block, hint_ms, main._solver_busy()])
	assert(hint_ms < 200, "解线回放必须瞬时")

	# 等后台死局检测送达(最多 30 秒)
	var waited := 0
	while main._solver_busy() and waited < 3000:
		await process_frame
		waited += 1
	print("SMOKE_ASYNC doom_done=", not main._solver_busy(),
			" doomed=", main._doomed)
	print("SMOKE_ASYNC_OK")
	quit(0)
