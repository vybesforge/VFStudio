"""Re-UV, re-project and re-bake a GLB so it survives VR.

Fixes the real defect in ComfyUI's output: Hunyuan's unwrap produced ~70k UV
charts, so every island got a sliver of texture. This script:

  1. imports the GLB and welds/cleans the mesh
  2. decimates to a VR-friendly budget
  3. re-unwraps with Smart UV Project (a handful of islands, not thousands)
  4. triplanar-projects the source photo (no smearing at the seams)
  5. bakes that + ambient occlusion into the new clean atlas
  6. exports a GLB that carries a proper base colour texture

Run:
  blender -b --python blender_repair.py -- in.glb out.glb source.png [tris] [res]
"""

import sys

import bpy

argv = sys.argv[sys.argv.index("--") + 1:]
SRC, DST, TEX = argv[0], argv[1], argv[2]
TARGET_TRIS = int(argv[3]) if len(argv) > 3 else 120000
RES = int(argv[4]) if len(argv) > 4 else 2048

print(f"[repair] src={SRC} dst={DST} tex={TEX} tris={TARGET_TRIS} res={RES}")

bpy.ops.wm.read_factory_settings(use_empty=True)
scene = bpy.context.scene

# ── 1. import + join ────────────────────────────────────────────────────
bpy.ops.import_scene.gltf(filepath=SRC)
meshes = [o for o in scene.objects if o.type == "MESH"]
if not meshes:
    sys.exit("no mesh in GLB")

# ── weld, then strip the backdrop ───────────────────────────────────────
# Order matters: the raw GLB is split at every UV seam, so "separate by loose
# parts" on it yields tens of thousands of fragments and no meaningful
# components. Weld first, and the backdrop becomes one separable sheet.
bpy.ops.object.select_all(action="DESELECT")
for o in meshes:
    o.select_set(True)
bpy.context.view_layer.objects.active = meshes[0]
if len(meshes) > 1:
    bpy.ops.object.join()
obj = bpy.context.view_layer.objects.active

bpy.ops.object.mode_set(mode="EDIT")
bpy.ops.mesh.select_all(action="SELECT")
bpy.ops.mesh.remove_doubles(threshold=0.0001)
bpy.ops.mesh.separate(type="LOOSE")
bpy.ops.object.mode_set(mode="OBJECT")

parts = [o for o in scene.objects if o.type == "MESH"]
keep, dropped = [], []
for o in parts:
    bb = [o.matrix_world @ __import__("mathutils").Vector(c) for c in o.bound_box]
    dims = sorted([
        max(v.x for v in bb) - min(v.x for v in bb),
        max(v.y for v in bb) - min(v.y for v in bb),
        max(v.z for v in bb) - min(v.z for v in bb),
    ])
    biggest = dims[2] or 1e-6
    if dims[0] < biggest * 0.02 and dims[1] > biggest * 0.25:
        dropped.append((o.name, [round(d, 3) for d in dims]))
    else:
        keep.append(o)
print(f"[repair] components: {len(parts)} total, {len(keep)} kept, {len(dropped)} dropped")
for name, dims in dropped[:4]:
    print(f"[repair]   dropped planar sheet {name} dims={dims}")
for o in parts:
    if o not in keep:
        bpy.data.objects.remove(o, do_unlink=True)
if not keep:
    sys.exit("every component looked like a sheet — refusing to delete the subject")

meshes = keep
bpy.ops.object.select_all(action="DESELECT")
for o in meshes:
    o.select_set(True)
bpy.context.view_layer.objects.active = meshes[0]
if len(meshes) > 1:
    bpy.ops.object.join()
obj = bpy.context.view_layer.objects.active
obj.name = "asset"

# ── 2. clean ────────────────────────────────────────────────────────────
# glTF import writes custom split normals; shade_smooth silently does nothing
# until they're cleared, which is why the mesh keeps reading as low-poly.
try:
    bpy.context.view_layer.objects.active = obj
    bpy.ops.mesh.customdata_custom_splitnormals_clear()
    print("[repair] cleared custom split normals")
except Exception as exc:
    print(f"[repair] split-normal clear skipped: {exc}")

bpy.ops.object.mode_set(mode="EDIT")
bpy.ops.mesh.select_all(action="SELECT")
bpy.ops.mesh.remove_doubles(threshold=0.0001)
bpy.ops.mesh.normals_make_consistent(inside=False)
bpy.ops.object.mode_set(mode="OBJECT")

tris_before = sum(len(p.vertices) - 2 for p in obj.data.polygons)
print(f"[repair] imported tris={tris_before:,}")

# ── 3. decimate ─────────────────────────────────────────────────────────
if TARGET_TRIS and tris_before > TARGET_TRIS:
    mod = obj.modifiers.new("dec", "DECIMATE")
    mod.decimate_type = "COLLAPSE"
    mod.ratio = TARGET_TRIS / tris_before
    bpy.ops.object.modifier_apply(modifier=mod.name)
    tris_after = sum(len(p.vertices) - 2 for p in obj.data.polygons)
    print(f"[repair] decimated to {tris_after:,} tris")

# ── 4. planar projection UVs ────────────────────────────────────────────
# The reference is a side profile, so the correct mapping is a straight planar
# projection along the body's width axis: photo X -> body length, photo Y -> body
# height. Triplanar/BOX sampling was wrong twice over — it tiled, and it sampled
# the photo's white background over most of the body.
while obj.data.uv_layers:
    obj.data.uv_layers.remove(obj.data.uv_layers[0])
uv = obj.data.uv_layers.new(name="UVMap")
me = obj.data

