# VF Studio panel — UI conventions and pitfalls

One page (`control/studio.html`) served by one app (`control/panel.py`); per-modality job code lives in
`control/studio.py`. Everything here is a rule that has cost time when missed.

## Tab ownership — where a new control goes

| Tab | Owns |
|---|---|
| Image / Video / 3D & VR / Sound / Voice / Write / Vision / Train | run forms, jobs, galleries for that modality |
| Models | manifest + HF inventory |
| **Services** | service start/stop cards **and the endpoint list** — anything another program or page would point at |
| Resources | CPU/GPU/mem/swap, top processes, disk, unload-all / stop-everything |

Dylan moves a control to the tab whose subject it shares and will say so plainly ("put that on the
services page, not the resources page"). A URL/endpoint belongs with the services that serve it, not
with machine load. Put it where the semantic match is the first time; Resources is the machine's
thermometer, not an integration surface.

## Status indicator is the control

A status pill that only reports is a bug waiting to be reported. Every service card's status pill
(`.svctog`, dot + `running|starting|stopped`) is the toggle: click while running → `POST /api/stop/<key>`,
click while stopped → `POST /api/start/<key>`. `running` includes the `starting` state — anything with a
live process stops on click. Hover styling must telegraph the direction (running pill hovers red,
stopped pill hovers cyan) and the tooltip reads "click to stop" / "click to start".

**Before stopping ComfyUI, check the queue** (`curl -s http://127.0.0.1:8188/queue`): the box is shared
with the Telegram session, so a job that is `queue_running` is someone else's and dies with the server.
Stop mlx-audio to exercise the toggle when the queue is not empty.

## Endpoints — tiles inside each service card

- The list is **server data**: `ENDPOINTS` in `control/panel.py` → `GET /api/endpoints`. Never hard-code
  URLs in the HTML — a new service is one dict entry (`key, label, svc, port, env, path, desc, paths,
  snippet`), and the page picks it up. `svc` binds a tile to the card that owns it (`audio` ×3, `comfy`,
  `llm`, `vision`, `panel`) — a service without a `SERVICES` entry still gets a card, rendered separately.
- `snippet` uses `{{base}}` (origin + path) and `{{base_origin}}` placeholders; the host switch
  (`127.0.0.1` vs LAN IP from `lan_ip()`) rewrites them at render time, so the same data serves a
  laptop and a headset.
- **Tile payload**: endpoint name, the full URL as selectable cyan code, one line of what it is, and
  **Copy** + **curl** (method/path/what table + the snippet). Copy-all and the host switch sit in one
  slim bar above the grid; there is no standalone endpoint section — a second list of the same URLs is
  what Dylan merges away.
- **Card order**: header → port/pid → action buttons → endpoint tiles → log `<pre>` last. A log opened
  above the tiles shoves the copy-paste block down the card and reads as "the tiles disappeared".
- Only the panel is LAN-bound (`PANEL_HOST=0.0.0.0 stack panel`); ComfyUI, mlx-audio, the LLM and the
  VLM bind 127.0.0.1, so say that in the note under the host switch instead of letting a LAN link fail
  silently.
- Verify every snippet against the live service before shipping the block (`curl` the TTS route and
  confirm a `RIFF` wav, `curl` `/object_info` and count nodes). A link that 404s on the first paste is
  worse than no list. If a service is too heavy to start just to test the shape (writer LLM, VLM), read
  the body its CLI already sends (`tools/llm/scribe`, `tools/vision/see`) rather than guessing, and say
  in the report which rows were proven live and which were only read.

## Copy buttons

`navigator.clipboard.writeText` is unavailable on plain-HTTP LAN origins, so every copy goes through one
helper that falls back to a hidden `<textarea>` + `document.execCommand('copy')` and flashes success or
failure. Pass the text through a lookup function (`copyEp(key)` reads from `EP`) instead of interpolating
it into an inline `onclick` — quoting model ids and curl bodies inside HTML attributes is where these
break.

**Testing a copy button:** clipboard *read* fails with `NotAllowedError: Document is not focused` even
after `Browser.grantPermissions`, and that failure says nothing about your code. Stub the writer instead:

```python
js("navigator.clipboard.writeText = t => { window.__clip = t; return Promise.resolve(); }; window.__clip=''; 1")
js("copyEp('tts'); 1"); time.sleep(0.3); js("window.__clip")   # exact string that would be copied
```

## Card layout

Card headers are `.row` (flex, `flex-wrap:wrap`). A right-side control drops onto a second line as soon
as the description is long (long model ids do it every time). Give the text block
`style="flex:1;min-width:0"`, the row `flex-wrap:nowrap`, and the control `flex:0 0 auto` — then every
card's pill lands on the same baseline. Check it numerically, not by eye:

```python
js("Array.from(document.querySelectorAll('#services .card')).map(c=>{const p=c.querySelector('.svctog');const cr=c.getBoundingClientRect(),pr=p.getBoundingClientRect();return p.innerText+' top='+Math.round(pr.top-cr.top)+' rightGap='+Math.round(cr.right-pr.right);})")
```

## Editing loop

- **Syntax-gate every `studio.html` patch before judging it.** The page is one inline `<script>`; a
duplicate top-level `const` (the page already defines `esc`) aborts the parse and every function
disappears while the HTML still renders — the symptom is an empty card, not an error banner.

  ```bash
  tools/.venv/bin/python -c "import re;s=open('control/studio.html').read();open('/tmp/s.js','w').write(re.findall(r'<script>(.*?)</script>',s,re.S)[-1])"
  node --check /tmp/s.js            # must print nothing
  ```

  then assert the specific function exists in the live page (`js("typeof refreshProgress")` →
  `"function"`) before reading any values out of the DOM; `undefined` means the block died, not that
  your feature is broken.
- **ComfyUI's queue count is not a queue count.** `exec_info.queue_remaining` includes the running
  job. Derive running/pending from `/queue` yourself (as `GET /api/comfy/jobs` does), show them apart
  (`"1 running · 0 queued"`), and name each prompt from its node types plus `filename_prefix` — a node
  id is unreadable to the user who asked what the box is doing.
- **Track elapsed time yourself.** ComfyUI's queue items carry no start timestamp; keep a
  `{prompt_id: first_seen}` dict in the panel and prune ids that leave the queue, or every job shows
  a blank duration.
- `panel.py` / `studio.py` changes: `stack restart panel` (uvicorn does not hot-reload). `studio.html`
  alone needs **no** restart — it is read per request — just re-navigate; the browser keeps the old page
  and cached fetches, so reload before judging a fix.
- **Build the structure once, then patch state in place.** Re-rendering a card list on a 2.5 s poll
  collapses every open `Details`/log and throws away scroll position. Render the cards when the data or
  host changes (`svcRendered` flag), and on each poll rewrite only the changed text/class (`updateServiceState()`
  sets the pill's class, tooltip, `onclick` and the port line). Keep expandable state in `Set`s
  (`epOpen`, `logOpen`) so a genuine full re-render (host switch) restores it.
- **Click test targets by id, never by visible text.** `querySelectorAll('.svctog')` +
  `.find(b=>/running/.test(b.innerText))` hits the first running card — ComfyUI — when the intent was
  mlx-audio, and stopping the other service silently kills its work. Give each control an id
  (`svct-<key>`, `epd-<key>`, `slog-<key>`) and drive it by that.
- State the page shows must come from one fetch per refresh: reading `/api/status` twice in a row
  (once for cards, once for the endpoint block) leaves the second caller with stale tags when the
  first render wins the race.
