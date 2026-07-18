extends SceneTree
## 无头性能冒烟:测决赛段关卡的 死局检测 / 提示求解 耗时,以及选关面板构建。
## 用法:Godot --headless --path . -s res://tests/smoke_perf.gd

func _init() -> void:
	call_deferred("_run")


func _run() -> void:
	for lv in [120, 500, 900, 987, 995, 1000]:
		var main_script := load("res://scripts/main.gd")
		main_script.level_index = lv - 1
		main_script.progress_applied = true
		var scene := load("res://main.tscn")
		var main = scene.instantiate()
		root.add_child(main)
		await process_frame
		await process_frame

		var t0 := Time.get_ticks_msec()
		var seq = main._solve_from_current(main.DOOM_BUDGET)
		var doom_ms := Time.get_ticks_msec() - t0
		var doom_state := "解" if seq != null else ("超限" if main._dfs_overflow else "死")

		t0 = Time.get_ticks_msec()
		seq = main._solve_from_current(main.HINT_BUDGET)
		var hint_ms := Time.get_ticks_msec() - t0
		var hint_state := "解" if seq != null else ("超限" if main._dfs_overflow else "死")

		t0 = Time.get_ticks_msec()
		main._toggle_select()
		await process_frame
		var sel_ms := Time.get_ticks_msec() - t0

		print("L%04d doom=%dms(%s) hint=%dms(%s) select=%dms" % [
			lv, doom_ms, doom_state, hint_ms, hint_state, sel_ms])
		root.remove_child(main)
		main.free()
	print("SMOKE_PERF_OK")
	quit(0)
