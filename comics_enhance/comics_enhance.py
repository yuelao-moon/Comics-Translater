#!/usr/bin/env python3
"""ComicsEnhance - Batch comic/manga processing CLI.

Pipeline:
  1. Unpack input (EPUB/MOBI/AZW/PDF/CBZ/ZIP) to extract images
  2. Enhance images via sr-vulkan (Waifu2x / RealESRGAN / RealCUGAN)
  3. Repack as fixed-layout EPUB 3

Usage:
  comics-enhance manga.epub
  comics-enhance --model anime-n3 *.epub *.mobi
  comics-enhance --model realesr-anime --tta comic.cbz
  comics-enhance --no-enhance manga.pdf
"""

import argparse
import os
import shutil
import sys
import tempfile
import time
from pathlib import Path

from comics_enhance.config import (
    SUPPORTED_INPUT_FORMATS,
    MODEL_CATALOG,
    DEFAULT_MODEL,
    WAIFU2X_TILE_SIZE,
    WAIFU2X_TTA,
    WAIFU2X_OUTPUT_FORMAT,
    get_model_id,
    model_description,
    is_pillow_model,
    find_calibre_debug,
    ensure_dirs,
)
from comics_enhance.epub_extractor import (
    extract_images,
    extract_metadata,
)
from comics_enhance.waifu2x_enhancer import (
    is_waifu2x_available,
    enhance_images_batch,
)
from comics_enhance.epub_packer import pack_epub


def _fmt_duration(seconds: float) -> str:
    if seconds < 60:
        return f"{seconds:.1f}s"
    return f"{int(seconds // 60)}m{int(seconds % 60)}s"


def process_single(
    input_path: str,
    output_dir: str,
    model_name: str = DEFAULT_MODEL,
    tile_size: int = WAIFU2X_TILE_SIZE,
    tta: bool = WAIFU2X_TTA,
    output_format: str = WAIFU2X_OUTPUT_FORMAT,
    reading_direction: str = "rtl",
    language: str = "zh",
) -> str:
    """Process a single comic file through the full pipeline."""
    input_name = Path(input_path).stem
    ext = Path(input_path).suffix.lower()

    if ext not in SUPPORTED_INPUT_FORMATS:
        print(f"  Skipping {input_path}: unsupported format '{ext}'")
        return ""

    if ext not in {".epub", ".cbz", ".zip"}:
        calibre = find_calibre_debug()
        if not calibre:
            print(f"  Error: Calibre required for {ext} files but not found.")
            print(f"  Install from https://calibre-ebook.com/")
            return ""

    # Resolve model
    desc = model_description(model_name)
    force_pillow = is_pillow_model(model_name)
    if force_pillow:
        model_id = None  # will skip sr-vulkan path
    else:
        model_id = get_model_id(model_name)

    model_scale = 2
    if "4x" in model_name or "-4x" in model_name:
        model_scale = 4
    elif "3x" in model_name or "-3x" in model_name:
        model_scale = 3

    tmp_root = tempfile.mkdtemp(prefix=f"comics_enhance_{input_name}_")
    try:
        # ── Step 1: Extract ──
        print(f"\n{'='*60}")
        print(f"Processing: {os.path.basename(input_path)}")
        print(f"{'='*60}")

        image_dir = os.path.join(tmp_root, "extracted")
        print(f"\n[1/3] Extracting images...")

        start_t = time.time()
        image_paths, src_format = extract_images(input_path, image_dir, tmp_dir=tmp_root)
        extract_t = time.time() - start_t

        metadata = extract_metadata(input_path)
        print(f"    Title: {metadata.get('title', input_name)}")
        if metadata.get("author"):
            print(f"    Author: {metadata['author']}")
        print(f"    Extracted {len(image_paths)} images ({extract_t:.1f}s)")

        # ── Step 2: Enhance ──
        enhanced_dir = os.path.join(tmp_root, "enhanced")
        use_waifu2x = True  # always try, enhance_images_batch handles fallback

        tta_label = ", TTA on" if tta else ""
        print(f"\n[2/3] Enhancing... ({desc}{tta_label})")

        start_t = time.time()
        enhanced_paths = enhance_images_batch(
            image_paths=image_paths,
            output_dir=enhanced_dir,
            model=model_id,
            scale=model_scale,
            output_format=output_format,
            tile_size=tile_size,
            tta=tta,
            force_pillow=force_pillow,
        )
        enhance_t = time.time() - start_t
        print(f"    Enhanced {len(enhanced_paths)} images ({_fmt_duration(enhance_t)})")

        # ── Step 3: Pack ──
        print(f"\n[3/3] Packing EPUB...")

        os.makedirs(output_dir, exist_ok=True)
        epub_name = f"{input_name}.epub"
        epub_path = os.path.join(output_dir, epub_name)

        start_t = time.time()
        pack_epub(
            image_paths=enhanced_paths,
            output_path=epub_path,
            title=metadata.get("title", input_name),
            author=metadata.get("author", ""),
            language=language,
            reading_direction=reading_direction,
        )
        pack_t = time.time() - start_t

        epub_size_mb = os.path.getsize(epub_path) / (1024 * 1024)
        print(f"    Output: {epub_path} ({epub_size_mb:.1f} MB, {pack_t:.1f}s)")

        return epub_path

    except Exception as e:
        print(f"\n  Error processing {input_path}: {e}")
        import traceback
        traceback.print_exc()
        return ""

    finally:
        try:
            shutil.rmtree(tmp_root, ignore_errors=True)
        except Exception:
            pass


