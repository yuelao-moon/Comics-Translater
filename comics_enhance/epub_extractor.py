"""Multi-format comic image extractor.

Supports: EPUB, MOBI, AZW/AZW3, PDF, CBZ/ZIP

For non-EPUB formats, Calibre's ebook-convert is used as a preprocessor
to convert to EPUB first. CBZ/ZIP files are extracted directly.

Core extraction logic adapted from:
  kindle-comic-workaround-5.19.x/convert.py
"""

import os
import re
import shutil
import subprocess
import tempfile
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path
from typing import Optional

# XML Namespace constants
NS_CONTAINER = "urn:oasis:names:tc:opendocument:xmlns:container"
NS_OPF = "http://www.idpf.org/2007/opf"
NS_XHTML = "http://www.w3.org/1999/xhtml"
NS_SVG = "http://www.w3.org/2000/svg"
NS_XLINK = "http://www.w3.org/1999/xlink"

# EPUB image MIME types
IMAGE_MIME_TYPES = {
    "image/jpeg", "image/jpg", "image/png",
    "image/gif", "image/webp", "image/bmp",
}
# Files to skip in CBZ/ZIP
SKIP_NAMES = {"thumbs.db", ".ds_store", "__macosx"}


def find_calibre_debug() -> Optional[str]:
    """Locate calibre-debug executable."""
    import platform
    if platform.system() == "Darwin":
        path = "/Applications/calibre.app/Contents/MacOS/calibre-debug"
        if os.path.isfile(path):
            return path
    elif platform.system() == "Windows":
        for candidate in [
            os.path.expandvars(r"%ProgramFiles%\Calibre2\calibre-debug.exe"),
            os.path.expandvars(r"%ProgramFiles(x86)%\Calibre2\calibre-debug.exe"),
        ]:
            if os.path.isfile(candidate):
                return candidate
    return shutil.which("calibre-debug")


def find_opf_path(epub_zip: zipfile.ZipFile) -> str:
    """Read META-INF/container.xml to locate OPF file path."""
    container_xml = epub_zip.read("META-INF/container.xml")
    root = ET.fromstring(container_xml)
    rootfiles = root.find(f".//{{{NS_CONTAINER}}}rootfile")
    if rootfiles is None:
        raise ValueError("No rootfile found in container.xml")
    opf_path = rootfiles.get("full-path")
    if not opf_path:
        raise ValueError("rootfile has no full-path attribute")
    return opf_path


def parse_spine_items(epub_zip: zipfile.ZipFile, opf_path: str) -> list[tuple[str, str]]:
    """Parse OPF to get spine-ordered content documents.

    Returns list of (item_id, href) in spine order.
    """
    opf_xml = epub_zip.read(opf_path)
    root = ET.fromstring(opf_xml)
    opf_dir = str(Path(opf_path).parent)
    if opf_dir == ".":
        opf_dir = ""

    manifest = root.find(f"{{{NS_OPF}}}manifest")
    if manifest is None:
        raise ValueError("No manifest found in OPF")

    id_to_href = {}
    for item in manifest.findall(f"{{{NS_OPF}}}item"):
        item_id = item.get("id")
        href = item.get("href")
        if item_id and href:
            full_href = f"{opf_dir}/{href}" if opf_dir else href
            id_to_href[item_id] = full_href

    spine = root.find(f"{{{NS_OPF}}}spine")
    if spine is None:
        raise ValueError("No spine found in OPF")

    items = []
    for itemref in spine.findall(f"{{{NS_OPF}}}itemref"):
        idref = itemref.get("idref")
        if idref and idref in id_to_href:
            items.append((idref, id_to_href[idref]))

    return items


def _resolve_image_path(xhtml_path: str, img_src: str) -> str:
    """Resolve image path relative to XHTML file location.

    Normalizes '..' segments so the result works for ZIP lookups
    (ZIP files do not resolve parent-dir references).
    """
    xhtml_dir = str(Path(xhtml_path).parent)
    if xhtml_dir == ".":
        xhtml_dir = ""
    if xhtml_dir:
        resolved = f"{xhtml_dir}/{img_src}"
    else:
        resolved = img_src
    return os.path.normpath(resolved).replace("\\", "/")


