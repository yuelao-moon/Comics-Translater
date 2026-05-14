"""Textual task wizard for ComicsEnhance."""

from __future__ import annotations

import os
from typing import ClassVar

from textual.app import App, ComposeResult
from textual.containers import Container, Horizontal, VerticalScroll
from textual.screen import Screen
from textual.widgets import Button, Checkbox, Footer, Header, Input, Label, Select, Static

from comics_enhance.config import DEFAULT_MODEL, MODEL_CATALOG
from comics_enhance.mobi_options import (
    CROPPING_LABELS_ZH,
    INTER_PANEL_CROP_LABELS_ZH,
    MobiComicOptions,
    SPLITTER_LABELS_ZH,
    device_profile_options,
)
from comics_enhance.packers import parse_output_formats
from comics_enhance.tui_runner import TaskResult, open_output_directory, run_task
from comics_enhance.tui_settings import (
    ExistingOutputPolicy,
    TuiSettings,
    load_settings,
    reset_settings,
    save_settings,
)
from comics_enhance.tui_tasks import (
    TaskConfig,
    TaskMode,
    build_preview,
    plan_output_dir,
    run_safety_checks,
    scan_image_folders,
    scan_source_files,
)


HELP_TEXT = "Enter 确认 | Esc 返回 | ↑↓ 选择 | Tab 切换 | ? 帮助 | Ctrl+C 退出"


class ComicsEnhanceApp(App):
    """Main Textual application."""

    CSS_PATH = None
    CSS = """
    Horizontal {
        height: auto;
    }
    """
    BINDINGS: ClassVar = [
        ("q", "quit", "退出"),
        ("ctrl+c", "quit", "退出"),
        ("escape", "back", "返回"),
        ("?", "help", "帮助"),
    ]

    TITLE = "Comics Translater"
    SUB_TITLE = "漫画处理任务向导"

    def __init__(self, settings: TuiSettings | None = None):
        super().__init__()
        self.settings = settings or load_settings()
        self.current_config: TaskConfig | None = None
        self.last_result: TaskResult | None = None

    def on_mount(self) -> None:
        self.push_screen(HomeScreen())

    def action_back(self) -> None:
        if len(self.screen_stack) > 1:
            self.pop_screen()

    def action_help(self) -> None:
        self.notify(HELP_TEXT, title="帮助")

    def return_home(self) -> None:
        # Textual always keeps a base Screen at stack[0], and our HomeScreen
        # sits at stack[1].  Pop everything above HomeScreen, then replace
        # HomeScreen itself with a fresh instance so Textual fully re-renders it
        # (rapid pop_screen() calls without re-mounting leave the base Screen
        # visible, causing the black-screen bug).
        while len(self.screen_stack) > 2:
            self.pop_screen()
        self.switch_screen(HomeScreen())


class BaseScreen(Screen):
    """Shared screen helpers."""

    def frame(self, title: str, *children) -> ComposeResult:
        yield Header()
        with VerticalScroll(classes="page"):
            yield Static(title, classes="title")
            for child in children:
                yield child
        yield Static(HELP_TEXT, classes="status")
        yield Footer()

    @property
    def app_typed(self) -> ComicsEnhanceApp:
        return self.app  # type: ignore[return-value]

    def back(self) -> None:
        self.app_typed.action_back()


class HomeScreen(BaseScreen):
    def compose(self) -> ComposeResult:
        settings = self.app_typed.settings
        rows = "\n".join(f"{name}: {value}" for name, value in settings.summary_rows())
        actions = Container(
            Button("完整处理", id="full", variant="primary"),
            Button("只解包", id="extract"),
            Button("只增强", id="enhance"),
            Button("设置", id="settings"),
            Button("退出", id="quit"),
        )
        yield from self.frame(
            "Comics Translater",
            Static("当前默认设置\n" + rows, classes="panel"),
            Static("你想做什么？", classes="section"),
            actions,
        )

    def on_button_pressed(self, event: Button.Pressed) -> None:
        button_id = event.button.id
        if button_id == "quit":
            self.app.exit()
        elif button_id == "settings":
            self.app.push_screen(SettingsScreen())
        elif button_id in {"full", "extract", "enhance"}:
            mode = {
                "full": TaskMode.FULL,
                "extract": TaskMode.EXTRACT_ONLY,
                "enhance": TaskMode.ENHANCE_ONLY,
            }[button_id]
            self.app.push_screen(InputScreen(mode))


