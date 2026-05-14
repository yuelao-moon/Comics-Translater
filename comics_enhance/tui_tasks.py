"""Task planning, scanning, previews, and safety checks for the Textual TUI."""

from __future__ import annotations

import glob
import os
import re
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path

from comics_enhance.config import SUPPORTED_INPUT_FORMATS, find_calibre_debug, find_ebook_convert, find_kindlegen
from comics_enhance.mobi_options import (
    CROPPING_LABELS_ZH,
    INTER_PANEL_CROP_LABELS_ZH,
    MobiComicOptions,
    SPLITTER_LABELS_ZH,
)
from comics_enhance.packers import SUPPORTED_OUTPUT_FORMATS, parse_output_formats
from comics_enhance.tui_settings import ExistingOutputPolicy, OutputDirectoryMode, TuiSettings


IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp"}


class TaskMode(str, Enum):
    FULL = "full"
    EXTRACT_ONLY = "extract_only"
    ENHANCE_ONLY = "enhance_only"


@dataclass
class SourceScan:
    files: list[str]
    total_files: int


@dataclass
class ImageFolderScan:
    folders: list[str]
    folder_images: dict[str, list[str]]
    total_images: int


@dataclass
class SafetyIssue:
    title: str
    detail: str
    suggestion: str
    blocking: bool = True


@dataclass
class SafetyReport:
    issues: list[SafetyIssue] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not any(issue.blocking for issue in self.issues)

    def add(self, title: str, detail: str, suggestion: str, blocking: bool = True) -> None:
        self.issues.append(SafetyIssue(title, detail, suggestion, blocking))


@dataclass
class TaskConfig:
    mode: TaskMode
    input_paths: list[str]
    output_dir: str
    settings: TuiSettings
    output_formats: list[str] = field(default_factory=lambda: ["epub"])
    image_format: str = "jpg"
    enhance_enabled: bool = True
    enhance_preset: str = "smart"
    model_name: str = "anime-n3"
    tta: bool = False
    tile_size: int = 0
    reading_direction: str = "rtl"
    language: str = "zh"
    pack_after_enhance: bool = False
    merge_folders: bool = False
    merged_title: str = ""
    keep_enhanced_images: bool = True
    mobi_options: MobiComicOptions = field(default_factory=MobiComicOptions)
    kfx_virtual_panels: str = "off"
    kfx_facing_pages: bool = False
    kfx_facing_start: str = "single"

    @classmethod
    def from_settings(
        cls,
        mode: TaskMode,
        input_paths: list[str],
        settings: TuiSettings,
        output_dir: str | None = None,
    ) -> "TaskConfig":
        pack_after = mode is TaskMode.ENHANCE_ONLY and settings.enhance_pack_policy != "none"
        formats = settings.full_output_formats if mode is TaskMode.FULL else [settings.pack_format]
        return cls(
            mode=mode,
            input_paths=input_paths,
            output_dir=output_dir or plan_output_dir(mode, settings, settings.extract_enhance_default, pack_after),
            settings=settings,
            output_formats=parse_output_formats(formats or ["epub"]),
            image_format=settings.image_format,
            enhance_enabled=settings.enhance_preset != "none",
            enhance_preset=settings.enhance_preset,
            model_name=settings.manual_model,
            tta=settings.tta,
            tile_size=settings.tile_size,
            reading_direction=settings.reading_direction,
            language=settings.language,
            pack_after_enhance=pack_after,
            merge_folders=settings.enhance_pack_policy == "merge",
            keep_enhanced_images=settings.keep_enhanced_images,
            mobi_options=MobiComicOptions.from_dict(settings.mobi_options.to_dict() if settings.mobi_options else None),
            kfx_virtual_panels=settings.kfx_virtual_panels,
            kfx_facing_pages=settings.kfx_facing_pages,
            kfx_facing_start=settings.kfx_facing_start,
        )


