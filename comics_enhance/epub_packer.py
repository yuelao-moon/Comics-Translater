"""EPUB fixed-layout packer for comic/manga images.

Generates a valid EPUB 3 file from a list of images, supporting:
- Fixed layout (pre-paginated) for comics
- Reading direction: RTL (manga) or LTR (comic)
- Metadata: title, author, language
- Spine ordering in reading order
"""

import os
import uuid
import zipfile
from pathlib import Path
from typing import Optional


# EPUB 3 fixed-layout namespace
NS_OPF = "http://www.idpf.org/2007/opf"
NS_DC = "http://purl.org/dc/elements/1.1/"
NS_XHTML = "http://www.w3.org/1999/xhtml"

EPUB_MIMETYPE = "application/epub+zip"

CONTAINER_XML = '''<?xml version="1.0" encoding="UTF-8"?>
<container version="1.0"
  xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
  <rootfiles>
    <rootfile full-path="OEBPS/content.opf"
      media-type="application/oebps-package+xml"/>
  </rootfiles>
</container>'''


def _image_mime_type(ext: str) -> str:
    """Get MIME type for an image extension."""
    mimes = {
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".png": "image/png",
        ".gif": "image/gif",
        ".webp": "image/webp",
        ".bmp": "image/bmp",
    }
    return mimes.get(ext.lower(), "image/jpeg")


def _page_xhtml(image_rel_path: str) -> str:
    """Generate XHTML wrapper for a single image page (fixed layout)."""
    return f'''<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE html>
<html xmlns="http://www.w3.org/1999/xhtml"
      xmlns:epub="http://www.idpf.org/2007/ops">
<head>
  <meta charset="UTF-8"/>
  <meta name="viewport" content="width=device-width, initial-scale=1.0"/>
  <style type="text/css">
    html, body {{
      margin: 0;
      padding: 0;
      width: 100%;
      height: 100%;
      overflow: hidden;
    }}
    img {{
      width: 100%;
      height: 100%;
      object-fit: contain;
      display: block;
    }}
  </style>
</head>
<body>
  <div>
    <img src="{image_rel_path}" alt="page"/>
  </div>
</body>
</html>'''


def _generate_opf(
    title: str,
    author: str,
    language: str,
    reading_direction: str,
    book_uuid: str,
    page_ids: list[str],
    page_hrefs: list[str],
    image_ids: list[str],
    image_hrefs: list[str],
    image_mimes: list[str],
    cover_image_id: str,
) -> str:
    """Generate content.opf for a fixed-layout comic EPUB."""

    page_rendition = "rtl" if reading_direction == "rtl" else "ltr"
    page_spread = "rtl" if reading_direction == "rtl" else "ltr"

    # Manifest items
    manifest_items = []
    for pid, href, mime in zip(page_ids, page_hrefs, ["application/xhtml+xml"] * len(page_ids)):
        manifest_items.append(
            f'    <item id="{pid}" href="{href}" media-type="{mime}"'
            f' properties="rendition:layout-pre-paginated"/>'
        )
    for iid, href, mime in zip(image_ids, image_hrefs, image_mimes):
        manifest_items.append(
            f'    <item id="{iid}" href="{href}" media-type="{mime}"/>'
        )

    # Spine items
    spine_items = []
    for pid in page_ids:
        spine_items.append(f'    <itemref idref="{pid}" properties="page-spread-right"/>')

    opf = f'''<?xml version="1.0" encoding="UTF-8"?>
<package xmlns="http://www.idpf.org/2007/opf"
         xmlns:dc="http://purl.org/dc/elements/1.1/"
         unique-identifier="book-id" version="3.0">
  <metadata>
    <dc:identifier id="book-id">urn:uuid:{book_uuid}</dc:identifier>
    <dc:title>{_xml_escape(title)}</dc:title>
    <dc:creator>{_xml_escape(author or "Unknown")}</dc:creator>
    <dc:language>{language}</dc:language>
    <meta property="dcterms:modified">{_now_iso()}</meta>
    <meta property="rendition:layout">pre-paginated</meta>
    <meta property="rendition:orientation">auto</meta>
    <meta property="rendition:spread">auto</meta>
    <meta name="cover" content="{cover_image_id}"/>
  </metadata>
  <manifest>
{chr(10).join(manifest_items)}
  </manifest>
  <spine page-progression-direction="{page_spread}">
{chr(10).join(spine_items)}
  </spine>
</package>'''
    return opf


