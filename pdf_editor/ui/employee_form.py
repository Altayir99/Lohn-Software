"""
employee_form.py
================
Simplified Mitarbeiter form — only the ~12 essential inputs.
Advanced/technical fields are hidden under a collapsible "Erweitert" section.
"""

from __future__ import annotations

from PyQt5.QtCore    import Qt
from PyQt5.QtWidgets import (
    QComboBox, QDialog, QDialogButtonBox, QFrame,
    QGridLayout, QHBoxLayout, QLabel, QLineEdit,
    QMessageBox, QPushButton, QScrollArea,
    QSizePolicy, QVBoxLayout, QWidget,
)

from pdf_editor.core.employee_store import (
    DEFAULT_STORE_DIR, save_employee, load_employee,
)
from pdf_editor.core.sv_calculator import BBG_KV_2025, BBG_RV_2025
from pdf_editor.ui import theme

# ── Style constants (derived from theme) ─────────────────────────────────────
_BG      = theme.C_BG_APP
_CARD    = theme.C_BG_CARD
_EDIT    = (
    f"QLineEdit, QComboBox {{ background:{theme.C_BG_INPUT}; color:{theme.C_TEXT_MAIN}; "
    f"border:1px solid {theme.C_BORDER}; border-radius:6px; "
    f"padding:8px 10px; font-family:{theme.FONT_FAMILY}; font-size:{theme.SZ_MD}px; }}"
    f"QLineEdit:focus, QComboBox:focus {{ border-color:{theme.C_ACCENT}; }}"
    f"QComboBox::drop-down {{ border:none; width:24px; }}"
    f"QComboBox QAbstractItemView {{ background:{theme.C_BG_INPUT}; color:{theme.C_TEXT_MAIN}; "
    f"selection-background-color:{theme.C_ACCENT}; selection-color:#ffffff; border:1px solid {theme.C_BORDER}; }}"
)
_LBL  = f"color:{theme.C_TEXT_MUTED}; font-family:{theme.FONT_FAMILY}; font-size:{theme.SZ_SM}px; font-weight:600;"
_SEC  = (f"color:{theme.C_ACCENT}; font-family:{theme.FONT_FAMILY}; font-size:{theme.SZ_SM}px; "
         f"font-weight:800; letter-spacing:2px; padding:12px 0 4px;")
_HINT = f"color:{theme.C_TEXT_MUTED}; font-family:{theme.FONT_FAMILY}; font-size:{theme.SZ_SM}px; padding:0 2px;"


def _label(text: str) -> QLabel:
    lbl = QLabel(text)
    lbl.setStyleSheet(_LBL)
    return lbl


def _hint(text: str) -> QLabel:
    lbl = QLabel(text)
    lbl.setStyleSheet(_HINT)
    return lbl


def _section(text: str) -> QLabel:
    lbl = QLabel(text)
    lbl.setStyleSheet(_SEC)
    return lbl


