"""
pdf_editor/__main__.py
======================
Entry point — run with:

    python -m pdf_editor

Requirements:
    pip install PyQt5 pypdfium2 pikepdf opencv-python-headless numpy Pillow
"""

import sys

# !! IMPORTANT: pikepdf must be imported before PyQt5/QApplication !!
# pikepdf bundles QPDF which ships its own Qt5 DLLs.  If PyQt5's Qt5 is
# initialized first, loading pikepdf's Qt5 DLLs causes a silent crash on
# Windows.  Importing pikepdf here (before any Qt initialisation) avoids it.
import pikepdf  # noqa: F401  — side-effect import for DLL ordering

from PyQt5.QtGui     import QFont
from PyQt5.QtWidgets import QApplication

from pdf_editor.ui.main_window import PDFEditor


def main():
    app = QApplication(sys.argv)
    app.setFont(QFont("Inter", 10))
    win = PDFEditor()
    win.show()
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