class InputScreen(BaseScreen):
    def __init__(self, mode: TaskMode):
        super().__init__()
        self.mode = mode

    def compose(self) -> ComposeResult:
        prompt = "输入漫画文件路径（支持通配符，空格分隔）"
        if self.mode is TaskMode.ENHANCE_ONLY:
            prompt = "输入图片文件夹路径（多个文件夹用 ; 分隔）"
        yield from self.frame(
            f"{_mode_label(self.mode)} > 选择输入",
            Label(prompt),
            Input(placeholder=prompt, id="input_paths"),
            Horizontal(Button("继续", id="continue", variant="primary"), Button("返回", id="back")),
        )

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "back":
            self.back()
            return
        raw = self.query_one("#input_paths", Input).value.strip()
        if not raw:
            self.notify("请输入路径。", severity="warning")
            return
        if self.mode is TaskMode.ENHANCE_ONLY:
            inputs = [part.strip() for part in raw.split(";") if part.strip()]
            scan = scan_image_folders(inputs)
            if scan.total_images == 0:
                self.notify("未找到图片文件夹。", severity="error")
                return
            input_paths = scan.folders
        else:
            scan = scan_source_files(raw.split())
            if scan.total_files == 0:
                self.notify("未找到支持的漫画文件。", severity="error")
                return
            input_paths = scan.files

        settings = self.app_typed.settings
        config = TaskConfig.from_settings(self.mode, input_paths, settings)
        config.output_dir = plan_output_dir(
            self.mode,
            settings,
            settings.extract_enhance_default,
            config.pack_after_enhance,
            input_paths[0],
        )
        self.app_typed.current_config = config
        self.app.push_screen(ConfigScreen())


class ConfigScreen(BaseScreen):
    """格式选择与基本配置页面（不含格式专属参数）。"""

    def compose(self) -> ComposeResult:
        config = self._config()
        show_formats = not (config.mode is TaskMode.EXTRACT_ONLY and not config.pack_after_enhance)
        format_hint = ""
        if show_formats:
            mobi_kfx = [f for f in config.output_formats if f in ("mobi", "kfx")]
            if mobi_kfx:
                format_hint = f"（选中 {'/'.join(f.upper() for f in mobi_kfx)} 后点击继续将进入专属参数页）"
        yield from self.frame(
            f"{_mode_label(config.mode)} > 配置",
            Static(_config_summary(config), classes="panel"),
            OutputFormatSelector(config),
            Static(format_hint, classes="panel") if format_hint else Static(""),
            Checkbox("启用增强", value=config.enhance_enabled, id="enhance_enabled"),
            Label("输出目录"),
            Input(value=config.output_dir, id="output_dir"),
            Horizontal(Button("继续", id="continue", variant="primary"), Button("返回", id="back")),
        )

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "back":
            self.back()
            return
        config = self._config()
        config.output_dir = self.query_one("#output_dir", Input).value.strip() or config.output_dir
        config.enhance_enabled = self.query_one("#enhance_enabled", Checkbox).value
        config.output_formats = self.query_one(OutputFormatSelector).selected_formats()

        if "mobi" in config.output_formats:
            self.app.push_screen(MobiOptionsScreen())
        elif "kfx" in config.output_formats:
            self.app.push_screen(KfxOptionsScreen())
        else:
            self.app.push_screen(SafetyScreen())

    def _config(self) -> TaskConfig:
        config = self.app_typed.current_config
        if config is None:
            raise RuntimeError("No active task config")
        return config