def plan_output_dir(
    mode: TaskMode,
    settings: TuiSettings,
    enhance_after_extract: bool | None = None,
    pack_after_enhance: bool | None = None,
    first_input_path: str | None = None,
) -> str:
    if settings.output_directory_mode == OutputDirectoryMode.NEXT_TO_INPUT.value and first_input_path:
        base = os.path.join(os.path.dirname(os.path.abspath(first_input_path)), "output")
    else:
        base = settings.output_dir

    if not settings.categorized_subdirs:
        return base
    if mode is TaskMode.FULL:
        return os.path.join(base, "packed")
    if mode is TaskMode.EXTRACT_ONLY:
        return os.path.join(base, "enhanced" if enhance_after_extract else "extracted")
    if mode is TaskMode.ENHANCE_ONLY:
        return os.path.join(base, "packed" if pack_after_enhance else "enhanced")
    return base


def scan_source_files(patterns: list[str]) -> SourceScan:
    files: list[str] = []
    seen: set[str] = set()
    for pattern in patterns:
        matches = glob.glob(pattern)
        if not matches and os.path.isfile(pattern):
            matches = [pattern]
        for match in matches:
            path = os.path.abspath(match)
            if path in seen or not os.path.isfile(path):
                continue
            if Path(path).suffix.lower() in SUPPORTED_INPUT_FORMATS:
                files.append(path)
                seen.add(path)
    files.sort(key=_natural_key)
    return SourceScan(files=files, total_files=len(files))


def scan_image_folders(folders: list[str]) -> ImageFolderScan:
    normalized: list[str] = []
    folder_images: dict[str, list[str]] = {}
    total = 0
    for folder in folders:
        folder_path = os.path.abspath(folder)
        if not os.path.isdir(folder_path):
            continue
        images = [
            os.path.join(folder_path, name)
            for name in os.listdir(folder_path)
            if os.path.isfile(os.path.join(folder_path, name))
            and Path(name).suffix.lower() in IMAGE_EXTENSIONS
        ]
        images.sort(key=lambda p: _natural_key(os.path.basename(p)))
        if images:
            normalized.append(folder_path)
            folder_images[folder_path] = images
            total += len(images)
    normalized.sort(key=_natural_key)
    return ImageFolderScan(folders=normalized, folder_images=folder_images, total_images=total)


def run_safety_checks(config: TaskConfig) -> SafetyReport:
    report = SafetyReport()
    output_dir = os.path.abspath(config.output_dir)

    parent = os.path.dirname(output_dir) or output_dir
    if os.path.exists(parent) and not os.access(parent, os.W_OK):
        report.add("输出目录不可写", output_dir, "请选择有写入权限的输出目录。")

    _check_same_format_output(config, output_dir, report)
    _check_existing_outputs(config, output_dir, report)
    _check_dependencies(config, report)
    _check_enhance_output_overlap(config, output_dir, report)
    return report


def build_preview(config: TaskConfig) -> str:
    mode_labels = {
        TaskMode.FULL: "完整处理",
        TaskMode.EXTRACT_ONLY: "只解包",
        TaskMode.ENHANCE_ONLY: "只增强",
    }
    lines = [
        f"模式: {mode_labels[config.mode]}",
        f"输入: {len(config.input_paths)} 项",
        f"输出目录: {config.output_dir}",
    ]
    if config.mode is not TaskMode.EXTRACT_ONLY or config.pack_after_enhance:
        lines.append("输出格式: " + ", ".join(fmt.upper() for fmt in config.output_formats))
    if config.mode is TaskMode.ENHANCE_ONLY and not config.pack_after_enhance:
        lines.append("输出: 增强图片文件夹")
    lines.append("增强: " + ("启用" if config.enhance_enabled else "跳过"))
    lines.append(f"阅读方向: {config.reading_direction.upper()}")
    lines.append(f"语言: {config.language}")
    if "mobi" in config.output_formats:
        width, height = config.mobi_options.resolution
        lines.extend([
            f"MOBI 设备: {config.mobi_options.device_label} ({width}x{height})",
            "MOBI 裁边: " + CROPPING_LABELS_ZH.get(config.mobi_options.cropping, str(config.mobi_options.cropping)),
            "拉伸到全屏: " + ("是" if config.mobi_options.stretch else "否"),
            "放大小图: " + ("是" if config.mobi_options.upscale else "否"),
            "双页处理: " + SPLITTER_LABELS_ZH.get(config.mobi_options.splitter, str(config.mobi_options.splitter)),
            "格间空白裁剪: " + INTER_PANEL_CROP_LABELS_ZH.get(config.mobi_options.inter_panel_crop, str(config.mobi_options.inter_panel_crop)),
        ])
    if "kfx" in config.output_formats:
        lines.extend([
            "KFX 虚拟面板: " + {"off": "关闭", "horizontal": "水平", "vertical": "垂直"}.get(config.kfx_virtual_panels, config.kfx_virtual_panels),
            "KFX 横屏对开页: " + ("开启" if config.kfx_facing_pages else "关闭"),
            "KFX 对开页起始: " + ("封面单页" if config.kfx_facing_start == "single" else "第一页直接配对"),
        ])
    return "\n".join(lines)


