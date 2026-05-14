"""KCC-style MOBI comic display options."""

from __future__ import annotations

from dataclasses import asdict, dataclass


DEVICE_PROFILES: dict[str, tuple[str, tuple[int, int]]] = {
    "K1": ("Kindle 1", (600, 670)),
    "K2": ("Kindle 2", (600, 670)),
    "K11": ("Kindle 11", (1072, 1448)),
    "K34": ("Kindle Keyboard/Touch", (600, 800)),
    "K57": ("Kindle 5/7", (600, 800)),
    "K810": ("Kindle 8/10", (600, 800)),
    "KDX": ("Kindle DX/DXG", (824, 1000)),
    "KPW": ("Kindle Paperwhite 1/2", (758, 1024)),
    "KV": ("Kindle Voyage", (1072, 1448)),
    "KPW34": ("Kindle Paperwhite 3/4", (1072, 1448)),
    "KPW5": ("Kindle Paperwhite 5/Signature Edition", (1236, 1648)),
    "KPW6": ("Kindle Paperwhite 6", (1272, 1696)),
    "KO": ("Kindle Oasis 2/3", (1264, 1680)),
    "KCS": ("Kindle Colorsoft", (1272, 1696)),
    "KS1860": ("Kindle 1860", (1860, 1920)),
    "KS1920": ("Kindle 1920", (1920, 1920)),
    "KS1240": ("Kindle 1240", (1240, 1860)),
    "KS1324": ("Kindle 1324", (1324, 1986)),
    "KS": ("Kindle Scribe 1/2", (1860, 2480)),
    "KS3": ("Kindle Scribe 3", (1986, 2648)),
    "KSCS": ("Kindle Scribe Colorsoft", (1986, 2648)),
    "KoMT": ("Kobo Mini/Touch", (600, 800)),
    "KoG": ("Kobo Glo", (768, 1024)),
    "KoGHD": ("Kobo Glo HD", (1072, 1448)),
    "KoA": ("Kobo Aura", (758, 1024)),
    "KoAHD": ("Kobo Aura HD", (1080, 1440)),
    "KoAH2O": ("Kobo Aura H2O", (1080, 1430)),
    "KoAO": ("Kobo Aura ONE", (1404, 1872)),
    "KoN": ("Kobo Nia", (758, 1024)),
    "KoC": ("Kobo Clara HD/Kobo Clara 2E", (1072, 1448)),
    "KoCC": ("Kobo Clara Colour", (1072, 1448)),
    "KoL": ("Kobo Libra H2O/Kobo Libra 2", (1264, 1680)),
    "KoLC": ("Kobo Libra Colour", (1264, 1680)),
    "KoF": ("Kobo Forma", (1440, 1920)),
    "KoS": ("Kobo Sage", (1440, 1920)),
    "KoE": ("Kobo Elipsa", (1404, 1872)),
    "Rmk1": ("reMarkable 1", (1404, 1872)),
    "Rmk2": ("reMarkable 2", (1404, 1872)),
    "RmkPP": ("reMarkable Paper Pro", (1620, 2160)),
    "RmkPPMove": ("reMarkable Paper Pro Move", (954, 1696)),
    "OTHER": ("自定义设备", (0, 0)),
}


@dataclass
class MobiComicOptions:
    device_profile: str = "KPW5"
    custom_width: int = 0
    custom_height: int = 0
    manga_style: bool = True
    upscale: bool = False
    stretch: bool = False
    cropping: int = 2
    cropping_power: float = 1.0
    preserve_margin: float = 0.0
    cropping_minimum: float = 0.0
    splitter: int = 0
    inter_panel_crop: int = 0
    hq: bool = False
    two_panel: bool = False
    webtoon: bool = False
    autolevel: bool = False
    no_autocontrast: bool = False
    color_autocontrast: bool = False
    black_borders: bool = False
    white_borders: bool = False
    smart_cover_crop: bool = False
    cover_fill: bool = False
    force_color: bool = False
    force_png: bool = False
    force_png_rgb: bool = False
    png_legacy: bool = False
    no_quantize: bool = False
    jpeg_quality: int = 85
    maximize_strips: bool = False
    spread_shift: bool = False
    no_rotate: bool = False
    rotate_right: bool = False
    rotate_first: bool = False
    file_fusion: bool = False
    target_size_mb: int = 400

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict | None) -> "MobiComicOptions":
        values = cls().to_dict()
        if data:
            values.update({key: value for key, value in data.items() if key in values})
        return cls(**values)

    @property
    def device_label(self) -> str:
        return DEVICE_PROFILES.get(self.device_profile, DEVICE_PROFILES["KPW5"])[0]

    @property
    def resolution(self) -> tuple[int, int]:
        return resolve_device_profile(self.device_profile, self.custom_width, self.custom_height)

    def is_default(self) -> bool:
        return self.to_dict() == MobiComicOptions().to_dict()


KCC_OPTION_LABELS_ZH: dict[str, str] = {
    "device_profile": "设备型号",
    "custom_width": "自定义宽度",
    "custom_height": "自定义高度",
    "manga_style": "日漫模式",
    "upscale": "放大小图到设备分辨率",
    "stretch": "拉伸到全屏",
    "cropping": "裁边模式",
    "cropping_power": "裁边强度",
    "preserve_margin": "保留边距",
    "cropping_minimum": "最小裁剪面积比例",
    "splitter": "双页处理",
    "inter_panel_crop": "格间空白裁剪",
    "hq": "高质量放大",
    "two_panel": "面板视图使用两格",
    "webtoon": "条漫模式",
    "autolevel": "自动黑场校正",
    "no_autocontrast": "禁用自动对比度",
    "color_autocontrast": "彩页强制自动对比度",
    "black_borders": "强制黑边检测",
    "white_borders": "强制白边检测",
    "smart_cover_crop": "智能封面裁切",
    "cover_fill": "封面铺满屏幕",
    "force_color": "保留彩色",
    "force_png": "黑白页输出 PNG",
    "force_png_rgb": "彩色页强制 PNG",
    "png_legacy": "兼容 8-bit PNG",
    "no_quantize": "禁用 PNG 16 色量化",
    "jpeg_quality": "JPEG 质量",
    "maximize_strips": "条带页转 2x2",
    "spread_shift": "对开页首屏偏移",
    "no_rotate": "不旋转双页",
    "rotate_right": "双页反向旋转",
    "rotate_first": "旋转页优先",
    "file_fusion": "合并输入为单本",
    "target_size_mb": "目标文件大小 MB",
}


CROPPING_LABELS_ZH = {
    0: "不裁边",
    1: "裁白边",
    2: "裁白边和页码区域",
}


SPLITTER_LABELS_ZH = {
    0: "拆分",
    1: "旋转",
    2: "拆分并旋转",
}


INTER_PANEL_CROP_LABELS_ZH = {
    0: "关闭",
    1: "水平",
    2: "水平和垂直",
}


def resolve_device_profile(
    profile: str,
    custom_width: int = 0,
    custom_height: int = 0,
) -> tuple[int, int]:
    if profile == "OTHER":
        if custom_width <= 0 or custom_height <= 0:
            raise ValueError("自定义设备需要填写宽度和高度")
        return custom_width, custom_height
    if profile not in DEVICE_PROFILES:
        raise ValueError(f"未知设备型号: {profile}")
    return DEVICE_PROFILES[profile][1]


def device_profile_options() -> list[tuple[str, str]]:
    return [(f"{code} - {label} ({size[0]}x{size[1]})", code) for code, (label, size) in DEVICE_PROFILES.items()]
