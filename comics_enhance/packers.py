"""Multi-format packers for enhanced comic images."""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import zipfile
from pathlib import Path
from typing import Iterable

from PIL import Image

from comics_enhance.config import (
    find_calibre_debug,
    find_ebook_convert,
    find_kindlegen,
)
from comics_enhance.epub_packer import pack_epub
from comics_enhance.mobi_options import MobiComicOptions
from comics_enhance.mobi_preprocessor import preprocess_for_mobi


SUPPORTED_OUTPUT_FORMATS = ("epub", "cbz", "mobi", "kfx")
KFX_IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png"}


def parse_output_formats(raw: str | Iterable[str]) -> list[str]:
    """Parse output format selections, preserving first-seen order."""
    if isinstance(raw, str):
        parts = raw.split(",")
    else:
        parts = list(raw)

    formats: list[str] = []
    seen: set[str] = set()
    for part in parts:
        fmt = str(part).strip().lower().lstrip(".")
        if not fmt:
            continue
        if fmt not in SUPPORTED_OUTPUT_FORMATS:
            raise ValueError(f"Unsupported output format: {fmt}")
        if fmt not in seen:
            formats.append(fmt)
            seen.add(fmt)

    if not formats:
        raise ValueError("At least one output format is required")
    return formats


def pack_cbz(image_paths: list[str], output_path: str) -> str:
    """Pack images into a CBZ archive with stable page numbering."""
    if not image_paths:
        raise ValueError("No images to pack")

    os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
    with zipfile.ZipFile(output_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for idx, image_path in enumerate(image_paths, 1):
            ext = Path(image_path).suffix.lower()
            if ext == ".jpeg":
                ext = ".jpg"
            if not ext:
                ext = ".jpg"
            zf.write(image_path, f"{idx:04d}{ext}")
    return output_path


def pack_mobi(
    epub_path: str,
    output_path: str,
    timeout: int = 600,
) -> str:
    """Convert an EPUB to MOBI using Calibre, with kindlegen fallback."""
    os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)

    ebook_convert = find_ebook_convert()
    if ebook_convert:
        result = subprocess.run(
            [ebook_convert, epub_path, output_path],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
        )
        if result.returncode == 0 and os.path.isfile(output_path):
            return output_path
        calibre_error = (result.stderr or result.stdout or "").strip()
    else:
        calibre_error = "ebook-convert not found"

    kindlegen = find_kindlegen()
    if not kindlegen:
        raise RuntimeError(
            "MOBI output requires Calibre ebook-convert or kindlegen. "
            f"Calibre error: {calibre_error[:500]}"
        )

    with tempfile.TemporaryDirectory(prefix="comics_mobi_") as tmp_dir:
        tmp_epub = os.path.join(tmp_dir, Path(epub_path).name)
        shutil.copy2(epub_path, tmp_epub)
        result = subprocess.run(
            [kindlegen, tmp_epub, "-o", Path(output_path).name],
            cwd=tmp_dir,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
        )
        generated = os.path.join(tmp_dir, Path(output_path).name)
        if result.returncode not in (0, 1) or not os.path.isfile(generated):
            detail = (result.stderr or result.stdout or "").strip()
            raise RuntimeError(f"kindlegen MOBI conversion failed: {detail[:500]}")
        shutil.copy2(generated, output_path)
    return output_path


def pack_kfx(
    image_paths: list[str],
    output_path: str,
    title: str = "",
    author: str = "",
    language: str = "zh",
    reading_direction: str = "rtl",
    virtual_panels: str = "off",
    facing_pages: bool = False,
    facing_start: str = "single",
    timeout: int = 600,
) -> str:
    """Generate KFX from images via KPF and Calibre's KFX Output plugin."""
    calibre_debug = find_calibre_debug()
    if not calibre_debug:
        raise RuntimeError(
            "KFX output requires Calibre with the KFX Output plugin installed "
            "(calibre-debug was not found)."
        )

    from comics_enhance.kpf_generator import generate_kpf

    os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="comics_kfx_") as tmp_dir:
        kfx_images = _prepare_kfx_images(image_paths, os.path.join(tmp_dir, "images"))
        kpf_path = os.path.join(tmp_dir, f"{Path(output_path).stem}.kpf")

        generate_kpf(
            image_paths=kfx_images,
            output_path=kpf_path,
            title=title,
            author=author,
            reading_direction=reading_direction,
            language=language,
            virtual_panels=virtual_panels,
            facing_pages=facing_pages,
            facing_start=facing_start,
        )

        result = subprocess.run(
            [calibre_debug, "-r", "KFX Output", "--", kpf_path, output_path],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
        )
        if result.returncode != 0:
            detail = (result.stderr or result.stdout or "").strip()
            raise RuntimeError(
                "KFX conversion failed. Check that Calibre's KFX Output plugin "
                f"is installed and working. {detail[:500]}"
            )
        if not os.path.isfile(output_path):
            raise RuntimeError(
                "KFX output file was not created. Check that Calibre's KFX "
                "Output plugin is installed and working."
            )
    return output_path


