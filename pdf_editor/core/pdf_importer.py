"""
pdf_importer.py
===============
Extract field values from a filled Brutto-Netto-Abrechnung PDF by querying
text at each field's known bounding-box coordinates.

Strategy
--------
* Use pypdfium2 (already a project dependency) to open the source PDF and
  obtain a PdfTextPage for page 0.
* For every editable field in FIELD_SPEC, call
  ``PdfTextPage.get_text_bounded(left, bottom, right, top)`` using pypdfium2's
  coordinate system (y=0 at page bottom, matching PDF spec).
* Scale the A4 reference coordinates from FIELD_SPEC to the actual page size
  of the imported PDF — identical approach to ``overlay_editor.create_filled_pdf``.
* Return a ``dict[field_id, extracted_text]`` ready to be loaded into the UI.

Padding philosophy
------------------
We use **zero padding** on all sides by default.  The FIELD_SPEC coordinates are
accurate enough — adding vertical padding pulls in characters from adjacent rows
(column-header labels like 'g', 'p', 'j' appear immediately above empty cells),
and adding horizontal padding pulls in comma/dot glyphs from the previous
column's right edge.

The one documented exception is ``abrechnungsmonat``, whose spec x0 clips the
leading glyph of some month names (e.g. 'Dezember'). That field gets a small
horizontal-only nudge via ``_X0_NUDGE``.

Coordinate systems
------------------
FIELD_SPEC uses pdfplumber / top-origin conventions::

    (x0, top)  →  (x1, bottom)   where y=0 is page *top*

pypdfium2 ``get_text_bounded`` expects PDF / bottom-origin coordinates::

    (left, bottom, right, top)   where y=0 is page *bottom*

Conversion (given page_height in points)::

    pdf_left   = spec_x0   * scale_x
    pdf_right  = spec_x1   * scale_x
    pdf_bottom = page_height - spec_bottom * scale_y
    pdf_top    = page_height - spec_top    * scale_y
"""

from __future__ import annotations

import re

import pypdfium2 as pdfium

from pdf_editor.core.overlay_editor import SPEC_WIDTH, SPEC_HEIGHT
from pdf_editor.core.payroll_fields import FIELD_SPEC

# ── Per-field x0 nudge (horizontal only, in spec points) ─────────────────────
# Only used for fields where the leading glyph sits just left of spec x0.
# Positive value moves x0 leftward (expands the left edge of the bbox).
# Keep at 0 for all other fields to avoid bleeding from adjacent columns.
_X0_NUDGE: dict[str, float] = {
    "abrechnungsmonat": 1.5,   # 'D' of 'Dezember' clips the left edge
    "anw_std":          1.5,   # leading digit clips when value >= 100 (e.g. 192,25)
}


def extract_fields_from_pdf(pdf_path: str) -> dict[str, str]:
    """
    Open *pdf_path* and return a ``{field_id: text}`` mapping for every
    editable field found on page 0.

    Parameters
    ----------
    pdf_path : str
        Path to the filled Brutto-Netto-Abrechnung PDF to import.

    Returns
    -------
    dict[str, str]
        Only fields where non-empty text was found are included.
    """
    doc = pdfium.PdfDocument(pdf_path)
    try:
        page = doc[0]
        page_width  = page.get_width()
        page_height = page.get_height()

        # Scale from A4 spec space → actual page dimensions
        scale_x = page_width  / SPEC_WIDTH
        scale_y = page_height / SPEC_HEIGHT

        textpage = page.get_textpage()

        values: dict[str, str] = {}

        for spec in FIELD_SPEC:
            field_id = spec["id"]

            # Skip internal mask fields and non-editable static fields
            if field_id.startswith("_"):
                continue
            if spec.get("editable") is False:
                continue

            # Convert spec bbox → pdf coordinates (y=0 at bottom).
            # Zero padding on all sides — exact spec coords are accurate.
            # Per-field x0 nudge only for fields with documented left-clip.
            x0_nudge = _X0_NUDGE.get(field_id, 0.0)

            pdf_left   = (spec["x0"] - x0_nudge) * scale_x
            pdf_right  =  spec["x1"]              * scale_x
            pdf_bottom = page_height - spec["bottom"] * scale_y
            pdf_top    = page_height - spec["top"]    * scale_y

            raw = textpage.get_text_bounded(
                left   = pdf_left,
                bottom = pdf_bottom,
                right  = pdf_right,
                top    = pdf_top,
            )

            text = _clean(raw)
            if text:
                values[field_id] = text

        return values

    finally:
        doc.close()


# ── Post-processing ───────────────────────────────────────────────────────────

def _clean(raw: str) -> str:
    """
    Normalise raw extracted text into a clean, single-line string.

    Steps
    -----
    1. Collapse any newlines to spaces (multi-line extractions).
    2. Remove known PDF encoding artefacts (U+FFFD, cp1252 \x83).
    3. Strip leading comma/space prefix that bleeds from previous-column
       decimal separators (e.g. ``', 32,25'`` → ``'32,25'``).
    4. Strip a leading slash + space that bleeds from a '/' separator field.
    5. Strip leading/trailing whitespace.
    6. Discard the result if, after cleaning, the entire string is just a
       single punctuation/symbol character that has no meaning on its own
       (e.g. a lone comma from an empty Lohnarten row).
    """
    if not raw:
        return ""

    # 1. Collapse newlines
    text = " ".join(raw.splitlines())

    # 2. Remove PDF encoding artefacts
    text = text.replace("\ufffd", "")
    text = text.replace("\x83", "")   # cp1252 artefact

    text = text.strip()
    if not text:
        return ""

    # 3. Strip leading ', ' — decimal separator bleeding from previous column
    #    e.g. ', 32,25'  →  '32,25'
    text = re.sub(r'^,\s+', '', text)

    # 4. Strip leading '/ ' — slash separator field bleeding
    #    e.g. '/ 3,50'  →  '3,50'
    text = re.sub(r'^/\s+', '', text)

    text = text.strip()
    if not text:
        return ""

    # 5. Discard lone punctuation/symbols that are clearly noise from empty cells.
    #    A single comma, dot, bracket, or a short all-lowercase label fragment
    #    with no digits is not a real field value.
    if re.match(r'^[,.\(\)\[\]]{1,2}$', text):
        return ""
    # Lone lowercase letters 1-3 chars with no digits = column header bleed
    if re.match(r'^[a-z]{1,3}$', text):
        return ""

    return text