def extract_images_from_page(epub_zip: zipfile.ZipFile, xhtml_path: str) -> list[str]:
    """Extract image references from an XHTML/SVG spine item.

    Handles <img src="...">, <svg><image xlink:href="...">, and <image href="...">.
    Falls back to regex if XML parsing fails.
    """
    xhtml_bytes = epub_zip.read(xhtml_path)

    image_hrefs = []

    try:
        root = ET.fromstring(xhtml_bytes)

        # Handle <svg><image> elements
        for img_el in root.iter(f"{{{NS_SVG}}}image"):
            href = img_el.get(f"{{{NS_XLINK}}}href") or img_el.get("href")
            if href:
                image_hrefs.append(href)

        # Handle <img> elements (XHTML and HTML)
        for img_el in root.iter(f"{{{NS_XHTML}}}img"):
            src = img_el.get("src")
            if src:
                image_hrefs.append(src)
        for img_el in root.iter("img"):
            src = img_el.get("src")
            if src:
                image_hrefs.append(src)

        # Handle <image> elements (HTML5)
        for img_el in root.iter("image"):
            href = img_el.get("href") or img_el.get(f"{{{NS_XLINK}}}href")
            if href:
                image_hrefs.append(href)

    except ET.ParseError:
        # Fallback: regex for img/ image src= and xlink:href=
        img_re = re.compile(
            r'<(?:img|image)[^>]+?'
            r'(?:src|' + re.escape(f"{{{NS_XLINK}}}") + r'href|href)\s*=\s*'
            r'[\'"]([^\'"]+?)[\'"]',
            re.IGNORECASE,
        )
        image_hrefs = img_re.findall(xhtml_bytes.decode("utf-8", errors="replace"))

    # Resolve paths relative to XHTML location
    resolved = [_resolve_image_path(xhtml_path, h) for h in image_hrefs]

    return resolved


def _get_manifest_media_types(epub_zip: zipfile.ZipFile, opf_path: str) -> dict[str, str]:
    """Build a mapping from href to media-type from OPF manifest."""
    opf_xml = epub_zip.read(opf_path)
    root = ET.fromstring(opf_xml)
    opf_dir = str(Path(opf_path).parent)
    if opf_dir == ".":
        opf_dir = ""

    href_to_type = {}
    manifest = root.find(f"{{{NS_OPF}}}manifest")
    if manifest is not None:
        for item in manifest.findall(f"{{{NS_OPF}}}item"):
            href = item.get("href")
            media_type = item.get("media-type", "")
            if href:
                full_href = f"{opf_dir}/{href}" if opf_dir else href
                href_to_type[full_href] = media_type
    return href_to_type


def _is_image_path(path: str, href_to_type: dict[str, str]) -> bool:
    """Check if a path points to an image by manifest MIME type or extension."""
    # Normalize path for lookup (remove ./ etc.)
    normalized = os.path.normpath(path).replace("\\", "/")
    if normalized in href_to_type:
        return href_to_type[normalized] in IMAGE_MIME_TYPES
    # Fallback: check extension
    ext = Path(path).suffix.lower()
    return ext in {".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp"}


