from concurrent.futures import ThreadPoolExecutor
import os
from PIL import Image

_IMG_EXECUTOR = ThreadPoolExecutor(max_workers=3, thread_name_prefix="pngtuber_img")

PERFORMANCE_PRESETS = {
    "performance": {
        "label": "⚡ Rendimiento",
        "preview_max_dim": 360,
        "preview_max_frames": 30,
        "preview_mouth_dim": 256,
        "preview_fps_ms": 28,
        "obs_max_dim": 960,
        "obs_prop_dim": 768,
        "obs_mouth_dim": 384,
        "obs_max_frames": 45,
        "obs_fps_ms": 16,
        "squash_cache_max": 24,
        "mouth_cache_max": 64,
    },
    "balanced": {
        "label": "⚖️ Equilibrado",
        "preview_max_dim": 512,
        "preview_max_frames": 45,
        "preview_mouth_dim": 320,
        "preview_fps_ms": 22,
        "obs_max_dim": 1440,
        "obs_prop_dim": 1080,
        "obs_mouth_dim": 512,
        "obs_max_frames": 60,
        "obs_fps_ms": 16,
        "squash_cache_max": 48,
        "mouth_cache_max": 128,
    },
    "quality": {
        "label": "✨ Alta Calidad",
        "preview_max_dim": 720,
        "preview_max_frames": 60,
        "preview_mouth_dim": 384,
        "preview_fps_ms": 16,
        "obs_max_dim": None,
        "obs_prop_dim": 2048,
        "obs_mouth_dim": 768,
        "obs_max_frames": 90,
        "obs_fps_ms": 16,
        "squash_cache_max": 96,
        "mouth_cache_max": 256,
    },
}


def get_performance_preset(mode_key):
    return PERFORMANCE_PRESETS.get(mode_key, PERFORMANCE_PRESETS["performance"])


def submit_bg_task(fn, *args, **kwargs):
    """Envía una tarea pesada (I/O o PIL resize) al pool de hilos en segundo plano."""
    return _IMG_EXECUTOR.submit(fn, *args, **kwargs)


def load_pil_frames_from_path(path, max_dim=None, max_frames=60):
    """Carga un PNG/GIF/WEBP a lista [(PIL.Image RGBA, duration_sec), ...] fuera del hilo UI."""
    if not path or not os.path.exists(path):
        return []
    frames = []
    try:
        with Image.open(path) as img:
            n_frames = min(getattr(img, "n_frames", 1), max_frames)
            if n_frames > 1 and getattr(img, "is_animated", False):
                for f_idx in range(n_frames):
                    img.seek(f_idx)
                    dur_ms = img.info.get("duration", 80) or 80
                    dur_sec = max(0.02, min(2.0, dur_ms / 1000.0))
                    fr = img.convert("RGBA").copy()
                    if max_dim and max(fr.size) > max_dim:
                        fr.thumbnail((max_dim, max_dim), Image.Resampling.LANCZOS)
                    frames.append((fr, dur_sec))
            else:
                fr = img.convert("RGBA")
                if max_dim and max(fr.size) > max_dim:
                    fr.thumbnail((max_dim, max_dim), Image.Resampling.LANCZOS)
                frames.append((fr, 1.0))
    except Exception:
        return []
    return frames


def resize_avatar_frames(raw_images, max_w, max_h, flip_x=False):
    """Pre-escala todos los frames PIL de un avatar en segundo plano."""
    resized = {}
    for role, frames_list in raw_images.items():
        out = []
        for pil_img, dur in frames_list:
            w, h = pil_img.size
            ratio = min(max_w / max(1, w), max_h / max(1, h))
            nw = max(1, int(w * ratio))
            nh = max(1, int(h * ratio))
            res_img = pil_img.resize((nw, nh), Image.Resampling.LANCZOS)
            if flip_x:
                res_img = res_img.transpose(Image.FLIP_LEFT_RIGHT)
            out.append((res_img, dur))
        resized[role] = out
    return resized


def resize_props_frames(raw_props, pos_scale):
    """Pre-escala y rota los frames PIL de props en segundo plano."""
    out_props = []
    for p in raw_props:
        sc_factor = max(0.05, pos_scale * (p.get("scale", 100) / 100.0))
        rot_deg = p.get("rotation", 0)
        scaled_frames = []
        for p_img, dur in p.get("raw_frames", []):
            pw = max(1, int(p_img.width * sc_factor))
            ph = max(1, int(p_img.height * sc_factor))
            res_p = p_img.resize((pw, ph), Image.Resampling.LANCZOS)
            if rot_deg != 0:
                res_p = res_p.rotate(-rot_deg, expand=True, resample=Image.Resampling.BICUBIC)
            scaled_frames.append((res_p, dur))
        out_props.append({
            "id": p["id"],
            "frames": scaled_frames,
            "layer": p.get("layer", "front"),
            "follows_bounce": p.get("follows_bounce", False),
            "offset_x": p.get("offset_x", 0),
            "offset_y": p.get("offset_y", 0),
            "enabled": p.get("enabled", True),
            "visible_frames": p.get("visible_frames", "all"),
        })
    return out_props
