"""Scanned-style device history records: image-only PDFs rendered with Pillow.

These exercise the OCR ingestion path. Noise and skew are seeded from the lot
number so output is byte-deterministic; PDF metadata dates are pinned.
"""

import random
import zlib
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from gg_synthdata.model import Traveler, World
from gg_synthdata.render.common import FIXED_DOC_DATETIME, fmt_date

_PAGE_W, _PAGE_H = 1275, 1650  # US letter at 150 dpi
_MARGIN = 90


_Font = ImageFont.FreeTypeFont | ImageFont.ImageFont


def _fonts() -> tuple[_Font, _Font]:
    return ImageFont.load_default(size=34), ImageFont.load_default(size=22)


def _speckle(draw: ImageDraw.ImageDraw, rng: random.Random) -> None:
    for _ in range(1400):
        x = rng.randrange(_PAGE_W)
        y = rng.randrange(_PAGE_H)
        shade = rng.randrange(120, 210)
        draw.point((x, y), fill=(shade, shade, shade))


def render_scanned_traveler(world: World, traveler: Traveler, out_dir: Path) -> Path:
    rng = random.Random(zlib.crc32(traveler.lot.encode()))
    title_font, body_font = _fonts()

    image = Image.new("RGB", (_PAGE_W, _PAGE_H), (247, 246, 242))
    draw = ImageDraw.Draw(image)
    _speckle(draw, rng)

    y = _MARGIN
    draw.text((_MARGIN, y), world.company, font=title_font, fill=(25, 25, 30))
    y += 55
    draw.text(
        (_MARGIN, y),
        f"DEVICE HISTORY RECORD - LOT {traveler.lot}",
        font=title_font,
        fill=(25, 25, 30),
    )
    y += 60
    draw.text(
        (_MARGIN, y),
        f"Model: {traveler.model}   Quantity: {traveler.quantity}   "
        f"Started: {fmt_date(traveler.started)}",
        font=body_font,
        fill=(35, 35, 40),
    )
    y += 55
    draw.line((_MARGIN, y, _PAGE_W - _MARGIN, y), fill=(60, 60, 70), width=2)
    y += 20

    columns = ("SEQ", "OPERATION", "PROC", "OPER", "DATE", "RESULT")
    x_positions = (
        _MARGIN,
        _MARGIN + 80,
        _MARGIN + 520,
        _MARGIN + 680,
        _MARGIN + 790,
        _MARGIN + 980,
    )
    for x, label in zip(x_positions, columns, strict=True):
        draw.text((x, y), label, font=body_font, fill=(25, 25, 30))
    y += 40
    for step in traveler.steps:
        values = (
            str(step.seq),
            step.operation[:38],
            step.sop_ref,
            step.operator_initials,
            fmt_date(step.completed),
            step.result.upper(),
        )
        for x, value in zip(x_positions, values, strict=True):
            draw.text((x, y), value, font=body_font, fill=(40, 40, 48))
        y += 42
    y += 30
    draw.text(
        (_MARGIN, y),
        "Reviewed and released per SOP-010.",
        font=body_font,
        fill=(40, 40, 48),
    )
    y += 60
    draw.text((_MARGIN, y), "QA Release Signature:", font=body_font, fill=(40, 40, 48))
    draw.line((_MARGIN + 290, y + 24, _MARGIN + 640, y + 24), fill=(60, 60, 70), width=2)

    angle = ((zlib.crc32(traveler.lot.encode()) % 7) - 3) * 0.35
    image = image.rotate(angle, expand=False, fillcolor=(247, 246, 242))

    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"DHR_{traveler.lot}_scanned.pdf"
    image.save(
        str(path),
        "PDF",
        resolution=150,
        creationDate=FIXED_DOC_DATETIME.timetuple(),
        modDate=FIXED_DOC_DATETIME.timetuple(),
        producer="Halvern Scan Station",
    )
    return path


def render_scanned_corpus(world: World, corpus_dir: Path) -> list[Path]:
    dhr_dir = corpus_dir / "08_production_records"
    return [render_scanned_traveler(world, t, dhr_dir) for t in world.travelers if t.scanned]