def extract_images_from_epub(epub_path: str, output_dir: str) -> tuple[list[str], int]:
    """Extract images from EPUB in spine reading order.

    Args:
        epub_path: Path to EPUB file.
        output_dir: Directory to save extracted images.

    Returns:
        Tuple of (list of output image paths, image count).
    """
    os.makedirs(output_dir, exist_ok=True)

    with zipfile.ZipFile(epub_path, "r") as zf:
        opf_path = find_opf_path(zf)
        spine_items = parse_spine_items(zf, opf_path)

        href_to_type = {}
        try:
            href_to_type = _get_manifest_media_types(zf, opf_path)
        except Exception:
            pass

        extracted = []
        extracted_names = set()  # Track extracted ZIP entry names for dedup

        for item_id, xhtml_path in spine_items:
            # Find image references in this spine page
            img_refs = extract_images_from_page(zf, xhtml_path)
            for img_ref in img_refs:
                if not _is_image_path(img_ref, href_to_type):
                    continue
                if img_ref in extracted_names:
                    continue
                try:
                    img_data = zf.read(img_ref)
                    extracted_names.add(img_ref)
                    base_name = os.path.basename(img_ref)
                    out_path = os.path.join(output_dir, base_name)
                    if os.path.exists(out_path):
                        name, ext = os.path.splitext(base_name)
                        out_path = os.path.join(
                            output_dir, f"{name}_{len(extracted)}{ext}"
                        )
                    with open(out_path, "wb") as f:
                        f.write(img_data)
                    extracted.append(out_path)
                except (KeyError, zipfile.BadZipFile):
                    continue

        # Fallback: scan all ZIP entries for images missed by spine parsing
        # (handles EPUBs where images are in manifest but not in spine pages,
        #  or where img/src parsing in spine pages was incomplete)
        for name in zf.namelist():
            if name in extracted_names:
                continue
            if _is_image_path(name, href_to_type):
                try:
                    img_data = zf.read(name)
                    extracted_names.add(name)
                    base_name = os.path.basename(name)
                    out_path = os.path.join(output_dir, base_name)
                    if os.path.exists(out_path):
                        stem, ext = os.path.splitext(base_name)
                        out_path = os.path.join(
                            output_dir, f"{stem}_{len(extracted)}{ext}"
                        )
                    with open(out_path, "wb") as f:
                        f.write(img_data)
                    extracted.append(out_path)
                except (KeyError, zipfile.BadZipFile):
                    continue

    return extracted, len(extracted)


def extract_metadata_from_epub(epub_path: str) -> dict:
    """Extract book metadata (title, author) from EPUB OPF."""
    metadata = {"title": "", "author": ""}
    try:
        with zipfile.ZipFile(epub_path, "r") as zf:
            opf_path = find_opf_path(zf)
            opf_xml = zf.read(opf_path)
            root = ET.fromstring(opf_xml)

            # Dublin Core namespace
            dc_ns = "http://purl.org/dc/elements/1.1/"
            metadata_el = root.find(f"{{{NS_OPF}}}metadata")
            if metadata_el is None:
                return metadata

            title_el = metadata_el.find(f"{{{dc_ns}}}title")
            if title_el is not None and title_el.text:
                metadata["title"] = title_el.text.strip()

            creator_el = metadata_el.find(f"{{{dc_ns}}}creator")
            if creator_el is not None and creator_el.text:
                metadata["author"] = creator_el.text.strip()

    except Exception:
        pass

    return metadata


def convert_to_epub(input_path: str, output_dir: str) -> str:
    """Convert PDF/MOBI/AZW to EPUB using Calibre ebook-convert.

    Args:
        input_path: Path to input file.
        output_dir: Directory for the converted EPUB.

    Returns:
        Path to the generated EPUB file.
    """
    calibre_debug = find_calibre_debug()
    if not calibre_debug:
        raise RuntimeError(
            "Calibre not found. Install Calibre from https://calibre-ebook.com/"
        )

    input_name = Path(input_path).stem
    epub_path = os.path.join(output_dir, f"{input_name}.epub")

    cmd = [
        calibre_debug, "-r", "KFX Output", "--",
        calibre_debug.replace("calibre-debug", "ebook-convert")
        if "calibre-debug" in calibre_debug
        else "ebook-convert",
        input_path, epub_path,
    ]

    # Try simpler direct approach first
    ebook_convert = calibre_debug.replace("calibre-debug", "ebook-convert")
    if not os.path.isfile(ebook_convert):
        ebook_convert = shutil.which("ebook-convert")
        if not ebook_convert:
            ebook_convert = calibre_debug.replace("calibre-debug.exe", "ebook-convert.exe")

    if os.path.isfile(ebook_convert) or shutil.which(ebook_convert):
        cmd = [ebook_convert, input_path, epub_path]

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=300,  # 5 minute timeout for large files
        )
        if result.returncode != 0:
            raise RuntimeError(
                f"Calibre conversion failed:\n{result.stderr[:500]}"
            )
    except subprocess.TimeoutExpired:
        raise RuntimeError("Calibre conversion timed out (>5 minutes)")

    if not os.path.isfile(epub_path):
        raise RuntimeError(f"EPUB not created at {epub_path}")

    return epub_path


