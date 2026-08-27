"""
overlay_editor.py
=================
Coordinate-based text overlay for fixed-layout PDFs.

Instead of patching the PDF content stream (Tj/TJ operators), this module:
1. Renders a transparent overlay PDF with text placed at exact coordinates
   using ReportLab.
2. Merges the overlay onto the blank template using pikepdf.

Every field is fully independent — changing one never affects another.
"""

import io
import os
import tempfile

import pikepdf
from reportlab.lib.units import inch
from reportlab.pdfgen import canvas
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

# A4 reference dimensions — field coordinates are defined in this space
SPEC_WIDTH  = 595.0
SPEC_HEIGHT = 842.0

# ── Font Registration ────────────────────────────────────────────────────────
# The original documents use ArialMT.  Register the system Arial font so
# ReportLab embeds identical glyphs and metrics.
_ARIAL_PATH = "C:/Windows/Fonts/arial.ttf"
_ARIAL_BOLD_PATH = "C:/Windows/Fonts/arialbd.ttf"
if os.path.exists(_ARIAL_PATH):
    pdfmetrics.registerFont(TTFont("ArialMT", _ARIAL_PATH))
    FONT_NAME = "ArialMT"
else:
    FONT_NAME = "Helvetica"   # fallback for non-Windows systems

if os.path.exists(_ARIAL_BOLD_PATH):
    pdfmetrics.registerFont(TTFont("Arial-BoldMT", _ARIAL_BOLD_PATH))
    FONT_NAME_BOLD = "Arial-BoldMT"
else:
    FONT_NAME_BOLD = "Helvetica-Bold"

FONT_SIZE = 7.99  # exact size from reference PDF (pdfplumber-extracted)
WRAP_LINE_GAP = 1.0  # 1pt empty gap between wrapped lines


def _wrap_text(text: str, font_name: str, font_size: float, max_width: float) -> list[str]:
    """
    Word-wrap *text* so each line fits within *max_width* PDF points.

    Splits on spaces first (word-wrap). If a single word is still wider
    than max_width, it is broken at the character level.

    Returns a list of lines ordered top→bottom (first element is the
    topmost line when rendered).
    """

    def _char_break(word: str) -> list[str]:
        """Break a single word into chunks that each fit within max_width."""
        chunks: list[str] = []
        buf = ""
        for ch in word:
            candidate = buf + ch
            if pdfmetrics.stringWidth(candidate, font_name, font_size) <= max_width:
                buf = candidate
            else:
                if buf:
                    chunks.append(buf)
                buf = ch
        if buf:
            chunks.append(buf)
        return chunks

    words = text.split(" ")
    lines: list[str] = []
    current_line = ""

    for word in words:
        # If the word alone is wider than max_width, break it by character
        if pdfmetrics.stringWidth(word, font_name, font_size) > max_width:
            # Flush current line first
            if current_line:
                lines.append(current_line)
                current_line = ""
            for chunk in _char_break(word):
                lines.append(chunk)
            continue

        candidate = f"{current_line} {word}".strip() if current_line else word
        w = pdfmetrics.stringWidth(candidate, font_name, font_size)
        if w <= max_width:
            current_line = candidate
        else:
            lines.append(current_line)
            current_line = word

    if current_line:
        lines.append(current_line)

    return lines


# ──────────────────────────────────────────────────────────────────────────────
#  Overlay rendering
# ──────────────────────────────────────────────────────────────────────────────

