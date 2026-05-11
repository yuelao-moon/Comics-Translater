"""Waifu2x image enhancement module.

Wraps sr_vulkan (waifu2x-ncnn-vulkan) for GPU-accelerated batch image processing.
Based on the pattern from JMComic-qt's TaskWaifu2x.

If sr_vulkan is unavailable, images pass through unchanged.
"""

import os
import time
from pathlib import Path
from typing import Callable, Optional


# ---- sr_vulkan availability ----

_sr_vulkan = None
_sr_available = False
_sr_error = ""

def _init_sr_vulkan():
    """Lazy-init sr_vulkan. Returns True if available.

    Proper init sequence from sr-vulkan docs:
      1. sr.init()           — initialize Vulkan runtime
      2. sr.initSet(gpuId=0) — select GPU 0
    Model weights installed via pip:
      pip install sr-vulkan-model-waifu2x
      pip install sr-vulkan-model-realesrgan
      pip install sr-vulkan-model-realcugan
      pip install sr-vulkan-model-realsr
    """
    global _sr_vulkan, _sr_available, _sr_error
    if _sr_vulkan is not None:
        return _sr_available
    try:
        from sr_vulkan import sr_vulkan as sr

        # Phase 1: init Vulkan
        init_ret = sr.init()
        if init_ret < 0:
            _sr_error = f"sr.init() returned {init_ret}"
            _sr_available = False
            return False

        # Phase 2: select GPU
        set_ret = sr.initSet(gpuId=0)
        if set_ret < 0:
            _sr_error = f"sr.initSet(gpuId=0) returned {set_ret}"
            _sr_available = False
            return False

        _sr_vulkan = sr
        _sr_available = True
        _sr_error = ""
    except ImportError:
        _sr_error = "sr_vulkan package not installed. Download from GitHub releases."
        _sr_available = False
    except Exception as e:
        _sr_error = f"sr_vulkan init failed: {e}"
        _sr_available = False
    return _sr_available


def is_waifu2x_available() -> bool:
    """Check if Waifu2x (sr_vulkan) is available."""
    return _init_sr_vulkan()


def get_waifu2x_error() -> str:
    """Get last Waifu2x error message."""
    _init_sr_vulkan()
    return _sr_error


# ---- Progress callback type ----
# callback(current_index, total_count, image_path)
ProgressCallback = Optional[Callable[[int, int, str], None]]


# ---- Core enhancement functions ----

def _get_output_ext(format_name: str) -> str:
    """Map format name to file extension."""
    fmts = {"jpg": ".jpg", "jpeg": ".jpg", "png": ".png",
            "webp": ".webp", "bmp": ".bmp"}
    return fmts.get(format_name.lower(), ".jpg")


