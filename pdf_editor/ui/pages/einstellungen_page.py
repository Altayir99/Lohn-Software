"""einstellungen_page.py — BBG & rates settings."""
from __future__ import annotations
from PyQt5.QtWidgets import (
    QFrame, QGridLayout, QHBoxLayout, QLabel,
    QLineEdit, QPushButton, QVBoxLayout, QWidget,
)
from pdf_editor.core.sv_calculator import (
    BBG_KV_2026, BBG_RV_2026, KV_BASIS, PV_WEST, RV_SATZ,
    AV_SATZ, PV_KINDERLOS, KV_AVG_PAP, GRUNDFREIBETRAG, WKP,
)
from pdf_editor.ui import theme

def _lbl(t):
    l = QLabel(t)
    l.setStyleSheet(theme.css_label_sub())
    return l

def _edit(val):
    e = QLineEdit(str(val))
    e.setStyleSheet(theme.css_input())
    return e

class EinstellungenPage(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setStyleSheet(f"background:{theme.C_BG_APP};")
        self._fields: dict[str, QLineEdit] = {}
        root = QVBoxLayout(self)
        root.setContentsMargins(0,0,0,0)

        hdr = QWidget()
        hdr.setStyleSheet(f"background:{theme.C_BG_CARD};border-bottom:1px solid {theme.C_BORDER};")
        hl = QHBoxLayout(hdr); hl.setContentsMargins(24,20,24,20)
        t = QLabel("Einstellungen")
        t.setStyleSheet(theme.css_label_header())
        s = QLabel("Beitragssätze · BBG · PAP-Parameter 2026")
        s.setStyleSheet(theme.css_label_sub() + f"; font-size:{theme.SZ_MD}px; margin-left: 12px;")
        hl.addWidget(t); hl.addWidget(s); hl.addStretch()
        root.addWidget(hdr)

        body = QWidget(); body.setStyleSheet(f"background:{theme.C_BG_APP};")
        bl = QVBoxLayout(body); bl.setContentsMargins(24,24,24,24); bl.setSpacing(20)

        row = QHBoxLayout(); row.setSpacing(12)

        # SV rates card
        sv_card = QFrame()
        sv_card.setStyleSheet(theme.css_card())
        sv_l = QVBoxLayout(sv_card); sv_l.setContentsMargins(20,20,20,20); sv_l.setSpacing(12)
        hh = QLabel("BEITRAGSSÄTZE SV 2026")
        hh.setStyleSheet(f"color:{theme.C_ACCENT};font-family:{theme.FONT_FAMILY};font-size:{theme.SZ_MD}px;font-weight:bold;"
                         f"letter-spacing:2px;padding-bottom:10px;border-bottom:1px solid {theme.C_BORDER};background:transparent;")
        sv_l.addWidget(hh)
        for lbl_txt, key, default in [
            ("KV-Basissatz gesamt (%)",      "kv_basis",   KV_BASIS),
            ("PV West gesamt (%)",           "pv_west",    PV_WEST),
            ("PV Sachsen AN (%)",            "pv_sach_an", 2.30),
            ("PV Sachsen AG (%)",            "pv_sach_ag", 1.30),
            ("RV gesamt (%)",                "rv_satz",    RV_SATZ),
            ("AV gesamt (%)",                "av_satz",    AV_SATZ),
            ("PV Kinderlos-Zuschlag AN (%)","pv_kinderlos",PV_KINDERLOS),
        ]:
            sv_l.addWidget(_lbl(lbl_txt))
            e = _edit(default); self._fields[key] = e; sv_l.addWidget(e)
        sv_l.addStretch()
        row.addWidget(sv_card)

        # BBG + PAP card
        bbg_card = QFrame()
        bbg_card.setStyleSheet(theme.css_card())
        bbg_l = QVBoxLayout(bbg_card); bbg_l.setContentsMargins(20,20,20,20); bbg_l.setSpacing(12)
        hh2 = QLabel("BBG & PAP-PARAMETER 2026")
        hh2.setStyleSheet(f"color:{theme.C_ACCENT};font-family:{theme.FONT_FAMILY};font-size:{theme.SZ_MD}px;font-weight:bold;"
                          f"letter-spacing:2px;padding-bottom:10px;border-bottom:1px solid {theme.C_BORDER};background:transparent;")
        bbg_l.addWidget(hh2)
        for lbl_txt, key, default in [
            ("BBG KV/PV monatlich (€)",           "bbg_kv",      BBG_KV_2026),
            ("BBG RV/AV bundeseinheitlich (€)",   "bbg_rv",      BBG_RV_2026),
            ("Grundfreibetrag (€/Jahr)",           "grundfreibetrag", GRUNDFREIBETRAG),
            ("Werbungskostenpauschbetrag (€/Jahr)","wkp",         WKP),
            ("BMF-Durchschnitt KV-Zusatzbeitrag (%) [PAP]","kv_avg_pap", KV_AVG_PAP),
        ]:
            bbg_l.addWidget(_lbl(lbl_txt))
            e = _edit(default); self._fields[key] = e; bbg_l.addWidget(e)

        note = QLabel("ℹ PAP nutzt den Durchschnittszusatzbeitrag (nicht den individuellen Kassensatz) → LSt kann leicht abweichen.")
        note.setWordWrap(True)
        note.setStyleSheet(f"color:{theme.C_TEXT_MUTED};font-family:{theme.FONT_FAMILY};font-size:{theme.SZ_MD}px;background:transparent;"
                           f"padding:10px;border:1px solid {theme.C_BORDER};border-radius:6px;")
        bbg_l.addWidget(note)
        bbg_l.addStretch()
        row.addWidget(bbg_card)
        bl.addLayout(row)

        save_btn = QPushButton("✔  Einstellungen speichern")
        save_btn.setStyleSheet(theme.css_button_primary())
        save_btn.clicked.connect(self._save)
        bl.addWidget(save_btn)
        bl.addStretch()
        root.addWidget(body)

    def _save(self):
        """Persist to sv_calculator module-level overrides at runtime."""
        import pdf_editor.core.sv_calculator as sv_mod
        try:
            sv_mod.BBG_KV_2026        = float(self._fields["bbg_kv"].text())
            sv_mod.BBG_RV_2026        = float(self._fields["bbg_rv"].text())
            sv_mod.KV_BASIS           = float(self._fields["kv_basis"].text())
            sv_mod.PV_WEST            = float(self._fields["pv_west"].text())
            sv_mod.PV_SACHSEN_AN      = float(self._fields["pv_sach_an"].text())
            sv_mod.PV_SACHSEN_AG      = float(self._fields["pv_sach_ag"].text())
            sv_mod.RV_SATZ            = float(self._fields["rv_satz"].text())
            sv_mod.AV_SATZ            = float(self._fields["av_satz"].text())
            sv_mod.PV_KINDERLOS       = float(self._fields["pv_kinderlos"].text())
            sv_mod.KV_AVG_PAP         = float(self._fields["kv_avg_pap"].text())
            sv_mod.GRUNDFREIBETRAG    = float(self._fields["grundfreibetrag"].text())
            sv_mod.WKP                = float(self._fields["wkp"].text())
            from PyQt5.QtWidgets import QMessageBox
            QMessageBox.information(self, "Gespeichert",
                                    "Einstellungen wurden übernommen.\n"
                                    "(Gelten für alle neuen Berechnungen in dieser Sitzung.)")
        except ValueError as e:
            from PyQt5.QtWidgets import QMessageBox
            QMessageBox.warning(self, "Fehler", f"Ungültiger Wert: {e}")

    def get_values(self) -> dict:
        result = {}
        for k, e in self._fields.items():
            try: result[k] = float(e.text())
            except: pass
        return result
