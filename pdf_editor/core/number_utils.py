"""
number_utils.py
===============
Utilities for converting between German number format ('9.582,19') and float.
"""

import re

_DE_MONTHS = {
    "januar": 1, "februar": 2, "märz": 3, "april": 4,
    "mai": 5, "juni": 6, "juli": 7, "august": 8,
    "september": 9, "oktober": 10, "november": 11, "dezember": 12,
}


def parse_de(s: str) -> float:
    """
    Convert a German-formatted number string to float.

    Examples
    --------
    '9.582,19'   →  9582.19
    '9.582,19-'  →  -9582.19
    '-9.582,19'  →  -9582.19
    '498,88'     →  498.88
    ''           →  0.0
    """
    if not s:
        return 0.0
    s = str(s).strip()
    if not s:
        return 0.0

    # Detect trailing or leading minus
    negative = False
    if s.endswith('-'):
        negative = True
        s = s[:-1].strip()
    elif s.startswith('-'):
        negative = True
        s = s[1:].strip()

    # Remove thousands dots, replace decimal comma with dot
    s = s.replace('.', '').replace(',', '.')

    try:
        val = float(s)
        return -val if negative else val
    except (ValueError, TypeError):
        return 0.0


def fmt_de(v: float, trailing_minus: bool = False, decimals: int = 2) -> str:
    """
    Format a float as a German number string.

    Examples
    --------
    9582.19             →  '9.582,19'
    -9582.19 (trailing) →  '9.582,19-'
    498.88              →  '498,88'
    """
    if v is None:
        return ""
    negative = v < 0
    v = abs(v)

    # Build with Python's locale-independent formatter using comma for thousands
    fmt = f"{v:,.{decimals}f}"          # e.g. "9,582.19"
    # Swap separators: , → X, . → ,, X → .
    result = fmt.replace(',', 'X').replace('.', ',').replace('X', '.')

    if negative:
        return f"{result}-" if trailing_minus else f"-{result}"
    return result


def parse_abrechnungsmonat(text: str) -> tuple[int, int] | None:
    """
    Parse an 'Abrechnungsmonat' string into (year, month).

    Accepts:
        'Januar 2026'  → (2026, 1)
        'Dezember 2025' → (2025, 12)
        '2025-12'      → (2025, 12)

    Returns None if unparsable.
    """
    text = text.strip()
    # Try 'YYYY-MM'
    m = re.match(r'^(\d{4})-(\d{1,2})$', text)
    if m:
        return int(m.group(1)), int(m.group(2))
    # Try 'Monatname YYYY'
    m = re.match(r'^([A-Za-zäöüÄÖÜ]+)\s+(\d{4})$', text)
    if m:
        month_name = m.group(1).lower()
        year = int(m.group(2))
        month = _DE_MONTHS.get(month_name)
        if month:
            return year, month
    return None


def monat_key(year: int, month: int) -> str:
    """Return the storage key string e.g. '2025-12'."""
    return f"{year:04d}-{month:02d}"
