extends Camera3D
## Desktop fallback: free-fly camera. WASD/QE move, hold right mouse to look,
## Shift = faster. Only active when main.gd could not start OpenXR.

var speed := 2.0
var look_sens := 0.003
var _yaw := 0.0
var _pitch := 0.0

func _ready() -> void:
	_yaw = rotation.y
	_pitch = rotation.x
	set_process(false)

func activate() -> void:
	current = true
	set_process(true)

func _unhandled_input(event: InputEvent) -> void:
	if not is_processing():
		return
	if event is InputEventMouseButton and event.button_index == MOUSE_BUTTON_RIGHT:
		Input.mouse_mode = Input.MOUSE_MODE_CAPTURED if event.pressed else Input.MOUSE_MODE_VISIBLE
	elif event is InputEventMouseMotion and Input.mouse_mode == Input.MOUSE_MODE_CAPTURED:
		_yaw -= event.relative.x * look_sens
		_pitch = clamp(_pitch - event.relative.y * look_sens, -1.5, 1.5)
		rotation = Vector3(_pitch, _yaw, 0.0)

func _process(delta: float) -> void:
	var dir := Vector3.ZERO
	if Input.is_physical_key_pressed(KEY_W): dir.z -= 1.0
	if Input.is_physical_key_pressed(KEY_S): dir.z += 1.0
	if Input.is_physical_key_pressed(KEY_A): dir.x -= 1.0
	if Input.is_physical_key_pressed(KEY_D): dir.x += 1.0
	if Input.is_physical_key_pressed(KEY_E): dir.y += 1.0
	if Input.is_physical_key_pressed(KEY_Q): dir.y -= 1.0
	var s := speed * (3.0 if Input.is_physical_key_pressed(KEY_SHIFT) else 1.0)
	if dir != Vector3.ZERO:
		translate_object_local(dir.normalized() * s * delta)
