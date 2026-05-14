import os
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest import mock

from PIL import Image

from comics_enhance.packers import (
    parse_output_formats,
    pack_cbz,
    pack_kfx,
    pack_mobi,
    pack_outputs,
)
from comics_enhance.mobi_options import MobiComicOptions


def _make_image(path: str, color: tuple[int, int, int]) -> None:
    Image.new("RGB", (8, 12), color).save(path)


class OutputFormatParsingTests(unittest.TestCase):
    def test_parse_output_formats_normalizes_deduplicates_and_preserves_order(self):
        formats = parse_output_formats(" EPUB,cbz,epub,KFX ")

        self.assertEqual(formats, ["epub", "cbz", "kfx"])

    def test_parse_output_formats_rejects_unknown_formats(self):
        with self.assertRaisesRegex(ValueError, "Unsupported output format: pdf"):
            parse_output_formats("epub,pdf")


class CbzPackerTests(unittest.TestCase):
    def test_pack_cbz_writes_images_in_page_order_with_numbered_names(self):
        with tempfile.TemporaryDirectory() as tmp:
            first = os.path.join(tmp, "cover.png")
            second = os.path.join(tmp, "page-final.jpg")
            _make_image(first, (255, 0, 0))
            _make_image(second, (0, 255, 0))

            output_path = os.path.join(tmp, "book.cbz")
            result = pack_cbz([first, second], output_path)

            self.assertEqual(result, output_path)
            with zipfile.ZipFile(output_path, "r") as zf:
                self.assertEqual(zf.namelist(), ["0001.png", "0002.jpg"])
                self.assertGreater(zf.getinfo("0001.png").file_size, 0)
                self.assertGreater(zf.getinfo("0002.jpg").file_size, 0)


class PackOutputsTests(unittest.TestCase):
    def test_pack_outputs_generates_requested_epub_and_cbz_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            image_path = os.path.join(tmp, "page.jpg")
            _make_image(image_path, (0, 0, 255))
            out_dir = os.path.join(tmp, "out")

            outputs = pack_outputs(
                image_paths=[image_path],
                output_dir=out_dir,
                basename="sample",
                metadata={"title": "Sample", "author": "Tester"},
                formats=["epub", "cbz"],
                language="zh",
                reading_direction="rtl",
            )

            self.assertEqual(
                [Path(path).suffix for path in outputs],
                [".epub", ".cbz"],
            )
            self.assertTrue(os.path.isfile(os.path.join(out_dir, "sample.epub")))
            self.assertTrue(os.path.isfile(os.path.join(out_dir, "sample.cbz")))

    def test_pack_outputs_uses_mobi_preprocessed_images_without_touching_epub(self):
        with tempfile.TemporaryDirectory() as tmp:
            original = os.path.join(tmp, "page.jpg")
            mobi_page = os.path.join(tmp, "mobi_page.jpg")
            _make_image(original, (0, 0, 255))
            _make_image(mobi_page, (255, 255, 0))
            out_dir = os.path.join(tmp, "out")

            with mock.patch("comics_enhance.packers.preprocess_for_mobi", return_value=[mobi_page]) as preprocess, \
                    mock.patch("comics_enhance.packers.pack_mobi", return_value=os.path.join(out_dir, "sample.mobi")) as pack_mobi_mock:
                outputs = pack_outputs(
                    image_paths=[original],
                    output_dir=out_dir,
                    basename="sample",
                    metadata={"title": "Sample", "author": "Tester"},
                    formats=["epub", "mobi"],
                    mobi_options=MobiComicOptions(stretch=True),
                )

            self.assertEqual([Path(path).suffix for path in outputs], [".epub", ".mobi"])
            preprocess.assert_called_once()
            pack_mobi_mock.assert_called_once()
            with zipfile.ZipFile(os.path.join(out_dir, "sample.epub"), "r") as epub:
                page_bytes = epub.read("OEBPS/images/page_0000.jpg")
            with open(original, "rb") as original_file:
                self.assertEqual(page_bytes, original_file.read())


class DependencyErrorTests(unittest.TestCase):
    def test_pack_mobi_reports_missing_calibre_and_kindlegen(self):
        with tempfile.TemporaryDirectory() as tmp:
            epub_path = os.path.join(tmp, "book.epub")
            Path(epub_path).write_bytes(b"fake epub")

            with mock.patch("comics_enhance.packers.find_ebook_convert", return_value=None), \
                    mock.patch("comics_enhance.packers.find_kindlegen", return_value=None):
                with self.assertRaisesRegex(RuntimeError, "MOBI output requires"):
                    pack_mobi(epub_path, os.path.join(tmp, "book.mobi"))

    def test_pack_kfx_reports_missing_calibre_debug(self):
        with tempfile.TemporaryDirectory() as tmp:
            image_path = os.path.join(tmp, "page.jpg")
            _make_image(image_path, (10, 20, 30))

            with mock.patch("comics_enhance.packers.find_calibre_debug", return_value=None):
                with self.assertRaisesRegex(RuntimeError, "KFX output requires"):
                    pack_kfx([image_path], os.path.join(tmp, "book.kfx"))


if __name__ == "__main__":
    unittest.main()