class MobiOptionsScreen(BaseScreen):
    """MOBI 漫画专属参数页面。"""

    def compose(self) -> ComposeResult:
        config = self._config()
        options = config.mobi_options
        yield from self.frame(
            "MOBI 漫画显示参数",
            Label("设备型号"),
            Select(device_profile_options(), value=options.device_profile, id="mobi_device_profile"),
            Label("自定义宽高（选择 OTHER 时使用）"),
            Horizontal(
                Input(value=str(options.custom_width), id="mobi_custom_width"),
                Input(value=str(options.custom_height), id="mobi_custom_height"),
            ),
            Checkbox("日漫模式（从右到左阅读/拆页）", value=options.manga_style, id="mobi_manga_style"),
            Checkbox("放大小图到设备分辨率", value=options.upscale, id="mobi_upscale"),
            Checkbox("拉伸到全屏（可能改变比例）", value=options.stretch, id="mobi_stretch"),
            Label("裁边模式"),
            Select(_int_options(CROPPING_LABELS_ZH), value=str(options.cropping), id="mobi_cropping"),
            Label("双页处理"),
            Select(_int_options(SPLITTER_LABELS_ZH), value=str(options.splitter), id="mobi_splitter"),
            Label("格间空白裁剪"),
            Select(_int_options(INTER_PANEL_CROP_LABELS_ZH), value=str(options.inter_panel_crop), id="mobi_inter_panel_crop"),
            Label("裁边强度 / 保留边距% / 最小裁剪面积比例"),
            Horizontal(
                Input(value=str(options.cropping_power), id="mobi_cropping_power"),
                Input(value=str(options.preserve_margin), id="mobi_preserve_margin"),
                Input(value=str(options.cropping_minimum), id="mobi_cropping_minimum"),
            ),
            Checkbox("高质量放大", value=options.hq, id="mobi_hq"),
            Checkbox("面板视图使用两格", value=options.two_panel, id="mobi_two_panel"),
            Checkbox("条漫模式", value=options.webtoon, id="mobi_webtoon"),
            Checkbox("自动黑场校正", value=options.autolevel, id="mobi_autolevel"),
            Checkbox("禁用自动对比度", value=options.no_autocontrast, id="mobi_no_autocontrast"),
            Checkbox("彩页强制自动对比度", value=options.color_autocontrast, id="mobi_color_autocontrast"),
            Checkbox("强制黑边检测", value=options.black_borders, id="mobi_black_borders"),
            Checkbox("强制白边检测", value=options.white_borders, id="mobi_white_borders"),
            Checkbox("智能封面裁切", value=options.smart_cover_crop, id="mobi_smart_cover_crop"),
            Checkbox("封面铺满屏幕", value=options.cover_fill, id="mobi_cover_fill"),
            Checkbox("保留彩色", value=options.force_color, id="mobi_force_color"),
            Checkbox("黑白页输出 PNG", value=options.force_png, id="mobi_force_png"),
            Checkbox("彩色页强制 PNG", value=options.force_png_rgb, id="mobi_force_png_rgb"),
            Checkbox("兼容 8-bit PNG", value=options.png_legacy, id="mobi_png_legacy"),
            Checkbox("禁用 PNG 16 色量化", value=options.no_quantize, id="mobi_no_quantize"),
            Label("JPEG 质量 / 目标大小 MB"),
            Horizontal(
                Input(value=str(options.jpeg_quality), id="mobi_jpeg_quality"),
                Input(value=str(options.target_size_mb), id="mobi_target_size_mb"),
            ),
            Checkbox("条带页转 2x2", value=options.maximize_strips, id="mobi_maximize_strips"),
            Checkbox("对开页首屏偏移", value=options.spread_shift, id="mobi_spread_shift"),
            Checkbox("不旋转双页", value=options.no_rotate, id="mobi_no_rotate"),
            Checkbox("双页反向旋转", value=options.rotate_right, id="mobi_rotate_right"),
            Checkbox("旋转页优先", value=options.rotate_first, id="mobi_rotate_first"),
            Checkbox("合并输入为单本", value=options.file_fusion, id="mobi_file_fusion"),
            Horizontal(Button("继续", id="continue", variant="primary"), Button("返回", id="back")),
        )

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "back":
            self.back()
            return
        self._apply()
        config = self._config()
        if "kfx" in config.output_formats:
            self.app.push_screen(KfxOptionsScreen())
        else:
            self.app.push_screen(SafetyScreen())

    def _apply(self) -> None:
        options = self._config().mobi_options
        options.device_profile = str(self.query_one("#mobi_device_profile", Select).value or "KPW5")
        options.custom_width = _input_int(self, "#mobi_custom_width", 0)
        options.custom_height = _input_int(self, "#mobi_custom_height", 0)
        options.manga_style = self.query_one("#mobi_manga_style", Checkbox).value
        options.upscale = self.query_one("#mobi_upscale", Checkbox).value
        options.stretch = self.query_one("#mobi_stretch", Checkbox).value
        options.cropping = _select_int(self, "#mobi_cropping", 2)
        options.splitter = _select_int(self, "#mobi_splitter", 0)
        options.inter_panel_crop = _select_int(self, "#mobi_inter_panel_crop", 0)
        options.cropping_power = _input_float(self, "#mobi_cropping_power", 1.0)
        options.preserve_margin = _input_float(self, "#mobi_preserve_margin", 0.0)
        options.cropping_minimum = _input_float(self, "#mobi_cropping_minimum", 0.0)
        for field in _MOBI_BOOL_FIELDS:
            setattr(options, field, self.query_one(f"#mobi_{field}", Checkbox).value)
        options.jpeg_quality = _input_int(self, "#mobi_jpeg_quality", 85)
        options.target_size_mb = _input_int(self, "#mobi_target_size_mb", 400)

    def _config(self) -> TaskConfig:
        config = self.app_typed.current_config
        if config is None:
            raise RuntimeError("No active task config")
        return config