def extract_from_cbz(input_path: str, output_dir: str) -> tuple[list[str], int]:
    """Extract images from a CBZ (or generic ZIP) file.

    CBZ files are simply ZIP archives containing images.
    Images are sorted by filename for page order.

    Returns:
        Tuple of (list of output image paths, image count).
    """
    os.makedirs(output_dir, exist_ok=True)
    image_exts = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp"}

    extracted = []
    with zipfile.ZipFile(input_path, "r") as zf:
        # Get image files, sorted naturally
        image_files = []
        for name in zf.namelist():
            basename = os.path.basename(name).lower()
            if basename in SKIP_NAMES:
                continue
            if any(basename.endswith(ext) for ext in image_exts):
                image_files.append(name)

        # Natural sort for page order
        image_files.sort(key=lambda x: [
            int(c) if c.isdigit() else c.lower()
            for c in re.split(r"(\d+)", os.path.basename(x))
        ])

        for name in image_files:
            try:
                img_data = zf.read(name)
                base_name = os.path.basename(name)
                out_path = os.path.join(output_dir, base_name)
                if os.path.exists(out_path):
                    stem, ext = os.path.splitext(base_name)
                    out_path = os.path.join(
                        output_dir, f"{stem}_{len(extracted)}{ext}"
                    )
                with open(out_path, "wb") as f:
                    f.write(img_data)
                extracted.append(out_path)
            except (KeyError, zipfile.BadZipFile):
                continue

    return extracted, len(extracted)


# ---- Public API ----


def extract_images(
    input_path: str,
    output_dir: str,
    calibre_path: Optional[str] = None,
    tmp_dir: Optional[str] = None,
) -> tuple[list[str], str]:
    """Extract images from a comic file in page order.

    Supports EPUB, MOBI, AZW, AZW3, PDF, CBZ, ZIP.

    For non-EPUB/non-CBZ formats, Calibre is used to pre-convert to EPUB.

    Args:
        input_path: Path to the comic file.
        output_dir: Directory to save extracted images.
        calibre_path: Optional explicit path to calibre-debug.
        tmp_dir: Optional temp directory for intermediate files.

    Returns:
        Tuple of (list of image paths, format label).
    """
    ext = Path(input_path).suffix.lower()
    temp_dir = tmp_dir or tempfile.mkdtemp(prefix="comics_enhance_")

    if ext == ".epub":
        images, count = extract_images_from_epub(input_path, output_dir)
        if count == 0:
            raise RuntimeError(f"No images found in {input_path}")
        return images, "epub"

    elif ext in {".cbz", ".zip"}:
        images, count = extract_from_cbz(input_path, output_dir)
        if count == 0:
            raise RuntimeError(f"No images found in {input_path}")
        return images, "cbz"

    elif ext in {".mobi", ".azw", ".azw3", ".pdf"}:
        print(f"    Pre-converting {ext} to EPUB via Calibre...")
        epub_path = convert_to_epub(input_path, temp_dir)
        images, count = extract_images_from_epub(epub_path, output_dir)
        if count == 0:
            raise RuntimeError(f"No images found after converting {input_path}")
        return images, ext

    else:
        raise ValueError(f"Unsupported format: {ext}")


def extract_metadata(input_path: str) -> dict:
    """Extract metadata from a comic file.

    For EPUB, parses the OPF metadata block.
    For other formats, falls back to filename.
    """
    ext = Path(input_path).suffix.lower()
    if ext == ".epub":
        return extract_metadata_from_epub(input_path)

    # Fallback: use filename
    name = Path(input_path).stem
    return {"title": name, "author": ""}
