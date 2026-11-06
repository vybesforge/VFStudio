"""lanes — resolve a lane to its ComfyUI URL / port / GPU UUID.

One reader for config/gpu-lanes.env so no tool has to hardcode a port number.
The port IS the lane interface: which card answers on it is defined in that file.

    from lanes import url, port, uuid
    HOST = os.environ.get("COMFY_HOST") or url("video")
"""
import os

CONF = os.path.expanduser("~/media-stack/config/gpu-lanes.env")
_CACHE = {}


def _load():
    if "conf" in _CACHE:
        return _CACHE["conf"]
    conf = {}
    try:
        for raw in open(CONF, encoding="utf-8"):
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            v = v.split("#", 1)[0].strip().strip('"')
            if v:
                conf[k.strip()] = v
    except OSError:
        pass
    _CACHE["conf"] = conf
    return conf


# lane names a human (or a tool) might use -> the key holding that lane's port
_PORT_KEY = {
    "stills": "COMFY_STILLS_PORT",
    "image": "COMFY_STILLS_PORT",
    "img": "COMFY_STILLS_PORT",
    "a": "COMFY_STILLS_PORT",
    "audio": "COMFY_STILLS_PORT",
    "music": "COMFY_STILLS_PORT",
    "sfx": "COMFY_STILLS_PORT",
    "voice": "COMFY_STILLS_PORT",
    "video": "COMFY_VIDEO_PORT",
    "vid": "COMFY_VIDEO_PORT",
    "3d": "COMFY_VIDEO_PORT",
    "mesh": "COMFY_VIDEO_PORT",
    "b": "COMFY_VIDEO_PORT",
}
_UUID_KEY = {
    "stills": "GPU_A_UUID", "image": "GPU_A_UUID", "img": "GPU_A_UUID", "a": "GPU_A_UUID",
    "audio": "GPU_A_UUID", "music": "GPU_A_UUID", "sfx": "GPU_A_UUID", "voice": "GPU_A_UUID",
    "video": "GPU_B_UUID", "vid": "GPU_B_UUID", "3d": "GPU_B_UUID", "mesh": "GPU_B_UUID",
    "b": "GPU_B_UUID", "display": "GPU_DISPLAY_UUID",
}
_DEFAULT = {"COMFY_STILLS_PORT": "8189", "COMFY_VIDEO_PORT": "8190"}


def port(lane: str) -> int:
    key = _PORT_KEY.get(str(lane).lower(), "COMFY_STILLS_PORT")
    return int(_load().get(key) or _DEFAULT[key])


def url(lane: str, host: str = "127.0.0.1") -> str:
    return "http://%s:%d" % (host, port(lane))


def uuid(lane: str) -> str:
    return _load().get(_UUID_KEY.get(str(lane).lower(), "GPU_A_UUID"), "")


def output_dir_for_port(p: int) -> str:
    """Each ComfyUI instance writes somewhere different; follow the port."""
    vid = port("video")
    return os.path.expanduser("~/comfy/output-b") if int(p) == vid \
        else os.path.expanduser("~/media-stack/ComfyUI/output")