class KfxOptionsScreen(BaseScreen):
    """KFX 阅读参数页面。"""

    def compose(self) -> ComposeResult:
        config = self._config()
        yield from self.frame(
            "KFX 阅读参数",
            Label("虚拟面板"),
            Select(
                [("关闭", "off"), ("水平", "horizontal"), ("垂直", "vertical")],
                value=config.kfx_virtual_panels,
                id="kfx_virtual_panels",
            ),
            Checkbox("横屏对开页", value=config.kfx_facing_pages, id="kfx_facing_pages"),
            Label("对开页起始方式"),
            Select(
                [("封面单页，然后 2+3", "single"), ("第一页直接配对 1+2", "double")],
                value=config.kfx_facing_start,
                id="kfx_facing_start",
            ),
            Horizontal(Button("继续", id="continue", variant="primary"), Button("返回", id="back")),
        )

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "back":
            self.back()
            return
        self._apply()
        self.app.push_screen(SafetyScreen())

    def _apply(self) -> None:
        config = self._config()
        config.kfx_virtual_panels = str(self.query_one("#kfx_virtual_panels", Select).value or "off")
        config.kfx_facing_pages = self.query_one("#kfx_facing_pages", Checkbox).value
        config.kfx_facing_start = str(self.query_one("#kfx_facing_start", Select).value or "single")

    def _config(self) -> TaskConfig:
        config = self.app_typed.current_config
        if config is None:
            raise RuntimeError("No active task config")
        return config


class OutputFormatSelector(Container):
    def __init__(self, config: TaskConfig):
        super().__init__()
        self.config = config

    def compose(self) -> ComposeResult:
        if self.config.mode is TaskMode.EXTRACT_ONLY and not self.config.pack_after_enhance:
            yield Static("输出格式: 图片文件夹")
            return
        yield Static("输出格式")
        for fmt in ("epub", "cbz", "mobi", "kfx"):
            yield Checkbox(fmt.upper(), value=fmt in self.config.output_formats, id=f"fmt_{fmt}")

    def selected_formats(self) -> list[str]:
        if self.config.mode is TaskMode.EXTRACT_ONLY and not self.config.pack_after_enhance:
            return self.config.output_formats
        selected = []
        for fmt in ("epub", "cbz", "mobi", "kfx"):
            checkbox = self.query_one(f"#fmt_{fmt}", Checkbox)
            if checkbox.value:
                selected.append(fmt)
        return selected or ["epub"]


class SafetyScreen(BaseScreen):
    def compose(self) -> ComposeResult:
        config = self.app_typed.current_config
        if config is None:
            raise RuntimeError("No active task config")
        report = run_safety_checks(config)
        self.report = report
        if report.ok:
            body = "安全检查：通过"
        else:
            body = "安全检查未通过\n\n" + "\n\n".join(
                f"{issue.title}\n{issue.detail}\n建议: {issue.suggestion}" for issue in report.issues
            )
        buttons = Horizontal(Button("继续", id="continue", variant="primary", disabled=not report.ok), Button("返回修改", id="back"))
        yield from self.frame("安全检查", Static(body, classes="panel"), buttons)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "back":
            self.back()
        elif event.button.id == "continue":
            self.app.push_screen(PreviewScreen())


