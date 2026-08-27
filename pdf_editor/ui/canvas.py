"""
canvas.py
=========
PDFCanvas — a QLabel subclass that renders the PDF page pixmap and draws
interactive overlays for word selection (blue outline), per-character
highlights (cyan), and a draggable move block (green).
"""

from PyQt5.QtWidgets import QLabel
from PyQt5.QtGui     import QPixmap, QPainter, QPen, QColor, QCursor
from PyQt5.QtCore    import Qt, QRect


class PDFCanvas(QLabel):
    """
    Interactive PDF page display widget.

    Public API
    ----------
    set_zoom(z)                  Set the current zoom factor.
    set_page_pixmap(pm)          Load a new page pixmap (clears all overlays).
    set_mode(m)                  Switch between 'select' and 'move' modes.
    set_word_highlight(fr)       Highlight a word bounding box (blue dashed).
    set_char_highlights(chars)   Highlight individual char boxes (cyan).
    set_move_block(fr)           Show the green draggable move block.
    clear_all()                  Remove all overlays.

    Callbacks
    ---------
    on_click(pdf_x, pdf_y)       Called when user clicks in 'select' mode.
    on_drag_end(pdf_x, pdf_y)    Called when a move-block drag ends.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAlignment(Qt.AlignTop | Qt.AlignLeft)
        self._zoom        = 1.5
        self._base_pm     = None
        self._word_rect   = None   # QRect — blue word outline
        self._char_rects  = []     # list[QRect] — per-char cyan boxes
        self._move_rect   = None   # QRect — green draggable block
        self._drag_active = False
        self._drag_origin = None
        self.mode         = "select"
        self.on_click     = None   # fn(pdf_x, pdf_y)
        self.on_drag_end  = None   # fn(pdf_x, pdf_y)
        self._update_cursor()

    # ── public API ──────────────────────────────────────────────────────

    def set_zoom(self, z: float):
        self._zoom = z

    def set_page_pixmap(self, pm: QPixmap):
        self._base_pm    = pm
        self._word_rect  = None
        self._char_rects = []
        self._move_rect  = None
        self._refresh()

    def set_mode(self, m: str):
        self.mode = m
        self._update_cursor()
        self._refresh()

    def set_word_highlight(self, fr):
        """*fr* is a namespace/object with x0, y0, x1, y1 in PDF coords."""
        self._word_rect = self._r(fr) if fr else None
        self._refresh()

    def set_char_highlights(self, char_list: list[tuple]):
        """*char_list* — list of (x0, y0, x1, y1) tuples in PDF coords."""
        self._char_rects = [self._r4(c) for c in char_list]
        self._refresh()

    def set_move_block(self, fr):
        self._move_rect = self._r(fr) if fr else None
        self._refresh()

    def clear_all(self):
        self._word_rect  = None
        self._char_rects = []
        self._move_rect  = None
        self._refresh()

    # ── coordinate helpers ──────────────────────────────────────────────

    def _r(self, fr) -> QRect:
        return QRect(
            int(fr.x0 * self._zoom), int(fr.y0 * self._zoom),
            int((fr.x1 - fr.x0) * self._zoom),
            int((fr.y1 - fr.y0) * self._zoom),
        )

    def _r4(self, t: tuple) -> QRect:
        x0, y0, x1, y1 = t
        return QRect(
            int(x0 * self._zoom), int(y0 * self._zoom),
            int((x1 - x0) * self._zoom),
            int((y1 - y0) * self._zoom),
        )

    def _to_pdf(self, qp) -> tuple[float, float]:
        return qp.x() / self._zoom, qp.y() / self._zoom

    # ── painting ────────────────────────────────────────────────────────

    def _refresh(self):
        if self._base_pm is None:
            return
        pm = self._base_pm.copy()
        p  = QPainter(pm)

        # Word outline (blue dashed)
        if self._word_rect:
            fill = QColor("#89b4fa")
            fill.setAlpha(25)
            p.fillRect(self._word_rect, fill)
            p.setPen(QPen(QColor("#89b4fa"), 1, Qt.DashLine))
            p.drawRect(self._word_rect)

        # Per-character boxes (cyan)
        for cr in self._char_rects:
            fill = QColor("#94e2d5")
            fill.setAlpha(60)
            p.fillRect(cr, fill)
            p.setPen(QPen(QColor("#74c7ec"), 1))
            p.drawRect(cr)

        # Movable block (green dashed)
        if self._move_rect:
            fill = QColor("#a6e3a1")
            fill.setAlpha(40)
            p.fillRect(self._move_rect, fill)
            p.setPen(QPen(QColor("#a6e3a1"), 2, Qt.DashLine))
            p.drawRect(self._move_rect)
            # Drag handle indicator
            h = QRect(self._move_rect.x(), self._move_rect.y(), 14, 14)
            p.fillRect(h, QColor("#a6e3a1"))

        p.end()
        self.setPixmap(pm)
        self.resize(pm.size())

    def _update_cursor(self):
        cursor = Qt.OpenHandCursor if self.mode == "move" else Qt.IBeamCursor
        self.setCursor(QCursor(cursor))

    # ── mouse events ────────────────────────────────────────────────────

    def mousePressEvent(self, e):
        if e.button() != Qt.LeftButton:
            return
        if self.mode == "move" and self._move_rect and \
                self._move_rect.contains(e.pos()):
            self._drag_active = True
            self._drag_origin = e.pos() - self._move_rect.topLeft()
            self.setCursor(QCursor(Qt.ClosedHandCursor))
            return
        if self.mode == "select" and self.on_click:
            px, py = self._to_pdf(e.pos())
            self.on_click(px, py)

    def mouseMoveEvent(self, e):
        if self._drag_active and self._move_rect:
            self._move_rect.moveTopLeft(e.pos() - self._drag_origin)
            self._refresh()

    def mouseReleaseEvent(self, e):
        if self._drag_active:
            self._drag_active = False
            self.setCursor(QCursor(Qt.OpenHandCursor))
            if self.on_drag_end and self._move_rect:
                self.on_drag_end(
                    self._move_rect.x() / self._zoom,
                    self._move_rect.y() / self._zoom,
                )
