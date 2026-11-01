extends Node3D
## VR Godot Room: starts OpenXR (falls back to a desktop free-fly camera),
## loads a GLB at runtime, fits it to TARGET_HEIGHT and stands it on the floor.
##
## GLB path = first argument after `--` on the command line, e.g.
##   Godot --path . -- /abs/path/model.glb      (or  -- --glb=/abs/path/model.glb)
## Default: ~/media-stack/vr/pig.glb

const DEFAULT_GLB := "~/media-stack/vr/pig.glb"
const TARGET_HEIGHT := 1.8        # metres: longest axis of the model is scaled to this
const MODEL_DISTANCE := 2.0       # metres in front of the XR origin (-Z)

@onready var xr_origin: XROrigin3D = $XROrigin3D
@onready var xr_camera: XRCamera3D = $XROrigin3D/XRCamera3D
@onready var desktop_cam: Camera3D = $DesktopCamera
@onready var model_root: Node3D = $Model

var xr_interface: XRInterface


func _ready() -> void:
	_setup_xr()
	var path := _glb_path_from_args()
	var ok := load_glb(path)
	print("GLB_LOAD ", "OK " if ok else "FAILED ", path)
	if not ok:
		push_error("Could not load GLB: " + path)


func _setup_xr() -> void:
	xr_interface = XRServer.find_interface("OpenXR")
	if xr_interface and not xr_interface.is_initialized():
		xr_interface.initialize()
	if xr_interface and xr_interface.is_initialized():
		get_viewport().use_xr = true
		DisplayServer.window_set_vsync_mode(DisplayServer.VSYNC_DISABLED)
		xr_camera.current = true
		print("XR_MODE openxr")
	else:
		print("XR_MODE desktop_fallback")
		desktop_cam.activate()


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


## Load a .glb/.gltf from an absolute filesystem path, fit and place it. Returns true on success.
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
	var longest := aabb.get_longest_axis_size()
	var s := TARGET_HEIGHT / longest
	scene.scale = Vector3.ONE * s
	# Re-measure after scaling, then put the bottom on y=0 and centre on x/z.
	aabb = _scene_aabb(scene)
	var centre := aabb.get_center()
	scene.position = Vector3(-centre.x, -aabb.position.y, -centre.z - MODEL_DISTANCE)
	var tris := _scene_triangles(scene)
	print("GLB_INFO size_m=%.2fx%.2fx%.2f scale=%.3f tris=%d" % [aabb.size.x, aabb.size.y, aabb.size.z, s, tris])
	return true


## World-space AABB of all MeshInstance3D under `root` (relative to model_root).
func _scene_aabb(root: Node) -> AABB:
	var result := AABB()
	var first := true
	for mi in root.find_children("*", "MeshInstance3D", true, false):
		if mi.mesh == null:
			continue
		var xf: Transform3D = model_root.global_transform.affine_inverse() * mi.global_transform
		var box: AABB = xf * mi.mesh.get_aabb()
		if first:
			result = box
			first = false
		else:
			result = result.merge(box)
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
			if idx != null and idx.size() > 0:
				total += idx.size() / 3
			else:
				total += arrays[Mesh.ARRAY_VERTEX].size() / 3
	return total
