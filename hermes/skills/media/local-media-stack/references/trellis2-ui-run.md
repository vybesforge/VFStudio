# Running the TRELLIS.2 template through the UI

The official `3d_pixal3d_trellis2_image_to_model.json` graph cannot be queued via
`POST /prompt`. Two independent blockers:

1. `Save3DAdvanced` requires a `viewport_state` of type `LOAD_3D`. It is a socket,
   not a widget — the web frontend injects it at queue time.
2. No `output_node` accepts `MESH`. `MeshToFile3D` reports `output_node=False`, so
   with the UI savers pruned nothing pulls the graph and nothing executes.

The failure mode is nasty: ComfyUI returns `status_str=success` in 0.02–8 s, the
`/history` entry contains only `PreviewImage`/`MaskPreview` outputs, and no file
appears in `output/3d/`. Always check for the written GLB, never the status.

## Working route: drive the real frontend over CDP

The template is served by the ComfyUI server itself:

```
http://127.0.0.1:8188/templates/3d_pixal3d_trellis2_image_to_model.json
```

(Not under `/api/`. `/templates/index.json` lists them all.)

### 1. Load the graph

`app` is the ComfyUI frontend object; `app.loadGraphData` and `app.queuePrompt`
both exist on it. A 66-node graph takes longer than the CDP eval timeout, so fire
the load unawaited and poll a flag rather than awaiting it:

```js
window.__loadState = 'starting';
(async () => {
  try {
    const r = await fetch('/templates/3d_pixal3d_trellis2_image_to_model.json');
    const wf = await r.json();
    window.__loadState = 'fetched';
    await window.app.loadGraphData(wf);
    window.__loadState = 'loaded';
  } catch (e) { window.__loadState = 'ERR ' + e.message; }
})();
'started';
```

Poll `window.__loadState` and `app.graph._nodes.length` (expect 66) until loaded.

### 2. Set the branch and inputs

The reference must be in `ComfyUI/input/` before this — copy it there, or
`LoadImage` will not list it.

```js
for (const node of window.app.graph._nodes) {
  if (node.type === 'PrimitiveBoolean') node.widgets[0].value = true;   // TRELLIS.2
  if (node.type === 'LoadImage')       node.widgets[0].value = 'my_ref.png';
  if (node.type === 'PrimitiveInt')    node.widgets[0].value = 4096;
}
```

`PrimitiveBoolean` node 316 is the single master switch feeding all three
`ComfySwitchNode`s. `true` = TRELLIS.2, `false` = Pixal3D.

### 3. Mute the uninstalled branch

```js
const MUTE = ['319', '55', '56', '242', '298'];
for (const node of window.app.graph._nodes)
  if (MUTE.includes(String(node.id))) node.mode = 2;
```

| id | node | why |
|---|---|---|
| 319 | `UNETLoader` (pixal3d) | weight not installed |
| 55 | `LoadMoGeModel` | weight not installed |
| 56 | `MoGeInference` | only feeds Pixal3D conditioning |
| 242 | `MoGeGeometryToFOV` | ditto |
| 298 | `Pixal3DConditioning` | unreachable when the switch is true |

Validation runs over the entire prompt, **not** only the selected switch branch,
so leaving these live fails the job even though the switch makes them
unreachable. `mode = 2` mutes; `mode = 4` bypasses.

**Compare ids as strings.** `node.id` is a number and `[55,56].includes(node.id)`
works, but a mixed list silently matches nothing — the mute loop then reports an
empty list and you queue a doomed prompt.

### 4. Queue

```js
const p = window.app.queuePrompt(0, 1);
p.then(r => window.__qres = 'ok ' + JSON.stringify(r))
 .catch(e => window.__qres = 'REJECT ' + e.message);
```

Confirm with `GET /queue` → `queue_running` length 1. A rejected submit surfaces
as a modal, not a thrown error — check the queue, not just the return value.

## What a good run looks like

| stage | observed |
|---|---|
| shape sampling | 12 steps, ~26 s/step |
| texture stage + refine | follows the shape latent |
| `RemeshMesh` | 31 chunks, the slow tail |
| bake | 5 chunks, ~24 s |
| total | **16 min 16 s** on M3 Max 64 GB |
| output | `ComfyUI/output/3d/ComfyUI_00001.glb` |
| result | 700k tris, 3 PBR textures, 56 MB |

Peak during the run: GPU ~95 %, RAM ~47 GB. The `RemeshMesh` stage is where memory
presses hardest.

## Downstream notes

- Scale to real-world size before rigging — TRELLIS returns roughly a 1 m object.
- The GLB carries base colour, metallic/roughness, normal and AO; judge the
  **base colour** image when checking texture quality.
- 700k / 56 MB is heavy for a 16 GB headset GPU. Bake a decimated LOD pair rather
  than shipping the master to the VR room.
