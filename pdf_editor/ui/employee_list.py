"""
employee_list.py
================
Employee list panel — a QWidget (not a dialog) that lives in the left sidebar.

Shows all saved Mitarbeiter as compact clickable rows.
Signals: on_new_abrechnung(pers_nr) when a row is double-clicked or
         "Abrechnung erstellen" is pressed.
"""

from __future__ import annotations

from PyQt5.QtCore    import Qt, pyqtSignal
from PyQt5.QtWidgets import (
    QFrame, QHBoxLayout, QLabel, QPushButton,
    QScrollArea, QSizePolicy, QVBoxLayout, QWidget,
)

from pdf_editor.core.employee_store import (
    DEFAULT_STORE_DIR, delete_employee, list_employees,
)
from pdf_editor.ui import theme


class _EmployeeRow(QFrame):
    """A single clickable employee row."""

    clicked       = pyqtSignal(str)   # pers_nr
    request_edit  = pyqtSignal(str)
    request_del   = pyqtSignal(str)
    request_abr   = pyqtSignal(str)

    def __init__(self, emp: dict, parent=None):
        super().__init__(parent)
        self._pers_nr = emp.get("pers_nr", "")
        self.setStyleSheet(
            f"QFrame {{ background:{theme.C_BG_ROW}; border:1px solid {theme.C_BORDER}; "
            f"border-radius:6px; }}"
            f"QFrame:hover {{ background:{theme.C_BG_HOVER}; border-color:{theme.C_BORDER_FOCUS}; }}"
        )
        self.setCursor(Qt.PointingHandCursor)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

        root = QVBoxLayout(self)
        root.setContentsMargins(10, 10, 10, 10)
        root.setSpacing(6)

        # Top row: name
        name = emp.get("vorname_nachname", "—")
        name_lbl = QLabel(name)
        name_lbl.setWordWrap(False)
        name_lbl.setStyleSheet(
            f"color:{theme.C_TEXT_MAIN}; font-family:{theme.FONT_FAMILY}; font-size:{theme.SZ_MD}px; "
            f"font-weight:600; background:transparent; border:none;"
        )
        name_lbl.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        # Elide if too long
        from PyQt5.QtCore import Qt as _Qt
        name_lbl.setMaximumWidth(180)
        root.addWidget(name_lbl)

        # Bottom row: pers_nr badge + action buttons
        btn_row = QHBoxLayout()
        btn_row.setContentsMargins(0, 0, 0, 0)
        btn_row.setSpacing(6)

        badge = QLabel(self._pers_nr)
        badge.setStyleSheet(
            f"background:{theme.C_ACCENT}; color:#ffffff; border-radius:4px; "
            f"font-family:{theme.FONT_FAMILY}; font-size:{theme.SZ_SM}px; font-weight:bold; "
            f"padding:2px 6px;"
        )
        btn_row.addWidget(badge)
        btn_row.addStretch()

        btn_css = (
            f"QPushButton {{ background:{theme.C_BG_INPUT}; color:{theme.C_TEXT_MAIN}; border:none; "
            f"border-radius:4px; font-size:{theme.SZ_MD}px; padding:4px 8px; }}"
            f"QPushButton:hover {{ background:{theme.C_ACCENT}; color:#ffffff; }}"
        )
        del_css = (
            f"QPushButton {{ background:transparent; color:{theme.C_RED}; border:1px solid {theme.C_RED}; "
            f"border-radius:4px; font-size:{theme.SZ_MD}px; padding:4px 8px; }}"
            f"QPushButton:hover {{ background:rgba(243, 139, 168, 0.1); }}"
        )

        abr_btn = QPushButton("📄")
        abr_btn.setToolTip("Abrechnung (PDF) erstellen")
        abr_btn.setFixedSize(28, 28)
        abr_btn.setStyleSheet(btn_css)
        abr_btn.clicked.connect(lambda: self.request_abr.emit(self._pers_nr))
        btn_row.addWidget(abr_btn)

        edit_btn = QPushButton("✏")
        edit_btn.setToolTip("Bearbeiten")
        edit_btn.setFixedSize(28, 28)
        edit_btn.setStyleSheet(btn_css)
        edit_btn.clicked.connect(lambda: self.request_edit.emit(self._pers_nr))
        btn_row.addWidget(edit_btn)

        del_btn = QPushButton("🗑")
        del_btn.setToolTip("Löschen")
        del_btn.setFixedSize(28, 28)
        del_btn.setStyleSheet(del_css)
        del_btn.clicked.connect(lambda: self.request_del.emit(self._pers_nr))
        btn_row.addWidget(del_btn)

        root.addLayout(btn_row)

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            self.clicked.emit(self._pers_nr)
        super().mousePressEvent(e)


