"""Image preprocessing for KCC-style MOBI comic output."""

from __future__ import annotations

import os
from pathlib import Path

from PIL import Image, ImageChops, ImageOps

from comics_enhance.mobi_options import MobiComicOptions


def preprocess_for_mobi(
    image_paths: list[str],
    output_dir: str,
    options: MobiComicOptions | None = None,
) -> list[str]:
    """Create MOBI-specific page images using KCC-style display options."""
    if not image_paths:
        raise ValueError("No images to preprocess")

    options = options or MobiComicOptions()
    width, height = options.resolution
    os.makedirs(output_dir, exist_ok=True)

    pages: list[Image.Image] = []
    for image_path in image_paths:
        with Image.open(image_path) as image:
            page = image.convert("RGB")
            for processed in _split_or_rotate(page, options):
                pages.append(processed)

    output_paths: list[str] = []
    for idx, page in enumerate(pages, 1):
        processed = _process_page(page, (width, height), options, is_cover=idx == 1)
        ext = ".png" if _should_save_png(processed, options) else ".jpg"
        out_path = os.path.join(output_dir, f"{idx:04d}{ext}")
        if ext == ".png":
            processed.save(out_path, "PNG")
        else:
            processed.save(out_path, "JPEG", quality=_jpeg_quality(options), optimize=True)
        output_paths.append(out_path)
    return output_paths


def _split_or_rotate(image: Image.Image, options: MobiComicOptions) -> list[Image.Image]:
    width, height = image.size
    is_spread = width >= height * 1.35
    if not is_spread:
        return [image.copy()]

    pages: list[Image.Image] = []
    if options.splitter in (0, 2):
        mid = width // 2
        left = image.crop((0, 0, mid, height))
        right = image.crop((mid, 0, width, height))
        pages = [right, left] if options.manga_style else [left, right]
    if options.splitter in (1, 2):
        if not options.no_rotate:
            angle = -90 if options.rotate_right else 90
            rotated = image.rotate(angle, expand=True)
            if options.rotate_first:
                pages.insert(0, rotated)
            else:
                pages.append(rotated)
    return pages or [image.copy()]


def _process_page(
    image: Image.Image,
    target_size: tuple[int, int],
    options: MobiComicOptions,
    is_cover: bool,
) -> Image.Image:
    page = image
    if options.cropping:
        page = _crop_margin(page, options)
    if is_cover and (options.cover_fill or options.smart_cover_crop):
        return ImageOps.fit(page, target_size, method=Image.Resampling.LANCZOS, centering=(0.5, 0.5))
    if options.stretch:
        return page.resize(target_size, Image.Resampling.LANCZOS)
    if options.upscale or page.width > target_size[0] or page.height > target_size[1]:
        return ImageOps.contain(page, target_size, method=Image.Resampling.LANCZOS)
    return page.copy()


def _crop_margin(image: Image.Image, options: MobiComicOptions) -> Image.Image:
    background_color = "black" if options.black_borders else "white"
    background = Image.new(image.mode, image.size, background_color)
    diff = ImageChops.difference(image, background).convert("L")
    threshold = max(4, min(80, int(18 * max(options.cropping_power, 0.1))))
    mask = diff.point(lambda pixel: 255 if pixel > threshold else 0)
    bbox = mask.getbbox()
    if not bbox:
        return image.copy()

    left, top, right, bottom = bbox
    if options.cropping == 2:
        page_number_band = max(0, int(image.height * 0.025 * max(options.cropping_power, 0.1)))
        bottom = min(image.height, bottom + page_number_band)

    backup = max(0, int(min(image.size) * (options.preserve_margin / 100.0)))
    left = max(0, left - backup)
    top = max(0, top - backup)
    right = min(image.width, right + backup)
    bottom = min(image.height, bottom + backup)

    cropped_area = (right - left) * (bottom - top)
    total_area = image.width * image.height
    if options.cropping_minimum and cropped_area / total_area < options.cropping_minimum:
        return image.copy()
    return image.crop((left, top, right, bottom))


def _should_save_png(image: Image.Image, options: MobiComicOptions) -> bool:
    if options.force_png_rgb:
        return True
    if not options.force_png:
        return False
    return _is_grayscale(image)


def _is_grayscale(image: Image.Image) -> bool:
    rgb = image.convert("RGB")
    for red, green, blue in rgb.getdata():
        if red != green or green != blue:
            return False
    return True


def _jpeg_quality(options: MobiComicOptions) -> int:
    return max(1, min(95, int(options.jpeg_quality)))
