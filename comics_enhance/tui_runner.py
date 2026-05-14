"""Execution layer for Textual TUI task configurations."""

from __future__ import annotations

import os
import shutil
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from comics_enhance.config import get_model_id, is_pillow_model, model_scale
from comics_enhance.epub_extractor import extract_images, extract_metadata
from comics_enhance.packers import pack_outputs
from comics_enhance.tui_settings import ExistingOutputPolicy
from comics_enhance.tui_tasks import IMAGE_EXTENSIONS, TaskConfig, TaskMode, scan_image_folders
from comics_enhance.waifu2x_enhancer import enhance_images_batch


ProgressCallback = Callable[[str], None]


@dataclass
class TaskFailure:
    input_path: str
    reason: str
    suggestion: str = ""


@dataclass
class TaskResult:
    outputs: list[str] = field(default_factory=list)
    failures: list[TaskFailure] = field(default_factory=list)
    completed_items: int = 0
    elapsed_seconds: float = 0.0

    @property
    def success_count(self) -> int:
        return self.completed_items

    @property
    def fail_count(self) -> int:
        return len(self.failures)


def run_task(config: TaskConfig, progress: ProgressCallback | None = None) -> TaskResult:
    """Execute a planned TUI task and return a structured result."""
    start = time.time()
    result = TaskResult()

    if config.mode is TaskMode.ENHANCE_ONLY:
        _run_enhance_only(config, result, progress)
    else:
        for input_path in config.input_paths:
            try:
                if config.mode is TaskMode.FULL:
                    outputs = _run_full_single(config, input_path, progress)
                    result.outputs.extend(outputs)
                    result.completed_items += 1
                elif config.mode is TaskMode.EXTRACT_ONLY:
                    output_dir = _run_extract_single(config, input_path, progress)
                    result.outputs.append(output_dir)
                    result.completed_items += 1
            except Exception as exc:
                result.failures.append(TaskFailure(input_path, str(exc), _suggestion_for_error(str(exc))))

    result.elapsed_seconds = time.time() - start
    return result


def open_output_directory(path: str) -> tuple[bool, str]:
    """Open an output directory with the platform file manager."""
    directory = path if os.path.isdir(path) else os.path.dirname(path)
    if not directory:
        directory = "."
    try:
        if os.name == "nt":
            os.startfile(directory)  # type: ignore[attr-defined]
        elif sys_platform() == "darwin":
            import subprocess
            subprocess.Popen(["open", directory])
        else:
            import subprocess
            subprocess.Popen(["xdg-open", directory])
        return True, directory
    except Exception as exc:
        return False, f"{directory}: {exc}"


def _run_full_single(config: TaskConfig, input_path: str, progress: ProgressCallback | None) -> list[str]:
    _emit(progress, f"提取图片: {os.path.basename(input_path)}")
    with tempfile.TemporaryDirectory(prefix=f"comics_tui_{Path(input_path).stem}_") as tmp_root:
        image_dir = os.path.join(tmp_root, "extracted")
        os.makedirs(image_dir, exist_ok=True)
        image_paths, _ = extract_images(input_path, image_dir, tmp_dir=tmp_root)
        page_paths = _maybe_enhance(config, image_paths, os.path.join(tmp_root, "enhanced"), progress)
        metadata = extract_metadata(input_path)
        _emit(progress, "打包输出")
        basename = _safe_basename(config.output_dir, Path(input_path).stem, config.output_formats, config)
        return pack_outputs(
            image_paths=page_paths,
            output_dir=config.output_dir,
            basename=basename,
            metadata=metadata,
            formats=config.output_formats,
            language=config.language,
            reading_direction=config.reading_direction,
            virtual_panels=config.kfx_virtual_panels,
            facing_pages=config.kfx_facing_pages,
            facing_start=config.kfx_facing_start,
            mobi_options=config.mobi_options,
        )


def _run_extract_single(config: TaskConfig, input_path: str, progress: ProgressCallback | None) -> str:
    base_output = os.path.join(config.output_dir, Path(input_path).stem)
    os.makedirs(base_output, exist_ok=True)
    _emit(progress, f"解包: {os.path.basename(input_path)}")
    with tempfile.TemporaryDirectory(prefix=f"comics_extract_{Path(input_path).stem}_") as tmp_root:
        image_paths, _ = extract_images(input_path, base_output, tmp_dir=tmp_root)
        if config.enhance_enabled:
            enhanced_dir = os.path.join(config.output_dir, f"{Path(input_path).stem}_enhanced")
            _maybe_enhance(config, image_paths, enhanced_dir, progress)
            return enhanced_dir
    return base_output