def expected_output_paths(config: TaskConfig) -> list[str]:
    if config.mode is TaskMode.EXTRACT_ONLY and not config.pack_after_enhance:
        return []
    paths: list[str] = []
    for input_path in config.input_paths:
        stem = config.merged_title or Path(input_path).stem
        for fmt in config.output_formats:
            paths.append(os.path.join(config.output_dir, f"{stem}.{fmt}"))
    return paths


def _check_same_format_output(config: TaskConfig, output_dir: str, report: SafetyReport) -> None:
    if config.settings.same_format_policy != "block":
        return
    for input_path in config.input_paths:
        source_ext = Path(input_path).suffix.lower().lstrip(".")
        if source_ext in config.output_formats and os.path.abspath(os.path.dirname(input_path)) == output_dir:
            report.add(
                "同格式同目录输出被阻止",
                f"{input_path} 会输出到同目录的 .{source_ext} 文件。",
                "请修改输出目录或输出格式，避免覆盖源文件。",
            )


def _check_existing_outputs(config: TaskConfig, output_dir: str, report: SafetyReport) -> None:
    if config.settings.existing_output_policy != ExistingOutputPolicy.ERROR.value:
        return
    for output_path in expected_output_paths(config):
        if os.path.exists(output_path):
            report.add(
                "输出文件已存在",
                output_path,
                "请选择自动添加序号、修改输出目录，或手动删除已有文件。",
            )


def _check_dependencies(config: TaskConfig, report: SafetyReport) -> None:
    input_exts = {Path(path).suffix.lower() for path in config.input_paths}
    if input_exts & {".mobi", ".azw", ".azw3", ".pdf"} and not find_calibre_debug():
        report.add("Calibre 依赖缺失", "PDF/MOBI/AZW 输入需要 Calibre。", "安装 Calibre 后重试。")
    if "mobi" in config.output_formats and not (find_ebook_convert() or find_kindlegen()):
        report.add("MOBI 输出依赖缺失", "MOBI 输出需要 ebook-convert 或 kindlegen。", "安装 Calibre 或配置 KINDLEGEN_PATH。")
    if "kfx" in config.output_formats and not find_calibre_debug():
        report.add("KFX 输出依赖缺失", "KFX 输出需要 Calibre 和 KFX Output 插件。", "安装 Calibre 与 KFX Output 插件。")
    if "mobi" in config.output_formats and config.mobi_options.device_profile == "OTHER":
        try:
            config.mobi_options.resolution
        except ValueError as exc:
            report.add("MOBI 自定义设备尺寸缺失", str(exc), "填写自定义宽度和高度，或选择内置阅读器型号。")


def _check_enhance_output_overlap(config: TaskConfig, output_dir: str, report: SafetyReport) -> None:
    if config.mode is not TaskMode.ENHANCE_ONLY or config.pack_after_enhance:
        return
    for input_path in config.input_paths:
        abs_input = os.path.abspath(input_path)
        if os.path.isdir(abs_input) and output_dir == abs_input:
            report.add("增强输出会覆盖输入目录", abs_input, "请选择不同输出目录，或确认覆盖策略。")
        elif os.path.isdir(abs_input) and output_dir.startswith(abs_input + os.sep):
            report.add("增强输出位于输入目录内部", output_dir, "建议输出到独立目录。", blocking=False)


def _natural_key(value: str) -> list[int | str]:
    return [int(part) if part.isdigit() else part.lower() for part in re.split(r"(\d+)", value)]
