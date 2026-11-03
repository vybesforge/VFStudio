# TRELLIS.2 headless: image → textured GLB over the HTTP API

Companion to `trellis2-ui-run.md`. That doc says the template cannot be queued over
`POST /prompt` and must be driven through the browser frontend. **That is no longer
true on ComfyUI 0.43+**, and the headless route is faster, reproducible and has no
CDP timing games.

```
trellis3d ref.png --prefix 3d/my_asset --texres 4096 --out ~/media-stack/output/3d
```

`tools/comfy/trellis3d` builds it; the panel's 3D tab has the same thing as a form
("Image → 3D mesh"), which shells out to the same CLI.

---

## How the API route works

The two blockers in the UI-only doc were:

1. `Save3DAdvanced` needs a `viewport_state` socket only the frontend injects. — Still true. Do not use it.
2. "No output node accepts MESH." — **False on this build.** `SaveGLB` is a real
   output node (`is_output_node=True`) taking just `mesh` + `filename_prefix`.

So: convert the shipped template to API format, drop the viewer/saver nodes,
append `SaveGLB` on the *textured* mesh, submit.

Template: `comfyui_workflow_templates_json/templates/3d_pixal3d_trellis2_image_to_model.json`
(66 nodes → 53 after pruning).

## The five things that actually bite

1. **`node_errors` is not optional.** ComfyUI answers `200` with a `prompt_id`
   *and* a non-empty `node_errors` when only part of the graph fails validation.
   The valid branch runs, the failed branch is silently dropped, and the run ends
   `status_str=success` in seconds having produced nothing. Always read
   `node_errors` from the submit response — `trellis3d` dies on it, and `--validate`
   checks the graph locally before anything is queued.

2. **Dynamic combos need their sub-inputs.** `RemeshMesh.sign_mode` is a
   `COMFY_DYNAMICCOMBO_V3`: the option's sub-inputs are addressed as
   `"sign_mode.fill"` / `"sign_mode.qef"` and are **required**. Same shape for
   `DecimateMesh.placement_mode` — which also consumes a `widgets_values` slot, so a
   positional widget mapping that does not know `COMFY_DYNAMICCOMBO_V3` is a widget
   silently loses it and then dies 4 minutes into the run with
   `DecimateMesh.execute() missing 1 required positional argument`.

3. **Save the *textured* mesh.** The template feeds its savers from three places
   (raw `VoxelToMesh`, the smoothed shape stage, and the painted result). Node id
   order tells you nothing — walk back from `ApplyTextureToMesh` →
   `MeshSmoothNormals` and save that.

4. **`ImageCropToMask.pad_factor` should be 1.0 for TRELLIS.2.** The template ships
   1.1 (a Pixal3D default). The node's own tooltip says 1.0. Pad is margin, margin
   becomes geometry, and it lands on the model's proportions.

5. **Muting ≠ deleting.** Minus `mode 2` in the UI is fine; in an API prompt you
   drop the node *and* every link that pointed at it. Pixal3D/MoGe weights are not
   installed and ComfyUI validates the whole prompt, so they must go.

## Measured on billie (V100 32 GB)

| stage | observed |
|---|---|
| shape stage (12 steps) | ~200 s |
| remesh / unwrap / paint / bakes | ~110 s |
| **total, 4096 bake** | **~5 min 10 s** |
| output | 699,911 tris, 416,582 verts, 1 material |
| GLB | ~47 MB, 3 PBR textures (base 4096², MR+AO 4096², normal 2048²) |

Roughly 3× faster than the M3 Max reference run (16 min 16 s).

## After the mesh — two things worth doing

**Force metallic to 0.** The bake guesses a metallic/roughness map and lands around
25–30 % metallic on a stylised character; a metallic dielectric renders dark and
glossy and gets blamed on the albedo. `tools/anim/glb_material.py in.glb out.glb
--metallic 0 --roughness 0.8 --drop-metallic-map` rewrites only the JSON chunk and
keeps base colour, normal and occlusion exactly as baked.

**Look at every side.** `tools/anim/turntable.py` (run through `bin/blender -b -P`)
renders N yaw angles plus dumps the GLB's textures. Use `Standard` view transform,
not AgX: AgX desaturates hard and will make a serviceable albedo look muddy.

## Known limits (single-image route)

- Hands and feet come back as mittens/stumps. That is the model, not a setting.
  Barefoot references at least give it toes to average; shoes give it a block.
- The profile face is flat (the front is the only conditioned view) and the back is
  invented. `Trellis2Conditioning` takes exactly one `IMAGE` — multi-view
  conditioning is not exposed by this node, so a turnaround does not help yet.
- Paint detail is capped by the texture stage's 512 px view renders, so sides and
  back smear even at a 4096 bake. Colour can also drift warm/magenta on
  illustration inputs; check the albedo atlas itself, not just the render.