class EmployeeListPanel(QWidget):
    """
    Compact sidebar panel listing all Mitarbeiter.

    Signals
    -------
    new_abrechnung(pers_nr)  : user wants to create an Abrechnung for this employee
    add_employee()           : user clicked '+ Mitarbeiter hinzufügen'
    edit_employee(pers_nr)   : user clicked the edit button
    """

    new_abrechnung   = pyqtSignal(str)
    add_employee     = pyqtSignal()
    edit_employee    = pyqtSignal(str)
    employee_selected = pyqtSignal(str)   # emitted when row is clicked/selected
    employee_deleted  = pyqtSignal()      # emitted after a Mitarbeiter is deleted

    def __init__(self, parent=None, store_dir: str = DEFAULT_STORE_DIR):
        super().__init__(parent)
        self._store_dir = store_dir
        self._rows: list[_EmployeeRow] = []
        self._active_pers_nr: str | None = None
        self._filter_text: str = ""

        self.setStyleSheet(f"background:{theme.C_BG_CARD};")

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # ── Search bar ────────────────────────────────────────────────
        from PyQt5.QtWidgets import QLineEdit
        from PyQt5.QtCore import QTimer
        search_container = QWidget()
        search_container.setStyleSheet(f"background:{theme.C_BG_CARD};")
        sl = QHBoxLayout(search_container)
        sl.setContentsMargins(12, 12, 12, 8)
        sl.setSpacing(6)

        self._search_edit = QLineEdit()
        self._search_edit.setPlaceholderText("🔍  Suchen (Name / Nr.)")
        self._search_edit.setClearButtonEnabled(True)
        self._search_edit.setStyleSheet(
            f"QLineEdit {{ background:{theme.C_BG_INPUT}; color:{theme.C_TEXT_MAIN}; "
            f"border:1px solid {theme.C_BORDER}; border-radius:6px; "
            f"padding:8px 12px; font-family:{theme.FONT_FAMILY}; font-size:{theme.SZ_MD}px; }}"
            f"QLineEdit:focus {{ border-color:{theme.C_ACCENT}; }}"
        )
        sl.addWidget(self._search_edit)
        root.addWidget(search_container)

        # Debounce timer (300ms)
        self._search_timer = QTimer(self)
        self._search_timer.setSingleShot(True)
        self._search_timer.setInterval(300)
        self._search_timer.timeout.connect(self._apply_filter)
        self._search_edit.textChanged.connect(lambda _: self._search_timer.start())

        # ── Scrollable rows ───────────────────────────────────────────
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setStyleSheet(
            f"QScrollArea {{ border:none; background:{theme.C_BG_CARD}; }}"
            f"QScrollBar:vertical {{ background:{theme.C_BG_CARD}; width:5px; border-radius:2px; }}"
            f"QScrollBar::handle:vertical {{ background:#9CA3AF; border-radius:2px; min-height:20px; }}"
            f"QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height:0; }}"
        )

        self._list_body = QWidget()
        self._list_body.setStyleSheet(f"background:{theme.C_BG_CARD};")
        self._list_layout = QVBoxLayout(self._list_body)
        self._list_layout.setContentsMargins(12, 4, 12, 12)
        self._list_layout.setSpacing(8)
        self._list_layout.addStretch()

        scroll.setWidget(self._list_body)
        root.addWidget(scroll)

        # ── "+ Mitarbeiter hinzufügen" button ─────────────────────────
        add_btn = QPushButton("＋  Mitarbeiter hinzufügen")
        add_btn.setStyleSheet(
            f"QPushButton {{ background:transparent; color:{theme.C_ACCENT}; "
            f"font-family:{theme.FONT_FAMILY}; font-size:{theme.SZ_MD}px; font-weight:bold; "
            f"border:1px dashed {theme.C_BORDER_FOCUS}; border-radius:6px; "
            f"padding:12px; margin:12px; }}"
            f"QPushButton:hover {{ background:{theme.C_BG_HOVER}; }}"
        )
        add_btn.clicked.connect(self.add_employee)
        root.addWidget(add_btn)

        # Divider
        div = QFrame()
        div.setFrameShape(QFrame.HLine)
        div.setStyleSheet(f"color:{theme.C_BORDER};")
        root.addWidget(div)

        self.refresh()

    # ── Public API ────────────────────────────────────────────────────

    def refresh(self):
        """Reload the employee list from disk, applying current filter."""
        # Clear existing rows (but keep the stretch at end)
        while self._list_layout.count() > 1:
            item = self._list_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        employees = list_employees(self._store_dir)
        self._rows.clear()

        # Apply search filter
        q = self._filter_text.lower().strip()
        if q:
            employees = [e for e in employees
                         if q in e.get("vorname_nachname", "").lower()
                         or q in e.get("pers_nr", "").lower()]

        if not employees:
            msg = "Keine Treffer" if q else "Noch kein Mitarbeiter"
            empty = QLabel(msg)
            empty.setAlignment(Qt.AlignCenter)
            empty.setStyleSheet(
                f"color:{theme.C_TEXT_MUTED}; font-family:{theme.FONT_FAMILY}; font-size:{theme.SZ_MD}px; padding:16px;"
            )
            self._list_layout.insertWidget(0, empty)
            return

        for i, emp in enumerate(employees):
            row = _EmployeeRow(emp)
            row.clicked.connect(self._on_row_clicked)
            row.request_abr.connect(self.new_abrechnung)
            row.request_edit.connect(self.edit_employee)
            row.request_del.connect(self._on_delete)
            self._rows.append(row)
            self._list_layout.insertWidget(i, row)
            if emp.get("pers_nr") == self._active_pers_nr:
                row.setStyleSheet(
                    f"QFrame {{ background:{theme.C_BG_HOVER}; border:1px solid {theme.C_ACCENT}; border-radius:6px; }}"
                )

    def _apply_filter(self):
        """Called by the debounce timer when search text changes."""
        self._filter_text = self._search_edit.text()
        self.refresh()

    def _on_row_clicked(self, pers_nr: str):
        """Highlight the clicked row and emit employee_selected."""
        self._active_pers_nr = pers_nr
        for row in self._rows:
            if row._pers_nr == pers_nr:
                row.setStyleSheet(
                    f"QFrame {{ background:{theme.C_BG_HOVER}; border:1px solid {theme.C_ACCENT}; border-radius:6px; }}"
                )
            else:
                row.setStyleSheet(
                    f"QFrame {{ background:{theme.C_BG_ROW}; border:1px solid {theme.C_BORDER}; border-radius:6px; }}"
                    f"QFrame:hover {{ background:{theme.C_BG_HOVER}; border-color:{theme.C_BORDER_FOCUS}; }}"
                )
        self.employee_selected.emit(pers_nr)

    def _on_delete(self, pers_nr: str):
        from PyQt5.QtWidgets import QMessageBox
        emp = None
        try:
            from pdf_editor.core.employee_store import load_employee
            emp = load_employee(pers_nr, self._store_dir)
        except Exception:
            pass
        name = emp.get("vorname_nachname", pers_nr) if emp else pers_nr
        ans = QMessageBox.question(
            self, "Mitarbeiter löschen",
            f"⚠ï¸  <b>{name}</b> ({pers_nr}) wirklich löschen?<br>"
            "Alle gespeicherten Abrechnungen gehen verloren.",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if ans == QMessageBox.Yes:
            delete_employee(pers_nr, self._store_dir)
            if self._active_pers_nr == pers_nr:
                self._active_pers_nr = None
            self.refresh()
            self.employee_deleted.emit()   # tell main window to clear forms
