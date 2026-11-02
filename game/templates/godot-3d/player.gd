extends CharacterBody3D
## First/third-person controller. WASD move, Space jump, mouse look (click to capture, Esc to
## release), V toggles first <-> third person, Shift = run.

const SPEED := 4.0
const RUN_SPEED := 8.0
const JUMP_VELOCITY := 5.0
const MOUSE_SENS := 0.0025

@onready var head: Node3D = $Head
@onready var cam_fp: Camera3D = $Head/CameraFP
@onready var arm: SpringArm3D = $Head/SpringArm3D
@onready var cam_tp: Camera3D = $Head/SpringArm3D/CameraTP

var third_person := false


func _ready() -> void:
	for pair in [["move_left", KEY_A], ["move_right", KEY_D], ["move_forward", KEY_W],
			["move_back", KEY_S], ["jump", KEY_SPACE], ["toggle_view", KEY_V], ["run", KEY_SHIFT]]:
		if not InputMap.has_action(pair[0]):
			InputMap.add_action(pair[0])
		var ev := InputEventKey.new()
		ev.physical_keycode = pair[1]
		InputMap.action_add_event(pair[0], ev)
	_apply_view()


func _unhandled_input(event: InputEvent) -> void:
	if event is InputEventMouseButton and event.pressed:
		Input.mouse_mode = Input.MOUSE_MODE_CAPTURED
	elif event.is_action_pressed("ui_cancel"):
		Input.mouse_mode = Input.MOUSE_MODE_VISIBLE
	elif event is InputEventMouseMotion and Input.mouse_mode == Input.MOUSE_MODE_CAPTURED:
		rotate_y(-event.relative.x * MOUSE_SENS)
		head.rotation.x = clamp(head.rotation.x - event.relative.y * MOUSE_SENS, -1.3, 1.3)
	elif event.is_action_pressed("toggle_view"):
		third_person = not third_person
		_apply_view()


func _apply_view() -> void:
	cam_fp.current = not third_person
	cam_tp.current = third_person


func _physics_process(delta: float) -> void:
	if not is_on_floor():
		velocity += get_gravity() * delta
	if Input.is_action_just_pressed("jump") and is_on_floor():
		velocity.y = JUMP_VELOCITY
	var input := Input.get_vector("move_left", "move_right", "move_forward", "move_back")
	var dir := (transform.basis * Vector3(input.x, 0, input.y)).normalized()
	var speed := RUN_SPEED if Input.is_action_pressed("run") else SPEED
	if dir != Vector3.ZERO:
		velocity.x = dir.x * speed
		velocity.z = dir.z * speed
	else:
		velocity.x = move_toward(velocity.x, 0, speed)
		velocity.z = move_toward(velocity.z, 0, speed)
	move_and_slide()
