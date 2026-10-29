"""Shared rendering utilities, focused on byte-deterministic output.

docx/xlsx are zip archives whose entries carry timestamps; PDF producers embed
creation dates. Everything here pins those to fixed values so the same seed
always yields byte-identical files (the determinism test depends on it).
"""

import re
import zipfile
from datetime import date, datetime
from pathlib import Path

# Fixed timestamp stamped into every zip entry and document property.
FIXED_ZIP_DATETIME = (2026, 1, 1, 0, 0, 0)
FIXED_DOC_DATETIME = datetime(2026, 1, 1, 0, 0, 0)
# reportlab/Pillow PDF date strings (PDF date format, UTC).
FIXED_PDF_DATE = "D:20260101000000+00'00'"

_CORE_PROPS_DATE_RE = re.compile(rb"(<dcterms:(?:created|modified)[^>]*>)[^<]*(</dcterms:)")
_FIXED_W3CDTF = b"2026-01-01T00:00:00Z"


def normalize_zip(path: Path) -> None:
    """Rewrite a zip archive (docx/xlsx) with fixed timestamps.

    Entries are re-added in their original order with identical content and
    compression, but with a fixed zip date_time. The created/modified dates in
    docProps/core.xml are also pinned because openpyxl stamps wall-clock time
    on save. Together these remove every source of nondeterminism python-docx
    and openpyxl leave behind.
    """
    tmp = path.with_suffix(path.suffix + ".tmp")
    with (
        zipfile.ZipFile(path, "r") as src,
        zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as dst,
    ):
        for item in src.infolist():
            data = src.read(item.filename)
            if item.filename == "docProps/core.xml":
                data = _CORE_PROPS_DATE_RE.sub(rb"\g<1>" + _FIXED_W3CDTF + rb"\g<2>", data)
            info = zipfile.ZipInfo(item.filename, date_time=FIXED_ZIP_DATETIME)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = item.external_attr
            dst.writestr(info, data)
    path.write_bytes(tmp.read_bytes())
    tmp.unlink()


def fmt_date(d: date) -> str:
    return d.strftime("%d-%b-%Y")
