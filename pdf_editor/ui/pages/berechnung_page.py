"""berechnung_page.py — PAP 2026 full calculator page."""
from __future__ import annotations
from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtWidgets import (
    QComboBox, QFrame, QGridLayout, QHBoxLayout, QLabel,
    QLineEdit, QPushButton, QScrollArea, QSizePolicy,
    QVBoxLayout, QWidget,
)
from pdf_editor.core.sv_calculator import calculate_full, BBG_KV_2025, BBG_RV_2025
from pdf_editor.core.number_utils import fmt_de
from pdf_editor.ui import theme

def _lbl(t, c=None, sz=None, bold=False):
    l = QLabel(t)
    w = "bold" if bold else "500"
    col = c or theme.C_TEXT_MUTED
    size = sz or theme.SZ_MD
    l.setStyleSheet(f"color:{col};font-family:{theme.FONT_FAMILY};font-size:{size}px;font-weight:{w};background:transparent;")
    return l

def _parse_num(text: str) -> float | None:
    """Parse German or English number string. Returns None if not a valid number."""
    t = text.strip()
    if not t:
        return None
    # German: 1.234,56 → remove dots, replace comma with dot
    if "," in t:
        t = t.replace(".", "").replace(",", ".")
    # English: 1,234.56 → remove commas
    elif "," not in t and "." in t:
        pass  # already dot-decimal
    try:
        return float(t)
    except ValueError:
        return None


class GermanNumEdit(QLineEdit):
    """QLineEdit that auto-formats numbers in German locale (1.234,56) on focus-out."""
    _CSS = theme.css_input()

    def __init__(self, placeholder="", value="", decimals=2, parent=None):
        super().__init__(parent)
        self._decimals = decimals
        self.setPlaceholderText(placeholder)
        self.setStyleSheet(self._CSS)
        if value:
            self.setText(value)

    def focusOutEvent(self, event):
        """Reformat the value to German locale when user leaves the field."""
        v = _parse_num(self.text())
        if v is not None:
            # Format: thousand separator = ".", decimal separator = ","
            formatted = f"{v:,.{self._decimals}f}".replace(",", "X").replace(".", ",").replace("X", ".")
            self.setText(formatted)
        super().focusOutEvent(event)

    def value(self) -> float:
        """Return the numeric value (0.0 if empty or invalid)."""
        v = _parse_num(self.text())
        return v if v is not None else 0.0


def _edit(ph="", val="", numeric=False):
    if numeric:
        return GermanNumEdit(placeholder=ph, value=val)
    e = QLineEdit(val)
    e.setPlaceholderText(ph)
    e.setStyleSheet(theme.css_input())
    return e

def _combo(items):
    c = QComboBox()
    c.addItems(items)
    c.setStyleSheet(f"QComboBox{{background:{theme.C_BG_INPUT};color:{theme.C_TEXT_MAIN};border:1px solid {theme.C_BORDER};"
                    f"border-radius:6px;padding:8px 12px;font-family:{theme.FONT_FAMILY};font-size:{theme.SZ_MD}px;}}"
                    f"QComboBox::drop-down{{border:none;width:24px;}}"
                    f"QComboBox QAbstractItemView{{background:{theme.C_BG_INPUT};color:{theme.C_TEXT_MAIN};"
                    f"selection-background-color:{theme.C_ACCENT};selection-color:#ffffff;border:1px solid {theme.C_BORDER};}}")
    return c

def _card(title):
    f = QFrame()
    f.setStyleSheet(theme.css_card())
    v = QVBoxLayout(f)
    v.setContentsMargins(20,16,20,20)
    v.setSpacing(12)
    h = QLabel(title)
    h.setStyleSheet(f"color:{theme.C_ACCENT};font-family:{theme.FONT_FAMILY};font-size:{theme.SZ_MD}px;font-weight:bold;"
                    f"letter-spacing:2px;padding-bottom:10px;border-bottom:1px solid {theme.C_BORDER};"
                    f"background:transparent;")
    v.addWidget(h)
    return f, v

def _field_row(layout, label, widget):
    layout.addWidget(_lbl(label))
    layout.addWidget(widget)