def _xml_escape(text: str) -> str:
    """Escape XML special characters."""
    return (text.replace("&", "&amp;")
                 .replace("<", "&lt;")
                 .replace(">", "&gt;")
                 .replace('"', "&quot;")
                 .replace("'", "&apos;"))


def _now_iso() -> str:
    """Return current UTC time in ISO 8601 format."""
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _page_id(index: int) -> str:
    """Generate page item ID."""
    return f"page_{index:04d}"


def _image_id(index: int) -> str:
    """Generate image item ID."""
    return f"img_{index:04d}"


def _page_href(index: int) -> str:
    """Generate page href in OEBPS."""
    return f"page_{index:04d}.xhtml"


def _image_href(index: int, ext: str) -> str:
    """Generate image href in OEBPS/images/."""
    return f"images/page_{index:04d}{ext}"


# ---- Public API ----


def pack_epub(
    image_paths: list[str],
    output_path: str,
    title: str = "",
    author: str = "",
    language: str = "zh",
    reading_direction: str = "rtl",
) -> str:
    """Pack a list of images into a fixed-layout EPUB 3 file.

    Args:
        image_paths: Sorted list of image file paths (page order).
        output_path: Output EPUB file path.
        title: Book title (defaults to filename stem).
        author: Book author.
        language: Language code (ISO 639-1).
        reading_direction: "rtl" for manga, "ltr" for comic.

    Returns:
        Path to the generated EPUB file.
    """
    if not image_paths:
        raise ValueError("No images to pack")

    total = len(image_paths)
    book_uuid = str(uuid.uuid4())

    if not title:
        title = Path(output_path).stem

    # Prepare EPUB internal paths
    page_ids = []
    page_hrefs = []
    image_ids = []
    image_hrefs = []
    image_mimes = []

    for i, img_path in enumerate(image_paths):
        ext = Path(img_path).suffix
        page_ids.append(_page_id(i))
        page_hrefs.append(_page_href(i))
        image_ids.append(_image_id(i))
        image_hrefs.append(_image_href(i, ext))
        image_mimes.append(_image_mime_type(ext))

    cover_image_id = image_ids[0] if image_ids else "img_0000"

    opf_content = _generate_opf(
        title=title,
        author=author,
        language=language,
        reading_direction=reading_direction,
        book_uuid=book_uuid,
        page_ids=page_ids,
        page_hrefs=page_hrefs,
        image_ids=image_ids,
        image_hrefs=image_hrefs,
        image_mimes=image_mimes,
        cover_image_id=cover_image_id,
    )

    # Write EPUB (ZIP)
    with zipfile.ZipFile(output_path, "w", zipfile.ZIP_DEFLATED) as zf:
        # mimetype must be first, uncompressed
        zf.writestr("mimetype", EPUB_MIMETYPE, compress_type=zipfile.ZIP_STORED)
        zf.writestr("META-INF/container.xml", CONTAINER_XML)
        zf.writestr("OEBPS/content.opf", opf_content)

        for i, img_path in enumerate(image_paths):
            # Write XHTML page
            img_rel = _image_href(i, Path(img_path).suffix)
            xhtml = _page_xhtml(img_rel)
            zf.writestr(f"OEBPS/{_page_href(i)}", xhtml)

            # Write image
            with open(img_path, "rb") as f:
                img_data = f.read()
            zf.writestr(f"OEBPS/{_image_href(i, Path(img_path).suffix)}", img_data)

    return output_path
