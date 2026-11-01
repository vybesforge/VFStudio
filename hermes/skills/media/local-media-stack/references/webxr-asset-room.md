# WebXR asset test room

Inspect a generated GLB at true scale in a headset before it goes into a real
pipeline. A single HTML file plus a vendored three.js runs in Chrome/Edge on
Windows and reaches SteamVR through OpenXR — no Unity, no install, no build step.

## Vendor three.js (do not use an importmap + CDN)

An importmap pointing at unpkg works on the dev machine and silently phones home
from the target machine. For a local-first deliverable, vendor it:

```bash
cd ~/media-stack/vr && mkdir -p vendor
B=https://unpkg.com/three@0.170.0
for f in build/three.module.js \
         examples/jsm/loaders/GLTFLoader.js \
         examples/jsm/controls/OrbitControls.js \
         examples/jsm/utils/BufferGeometryUtils.js ; do
  curl -sfL "$B/$f" -o "vendor/$(basename "$f")"
done
```

Then rewrite bare specifiers, because flattening `build/` and `examples/jsm/`
into one directory breaks the addons' relative imports:

```python
s = s.replace("from 'three'", "from './three.module.js'")
s = s.replace("from '../utils/BufferGeometryUtils.js'", "from './BufferGeometryUtils.js'")
```

Point the page at `./vendor/three.module.js`, `./vendor/GLTFLoader.js`,
`./vendor/OrbitControls.js` and drop the importmap entirely.

**`VRButton.js` needs no import** — it is a standalone class with zero `three`
imports. If you wire your own Enter-VR button to `navigator.xr.requestSession`,
do not vendor or import it at all.

## Prove it is offline

Assertion beats assumption. In the browser tool:

```python
js("JSON.stringify(performance.getEntriesByType('resource')"
   ".map(r=>r.name).filter(n=>!n.startsWith(location.origin)))")
# must return []
```

## Fit the asset automatically

Generated meshes arrive in arbitrary units and origins. Never assume metres —
measure and normalise so the model sits on the floor, centred, whatever it is:

```js
const box = new THREE.Box3().setFromObject(obj);
const size = box.getSize(new THREE.Vector3());
obj.position.y -= box.min.y;                 // sit on the floor
const c = box.getCenter(new THREE.Vector3());
obj.position.x -= c.x; obj.position.z -= c.z; // centre on XZ
```

Report `size` and triangle count in the HUD — that is how the user judges whether
the asset is the right scale for their world without putting a headset on.

## Play the clip, and prove it is playing

A rigged GLB whose animation never runs looks identical to a static asset, so wire
the mixer at load and put the **clip name in the HUD** — that turns "I think it
animates" into something you can assert from the DOM:

```js
let mixer = null;
if (gltf.animations && gltf.animations.length) {
  mixer = new THREE.AnimationMixer(obj);
  mixer.clipAction(gltf.animations[0]).play();
}
const anim = gltf.animations?.length
  ? ` · anim: ${gltf.animations[0].name || 'clip 1'}` : ' · no anim';
```

`mixer.update(dt)` must run inside `setAnimationLoop`. A clip registered at load
but never ticked still reports `animations.length === 1` while the mesh stands
still. Verify with `document.getElementById('meta').textContent` — a line ending
in `· anim: Trot` proves the clip exists; a rendered-frame comparison is the proof
that it actually moves.

## Room features that earn their place

- **1 m grid plus a 1.8 m vertical reference pole.** Scale errors are invisible in
  VR until something of known height is beside the asset.
- **Wireframe toggle** — exposes topology problems that shading hides.
- **Rotate toggle** — shows the silhouette from every angle without moving.
- **Lighting toggle** — a single hemisphere + two directionals reads flat; let the
  user flip to a brighter exposure to judge texture.
- **Graceful missing-asset path** — a named error telling the user to drop the GLB
  beside the HTML. A blank canvas reads as a broken room.

## Pitfalls

- **`GLTFLoader` imports `BufferGeometryUtils`.** Vendor it too, or the module
  graph fails at load with a bare-specifier error only visible in the console.
- **WebXR requires a secure context.** `http://localhost` and `http://127.0.0.1`
  count; a plain `http://<LAN-IP>` does not, so a headset on another machine
  cannot open the room that way — serve over HTTPS or copy the folder onto the
  target box and run it there.
- **`navigator.xr` exists even when no headset is connected.** Test for a session,
  not for the object, before telling anyone VR is ready.
- **Replacing the asset while the page is open does not reload it.** The loader
  runs once; a stale GLB stays cached, so copy the new file over and reload, then
  re-read the HUD before reporting the swap.
