"""Turn a clean PDF into one that was printed, signed, and faxed back.

The amendment that matters is never a tidy PDF. It is a scan: slightly rotated,
softened by the glass, speckled, compressed to death, with a fax header across
the top and no text layer at all.

That last part is the point. `pipeline.extract()` returns no words for these
pages, so the abstraction agent cannot read them the usual way and has to go
through vision instead. A corpus of clean PDFs never exercises that path, and
a system that silently returns nothing for a scanned amendment is worse than
one that says it cannot read it.
"""

import hashlib
import io
import random
import re
from dataclasses import dataclass
from typing import List, Optional, Tuple

import pymupdf
from PIL import Image, ImageDraw, ImageEnhance, ImageFilter

DEFAULT_DPI = 150


@dataclass(frozen=True)
class ScanProfile:
    """How badly this document was treated on its way to us."""
    name: str
    rotation: float          # degrees of skew from the feeder
    blur: float              # focus softness
    noise: float             # speckle, 0..1
    jpeg_quality: int        # compression artifacts
    contrast: float
    brightness: float
    fax_header: Optional[str] = None
    greyscale: bool = True


CLEAN_SCAN = ScanProfile("clean_scan", 0.4, 0.3, 0.02, 85, 1.05, 1.0)
OFFICE_COPIER = ScanProfile("office_copier", -1.2, 0.6, 0.05, 70, 1.15, 0.97)
BAD_FAX = ScanProfile(
    "bad_fax", 2.1, 1.1, 0.11, 45, 1.35, 0.92,
    fax_header="FROM: SERRAMONTE RETAIL PARTNERS   650-555-0188   PAGE %(page)02d OF %(total)02d",
)

PROFILES = (CLEAN_SCAN, OFFICE_COPIER, BAD_FAX)


def scan(pdf_bytes: bytes, profile: ScanProfile = OFFICE_COPIER,
         dpi: int = DEFAULT_DPI, seed: int = 7) -> bytes:
    """Render every page, degrade it, and reassemble as an image-only PDF."""
    rng = random.Random(seed)
    images: List[Image.Image] = []

    with pymupdf.open(stream=pdf_bytes, filetype="pdf") as doc:
        total = doc.page_count
        for index, page in enumerate(doc, start=1):
            pixmap = page.get_pixmap(dpi=dpi)
            image = Image.frombytes("RGB", (pixmap.width, pixmap.height), pixmap.samples)
            images.append(_degrade(image, profile, rng, index, total))

    return _to_pdf(images)


def _degrade(image: Image.Image, profile: ScanProfile, rng: random.Random,
             page: int, total: int) -> Image.Image:
    if profile.greyscale:
        image = image.convert("L").convert("RGB")

    if profile.fax_header:
        image = _stamp_header(image, profile.fax_header % {"page": page, "total": total})

    # Skew varies slightly page to page, as a sheet feeder does.
    angle = profile.rotation + rng.uniform(-0.3, 0.3)
    image = image.rotate(angle, resample=Image.BICUBIC, fillcolor=(248, 247, 244))

    if profile.blur:
        image = image.filter(ImageFilter.GaussianBlur(profile.blur))

    image = ImageEnhance.Contrast(image).enhance(profile.contrast)
    image = ImageEnhance.Brightness(image).enhance(profile.brightness)

    if profile.noise:
        image = _speckle(image, profile.noise, rng)

    # Round-trip through JPEG so the compression artifacts are real.
    buffer = io.BytesIO()
    image.save(buffer, format="JPEG", quality=profile.jpeg_quality)
    buffer.seek(0)
    return Image.open(buffer).convert("RGB")


def _stamp_header(image: Image.Image, text: str) -> Image.Image:
    draw = ImageDraw.Draw(image)
    draw.rectangle([(0, 0), (image.width, 26)], fill=(236, 234, 230))
    draw.line([(0, 27), (image.width, 27)], fill=(120, 120, 120), width=1)
    draw.text((14, 8), text, fill=(40, 40, 40))
    return image


def _speckle(image: Image.Image, amount: float, rng: random.Random) -> Image.Image:
    pixels = image.load()
    count = int(image.width * image.height * amount * 0.04)
    for _ in range(count):
        x = rng.randrange(image.width)
        y = rng.randrange(image.height)
        shade = rng.choice((0, 0, 60, 200, 255))
        pixels[x, y] = (shade, shade, shade)
    return image


def _to_pdf(images: List[Image.Image]) -> bytes:
    """An image-only PDF: no text layer, which is what forces vision."""
    doc = pymupdf.open()
    for image in images:
        buffer = io.BytesIO()
        image.save(buffer, format="JPEG", quality=80)
        data = buffer.getvalue()

        rect = pymupdf.Rect(0, 0, image.width * 72 / DEFAULT_DPI,
                            image.height * 72 / DEFAULT_DPI)
        page = doc.new_page(width=rect.width, height=rect.height)
        page.insert_image(rect, stream=data)

    doc.set_metadata({})
    out = doc.tobytes()
    doc.close()
    return _fix_id(out)


_PDF_ID = re.compile(rb"/ID\s*\[\s*<[0-9A-Fa-f]+>\s*<[0-9A-Fa-f]+>\s*\]")


def _fix_id(pdf: bytes) -> bytes:
    """Replace the random document id with one derived from the content.

    PyMuPDF writes a fresh /ID on every save, so the same scan hashed
    differently each run. The store is content-addressed and the answer key
    cites documents by sha256, so the bytes have to be reproducible — the same
    reason the lease renderer sets invariant=1.
    """
    digest = hashlib.sha256(_PDF_ID.sub(b"", pdf)).hexdigest()[:32].upper().encode()
    replacement = b"/ID [<" + digest + b"><" + digest + b">]"
    return _PDF_ID.sub(replacement, pdf)


def has_text_layer(pdf_bytes: bytes) -> bool:
    with pymupdf.open(stream=pdf_bytes, filetype="pdf") as doc:
        return any(page.get_text("text").strip() for page in doc)
