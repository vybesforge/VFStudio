extends Node2D
## Main scene: builds a floor in the TileMapLayer from code (no hand-edited tile data needed),
## counts coins, updates the HUD. Prints machine-readable lines for headless checks:
##   2D_READY tiles=N coins=N player=(x, y)
##   2D_FRAME on_floor=true pos=(x, y)        (after a few physics frames)
##   2D_COIN total=N                         (when a coin is picked up)
##   2D_SELFTEST OK frames=N coins=N          (only with `-- --selftest`: walks right into a coin)

const FLOOR_Y := 12          # tile row of the ground (16 px tiles -> y = 192 px)
const FLOOR_LEN := 60        # tiles wide

@onready var floor_layer: TileMapLayer = $Floor
@onready var hud_label: Label = $HUD/Label
@onready var player: CharacterBody2D = $Player

var coins := 0
var _frames := 0


func _ready() -> void:
	# Source 0 = tiles/tiles.png atlas; (0,0) grass, (1,0) dirt. Platforms at a few spots.
	for x in range(-5, FLOOR_LEN):
		floor_layer.set_cell(Vector2i(x, FLOOR_Y), 0, Vector2i(0, 0))
		floor_layer.set_cell(Vector2i(x, FLOOR_Y + 1), 0, Vector2i(1, 0))
	for x in range(14, 19):
		floor_layer.set_cell(Vector2i(x, FLOOR_Y - 4), 0, Vector2i(0, 0))
	for x in range(26, 30):
		floor_layer.set_cell(Vector2i(x, FLOOR_Y - 7), 0, Vector2i(0, 0))
	for c in get_tree().get_nodes_in_group("coins"):
		c.collected.connect(_on_coin_collected)
	_update_hud()
	print("2D_READY tiles=%d coins=%d player=%s" % [
		floor_layer.get_used_cells().size(), get_tree().get_nodes_in_group("coins").size(), player.position])


func _physics_process(_delta: float) -> void:
	_frames += 1
	if _frames == 3:
		print("2D_FRAME on_floor=%s pos=%s" % [player.is_on_floor(), player.position])
	# --selftest (after `--` on the command line): auto-run right until a coin is picked up.
	if "--selftest" in OS.get_cmdline_user_args():
		if _frames == 1:
			Input.action_press("ui_right")
		if coins > 0 or _frames > 300:
			print("2D_SELFTEST %s frames=%d coins=%d" % ["OK" if coins > 0 else "FAILED", _frames, coins])
			get_tree().quit(0 if coins > 0 else 1)


func _on_coin_collected() -> void:
	coins += 1
	_update_hud()
	print("2D_COIN total=%d" % coins)


func _update_hud() -> void:
	hud_label.text = "Coins: %d" % coins