def _run_enhance_only(config: TaskConfig, result: TaskResult, progress: ProgressCallback | None) -> None:
    scan = scan_image_folders(config.input_paths)
    if scan.total_images == 0:
        result.failures.append(TaskFailure(", ".join(config.input_paths), "No images found", "请选择包含图片的文件夹。"))
        return

    if config.merge_folders:
        all_images: list[str] = []
        for folder in scan.folders:
            all_images.extend(scan.folder_images[folder])
        with tempfile.TemporaryDirectory(prefix="comics_enhance_merge_") as tmp_root:
            enhanced_dir = os.path.join(tmp_root, "enhanced")
            enhanced = _maybe_enhance(config, all_images, enhanced_dir, progress)
            if config.pack_after_enhance:
                basename = config.merged_title or Path(scan.folders[0]).name
                basename = _safe_basename(config.output_dir, basename, config.output_formats, config)
                outputs = pack_outputs(
                    enhanced,
                    config.output_dir,
                    basename,
                    {"title": basename, "author": ""},
                    config.output_formats,
                    language=config.language,
                    reading_direction=config.reading_direction,
                    virtual_panels=config.kfx_virtual_panels,
                    facing_pages=config.kfx_facing_pages,
                    facing_start=config.kfx_facing_start,
                    mobi_options=config.mobi_options,
                )
                result.outputs.extend(outputs)
                result.completed_items += 1
            else:
                dest = os.path.join(config.output_dir, config.merged_title or "enhanced")
                _copy_images(enhanced, dest)
                result.outputs.append(dest)
                result.completed_items += 1
        return

    for folder in scan.folders:
        try:
            basename = Path(folder).name
            enhanced_dir = os.path.join(config.output_dir, basename)
            enhanced = _maybe_enhance(config, scan.folder_images[folder], enhanced_dir, progress)
            if config.pack_after_enhance:
                output_basename = _safe_basename(config.output_dir, basename, config.output_formats, config)
                outputs = pack_outputs(
                    enhanced,
                    config.output_dir,
                    output_basename,
                    {"title": basename, "author": ""},
                    config.output_formats,
                    language=config.language,
                    reading_direction=config.reading_direction,
                    virtual_panels=config.kfx_virtual_panels,
                    facing_pages=config.kfx_facing_pages,
                    facing_start=config.kfx_facing_start,
                    mobi_options=config.mobi_options,
                )
                result.outputs.extend(outputs)
                result.completed_items += 1
                if not config.keep_enhanced_images:
                    shutil.rmtree(enhanced_dir, ignore_errors=True)
            else:
                result.outputs.append(enhanced_dir)
                result.completed_items += 1
        except Exception as exc:
            result.failures.append(TaskFailure(folder, str(exc), _suggestion_for_error(str(exc))))


def _maybe_enhance(
    config: TaskConfig,
    image_paths: list[str],
    output_dir: str,
    progress: ProgressCallback | None,
) -> list[str]:
    if not config.enhance_enabled:
        return image_paths
    _emit(progress, f"增强 {len(image_paths)} 张图片")
    os.makedirs(output_dir, exist_ok=True)
    return enhance_images_batch(
        image_paths=image_paths,
        output_dir=output_dir,
        model=None if is_pillow_model(config.model_name) else get_model_id(config.model_name),
        scale=model_scale(config.model_name),
        output_format=config.image_format,
        tile_size=config.tile_size,
        tta=config.tta,
        force_pillow=is_pillow_model(config.model_name),
    )


def _copy_images(image_paths: list[str], output_dir: str) -> None:
    os.makedirs(output_dir, exist_ok=True)
    for idx, image_path in enumerate(image_paths, 1):
        ext = Path(image_path).suffix.lower()
        if ext not in IMAGE_EXTENSIONS:
            ext = ".jpg"
        shutil.copy2(image_path, os.path.join(output_dir, f"{idx:04d}{ext}"))


def _safe_basename(output_dir: str, basename: str, formats: list[str], config: TaskConfig) -> str:
    """Apply the TUI existing-output policy before packers create files."""
    if config.settings.existing_output_policy != ExistingOutputPolicy.AUTO_RENAME.value:
        return basename
    candidate = basename
    counter = 2
    while any(os.path.exists(os.path.join(output_dir, f"{candidate}.{fmt}")) for fmt in formats):
        candidate = f"{basename}_{counter}"
        counter += 1
    return candidate


def _emit(progress: ProgressCallback | None, message: str) -> None:
    if progress:
        progress(message)


def _suggestion_for_error(reason: str) -> str:
    lower = reason.lower()
    if "calibre" in lower:
        return "安装 Calibre 后重试。"
    if "kfx" in lower:
        return "确认 Calibre KFX Output 插件已安装。"
    if "no images" in lower or "图片" in reason:
        return "确认输入文件或文件夹包含可读取的图片。"
    return "请检查输入路径、输出目录和依赖环境。"


def sys_platform() -> str:
    import sys
    return sys.platform