def _pillow_upscale_batch(
    image_paths: list[str],
    output_dir: str,
    scale: int,
    output_format: str,
    jpeg_quality: int = 92,
    jpeg_subsampling: str = "444",
    progress_callback: ProgressCallback = None,
) -> list[str]:
    """Upscale images using Pillow LANCZOS resampling (CPU, multi-threaded).

    Uses ThreadPoolExecutor to process images in parallel.
    Worker count adapts to CPU cores via optimal_workers().

    Args:
        image_paths: Source image paths.
        output_dir: Output directory.
        scale: Integer upscale factor (1, 2, 4).
        output_format: "jpg", "png", "webp", "bmp".
        jpeg_quality: JPEG quality 1-100 (default 92).
        jpeg_subsampling: "444", "422", or "420" (default "444").
        progress_callback: Progress reporter.

    Returns:
        List of output image paths in order.
    """
    from PIL import Image
    from concurrent.futures import ThreadPoolExecutor, as_completed
    import threading
    from comics_enhance.config import optimal_workers

    total = len(image_paths)
    out_ext = _get_output_ext(output_format)

    # ── Build save kwargs ──
    fmt_lower = output_format.lower()
    save_kwargs = {}
    if fmt_lower in ("jpg", "jpeg"):
        save_kwargs["quality"] = max(1, min(100, jpeg_quality))
        save_kwargs["optimize"] = True
        sub_map = {"444": -1, "422": 0, "420": 1}
        save_kwargs["subsampling"] = sub_map.get(jpeg_subsampling, -1)
    elif fmt_lower == "png":
        save_kwargs["optimize"] = True
    elif fmt_lower == "webp":
        save_kwargs["quality"] = 85

    # ── Per-image worker ──
    _lock = threading.Lock()
    _completed = 0
    _results: dict[int, str] = {}
    num_workers = optimal_workers()
    fmt_label = fmt_lower.upper() if fmt_lower != "jpg" else "JPEG"

    def _worker(idx: int, src_path: str) -> tuple[int, str]:
        """Process one image, return (index, out_path)."""
        nonlocal _completed
        try:
            with Image.open(src_path) as img:
                if img.mode not in ("RGB", "RGBA"):
                    img = img.convert("RGB")

                w, h = img.size
                new_size = (w * scale, h * scale)
                resized = img.resize(new_size, Image.Resampling.LANCZOS)

                # Mild sharpening
                try:
                    from PIL import ImageFilter
                    resized = resized.filter(
                        ImageFilter.UnsharpMask(radius=1, percent=80, threshold=3)
                    )
                except Exception:
                    pass

                # Output path with dedup
                base_stem = Path(src_path).stem
                out_name = f"{base_stem}{out_ext}"
                out_path = os.path.join(output_dir, out_name)
                if os.path.exists(out_path):
                    out_name = f"{base_stem}_{idx}{out_ext}"
                    out_path = os.path.join(output_dir, out_name)

                # RGBA → RGB for JPEG
                save_img = resized
                if fmt_lower in ("jpg", "jpeg") and save_img.mode == "RGBA":
                    bg = Image.new("RGB", save_img.size, (255, 255, 255))
                    bg.paste(save_img, mask=save_img.split()[3])
                    save_img = bg

                save_img.save(out_path, format=fmt_label, **save_kwargs)

                # Print progress (thread-safe)
                with _lock:
                    _completed += 1
                    done = _completed
                print(f"    [{done}/{total}] {os.path.basename(src_path)} "
                      f"({w}x{h} → {new_size[0]}x{new_size[1]})")

                if progress_callback:
                    progress_callback(done, total, src_path)

                return idx, out_path

        except Exception as e:
            print(f"    [{idx+1}/{total}] Error {os.path.basename(src_path)}: {e}")
            # Fallback: copy original
            out_path = os.path.join(output_dir, Path(src_path).name)
            with open(src_path, "rb") as fin, open(out_path, "wb") as fout:
                fout.write(fin.read())
            with _lock:
                _completed += 1
            if progress_callback:
                progress_callback(_completed, total, src_path)
            return idx, out_path

    # ── Dispatch pool ──
    print(f"    Workers: {num_workers} (detected {os.cpu_count()} logical cores)")
    with ThreadPoolExecutor(max_workers=num_workers) as pool:
        futures = {pool.submit(_worker, i, p): i for i, p in enumerate(image_paths)}
        for future in as_completed(futures):
            idx, out_path = future.result()
            _results[idx] = out_path

    # ── Reassemble in original order ──
    return [_results[i] for i in range(total)]


