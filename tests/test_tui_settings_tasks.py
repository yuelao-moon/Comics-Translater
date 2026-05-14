import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from PIL import Image

from comics_enhance.tui_settings import (
    ExistingOutputPolicy,
    OutputDirectoryMode,
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
    scan_image_folders,
    scan_source_files,
    run_safety_checks,
)


def _make_image(path: str) -> None:
    Image.new("RGB", (6, 8), (100, 120, 140)).save(path)


class TuiSettingsTests(unittest.TestCase):
    def test_default_settings_match_wizard_defaults(self):
        with tempfile.TemporaryDirectory() as tmp:
            settings = TuiSettings.default(work_dir=tmp)

            self.assertEqual(settings.output_dir, os.path.join(tmp, "output"))
            self.assertEqual(settings.full_output_formats, ["epub"])
            self.assertEqual(settings.image_format, "jpg")
            self.assertEqual(settings.enhance_preset, "smart")
            self.assertEqual(settings.reading_direction, "rtl")
            self.assertEqual(settings.language, "zh")
            self.assertTrue(settings.categorized_subdirs)
            self.assertEqual(settings.same_format_policy, "block")

    def test_save_load_and_reset_settings_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "settings.json")
            settings = TuiSettings.default(work_dir=tmp)
            settings.full_output_formats = ["epub", "cbz"]
            settings.mobi_options.stretch = True
            settings.kfx_virtual_panels = "horizontal"
            settings.existing_output_policy = ExistingOutputPolicy.AUTO_RENAME.value

            save_settings(settings, path)
            loaded = load_settings(path, work_dir=tmp)
            reset = reset_settings(path, work_dir=tmp)

            self.assertEqual(loaded.full_output_formats, ["epub", "cbz"])
            self.assertTrue(loaded.mobi_options.stretch)
            self.assertEqual(loaded.kfx_virtual_panels, "horizontal")
            self.assertEqual(loaded.existing_output_policy, "auto_rename")
            self.assertEqual(reset.full_output_formats, ["epub"])


class TuiTaskPlanningTests(unittest.TestCase):
    def test_plan_output_dir_uses_categorized_subdirectories(self):
        with tempfile.TemporaryDirectory() as tmp:
            settings = TuiSettings.default(work_dir=tmp)
            settings.output_dir = os.path.join(tmp, "out")
            settings.output_directory_mode = OutputDirectoryMode.FIXED.value
            settings.categorized_subdirs = True

            self.assertEqual(
                plan_output_dir(TaskMode.FULL, settings),
                os.path.join(tmp, "out", "packed"),
            )
            self.assertEqual(
                plan_output_dir(TaskMode.EXTRACT_ONLY, settings, enhance_after_extract=False),
                os.path.join(tmp, "out", "extracted"),
            )
            self.assertEqual(
                plan_output_dir(TaskMode.ENHANCE_ONLY, settings, pack_after_enhance=False),
                os.path.join(tmp, "out", "enhanced"),
            )

    def test_scan_source_files_expands_globs_and_filters_supported_formats(self):
        with tempfile.TemporaryDirectory() as tmp:
            epub = os.path.join(tmp, "a.epub")
            cbz = os.path.join(tmp, "b.cbz")
            txt = os.path.join(tmp, "note.txt")
            Path(epub).write_bytes(b"epub")
            Path(cbz).write_bytes(b"cbz")
            Path(txt).write_text("nope", encoding="utf-8")

            scan = scan_source_files([os.path.join(tmp, "*")])

            self.assertEqual([Path(p).name for p in scan.files], ["a.epub", "b.cbz"])
            self.assertEqual(scan.total_files, 2)

    def test_scan_image_folders_natural_sorts_images_per_folder(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = os.path.join(tmp, "chapter")
            os.makedirs(folder)
            _make_image(os.path.join(folder, "10.jpg"))
            _make_image(os.path.join(folder, "2.jpg"))
            _make_image(os.path.join(folder, "1.jpg"))

            scan = scan_image_folders([folder])

            self.assertEqual(scan.total_images, 3)
            self.assertEqual(
                [Path(p).name for p in scan.folder_images[folder]],
                ["1.jpg", "2.jpg", "10.jpg"],
            )

    def test_safety_blocks_same_format_same_directory(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = os.path.join(tmp, "book.epub")
            Path(source).write_bytes(b"epub")
            settings = TuiSettings.default(work_dir=tmp)
            config = TaskConfig(
                mode=TaskMode.FULL,
                input_paths=[source],
                output_dir=tmp,
                output_formats=["epub"],
                settings=settings,
            )

            report = run_safety_checks(config)

            self.assertFalse(report.ok)
            self.assertIn("同格式同目录输出", report.issues[0].title)

    def test_safety_reports_missing_kfx_dependency(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = os.path.join(tmp, "book.cbz")
            Path(source).write_bytes(b"cbz")
            settings = TuiSettings.default(work_dir=tmp)
            config = TaskConfig(
                mode=TaskMode.FULL,
                input_paths=[source],
                output_dir=os.path.join(tmp, "out"),
                output_formats=["kfx"],
                settings=settings,
            )

            with mock.patch("comics_enhance.tui_tasks.find_calibre_debug", return_value=None):
                report = run_safety_checks(config)

            self.assertFalse(report.ok)
            self.assertIn("KFX", report.issues[0].title)

    def test_preview_summarizes_full_task(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = os.path.join(tmp, "book.cbz")
            Path(source).write_bytes(b"cbz")
            settings = TuiSettings.default(work_dir=tmp)
            config = TaskConfig(
                mode=TaskMode.FULL,
                input_paths=[source],
                output_dir=os.path.join(tmp, "packed"),
                output_formats=["epub", "cbz"],
                settings=settings,
                enhance_enabled=False,
            )

            preview = build_preview(config)

            self.assertIn("模式: 完整处理", preview)
            self.assertIn("输出格式: EPUB, CBZ", preview)
            self.assertIn("增强: 跳过", preview)

    def test_preview_includes_mobi_and_kfx_display_options(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = os.path.join(tmp, "book.cbz")
            Path(source).write_bytes(b"cbz")
            settings = TuiSettings.default(work_dir=tmp)
            settings.mobi_options.stretch = True
            config = TaskConfig.from_settings(TaskMode.FULL, [source], settings)
            config.output_dir = os.path.join(tmp, "packed")
            config.output_formats = ["mobi", "kfx"]
            config.kfx_virtual_panels = "horizontal"
            config.kfx_facing_pages = True

            preview = build_preview(config)

            self.assertIn("MOBI 设备: Kindle Paperwhite 5/Signature Edition", preview)
            self.assertIn("拉伸到全屏: 是", preview)
            self.assertIn("KFX 虚拟面板: 水平", preview)
            self.assertIn("KFX 横屏对开页: 开启", preview)


if __name__ == "__main__":
    unittest.main()