# ── CLI ──

_MODEL_CHOICES = sorted(MODEL_CATALOG.keys())


def _model_autocomplete() -> str:
    """Build help text listing all models grouped by family."""
    lines = []
    groups = [
        ("Waifu2x CUNet", [n for n in _MODEL_CHOICES if n.startswith("cunet")]),
        ("Waifu2x Anime", [n for n in _MODEL_CHOICES if n.startswith("anime")]),
        ("Waifu2x Photo", [n for n in _MODEL_CHOICES if n.startswith("photo")]),
        ("RealESRGAN",    [n for n in _MODEL_CHOICES if n.startswith("realesr")]),
        ("RealCUGAN/RealSR", [n for n in _MODEL_CHOICES if not any(n.startswith(p) for p in ("cunet","anime","photo","realesr"))]),
    ]
    for group_name, items in groups:
        if items:
            lines.append(f"\n  {group_name}:")
            for n in items:
                lines.append(f"    {n:22s}  {MODEL_CATALOG[n]['desc']}")
    return "".join(lines)


def main():
    parser = argparse.ArgumentParser(
        description="ComicsEnhance — Batch comic/manga processing: "
                    "unpack, enhance (Waifu2x/RealESRGAN), pack as EPUB",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=f"""
Models (--model):
{_model_autocomplete()}

Examples:
  comics-enhance manga.epub
  comics-enhance --model anime-n2 *.epub *.mobi
  comics-enhance --model realesr-anime --tta comic.cbz
  comics-enhance --model photo-n1 --format png manga.epub
  comics-enhance --no-enhance manga.pdf
        """,
    )

    parser.add_argument(
        "input_files", nargs="+", metavar="FILE",
        help="One or more comic files (EPUB/MOBI/AZW/AZW3/PDF/CBZ/ZIP)",
    )
    parser.add_argument(
        "--output", "-o", default=".",
        help="Output directory for enhanced EPUB files (default: current dir)",
    )
    parser.add_argument(
        "--direction", choices=["rtl", "ltr"], default="rtl",
        help="Reading direction: rtl=manga, ltr=comic (default: rtl)",
    )
    parser.add_argument(
        "--language", "-l", default="zh",
        help="Book language code (default: zh)",
    )

    enhance_group = parser.add_argument_group("Enhancement options")

    enhance_group.add_argument(
        "--no-enhance",
        action="store_true",
        dest="no_enhance",
        help="Skip all image enhancement (extract + pack only)",
    )
    enhance_group.add_argument(
        "--model", default=DEFAULT_MODEL, choices=_MODEL_CHOICES,
        metavar="NAME",
        help=f"Enhancement model (default: {DEFAULT_MODEL}). "
             f"See below for full list.",
    )
    enhance_group.add_argument(
        "--tta", action="store_true", default=WAIFU2X_TTA,
        help="Enable TTA mode (higher quality, ~2x slower)",
    )
    enhance_group.add_argument(
        "--format", default=WAIFU2X_OUTPUT_FORMAT,
        choices=["jpg", "png", "webp", "bmp"],
        help="Output image format (default: jpg)",
    )
    enhance_group.add_argument(
        "--tile-size", type=int, default=WAIFU2X_TILE_SIZE,
        metavar="PIXELS",
        help=f"GPU tile size, 0=auto (default: {WAIFU2X_TILE_SIZE})",
    )

    args = parser.parse_args()
    ensure_dirs()

    # Check sr-vulkan
    if not args.no_enhance:
        if is_waifu2x_available():
            print("GPU accelerator: available")
        else:
            print("GPU accelerator: NOT available, using CPU fallback (Pillow)")
            print("  Install sr-vulkan for GPU: pip install sr_vulkan-*.whl")

    # Check Calibre
    has_non_epub = any(
        Path(f).suffix.lower() not in {".epub", ".cbz", ".zip"}
        for f in args.input_files
    )
    if has_non_epub and not find_calibre_debug():
        print("Warning: Calibre not found. MOBI/AZW/PDF files will fail.")
        print("  Install from: https://calibre-ebook.com/")

    # Process
    total_start = time.time()
    success = fail = 0

    for input_file in args.input_files:
        if args.no_enhance:
            # Skip enhancement — pass model=none, enhance_images_batch fallback
            result = process_single(
                input_path=input_file,
                output_dir=args.output,
                model_name=DEFAULT_MODEL,
                tile_size=args.tile_size,
                tta=args.tta,
                output_format=args.format,
                reading_direction=args.direction,
                language=args.language,
            )
        else:
            model_name = args.model
            result = process_single(
                input_path=input_file,
                output_dir=args.output,
                model_name=model_name,
                tile_size=args.tile_size,
                tta=args.tta,
                output_format=args.format,
                reading_direction=args.direction,
                language=args.language,
            )
        if result:
            success += 1
        else:
            fail += 1

    total_t = time.time() - total_start
    print(f"\n{'='*60}")
    print(f"Summary: {success}/{success+fail} succeeded, "
          f"{fail}/{success+fail} failed ({_fmt_duration(total_t)})")
    print(f"{'='*60}")
    if fail > 0:
        sys.exit(1)


if __name__ == "__main__":
    main()