bb2 = [obj.matrix_world @ __import__("mathutils").Vector(c) for c in obj.bound_box]
x0, x1 = min(v.x for v in bb2), max(v.x for v in bb2)
z0, z1 = min(v.z for v in bb2), max(v.z for v in bb2)
lx, lz = max(x1 - x0, 1e-6), max(z1 - z0, 1e-6)
for poly in me.polygons:
    for li in poly.loop_indices:
        co = me.vertices[me.loops[li].vertex_index].co
        u = (co.x - x0) / lx
        # Blender's V axis already runs bottom-to-top, so do NOT flip it here.
        # A 1.0-v flip is what rendered the paint upside down.
        v = (co.z - z0) / lz
        uv.data[li].uv = (min(max(u, 0.0), 1.0), min(max(v, 0.0), 1.0))
print(f"[repair] planar UV projection over {lx:.2f} x {lz:.2f} m")

# ── 5. triplanar source material ────────────────────────────────────────
obj.data.materials.clear()
mat = bpy.data.materials.new("proj")
mat.use_nodes = True
nt = mat.node_tree
nt.nodes.clear()

out = nt.nodes.new("ShaderNodeOutputMaterial")
bsdf = nt.nodes.new("ShaderNodeBsdfPrincipled")
img = nt.nodes.new("ShaderNodeTexImage")
img.image = bpy.data.images.load(TEX)
# BOX projection reads from three axes, so seams never stretch one photo flat.
img.projection = "FLAT"
# REPEAT (the default) tiles the photo across the body — that produced rows of
# tiny pig silhouettes. EXTEND clamps to the edge instead of repeating.
img.extension = "EXTEND"
tex_coord = nt.nodes.new("ShaderNodeTexCoord")
nt.links.new(tex_coord.outputs["UV"], img.inputs["Vector"])
print("[repair] texture sampled through planar UVs")
nt.links.new(img.outputs["Color"], bsdf.inputs["Base Color"])
bsdf.inputs["Roughness"].default_value = 0.62
nt.links.new(bsdf.outputs["BSDF"], out.inputs["Surface"])
obj.data.materials.append(mat)

# ── 6. bake base colour into the new atlas ──────────────────────────────
baked = bpy.data.images.new("baked_color", RES, RES)
bake_node = nt.nodes.new("ShaderNodeTexImage")
bake_node.image = baked
nt.nodes.active = bake_node

scene.render.engine = "CYCLES"
scene.cycles.samples = 8
scene.cycles.use_denoising = False
bpy.ops.object.select_all(action="DESELECT")
obj.select_set(True)
bpy.context.view_layer.objects.active = obj

print("[repair] baking base colour...")
bpy.ops.object.bake(type="DIFFUSE", pass_filter={"COLOR"}, margin=16,
                    use_clear=True, target="IMAGE_TEXTURES")

# ── 7. AO bake, multiplied into the colour ──────────────────────────────
ao_img = bpy.data.images.new("baked_ao", RES, RES, is_data=True)
ao_node = nt.nodes.new("ShaderNodeTexImage")
ao_node.image = ao_img
nt.nodes.active = ao_node
print("[repair] baking AO...")
bpy.ops.object.bake(type="AO", margin=16, use_clear=True, target="IMAGE_TEXTURES")

# pack results so the GLB is self-contained
baked.pack()
ao_img.pack()

# ── 8. final material: baked colour x AO ────────────────────────────────
# Hunyuan's output ships with flat normals; at 94k tris that reads as a
# faceted low-poly toy. Smooth them or the texture never lands on a
# convincing surface.
bpy.ops.object.select_all(action="DESELECT")
obj.select_set(True)
bpy.context.view_layer.objects.active = obj
bpy.ops.object.shade_smooth()
# NOTE: do NOT add a "Smooth by Angle" modifier here — at its default 30° it
# re-splits normals on a mesh like this and brings the faceting straight back.

final = bpy.data.materials.new("baked")
final.use_nodes = True
fnt = final.node_tree
fnt.nodes.clear()
fout = fnt.nodes.new("ShaderNodeOutputMaterial")
fbsdf = fnt.nodes.new("ShaderNodeBsdfPrincipled")
fcol = fnt.nodes.new("ShaderNodeTexImage")
fcol.image = baked
fao = fnt.nodes.new("ShaderNodeTexImage")
fao.image = ao_img
mix = fnt.nodes.new("ShaderNodeMix")
mix.data_type = "RGBA"
mix.blend_type = "MULTIPLY"
mix.inputs["Factor"].default_value = 0.65
fnt.links.new(fcol.outputs["Color"], mix.inputs[6])
fnt.links.new(fao.outputs["Color"], mix.inputs[7])
fnt.links.new(mix.outputs[2], fbsdf.inputs["Base Color"])
fbsdf.inputs["Roughness"].default_value = 0.6
fnt.links.new(fbsdf.outputs["BSDF"], fout.inputs["Surface"])

obj.data.materials.clear()
obj.data.materials.append(final)

# ── 9. export ───────────────────────────────────────────────────────────
bpy.ops.object.select_all(action="DESELECT")
obj.select_set(True)
bpy.context.view_layer.objects.active = obj
bpy.ops.export_scene.gltf(
    filepath=DST,
    export_format="GLB",
    use_selection=True,
    export_image_format="AUTO",
    export_materials="EXPORT",
)

tris_final = sum(len(p.vertices) - 2 for p in obj.data.polygons)
print(f"[repair] done: {DST} tris={tris_final:,} res={RES}")
