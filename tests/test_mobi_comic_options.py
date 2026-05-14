import os
import tempfile
import unittest
import zipfile

from PIL import Image

from comics_enhance.mobi_options import (
    KCC_OPTION_LABELS_ZH,
    MobiComicOptions,
    resolve_device_profile,
)
from comics_enhance.mobi_preprocessor import preprocess_for_mobi


def _make_image(path: str, size=(80, 120), border=0) -> None:
    image = Image.new("RGB", size, "white")
    for x in range(border, size[0] - border):
        for y in range(border, size[1] - border):
            image.putpixel((x, y), (20, 20, 20))
    image.save(path)


class MobiComicOptionsTests(unittest.TestCase):
    def test_default_options_match_kcc_style_defaults(self):
        options = MobiComicOptions()

        self.assertEqual(options.device_profile, "KPW5")
        self.assertEqual(options.cropping, 2)
        self.assertFalse(options.upscale)
        self.assertFalse(options.stretch)

    def test_profile_resolution_supports_known_and_other_profiles(self):
        self.assertEqual(resolve_device_profile("KPW5"), (1236, 1648))
        self.assertEqual(resolve_device_profile("KPW6"), (1272, 1696))
        self.assertEqual(resolve_device_profile("KO"), (1264, 1680))
        self.assertEqual(resolve_device_profile("KS"), (1860, 2480))

        self.assertEqual(
            resolve_device_profile("OTHER", custom_width=900, custom_height=1200),
            (900, 1200),
        )

    def test_chinese_label_map_covers_all_public_options(self):
        fields = set(MobiComicOptions().__dataclass_fields__)

        self.assertTrue(fields.issubset(set(KCC_OPTION_LABELS_ZH)))
        self.assertEqual(len(KCC_OPTION_LABELS_ZH), len(set(KCC_OPTION_LABELS_ZH)))


class MobiPreprocessorTests(unittest.TestCase):
    def test_preprocess_crops_white_margin_and_stretches_to_device_size(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = os.path.join(tmp, "page.jpg")
            _make_image(source, size=(80, 120), border=12)
            out_dir = os.path.join(tmp, "mobi")
            options = MobiComicOptions(
                device_profile="OTHER",
                custom_width=100,
                custom_height=160,
                cropping=2,
                stretch=True,
                jpeg_quality=90,
            )

            outputs = preprocess_for_mobi([source], out_dir, options)

            self.assertEqual(len(outputs), 1)
            with Image.open(outputs[0]) as image:
                self.assertEqual(image.size, (100, 160))
            self.assertTrue(outputs[0].endswith(".jpg"))

    def test_cover_fill_center_crops_only_first_page(self):
        with tempfile.TemporaryDirectory() as tmp:
            cover = os.path.join(tmp, "cover.jpg")
            page = os.path.join(tmp, "page.jpg")
            _make_image(cover, size=(80, 100))
            _make_image(page, size=(80, 100))
            options = MobiComicOptions(
                device_profile="OTHER",
                custom_width=100,
                custom_height=100,
                cover_fill=True,
                stretch=False,
                upscale=True,
                cropping=0,
            )

            outputs = preprocess_for_mobi([cover, page], os.path.join(tmp, "out"), options)

            with Image.open(outputs[0]) as cover_out, Image.open(outputs[1]) as page_out:
                self.assertEqual(cover_out.size, (100, 100))
                self.assertEqual(page_out.size, (80, 100))

    def test_splitter_splits_double_width_pages(self):
        with tempfile.TemporaryDirectory() as tmp:
            spread = os.path.join(tmp, "spread.jpg")
            _make_image(spread, size=(240, 100), border=0)
            options = MobiComicOptions(
                device_profile="OTHER",
                custom_width=100,
                custom_height=100,
                splitter=0,
                cropping=0,
            )

            outputs = preprocess_for_mobi([spread], os.path.join(tmp, "out"), options)

            self.assertEqual(len(outputs), 2)
            with Image.open(outputs[0]) as first, Image.open(outputs[1]) as second:
                self.assertEqual(first.size, (100, 83))
                self.assertEqual(second.size, (100, 83))


if __name__ == "__main__":
    unittest.main()
