extends Node
## Meta 单例:游戏外围系统的全部状态与存档。
## 体系参照休闲解谜的成熟做法(Royal Match / Candy Crush / 梦幻花园):
##   红心体力 · 金币 · 三星评级 · 连胜 · 道具(撤销/提示/加步) · 皮肤收集 · 每日奖励

const CFG := "user://meta.cfg"

const MAX_HEARTS := 5
const HEART_REGEN_SEC := 30 * 60
## 测试开关:true 时红心照常扣减显示,但不阻塞游玩。发布前改回 false。
const FREE_HEARTS := true

## 道具没有库存时用金币购买的单价
const BOOSTER_PRICE := {"undo": 100, "hint": 150, "steps": 300}
const CONTINUE_PRICE := 300   # 步数耗尽时 +2 步续关
const DAILY_COINS := 200

const SKINS := {
	"pink":  {"name": "粉红小猪", "price": 0,    "tint": Color(1.0, 1.0, 1.0)},
	"mint":  {"name": "薄荷小猪", "price": 800,  "tint": Color(0.72, 1.05, 0.85)},
	"lilac": {"name": "丁香小猪", "price": 800,  "tint": Color(0.9, 0.82, 1.1)},
	"gold":  {"name": "黄金小猪", "price": 1500, "tint": Color(1.15, 0.98, 0.5)},
	"ash":   {"name": "乌黑小猪", "price": 2000, "tint": Color(0.5, 0.46, 0.55)},
}

var coins := 600
var hearts := MAX_HEARTS
var heart_ts := 0          # 开始回复第一颗心的 unix 秒
var streak := 0
var best_streak := 0
var stars := {}            # "关序号" -> 1..3
var boosters := {"undo": 3, "hint": 3, "steps": 1}
var owned_skins: Array = ["pink"]
var skin := "pink"
var last_daily := ""
var daily_pending := false


func _ready() -> void:
	_load()
	tick_hearts()
	var today := Time.get_date_string_from_system()
	if last_daily != today:
		last_daily = today
		daily_pending = true
		save()


# ---------- 红心 ----------

func tick_hearts() -> void:
	## 按离线时间补回红心
	var now := int(Time.get_unix_time_from_system())
	while hearts < MAX_HEARTS and now - heart_ts >= HEART_REGEN_SEC:
		hearts += 1
		heart_ts += HEART_REGEN_SEC
	if hearts >= MAX_HEARTS:
		heart_ts = now


func can_play() -> bool:
	tick_hearts()
	return FREE_HEARTS or hearts > 0


func lose_heart() -> void:
	tick_hearts()
	if hearts >= MAX_HEARTS:
		heart_ts = int(Time.get_unix_time_from_system())
	hearts = maxi(hearts - 1, 0)
	save()


func heart_wait_text() -> String:
	tick_hearts()
	if hearts >= MAX_HEARTS:
		return ""
	var left := HEART_REGEN_SEC - (int(Time.get_unix_time_from_system()) - heart_ts)
	return "%d:%02d" % [left / 60, left % 60]


# ---------- 金币与道具 ----------

func try_spend(n: int) -> bool:
	if coins < n:
		return false
	coins -= n
	save()
	return true


func add_coins(n: int) -> void:
	coins += n
	save()


func use_booster(kind: String) -> bool:
	## 有库存扣库存,否则尝试金币购买;成功返回 true
	if boosters.get(kind, 0) > 0:
		boosters[kind] -= 1
		save()
		return true
	if try_spend(BOOSTER_PRICE[kind]):
		return true
	return false


func booster_label(kind: String) -> String:
	var cnt: int = boosters.get(kind, 0)
	return "×%d" % cnt if cnt > 0 else "%d🪙" % BOOSTER_PRICE[kind]


# ---------- 胜负结算 ----------

func record_win(level: int, star_cnt: int) -> Dictionary:
	## 返回 {coins, streak, bonus_booster}:金币 = 基础 + 星级 + 连胜加成;
	## 连胜到 3/5/10 额外送随机道具(Royal Match 式连胜激励)
	streak += 1
	best_streak = maxi(best_streak, streak)
	var reward := 30 + 20 * star_cnt + 10 * mini(streak - 1, 5)
	coins += reward
	var key := str(level)
	stars[key] = maxi(int(stars.get(key, 0)), star_cnt)
	var bonus := ""
	if streak in [3, 5, 10]:
		var kinds := ["undo", "hint", "steps"]
		bonus = kinds[randi() % kinds.size()]
		boosters[bonus] += 1
	save()
	return {"coins": reward, "streak": streak, "bonus_booster": bonus}


func record_fail() -> void:
	streak = 0
	lose_heart()


func level_stars(level: int) -> int:
	return int(stars.get(str(level), 0))


func total_stars() -> int:
	var t := 0
	for k in stars:
		t += int(stars[k])
	return t


# ---------- 每日奖励 ----------

func claim_daily() -> int:
	## 领取每日奖励,返回金币数(顺带送 1 个提示)
	daily_pending = false
	coins += DAILY_COINS
	boosters["hint"] += 1
	save()
	return DAILY_COINS


# ---------- 皮肤 ----------

func buy_skin(id: String) -> bool:
	if owned_skins.has(id):
		return true
	if not try_spend(int(SKINS[id]["price"])):
		return false
	owned_skins.append(id)
	save()
	return true


func select_skin(id: String) -> void:
	if owned_skins.has(id):
		skin = id
		save()


func skin_tint() -> Color:
	return SKINS[skin]["tint"]


# ---------- 存档 ----------

func save() -> void:
	var cfg := ConfigFile.new()
	cfg.set_value("meta", "coins", coins)
	cfg.set_value("meta", "hearts", hearts)
	cfg.set_value("meta", "heart_ts", heart_ts)
	cfg.set_value("meta", "streak", streak)
	cfg.set_value("meta", "best_streak", best_streak)
	cfg.set_value("meta", "stars", stars)
	cfg.set_value("meta", "boosters", boosters)
	cfg.set_value("meta", "owned_skins", owned_skins)
	cfg.set_value("meta", "skin", skin)
	cfg.set_value("meta", "last_daily", last_daily)
	cfg.save(CFG)


func _load() -> void:
	var cfg := ConfigFile.new()
	if cfg.load(CFG) != OK:
		heart_ts = int(Time.get_unix_time_from_system())
		return
	coins = int(cfg.get_value("meta", "coins", coins))
	hearts = int(cfg.get_value("meta", "hearts", hearts))
	heart_ts = int(cfg.get_value("meta", "heart_ts",
			int(Time.get_unix_time_from_system())))
	streak = int(cfg.get_value("meta", "streak", 0))
	best_streak = int(cfg.get_value("meta", "best_streak", 0))
	stars = cfg.get_value("meta", "stars", {})
	boosters = cfg.get_value("meta", "boosters", boosters)
	owned_skins = cfg.get_value("meta", "owned_skins", owned_skins)
	skin = str(cfg.get_value("meta", "skin", "pink"))
	last_daily = str(cfg.get_value("meta", "last_daily", ""))