class BerechnungPage(QWidget):
    # Emitted when user clicks "→ Abrechnung PDF erstellen"
    # Payload: (result, monat_idx 1-12, jahr int, monat_values dict)
    abrechnung_ready = pyqtSignal(object, int, int, dict)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setStyleSheet(f"background:{theme.C_BG_APP};")
        self._fields = {}
        self._result_labels = {}
        self._last_result = None   # most recent LohnResult
        root = QVBoxLayout(self)
        root.setContentsMargins(0,0,0,0)
        root.setSpacing(0)

        # Header with Monat + Jahr always visible
        hdr = QWidget()
        hdr.setStyleSheet(f"background:{theme.C_BG_CARD};border-bottom:1px solid {theme.C_BORDER};")
        hl = QHBoxLayout(hdr)
        hl.setContentsMargins(24,20,24,20)
        t = QLabel("Berechnung")
        t.setStyleSheet(theme.css_label_header())
        hl.addWidget(t)
        s = QLabel("BMF PAP 2026")
        s.setStyleSheet(theme.css_label_sub() + f"; font-size:{theme.SZ_MD}px; margin-left:12px;")
        hl.addWidget(s)
        hl.addStretch()

        # Monat + Jahr in header
        hl.addWidget(_lbl("Monat:", theme.C_TEXT_MUTED, theme.SZ_MD))
        monat_cb_hdr = _combo(["Januar","Februar","März","April","Mai","Juni",
                               "Juli","August","September","Oktober","November","Dezember"])
        monat_cb_hdr.setFixedWidth(130)
        hl.addWidget(monat_cb_hdr)
        self._fields["monat"] = monat_cb_hdr

        import datetime
        hl.addSpacing(16)
        hl.addWidget(_lbl("Jahr:", theme.C_TEXT_MUTED, theme.SZ_MD))
        cur_year = datetime.date.today().year
        jahr_cb_hdr = _combo([str(y) for y in range(cur_year - 2, cur_year + 5)])
        jahr_cb_hdr.setCurrentText(str(cur_year))
        jahr_cb_hdr.setFixedWidth(90)
        hl.addWidget(jahr_cb_hdr)
        self._fields["ag_jahr"] = jahr_cb_hdr
        hl.addSpacing(12)

        root.addWidget(hdr)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setStyleSheet(f"QScrollArea{{background:{theme.C_BG_APP};border:none;}}"
                             f"QScrollBar:vertical{{background:transparent;width:8px;}}"
                             f"QScrollBar::handle:vertical{{background:#9CA3AF;border-radius:4px;}}")
        body = QWidget()
        body.setStyleSheet(f"background:{theme.C_BG_APP};")
        bl = QVBoxLayout(body)
        bl.setContentsMargins(24,24,24,24)
        bl.setSpacing(20)

        # Row 1: Arbeitgeber + Arbeitnehmer
        r1 = QHBoxLayout()
        r1.setSpacing(12)

        ag_card, ag_l = _card("ARBEITGEBER")
        self._f("ag_firma", ag_l, "Firmenname", "")
        ag_l.addStretch()
        r1.addWidget(ag_card)

        an_card, an_l = _card("ARBEITNEHMER")
        row_name = QHBoxLayout()
        vn = _edit("Vorname"); nn = _edit("Nachname")
        row_name.addWidget(vn); row_name.addWidget(nn)
        self._fields["vorname"] = vn; self._fields["nachname"] = nn
        an_l.addWidget(_lbl("Vorname / Nachname"))
        an_l.addLayout(row_name)
        self._f("pnr",  an_l, "Personalnummer", "")
        self._f("iban", an_l, "IBAN", "")
        an_l.addStretch()
        r1.addWidget(an_card)
        bl.addLayout(r1)


        # Row 2: Steuer + SV + Bezüge
        r2 = QHBoxLayout()
        r2.setSpacing(12)

        st_card, st_l = _card("STEUER (ELSTAM)")
        self._f("stkl", st_l, "Steuerklasse", None, is_combo=True,
                items=["I (1)","II (2)","III (3)","IV (4)","V (5)","VI (6)"])
        self._f("kfb",    st_l, "Kinderfreibeträge", "0")
        self._f("jfreib", st_l, "ELStAM-Jahresfreibetrag (€/Jahr)", "0")
        self._f("kist", st_l, "Kirchensteuer", None, is_combo=True,
                items=["Keine (0%)", "9% (meiste BL)", "8% (Bayern/BW)"])
        st_l.addStretch()
        r2.addWidget(st_card)

        sv_card, sv_l = _card("SOZIALVERSICHERUNG")
        self._f("bl", sv_l, "Bundesland", None, is_combo=True,
                items=["West (ohne Sachsen)","Sachsen","Ost (ohne Sachsen)"])
        self._f("kk_name", sv_l, "Krankenkasse", "")
        self._f("kk_pct", sv_l, "KV-Basisbeitrag (%)", "14,60")
        self._f("z_pct", sv_l, "KV-Zusatzbeitrag AN+AG gesamt (%)", "")
        self._f("pv_status", sv_l, "Pflegeversicherung", None, is_combo=True,
                items=["Mit Kindern (unter 23)","Kinderlos (+0,60% AN)"])
        self._f("rv_status", sv_l, "Rentenversicherung", None, is_combo=True,
                items=["Pflichtversichert","Befreit"])
        self._f("av_status", sv_l, "Arbeitslosenvers.", None, is_combo=True,
                items=["Pflichtversichert","Befreit"])
        self._f("beschaeftigung", sv_l, "Beschäftigungsart", None, is_combo=True,
                items=["Vollzeit / Teilzeit","Minijob (≤538€)","Midijob (538-2.000€)"])
        sv_l.addStretch()
        r2.addWidget(sv_card)

        bez_card, bez_l = _card("BEZÜGE & ABZÜGE")

        # ── Brutto / Netto mode toggle ────────────────────────────────────
        bez_l.addWidget(_lbl("Berechnungsmodus"))
        self._mode_combo = _combo(["Brutto → Netto", "Netto → Brutto"])
        self._mode_combo.currentIndexChanged.connect(self._on_mode_changed)
        bez_l.addWidget(self._mode_combo)
        self._fields["calc_mode"] = self._mode_combo

        self._gehalt_label = _lbl("Gehalt (€/Monat)")
        bez_l.addWidget(self._gehalt_label)
        w = _edit("", "", numeric=True)
        bez_l.addWidget(w)
        self._fields["grundgehalt"] = w
        self._f("ueberstunden",  bez_l, "Überstunden (€)",                   "")
        self._f("sachbezug",     bez_l, "Sachbezug stpfl. (€)",             "")
        self._f("einmalzahlung", bez_l, "Einmalzahlung / Weihnachtsgeld (€)","")
        self._f("fahrgeld",      bez_l, "Fahrgeld steuerfrei (€)",          "")
        self._f("vwl_ag",        bez_l, "VWL AG-Anteil (€)",                "")
        self._f("vorschuss",     bez_l, "Vorschuss / Pfändung (€)",         "")
        self._f("vwl_an",        bez_l, "VWL AN-Eigenbetrag (€)",           "")
        bez_l.addStretch()
        r2.addWidget(bez_card)
        bl.addLayout(r2)

        # Result section (inside scroll, shown after calculation)

        self._result_widget = QWidget()
        self._result_widget.setVisible(False)
        self._result_widget.setStyleSheet(f"background:{theme.C_BG_APP};")
        rl = QVBoxLayout(self._result_widget)
        rl.setContentsMargins(0,20,0,0)
        rl.setSpacing(20)

        # Brutto / Netto header
        rh = QHBoxLayout()
        bg = QVBoxLayout(); bg.addWidget(_lbl("GESAMTBRUTTO",theme.C_TEXT_MUTED,theme.SZ_MD))
        self._result_labels["brutto"] = QLabel("–")
        self._result_labels["brutto"].setStyleSheet(
            f"color:{theme.C_TEXT_MAIN};font-family:{theme.FONT_FAMILY};font-size:{theme.SZ_XL}px;font-weight:bold;background:transparent;")
        bg.addWidget(self._result_labels["brutto"])
        rh.addLayout(bg); rh.addStretch()
        ng = QVBoxLayout(); ng.addWidget(_lbl("NETTO-AUSZAHLUNG",theme.C_TEXT_MUTED,theme.SZ_MD))
        self._result_labels["netto"] = QLabel("–")
        self._result_labels["netto"].setStyleSheet(
            f"color:{theme.C_GREEN};font-family:{theme.FONT_FAMILY};font-size:{theme.SZ_XL}px;font-weight:bold;background:transparent;")
        ng.addWidget(self._result_labels["netto"])
        rh.addLayout(ng)
        rl.addLayout(rh)

        # Breakdown table
        self._table_widget = QWidget()
        self._table_widget.setStyleSheet(theme.css_card())
        self._table_layout = QVBoxLayout(self._table_widget)
        self._table_layout.setContentsMargins(0,0,0,0)
        self._table_layout.setSpacing(0)
        rl.addWidget(self._table_widget)

        # SV cards grid
        self._sv_grid = QWidget()
        self._sv_grid.setStyleSheet(f"background:{theme.C_BG_APP};")
        self._sv_grid_layout = QHBoxLayout(self._sv_grid)
        self._sv_grid_layout.setSpacing(16)
        rl.addWidget(self._sv_grid)

        bl.addWidget(self._result_widget)
        bl.addStretch()
        scroll.setWidget(body)
        root.addWidget(scroll, stretch=1)   # input scroll takes remaining space

        # ── Fixed footer: button always visible ──────────────────────────────
        footer = QWidget()
        footer.setStyleSheet(f"background:{theme.C_BG_CARD};border-top:1px solid {theme.C_BORDER};")
        fl = QHBoxLayout(footer)
        fl.setContentsMargins(24, 16, 24, 16)

        calc_btn = QPushButton("▶  Abrechnung berechnen  →  Lohnabrechnung öffnen")
        calc_btn.setStyleSheet(theme.css_button_primary())
        calc_btn.clicked.connect(self._calculate_and_forward)
        fl.addWidget(calc_btn)
        fl.addStretch()
        root.addWidget(footer)              # always visible, outside scroll


    def _f(self, key, layout, label, default=None, is_combo=False, items=None, placeholder=None):
        if label:
            layout.addWidget(_lbl(label))
        if is_combo:
            w = _combo(items or [])
        else:
            # Detect numeric fields by key name
            _NUMERIC_KEYS = {
                "grundgehalt","ueberstunden","sachbezug","einmalzahlung",
                "fahrgeld","vwl_ag","vorschuss","vwl_an",
                "kfb","jfreib","z_pct","kk_pct",
            }
            numeric = key in _NUMERIC_KEYS
            w = _edit(placeholder or "", default or "", numeric=numeric)
        layout.addWidget(w)
        self._fields[key] = w

    def _get(self, key, default=0.0):
        w = self._fields.get(key)
        if w is None: return default
        if isinstance(w, QComboBox): return w.currentIndex()
        v = _parse_num(w.text())
        return v if v is not None else default

    def _on_mode_changed(self, idx: int):
        """Update label when Brutto↔Netto mode changes."""
        if idx == 0:  # Brutto → Netto
            self._gehalt_label.setText("Gehalt (€/Monat)")
        else:         # Netto → Brutto
            self._gehalt_label.setText("Wunsch-Netto (€/Monat)")

    def _collect_params(self) -> dict:
        """Collect all calculation parameters from the form."""
        return {
            "stkl":       int(self._get("stkl", 0)) + 1,
            "kfb":        self._get("kfb", 0.0),
            "jfreib":     self._get("jfreib", 0.0),
            "kist_satz":  [0.0, 0.09, 0.08][int(self._get("kist", 0))],
            "bundesland": ["west","sachsen","ost"][int(self._get("bl", 0))],
            "kk_pct":     self._get("kk_pct", 14.60),
            "z_pct":      self._get("z_pct", 2.20),
            "pvz":        int(self._get("pv_status", 0)) == 1,
            "rv":         int(self._get("rv_status", 0)) == 0,
            "av":         int(self._get("av_status", 0)) == 0,
            "ue":         self._get("ueberstunden", 0.0),
            "sach":       self._get("sachbezug", 0.0),
            "einmal":     self._get("einmalzahlung", 0.0),
            "fahr":       self._get("fahrgeld", 0.0),
            "vwl_ag":     self._get("vwl_ag", 0.0),
            "vor":        self._get("vorschuss", 0.0),
            "vwl_an":     self._get("vwl_an", 0.0),
            "beschaeftigung": ["vollzeit","minijob","midijob"][int(self._get("beschaeftigung", 0))],
        }

    def _run_calc(self, grundgehalt: float, params: dict):
        """Execute calculate_full with a given Grundgehalt and param dict."""
        return calculate_full(
            grundgehalt=grundgehalt, stkl=params["stkl"], kfb=params["kfb"],
            kk_pct=params["kk_pct"], z_pct=params["z_pct"],
            pv_kinderlos=params["pvz"], rv_pflicht=params["rv"], av_pflicht=params["av"],
            bundesland=params["bundesland"], kist_satz=params["kist_satz"],
            jfreib=params["jfreib"],
            ueberstunden=params["ue"], sachbezug=params["sach"],
            einmalzahlung=params["einmal"],
            fahrgeld=params["fahr"], vwl_ag=params["vwl_ag"],
            vorschuss=params["vor"], vwl_an=params["vwl_an"],
            beschaeftigung=params["beschaeftigung"],
        )

    def _calculate(self):
        is_netto_mode = self._mode_combo.currentIndex() == 1
        params = self._collect_params()
        input_val = self._get("grundgehalt", 0.0)

        if is_netto_mode and input_val > 0:
            # ── Netto → Brutto: bisection to find Grundgehalt ──────────
            target_netto = input_val
            brutto = self._find_brutto_for_netto(target_netto, params)
            r = self._run_calc(brutto, params)
            # Update the Grundgehalt field to show the found Brutto
            self._fields["grundgehalt"].blockSignals(True)
            self._fields["grundgehalt"].setText(str(round(brutto, 2)))
            self._fields["grundgehalt"].blockSignals(False)
        else:
            # ── Brutto → Netto: normal calculation ─────────────────────
            r = self._run_calc(input_val, params)

        self._last_result = r
        self._result_labels["brutto"].setText(fmt_de(r.gesamtbrutto) + " €")
        self._result_labels["netto"].setText(fmt_de(r.netto) + " €")
        self._render_table(r)
        self._render_sv_cards(r)
        self._result_widget.setVisible(True)

    def _find_brutto_for_netto(self, target_netto: float, params: dict,
                                tol: float = 0.005, max_iter: int = 120) -> float:
        """Bisection: find Grundgehalt such that calculate_full().netto ≈ target_netto."""
        # Bounds: Netto is always less than Brutto, and Brutto can't exceed ~3× Netto
        lo, hi = 0.0, target_netto * 3.5

        # Expand hi if needed (for very high tax brackets)
        r_hi = self._run_calc(hi, params)
        while r_hi.netto < target_netto and hi < 500_000:
            hi *= 2
            r_hi = self._run_calc(hi, params)

        for _ in range(max_iter):
            mid = (lo + hi) / 2.0
            r = self._run_calc(mid, params)
            diff = r.netto - target_netto
            if abs(diff) < tol:
                break
            if diff < 0:
                lo = mid
            else:
                hi = mid

        # ── Cent-level refinement ─────────────────────────────────────
        # The tax engine uses math.floor(), so rounding the bisection
        # result to 2 decimals can shift netto by several cents.
        # Sweep ± 10 cents around the converged value and pick the
        # brutto whose netto is closest to the target.
        base = round((lo + hi) / 2.0, 2)
        best_brutto = base
        best_diff   = abs(self._run_calc(base, params).netto - target_netto)

        for offset in range(-10, 11):          # -0.10 … +0.10
            candidate = round(base + offset * 0.01, 2)
            if candidate < 0:
                continue
            r = self._run_calc(candidate, params)
            d = abs(r.netto - target_netto)
            if d < best_diff:
                best_diff   = d
                best_brutto = candidate
                if d < 0.001:                  # exact hit
                    break

        return best_brutto

    def _calculate_and_forward(self):
        """Calculate and immediately emit abrechnung_ready to switch to PDF page."""
        # If in Netto→Brutto mode, switch back to Brutto mode after finding
        # the Brutto, so the forward uses the computed Brutto value
        was_netto_mode = self._mode_combo.currentIndex() == 1
        self._calculate()
        if was_netto_mode:
            # Reset mode to Brutto→Netto so the Grundgehalt field holds the real Brutto
            self._mode_combo.blockSignals(True)
            self._mode_combo.setCurrentIndex(0)
            self._mode_combo.blockSignals(False)
            self._gehalt_label.setText("Gehalt (€/Monat)")
        if self._last_result is not None:
            self._emit_abrechnung()


    def _render_table(self, r):
        # Clear
        while self._table_layout.count():
            item = self._table_layout.takeAt(0)
            if item.widget(): item.widget().deleteLater()

        def row(pos, hint, betrag, header=False, subtotal=False, total=False):
            w = QWidget()
            if total:
                w.setStyleSheet(f"background:{theme.C_BG_APP};")
            elif subtotal:
                w.setStyleSheet(f"background:{theme.C_BG_ROW};")
            elif header:
                w.setStyleSheet(f"background:{theme.C_BG_ROW};")
            else:
                w.setStyleSheet(f"background:{theme.C_BG_CARD};")
            rl = QHBoxLayout(w)
            rl.setContentsMargins(20,12,20,12)
            p_lbl = QLabel(pos)
            h_lbl = QLabel(hint)
            b_lbl = QLabel(betrag)
            b_lbl.setAlignment(Qt.AlignRight)
            c = theme.C_TEXT_MAIN if not total else theme.C_TEXT_MAIN
            sz = theme.SZ_MD if not total else theme.SZ_LG
            bld = total or subtotal
            for l, stretch in [(p_lbl,2),(h_lbl,3),(b_lbl,1)]:
                l.setStyleSheet(f"color:{c};font-family:{theme.FONT_FAMILY};font-size:{sz}px;"
                                f"font-weight:{'bold' if bld else '400'};background:transparent;")
                rl.addWidget(l, stretch)
            self._table_layout.addWidget(w)
            sep = QFrame()
            sep.setFrameShape(QFrame.HLine)
            sep.setStyleSheet(f"color:{theme.C_BORDER};")
            if not total:
                self._table_layout.addWidget(sep)

        def sh(text):
            w = QWidget(); w.setStyleSheet(f"background:{theme.C_BG_ROW};")
            l = QHBoxLayout(w); l.setContentsMargins(20,8,20,8)
            lb = QLabel(text)
            lb.setStyleSheet(f"color:{theme.C_TEXT_MUTED};font-family:{theme.FONT_FAMILY};font-size:{theme.SZ_SM}px;"
                             f"font-weight:bold;letter-spacing:2px;background:transparent;")
            l.addWidget(lb)
            self._table_layout.addWidget(w)

        sh("BEZÜGE")
        row("Gehalt", "Laufender Bezug", fmt_de(r.grundgehalt)+" €")
        if r.ueberstunden: row("Überstunden", "lfd. Bezug", fmt_de(r.ueberstunden)+" €")
        if r.sachbezug:    row("Sachbezug", "stpfl.", fmt_de(r.sachbezug)+" €")
        if r.fahrgeld:     row("Fahrgeld", "§3 Nr.13/16 EStG", fmt_de(r.fahrgeld)+" €")
        if r.vwl_ag:       row("VWL AG-Anteil", "", fmt_de(r.vwl_ag)+" €")
        if r.einmalzahlung:row("Einmalzahlung", "Fünftelregelung §39b Abs.3", fmt_de(r.einmalzahlung)+" €")
        row("Gesamtbezüge (brutto)", "", fmt_de(r.gesamtbrutto)+" €", subtotal=True)

        sh("ABZÜGE — SOZIALVERSICHERUNG (AN-Anteil)")
        row("Krankenversicherung", fmt_de(r.sv.kv_beitrag_an/r.sv.kv_sv_brutto*100 if r.sv.kv_sv_brutto else 0,decimals=2)+"% v. "+fmt_de(r.sv.kv_sv_brutto)+"€", "– "+fmt_de(r.sv.kv_beitrag_an)+" €")
        row("Pflegeversicherung",  "", "– "+fmt_de(r.sv.pv_beitrag_an)+" €")
        if r.sv.rv_beitrag_an: row("Rentenversicherung", "9,30% v. "+fmt_de(r.sv.rv_sv_brutto)+"€", "– "+fmt_de(r.sv.rv_beitrag_an)+" €")
        if r.sv.av_beitrag_an: row("Arbeitslosenversicherung","1,30% v. "+fmt_de(r.sv.av_sv_brutto)+"€","– "+fmt_de(r.sv.av_beitrag_an)+" €")
        if r.sv_einmal_an:     row("SV auf Einmalzahlung","BBG-Restbetrag","– "+fmt_de(r.sv_einmal_an)+" €")
        row("SV-Beiträge gesamt (AN)","",  "– "+fmt_de(r.sv.sv_an_gesamt)+" €", subtotal=True)

        sh("ABZÜGE — STEUERN  (BMF PAP 2026)")
        row("Lohnsteuer (laufend)", f"SK{int(self._get('stkl',0))+1} · zvE/Jahr: {fmt_de(r.pap.zve)}€", "– "+fmt_de(r.pap.lst_monat)+" €")
        if r.lst_einmal: row("LSt Einmalzahlung","Fünftelreg.","– "+fmt_de(r.lst_einmal)+" €")
        row("Solidaritätszuschlag", "Freigrenze < 18.130€/Jahr" if r.solz_gesamt==0 else "5,50% d. LSt","– "+fmt_de(r.solz_gesamt)+" €")
        if r.kist_gesamt: row("Kirchensteuer","","– "+fmt_de(r.kist_gesamt)+" €")

        if r.vorschuss or r.vwl_an:
            sh("SONSTIGE ABZÜGE")
            if r.vorschuss: row("Vorschuss/Pfändung","","– "+fmt_de(r.vorschuss)+" €")
            if r.vwl_an:    row("VWL AN-Eigenbetrag","§13 VermBG","– "+fmt_de(r.vwl_an)+" €")

        row("NETTO-AUSZAHLUNG","", fmt_de(r.netto)+" €", total=True)

    def _render_sv_cards(self, r):
        while self._sv_grid_layout.count():
            item = self._sv_grid_layout.takeAt(0)
            if item.widget(): item.widget().deleteLater()
        items = [
            ("Krankenversicherung", r.sv.kv_beitrag_an, r.sv.kv_beitrag_ag),
            ("Pflegeversicherung",  r.sv.pv_beitrag_an, r.sv.pv_beitrag_ag),
            ("Rentenversicherung",  r.sv.rv_beitrag_an, r.sv.rv_beitrag_ag),
            ("Arbeitslosenvers.",   r.sv.av_beitrag_an, r.sv.av_beitrag_ag),
        ]
        for label, an, ag in items:
            c = QFrame()
            c.setStyleSheet(theme.css_card())
            cl = QVBoxLayout(c)
            cl.setContentsMargins(16,14,16,14)
            cl.setSpacing(6)
            cl.addWidget(_lbl(label, theme.C_TEXT_MUTED, theme.SZ_MD))
            an_l = QLabel(f"AN: {fmt_de(an)} €")
            an_l.setStyleSheet(f"color:{theme.C_TEXT_MAIN};font-family:{theme.FONT_FAMILY};font-size:{theme.SZ_LG}px;font-weight:bold;background:transparent;")
            ag_l = QLabel(f"AG: {fmt_de(ag)} €")
            ag_l.setStyleSheet(f"color:{theme.C_TEXT_MUTED};font-family:{theme.FONT_FAMILY};font-size:{theme.SZ_MD}px;background:transparent;")
            tot_l = QLabel(f"Σ {fmt_de(an+ag)} €")
            tot_l.setStyleSheet(f"color:{theme.C_ACCENT};font-family:{theme.FONT_FAMILY};font-size:{theme.SZ_MD}px;font-weight:600;background:transparent;")
            cl.addWidget(an_l); cl.addWidget(ag_l); cl.addWidget(tot_l)
            self._sv_grid_layout.addWidget(c)

    def fill_from_employee(self, emp: dict):
        """Pre-fill inputs from a saved employee record and reset any previous result."""
        # ── Clear ALL input fields first (blank slate for new employees) ───────
        for w in self._fields.values():
            if isinstance(w, QLineEdit):
                w.setText("")
            elif isinstance(w, QComboBox):
                w.setCurrentIndex(0)

        # ── Reset result panel so previous employee's values don't carry over ──
        self._last_result = None
        self._result_widget.setVisible(False)
        self._result_labels["brutto"].setText("–")
        self._result_labels["netto"].setText("–")
        # Clear the breakdown table
        while self._table_layout.count():
            item = self._table_layout.takeAt(0)
            if item.widget():

                item.widget().deleteLater()
        # Clear the SV cards
        while self._sv_grid_layout.count():
            item = self._sv_grid_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()


        def sv(key, val):
            w = self._fields.get(key)
            if w and val and isinstance(w, QLineEdit):
                w.setText(str(val))

        # Numeric fields that must never be blank — default to 0
        for _zero_key in ("kfb", "jfreib"):
            w = self._fields.get(_zero_key)
            if w and isinstance(w, QLineEdit):
                w.setText("0")

        # ── Arbeitnehmer / Arbeitgeber ────────────────────────────────────────
        sv("kk_name",     emp.get("krankenkasse",""))
        sv("kk_pct",      emp.get("kk_pct","14,60").replace(",","."))
        sv("z_pct",       emp.get("z_pct","2.20").replace(",","."))
        sv("pnr",         emp.get("pers_nr",""))
        sv("iban",        emp.get("iban",""))
        sv("vorname",     emp.get("vorname_nachname","").split()[0] if emp.get("vorname_nachname") else "")
        sv("nachname",    " ".join(emp.get("vorname_nachname","").split()[1:]))
        sv("ag_firma",    emp.get("arbeitgeber_name",""))

        # ── Steuer (ELStAM) ──────────────────────────────────────────────────
        # Steuerklasse
        stk = str(emp.get("st_kl","1"))
        stk_idx = {"1":0,"2":1,"3":2,"4":3,"5":4,"6":5}.get(stk,0)
        stk_w = self._fields.get("stkl")
        if stk_w: stk_w.setCurrentIndex(stk_idx)

        # Kinderfreibeträge
        kfb_val = emp.get("kinder_fb", "0").replace(",",".")
        sv("kfb", kfb_val)

        # Jahresfreibetrag (from ELStAM)
        jfreib_val = emp.get("freibetrag_jaehrl", "0").replace(",",".")
        sv("jfreib", jfreib_val)

        # Kirchensteuer — map konfession code to KiSt combo index
        konf = emp.get("konfession", "/")
        # "/": 0 (Keine), "ev": 1 (9% meiste BL), "rk": 1 (9%), "jd": 1, "ak": 1
        # Bayern/BW = 8%, but we default to 9% — user can override
        kist_w = self._fields.get("kist")
        if kist_w:
            if konf in ("ev", "rk", "jd", "ak"):
                kist_w.setCurrentIndex(1)  # 9% (meiste BL)
            else:
                kist_w.setCurrentIndex(0)  # Keine

        # ── Sozialversicherung ────────────────────────────────────────────────
        # PV kinderlos: KZ 0 = kinderlos, KZ ≥ 1 = has children
        kz_raw = emp.get("pv_kinder_kz", "")
        try:
            kz = int(kz_raw) if kz_raw else 0
        except (ValueError, TypeError):
            kz = 0
        pv_w = self._fields.get("pv_status")
        if pv_w: pv_w.setCurrentIndex(1 if kz == 0 else 0)

        # ── Grundgehalt: fill from last stored Abrechnung (if any) ────────────
        grundgehalt_w = self._fields.get("grundgehalt")
        if grundgehalt_w:
            grundgehalt_w.setText("")   # clear for new employee
        abrechnungen = emp.get("abrechnungen", {})
        if abrechnungen and grundgehalt_w:
            # Sort by YYYY-MM key (lexicographic = chronological)
            last_key = sorted(abrechnungen.keys())[-1]
            brutto = abrechnungen[last_key].get("abrechnungs_brutto", 0)
            if brutto:
                grundgehalt_w.setText(str(brutto))
            # Auto-advance Monat/Jahr to the NEXT month after the last saved one
            try:
                yr, mo = last_key.split("-")
                next_mo = int(mo) % 12  # 0-based index for next month
                monat_cb = self._fields.get("monat")
                jahr_cb = self._fields.get("ag_jahr")
                if monat_cb:
                    monat_cb.setCurrentIndex(next_mo)
                if jahr_cb and int(mo) == 12:
                    next_yr = str(int(yr) + 1)
                    idx = jahr_cb.findText(next_yr)
                    if idx >= 0:
                        jahr_cb.setCurrentIndex(idx)
                elif jahr_cb:
                    idx = jahr_cb.findText(yr)
                    if idx >= 0:
                        jahr_cb.setCurrentIndex(idx)
            except (ValueError, IndexError):
                pass

    # ── Month/year helpers ──────────────────────────────────────────────────

    def _get_monat_idx(self) -> int:
        """Return 1-based month index from the Monat combo."""
        return self._fields["monat"].currentIndex() + 1   # 0-based → 1-based

    def _get_jahr(self) -> int:
        cb = self._fields.get("ag_jahr")
        if cb:
            try: return int(cb.currentText())
            except: pass
        return 2026

    # ── Emit abrechnung_ready ───────────────────────────────────────────────

    def _emit_abrechnung(self):
        r = self._last_result
        if r is None:
            return
        monat_values = {
            "abrechnungs_brutto": r.gesamtbrutto,
            "lohnsteuer":         r.pap.lst_monat + (r.lst_einmal or 0.0),
            "solz":               r.solz_gesamt,
            "kv_beitrag":         r.sv.kv_beitrag_an,
            "rv_beitrag":         r.sv.rv_beitrag_an,
            "av_beitrag":         r.sv.av_beitrag_an,
            "pv_beitrag":         r.sv.pv_beitrag_an,
            "abrechnungs_netto":  r.netto,
            # AG contributions (for SV-AG-Anteil kum.)
            "kv_beitrag_ag":      r.sv.kv_beitrag_ag,
            "rv_beitrag_ag":      r.sv.rv_beitrag_ag,
            "av_beitrag_ag":      r.sv.av_beitrag_ag,
            "pv_beitrag_ag":      r.sv.pv_beitrag_ag,
        }
        self.abrechnung_ready.emit(r, self._get_monat_idx(), self._get_jahr(), monat_values)