class PreviewScreen(BaseScreen):
    def compose(self) -> ComposeResult:
        config = self.app_typed.current_config
        if config is None:
            raise RuntimeError("No active task config")
        yield from self.frame(
            "任务预览",
            Static(build_preview(config), classes="panel"),
            Horizontal(Button("开始执行", id="run", variant="success"), Button("返回修改", id="back")),
        )

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "back":
            self.back()
        elif event.button.id == "run":
            self.app.push_screen(RunningScreen())


class RunningScreen(BaseScreen):
    def compose(self) -> ComposeResult:
        yield from self.frame("执行中", Static("准备开始...", id="progress", classes="panel"))

    def on_mount(self) -> None:
        self.run_worker(self._execute, thread=True)

    def _execute(self) -> None:
        config = self.app_typed.current_config
        if config is None:
            raise RuntimeError("No active task config")

        def progress(message: str) -> None:
            self.app.call_from_thread(self._set_progress, message)

        result = run_task(config, progress)
        self.app_typed.last_result = result
        self.app.call_from_thread(self.app.push_screen, ResultScreen())

    def _set_progress(self, message: str) -> None:
        self.query_one("#progress", Static).update(message)


class ResultScreen(BaseScreen):
    def compose(self) -> ComposeResult:
        result = self.app_typed.last_result
        if result is None:
            body = "没有结果。"
        else:
            body = _result_summary(result)
        yield from self.frame(
            "处理完成",
            Static(body, classes="panel"),
            Horizontal(Button("打开输出目录", id="open"), Button("返回首页", id="home", variant="primary"), Button("退出", id="quit")),
        )

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "quit":
            self.app.exit()
        elif event.button.id == "home":
            self.app_typed.return_home()
        elif event.button.id == "open":
            config = self.app_typed.current_config
            if config:
                ok, message = open_output_directory(config.output_dir)
                if ok:
                    self.notify("已打开输出目录")
                else:
                    self.notify(message, severity="error")


