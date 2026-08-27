"""
main_window.py
==============
PDFEditor — specialized Brutto-Netto-Abrechnung editor.

Left panel : scrollable form with all editable fields grouped by section.
             Field names are taken from the real PDF column headers.
             Each field has a QLineEdit with live validation and a 600 ms
             debounce that renders an overlay and merges it with the blank
             template, then re-renders the canvas.

Center     : zoomable PDF canvas (read-only view; auto-refreshes on edit).

Architecture
------------
Text values are placed on a transparent overlay PDF (ReportLab) at exact
coordinates from the field spec, then merged onto a blank template (pikepdf).
No PDF stream manipulation — every field is an independent x/y coordinate.
"""

import collections
import io
import os
import re
import shutil
import tempfile
from datetime import datetime

import cv2
import numpy as np
import pypdfium2 as pdfium

from PyQt5.QtCore  import Qt, QTimer
from PyQt5.QtGui   import QColor, QFont, QFontDatabase, QImage, QPainter, QPixmap
from PyQt5.QtWidgets import (
    QAction, QApplication, QFileDialog, QFrame, QGridLayout, QHBoxLayout,
    QLabel, QLineEdit, QMainWindow, QMessageBox, QPushButton,
    QScrollArea, QSizePolicy, QSplitter, QStatusBar, QToolBar,
    QVBoxLayout, QWidget,
)

from pdf_editor.core.overlay_editor import create_filled_pdf
from pdf_editor.core.payroll_fields import (
    FIELD_SPEC, FIELDS_BY_ID, FIELDS_BY_SECTION, SECTIONS,
    TEMPLATE_BLANK_PDF, validate_field,
)
from pdf_editor.core.pdf_importer import extract_fields_from_pdf
from pdf_editor.core.number_utils  import parse_de, fmt_de, parse_abrechnungsmonat
from pdf_editor.core.employee_store import (
    DEFAULT_STORE_DIR, employee_to_field_values,
    get_kum_vormonat, save_monat, MONAT_KEYS,
)
from pdf_editor.core.sv_calculator import (
    calculate_sv, sum_lohnarten_betraege, BBG_KV_2025, BBG_RV_2025,
)
from pdf_editor.ui.canvas import PDFCanvas
from pdf_editor.ui.employee_list import EmployeeListPanel
from pdf_editor.ui.employee_form import EmployeeForm
from pdf_editor.ui.pages.berechnung_page import BerechnungPage
from pdf_editor.ui.pages.kumuliert_page import KumuliertPage
from pdf_editor.ui.pages.einstellungen_page import EinstellungenPage
from pdf_editor.ui import theme


# ── Display names for sections ────────────────────────────────────────────────
SECTION_DISPLAY = {
    "HEADER":                       "KOPFZEILE",
    "PERSÖNLICHE DATEN":            "PERSÖNLICHE DATEN",
    "SOZIALVERSICHERUNG":           "SOZIALVERSICHERUNG",
    "STATISTISCHE WERTE":           "STATISTISCHE WERTE",
    "EMPFÄNGERADRESSE":             "EMPFÄNGERADRESSE",
    "ARBEITGEBER":                  "ARBEITGEBER",
    "KALENDER":                     "KALENDER",
    "LOHNARTEN-TABELLE":            "LOHNARTEN",
    "STEUER-ABRECHNUNG":            "STEUER-ABRECHNUNG",
    "SV-ABRECHNUNG":                "SV-ABRECHNUNG",
    "VERDIENSTBESCHEINIGUNG":       "VERDIENSTBESCHEINIGUNG",
    "NETTO-KORREKTUREN KORR":       "NETTO-KORREKTUREN",
    "BANKVERBINDUNG & AUSZAHLUNG":  "BANKVERBINDUNG & AUSZAHLUNG",
    "ERSTELLUNGSVERMERK":           "ERSTELLUNGSVERMERK",
}

# ── Placeholder text for specific fields ──────────────────────────────────────
PLACEHOLDERS = {
    "abrechnungsmonat":     "z.B. Januar 2026",
    "geburtsdatum":         "TT.MM.JJJJ",
    "eintritt":             "TT.MM.JJJJ",
    "austritt":             "TT.MM.JJJJ",
    "erstellt_am":          "TT.MM.JJJJ",
    "erstellt_um":          "HH:MM",
    "iban":                 "DE00 0000 0000 0000 0000 00",
    "bic":                  "z.B. BELADEBEXXX",
    "pers_nr":              "z.B. 00237",
    "abrechnungs_brutto":   "0,00",
    "auszahlungsbetrag":    "0,00",
    "konfession":           "z.B. ev, rk",
    "erstellt_firmenname":  "Firmenname",
}

# ── Lohnarten row grouping ────────────────────────────────────────────────────
# Row 1 fields have no suffix (except menge_row1), rows 2-5 use _rowN
_LOHNART_ROW_FIELDS = [
    # (suffix, code_id, bez_id, menge_id, faktor_id, zuschlag_id, st_id, sv_id, gb_id, betrag_id)
    ("1", "lohnart", "bezeichnung", "menge_row1", "faktor_pct_row1",
     "pct_zuschlag_row1", "st", "sv", "gb", "betrag_lohnart"),
]
for n in range(2, 6):
    _LOHNART_ROW_FIELDS.append((
        str(n),
        f"lohnart_row{n}", f"bezeichnung_row{n}", f"menge_row{n}",
        f"faktor_pct_row{n}", f"pct_zuschlag_row{n}",
        f"st_row{n}", f"sv_row{n}", f"gb_row{n}", f"betrag_row{n}",
    ))


# ── main window ──────────────────────────────────────────────────────────────

