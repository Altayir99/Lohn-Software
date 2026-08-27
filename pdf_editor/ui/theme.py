import os
import sys

from PyQt5.QtGui import QFont, QColor, QFontDatabase

# ── Load bundled Inter font ──────────────────────────────────────────
def _load_inter():
    """Register Inter TTF files with Qt so 'Inter' is available globally."""
    if getattr(sys, 'frozen', False):
        base = os.path.dirname(sys.executable)
    else:
        base = os.path.dirname(os.path.abspath(__file__))
    fonts_dir = os.path.join(base, "fonts")
    if not os.path.isdir(fonts_dir):
        return
    for fn in os.listdir(fonts_dir):
        if fn.lower().endswith(".ttf"):
            QFontDatabase.addApplicationFont(os.path.join(fonts_dir, fn))

_load_inter()

# ── Font Sizes (Scaled up for Surface Pro / High-DPI readability) ──
FONT_FAMILY = "'Inter', 'Segoe UI', system-ui, sans-serif"

SZ_SM = 12  # Small text (labels, hints)
SZ_MD = 14  # Regular text (inputs, table cells)
SZ_LG = 18  # Subheaders
SZ_XL = 24  # Large summary numbers

# ── Color Palette (Professional Warm Beige Light Mode) ────────────────
C_BG_APP     = "#EDE8DF"   # Warm sand app background
C_BG_CARD    = "#F7F3EB"   # Visible cream for cards/panels
C_BG_ROW     = "#F0ECE3"   # Warm oat row background
C_BG_HOVER   = "#E3DDD2"   # Warm hover state
C_BG_INPUT   = "#FAF7F1"   # Soft cream inputs

C_BORDER     = "#D6D0C4"   # Warm beige borders
C_BORDER_FOCUS = "#2563EB" # Focused borders (Blue)

C_TEXT_MAIN  = "#111827"   # Primary text (almost black)
C_TEXT_MUTED = "#6B7280"   # Secondary text (labels, notes)

C_ACCENT     = "#2563EB"   # Primary brand color (Professional Blue)
C_ACCENT_HOVER = "#1D4ED8" # Darker blue on hover
C_GREEN      = "#059669"   # Positive values (Netto)
C_RED        = "#DC2626"   # Deductions (Steuer, SV)

# ── Common Style Mixins ───────────────────────────────────────────────

def get_base_stylesheet() -> str:
    """Returns the base stylesheet for the entire application."""
    return f"""
        QMainWindow {{ background: {C_BG_APP}; }}
        QWidget {{ color: {C_TEXT_MAIN}; font-family: {FONT_FAMILY}; }}
        
        QSplitter::handle {{ background: {C_BORDER}; width: 1px; }}

        /* Scrollbars */
        QScrollArea {{ border: none; background: transparent; }}
        QScrollBar:vertical {{ background: transparent; width: 8px; border-radius: 4px; }}
        QScrollBar::handle:vertical {{ background: #9CA3AF; border-radius: 4px; min-height: 30px; }}
        QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
        
        QScrollBar:horizontal {{ background: transparent; height: 8px; border-radius: 4px; }}
        QScrollBar::handle:horizontal {{ background: #9CA3AF; border-radius: 4px; }}

        /* Tooltip */
        QToolTip {{
            background: {C_BG_HOVER};
            color: {C_TEXT_MAIN};
            border: 1px solid {C_BORDER};
            padding: 4px 8px;
            border-radius: 4px;
            font-size: {SZ_SM}px;
        }}
    """

def css_card() -> str:
    return f"""
        background: {C_BG_CARD};
        border: 1px solid {C_BORDER};
        border-radius: 8px;
    """

def css_input() -> str:
    return f"""
        QLineEdit {{
            background: {C_BG_INPUT};
            color: {C_TEXT_MAIN};
            border: 1px solid {C_BORDER};
            border-radius: 6px;
            padding: 8px 12px;
            font-family: {FONT_FAMILY};
            font-size: {SZ_MD}px;
        }}
        QLineEdit:focus {{
            border: 1px solid {C_BORDER_FOCUS};
            background: {C_BG_CARD};
        }}
        QLineEdit:read-only {{
            background: {C_BG_ROW};
            color: {C_TEXT_MUTED};
        }}
    """

def css_button_primary() -> str:
    return f"""
        QPushButton {{
            background: {C_ACCENT};
            color: #ffffff;
            border: none;
            border-radius: 6px;
            padding: 10px 20px;
            font-family: {FONT_FAMILY};
            font-size: {SZ_MD}px;
            font-weight: bold;
        }}
        QPushButton:hover {{ background: {C_ACCENT_HOVER}; }}
        QPushButton:pressed {{ background: #5a6a9e; }}
    """

def css_button_secondary() -> str:
    return f"""
        QPushButton {{
            background: {C_BG_INPUT};
            color: {C_TEXT_MAIN};
            border: 1px solid {C_BORDER};
            border-radius: 6px;
            padding: 10px 20px;
            font-family: {FONT_FAMILY};
            font-size: {SZ_MD}px;
            font-weight: 600;
        }}
        QPushButton:hover {{ background: {C_BG_HOVER}; border-color: {C_BORDER_FOCUS}; }}
        QPushButton:pressed {{ background: {C_BG_ROW}; }}
    """

def css_button_danger() -> str:
    return f"""
        QPushButton {{
            background: transparent;
            color: {C_RED};
            border: 1px solid {C_RED};
            border-radius: 6px;
            padding: 10px 20px;
            font-family: {FONT_FAMILY};
            font-size: {SZ_MD}px;
            font-weight: 600;
        }}
        QPushButton:hover {{ background: rgba(243, 139, 168, 0.1); }}
    """

def css_label_header() -> str:
    return f"""
        color: {C_TEXT_MAIN};
        font-family: {FONT_FAMILY};
        font-size: {SZ_LG}px;
        font-weight: 800;
        background: transparent;
    """

def css_label_sub() -> str:
    return f"""
        color: {C_TEXT_MUTED};
        font-family: {FONT_FAMILY};
        font-size: {SZ_SM}px;
        background: transparent;
    """
