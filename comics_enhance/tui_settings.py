"""Persistent settings for the Textual TUI."""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
from enum import Enum

from comics_enhance.config import WORK_DIR
from comics_enhance.mobi_options import MobiComicOptions


SETTINGS_FILE = os.path.join(WORK_DIR, "settings.json")


class OutputDirectoryMode(str, Enum):
    FIXED = "fixed"
    NEXT_TO_INPUT = "next_to_input"
    ASK_EACH_TIME = "ask_each_time"


class ExistingOutputPolicy(str, Enum):
    ERROR = "error"
    AUTO_RENAME = "auto_rename"
    CONFIRM_OVERWRITE = "confirm_overwrite"


@dataclass
class TuiSettings:
    output_dir: str
    output_directory_mode: str = OutputDirectoryMode.FIXED.value
    categorized_subdirs: bool = True
    full_output_formats: list[str] | None = None
    image_format: str = "jpg"
    unpack_image_policy: str = "original"
    enhance_preset: str = "smart"
    manual_model: str = "anime-n3"
    tta: bool = False
    tile_size: int = 0
    reading_direction: str = "rtl"
    language: str = "zh"
    extract_enhance_default: bool = False
    enhance_pack_policy: str = "none"
    pack_format: str = "cbz"
    keep_enhanced_images: bool = True
    same_format_policy: str = "block"
    existing_output_policy: str = ExistingOutputPolicy.ERROR.value
    mobi_options: MobiComicOptions | None = None
    kfx_virtual_panels: str = "off"
    kfx_facing_pages: bool = False
    kfx_facing_start: str = "single"

    def __post_init__(self) -> None:
        if self.full_output_formats is None:
            self.full_output_formats = ["epub"]
        if self.mobi_options is None:
            self.mobi_options = MobiComicOptions()
        elif isinstance(self.mobi_options, dict):
            self.mobi_options = MobiComicOptions.from_dict(self.mobi_options)

    @classmethod
    def default(cls, work_dir: str | None = None) -> "TuiSettings":
        base = work_dir or WORK_DIR
        return cls(output_dir=os.path.join(base, "output"))

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict, work_dir: str | None = None) -> "TuiSettings":
        defaults = cls.default(work_dir).to_dict()
        defaults.update(data)
        defaults["mobi_options"] = MobiComicOptions.from_dict(defaults.get("mobi_options"))
        return cls(**defaults)

    def summary_rows(self) -> list[tuple[str, str]]:
        full_formats = ", ".join(fmt.upper() for fmt in (self.full_output_formats or ["epub"]))
        return [
            ("输出目录", self.output_dir),
            ("完整处理", f"{full_formats} + {preset_label(self.enhance_preset)}"),
            ("只解包", "解包并增强" if self.extract_enhance_default else "保留原始图片"),
            ("只增强", enhance_pack_policy_label(self.enhance_pack_policy)),
            ("阅读方向", self.reading_direction.upper()),
            ("MOBI 设备", self.mobi_options.device_label if self.mobi_options else "Kindle Paperwhite 5/Signature Edition"),
            ("KFX", f"虚拟面板 {self.kfx_virtual_panels} / 对开页 {'开' if self.kfx_facing_pages else '关'}"),
        ]


def preset_label(value: str) -> str:
    return {
        "smart": "智能增强",
        "mono": "黑白漫画",
        "color": "彩色漫画",
        "quality": "高质量精修",
        "photo": "照片写实",
        "manual": "手动模型",
        "none": "不增强",
    }.get(value, value)


def enhance_pack_policy_label(value: str) -> str:
    return {
        "none": "不打包，只输出增强图片",
        "separate": "每个文件夹单独打包",
        "merge": "合并所有文件夹打包为一本",
    }.get(value, value)


def load_settings(path: str = SETTINGS_FILE, work_dir: str | None = None) -> TuiSettings:
    if not os.path.isfile(path):
        return TuiSettings.default(work_dir)
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return TuiSettings.from_dict(data, work_dir)
    except Exception:
        return TuiSettings.default(work_dir)


def save_settings(settings: TuiSettings, path: str = SETTINGS_FILE) -> None:
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(settings.to_dict(), f, ensure_ascii=False, indent=2)


def reset_settings(path: str = SETTINGS_FILE, work_dir: str | None = None) -> TuiSettings:
    settings = TuiSettings.default(work_dir)
    save_settings(settings, path)
    return settings