class PDFEditor(QMainWindow):
    """
    Specialized Brutto-Netto-Abrechnung editor.

    Always opens the same template PDF and lets the user fill in the
    highlighted fields via a structured left-panel form.
    """

    RENDER_ZOOM = 1.5

    def __init__(self):
        super().__init__()

        # ── internal state ────────────────────────────────────────────────
        self._template_path: str = TEMPLATE_BLANK_PDF
        self._work_path:     str | None = None
        self._pdfium_doc            = None

        self._undo_stack: collections.deque = collections.deque(maxlen=100)
        self._user_values:     dict[str, str] = {}
        self._field_edits:  dict[str, QLineEdit] = {}
        self._field_timers: dict[str, QTimer]    = {}
        self._lohnart_rows: list = []          # [(row_widget, field_ids)]
        self._lohnart_visible: int = 1         # how many rows visible

        # ── employee / SV state ───────────────────────────────────────────
        self._store_dir:       str       = DEFAULT_STORE_DIR
        self._active_pers_nr:  str | None = None   # employee loaded for current doc
        self._calc_result_labels: dict[str, QLabel] = {}   # id → label in calc card
        self._kum_edits: dict[str, QLineEdit] = {}          # kum Vormonat inputs

        # ── window ────────────────────────────────────────────────────────
        self.setWindowTitle("LohnPRO — Brutto-Netto-Abrechnung")
        self.setMinimumSize(1100, 650)
        self._apply_theme()
        self._build_ui()
        self._build_toolbar()
        self.showMaximized()
        self.statusBar().showMessage(
            "  Mitarbeiter auswählen oder ＋ klicken, um zu beginnen.")
        self.statusBar().setStyleSheet(
            f"background:{theme.C_BG_CARD}; color:{theme.C_TEXT_MUTED}; "
            f"font-family:{theme.FONT_FAMILY}; font-size:{theme.SZ_SM}px; padding:0 16px; "
            f"border-top:1px solid {theme.C_BORDER};")

    # ──────────────────────────────────────────────────────────────────────
    #  Theme
    # ──────────────────────────────────────────────────────────────────────

    def _apply_theme(self):
        self.setStyleSheet(f"""
            QMainWindow {{ background:{theme.C_BG_APP}; }}
            QWidget {{ color:{theme.C_TEXT_MAIN}; }}
            QSplitter::handle {{ background:{theme.C_BORDER}; width:1px; }}

            /* Sidebar scroll area */
            QScrollArea#sidebar_scroll {{ border:none; background:{theme.C_BG_CARD}; }}
            QScrollBar:vertical  {{ background:{theme.C_BG_CARD}; width:8px; border-radius:4px; }}
            QScrollBar::handle:vertical {{
                background:#9CA3AF; border-radius:4px; min-height:30px; }}
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
                height:0; }}
            QScrollBar:horizontal {{ height:0; }}

            /* Center scroll area — light background for white PDFs */
            QScrollArea#canvas_scroll {{
                border:none; background:#E5E7EB; }}
            QScrollArea#canvas_scroll QScrollBar:vertical {{
                background:#E5E7EB; width:10px; border-radius:5px; }}
            QScrollArea#canvas_scroll QScrollBar::handle:vertical {{
                background:#9CA3AF; border-radius:5px; min-height:30px; }}
            QScrollArea#canvas_scroll QScrollBar:horizontal {{
                background:#E5E7EB; height:10px; border-radius:5px; }}
            QScrollArea#canvas_scroll QScrollBar::handle:horizontal {{
                background:#9CA3AF; border-radius:5px; }}

            /* Toolbar */
            QToolBar {{
                background:{theme.C_BG_CARD}; border-bottom:1px solid {theme.C_BORDER};
                spacing:2px; padding:6px 12px; }}
            QToolBar QToolButton {{
                background:transparent; color:{theme.C_TEXT_MUTED};
                border:1px solid transparent; border-radius:6px;
                padding:8px 16px; font-size:{theme.SZ_MD}px;
                font-family:{theme.FONT_FAMILY}; font-weight:500;
                margin:0 2px; }}
            QToolBar QToolButton:hover {{
                background:{theme.C_BG_HOVER}; border:1px solid {theme.C_BORDER}; color:{theme.C_TEXT_MAIN}; }}
            QToolBar QToolButton:pressed {{
                background:{theme.C_BORDER}; }}

            /* Generic buttons */
            QPushButton {{
                background:{theme.C_BG_INPUT}; color:{theme.C_TEXT_MAIN}; border:1px solid {theme.C_BORDER};
                border-radius:6px; padding:8px 16px; font-size:{theme.SZ_MD}px;
                font-family:{theme.FONT_FAMILY}; }}
            QPushButton:hover {{ background:{theme.C_BG_HOVER}; color:{theme.C_TEXT_MAIN}; }}
        """)

    # ──────────────────────────────────────────────────────────────────────
    #  UI construction
    # ──────────────────────────────────────────────────────────────────────

    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        root = QHBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # ── LEFT: Navigation sidebar ──────────────────────────────────────
        from PyQt5.QtWidgets import QStackedWidget
        nav = QFrame()
        nav.setObjectName("nav_sidebar")
        nav.setFixedWidth(240)
        nav.setStyleSheet(
            f"QFrame#nav_sidebar {{ background:{theme.C_BG_CARD}; "
            f"border-right:1px solid {theme.C_BORDER}; }}")
        nav_l = QVBoxLayout(nav)
        nav_l.setContentsMargins(0, 0, 0, 0)
        nav_l.setSpacing(0)

        # ── Brand header ──────────────────────────────────────────────
        brand = QLabel("  LohnPRO")
        brand.setStyleSheet(
            f"color:{theme.C_ACCENT}; font-family:{theme.FONT_FAMILY}; "
            f"font-size:{theme.SZ_LG}px; font-weight:900; "
            f"padding:16px 20px 4px; background:transparent;")
        nav_l.addWidget(brand)
        brand_sub = QLabel("  Brutto-Netto-Abrechnung")
        brand_sub.setStyleSheet(
            f"color:{theme.C_TEXT_MUTED}; font-family:{theme.FONT_FAMILY}; "
            f"font-size:{theme.SZ_SM}px; letter-spacing:1px; "
            f"padding:0 20px 16px; background:transparent;")
        nav_l.addWidget(brand_sub)

        sep0 = QFrame()
        sep0.setFrameShape(QFrame.HLine)
        sep0.setStyleSheet(f"color:{theme.C_BORDER};")
        nav_l.addWidget(sep0)

        # ── Navigation section label ──────────────────────────────────
        nav_hdr = QLabel("  NAVIGATION")
        nav_hdr.setStyleSheet(
            f"color:{theme.C_TEXT_MUTED}; font-family:{theme.FONT_FAMILY}; "
            f"font-size:{theme.SZ_SM}px; font-weight:bold; letter-spacing:2px; "
            f"padding:16px 20px 8px; background:transparent;")
        nav_l.addWidget(nav_hdr)

        # Nav buttons
        self._nav_stack = QStackedWidget()
        self._nav_btns = []

        _NAV_CSS = (
            f"QPushButton {{ background:transparent; color:{theme.C_TEXT_MUTED}; "
            f"border:none; border-left:3px solid transparent; "
            f"padding:14px 20px; text-align:left; font-family:{theme.FONT_FAMILY}; "
            f"font-size:{theme.SZ_MD}px; font-weight:600; }}"
            f"QPushButton:hover {{ background:{theme.C_BG_HOVER}; "
            f"color:{theme.C_TEXT_MAIN}; }}"
        )
        _NAV_ON = (
            f"QPushButton {{ background:{theme.C_BG_ROW}; "
            f"color:{theme.C_ACCENT}; border:none; "
            f"border-left:3px solid {theme.C_ACCENT}; "
            f"padding:14px 20px; text-align:left; font-family:{theme.FONT_FAMILY}; "
            f"font-size:{theme.SZ_MD}px; font-weight:bold; }}"
        )

        def _make_nav_btn(label, idx):
            btn = QPushButton(f"  {label}")
            btn.setStyleSheet(_NAV_CSS)
            btn.clicked.connect(lambda _, i=idx: self._switch_page(i))
            nav_l.addWidget(btn)
            self._nav_btns.append((btn, _NAV_CSS, _NAV_ON))
            return btn

        _make_nav_btn("Abrechnung",    0)
        _make_nav_btn("Berechnung",    1)
        _make_nav_btn("Kumuliert",     2)
        _make_nav_btn("Einstellungen", 3)

        # ── Mitarbeiter section ───────────────────────────────────────
        sep1 = QFrame()
        sep1.setFrameShape(QFrame.HLine)
        sep1.setStyleSheet(f"color:{theme.C_BORDER}; margin:8px 0 0 0;")
        nav_l.addWidget(sep1)
        ma_lbl = QLabel("  MITARBEITER")
        ma_lbl.setStyleSheet(
            f"color:{theme.C_TEXT_MUTED}; font-family:{theme.FONT_FAMILY}; "
            f"font-size:{theme.SZ_SM}px; font-weight:bold; letter-spacing:2px; "
            f"padding:16px 20px 8px; background:transparent;")
        nav_l.addWidget(ma_lbl)
        self._emp_panel = EmployeeListPanel(store_dir=self._store_dir)
        self._emp_panel.add_employee.connect(self._on_add_employee)
        self._emp_panel.edit_employee.connect(self._on_edit_employee)
        self._emp_panel.new_abrechnung.connect(self._new_document_for_pers_nr)
        self._emp_panel.employee_selected.connect(self._on_employee_selected)
        self._emp_panel.employee_deleted.connect(self._on_employee_deleted)
        nav_l.addWidget(self._emp_panel, stretch=1)

        # ── Footer ────────────────────────────────────────────────────
        sep2 = QFrame()
        sep2.setFrameShape(QFrame.HLine)
        sep2.setStyleSheet(f"color:{theme.C_BORDER};")
        nav_l.addWidget(sep2)
        footer = QLabel("  BMF PAP 2026 · §32a EStG")
        footer.setStyleSheet(
            f"color:{theme.C_TEXT_MUTED}; font-family:{theme.FONT_FAMILY}; "
            f"font-size:{theme.SZ_SM}px; padding:12px 20px; background:transparent;")
        nav_l.addWidget(footer)

        root.addWidget(nav)

        # ── RIGHT: Stacked pages ──────────────────────────────────────────
        root.addWidget(self._nav_stack, 1)

        # Page 0: Abrechnung (form + canvas) — built below in existing code
        self._abrechnung_widget = QWidget()
        self._abrechnung_widget.setStyleSheet(f"background:{theme.C_BG_APP};")
        abr_layout = QHBoxLayout(self._abrechnung_widget)
        abr_layout.setContentsMargins(0, 0, 0, 0)
        abr_layout.setSpacing(0)
        self._nav_stack.addWidget(self._abrechnung_widget)   # index 0

        # Page 1: Berechnung
        self._berechnung_page = BerechnungPage()
        self._berechnung_page.abrechnung_ready.connect(self._on_abrechnung_ready)
        self._nav_stack.addWidget(self._berechnung_page)     # index 1

        # Page 2: Kumuliert
        self._kumuliert_page = KumuliertPage()
        self._kumuliert_page.show_abrechnung.connect(self._on_show_month_abrechnung)
        self._nav_stack.addWidget(self._kumuliert_page)      # index 2

        # Page 3: Einstellungen
        self._einstellungen_page = EinstellungenPage()
        self._nav_stack.addWidget(self._einstellungen_page)  # index 3

        # Activate default page
        self._switch_page(0)

        # ── Build Abrechnung page contents (form + splitter + canvas) ─────
        splitter = QSplitter(Qt.Horizontal)
        abr_layout.addWidget(splitter)

        # ── LEFT: field form panel ────────────────────────────────────────
        form_outer = QFrame()
        form_outer.setObjectName("sidebar")
        form_outer.setStyleSheet(
            f"QFrame#sidebar {{ background:{theme.C_BG_CARD}; "
            f"border-right:1px solid {theme.C_BORDER}; }}")
        form_outer.setFixedWidth(440)
        fl = QVBoxLayout(form_outer)
        fl.setContentsMargins(0, 0, 0, 0)
        fl.setSpacing(0)

        hdr = QLabel("   FELDER")
        hdr.setStyleSheet(
            f"color:{theme.C_ACCENT}; font-family:{theme.FONT_FAMILY};"
            f"font-size:{theme.SZ_MD}px; font-weight:bold; "
            f"padding:16px 20px 12px; background:{theme.C_BG_ROW}; "
            f"border-bottom:1px solid {theme.C_BORDER}; letter-spacing:2px;")
        fl.addWidget(hdr)

        form_scroll = QScrollArea()
        form_scroll.setObjectName("sidebar_scroll")
        form_scroll.setWidgetResizable(True)
        form_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

        self._form_body = QWidget()
        self._form_body.setStyleSheet(f"background:{theme.C_BG_CARD};")
        self._form_layout = QVBoxLayout(self._form_body)
        self._form_layout.setContentsMargins(16, 16, 16, 16)
        self._form_layout.setSpacing(12)

        placeholder = QLabel(
            "Klicken Sie oben auf\n'Neue Abrechnung'\num zu beginnen.")
        placeholder.setAlignment(Qt.AlignCenter)
        placeholder.setStyleSheet(
            f"color:{theme.C_TEXT_MUTED}; font-family:{theme.FONT_FAMILY}; "
            f"font-size:{theme.SZ_MD}px; padding:40px 20px;")
        self._form_layout.addWidget(placeholder)
        self._form_placeholder = placeholder
        self._form_layout.addStretch()

        form_scroll.setWidget(self._form_body)
        fl.addWidget(form_scroll)

        splitter.addWidget(form_outer)

        # ── CENTER: PDF canvas ────────────────────────────────────────────
        center = QWidget()
        center.setStyleSheet(f"background:{theme.C_BG_APP};")
        cl = QVBoxLayout(center)
        cl.setContentsMargins(0, 0, 0, 0)
        cl.setSpacing(0)

        # Zoom bar — blends with canvas area
        zbar = QWidget()
        zbar.setStyleSheet(
            f"background:{theme.C_BG_APP}; border-bottom:1px solid {theme.C_BORDER};")
        zl = QHBoxLayout(zbar)
        zl.setContentsMargins(16, 8, 16, 8)
        self._page_label = QLabel("Keine Datei geöffnet")
        self._page_label.setStyleSheet(
            f"color:{theme.C_TEXT_MUTED}; font-family:{theme.FONT_FAMILY}; font-size:{theme.SZ_SM}px;")
        zl.addWidget(self._page_label)
        zl.addStretch()

        zm = QPushButton("−")
        zm.setStyleSheet(
            f"QPushButton {{ background:{theme.C_BG_HOVER}; color:{theme.C_TEXT_MAIN}; "
            f"border:none; border-radius:4px; "
            f"padding:4px 12px; font-size:16px; font-weight:bold; }}"
            f"QPushButton:hover {{ background:{theme.C_BORDER}; }}")
        zm.clicked.connect(self._zoom_out)
        zl.addWidget(zm)

        self._zoom_label = QLabel("150%")
        self._zoom_label.setStyleSheet(
            f"color:{theme.C_TEXT_MUTED}; font-family:{theme.FONT_FAMILY}; "
            f"font-size:{theme.SZ_SM}px; font-weight:600; min-width:50px;")
        self._zoom_label.setAlignment(Qt.AlignCenter)
        zl.addWidget(self._zoom_label)

        zp = QPushButton("+")
        zp.setStyleSheet(
            f"QPushButton {{ background:{theme.C_BG_HOVER}; color:{theme.C_TEXT_MAIN}; "
            f"border:none; border-radius:4px; "
            f"padding:4px 12px; font-size:16px; font-weight:bold; }}"
            f"QPushButton:hover {{ background:{theme.C_BORDER}; }}")
        zp.clicked.connect(self._zoom_in)
        zl.addWidget(zp)
        cl.addWidget(zbar)

        self._scroll = QScrollArea()
        self._scroll.setObjectName("canvas_scroll")
        self._scroll.setAlignment(Qt.AlignCenter)
        self._scroll.setWidgetResizable(False)
        self._canvas = PDFCanvas()
        self._canvas.on_click    = lambda px, py: None
        self._canvas.on_drag_end = lambda *a: None
        self._scroll.setWidget(self._canvas)
        cl.addWidget(self._scroll)
        splitter.addWidget(center)

        splitter.setSizes([380, 1020])
        splitter.setCollapsible(0, False)
        splitter.setCollapsible(1, False)

        self._zoom = 1.5

    def _build_toolbar(self):
        tb = QToolBar()
        tb.setMovable(False)
        self.addToolBar(tb)

        def _div():
            d = QFrame()
            d.setFrameShape(QFrame.VLine)
            d.setStyleSheet("color:#2a2d45; max-height:20px;")
            tb.addWidget(d)

        # ── Document actions ──────────────────────────────────────────
        new_a = QAction("  Neue Abrechnung  ", self)
        new_a.triggered.connect(self._new_document)
        tb.addAction(new_a)

        _div()

        save_a = QAction("  Speichern  ", self)
        save_a.triggered.connect(self._save)
        save_a.setShortcut("Ctrl+S")
        tb.addAction(save_a)

        save_as_a = QAction("  Speichern unter…  ", self)
        save_as_a.triggered.connect(self._save_as)
        tb.addAction(save_as_a)

        _div()

        import_a = QAction("  PDF importieren  ", self)
        import_a.triggered.connect(self._import_pdf)
        import_a.setShortcut("Ctrl+O")
        tb.addAction(import_a)

        _div()

        undo_a = QAction("  Rückgängig  ", self)
        undo_a.triggered.connect(self._undo)
        undo_a.setShortcut("Ctrl+Z")
        tb.addAction(undo_a)

        self._undo_lbl = QLabel("  0 / 100  ")
        self._undo_lbl.setStyleSheet(
            "color:#4a4f6e; font-family:'Segoe UI'; "
            "font-size:11px; padding:0 6px;")
        tb.addWidget(self._undo_lbl)

        _div()

        edit_a = QAction("  ✎ Bearbeiten  ", self)
        edit_a.triggered.connect(self._edit_current_abrechnung)
        tb.addAction(edit_a)


    # ──────────────────────────────────────────────────────────────────────
    #  Document lifecycle
    # ──────────────────────────────────────────────────────────────────────

    def _new_document(self):
        """Create a new document from the blank template."""
        if not os.path.exists(self._template_path):
            QMessageBox.critical(
                self, "Vorlage fehlt",
                f"Die Vorlage-PDF wurde nicht gefunden:\n{self._template_path}")
            return

        tmp = tempfile.NamedTemporaryFile(
            suffix=".pdf", delete=False,
            prefix="abrechnungen_", dir=tempfile.gettempdir())
        tmp.close()

        self._work_path = tmp.name
        self._user_values.clear()
        # Populate with default values from the field spec.
        for f in FIELD_SPEC:
            if f["default_value"]:
                self._user_values[f["id"]] = f["default_value"]

        self._rebuild_pdf()
        self._open_work_file()

    def _open_work_file(self):
        if not self._work_path:
            return

        if self._pdfium_doc:
            self._pdfium_doc.close()
            self._pdfium_doc = None

        self._pdfium_doc = pdfium.PdfDocument(self._work_path)

        self._undo_stack.clear()
        self._update_undo_label()

        self._build_form()
        self._render_page()

        page_h = self._pdfium_doc[0].get_height()
        self._page_label.setText(
            f"Abrechnung — 1 Seite  |  Seitenhöhe: {page_h:.0f} pt")
        self.statusBar().showMessage(
            "Neue Abrechnung geöffnet — Felder ausfüllen und dann "
            "'Speichern unter…'")

    # ──────────────────────────────────────────────────────────────────────
    #  PDF import
    # ──────────────────────────────────────────────────────────────────────

    def _import_pdf(self):
        """
        Let the user pick a filled Brutto-Netto-Abrechnung PDF, extract all
        recognisable field values by coordinate, populate the form, and
        rebuild the live preview.

        Design note
        -----------
        We explicitly zero every editable field in ``_user_values`` BEFORE
        applying extracted values.  ``render_overlay`` falls back to a field's
        ``default_value`` for any key *absent* from ``field_values``, so
        without this step, un-extracted fields would silently render their
        spec defaults — values the imported PDF never contained.
        """
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Ausgefüllte Abrechnung öffnen",
            "",
            "PDF-Dateien (*.pdf)",
        )
        if not path:
            return

        # Show a 'working' cursor while extracting
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            extracted = extract_fields_from_pdf(path)
        except Exception as exc:
            QApplication.restoreOverrideCursor()
            QMessageBox.critical(
                self,
                "Import fehlgeschlagen",
                f"Die PDF konnte nicht gelesen werden:\n{exc}",
            )
            return
        QApplication.restoreOverrideCursor()

        if not extracted:
            QMessageBox.warning(
                self,
                "Keine Felder gefunden",
                "In der gewählten PDF wurden keine bekannten Felder erkannt.\n"
                "Bitte vergewissern Sie sich, dass es sich um eine "
                "Brutto-Netto-Abrechnung handelt.",
            )
            return

        # ── Close any open pdfium document ────────────────────────────────
        if self._pdfium_doc:
            self._pdfium_doc.close()
            self._pdfium_doc = None

        # ── Ensure a temp work file exists ────────────────────────────────
        if not self._work_path:
            tmp = tempfile.NamedTemporaryFile(
                suffix=".pdf", delete=False,
                prefix="abrechnungen_", dir=tempfile.gettempdir())
            tmp.close()
            self._work_path = tmp.name

        # ── Build _user_values from scratch ───────────────────────────────
        # Step 1: pre-zero every editable field so render_overlay cannot
        # fall back to default_value for fields absent from the source PDF.
        self._user_values.clear()
        for spec in FIELD_SPEC:
            fid = spec["id"]
            if fid.startswith("_"):
                continue          # internal mask — renderer owns it
            if spec.get("editable") is False:
                continue          # static fixed field — renderer owns it
            self._user_values[fid] = ""   # explicit empty overrides default

        # Step 2: apply extracted values on top.
        self._undo_stack.clear()
        for field_id, new_text in extracted.items():
            if field_id not in FIELDS_BY_ID:
                continue
            self._user_values[field_id] = new_text
            self._undo_stack.append({
                "field_id":  field_id,
                "old_value": "",
                "new_value": new_text,
            })
        self._update_undo_label()

        # ── Rebuild PDF + UI ──────────────────────────────────────────────
        # _rebuild_pdf writes the correct file; _open_work_file re-opens
        # pdfium, rebuilds the form from the now-correct _user_values,
        # and re-renders the canvas.
        self._rebuild_pdf()
        self._open_work_file()

        n = len(extracted)
        self.statusBar().showMessage(
            f"\u2714  Import abgeschlossen \u2014 {n} Felder aus "
            f"'{os.path.basename(path)}' \u00fcbernommen."
        )


    def _populate_from_values(self, values: dict[str, str]):
        """
        Merge *values* into ``_user_values``, update every matching QLineEdit,
        and rebuild the PDF preview.

        Parameters
        ----------
        values : dict[str, str]
            ``{field_id: text}`` mapping, e.g. from ``extract_fields_from_pdf``.
        """
        if not self._work_path:
            return

        # Push a single 'before-import' undo snapshot for each field that
        # will change, so the user can step back field-by-field if needed.
        for field_id, new_text in values.items():
            fld = FIELDS_BY_ID.get(field_id)
            if fld is None:
                continue
            old_val = self._user_values.get(field_id, fld.get("default_value", ""))
            self._undo_stack.append({
                "field_id":  field_id,
                "old_value": old_val,
                "new_value": new_text,
            })
            self._user_values[field_id] = new_text

        self._update_undo_label()

        # Refresh every QLineEdit that is currently rendered in the form
        for field_id, new_text in values.items():
            edit = self._field_edits.get(field_id)
            if edit is not None:
                edit.blockSignals(True)
                edit.setText(new_text)
                edit.blockSignals(False)

        # Refresh Lohnarten row visibility based on freshly imported data
        if self._lohnart_rows:
            self._update_lohnart_visibility()

        # Rebuild PDF from scratch and update preview
        self._rebuild_pdf()
        self._save_to_work()

    # ──────────────────────────────────────────────────────────────────────
    #  Form panel — building
    # ──────────────────────────────────────────────────────────────────────

    def _build_form(self):
        """Rebuild the left-panel form rows from FIELD_SPEC."""
        for t in self._field_timers.values():
            t.stop()
        self._field_timers.clear()
        self._field_edits.clear()
        self._lohnart_rows.clear()

        # Clear layout
        while self._form_layout.count():
            item = self._form_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        # Custom section order per user preference
        _CUSTOM_ORDER = [
            "PERSÖNLICHE DATEN",         # 1 — open
            "EMPFÄNGERADRESSE",          # 2 — open
            "BANKVERBINDUNG & AUSZAHLUNG", # 3 — open  (swapped with Erstellungsvermerk)
            "LOHNARTEN-TABELLE",         # 4 — open
            "ERSTELLUNGSVERMERK",        # 5 — collapsed (swapped with Bankverbindung)
            "STEUER-ABRECHNUNG",         # 6 — open
            "SV-ABRECHNUNG",             # 7 — open
            "SOZIALVERSICHERUNG",
            "ARBEITGEBER",
            "VERDIENSTBESCHEINIGUNG",
            "NETTO-BEZÜGE/ABZÜGE",
            "STATISTISCHE WERTE",
            "KALENDER",
            "HEADER",                    # last
        ]
        # Sections that start COLLAPSED
        _COLLAPSED_DEFAULT = {
            "ERSTELLUNGSVERMERK",
            "SOZIALVERSICHERUNG",
            "ARBEITGEBER",
            "VERDIENSTBESCHEINIGUNG",
            "NETTO-BEZÜGE/ABZÜGE",
            "STATISTISCHE WERTE",
            "KALENDER",
            "HEADER",
        }


        # Build in custom order, fall back to SECTIONS for any not listed
        ordered = [s for s in _CUSTOM_ORDER if s in SECTIONS]
        remaining = [s for s in SECTIONS if s not in _CUSTOM_ORDER]
        ordered += remaining

        for section in ordered:
            if section not in FIELDS_BY_SECTION:
                continue
            fields = FIELDS_BY_SECTION[section]
            display_name = SECTION_DISPLAY.get(section, section)
            collapsed = section in _COLLAPSED_DEFAULT

            # ── Section card container ────────────────────────────────
            card = QFrame()
            card.setStyleSheet(
                "QFrame { background:#242640; "
                "border:1px solid #2e3150; border-radius:8px; }")
            card_layout = QVBoxLayout(card)
            card_layout.setContentsMargins(0, 0, 0, 0)
            card_layout.setSpacing(0)

            # ── Clickable section header ──────────────────────────────
            arrow = "▶" if collapsed else "▾"
            sec_btn = QPushButton(f"  {arrow}  {display_name}")
            sec_btn.setStyleSheet(
                f"QPushButton {{ "
                f"  background:{theme.C_BG_ROW}; color:{theme.C_ACCENT}; "
                f"  font-family:{theme.FONT_FAMILY}; font-size:{theme.SZ_SM}px; font-weight:800; "
                f"  padding:12px 16px; text-align:left; "
                f"  border:none; "
                f"  border-top-left-radius:8px; border-top-right-radius:8px; "
                f"  border-bottom-left-radius:0; border-bottom-right-radius:0; "
                f"  letter-spacing:2px; }}"
                f"QPushButton:hover {{ background:{theme.C_BG_HOVER}; }}")
            card_layout.addWidget(sec_btn)

            # ── Field container (collapsible) ─────────────────────────
            fields_widget = QWidget()
            fields_widget.setStyleSheet("background:transparent;")
            fw_layout = QVBoxLayout(fields_widget)
            fw_layout.setContentsMargins(0, 6, 0, 10)
            fw_layout.setSpacing(6)

            if section == "LOHNARTEN-TABELLE":
                self._build_lohnarten_section(fw_layout, fields)
            else:
                visible = [f for f in fields
                           if f.get("editable") is not False
                           and not f["id"].startswith("_")]
                _GRID_SECTIONS = {
                    "PERSÖNLICHE DATEN",
                    "SOZIALVERSICHERUNG",
                    "STATISTISCHE WERTE",
                    "KALENDER",
                }
                if section in _GRID_SECTIONS:
                    self._add_mixed_grid(visible, fw_layout)
                else:
                    for f in visible:
                        self._add_field_row(f, fw_layout)

            fields_widget.setVisible(not collapsed)
            card_layout.addWidget(fields_widget)

            # Wire toggle
            def _make_toggle(btn, widget, sec_name=display_name):
                def toggle():
                    vis = widget.isVisible()
                    widget.setVisible(not vis)
                    arrow_new = "▾" if not vis else "▶"
                    btn.setText(f"  {arrow_new}  {sec_name}")
                return toggle

            sec_btn.clicked.connect(_make_toggle(sec_btn, fields_widget))
            self._form_layout.addWidget(card)

        self._form_layout.addStretch()


    def _make_section_header(self, text: str) -> QLabel:
        """Create a styled section header label."""
        lbl = QLabel(f"  {text}")
        lbl.setStyleSheet(
            f"QLabel {{ "
            f"  background:{theme.C_BG_ROW}; color:{theme.C_ACCENT}; "
            f"  font-family:{theme.FONT_FAMILY}; font-size:{theme.SZ_SM}px; font-weight:800; "
            f"  padding:8px 12px; "
            f"  border-left:3px solid {theme.C_ACCENT}; "
            f"  border-radius:4px; "
            f"  letter-spacing:1px; "
            f"}}")
        return lbl

    # CSS constants for normal-sized inputs
    _EDIT_NORMAL = (
        f"QLineEdit {{ "
        f"  font-family:{theme.FONT_FAMILY}; font-size:{theme.SZ_MD}px; "
        f"  min-height:34px; "
        f"  background:{theme.C_BG_INPUT}; "
        f"  border:1px solid {theme.C_BORDER}; border-radius:5px; "
        f"  padding:6px 10px; color:{theme.C_TEXT_MAIN}; "
        f"}} "
        f"QLineEdit:focus {{ "
        f"  border:1px solid {theme.C_BORDER_FOCUS}; "
        f"}} "
    )
    _EDIT_ERROR = (
        f"QLineEdit {{ "
        f"  font-family:{theme.FONT_FAMILY}; font-size:{theme.SZ_MD}px; "
        f"  min-height:34px; "
        f"  background:#FEF2F2; "
        f"  border:1px solid {theme.C_RED}; border-radius:5px; "
        f"  padding:6px 10px; color:{theme.C_TEXT_MAIN}; "
        f"}} "
        f"QLineEdit:focus {{ "
        f"  border:1px solid {theme.C_RED}; "
        f"}} "
    )

    def _add_field_row(self, field: dict, parent_layout: QVBoxLayout):
        """Create a label + QLineEdit row for one field."""
        row = QWidget()
        row.setStyleSheet("background:transparent; border:none;")
        rv  = QVBoxLayout(row)
        rv.setContentsMargins(0, 4, 0, 4)
        rv.setSpacing(3)

        lbl = QLabel(field["label"])
        lbl.setStyleSheet(
            f"QLabel {{ "
            f"  color:{theme.C_TEXT_MUTED}; font-family:{theme.FONT_FAMILY}; font-size:{theme.SZ_SM}px; "
            f"  font-weight:600; padding:0 0 2px 2px; "
            f"  background:transparent; border:none; "
            f"}}")
        rv.addWidget(lbl)

        current_val = self._user_values.get(
            field["id"], field.get("default_value", ""))
        edit = QLineEdit(current_val)
        placeholder = PLACEHOLDERS.get(field["id"], "–")
        edit.setPlaceholderText(placeholder)
        edit.setStyleSheet(self._EDIT_NORMAL)

        # Smart width: narrow inputs for short fields (< 50pt PDF width)
        pdf_width = field.get("x1", 0) - field.get("x0", 0)
        if pdf_width > 0 and pdf_width < 15:
            edit.setMaximumWidth(60)   # 1-2 chars (St.Kl, St, SV, GB)
        elif pdf_width > 0 and pdf_width < 30:
            edit.setMaximumWidth(90)   # 3-4 chars (Faktor, Kinder-FB)
        elif pdf_width > 0 and pdf_width < 50:
            edit.setMaximumWidth(130)  # 5-8 chars (dates, Pers-Nr)
        # Wider fields (addresses, names, etc.) stay full width

        rv.addWidget(edit)

        err_lbl = QLabel("")
        err_lbl.setStyleSheet(
            f"QLabel {{ "
            f"  color:{theme.C_RED}; font-family:{theme.FONT_FAMILY}; font-size:{theme.SZ_SM}px; "
            f"  padding:2px 0 0 2px; background:transparent; border:none; "
            f"}}")
        err_lbl.setVisible(False)
        rv.addWidget(err_lbl)

        parent_layout.addWidget(row)
        self._field_edits[field["id"]] = edit

        # Debounce timer
        timer = QTimer(self)
        timer.setSingleShot(True)
        timer.setInterval(600)
        self._field_timers[field["id"]] = timer

        def _make_handler(fld=field, ed=edit, el=err_lbl, t=timer):
            def _on_edit(text):
                # Auto-format IBAN: insert space every 4 characters
                if fld.get("type") == "iban":
                    raw = text.replace(" ", "").upper()
                    formatted = " ".join(
                        raw[i:i+4] for i in range(0, len(raw), 4))
                    if formatted != text:
                        cursor = ed.cursorPosition()
                        # Count spaces before cursor in old vs new text
                        old_spaces = text[:cursor].count(" ")
                        raw_pos = cursor - old_spaces
                        new_spaces = sum(
                            1 for i in range(len(formatted))
                            if formatted[i] == " "
                            and i < raw_pos + (raw_pos // 4))
                        ed.blockSignals(True)
                        ed.setText(formatted)
                        ed.setCursorPosition(
                            min(raw_pos + new_spaces, len(formatted)))
                        ed.blockSignals(False)
                        text = formatted

                err = validate_field(fld, text)
                if err:
                    ed.setStyleSheet(PDFEditor._EDIT_ERROR)
                    el.setText(err)
                    el.setVisible(True)
                else:
                    ed.setStyleSheet(PDFEditor._EDIT_NORMAL)
                    el.setVisible(False)

                if not err:
                    try:
                        t.timeout.disconnect()
                    except TypeError:
                        pass
                    t.timeout.connect(
                        lambda: self._commit_field(fld, text))
                    t.start()
            return _on_edit

        edit.textEdited.connect(_make_handler())

    def _add_mixed_grid(self, fields: list, parent_layout: QVBoxLayout):
        """Render wide fields normally, then pack short fields into a grid."""
        wide_fields = []
        short_fields = []
        for f in fields:
            pdf_w = f.get("x1", 0) - f.get("x0", 0)
            if pdf_w > 0 and pdf_w < 50:
                short_fields.append(f)
            else:
                wide_fields.append(f)

        # Wide fields rendered normally first
        for f in wide_fields:
            self._add_field_row(f, parent_layout)

        if not short_fields:
            return

        # Grid: determine columns based on count
        cols = 4 if len(short_fields) >= 8 else 3
        grid = QGridLayout()
        grid.setSpacing(6)
        grid.setContentsMargins(0, 4, 0, 4)

        for idx, f in enumerate(short_fields):
            row_i = idx // cols
            col_i = idx % cols

            cell = QWidget()
            cell.setStyleSheet("background:transparent; border:none;")
            cl = QVBoxLayout(cell)
            cl.setContentsMargins(0, 2, 0, 2)
            cl.setSpacing(2)

            lbl = QLabel(f["label"])
            lbl.setStyleSheet(
                "QLabel { "
                "  color:#7a85a8; font-family:'Segoe UI'; font-size:11px; "
                "  font-weight:600; background:transparent; border:none; "
                "}")
            cl.addWidget(lbl)

            val = self._user_values.get(f["id"], f.get("default_value", ""))
            edit = QLineEdit(val)
            edit.setPlaceholderText(PLACEHOLDERS.get(f["id"], "–"))
            edit.setStyleSheet(self._LINEEDIT_STYLE_COMPACT)
            edit.setMaximumWidth(75)
            cl.addWidget(edit)

            grid.addWidget(cell, row_i, col_i)
            self._field_edits[f["id"]] = edit

            # Debounce timer + handler (same as compact edits)
            timer = QTimer(self)
            timer.setSingleShot(True)
            timer.setInterval(600)
            self._field_timers[f["id"]] = timer

            def _make_handler(fld=f, ed=edit, t=timer):
                def _on_edit(text):
                    err = validate_field(fld, text)
                    if err:
                        ed.setStyleSheet(
                            "QLineEdit { "
                            "  font-family:'Segoe UI'; font-size:12px; "
                            "  min-height:28px; max-height:28px; "
                            "  background:#3a1a1a; "
                            "  border:1px solid #f38ba8; border-radius:4px; "
                            "  padding:2px 6px; color:#cdd6f4; "
                            "} "
                            "QLineEdit:focus { "
                            "  border:1px solid #f38ba8; background:#3a1a1a; "
                            "} "
                        )
                    else:
                        ed.setStyleSheet(self._LINEEDIT_STYLE_COMPACT)
                    if not err:
                        try:
                            t.timeout.disconnect()
                        except TypeError:
                            pass
                        t.timeout.connect(
                            lambda: self._commit_field(fld, text))
                        t.start()
                return _on_edit
            edit.textEdited.connect(_make_handler())

        parent_layout.addLayout(grid)

    # ──────────────────────────────────────────────────────────────────────
    #  Lohnarten — compact table layout
    # ──────────────────────────────────────────────────────────────────────

    _LINEEDIT_STYLE_COMPACT = (
        "QLineEdit { "
        "  font-family:'Segoe UI'; font-size:12px; "
        "  min-height:28px; max-height:28px; "
        "  background:#2a2d4a; "
        "  border:1px solid #353858; border-radius:4px; "
        "  padding:2px 6px; color:#c8cde0; "
        "} "
        "QLineEdit:focus { "
        "  border:1px solid #6b7fbd; background:#303354; "
        "} "
    )

    def _build_lohnarten_section(self, parent_layout, fields):
        """Build compact Lohnarten rows with collapsible empty rows."""
        self._lohnart_rows.clear()
        self._lohnart_container = QVBoxLayout()
        self._lohnart_container.setSpacing(6)

        for row_def in _LOHNART_ROW_FIELDS:
            row_num = row_def[0]
            field_ids = row_def[1:]  # code, bez, menge, faktor, zuschlag, st, sv, gb, betrag
            row_widget = self._build_lohnart_row(row_num, field_ids)
            self._lohnart_rows.append((row_widget, field_ids))
            self._lohnart_container.addWidget(row_widget)

        parent_layout.addLayout(self._lohnart_container)

        # "+ Zeile hinzufügen" button
        self._lohnart_add_btn = QPushButton("＋  Zeile hinzufügen")
        self._lohnart_add_btn.setStyleSheet(
            "QPushButton { "
            "  background:transparent; color:#6b7fbd; "
            "  font-family:'Segoe UI'; font-size:12px; font-weight:600; "
            "  border:1px dashed #3b3f5c; border-radius:6px; "
            "  padding:8px; "
            "} "
            "QPushButton:hover { background:#2a2d4a; border-color:#6b7fbd; }"
        )
        self._lohnart_add_btn.clicked.connect(self._show_next_lohnart_row)
        parent_layout.addWidget(self._lohnart_add_btn)

        # Initially show rows that have content + 1 empty
        self._update_lohnart_visibility()

    def _build_lohnart_row(self, row_num: str, field_ids: tuple) -> QWidget:
        """Build a single compact Lohnart row card."""
        code_id, bez_id, menge_id, faktor_id, zuschlag_id, \
            st_id, sv_id, gb_id, betrag_id = field_ids

        row = QFrame()
        row.setStyleSheet(
            "QFrame { background:#282b44; border:1px solid #353858; "
            "border-radius:6px; }")
        rl = QVBoxLayout(row)
        rl.setContentsMargins(8, 6, 8, 6)
        rl.setSpacing(4)

        # ── Top line: badge + Code + Bezeichnung ──────────────────────
        top_line = QHBoxLayout()
        top_line.setSpacing(6)

        badge = QLabel(row_num)
        badge.setFixedSize(22, 22)
        badge.setAlignment(Qt.AlignCenter)
        badge.setStyleSheet(
            "QLabel { "
            "  background:#6b7fbd; color:#1a1b2e; "
            "  font-family:'Segoe UI'; font-size:11px; font-weight:bold; "
            "  border-radius:11px; border:none; "
            "}")
        top_line.addWidget(badge)

        code_edit = self._make_compact_edit(code_id, "Code", 60)
        top_line.addWidget(code_edit)

        bez_edit = self._make_compact_edit(bez_id, "Bezeichnung")
        bez_edit.setMinimumWidth(120)
        top_line.addWidget(bez_edit, 1)  # stretch

        rl.addLayout(top_line)

        # ── Bottom line: Menge / Faktor / St / SV / GB / Betrag ───────
        bot_line = QHBoxLayout()
        bot_line.setSpacing(4)

        for fid, ph, w in [
            (menge_id,    "Menge",   50),
            (faktor_id,   "Faktor",  50),
            (zuschlag_id, "%",       35),
            (st_id,       "St",      30),
            (sv_id,       "SV",      30),
            (gb_id,       "GB",      30),
            (betrag_id,   "Betrag",  65),
        ]:
            ed = self._make_compact_edit(fid, ph, w)
            bot_line.addWidget(ed)

        rl.addLayout(bot_line)

        return row

    def _make_compact_edit(self, field_id: str, placeholder: str,
                           width: int = 0) -> QLineEdit:
        """Create a small QLineEdit for Lohnarten sub-fields."""
        spec = FIELDS_BY_ID.get(field_id)
        val = self._user_values.get(
            field_id, spec.get("default_value", "") if spec else "")
        edit = QLineEdit(val)
        edit.setPlaceholderText(placeholder)
        edit.setStyleSheet(self._LINEEDIT_STYLE_COMPACT)
        if width:
            edit.setFixedWidth(width)

        self._field_edits[field_id] = edit

        # Debounce timer
        timer = QTimer(self)
        timer.setSingleShot(True)
        timer.setInterval(600)
        self._field_timers[field_id] = timer

        if spec:
            def _make_handler(fld=spec, ed=edit, t=timer):
                def _on_edit(text):
                    err = validate_field(fld, text)
                    # No inline error label in compact mode — just border color
                    if err:
                        ed.setStyleSheet(
                            "QLineEdit { "
                            "  font-family:'Segoe UI'; font-size:12px; "
                            "  min-height:28px; max-height:28px; "
                            "  background:#3a1a1a; "
                            "  border:1px solid #f38ba8; border-radius:4px; "
                            "  padding:2px 6px; color:#cdd6f4; "
                            "} "
                            "QLineEdit:focus { "
                            "  border:1px solid #f38ba8; background:#3a1a1a; "
                            "} "
                        )
                    else:
                        ed.setStyleSheet(self._LINEEDIT_STYLE_COMPACT)

                    if not err:
                        try:
                            t.timeout.disconnect()
                        except TypeError:
                            pass
                        t.timeout.connect(
                            lambda: self._commit_field(fld, text))
                        t.start()
                return _on_edit

            edit.textEdited.connect(_make_handler())

        return edit

    def _update_lohnart_visibility(self):
        """Show rows with content + 1 empty row. Hide the rest."""
        last_filled = -1
        for i, (row_widget, field_ids) in enumerate(self._lohnart_rows):
            has_content = any(
                self._user_values.get(fid, "").strip()
                for fid in field_ids
                if FIELDS_BY_ID.get(fid)
            )
            if has_content:
                last_filled = i

        show_count = min(last_filled + 2, len(self._lohnart_rows))
        show_count = max(show_count, 1)  # always show at least 1
        self._lohnart_visible = show_count

        for i, (row_widget, _) in enumerate(self._lohnart_rows):
            if i < show_count:
                row_widget.show()
            else:
                row_widget.hide()

        # Hide add button if all rows visible
        if hasattr(self, '_lohnart_add_btn'):
            if show_count < len(self._lohnart_rows):
                self._lohnart_add_btn.show()
            else:
                self._lohnart_add_btn.hide()

    def _show_next_lohnart_row(self):
        """Reveal one more Lohnart row."""
        if self._lohnart_visible < len(self._lohnart_rows):
            self._lohnart_visible += 1
            for i, (row_widget, _) in enumerate(self._lohnart_rows):
                if i < self._lohnart_visible:
                    row_widget.show()
                else:
                    row_widget.hide()
            if self._lohnart_visible < len(self._lohnart_rows):
                self._lohnart_add_btn.show()
            else:
                self._lohnart_add_btn.hide()

    # ──────────────────────────────────────────────────────────────────────
    #  Field commit
    # ──────────────────────────────────────────────────────────────────────

    def _commit_field(self, field: dict, new_text: str):
        """
        Record the user's edit and rebuild the PDF from scratch using the
        overlay approach.
        """
        if not self._work_path:
            return
        if not self._pdfium_doc:
            t = self._field_timers.get(field["id"])
            if t:
                try:
                    t.timeout.disconnect()
                except TypeError:
                    pass
                t.timeout.connect(
                    lambda: self._commit_field(field, new_text))
                t.start(300)
            return

        default_val   = field.get("default_value", "")
        prev_user_val = self._user_values.get(field["id"], default_val)

        if prev_user_val.strip() == new_text.strip():
            return

        self._undo_stack.append({
            "field_id":  field["id"],
            "old_value": prev_user_val,
            "new_value": new_text,
        })
        self._update_undo_label()

        self._user_values[field["id"]] = new_text

        self._rebuild_pdf()
        self._save_to_work()
        self.statusBar().showMessage(
            f"✔  {field['label']}: '{prev_user_val.strip()}' → "
            f"'{new_text}'  (Ctrl+Z rückgängig)")

    def _rebuild_pdf(self):
        """Create a new PDF by rendering all user values as an overlay."""
        if not self._work_path:
            return

        if self._pdfium_doc:
            self._pdfium_doc.close()
            self._pdfium_doc = None

        field_values = {}
        for fid, val in self._user_values.items():
            field_values[fid] = val

        create_filled_pdf(
            template_path=self._template_path,
            field_values=field_values,
            field_spec=FIELD_SPEC,
            output_path=self._work_path,
        )

    def _save_to_work(self):
        """Reload pdfium from the work file and re-render the canvas."""
        if not self._work_path:
            return
        if not self._pdfium_doc:
            self._pdfium_doc = pdfium.PdfDocument(self._work_path)
        self._render_page()

    # ──────────────────────────────────────────────────────────────────────
    #  Undo
    # ──────────────────────────────────────────────────────────────────────

    def _undo(self):
        if not self._undo_stack:
            self.statusBar().showMessage("No undo steps available.")
            return
        rec = self._undo_stack.pop()
        self._update_undo_label()

        fld     = FIELDS_BY_ID[rec["field_id"]]
        restore = rec["old_value"]
        default_val = fld.get("default_value", "")

        if restore.strip() == default_val.strip():
            self._user_values[fld["id"]] = default_val
        else:
            self._user_values[fld["id"]] = restore

        self._rebuild_pdf()

        if fld["id"] in self._field_edits:
            self._field_edits[fld["id"]].blockSignals(True)
            self._field_edits[fld["id"]].setText(restore.strip())
            self._field_edits[fld["id"]].blockSignals(False)
        self._save_to_work()
        self.statusBar().showMessage(
            f"[Undo] {fld['label']} -> '{restore.strip()}'")

    def _update_undo_label(self):
        n   = len(self._undo_stack)
        cap = self._undo_stack.maxlen
        if n == 0:
            self._undo_lbl.setText("  0 / 100  ")
            self._undo_lbl.setStyleSheet(
                "color:#4a4f6e; font-family:'Segoe UI'; "
                "font-size:11px; padding:0 6px;")
        else:
            self._undo_lbl.setText(f"  {n}/{cap}  ")
            self._undo_lbl.setStyleSheet(
                "color:#7dba8c; font-family:'Segoe UI'; "
                "font-size:11px; font-weight:600; padding:0 6px;")

    # ──────────────────────────────────────────────────────────────────────
    #  Save
    # ──────────────────────────────────────────────────────────────────────

    def _save(self):
        if not self._work_path:
            self._save_as()
            return
        errors = self._collect_errors()
        if errors:
            QMessageBox.warning(
                self, "Validierungsfehler",
                "Bitte korrigieren Sie die folgenden Felder:\n\n" +
                "\n".join(f"* {e}" for e in errors))
            return
        self.statusBar().showMessage(f"Gespeichert: {self._work_path}")

    def _save_as(self):
        if not self._work_path:
            QMessageBox.information(
                self, "Keine Datei",
                "Oeffnen Sie zuerst eine neue Abrechnung.")
            return
        errors = self._collect_errors()
        if errors:
            QMessageBox.warning(
                self, "Validierungsfehler",
                "Bitte korrigieren Sie die folgenden Felder:\n\n" +
                "\n".join(f"* {e}" for e in errors))
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "Speichern unter", "", "PDF-Dateien (*.pdf)")
        if path:
            import shutil
            shutil.copy2(self._work_path, path)
            self.statusBar().showMessage(f"Gespeichert unter: {path}")

    def _collect_errors(self) -> list[str]:
        errors = []
        for fld in FIELD_SPEC:
            if not fld.get("required"):
                continue
            val = self._field_edits.get(fld["id"], QLineEdit()).text()
            err = validate_field(fld, val)
            if err:
                errors.append(f"{fld['label']}: {err}")
        return errors

    # ──────────────────────────────────────────────────────────────────────
    #  Rendering
    # ──────────────────────────────────────────────────────────────────────

    def _render_page(self):
        if not self._pdfium_doc:
            return
        ppage = self._pdfium_doc[0]
        bm    = ppage.render(scale=self._zoom)
        pil   = bm.to_pil()
        arr   = np.array(pil.convert("RGB"))
        h, w  = arr.shape[:2]
        qi    = QImage(arr.tobytes(), w, h, w * 3, QImage.Format_RGB888)
        pm    = QPixmap.fromImage(qi)
        self._canvas.set_zoom(self._zoom)
        self._canvas.set_page_pixmap(pm)

    def _zoom_in(self):
        self._zoom = min(self._zoom + 0.25, 4.0)
        self._zoom_label.setText(f"{int(self._zoom * 100)}%")
        self._render_page()

    def _zoom_out(self):
        self._zoom = max(self._zoom - 0.25, 0.5)
        self._zoom_label.setText(f"{int(self._zoom * 100)}%")
        self._render_page()

    # ──────────────────────────────────────────────────────────────────────
    #  Cleanup
    # ──────────────────────────────────────────────────────────────────────

    def closeEvent(self, event):
        for t in self._field_timers.values():
            t.stop()
        if self._pdfium_doc:
            self._pdfium_doc.close()
        super().closeEvent(event)

    # ──────────────────────────────────────────────────────────────────────
    #  Navigation
    # ──────────────────────────────────────────────────────────────────────

    def _switch_page(self, idx: int):
        self._nav_stack.setCurrentIndex(idx)
        for i, (btn, off_css, on_css) in enumerate(self._nav_btns):
            btn.setStyleSheet(on_css if i == idx else off_css)
        # Refresh kumuliert when switching to it
        if idx == 2 and self._active_pers_nr:
            from pdf_editor.core.employee_store import load_employee
            emp = load_employee(self._active_pers_nr, self._store_dir)
            self._kumuliert_page.refresh(emp)
        # Fill berechnung with employee data when switching to it
        if idx == 1 and self._active_pers_nr:
            from pdf_editor.core.employee_store import load_employee
            emp = load_employee(self._active_pers_nr, self._store_dir)
            if emp:
                self._berechnung_page.fill_from_employee(emp)

    def _edit_current_abrechnung(self):
        """Switch to Berechnung page so user can edit the current month's calculation."""
        if self._active_pers_nr:
            from pdf_editor.core.employee_store import load_employee
            emp = load_employee(self._active_pers_nr, self._store_dir)
            if emp:
                # Switch page first (this calls fill_from_employee internally)
                self._switch_page(1)

                # Now OVERRIDE month/year/grundgehalt AFTER _switch_page
                # because _switch_page(1) calls fill_from_employee which
                # auto-advances to the next unprocessed month.
                if hasattr(self, '_last_calc_monat') and self._last_calc_monat:
                    monat_cb = self._berechnung_page._fields.get("monat")
                    jahr_cb = self._berechnung_page._fields.get("ag_jahr")
                    if monat_cb:
                        monat_cb.setCurrentIndex(self._last_calc_monat - 1)  # 0-based
                    if jahr_cb:
                        idx = jahr_cb.findText(str(self._last_calc_jahr))
                        if idx >= 0:
                            jahr_cb.setCurrentIndex(idx)

                if hasattr(self, '_last_calc_grundgehalt') and self._last_calc_grundgehalt:
                    gehalt_w = self._berechnung_page._fields.get("grundgehalt")
                    if gehalt_w:
                        gehalt_w.setText(str(self._last_calc_grundgehalt))

                _MONTHS_DE = ["Januar","Februar","März","April","Mai","Juni",
                              "Juli","August","September","Oktober","November","Dezember"]
                m_name = _MONTHS_DE[self._last_calc_monat - 1] if hasattr(self, '_last_calc_monat') and self._last_calc_monat else ""
                self.statusBar().showMessage(
                    f"✎  Berechnung {m_name} bearbeiten — Werte anpassen und neu berechnen.")
                return
        # No employee selected — just switch to Berechnung
        self._switch_page(1)
        self.statusBar().showMessage(
            "✎  Berechnung — kein Mitarbeiter ausgewählt.")

    # ──────────────────────────────────────────────────────────────────────
    #  Employee management
    # ──────────────────────────────────────────────────────────────────────

    def _on_add_employee(self):
        dlg = EmployeeForm(self, store_dir=self._store_dir)
        if dlg.exec_():
            new_pnr = dlg.get_pers_nr()
            self._emp_panel.refresh()
            # Auto-select the newly created employee
            if new_pnr:
                self._active_pers_nr = new_pnr
                self._emp_panel._on_row_clicked(new_pnr)
                from pdf_editor.core.employee_store import load_employee
                emp = load_employee(new_pnr, self._store_dir)
                if emp:
                    self._berechnung_page.fill_from_employee(emp)
                    self._kumuliert_page.refresh(emp)
                # Switch to Berechnung so user can immediately calculate
                self._switch_page(1)
            self.statusBar().showMessage(
                f"✔  Mitarbeiter '{new_pnr}' gespeichert — Berechnung bereit.")

    def _on_edit_employee(self, pers_nr: str):
        dlg = EmployeeForm(self, store_dir=self._store_dir, pers_nr=pers_nr)
        if dlg.exec_():
            self._emp_panel.refresh()
            self.statusBar().showMessage(
                f"✔  Mitarbeiter '{pers_nr}' aktualisiert.")

    def _on_employee_selected(self, pers_nr: str):
        """Called when user clicks a row in the employee list — show their Kumuliert data."""
        from pdf_editor.core.employee_store import load_employee
        self._active_pers_nr = pers_nr
        emp = load_employee(pers_nr, self._store_dir)
        if emp is None:
            return
        name = emp.get("vorname_nachname", pers_nr)
        self.statusBar().showMessage(
            f"  {name}  ausgewählt — Jahresübersicht wird angezeigt.")
        # Pre-fill Berechnung page silently
        self._berechnung_page.fill_from_employee(emp)
        # Show Kumuliert page with their data
        self._kumuliert_page.refresh(emp)
        self._switch_page(2)

    def _on_employee_deleted(self):
        """Called after an employee is deleted — clears all form state."""
        self._active_pers_nr = None
        # Reset Berechnung form completely (blank slate)
        self._berechnung_page.fill_from_employee({})
        # Clear Kumuliert view
        self._kumuliert_page.refresh(None)
        self.statusBar().showMessage("  Mitarbeiter gelöscht.")

    def _on_abrechnung_ready(self, result, monat: int, jahr: int, monat_values: dict):
        """
        Called when user clicks '→ Abrechnung PDF erstellen' on the Berechnung page.
        1. Save monat_values to employee JSON (Kumuliert history).
        2. Fill all relevant PDF form fields with the calculated values.
        3. Switch to the Abrechnung page (page 0).
        """
        from pdf_editor.core.employee_store import save_monat, load_employee
        from pdf_editor.core.number_utils import fmt_de

        # ── 1. Save to Kumuliert ──────────────────────────────────────────
        # Store last calculation context for the Bearbeiten button
        self._last_calc_monat = monat
        self._last_calc_jahr = jahr
        self._last_calc_grundgehalt = result.grundgehalt
        if self._active_pers_nr:
            save_monat(self._active_pers_nr, jahr, monat, monat_values,
                       store_dir=self._store_dir)
            emp = load_employee(self._active_pers_nr, self._store_dir)
            if emp:
                self._kumuliert_page.refresh(emp)
            # Refresh sidebar so badges/data stay current
            self._emp_panel.refresh()
            # Auto-advance Berechnung Monat combo to next month
            monat_cb = self._berechnung_page._fields.get("monat")
            jahr_cb = self._berechnung_page._fields.get("ag_jahr")
            if monat_cb and jahr_cb:
                next_m = monat % 12  # 0-based index for next month
                if monat == 12:  # wrap to January of next year
                    next_yr = str(jahr + 1)
                    idx = jahr_cb.findText(next_yr)
                    if idx >= 0:
                        jahr_cb.setCurrentIndex(idx)
                monat_cb.setCurrentIndex(next_m)

        # ── 2. Start from a fresh template, then overlay all values ──────────
        self._new_document()   # always reset — clears old template values

        _MONTHS_DE = ["Januar","Februar","März","April","Mai","Juni",
                      "Juli","August","September","Oktober","November","Dezember"]
        monat_name = _MONTHS_DE[monat - 1]

        sv  = result.sv
        pap = result.pap

        # ── Employee Stammdaten ───────────────────────────────────────────────
        if self._active_pers_nr:
            emp = load_employee(self._active_pers_nr, self._store_dir)
            if emp:
                from pdf_editor.core.employee_store import employee_to_field_values
                emp_fields = employee_to_field_values(emp)

                # Mask private fields only for Milo (pers_nr 00237)
                if self._active_pers_nr == "00237":
                    _PRIVATE_FIELDS = {
                        "vorname_nachname", "anrede",
                        "strasse_hausnummer", "plz_ort",
                        "steuer_id", "versicherungs_nr",
                        "geburtsdatum", "iban", "bic", "bank",
                    }
                    for fid in _PRIVATE_FIELDS:
                        if fid in emp_fields and emp_fields[fid]:
                            emp_fields[fid] = ''.join(
                                'x' if c.isalnum() else c
                                for c in emp_fields[fid]
                            )

                for fid, val in emp_fields.items():
                    self._user_values[fid] = val
                    edit = self._field_edits.get(fid)
                    if edit:
                        edit.blockSignals(True); edit.setText(val); edit.blockSignals(False)

        # ── Calculated values → correct FIELD_SPEC IDs ────────────────────────
        lst_total = pap.lst_monat + (getattr(result, "lst_einmal", 0.0) or 0.0)
        fill_map = {
            # Header
            "abrechnungsmonat":              f"{monat_name} {jahr}",
            # Lohnart row 1
            "lohnart":               "100",
            "bezeichnung":           "Gehalt",
            "betrag_lohnart":        fmt_de(result.grundgehalt),
            # Steuer-Abrechnung
            "abrechnungs_brutto":             fmt_de(result.gesamtbrutto),
            "lst_st_brutto_lfd_l":            fmt_de(result.gesamtbrutto),
            "lst_st_abzuege_lfd_l":           fmt_de(lst_total),
            "solz_st_brutto_lfd_l":           fmt_de(result.gesamtbrutto),
            "solz_betrag":                    fmt_de(result.solz_gesamt),
            # Steuerrechtl. Abzüge gesamt = LSt + SolZ + KiSt
            "steuerrechtl_abzuege_gesamt":    fmt_de(lst_total + result.solz_gesamt + result.kist_gesamt),
            # SV-Abrechnung (laufend)
            "kv_sv_brutto_lfd":      fmt_de(sv.kv_sv_brutto),
            "kv_sv_beitrag_lfd":     fmt_de(sv.kv_beitrag_an),
            "rv_sv_brutto_lfd":      fmt_de(sv.rv_sv_brutto),
            "rv_sv_beitrag_lfd":     fmt_de(sv.rv_beitrag_an),
            "av_sv_brutto_lfd":      fmt_de(sv.av_sv_brutto),
            "av_sv_beitrag_lfd":     fmt_de(sv.av_beitrag_an),
            "pv_sv_brutto_lfd":      fmt_de(sv.kv_sv_brutto),
            "pv_sv_beitrag_lfd":     fmt_de(sv.pv_beitrag_an),
            # SV-rechtl. Abzüge gesamt = KV+RV+AV+PV AN
            "sv_rechtl_abzuege_gesamt": fmt_de(
                sv.kv_beitrag_an + sv.rv_beitrag_an + sv.av_beitrag_an + sv.pv_beitrag_an),
            # Netto
            "abrechnungs_netto":     fmt_de(result.netto),
            "auszahlungsbetrag":     fmt_de(result.netto),
            # Verdienstbescheinigung — monthly
            "gesamt_brutto_mtl":     fmt_de(result.gesamtbrutto),
            "nettoentgelt_mtl":      fmt_de(result.netto),
        }

        # KiSt fields — only fill when there's actual church tax (leaves row blank otherwise)
        if result.kist_gesamt > 0:
            fill_map["kist_st_brutto_lfd_l"] = fmt_de(result.gesamtbrutto)
            fill_map["kist_betrag"]           = fmt_de(result.kist_gesamt)

        # ── Kumuliert (year-to-date incl. current month) ──────────────────────
        # save_monat was already called above, so load fresh YTD by summing
        # all months up to and including this one (kum_vormonat gives BEFORE,
        # so we add the current month on top).
        if self._active_pers_nr:
            from pdf_editor.core.employee_store import get_kum_vormonat
            kum_prev = get_kum_vormonat(
                self._active_pers_nr, jahr, monat,
                store_dir=self._store_dir)
            # current month contribution
            brutto_ytd   = kum_prev["abrechnungs_brutto"] + result.gesamtbrutto
            lst_ytd      = kum_prev["lohnsteuer"]         + lst_total
            solz_ytd     = kum_prev["solz"]               + result.solz_gesamt
            kv_ytd       = kum_prev["kv_beitrag"]         + sv.kv_beitrag_an
            rv_ytd       = kum_prev["rv_beitrag"]         + sv.rv_beitrag_an
            av_ytd       = kum_prev["av_beitrag"]         + sv.av_beitrag_an
            pv_ytd       = kum_prev["pv_beitrag"]         + sv.pv_beitrag_an

            kum_map = {
                "abrechnungs_brutto_kum": fmt_de(brutto_ytd),
                "steuer_brutto_kum":      fmt_de(brutto_ytd),
                "sv_brutto_kum":          fmt_de(brutto_ytd),
                "lohnsteuer_kum":         fmt_de(lst_ytd) + "-",
                "solz_kum":               fmt_de(solz_ytd) + "-",
                "kv_beitrag_kum":         fmt_de(kv_ytd) + "-",
                "rv_beitrag_kum":         fmt_de(rv_ytd) + "-",
                "av_beitrag_kum":         fmt_de(av_ytd) + "-",
                "pv_beitrag_kum":         fmt_de(pv_ytd) + "-",
            }
            fill_map.update(kum_map)

            # ── SV-AG-Anteil kumuliert ────────────────────────────────────────
            # Sum AG contributions from all prior months + current
            kv_ag_ytd = kum_prev.get("kv_beitrag_ag", 0.0) + sv.kv_beitrag_ag
            rv_ag_ytd = kum_prev.get("rv_beitrag_ag", 0.0) + sv.rv_beitrag_ag
            av_ag_ytd = kum_prev.get("av_beitrag_ag", 0.0) + sv.av_beitrag_ag
            pv_ag_ytd = kum_prev.get("pv_beitrag_ag", 0.0) + sv.pv_beitrag_ag
            sv_ag_kum = kv_ag_ytd + rv_ag_ytd + av_ag_ytd + pv_ag_ytd
            fill_map["sv_ag_anteil_kum"] = fmt_de(sv_ag_kum) + "-"

        # ── Statistische Werte (auto-calculated from Vertrag) ─────────────
        # SV-AG-Anteil mtl. = total AG contributions for this month
        sv_ag_mtl = sv.kv_beitrag_ag + sv.rv_beitrag_ag + sv.av_beitrag_ag + sv.pv_beitrag_ag
        fill_map["sv_ag_anteil_mtl"] = fmt_de(sv_ag_mtl) + "-"

        # Get employee contract parameters
        emp_data = None
        if self._active_pers_nr:
            emp_data = load_employee(self._active_pers_nr, self._store_dir)

        # Wochenstunden: from employee record, default 40
        try:
            wochenstunden = float(str(emp_data.get("wochenstunden", "40")).replace(",", ".")) if emp_data else 40.0
        except (ValueError, TypeError):
            wochenstunden = 40.0
        if wochenstunden <= 0:
            wochenstunden = 40.0

        # Monats-Stunden = Wochenstunden × 52 / 12
        monats_std = round(wochenstunden * 52 / 12, 2)
        fill_map["anw_std"] = fmt_de(monats_std)

        # Anw.-Tage = Wochenstunden / (Wochenstunden/5) × 52/12
        # = 5 Tage/Woche × 52/12 ≈ 21.67 for full-time
        # For Teilzeit with fewer weekly days, scale proportionally
        tage_pro_woche = min(wochenstunden / 8.0, 5.0)  # max 5 days
        anw_tage = round(tage_pro_woche * 52 / 12, 2)
        fill_map["anw_tage"] = fmt_de(anw_tage)

        # Std.-Lohn = Grundgehalt / Monatsstunden
        if monats_std > 0 and result.grundgehalt > 0:
            std_lohn = round(result.grundgehalt / monats_std, 2)
            fill_map["std_lohn_1"] = fmt_de(std_lohn)
            fill_map["durchschnitt_1"] = fmt_de(std_lohn)
            fill_map["durchschnitt_2"] = fmt_de(std_lohn)

        # Grundlohn = Grundgehalt
        fill_map["grundlohn"] = fmt_de(result.grundgehalt)

        # ── Erstellungsvermerk: real click time + 09.next_month ────────────
        now = datetime.now()
        fill_map["erstellt_um"] = now.strftime("%H:%M")
        # Date = always 09. of the NEXT month after the Lohnabrechnung month
        next_monat = monat % 12 + 1      # 1-based: Jan=1 … Dec=12 → wraps
        next_jahr  = jahr if monat < 12 else jahr + 1
        fill_map["erstellt_am"] = f"09.{next_monat:02d}.{next_jahr}"

        # ── Bank name from employee ───────────────────────────────────────
        if self._active_pers_nr and emp_data:
            bank_name = emp_data.get("bank_name", "")
            if bank_name:
                fill_map["bank"] = bank_name


        for fid, val in fill_map.items():
            self._user_values[fid] = val
            edit = self._field_edits.get(fid)
            if edit:
                edit.blockSignals(True); edit.setText(val); edit.blockSignals(False)

        self._rebuild_pdf()
        self._save_to_work()


        # ── 3. Switch to Abrechnung page ─────────────────────────────────
        self._switch_page(0)
        name = ""
        if self._active_pers_nr:
            emp = load_employee(self._active_pers_nr, self._store_dir)
            if emp: name = emp.get("vorname_nachname", "")
        self.statusBar().showMessage(
            f"✔  Abrechnung {monat_name} {jahr}"
            + (f" für {name}" if name else "")
            + " — gespeichert in Kumuliert · PDF-Felder befüllt.")


    # ── Show a specific month's Abrechnung from Kumuliert ─────────────

    def _on_show_month_abrechnung(self, pers_nr: str, year: int, month: int):
        """Re-generate and display the Lohnabrechnung for a specific month."""
        from pdf_editor.core.employee_store import load_employee
        emp = load_employee(pers_nr, self._store_dir)
        if emp is None:
            self.statusBar().showMessage(f"⚠  Mitarbeiter {pers_nr} nicht gefunden.")
            return

        # Set active employee
        self._active_pers_nr = pers_nr

        # Fill the Berechnung form with employee data
        self._berechnung_page.fill_from_employee(emp)

        # Override month/year to the specific month requested
        monat_cb = self._berechnung_page._fields.get("monat")
        jahr_cb = self._berechnung_page._fields.get("ag_jahr")
        if monat_cb:
            monat_cb.setCurrentIndex(month - 1)  # 0-based index
        if jahr_cb:
            idx = jahr_cb.findText(str(year))
            if idx >= 0:
                jahr_cb.setCurrentIndex(idx)

        # Fill Grundgehalt from the stored month if available
        abrechnungen = emp.get("abrechnungen", {})
        from pdf_editor.core.number_utils import monat_key
        mk = monat_key(year, month)
        stored = abrechnungen.get(mk, {})
        brutto = stored.get("abrechnungs_brutto", 0)
        if brutto:
            grundgehalt_w = self._berechnung_page._fields.get("grundgehalt")
            if grundgehalt_w:
                grundgehalt_w.setText(str(brutto))

        # Run calculation and forward to PDF page
        self._berechnung_page._calculate_and_forward()

        name = emp.get("vorname_nachname", "")
        _MONTHS = ["Januar","Februar","März","April","Mai","Juni",
                    "Juli","August","September","Oktober","November","Dezember"]
        monat_name = _MONTHS[month - 1] if 1 <= month <= 12 else str(month)
        self.statusBar().showMessage(
            f"📄  Abrechnung {monat_name} {year} für {name} — PDF geladen.")


    def _new_document_for_pers_nr(self, pers_nr: str):
        """Create a new Abrechnung pre-filled with an employee's Stammdaten."""
        from pdf_editor.core.employee_store import load_employee
        emp = load_employee(pers_nr, self._store_dir)
        if emp is None:
            QMessageBox.warning(self, "Nicht gefunden",
                                f"Mitarbeiter {pers_nr} nicht gefunden.")
            return
        self._active_pers_nr = pers_nr
        self._new_document()
        # Overlay Stammdaten on top of defaults
        field_vals = employee_to_field_values(emp)
        for fid, val in field_vals.items():
            self._user_values[fid] = val
            edit = self._field_edits.get(fid)
            if edit:
                edit.blockSignals(True)
                edit.setText(val)
                edit.blockSignals(False)
        # Fill Abrechnungsmonat from employee record
        abr_monat = emp.get("abrechnungsmonat", "")
        if abr_monat:
            self._user_values["abrechnungsmonat"] = abr_monat
            edit = self._field_edits.get("abrechnungsmonat")
            if edit:
                edit.blockSignals(True); edit.setText(abr_monat); edit.blockSignals(False)
        # Also pre-fill Berechnung page so user can switch to calculate
        self._berechnung_page.fill_from_employee(emp)
        self._kumuliert_page.refresh(emp)
        self._rebuild_pdf()
        self._save_to_work()
        # Switch to Abrechnung page
        self._switch_page(0)
        self.statusBar().showMessage(
            f"✔  Abrechnung für {emp.get('vorname_nachname', pers_nr)} geöffnet — alle Stammdaten geladen.")


    # ──────────────────────────────────────────────────────────────────────
    #  SV Calculation card
    # ──────────────────────────────────────────────────────────────────────

    def _build_calc_card(self):
        """Build the ⚙ BERECHNUNG card and append it to the form layout."""
        self._calc_result_labels.clear()
        self._kum_edits.clear()

        card = QFrame()
        card.setStyleSheet(
            "QFrame { background:#1e2a20; border:1px solid #2e4535; border-radius:8px; }")
        cl = QVBoxLayout(card)
        cl.setContentsMargins(0, 0, 0, 10)
        cl.setSpacing(6)

        # Header
        hdr = QLabel("  ⚙  BERECHNUNG")
        hdr.setStyleSheet(
            "QLabel { background:#243328; color:#7dba8c; font-family:'Segoe UI'; "
            "font-size:11px; font-weight:bold; padding:10px 16px; "
            "border:none; border-top-left-radius:8px; border-top-right-radius:8px; "
            "letter-spacing:2px; }")
        cl.addWidget(hdr)

        body = QWidget()
        body.setStyleSheet("background:transparent; border:none;")
        bl = QVBoxLayout(body)
        bl.setContentsMargins(12, 4, 12, 4)
        bl.setSpacing(4)

        # Lohnarten-Summe display
        sum_row = QHBoxLayout()
        sum_row.addWidget(QLabel("Lohnarten-Summe:"))
        self._lohnarten_sum_lbl = QLabel("–")
        self._lohnarten_sum_lbl.setStyleSheet(
            "color:#7dba8c; font-weight:bold; font-family:'Segoe UI'; "
            "font-size:13px; background:transparent; border:none;")
        sum_row.addWidget(self._lohnarten_sum_lbl, 1)
        bl.addLayout(sum_row)

        _edit_css = (
            "QLineEdit { background:#1e3025; color:#c8cde0; border:1px solid #2e4535; "
            "border-radius:4px; padding:3px 6px; font-family:'Segoe UI'; font-size:12px; }"
            "QLineEdit:focus { border-color:#7dba8c; }")
        _lbl_css = ("color:#8ab898; font-family:'Segoe UI'; font-size:11px; "
                    "background:transparent; border:none;")

        # SV result rows
        sv_rows = [
            ("kv", "KV-Beitrag AN"),
            ("rv", "RV-Beitrag AN"),
            ("av", "AV-Beitrag AN"),
            ("pv", "PV-Beitrag AN"),
            ("ges", "SV-Abzüge gesamt"),
        ]
        for key, label in sv_rows:
            row = QHBoxLayout()
            lbl = QLabel(f"{label}:")
            lbl.setStyleSheet(_lbl_css)
            row.addWidget(lbl, 1)
            val_lbl = QLabel("–")
            val_lbl.setAlignment(Qt.AlignRight)
            val_lbl.setStyleSheet(
                "color:#c8cde0; font-family:'Segoe UI'; font-size:12px; "
                "font-weight:600; background:transparent; border:none;")
            self._calc_result_labels[key] = val_lbl
            row.addWidget(val_lbl)
            bl.addLayout(row)

        # Berechnen button
        calc_btn = QPushButton("▶  SV berechnen & übernehmen")
        calc_btn.setStyleSheet(
            "QPushButton { background:#2d5c3a; color:#a8e6b0; border:none; "
            "border-radius:6px; padding:8px; font-family:'Segoe UI'; "
            "font-size:12px; font-weight:600; margin-top:4px; }"
            "QPushButton:hover { background:#3a7a4a; }")
        calc_btn.clicked.connect(self._run_sv_calculation)
        bl.addWidget(calc_btn)

        # Separator
        sep = QFrame()
        sep.setFrameShape(QFrame.HLine)
        sep.setStyleSheet("color:#2e4535; margin:4px 0;")
        bl.addWidget(sep)

        # Kumuliert section
        kum_title = QLabel("Kumuliert (Vormonat-Stand):")
        kum_title.setStyleSheet(_lbl_css + " font-weight:bold;")
        bl.addWidget(kum_title)

        kum_fields = [
            ("abrechnungs_brutto", "Brutto kum."),
            ("lohnsteuer",         "LSt kum."),
            ("solz",               "SolZ kum."),
            ("kv_beitrag",         "KV kum."),
            ("rv_beitrag",         "RV kum."),
            ("av_beitrag",         "AV kum."),
            ("pv_beitrag",         "PV kum."),
        ]
        for key, label in kum_fields:
            row = QHBoxLayout()
            lbl = QLabel(f"{label}:")
            lbl.setStyleSheet(_lbl_css)
            lbl.setFixedWidth(110)
            row.addWidget(lbl)
            edit = QLineEdit("0,00")
            edit.setStyleSheet(_edit_css)
            edit.setFixedWidth(110)
            self._kum_edits[key] = edit
            row.addWidget(edit)
            row.addStretch()
            bl.addLayout(row)

        # Alle übernehmen button
        all_btn = QPushButton("✓  Alle Felder (inkl. kumuliert) übernehmen")
        all_btn.setStyleSheet(
            "QPushButton { background:#243328; color:#7dba8c; "
            "border:1px solid #2e4535; border-radius:6px; padding:8px; "
            "font-family:'Segoe UI'; font-size:12px; margin-top:2px; }"
            "QPushButton:hover { background:#2d5c3a; }")
        all_btn.clicked.connect(self._apply_kum_values)
        bl.addWidget(all_btn)

        cl.addWidget(body)
        self._form_layout.addWidget(card)

    # ──────────────────────────────────────────────────────────────────────
    #  SV calculation logic
    # ──────────────────────────────────────────────────────────────────────

    def _auto_sum_lohnarten(self):
        """Sum all Lohnarten Betrag fields and update lohnarten_sum_lbl."""
        total = sum_lohnarten_betraege(self._user_values)
        if hasattr(self, '_lohnarten_sum_lbl'):
            self._lohnarten_sum_lbl.setText(f"{fmt_de(total)} €")
        return total

    def _run_sv_calculation(self):
        """Calculate SV contributions and write results to form + PDF."""
        if not self._work_path:
            QMessageBox.information(self, "Kein Dokument",
                                    "Bitte zuerst eine Abrechnung öffnen.")
            return

        brutto = sum_lohnarten_betraege(self._user_values)

        # Read rates from user_values (fall back to field defaults)
        def _pf(fid, default="0"):
            return parse_de(self._user_values.get(fid, default))

        kk_pct       = _pf("kk_pct", "14,60")
        z_pct        = _pf("z_pct",  "3,50")
        pv_kz        = int(_pf("pv_kinder_kennzeichen", "0"))
        bbg_kv       = float(self._user_values.get("bbg_kv", str(BBG_KV_2025)) or BBG_KV_2025)
        bbg_rv       = float(self._user_values.get("bbg_rv", str(BBG_RV_2025)) or BBG_RV_2025)

        result = calculate_sv(brutto, kk_pct, z_pct, pv_kz, bbg_kv, bbg_rv)

        # Update display labels
        self._calc_result_labels["kv"].setText(f"{fmt_de(result.kv_beitrag_an)} €")
        self._calc_result_labels["rv"].setText(f"{fmt_de(result.rv_beitrag_an)} €")
        self._calc_result_labels["av"].setText(f"{fmt_de(result.av_beitrag_an)} €")
        self._calc_result_labels["pv"].setText(f"{fmt_de(result.pv_beitrag_an)} €")
        self._calc_result_labels["ges"].setText(f"{fmt_de(result.sv_abzuege_ges)} €")

        # Write into PDF fields
        writes = {
            "kv_sv_brutto_lfd":   fmt_de(result.kv_sv_brutto),
            "kv_sv_beitrag_lfd":  fmt_de(result.kv_beitrag_an),
            "rv_sv_brutto_lfd":   fmt_de(result.rv_sv_brutto),
            "rv_sv_beitrag_lfd":  fmt_de(result.rv_beitrag_an),
            "av_sv_brutto_lfd":   fmt_de(result.av_sv_brutto),
            "av_sv_beitrag_lfd":  fmt_de(result.av_beitrag_an),
            "pv_sv_brutto_lfd":   fmt_de(result.pv_sv_brutto),
            "pv_sv_beitrag_lfd":  fmt_de(result.pv_beitrag_an),
            "sv_rechtl_abzuege_gesamt": fmt_de(result.sv_abzuege_ges),
            "abrechnungs_brutto": fmt_de(brutto),
            "gesamt_brutto_mtl":  fmt_de(brutto),
        }
        for fid, val in writes.items():
            self._user_values[fid] = val
            edit = self._field_edits.get(fid)
            if edit:
                edit.blockSignals(True)
                edit.setText(val)
                edit.blockSignals(False)

        # Auto-fill kum Vormonat from history if an employee is loaded
        self._load_kum_from_history()

        self._rebuild_pdf()
        self._save_to_work()
        self.statusBar().showMessage(
            f"✔  SV berechnet: KV {fmt_de(result.kv_beitrag_an)} | "
            f"RV {fmt_de(result.rv_beitrag_an)} | "
            f"AV {fmt_de(result.av_beitrag_an)} | "
            f"PV {fmt_de(result.pv_beitrag_an)} €")

    def _load_kum_from_history(self):
        """
        If an employee is active, load the kum Vormonat-Stand from history
        automatically (user doesn't need to type anything).
        """
        if not self._active_pers_nr:
            return
        abrm = self._user_values.get("abrechnungsmonat", "").strip()
        parsed = parse_abrechnungsmonat(abrm)
        if not parsed:
            return
        year, month = parsed
        kum = get_kum_vormonat(self._active_pers_nr, year, month, self._store_dir)
        for key, edit in self._kum_edits.items():
            val = kum.get(key, 0.0)
            edit.blockSignals(True)
            edit.setText(fmt_de(abs(val)))
            edit.blockSignals(False)

    def _apply_kum_values(self):
        """
        Write cumulative values to the PDF (Vormonat + current month).
        Then save this month's values to the employee history.
        """
        if not self._work_path:
            return

        # Collect current month values
        def _pf(fid):
            return parse_de(self._user_values.get(fid, "0"))

        cur = {
            "abrechnungs_brutto": _pf("abrechnungs_brutto"),
            "lohnsteuer":         _pf("lst_st_abzuege_lfd_l"),
            "solz":               _pf("solz_betrag"),
            "kv_beitrag":         _pf("kv_sv_beitrag_lfd"),
            "rv_beitrag":         _pf("rv_sv_beitrag_lfd"),
            "av_beitrag":         _pf("av_sv_beitrag_lfd"),
            "pv_beitrag":         _pf("pv_sv_beitrag_lfd"),
            "abrechnungs_netto":  _pf("abrechnungs_netto"),
        }

        # Kum = Vormonat + current
        kum_writes = {
            "abrechnungs_brutto_kum": fmt_de(
                parse_de(self._kum_edits["abrechnungs_brutto"].text())
                + cur["abrechnungs_brutto"]),
            "lohnsteuer_kum":  fmt_de(
                parse_de(self._kum_edits["lohnsteuer"].text())
                + cur["lohnsteuer"], trailing_minus=True),
            "solz_kum":        fmt_de(
                parse_de(self._kum_edits["solz"].text())
                + cur["solz"], trailing_minus=True),
            "kv_beitrag_kum":  fmt_de(
                parse_de(self._kum_edits["kv_beitrag"].text())
                + cur["kv_beitrag"], trailing_minus=True),
            "rv_beitrag_kum":  fmt_de(
                parse_de(self._kum_edits["rv_beitrag"].text())
                + cur["rv_beitrag"], trailing_minus=True),
            "av_beitrag_kum":  fmt_de(
                parse_de(self._kum_edits["av_beitrag"].text())
                + cur["av_beitrag"], trailing_minus=True),
            "pv_beitrag_kum":  fmt_de(
                parse_de(self._kum_edits["pv_beitrag"].text())
                + cur["pv_beitrag"], trailing_minus=True),
            "nettoentgelt_mtl": fmt_de(cur["abrechnungs_netto"]),
        }

        for fid, val in kum_writes.items():
            self._user_values[fid] = val
            edit = self._field_edits.get(fid)
            if edit:
                edit.blockSignals(True)
                edit.setText(val)
                edit.blockSignals(False)

        self._rebuild_pdf()
        self._save_to_work()

        # Persist this month to employee history
        if self._active_pers_nr:
            abrm   = self._user_values.get("abrechnungsmonat", "").strip()
            parsed = parse_abrechnungsmonat(abrm)
            if parsed:
                year, month = parsed
                save_monat(self._active_pers_nr, year, month,
                           {k: v for k, v in cur.items()},
                           self._store_dir)
                self.statusBar().showMessage(
                    f"✔  Kumuliert übernommen & Monat {abrm} gespeichert.")
            else:
                self.statusBar().showMessage(
                    "✔  Kumuliert übernommen (Monat nicht erkannt — nicht gespeichert).")
        else:
            self.statusBar().showMessage("✔  Kumulierte Werte übernommen.")
