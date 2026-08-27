"""kumuliert_page.py — Monthly history view with year filter, CSV export, and breakdown chart."""
from __future__ import annotations
import csv
import os

from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtGui import QPainter, QColor, QFont
from PyQt5.QtWidgets import (
    QComboBox, QFileDialog, QFrame, QHBoxLayout, QLabel,
    QPushButton, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)
from pdf_editor.core.number_utils import fmt_de
from pdf_editor.ui import theme

_MONTHS = ["Jan","Feb","Mär","Apr","Mai","Jun","Jul","Aug","Sep","Okt","Nov","Dez"]


class _BreakdownBar(QWidget):
    """Horizontal stacked bar showing Netto / SV / Steuer proportions."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(32)
        self._netto = 0.0
        self._sv = 0.0
        self._steuer = 0.0

    def set_values(self, netto: float, sv: float, steuer: float):
        self._netto = max(netto, 0)
        self._sv = max(sv, 0)
        self._steuer = max(steuer, 0)
        self.update()

    def paintEvent(self, event):
        total = self._netto + self._sv + self._steuer
        if total <= 0:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()
        r = 6  # border radius

        # Draw rounded background
        p.setBrush(QColor(theme.C_BG_ROW))
        p.setPen(Qt.NoPen)
        p.drawRoundedRect(0, 0, w, h, r, r)

        # Segments: Netto (green), SV (orange), Steuer (red)
        segments = [
            (self._netto / total, QColor("#059669"), "Netto"),
            (self._sv / total, QColor("#F59E0B"), "SV"),
            (self._steuer / total, QColor("#DC2626"), "Steuer"),
        ]

        x = 0.0
        for frac, color, label in segments:
            sw = frac * w
            if sw < 1:
                continue
            p.setBrush(color)
            p.drawRoundedRect(int(x), 0, int(sw) + 1, h, r if x == 0 else 0, r if x == 0 else 0)
            # Label inside bar if wide enough
            if sw > 50:
                p.setPen(QColor("#FFFFFF"))
                p.setFont(QFont("Inter", 9, QFont.Bold))
                p.drawText(int(x) + 8, 0, int(sw) - 16, h, Qt.AlignVCenter | Qt.AlignLeft,
                           f"{label} {frac*100:.0f}%")
                p.setPen(Qt.NoPen)
            x += sw
        p.end()


class KumuliertPage(QWidget):
    # Signal: (pers_nr: str, year: int, month: int)
    show_abrechnung = pyqtSignal(str, int, int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setStyleSheet(f"background:{theme.C_BG_APP};")
        self._current_employee: dict | None = None
        self._selected_year: str = ""  # "" = all years

        root = QVBoxLayout(self)
        root.setContentsMargins(0,0,0,0)

        # ── Header ──────────────────────────────────────────────────
        hdr = QWidget()
        hdr.setStyleSheet(f"background:{theme.C_BG_CARD};border-bottom:1px solid {theme.C_BORDER};")
        hl = QHBoxLayout(hdr); hl.setContentsMargins(24,16,24,16); hl.setSpacing(16)
        t = QLabel("Kumulierte Jahreswerte")
        t.setStyleSheet(theme.css_label_header())
        hl.addWidget(t)
        self._hdr_sub = QLabel("")
        self._hdr_sub.setStyleSheet(theme.css_label_sub() + f"; font-size:{theme.SZ_MD}px; margin-left: 12px;")
        hl.addWidget(self._hdr_sub)
        hl.addStretch()

        # Year filter
        yr_lbl = QLabel("Jahr:")
        yr_lbl.setStyleSheet(f"color:{theme.C_TEXT_MUTED}; font-family:{theme.FONT_FAMILY}; "
                             f"font-size:{theme.SZ_MD}px; background:transparent;")
        hl.addWidget(yr_lbl)
        self._year_combo = QComboBox()
        self._year_combo.setMinimumWidth(100)
        self._year_combo.setStyleSheet(
            f"QComboBox {{ background:{theme.C_BG_INPUT}; color:{theme.C_TEXT_MAIN}; "
            f"border:1px solid {theme.C_BORDER}; border-radius:6px; "
            f"padding:6px 10px; font-family:{theme.FONT_FAMILY}; font-size:{theme.SZ_MD}px; }}"
            f"QComboBox::drop-down {{ border:none; width:20px; }}"
            f"QComboBox QAbstractItemView {{ background:{theme.C_BG_INPUT}; color:{theme.C_TEXT_MAIN}; "
            f"selection-background-color:{theme.C_ACCENT}; selection-color:#ffffff; }}"
        )
        self._year_combo.currentTextChanged.connect(self._on_year_changed)
        hl.addWidget(self._year_combo)

        # CSV export button
        export_btn = QPushButton("📥  CSV Export")
        export_btn.setStyleSheet(
            f"QPushButton {{ background:{theme.C_BG_INPUT}; color:{theme.C_TEXT_MAIN}; "
            f"border:1px solid {theme.C_BORDER}; border-radius:6px; "
            f"padding:6px 14px; font-family:{theme.FONT_FAMILY}; font-size:{theme.SZ_MD}px; font-weight:600; }}"
            f"QPushButton:hover {{ background:{theme.C_BG_HOVER}; border-color:{theme.C_ACCENT}; }}"
        )
        export_btn.clicked.connect(self._export_csv)
        hl.addWidget(export_btn)

        root.addWidget(hdr)

        # ── Body ────────────────────────────────────────────────────
        body = QWidget(); body.setStyleSheet(f"background:{theme.C_BG_APP};")
        bl = QVBoxLayout(body); bl.setContentsMargins(24,20,24,24); bl.setSpacing(16)

        # Summary cards
        self._sum_row = QHBoxLayout(); self._sum_row.setSpacing(12)
        self._sum_brutto = self._make_stat("Jahresbrutto", "–")
        self._sum_sv     = self._make_stat("SV-AN gesamt", "–", theme.C_RED)
        self._sum_lst    = self._make_stat("Steuer gesamt", "–", theme.C_RED)
        self._sum_netto  = self._make_stat("Netto gesamt", "–", theme.C_GREEN)
        bl.addLayout(self._sum_row)

        # Breakdown bar
        self._breakdown = _BreakdownBar()
        bl.addWidget(self._breakdown)

        # Table — 9 columns: 8 data + 1 action button
        table_card = QFrame()
        table_card.setStyleSheet(theme.css_card())
        tcl = QVBoxLayout(table_card); tcl.setContentsMargins(0,0,0,0)
        self._table = QTableWidget()
        cols = ["Monat","Brutto","SV-AN","LSt","SolZ","Netto","Σ Brutto","Σ Netto",""]
        self._table.setColumnCount(len(cols))
        self._table.setHorizontalHeaderLabels(cols)
        self._table.setStyleSheet(
            f"QTableWidget{{background:{theme.C_BG_CARD};color:{theme.C_TEXT_MAIN};border:none;"
            f"font-family:{theme.FONT_FAMILY};font-size:{theme.SZ_MD}px;gridline-color:{theme.C_BORDER};}}"
            f"QHeaderView::section{{background:{theme.C_BG_ROW};color:{theme.C_TEXT_MUTED};"
            f"font-size:{theme.SZ_MD}px;font-weight:bold;padding:10px;border:none;border-bottom:1px solid {theme.C_BORDER};}}"
            f"QTableWidget::item{{padding:8px 12px;}}"
            f"QTableWidget::item:selected{{background:{theme.C_BG_HOVER};color:{theme.C_TEXT_MAIN};}}"
        )
        self._table.horizontalHeader().setStretchLastSection(False)
        # Stretch data columns, last column (button) gets fixed width
        from PyQt5.QtWidgets import QHeaderView
        for c in range(8):
            self._table.horizontalHeader().setSectionResizeMode(c, QHeaderView.Stretch)
        self._table.horizontalHeader().setSectionResizeMode(8, QHeaderView.Fixed)
        self._table.setColumnWidth(8, 130)
        self._table.verticalHeader().setVisible(False)
        self._table.setEditTriggers(QTableWidget.NoEditTriggers)
        tcl.addWidget(self._table)
        bl.addWidget(table_card)
        bl.addStretch()
        root.addWidget(body)

    def _make_stat(self, label, value, color=None):
        c = QFrame()
        c.setStyleSheet(theme.css_card())
        cl = QVBoxLayout(c); cl.setContentsMargins(20,14,20,14); cl.setSpacing(4)
        vl = QLabel(value)
        vl.setStyleSheet(f"color:{color or theme.C_TEXT_MAIN};font-family:{theme.FONT_FAMILY};font-size:{theme.SZ_XL}px;"
                         f"font-weight:bold;background:transparent;")
        ll = QLabel(label)
        ll.setStyleSheet(f"color:{theme.C_TEXT_MUTED};font-family:{theme.FONT_FAMILY};font-size:{theme.SZ_SM}px;"
                         f"letter-spacing:1px;background:transparent;")
        cl.addWidget(vl); cl.addWidget(ll)
        self._sum_row.addWidget(c)
        return vl

    # ── Year filter ──────────────────────────────────────────────────

    def _on_year_changed(self, text: str):
        self._selected_year = "" if text == "Alle Jahre" else text
        if self._current_employee:
            self._render(self._current_employee)

    # ── CSV export ───────────────────────────────────────────────────

    def _export_csv(self):
        if not self._current_employee:
            return
        name = self._current_employee.get("vorname_nachname", "export").replace(" ", "_")
        yr = self._selected_year or "alle"
        default_name = f"Kumuliert_{name}_{yr}.csv"
        path, _ = QFileDialog.getSaveFileName(
            self, "CSV Export", default_name, "CSV-Dateien (*.csv)")
        if not path:
            return

        abrechnungen = self._current_employee.get("abrechnungen", {})
        entries = sorted(abrechnungen.items())
        if self._selected_year:
            entries = [(k, v) for k, v in entries if k.startswith(self._selected_year)]

        with open(path, 'w', newline='', encoding='utf-8-sig') as f:
            writer = csv.writer(f, delimiter=';')
            writer.writerow(["Monat", "Brutto", "SV-AN", "LSt", "SolZ", "Netto", "Σ Brutto", "Σ Netto"])
            cum_b = cum_n = 0.0
            for key, vals in entries:
                b   = float(vals.get("abrechnungs_brutto", 0))
                sv  = (float(vals.get("kv_beitrag", 0)) + float(vals.get("rv_beitrag", 0)) +
                       float(vals.get("av_beitrag", 0)) + float(vals.get("pv_beitrag", 0)))
                lst = float(vals.get("lohnsteuer", 0))
                solz = float(vals.get("solz", 0))
                n   = float(vals.get("abrechnungs_netto", 0))
                cum_b += b; cum_n += n
                try:
                    yr_s, mo = key.split("-")
                    monat_lbl = f"{_MONTHS[int(mo)-1]} {yr_s}"
                except Exception:
                    monat_lbl = key
                writer.writerow([monat_lbl, fmt_de(b), fmt_de(sv), fmt_de(lst),
                                 fmt_de(solz), fmt_de(n), fmt_de(cum_b), fmt_de(cum_n)])
        from PyQt5.QtWidgets import QMessageBox
        QMessageBox.information(self, "Export", f"✔  CSV gespeichert:\n{path}")

    # ── Main refresh ─────────────────────────────────────────────────

    def refresh(self, employee: dict | None):
        self._current_employee = employee
        self._table.setRowCount(0)

        if not employee:
            self._hdr_sub.setText("")
            self._sum_brutto.setText("–")
            self._sum_sv.setText("–")
            self._sum_lst.setText("–")
            self._sum_netto.setText("–")
            self._breakdown.set_values(0, 0, 0)
            # Update year combo
            self._year_combo.blockSignals(True)
            self._year_combo.clear()
            self._year_combo.blockSignals(False)
            # Show empty state message
            self._table.setRowCount(1)
            self._table.setSpan(0, 0, 1, 9)
            hint = QTableWidgetItem("Bitte einen Mitarbeiter auswählen, um die Jahresübersicht zu sehen.")
            hint.setTextAlignment(Qt.AlignCenter)
            hint.setFlags(hint.flags() & ~Qt.ItemIsSelectable)
            self._table.setItem(0, 0, hint)
            return

        # Populate year combo from available data
        abrechnungen = employee.get("abrechnungen", {})
        years = sorted(set(k.split("-")[0] for k in abrechnungen.keys())) if abrechnungen else []
        self._year_combo.blockSignals(True)
        prev = self._year_combo.currentText()
        self._year_combo.clear()
        self._year_combo.addItem("Alle Jahre")
        self._year_combo.addItems(years)
        # Restore previous selection if still valid
        idx = self._year_combo.findText(prev)
        if idx >= 0:
            self._year_combo.setCurrentIndex(idx)
        elif years:
            # Default to latest year
            self._year_combo.setCurrentText(years[-1])
            self._selected_year = years[-1]
        self._year_combo.blockSignals(False)

        self._render(employee)

    def _render(self, employee: dict):
        """Render table + stats for the currently selected year filter."""
        self._table.setRowCount(0)

        # Header subtitle
        eintritt = employee.get("eintritt", "")
        name     = employee.get("vorname_nachname", "")
        sub_parts = []
        if name:     sub_parts.append(name)
        if eintritt: sub_parts.append(f"Eintritt: {eintritt}")
        self._hdr_sub.setText("  ·  ".join(sub_parts))

        abrechnungen = employee.get("abrechnungen", {})
        if not abrechnungen:
            self._sum_brutto.setText("0,00 €")
            self._sum_sv.setText("0,00 €")
            self._sum_lst.setText("0,00 €")
            self._sum_netto.setText("0,00 €")
            self._breakdown.set_values(0, 0, 0)
            self._table.setRowCount(1)
            self._table.setSpan(0, 0, 1, 9)
            hint = QTableWidgetItem(f"Noch keine Abrechnung für {name} vorhanden. → Berechnung durchführen.")
            hint.setTextAlignment(Qt.AlignCenter)
            hint.setFlags(hint.flags() & ~Qt.ItemIsSelectable)
            self._table.setItem(0, 0, hint)
            return

        # Filter by year
        entries = sorted(abrechnungen.items())
        if self._selected_year:
            entries = [(k, v) for k, v in entries if k.startswith(self._selected_year)]

        if not entries:
            self._sum_brutto.setText("0,00 €")
            self._sum_sv.setText("0,00 €")
            self._sum_lst.setText("0,00 €")
            self._sum_netto.setText("0,00 €")
            self._breakdown.set_values(0, 0, 0)
            return

        pers_nr = employee.get("pers_nr", "")
        cum_b = cum_sv = cum_lst = cum_n = 0.0
        self._table.setRowCount(len(entries))
        for i, (key, vals) in enumerate(entries):
            b   = float(vals.get("abrechnungs_brutto", 0))
            sv  = (float(vals.get("kv_beitrag", 0)) + float(vals.get("rv_beitrag", 0)) +
                   float(vals.get("av_beitrag", 0)) + float(vals.get("pv_beitrag", 0)))
            lst = float(vals.get("lohnsteuer", 0))
            solz= float(vals.get("solz", 0))
            n   = float(vals.get("abrechnungs_netto", 0))
            cum_b += b; cum_sv += sv; cum_lst += lst + solz; cum_n += n
            # Format month label: "2026-05" → "Mai 2026"
            try:
                yr, mo = key.split("-")
                monat_lbl = f"{_MONTHS[int(mo)-1]} {yr}"
            except Exception:
                monat_lbl = key
                yr, mo = "2026", "01"
            for j, v in enumerate([monat_lbl, fmt_de(b), fmt_de(sv), fmt_de(lst),
                                    fmt_de(solz), fmt_de(n), fmt_de(cum_b), fmt_de(cum_n)]):
                item = QTableWidgetItem(v)
                item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                if j == 0: item.setTextAlignment(Qt.AlignLeft | Qt.AlignVCenter)
                self._table.setItem(i, j, item)

            # ── "📄 Abrechnung" button in last column ──────────────────
            btn = QPushButton("📄 Abrechnung")
            btn.setStyleSheet(
                f"QPushButton {{ background:{theme.C_ACCENT}; color:#ffffff; "
                f"border:none; border-radius:4px; "
                f"padding:5px 10px; font-family:{theme.FONT_FAMILY}; "
                f"font-size:{int(theme.SZ_SM)+1}px; font-weight:600; }}"
                f"QPushButton:hover {{ background:#1D4ED8; }}"
            )
            btn.setCursor(Qt.PointingHandCursor)
            # Capture year/month in closure
            _yr, _mo = int(yr), int(mo)
            btn.clicked.connect(lambda checked, y=_yr, m=_mo: self.show_abrechnung.emit(pers_nr, y, m))
            self._table.setCellWidget(i, 8, btn)

        self._sum_brutto.setText(fmt_de(cum_b) + " €")
        self._sum_sv.setText(fmt_de(cum_sv) + " €")
        self._sum_lst.setText(fmt_de(cum_lst) + " €")
        self._sum_netto.setText(fmt_de(cum_n) + " €")

        # Update breakdown bar
        self._breakdown.set_values(cum_n, cum_sv, cum_lst)