def _batch_submit_and_collect(
    tasks: list[tuple[bytes, int]],
    model: int,
    scale: int,
    output_format: str,
    tile_size: int,
    base_task_id: int,
) -> dict[int, tuple[bytes, str, float]]:
    """Submit all tasks to sr_vulkan and collect results.

    Uses the proven pattern from JMComic-qt:
      1. sr.add(...) for each task
      2. sr.load(0) in a loop to collect completions

    Returns dict mapping task_id → (data, format, elapsed_seconds).
    """
    sr = _sr_vulkan
    task_start_times = {}
    pending = set()

    # Phase 1: Submit all
    for img_data, task_id in tasks:
        status = sr.add(img_data, model, task_id, scale,
                       format=output_format, tileSize=tile_size)
        if status <= 0:
            err = sr.getLastError()
            raise RuntimeError(f"Waifu2x add failed for task {task_id}: {err}")
        pending.add(task_id)
        task_start_times[task_id] = time.time()

    # Phase 2: Collect results (sr.load(0) blocks until a result is ready)
    results = {}
    timeout_per_task = 300  # 5 minutes per task

    while pending:
        start_wait = time.time()
        result = sr.load(0)  # Blocks until any task completes
        if not result or not result[0]:
            time.sleep(0.1)
            # Check timeout on the oldest pending task
            oldest = min(task_start_times[t] for t in pending)
            if time.time() - oldest > timeout_per_task:
                break
            continue

        data, fmt, tid, tick = result
        if tid in pending:
            pending.remove(tid)
            elapsed = time.time() - task_start_times[tid]
            results[tid] = (data, fmt or output_format, elapsed)
        del task_start_times[tid]

    # Clean up any remaining tasks
    if pending:
        try:
            sr.remove(list(pending))
        except Exception:
            pass

    return results


def enhance_image_sync(
    img_data: bytes,
    task_id: int,
    model: int = 1,
    scale: int = 2,
    output_format: str = "jpg",
    tile_size: int = 400,
    tta: bool = False,
) -> tuple[bytes, str, float]:
    """Enhance a single image synchronously via sr_vulkan.

    Uses the batch submit+collect pattern. For single images,
    submits one task and collects via sr.load(0).

    Args:
        img_data: Raw image bytes (JPEG/PNG).
        task_id: Unique task identifier (int).
        model: 0=anime, 1=photo, 2=cunet.
        scale: Upscale factor (1, 2, 4).
        output_format: "jpg", "png", "webp", "bmp".
        tile_size: GPU processing tile size (0=auto).
        tta: Test-time augmentation (higher quality, slower).

    Returns:
        Tuple of (enhanced_bytes, format_str, elapsed_seconds).
    """
    if not _init_sr_vulkan():
        return img_data, output_format, 0.0

    results = _batch_submit_and_collect(
        tasks=[(img_data, task_id)],
        model=model,
        scale=scale,
        output_format=output_format,
        tile_size=tile_size,
        base_task_id=task_id,
    )

    if task_id not in results:
        raise RuntimeError(f"Waifu2x failed for task {task_id}")

    return results[task_id]