class EmployeeForm(QDialog):
    """
    Simplified Mitarbeiter form.

    Parameters
    ----------
    parent    : parent widget
    store_dir : path to mitarbeiter/ directory
    pers_nr   : if given, loads existing record for editing
    """

    def __init__(self, parent=None,
                 store_dir: str = DEFAULT_STORE_DIR,
                 pers_nr: str | None = None):
        super().__init__(parent)
        self._store_dir = store_dir
        self._editing   = pers_nr
        self._edits: dict[str, QLineEdit | QComboBox] = {}

        self.setWindowTitle("Mitarbeiter bearbeiten" if pers_nr else "Neuer Mitarbeiter")
        self.setMinimumWidth(580)
        self.setMaximumWidth(660)
        self.setStyleSheet(
            f"QDialog {{ background:{theme.C_BG_APP}; color:{theme.C_TEXT_MAIN}; }}"
            f"QPushButton {{ background:{theme.C_BG_INPUT}; color:{theme.C_TEXT_MAIN}; "
            f"border:1px solid {theme.C_BORDER}; border-radius:6px; "
            f"padding:9px 22px; font-family:{theme.FONT_FAMILY}; font-size:{theme.SZ_MD}px; }}"
            f"QPushButton:hover {{ background:{theme.C_BG_HOVER}; }}"
            f"QLabel {{ background:transparent; }}"
        )

        root = QVBoxLayout(self)
        root.setContentsMargins(20, 20, 20, 20)
        root.setSpacing(0)

        # ── Scroll area ────────────────────────────────────────────────────
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setStyleSheet(
            f"QScrollArea {{ background:{theme.C_BG_APP}; border:none; }}"
            f"QScrollBar:vertical {{ background:{theme.C_BG_APP}; width:8px; border-radius:4px; }}"
            f"QScrollBar::handle:vertical {{ background:#9CA3AF; border-radius:4px; min-height:20px; }}"
            f"QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height:0; }}"
        )
        body = QWidget()
        body.setStyleSheet(f"background:{theme.C_BG_APP};")
        bl = QVBoxLayout(body)
        bl.setContentsMargins(0, 0, 12, 0)
        bl.setSpacing(4)

        # ══ SECTION: Arbeitnehmer (essentials) ═══════════════════════════
        bl.addWidget(_section("ARBEITNEHMER"))
        g2 = QGridLayout()
        g2.setSpacing(8)
        g2.setColumnStretch(0, 1)
        g2.setColumnStretch(1, 1)
        self._add_field(g2, 0, 0, "Vorname",  "vorname",  "Max")
        self._add_field(g2, 0, 1, "Nachname", "nachname", "Mustermann")
        pers_edit = self._add_field(g2, 1, 0, "Pers.-Nr.","pers_nr",  "00237")
        pers_edit.editingFinished.connect(self._format_pers_nr)
        self._add_field(g2, 1, 1, "Eintritt", "eintritt", "TT.MM.JJJJ")
        bl.addLayout(g2)

        # ══ SECTION: Arbeitgeber (essentials) ════════════════════════════
        bl.addWidget(_section("ARBEITGEBER"))
        g3 = QGridLayout()
        g3.setSpacing(8)
        g3.setColumnStretch(0, 1)
        self._add_field(g3, 0, 0, "Firmenname", "arbeitgeber_name", "Mustermann GmbH")
        bl.addLayout(g3)

        # ══ SECTION: Vertrag ══════════════════════════════════════════════
        bl.addWidget(_section("VERTRAG"))
        gv = QGridLayout()
        gv.setSpacing(8)
        gv.setColumnStretch(0, 1)
        gv.setColumnStretch(1, 1)
        gv.setColumnStretch(2, 1)

        gv.addWidget(_label("Vertragsart"), 0, 0)
        vart = QComboBox()
        vart.addItems(["Vollzeit", "Teilzeit", "Minijob", "Stundenlohn"])
        vart.setStyleSheet(_EDIT)
        vart.currentIndexChanged.connect(self._on_vertragsart_changed)
        gv.addWidget(vart, 1, 0)
        self._edits["vertragsart"] = vart

        self._add_field(gv, 0, 1, "Wochenstunden", "wochenstunden", "40")
        self._add_field(gv, 0, 2, "Urlaubstage/Jahr", "urlaubstage", "28")
        bl.addLayout(gv)

        # ══ ERWEITERN button ══════════════════════════════════════════════
        bl.addSpacing(10)
        self._adv_btn = QPushButton("▸  Erweitern  —  Steuer · SV · Adresse · Bank")
        self._adv_btn.setStyleSheet(
            f"QPushButton {{ background:{theme.C_BG_CARD}; color:{theme.C_ACCENT}; "
            f"border:1px solid {theme.C_BORDER}; border-radius:6px; text-align:left; "
            f"font-size:{theme.SZ_MD}px; font-family:{theme.FONT_FAMILY}; font-weight:bold; padding:9px 14px; }}"
            f"QPushButton:hover {{ background:{theme.C_BG_HOVER}; }}"
        )
        self._adv_btn.clicked.connect(self._toggle_advanced)
        bl.addWidget(self._adv_btn)

        self._adv_widget = self._build_advanced()
        # Auto-expand when editing an existing record
        _auto_expand = bool(pers_nr)
        self._adv_widget.setVisible(_auto_expand)
        if _auto_expand:
            self._adv_btn.setText("▾  Erweitern  —  Steuer · SV · Adresse · Bank")
        bl.addWidget(self._adv_widget)

        bl.addStretch()
        scroll.setWidget(body)
        root.addWidget(scroll)

        # ── Dialog buttons ─────────────────────────────────────────────────
        btns = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        btns.button(QDialogButtonBox.Save).setText("✔  Speichern")
        btns.button(QDialogButtonBox.Save).setStyleSheet(
            f"QPushButton {{ background:{theme.C_GREEN}; color:#ffffff; "
            f"border:none; border-radius:6px; padding:9px 22px; "
            f"font-family:{theme.FONT_FAMILY}; font-size:{theme.SZ_MD}px; font-weight:600; }}"
            f"QPushButton:hover {{ background:#047857; }}"
        )
        btns.button(QDialogButtonBox.Cancel).setText("Abbrechen")
        btns.accepted.connect(self._on_save)
        btns.rejected.connect(self.reject)
        root.addSpacing(12)
        root.addWidget(btns)

        # Load existing record
        if pers_nr:
            self._populate(load_employee(pers_nr, store_dir) or {})

    # ── Field builder ─────────────────────────────────────────────────────────

    def _add_field(self, grid, row: int, col: int,
                   label: str, key: str, placeholder: str = "") -> QLineEdit:
        grid.addWidget(_label(label), row * 2, col)
        edit = QLineEdit()
        edit.setPlaceholderText(placeholder)
        edit.setStyleSheet(_EDIT)
        grid.addWidget(edit, row * 2 + 1, col)
        self._edits[key] = edit
        return edit

    def _format_pers_nr(self):
        """Auto-pad Pers.-Nr. to 5 digits: '237' → '00237'."""
        w = self._edits.get("pers_nr")
        if not w:
            return
        raw = w.text().strip()
        # Extract digits only
        digits = ''.join(c for c in raw if c.isdigit())
        if digits:
            w.setText(digits.zfill(5))

    # ── Advanced section ──────────────────────────────────────────────────────

    def _build_advanced(self) -> QWidget:
        w  = QWidget()
        w.setStyleSheet(f"background:{theme.C_BG_APP};")
        bl = QVBoxLayout(w)
        bl.setContentsMargins(0, 4, 0, 0)
        bl.setSpacing(4)

        # ── Steuer ───────────────────────────────────────────────────────
        bl.addWidget(_section("STEUER (ELSTAM)"))
        gs = QGridLayout()
        gs.setSpacing(8)
        gs.setColumnStretch(0, 1)
        gs.setColumnStretch(1, 1)
        gs.addWidget(_label("Steuerklasse"), 0, 0)
        stk = QComboBox()
        stk.addItems(["1", "2", "3", "4", "5", "6"])
        stk.setStyleSheet(_EDIT)
        gs.addWidget(stk, 1, 0)
        self._edits["st_kl"] = stk
        self._add_field(gs, 0, 1, "Kinderfreibeträge", "kinder_fb", "0,0")
        gs.addWidget(_label("Kirchensteuer"), 2, 0)
        kfk = QComboBox()
        kfk.addItems([
            "Keine (/)", "Evangelisch (ev)", "Römisch-Katholisch (rk)",
            "Jüdisch (jd)", "Altkatholisch (ak)",
        ])
        kfk.setStyleSheet(_EDIT)
        gs.addWidget(kfk, 3, 0)
        self._edits["konfession_combo"] = kfk
        bl.addLayout(gs)

        # ── Sozialversicherung ───────────────────────────────────────────
        bl.addWidget(_section("SOZIALVERSICHERUNG"))
        gsv = QGridLayout()
        gsv.setSpacing(8)
        gsv.setColumnStretch(0, 1)
        gsv.setColumnStretch(1, 1)
        self._add_field(gsv, 0, 0, "Krankenkasse", "krankenkasse", "AOK Nordost")
        self._add_field(gsv, 0, 1, "KV-Zusatzbeitrag AN+AG gesamt (%)", "z_pct", "3,50")
        bl.addWidget(_hint("Für SV-Abzug. LSt-PAP nutzt Durchschnitt 2,9 %."))
        gsv.addWidget(_label("Pflegeversicherung"), 2, 0)
        pv_cb = QComboBox()
        pv_cb.addItems([
            "Mit Kindern (unter 23) – KZ 1",
            "Kinderlos (ab 23) – KZ 0",
            "2 Kinder – KZ 2",
            "3 Kinder – KZ 3",
            "4 Kinder – KZ 4",
            "5+ Kinder – KZ 5",
        ])
        pv_cb.setStyleSheet(_EDIT)
        gsv.addWidget(pv_cb, 3, 0)
        self._edits["pv_combo"] = pv_cb
        bl.addLayout(gsv)

        # ── Weitere Adress- & Persönliche Daten ──────────────────────────
        bl.addWidget(_section("ADRESSE & WEITERE DATEN"))
        g = QGridLayout()
        g.setSpacing(8)
        g.setColumnStretch(0, 1)
        g.setColumnStretch(1, 1)
        self._add_field(g, 0, 0, "Straße & Nr.",      "strasse_hausnummer", "Musterstraße 1")
        self._add_field(g, 0, 1, "PLZ / Ort",         "plz_ort",            "10115 Berlin")
        self._add_field(g, 1, 0, "Anrede",             "anrede",             "Herrn / Frau")
        self._add_field(g, 1, 1, "Geburtsdatum",       "geburtsdatum",       "TT.MM.JJJJ")
        self._add_field(g, 2, 0, "Steuer-ID",          "steuer_id",          "12 345 678 901")
        self._add_field(g, 2, 1, "SV-Nummer",          "versicherungs_nr",   "01 010185 M 001")
        self._add_field(g, 3, 0, "Austritt",           "austritt",           "")
        self._add_field(g, 3, 1, "Faktor",             "faktor",             "")
        self._add_field(g, 4, 0, "Freibetrag jährl. €","freibetrag_jaehrl", "0,00")
        self._add_field(g, 4, 1, "Freibetrag mtl. €",  "freibetrag_mtl",     "0,00")
        self._add_field(g, 5, 0, "Steuertage (St-Tg)", "st_tg",             "30")
        bl.addLayout(g)

        # ── BBG & KK-Satz ────────────────────────────────────────────────
        bl.addWidget(_section("BBG & KK-SATZ (2025)"))
        g2 = QGridLayout()
        g2.setSpacing(8)
        g2.setColumnStretch(0, 1)
        g2.setColumnStretch(1, 1)
        self._add_field(g2, 0, 0, "KK-Satz gesamt % (KV)", "kk_pct", "14,60")
        self._add_field(g2, 0, 1, "BBG KV/PV (€/mtl)",     "bbg_kv", f"{BBG_KV_2025:.2f}")
        self._add_field(g2, 1, 0, "BBG RV/AV (€/mtl)",     "bbg_rv", f"{BBG_RV_2025:.2f}")
        bl.addLayout(g2)
        bl.addWidget(_hint("Diese Werte werden jährlich angepasst (Stand 2025)."))

        # ── Bank ─────────────────────────────────────────────────────────
        bl.addWidget(_section("BANK"))
        g3 = QGridLayout()
        g3.setSpacing(8)
        g3.setColumnStretch(0, 1)
        g3.setColumnStretch(1, 1)
        self._add_field(g3, 0, 0, "Bankname", "bank_name", "z.B. Berliner Sparkasse")
        self._add_field(g3, 1, 0, "IBAN", "iban", "DE00 0000 0000 0000 0000 00")
        self._add_field(g3, 1, 1, "BIC",  "bic",  "BELADEBEXXX")
        bl.addLayout(g3)

        # ── SV-Kennzeichen ───────────────────────────────────────────────
        bl.addWidget(_section("SV-KENNZEICHEN"))
        g4 = QGridLayout()
        g4.setSpacing(8)
        for i, (lbl, key, ph) in enumerate([
            ("P", "p", "1"), ("G", "g", "0"), ("S", "s", "1"), ("UM", "um", "2"),
            ("MFB", "mfb", "Nein"), ("ÜB", "ueb", "1"), ("B", "b", "1"),
            ("G(SV)", "g_sv", "1"), ("R", "r", "1"), ("S(SV)", "s_sv", "1"),
            ("SV-Tage", "sv_tg", "30"),
        ]):
            col = i % 4
            row = (i // 4) * 2
            g4.addWidget(_label(lbl), row, col)
            edit = QLineEdit(ph)
            edit.setStyleSheet(_EDIT)
            g4.addWidget(edit, row + 1, col)
            self._edits[key] = edit
        bl.addLayout(g4)

        return w

    def _toggle_advanced(self):
        vis = self._adv_widget.isVisible()
        self._adv_widget.setVisible(not vis)
        self._adv_btn.setText(
            "▾  Erweitern  —  Steuer · SV · Adresse · Bank" if not vis
            else "▸  Erweitern  —  Steuer · SV · Adresse · Bank"
        )

    # ── Vertragsart helper ─────────────────────────────────────────────────
    _VERTRAG_VALUES = ["vollzeit", "teilzeit", "minijob", "stundenlohn"]
    _VERTRAG_MAP = {"vollzeit": 0, "teilzeit": 1, "minijob": 2, "stundenlohn": 3}
    _VERTRAG_DEFAULT_HOURS = {"vollzeit": "40", "teilzeit": "20", "minijob": "10", "stundenlohn": ""}

    def _on_vertragsart_changed(self, idx: int):
        """Auto-fill Wochenstunden when contract type changes."""
        vart = self._VERTRAG_VALUES[idx] if idx < len(self._VERTRAG_VALUES) else "vollzeit"
        default_h = self._VERTRAG_DEFAULT_HOURS.get(vart, "40")
        wh_edit = self._edits.get("wochenstunden")
        if wh_edit and isinstance(wh_edit, QLineEdit):
            # Only auto-fill if currently empty or matches a previous default
            current = wh_edit.text().strip()
            if not current or current in ("40", "20", "10", ""):
                wh_edit.setText(default_h)

    # ── Konfession combo helper ───────────────────────────────────────────────
    _KONF_MAP = {
        "/":  0, "ev": 1, "rk": 2, "jd": 3, "ak": 4,
    }
    _KONF_VALUES = ["/", "ev", "rk", "jd", "ak"]

    _PV_MAP = {0: 1, 1: 0, 2: 2, 3: 3, 4: 4, 5: 5}   # KZ → combo index
    _PV_KZ  = [1, 0, 2, 3, 4, 5]                       # combo index → KZ

    # ── Populate ──────────────────────────────────────────────────────────────

    def _populate(self, emp: dict):
        # Split vorname_nachname
        full = emp.get("vorname_nachname", "")
        parts = full.rsplit(" ", 1)
        self._edits["vorname"].setText(parts[0] if len(parts) > 1 else full)
        self._edits["nachname"].setText(parts[1] if len(parts) > 1 else "")

        simple_fields = [
            "pers_nr", "geburtsdatum", "steuer_id", "versicherungs_nr",
            "strasse_hausnummer", "plz_ort", "eintritt", "anrede",
            "arbeitgeber_name", "z_pct",
            "austritt", "faktor", "freibetrag_jaehrl", "freibetrag_mtl",
            "st_tg", "kk_pct", "bbg_kv", "bbg_rv",
            "iban", "bic", "bank_name", "p", "g", "s", "um", "mfb", "ueb",
            "b", "g_sv", "r", "s_sv", "sv_tg", "krankenkasse",
            "wochenstunden", "urlaubstage",
        ]
        for key in simple_fields:
            if key in self._edits and isinstance(self._edits[key], QLineEdit):
                self._edits[key].setText(str(emp.get(key, "")))

        # Combos
        st_kl = str(emp.get("st_kl", "1"))
        idx = ["1","2","3","4","5","6"].index(st_kl) if st_kl in ["1","2","3","4","5","6"] else 0
        self._edits["st_kl"].setCurrentIndex(idx)

        konf = emp.get("konfession", "/")
        self._edits["konfession_combo"].setCurrentIndex(self._KONF_MAP.get(konf, 0))

        pv_kz = int(emp.get("pv_kinder_kz", "1") or 1)
        self._edits["pv_combo"].setCurrentIndex(self._PV_MAP.get(pv_kz, 1))

        # Vertragsart combo
        vart = emp.get("vertragsart", "vollzeit")
        self._edits["vertragsart"].setCurrentIndex(self._VERTRAG_MAP.get(vart, 0))

    # ── Collect ───────────────────────────────────────────────────────────────

    def _collect(self) -> dict:
        data: dict = {}

        # Combine vorname + nachname
        vorname  = self._edits["vorname"].text().strip()
        nachname = self._edits["nachname"].text().strip()
        data["vorname_nachname"] = f"{vorname} {nachname}".strip()

        for key, widget in self._edits.items():
            if key in ("vorname", "nachname",
                       "konfession_combo", "pv_combo", "st_kl", "vertragsart"):
                continue
            if isinstance(widget, QLineEdit):
                data[key] = widget.text().strip()

        # Enforce 5-digit zero-padded Pers.-Nr.
        if "pers_nr" in data:
            digits = ''.join(c for c in data["pers_nr"] if c.isdigit())
            if digits:
                data["pers_nr"] = digits.zfill(5)

        # Combos
        st_kl_idx = self._edits["st_kl"].currentIndex()
        data["st_kl"] = str(st_kl_idx + 1)

        data["konfession"] = self._KONF_VALUES[
            self._edits["konfession_combo"].currentIndex()]

        data["pv_kinder_kz"] = str(
            self._PV_KZ[self._edits["pv_combo"].currentIndex()])

        # Vertragsart
        data["vertragsart"] = self._VERTRAG_VALUES[
            self._edits["vertragsart"].currentIndex()]

        # Defaults for KK if not in advanced
        data.setdefault("kk_pct",  "14,60")
        data.setdefault("bbg_kv",  str(BBG_KV_2025))
        data.setdefault("bbg_rv",  str(BBG_RV_2025))
        data.setdefault("wochenstunden", "40")
        data.setdefault("urlaubstage", "28")

        return data

    # ── Save ──────────────────────────────────────────────────────────────────

    # Validation error styling
    _ERR_EDIT = (
        f"QLineEdit {{ background:#FEF2F2; color:{theme.C_TEXT_MAIN}; "
        f"border:1px solid {theme.C_RED}; border-radius:6px; "
        f"padding:8px 10px; font-family:{theme.FONT_FAMILY}; font-size:{theme.SZ_MD}px; }}"
    )
    _ERR_LBL = (
        f"color:{theme.C_RED}; font-family:{theme.FONT_FAMILY}; "
        f"font-size:{theme.SZ_SM}px; padding:2px 0 0 4px;"
    )

    def _set_field_error(self, key: str, msg: str):
        """Highlight a field as invalid and show an error message."""
        w = self._edits.get(key)
        if w and isinstance(w, QLineEdit):
            w.setStyleSheet(self._ERR_EDIT)
        # Store error label if we haven't created one yet
        if not hasattr(self, '_err_labels'):
            self._err_labels: dict[str, QLabel] = {}
        if key not in self._err_labels:
            err = QLabel(msg)
            err.setStyleSheet(self._ERR_LBL)
            # Insert after the field widget
            if w:
                parent_layout = w.parent().layout() if w.parent() else None
                if parent_layout:
                    idx = parent_layout.indexOf(w)
                    if idx >= 0:
                        parent_layout.insertWidget(idx + 1, err)
                    else:
                        parent_layout.addWidget(err)
            self._err_labels[key] = err
        else:
            self._err_labels[key].setText(msg)
            self._err_labels[key].setVisible(True)

    def _clear_all_errors(self):
        """Reset all field styles and hide error labels."""
        for key, w in self._edits.items():
            if isinstance(w, QLineEdit):
                w.setStyleSheet(_EDIT)
        if hasattr(self, '_err_labels'):
            for lbl in self._err_labels.values():
                lbl.setVisible(False)

    def _validate(self) -> list[tuple[str, str]]:
        """
        Validate fields and return list of (field_key, error_message).
        Validation is SOFT — optional fields are only checked if non-empty.
        """
        import re
        errors = []
        data = self._collect()

        # Required fields
        if not data.get("pers_nr", "").strip():
            errors.append(("pers_nr", "Pflichtfeld — Pers.-Nr. eingeben."))
        if not data.get("vorname_nachname", "").strip():
            errors.append(("vorname", "Pflichtfeld — Vor- und Nachname eingeben."))

        # Steuer-ID: 11 digits (if filled)
        sid = data.get("steuer_id", "").replace(" ", "")
        if sid and (not sid.isdigit() or len(sid) != 11):
            errors.append(("steuer_id", "Steuer-ID muss genau 11 Ziffern haben."))

        # SV-Nummer: 12 alphanumeric chars (if filled)
        svnr = data.get("versicherungs_nr", "").replace(" ", "")
        if svnr and len(svnr) != 12:
            errors.append(("versicherungs_nr", "SV-Nummer muss 12 Zeichen haben (z.B. 25220683B013)."))

        # IBAN: starts with DE, 22 chars total (if filled)
        iban = data.get("iban", "").replace(" ", "")
        if iban:
            if not iban.upper().startswith("DE"):
                errors.append(("iban", "IBAN muss mit DE beginnen."))
            elif len(iban) != 22:
                errors.append(("iban", "Deutsche IBAN muss 22 Zeichen haben."))

        # Date fields: TT.MM.JJJJ format
        date_pat = re.compile(r'^\d{2}\.\d{2}\.\d{4}$')
        for key, label in [("geburtsdatum", "Geburtsdatum"), ("eintritt", "Eintritt"), ("austritt", "Austritt")]:
            val = data.get(key, "").strip()
            if val and not date_pat.match(val):
                errors.append((key, f"{label} — Format TT.MM.JJJJ erwartet."))

        # Integer range: st_tg and sv_tg (1–31)
        for key, label in [("st_tg", "Steuertage"), ("sv_tg", "SV-Tage")]:
            val = data.get(key, "").strip()
            if val:
                try:
                    n = int(val)
                    if n < 0 or n > 31:
                        errors.append((key, f"{label} muss 0–31 sein."))
                except ValueError:
                    errors.append((key, f"{label} muss eine Ganzzahl sein."))

        return errors

    def _on_save(self):
        self._clear_all_errors()
        errors = self._validate()

        if errors:
            for key, msg in errors:
                self._set_field_error(key, msg)
            # Show summary
            QMessageBox.warning(
                self, "Validierungsfehler",
                f"{len(errors)} Feld(er) mit Fehlern.\n"
                "Bitte die rot markierten Felder korrigieren.")
            return

        data = self._collect()

        # Preserve abrechnungen history when editing
        if self._editing:
            existing = load_employee(self._editing, self._store_dir)
            if existing:
                data["abrechnungen"] = existing.get("abrechnungen", {})

        save_employee(data, self._store_dir)
        self.accept()

    def get_pers_nr(self) -> str:
        w = self._edits.get("pers_nr")
        return w.text().strip() if isinstance(w, QLineEdit) else ""
