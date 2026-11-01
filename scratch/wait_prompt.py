"""Wait for a ComfyUI prompt to finish, reporting progress."""
import json
import sys
import time
import urllib.request

HOST = "http://127.0.0.1:8188"
pid = sys.argv[1]
deadline = time.time() + int(sys.argv[2] if len(sys.argv) > 2 else 3600)


def get(path):
    with urllib.request.urlopen(f"{HOST}{path}", timeout=30) as r:
        return json.loads(r.read() or b"{}")


last = None
while time.time() < deadline:
    q = get("/queue")
    running = len(q.get("queue_running", []))
    pending = len(q.get("queue_pending", []))
    hist = get(f"/history/{pid}")
    if pid in hist:
        h = hist[pid]
        status = h.get("status", {})
        print(f"[done] completed={status.get('completed')} "
              f"status_str={status.get('status_str')}")
        if status.get("status_str") == "error":
            for m in status.get("messages", []):
                if m and m[0] == "execution_error":
                    print("[error]", json.dumps(m[1])[:1500])
        outs = h.get("outputs", {})
        written = []
        for nid, o in outs.items():
            for key in ("glb", "gltf", "mesh", "result", "3d", "images"):
                for item in (o.get(key) or []):
                    written.append((nid, key, item if isinstance(item, str) else json.dumps(item)))
        for w in written:
            print("[output]", w)
        sys.exit(0)
    state = (running, pending)
    if state != last:
        print(f"[wait] running={running} pending={pending} {time.strftime('%H:%M:%S')}", flush=True)
        last = state
    time.sleep(10)

print("[timeout] still running")
sys.exit(2)