def enhance_images_batch(
    image_paths: list[str],
    output_dir: str,
    model: int = 1,
    scale: int = 2,
    output_format: str = "jpg",
    tile_size: int = 400,
    tta: bool = False,
    jpeg_quality: int = 92,
    jpeg_subsampling: str = "444",
    force_pillow: bool = False,
    progress_callback: ProgressCallback = None,
) -> list[str]:
    """Enhance a batch of images via Waifu2x.

    When force_pillow=True, uses Pillow LANCZOS regardless of GPU availability.
    If sr_vulkan is unavailable and force_pillow=False, copies images as-is.

    Args:
        image_paths: List of paths to source images (sorted by page order).
        output_dir: Directory to save enhanced images.
        model: 0=anime, 1=photo, 2=cunet.
        scale: Upscale factor.
        output_format: Output image format.
        tile_size: GPU tile size.
        tta: TTA mode.
        progress_callback: Called as (current, total, path).

    Returns:
        List of output image paths (same order as input).
    """
    os.makedirs(output_dir, exist_ok=True)

    total = len(image_paths)
    output_paths = []

    # Force Pillow mode (user selected "pillow" model)
    if force_pillow:
        print(f"    Using Pillow LANCZOS upscale ({scale}x)...")
        return _pillow_upscale_batch(
            image_paths, output_dir, scale, output_format,
            jpeg_quality, jpeg_subsampling, progress_callback,
        )

    if not _init_sr_vulkan():
        print(f"    [Waifu2x not available] {_sr_error}")
        print(f"    Using Pillow LANCZOS upscale as fallback ({scale}x)...")
        return _pillow_upscale_batch(
            image_paths, output_dir, scale, output_format,
            jpeg_quality, jpeg_subsampling, progress_callback,
        )

    sr = _sr_vulkan
    out_ext = _get_output_ext(output_format)

    # Pre-read all images and build task list
    tasks = []
    task_meta = {}  # task_id -> (index, src_path, img_data, out_path)

    for i, src_path in enumerate(image_paths):
        with open(src_path, "rb") as f:
            img_data = f.read()

        if len(img_data) == 0:
            print(f"    Skipping empty image: {src_path}")
            output_paths.append(src_path)
            if progress_callback:
                progress_callback(i + 1, total, src_path)
            continue

        task_id = 1000 + i
        base_stem = Path(src_path).stem
        out_name = f"{base_stem}{out_ext}"
        out_path = os.path.join(output_dir, out_name)
        if os.path.exists(out_path):
            out_name = f"{base_stem}_{i}{out_ext}"
            out_path = os.path.join(output_dir, out_name)

        tasks.append((img_data, task_id))
        task_meta[task_id] = (i, src_path, img_data, out_path)

    if not tasks:
        return output_paths

    # Submit all and collect results in batch
    try:
        results = _batch_submit_and_collect(
            tasks=tasks,
            model=model,
            scale=scale,
            output_format=output_format,
            tile_size=tile_size,
            base_task_id=1000,
        )
    except Exception as e:
        print(f"    Batch submit failed: {e}")
        # Fall back: copy all originals
        for task_id, (i, src_path, img_data, out_path) in task_meta.items():
            with open(out_path, "wb") as f:
                f.write(img_data)
            output_paths.append(out_path)
            if progress_callback:
                progress_callback(i + 1, total, src_path)
        return output_paths

    # Process results in order
    ordered = []  # (index, src_path, out_path, data, tick)
    for task_id, (data, fmt, tick) in results.items():
        if task_id in task_meta:
            i, src_path, img_data, out_path = task_meta[task_id]
            ordered.append((i, src_path, out_path, data, tick))

    ordered.sort(key=lambda x: x[0])  # Maintain original order

    for i, src_path, out_path, data, tick in ordered:
        try:
            with open(out_path, "wb") as f:
                f.write(data)

            if tick > 0:
                print(f"    [{i+1}/{total}] {os.path.basename(src_path)} "
                      f"→ {os.path.basename(out_path)} ({tick:.1f}s)")
        except Exception as e:
            print(f"    [{i+1}/{total}] Error saving {os.path.basename(src_path)}: {e}")
            # Copy original as fallback
            _, _, img_data, _ = task_meta.get(1000 + i, (None, None, b"", None))
            if img_data:
                with open(out_path, "wb") as f:
                    f.write(img_data)

    # Fill output_paths in original order
    result_map = {1000 + t[0]: t[2] for t in ordered}
    for i in range(total):
        task_id = 1000 + i
        if task_id in result_map:
            output_paths.append(result_map[task_id])
        elif task_id in task_meta:
            # Task that didn't get enhanced (e.g. skipped)
            output_paths.append(task_meta[task_id][3])
        if progress_callback:
            progress_callback(i + 1, total, image_paths[i] if i < len(image_paths) else "")

    # Clean up any remaining GPU tasks
    try:
        remaining = [1000 + i for i in range(total)
                    if (1000 + i) not in results and (1000 + i) in task_meta]
        if remaining:
            sr.remove(remaining)
    except Exception:
        pass

    return output_paths


def get_image_dimensions(path: str) -> tuple[int, int]:
    """Get image width and height using Pillow."""
    from PIL import Image
    with Image.open(path) as img:
        return img.size  # (width, height)


def get_image_format(path: str) -> str:
    """Get image format string from file extension."""
    ext = Path(path).suffix.lower()
    fmt_map = {".jpg": "jpg", ".jpeg": "jpg", ".png": "png",
               ".webp": "webp", ".bmp": "bmp", ".gif": "gif"}
    return fmt_map.get(ext, "jpg")