class SettingsScreen(BaseScreen):
    def compose(self) -> ComposeResult:
        settings = self.app_typed.settings
        yield from self.frame(
            "设置",
            Static(_settings_text(settings), classes="panel"),
            Label("默认输出目录"),
            Input(value=settings.output_dir, id="settings_output_dir"),
            Label("默认完整处理输出格式（逗号分隔）"),
            Input(value=",".join(settings.full_output_formats or ["epub"]), id="settings_formats"),
            Checkbox("按任务分类输出到 packed / extracted / enhanced", value=settings.categorized_subdirs, id="settings_categorized"),
            Label("图片输出格式"),
            Select([("JPG", "jpg"), ("PNG", "png"), ("WebP", "webp")], value=settings.image_format, id="settings_image_format"),
            Label("增强方案"),
            Select(
                [
                    ("智能增强", "smart"),
                    ("黑白漫画", "mono"),
                    ("彩色漫画", "color"),
                    ("高质量精修", "quality"),
                    ("照片写实", "photo"),
                    ("手动模型", "manual"),
                    ("不增强", "none"),
                ],
                value=settings.enhance_preset,
                id="settings_enhance_preset",
            ),
            Label("手动模型"),
            Select(_model_options(), value=settings.manual_model, id="settings_manual_model"),
            Select(
                [("日漫 / 右到左 RTL", "rtl"), ("普通 / 左到右 LTR", "ltr")],
                value=settings.reading_direction,
                id="settings_direction",
            ),
            Label("语言"),
            Select([("中文", "zh"), ("日文", "ja"), ("英文", "en"), ("韩文", "ko")], value=settings.language, id="settings_language"),
            Label("只增强后的打包策略"),
            Select(
                [("不打包，只输出增强图片", "none"), ("逐文件夹打包", "separate"), ("合并打包", "merge")],
                value=settings.enhance_pack_policy,
                id="settings_enhance_pack_policy",
            ),
            Label("只增强打包格式"),
            Select([("CBZ", "cbz"), ("EPUB", "epub"), ("MOBI", "mobi"), ("KFX", "kfx")], value=settings.pack_format, id="settings_pack_format"),
            Static("MOBI 默认显示参数"),
            Label("默认设备型号"),
            Select(device_profile_options(), value=settings.mobi_options.device_profile, id="settings_mobi_device_profile"),
            Label("自定义宽高（选择 OTHER 时使用）"),
            Horizontal(
                Input(value=str(settings.mobi_options.custom_width), id="settings_mobi_custom_width"),
                Input(value=str(settings.mobi_options.custom_height), id="settings_mobi_custom_height"),
            ),
            Checkbox("默认日漫模式", value=settings.mobi_options.manga_style, id="settings_mobi_manga_style"),
            Checkbox("默认放大小图", value=settings.mobi_options.upscale, id="settings_mobi_upscale"),
            Checkbox("默认拉伸到全屏", value=settings.mobi_options.stretch, id="settings_mobi_stretch"),
            Checkbox("默认封面铺满屏幕", value=settings.mobi_options.cover_fill, id="settings_mobi_cover_fill"),
            Label("默认裁边模式"),
            Select(_int_options(CROPPING_LABELS_ZH), value=str(settings.mobi_options.cropping), id="settings_mobi_cropping"),
            Label("默认双页处理"),
            Select(_int_options(SPLITTER_LABELS_ZH), value=str(settings.mobi_options.splitter), id="settings_mobi_splitter"),
            Static("KFX 默认阅读参数"),
            Select([("虚拟面板关闭", "off"), ("虚拟面板水平", "horizontal"), ("虚拟面板垂直", "vertical")], value=settings.kfx_virtual_panels, id="settings_kfx_virtual_panels"),
            Checkbox("默认横屏对开页", value=settings.kfx_facing_pages, id="settings_kfx_facing_pages"),
            Select([("封面单页，然后 2+3", "single"), ("第一页直接配对 1+2", "double")], value=settings.kfx_facing_start, id="settings_kfx_facing_start"),
            Checkbox("只解包后默认继续增强", value=settings.extract_enhance_default, id="settings_extract_enhance"),
            Checkbox("保留只增强流程中的增强图片", value=settings.keep_enhanced_images, id="settings_keep_images"),
            Checkbox("阻止同格式同目录输出", value=settings.same_format_policy == "block", id="settings_same_format_block"),
            Label("输出文件已存在时"),
            Select(
                [("报错停止", ExistingOutputPolicy.ERROR.value), ("自动加序号", ExistingOutputPolicy.AUTO_RENAME.value), ("允许覆盖", ExistingOutputPolicy.CONFIRM_OVERWRITE.value)],
                value=settings.existing_output_policy,
                id="settings_existing_policy",
            ),
            Horizontal(Button("保存", id="save", variant="primary"), Button("恢复默认", id="reset"), Button("返回", id="back")),
        )

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "back":
            self.back()
            return
        if event.button.id == "reset":
            self.app_typed.settings = reset_settings()
            self.app.pop_screen()
            self.app.push_screen(SettingsScreen())
            return
        settings = self.app_typed.settings
        settings.output_dir = self.query_one("#settings_output_dir", Input).value.strip() or settings.output_dir
        raw_formats = self.query_one("#settings_formats", Input).value.strip()
        try:
            settings.full_output_formats = parse_output_formats(raw_formats or "epub")
        except ValueError as exc:
            self.notify(str(exc), severity="error")
            return
        settings.categorized_subdirs = self.query_one("#settings_categorized", Checkbox).value
        settings.image_format = str(self.query_one("#settings_image_format", Select).value or "jpg")
        settings.enhance_preset = str(self.query_one("#settings_enhance_preset", Select).value or "smart")
        settings.manual_model = str(self.query_one("#settings_manual_model", Select).value or DEFAULT_MODEL)
        settings.reading_direction = str(self.query_one("#settings_direction", Select).value or "rtl")
        settings.language = str(self.query_one("#settings_language", Select).value or "zh")
        settings.enhance_pack_policy = str(self.query_one("#settings_enhance_pack_policy", Select).value or "none")
        settings.pack_format = str(self.query_one("#settings_pack_format", Select).value or "cbz")
        settings.mobi_options.device_profile = str(self.query_one("#settings_mobi_device_profile", Select).value or "KPW5")
        settings.mobi_options.custom_width = _input_int(self, "#settings_mobi_custom_width", 0)
        settings.mobi_options.custom_height = _input_int(self, "#settings_mobi_custom_height", 0)
        settings.mobi_options.manga_style = self.query_one("#settings_mobi_manga_style", Checkbox).value
        settings.mobi_options.upscale = self.query_one("#settings_mobi_upscale", Checkbox).value
        settings.mobi_options.stretch = self.query_one("#settings_mobi_stretch", Checkbox).value
        settings.mobi_options.cover_fill = self.query_one("#settings_mobi_cover_fill", Checkbox).value
        settings.mobi_options.cropping = _select_int(self, "#settings_mobi_cropping", 2)
        settings.mobi_options.splitter = _select_int(self, "#settings_mobi_splitter", 0)
        settings.kfx_virtual_panels = str(self.query_one("#settings_kfx_virtual_panels", Select).value or "off")
        settings.kfx_facing_pages = self.query_one("#settings_kfx_facing_pages", Checkbox).value
        settings.kfx_facing_start = str(self.query_one("#settings_kfx_facing_start", Select).value or "single")
        settings.extract_enhance_default = self.query_one("#settings_extract_enhance", Checkbox).value
        settings.keep_enhanced_images = self.query_one("#settings_keep_images", Checkbox).value
        settings.same_format_policy = "block" if self.query_one("#settings_same_format_block", Checkbox).value else "allow"
        settings.existing_output_policy = str(self.query_one("#settings_existing_policy", Select).value or ExistingOutputPolicy.ERROR.value)
        save_settings(settings)
        self.notify("设置已保存。")