def pack_outputs(
    image_paths: list[str],
    output_dir: str,
    basename: str,
    metadata: dict,
    formats: str | Iterable[str],
    language: str = "zh",
    reading_direction: str = "rtl",
    virtual_panels: str = "off",
    facing_pages: bool = False,
    facing_start: str = "single",
    mobi_options: MobiComicOptions | None = None,
) -> list[str]:
    """Pack enhanced images into all requested output formats."""
    selected = parse_output_formats(formats)
    os.makedirs(output_dir, exist_ok=True)

    title = metadata.get("title") or basename
    author = metadata.get("author") or ""
    outputs: list[str] = []
    intermediate_dir: tempfile.TemporaryDirectory[str] | None = None
    mobi_intermediate_dir: tempfile.TemporaryDirectory[str] | None = None
    if "epub" in selected:
        epub_path = os.path.join(output_dir, f"{basename}.epub")
    else:
        intermediate_dir = tempfile.TemporaryDirectory(prefix="comics_epub_")
        epub_path = os.path.join(intermediate_dir.name, f"{basename}.epub")

    def ensure_epub() -> str:
        if not os.path.isfile(epub_path):
            pack_epub(
                image_paths=image_paths,
                output_path=epub_path,
                title=title,
                author=author,
                language=language,
                reading_direction=reading_direction,
        )
        return epub_path

    def ensure_mobi_epub() -> str:
        nonlocal mobi_intermediate_dir
        if mobi_options is None:
            return ensure_epub()
        if mobi_intermediate_dir is None:
            mobi_intermediate_dir = tempfile.TemporaryDirectory(prefix="comics_mobi_epub_")
        mobi_epub_path = os.path.join(mobi_intermediate_dir.name, f"{basename}.epub")
        if not os.path.isfile(mobi_epub_path):
            mobi_images = preprocess_for_mobi(
                image_paths=image_paths,
                output_dir=os.path.join(mobi_intermediate_dir.name, "images"),
                options=mobi_options,
            )
            pack_epub(
                image_paths=mobi_images,
                output_path=mobi_epub_path,
                title=title,
                author=author,
                language=language,
                reading_direction=reading_direction,
            )
        return mobi_epub_path

    try:
        for fmt in selected:
            if fmt == "epub":
                outputs.append(ensure_epub())
            elif fmt == "cbz":
                outputs.append(pack_cbz(image_paths, os.path.join(output_dir, f"{basename}.cbz")))
            elif fmt == "mobi":
                outputs.append(pack_mobi(ensure_mobi_epub(), os.path.join(output_dir, f"{basename}.mobi")))
            elif fmt == "kfx":
                outputs.append(pack_kfx(
                    image_paths=image_paths,
                    output_path=os.path.join(output_dir, f"{basename}.kfx"),
                    title=title,
                    author=author,
                    language=language,
                    reading_direction=reading_direction,
                    virtual_panels=virtual_panels,
                    facing_pages=facing_pages,
                    facing_start=facing_start,
                ))
        return outputs
    finally:
        if intermediate_dir is not None:
            intermediate_dir.cleanup()
        if mobi_intermediate_dir is not None:
            mobi_intermediate_dir.cleanup()


def _prepare_kfx_images(image_paths: list[str], output_dir: str) -> list[str]:
    """Copy/convert images so KPF receives only JPEG or PNG pages."""
    if not image_paths:
        raise ValueError("No images to pack")

    os.makedirs(output_dir, exist_ok=True)
    prepared: list[str] = []
    for idx, image_path in enumerate(image_paths, 1):
        ext = Path(image_path).suffix.lower()
        if ext in KFX_IMAGE_EXTENSIONS:
            normalized = ".jpg" if ext == ".jpeg" else ext
            out_path = os.path.join(output_dir, f"{idx:04d}{normalized}")
            shutil.copy2(image_path, out_path)
        else:
            out_path = os.path.join(output_dir, f"{idx:04d}.jpg")
            with Image.open(image_path) as img:
                if img.mode != "RGB":
                    img = img.convert("RGB")
                img.save(out_path, "JPEG", quality=95)
        prepared.append(out_path)
    return prepared
