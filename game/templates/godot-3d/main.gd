extends Node3D
## Loads a GLB at runtime (first argument after `--`, default ~/media-stack/vr/pig.glb),
## scales it to TARGET_HEIGHT, stands it on the floor, and plays the first AnimationPlayer
## clip if the file has one. Machine-readable stdout for headless checks:
##   GLB_LOAD OK|FAILED <path>
##   GLB_INFO size_m=WxHxD scale=S tris=N
##   ANIM_PLAY <clip name> | ANIM_NONE
##   3D_FRAME on_floor=true pos=(x, y, z)

const DEFAULT_GLB := "~/media-stack/vr/pig.glb"
const TARGET_HEIGHT := 1.8
const MODEL_POS := Vector3(0, 0, -4)

@onready var model_root: Node3D = $Model
@onready var player: CharacterBody3D = $Player
@onready var hud: Label = $HUD/Label

var _frames := 0


func _ready() -> void:
	var path := _glb_path_from_args()
	var ok := load_glb(path)
	print("GLB_LOAD ", "OK " if ok else "FAILED ", path)
	if not ok:
		push_error("Could not load GLB: " + path)


func _physics_process(_delta: float) -> void:
	_frames += 1
	if _frames == 30:
		print("3D_FRAME on_floor=%s pos=%s" % [player.is_on_floor(), player.position])


func _glb_path_from_args() -> String:
	var path := DEFAULT_GLB
	for a in OS.get_cmdline_user_args():
		if a.begins_with("--glb="):
			path = a.trim_prefix("--glb=")
		elif not a.begins_with("--"):
			path = a
	return _expand_home(path)


func _expand_home(p: String) -> String:
	if p.begins_with("~/"):
		var home := OS.get_environment("HOME")
		if home.is_empty():
			home = OS.get_environment("USERPROFILE")
		return home.path_join(p.substr(2))
	return p


## Load a .glb/.gltf from an absolute path. Returns true on success.
func load_glb(path: String) -> bool:
	for c in model_root.get_children():
		c.queue_free()
	if not FileAccess.file_exists(path):
		push_error("GLB not found: " + path)
		return false
	var doc := GLTFDocument.new()
	var state := GLTFState.new()
	var err := doc.append_from_file(path, state)
	if err != OK:
		push_error("GLTFDocument.append_from_file failed (%d) for %s" % [err, path])
		return false
	var scene := doc.generate_scene(state)
	if scene == null:
		push_error("generate_scene returned null for " + path)
		return false
	model_root.add_child(scene)
	var aabb := _scene_aabb(scene)
	if aabb.size == Vector3.ZERO:
		push_error("GLB has no mesh geometry: " + path)
		return false
	var s := TARGET_HEIGHT / aabb.get_longest_axis_size()
	scene.scale = Vector3.ONE * s
	aabb = _scene_aabb(scene)
	var centre := aabb.get_center()
	scene.position = MODEL_POS + Vector3(-centre.x, -aabb.position.y, -centre.z)
	print("GLB_INFO size_m=%.2fx%.2fx%.2f scale=%.3f tris=%d" % [aabb.size.x, aabb.size.y, aabb.size.z, s, _scene_triangles(scene)])
	_play_first_animation(scene)
	hud.text = "GLB: %s" % path.get_file()
	return true


## Play the first clip of the first AnimationPlayer in the imported scene (looping).
func _play_first_animation(scene: Node) -> void:
	var players := scene.find_children("*", "AnimationPlayer", true, false)
	if scene is AnimationPlayer:
		players.push_front(scene)
	for ap in players:
		var names: PackedStringArray = ap.get_animation_list()
		if names.is_empty():
			continue
		var clip: String = names[0]
		ap.get_animation(clip).loop_mode = Animation.LOOP_LINEAR
		ap.play(clip)
		print("ANIM_PLAY ", clip, " (", names.size(), " clips)")
		return
	print("ANIM_NONE")


func _scene_aabb(root: Node) -> AABB:
	var result := AABB()
	var first := true
	for mi in root.find_children("*", "MeshInstance3D", true, false):
		if mi.mesh == null:
			continue
		var xf: Transform3D = model_root.global_transform.affine_inverse() * mi.global_transform
		var box: AABB = xf * mi.mesh.get_aabb()
		result = box if first else result.merge(box)
		first = false
	return result


func _scene_triangles(root: Node) -> int:
	var total := 0
	for mi in root.find_children("*", "MeshInstance3D", true, false):
		var m: Mesh = mi.mesh
		if m == null:
			continue
		for i in m.get_surface_count():
			var arrays := m.surface_get_arrays(i)
			var idx = arrays[Mesh.ARRAY_INDEX]
			total += (idx.size() if idx != null and idx.size() > 0 else arrays[Mesh.ARRAY_VERTEX].size()) / 3
	return total