def run_tui() -> None:
    ComicsEnhanceApp().run()


_MOBI_BOOL_FIELDS = [
    "hq",
    "two_panel",
    "webtoon",
    "autolevel",
    "no_autocontrast",
    "color_autocontrast",
    "black_borders",
    "white_borders",
    "smart_cover_crop",
    "cover_fill",
    "force_color",
    "force_png",
    "force_png_rgb",
    "png_legacy",
    "no_quantize",
    "maximize_strips",
    "spread_shift",
    "no_rotate",
    "rotate_right",
    "rotate_first",
    "file_fusion",
]


def _int_options(labels: dict[int, str]) -> list[tuple[str, str]]:
    return [(label, str(value)) for value, label in labels.items()]


def _select_int(screen: Screen, selector: str, default: int) -> int:
    try:
        return int(str(screen.query_one(selector, Select).value))
    except (TypeError, ValueError):
        return default


def _input_int(screen: Screen, selector: str, default: int) -> int:
    try:
        return int(screen.query_one(selector, Input).value.strip())
    except ValueError:
        return default


def _input_float(screen: Screen, selector: str, default: float) -> float:
    try:
        return float(screen.query_one(selector, Input).value.strip())
    except ValueError:
        return default


def _model_options() -> list[tuple[str, str]]:
    options = [(f"{name} - {info.get('desc', '')}", name) for name, info in MODEL_CATALOG.items()]
    if not any(value == DEFAULT_MODEL for _, value in options):
        options.insert(0, (DEFAULT_MODEL, DEFAULT_MODEL))
    return options


def _mode_label(mode: TaskMode) -> str:
    return {
        TaskMode.FULL: "完整处理",
        TaskMode.EXTRACT_ONLY: "只解包",
        TaskMode.ENHANCE_ONLY: "只增强",
    }[mode]


def _config_summary(config: TaskConfig) -> str:
    lines = [
        f"模式: {_mode_label(config.mode)}",
        f"输入: {len(config.input_paths)} 项",
        f"输出目录: {config.output_dir}",
        f"输出格式: {', '.join(fmt.upper() for fmt in config.output_formats)}",
        f"增强: {'启用' if config.enhance_enabled else '跳过'}",
    ]
    return "\n".join(lines)


def _settings_text(settings: TuiSettings) -> str:
    return "\n".join(f"{name}: {value}" for name, value in settings.summary_rows())


def _result_summary(result: TaskResult) -> str:
    lines = [
        f"成功: {result.success_count}",
        f"失败: {result.fail_count}",
        f"耗时: {result.elapsed_seconds:.1f}s",
        "",
        "成功列表:",
    ]
    lines.extend(result.outputs or ["(无)"])
    if result.failures:
        lines.append("")
        lines.append("失败列表:")
        for failure in result.failures:
            lines.append(f"{failure.input_path}\n原因: {failure.reason}\n建议: {failure.suggestion}")
    return "\n".join(lines)
