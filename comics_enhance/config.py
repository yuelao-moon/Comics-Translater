"""Global configuration for ComicsEnhance."""

import os
import platform
import shutil
from pathlib import Path


# === Project Info ===
PROJECT_NAME = "ComicsEnhance"
VERSION = "0.1.0"

# === Paths ===
def _get_default_work_dir() -> str:
    if platform.system() == "Windows":
        base = os.environ.get("LOCALAPPDATA", os.path.expanduser("~"))
    elif platform.system() == "Darwin":
        base = os.path.expanduser("~/Library/Application Support")
    else:
        base = os.environ.get("XDG_DATA_HOME", os.path.expanduser("~/.local/share"))
    return os.path.join(base, "ComicsEnhance")


WORK_DIR = _get_default_work_dir()
CACHE_DIR = os.path.join(WORK_DIR, "cache")
TEMP_DIR = os.path.join(WORK_DIR, "temp")


# === Model Catalog (sr-vulkan model constants) ===
# Each model encodes scale + noise into one ID.
# Even ID = regular, odd ID = TTA variant.
# --tta 切换到这个 +1 的奇数 ID.

MODEL_CATALOG = {
    # ── Waifu2x CUNet ──
    "cunet":        { "id": 8,  "desc": "Waifu2x CUNet 2x, no denoise" },
    "cunet-n0":     { "id": 10, "desc": "Waifu2x CUNet 2x, denoise 0" },
    "cunet-n1":     { "id": 12, "desc": "Waifu2x CUNet 2x, denoise 1" },
    "cunet-n2":     { "id": 14, "desc": "Waifu2x CUNet 2x, denoise 2" },
    "cunet-n3":     { "id": 16, "desc": "Waifu2x CUNet 2x, denoise 3" },

    # ── Waifu2x Anime ──
    "anime":        { "id": 18, "desc": "Waifu2x Anime 2x (no specific denoise)" },
    "anime-n0":     { "id": 20, "desc": "Waifu2x Anime 2x, denoise 0" },
    "anime-n1":     { "id": 22, "desc": "Waifu2x Anime 2x, denoise 1" },
    "anime-n2":     { "id": 24, "desc": "Waifu2x Anime 2x, denoise 2" },
    "anime-n3":     { "id": 26, "desc": "Waifu2x Anime 2x, denoise 3 (default)" },

    # ── Waifu2x Photo ──
    "photo":        { "id": 28, "desc": "Waifu2x Photo 2x (no specific denoise)" },
    "photo-n0":     { "id": 30, "desc": "Waifu2x Photo 2x, denoise 0" },
    "photo-n1":     { "id": 32, "desc": "Waifu2x Photo 2x, denoise 1" },
    "photo-n2":     { "id": 34, "desc": "Waifu2x Photo 2x, denoise 2" },
    "photo-n3":     { "id": 36, "desc": "Waifu2x Photo 2x, denoise 3" },

    # ── RealESRGAN ──
    "realesr-anime":   { "id": 74, "desc": "RealESRGAN AnimeVideoV3 2x (best for anime)" },
    "realesr-anime-3x":{ "id": 76, "desc": "RealESRGAN AnimeVideoV3 3x" },
    "realesr-anime-4x":{ "id": 78, "desc": "RealESRGAN AnimeVideoV3 4x" },
    "realesr-x4":      { "id": 82, "desc": "RealESRGAN x4+ Anime 4x" },

    # ── RealSR ──
    "realsr-4x":       { "id": 72, "desc": "RealSR DF2K 4x" },

    # ── CPU (Pillow) ──
    "pillow":        { "id": None, "desc": "Pillow LANCZOS 2x — CPU only, no GPU needed" },
    "pillow-4x":     { "id": None, "desc": "Pillow LANCZOS 4x — CPU only, upscale 4x" },

    # ── RealCUGAN (pro) ──
    "realcugan-pro-2x":    { "id": 38, "desc": "RealCUGAN Pro 2x" },
    "realcugan-pro-3x":    { "id": 44, "desc": "RealCUGAN Pro 3x" },
    "realcugan-pro-d3":    { "id": 42, "desc": "RealCUGAN Pro 2x, denoise 3" },
}

# Convenience access
_MODEL_NAMES = {info["id"]: name for name, info in MODEL_CATALOG.items()}


def get_model_id(name: str) -> int:
    """Look up sr-vulkan model ID by catalog name.

    Returns None for Pillow models.
    """
    if name == "pillow" or name == "pillow-4x":
        return None
    entry = MODEL_CATALOG.get(name)
    if entry is None:
        raise KeyError(f"Unknown model: {name!r}")
    return entry["id"]


def is_pillow_model(name: str) -> bool:
    """Check if model is a Pillow CPU upscale."""
    return name in ("pillow", "pillow-4x")


def model_scale(name: str) -> int:
    """Infer approximate scale factor from model name."""
    if "4x" in name or "-4x" in name:
        return 4
    if "3x" in name or "-3x" in name:
        return 3
    return 2


def model_description(name: str) -> str:
    """Get human-readable description for a model."""
    entry = MODEL_CATALOG.get(name)
    return entry["desc"] if entry else ""


# === Defaults ===
DEFAULT_MODEL = "anime-n3"


# Special model constants
MODEL_PILLOW = "__pillow__"  # force Pillow LANCZOS (no GPU)
WAIFU2X_TILE_SIZE = 400
WAIFU2X_TTA = False
WAIFU2X_OUTPUT_FORMAT = "jpg"


# === Calibre ===
def find_calibre_debug() -> str | None:
    if platform.system() == "Darwin":
        path = "/Applications/calibre.app/Contents/MacOS/calibre-debug"
        if os.path.isfile(path):
            return path
    elif platform.system() == "Windows":
        for candidate in [
            os.path.expandvars(r"%ProgramFiles%\Calibre2\calibre-debug.exe"),
            os.path.expandvars(r"%ProgramFiles(x86)%\Calibre2\calibre-debug.exe"),
        ]:
            if os.path.isfile(candidate):
                return candidate
    return shutil.which("calibre-debug")


def find_sr_vulkan():
    try:
        import importlib
        spec = importlib.util.find_spec("sr_vulkan")
        return spec is not None
    except Exception:
        return False


# === Supported Formats ===
SUPPORTED_INPUT_FORMATS = {".epub", ".mobi", ".azw", ".azw3", ".pdf", ".cbz", ".zip"}


# === EPUB Generation ===
EPUB_CONTAINER_XML = '''<?xml version="1.0" encoding="UTF-8"?>
<container version="1.0"
  xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
  <rootfiles>
    <rootfile full-path="OEBPS/content.opf"
      media-type="application/oebps-package+xml"/>
  </rootfiles>
</container>'''


def optimal_workers() -> int:
    """Return reasonable worker count for CPU-bound image tasks.

    Rule:
      ≤4 logical cores: use all
      5-8 cores: leave one for system
      9+ cores: cap at 8 (diminishing returns)
    """
    cores = os.cpu_count() or 4
    if cores <= 4:
        return cores
    elif cores <= 8:
        return cores - 1
    else:
        return 8


def ensure_dirs():
    for d in [WORK_DIR, CACHE_DIR, TEMP_DIR]:
        os.makedirs(d, exist_ok=True)