def render_overlay(
    field_values: dict[str, str],
    field_spec: list[dict],
    page_width: float = SPEC_WIDTH,
    page_height: float = SPEC_HEIGHT,
    scale_x: float = 1.0,
    scale_y: float = 1.0,
    font_name: str = FONT_NAME,
    font_size: float = FONT_SIZE,
) -> bytes:
    """
    Create a transparent PDF page with text placed at each field's coordinates.

    Parameters
    ----------
    field_values : dict
        Mapping of field_id → text value to render.
    field_spec : list of dict
        Each dict must have: id, x0, top, x1, bottom, alignment.
        Coordinates are in the A4 reference space (595 × 842 pt).
    page_width, page_height : float
        *Actual* page dimensions of the target template in PDF points.
    scale_x, scale_y : float
        Multipliers to map A4-spec coordinates → actual page coordinates.
    font_name, font_size : float
        Font to use for all text.

    Returns
    -------
    bytes
        PDF file content (single page, transparent background).
    """
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=(page_width, page_height))

    # Build a lookup by ID for quick access
    spec_by_id = {f["id"]: f for f in field_spec}

    # ── Draw text for non-empty values ──
    # Iterate over every field in the spec so that fixed (non-editable)
    # fields like "seite_slash" always render their default_value even
    # when the user has not typed anything.
    c.setFillColorRGB(0, 0, 0)
    for spec in field_spec:
        field_id = spec["id"]
        # If field_id is explicitly in field_values, use that value (even if
        # empty — the user deliberately cleared it).  Only fall back to
        # default_value when the field is *not present* at all.
        if field_id in field_values:
            text = field_values[field_id]
        else:
            text = spec.get("default_value", "")
        if not text or not text.strip():
            continue

        # Scale A4-spec coordinates to actual template coordinates
        x0     = spec["x0"] * scale_x
        top    = spec["top"] * scale_y
        x1     = spec["x1"] * scale_x
        bottom = spec["bottom"] * scale_y
        align  = spec.get("alignment", "left")

        # Per-field font name override (e.g. "Arial-BoldMT" for bold fields)
        current_font_name = spec.get("font_name", font_name)

        # Scale font size proportionally
        # Per-field font_size override takes priority
        if "font_size" in spec:
            current_font_size = spec["font_size"] * scale_y
        else:
            current_font_size = font_size * scale_y
            cell_height = bottom - top

            # Smaller font for very narrow cells (footer area)
            if cell_height < 7 * scale_y:
                current_font_size = 6.0 * scale_y

        # The Excel 'top' is the top of the glyph bounding box (pdfplumber y=0
        # at top).  ReportLab draws at the text baseline (y=0 at bottom).
        # baseline = page_height - top - ascent
        # Helvetica ascent ratio ≈ 0.718 of font size
        # +0.6pt correction: our overlay text was rendering ~0.6pt too high
        ascent = current_font_size * 0.718
        canvas_y = page_height - top - ascent - 0.6

        c.setFont(current_font_name, current_font_size)

        # ── Wrapping support ──────────────────────────────────────────
        if spec.get("wrap"):
            max_width = x1 - x0
            lines = _wrap_text(text, current_font_name, current_font_size, max_width)

            # Lines grow *upward*: the last line sits at the original
            # baseline (canvas_y) and earlier lines are stacked above.
            line_step = current_font_size + WRAP_LINE_GAP  # text height + 1pt gap
            for i, line in enumerate(reversed(lines)):
                y = canvas_y + i * line_step
                if align == "right":
                    c.drawRightString(x1, y, line)
                elif align == "center":
                    mid_x = (x0 + x1) / 2.0
                    c.drawCentredString(mid_x, y, line)
                else:
                    c.drawString(x0, y, line)
        else:
            if align == "right":
                # Right-align: text ends at x1
                c.drawRightString(x1, canvas_y, text)
            elif align == "center":
                # Center-align: text centered between x0 and x1
                mid_x = (x0 + x1) / 2.0
                c.drawCentredString(mid_x, canvas_y, text)
            else:
                # Left-align: text starts at x0
                c.drawString(x0, canvas_y, text)

    c.showPage()
    c.save()
    return buf.getvalue()


# ──────────────────────────────────────────────────────────────────────────────
#  Merge overlay with template
# ──────────────────────────────────────────────────────────────────────────────

def merge_overlay(
    template_path: str,
    overlay_bytes: bytes,
    output_path: str | None = None,
) -> bytes:
    """
    Merge a transparent overlay PDF onto the blank template.

    Parameters
    ----------
    template_path : str
        Path to the blank template PDF (no data values, just lines/labels).
    overlay_bytes : bytes
        The overlay PDF bytes from render_overlay().
    output_path : str or None
        If given, save the merged result to this path.

    Returns
    -------
    bytes
        The merged PDF content.
    """
    # Open the blank template
    template_pdf = pikepdf.open(template_path)
    template_page = template_pdf.pages[0]

    # Open the overlay
    overlay_pdf = pikepdf.open(io.BytesIO(overlay_bytes))
    overlay_page = overlay_pdf.pages[0]

    # Merge: stamp the overlay onto the template page
    # Use pikepdf's page.add_overlay which merges content streams
    template_page.add_overlay(overlay_page)

    # Save to bytes
    buf = io.BytesIO()
    template_pdf.save(buf)
    result = buf.getvalue()

    if output_path:
        with open(output_path, "wb") as f:
            f.write(result)

    template_pdf.close()
    overlay_pdf.close()

    return result


def _get_template_page_size(template_path: str) -> tuple[float, float]:
    """Read the page width and height of the first page in the template."""
    pdf = pikepdf.open(template_path)
    page = pdf.pages[0]
    mediabox = page.mediabox
    w = float(mediabox[2]) - float(mediabox[0])
    h = float(mediabox[3]) - float(mediabox[1])
    pdf.close()
    return w, h


def create_filled_pdf(
    template_path: str,
    field_values: dict[str, str],
    field_spec: list[dict],
    output_path: str | None = None,
) -> bytes:
    """
    High-level convenience: render overlay + merge with template in one call.

    Automatically detects the template's page size and scales the field
    coordinates (defined in the A4 595×842 reference space) to match.

    Parameters
    ----------
    template_path : str
        Path to the blank template PDF.
    field_values : dict
        Mapping of field_id → text value.
    field_spec : list of dict
        Field specification list (coordinates in A4 reference space).
    output_path : str or None
        Optional path to save the result.

    Returns
    -------
    bytes
        The final PDF with all field values placed.
    """
    # Read actual template page size
    tmpl_w, tmpl_h = _get_template_page_size(template_path)

    # Compute scale factors: spec coords (A4) → template coords
    scale_x = tmpl_w / SPEC_WIDTH
    scale_y = tmpl_h / SPEC_HEIGHT

    overlay_bytes = render_overlay(
        field_values, field_spec,
        page_width=tmpl_w, page_height=tmpl_h,
        scale_x=scale_x, scale_y=scale_y,
    )
    return merge_overlay(template_path, overlay_bytes, output_path)
