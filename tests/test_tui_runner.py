import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from PIL import Image

from comics_enhance.tui_runner import TaskFailure, run_task
from comics_enhance.tui_settings import ExistingOutputPolicy, TuiSettings
from comics_enhance.tui_tasks import TaskConfig, TaskMode


def _make_image(path: str) -> None:
    Image.new("RGB", (8, 10), (20, 40, 60)).save(path)


class TuiRunnerTests(unittest.TestCase):
    def test_extract_only_writes_images_to_output_folder(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = os.path.join(tmp, "book.cbz")
            out_dir = os.path.join(tmp, "out")
            settings = TuiSettings.default(work_dir=tmp)
            config = TaskConfig(
                mode=TaskMode.EXTRACT_ONLY,
                input_paths=[source],
                output_dir=out_dir,
                settings=settings,
                enhance_enabled=False,
            )

            def fake_extract(input_path, output_dir, tmp_dir=None):
                image_path = os.path.join(output_dir, "0001.jpg")
                _make_image(image_path)
                return [image_path], "cbz"

            with mock.patch("comics_enhance.tui_runner.extract_images", side_effect=fake_extract):
                result = run_task(config)

            self.assertEqual(result.success_count, 1)
            self.assertEqual(result.fail_count, 0)
            self.assertEqual(len(result.outputs), 1)
            self.assertTrue(os.path.isdir(result.outputs[0]))

    def test_full_task_packs_outputs_after_single_enhance_pass(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = os.path.join(tmp, "book.cbz")
            out_dir = os.path.join(tmp, "packed")
            settings = TuiSettings.default(work_dir=tmp)
            config = TaskConfig(
                mode=TaskMode.FULL,
                input_paths=[source],
                output_dir=out_dir,
                output_formats=["epub", "cbz"],
                settings=settings,
                enhance_enabled=True,
            )

            def fake_extract(input_path, output_dir, tmp_dir=None):
                image_path = os.path.join(output_dir, "0001.jpg")
                _make_image(image_path)
                return [image_path], "cbz"

            def fake_enhance(image_paths, output_dir, **kwargs):
                enhanced = os.path.join(output_dir, "0001.jpg")
                _make_image(enhanced)
                return [enhanced]

            with mock.patch("comics_enhance.tui_runner.extract_images", side_effect=fake_extract), \
                    mock.patch("comics_enhance.tui_runner.extract_metadata", return_value={"title": "Book", "author": ""}), \
                    mock.patch("comics_enhance.tui_runner.enhance_images_batch", side_effect=fake_enhance) as enhance, \
                    mock.patch("comics_enhance.tui_runner.pack_outputs", return_value=[os.path.join(out_dir, "book.epub"), os.path.join(out_dir, "book.cbz")]) as pack:
                result = run_task(config)

            self.assertEqual(result.success_count, 1)
            self.assertEqual(enhance.call_count, 1)
            self.assertEqual(pack.call_count, 1)
            self.assertIs(pack.call_args.kwargs["mobi_options"], config.mobi_options)
            self.assertEqual(result.outputs, [os.path.join(out_dir, "book.epub"), os.path.join(out_dir, "book.cbz")])

    def test_runner_collects_readable_failures(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = os.path.join(tmp, "bad.cbz")
            settings = TuiSettings.default(work_dir=tmp)
            config = TaskConfig(
                mode=TaskMode.FULL,
                input_paths=[source],
                output_dir=os.path.join(tmp, "out"),
                settings=settings,
            )

            with mock.patch("comics_enhance.tui_runner.extract_images", side_effect=RuntimeError("No images found")):
                result = run_task(config)

            self.assertEqual(result.success_count, 0)
            self.assertEqual(result.fail_count, 1)
            self.assertIsInstance(result.failures[0], TaskFailure)
            self.assertIn("No images found", result.failures[0].reason)

    def test_auto_rename_policy_changes_pack_basename_when_output_exists(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = os.path.join(tmp, "book.cbz")
            out_dir = os.path.join(tmp, "packed")
            os.makedirs(out_dir)
            Path(os.path.join(out_dir, "book.epub")).write_bytes(b"old")
            settings = TuiSettings.default(work_dir=tmp)
            settings.existing_output_policy = ExistingOutputPolicy.AUTO_RENAME.value
            config = TaskConfig(
                mode=TaskMode.FULL,
                input_paths=[source],
                output_dir=out_dir,
                output_formats=["epub"],
                settings=settings,
                enhance_enabled=False,
            )

            def fake_extract(input_path, output_dir, tmp_dir=None):
                image_path = os.path.join(output_dir, "0001.jpg")
                _make_image(image_path)
                return [image_path], "cbz"

            with mock.patch("comics_enhance.tui_runner.extract_images", side_effect=fake_extract), \
                    mock.patch("comics_enhance.tui_runner.extract_metadata", return_value={"title": "Book", "author": ""}), \
                    mock.patch("comics_enhance.tui_runner.pack_outputs", return_value=[os.path.join(out_dir, "book_2.epub")]) as pack:
                result = run_task(config)

            self.assertEqual(result.success_count, 1)
            self.assertEqual(pack.call_args.kwargs["basename"], "book_2")


if __name__ == "__main__":
    unittest.main()
