extends CharacterBody2D
## Platformer controller. Arrow keys / WASD move, Space / W / Up jumps.
## Plays "idle" / "run" from the SpriteFrames (player/player_frames.tres), flips to face movement.

const SPEED := 160.0
const JUMP_VELOCITY := -420.0

@onready var sprite: AnimatedSprite2D = $AnimatedSprite2D


func _ready() -> void:
	_add_key("ui_left", KEY_A)
	_add_key("ui_right", KEY_D)
	_add_key("ui_accept", KEY_W)
	_add_key("ui_accept", KEY_UP)
	sprite.play("idle")


func _add_key(action: String, key: Key) -> void:
	var ev := InputEventKey.new()
	ev.physical_keycode = key
	InputMap.action_add_event(action, ev)


func _physics_process(delta: float) -> void:
	if not is_on_floor():
		velocity += get_gravity() * delta
	if Input.is_action_just_pressed("ui_accept") and is_on_floor():
		velocity.y = JUMP_VELOCITY
	var dir := Input.get_axis("ui_left", "ui_right")
	velocity.x = dir * SPEED if dir != 0.0 else move_toward(velocity.x, 0.0, SPEED)
	move_and_slide()
	# animation
	if dir != 0.0:
		sprite.flip_h = dir < 0.0
		if sprite.animation != "run":
			sprite.play("run")
	elif sprite.animation != "idle":
		sprite.play("idle")
