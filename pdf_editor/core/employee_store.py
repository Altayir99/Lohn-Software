"""
employee_store.py
=================
Persistent employee (Mitarbeiter) storage using one JSON file per employee.

Directory structure
-------------------
<project_root>/mitarbeiter/
    00237_bosnjakovic.json
    00412_mueller.json
    ...

Employee JSON schema
--------------------
{
  "pers_nr":            "00237",
  "vorname_nachname":   "Milorad Bosnjakovic",
  "geburtsdatum":       "22.06.1983",
  "eintritt":           "01.01.2025",
  "austritt":           "",
  "steuer_id":          "82351078699",
  "st_kl":              "1",
  "faktor":             "",
  "kinder_fb":          "0,0",
  "st_tg":              "30",
  "freibetrag_jaehrl":  "",
  "freibetrag_mtl":     "",
  "konfession":         "/",
  "anrede":             "Herrn",
  "strasse_hausnummer": "Potsdamer Straße 197",
  "plz_ort":            "10783 Berlin",
  "p_nr":               "237*",
  "versicherungs_nr":   "25220683B013",
  "krankenkasse":       "AOK Nordost",
  "kk_pct":             "14,60",
  "z_pct":              "3,50",
  "pv_kinder_kz":       "0",
  "bbg_kv":             "5512.50",
  "bbg_rv":             "8050.00",
  "p": "1", "g": "0", "s": "1", "um": "2",
  "mfb": "Nein", "ueb": "1", "b": "1",
  "g_sv": "1", "r": "1", "s_sv": "1", "sv_tg": "30",
  "iban":               "",
  "bic":                "",
  "arbeitgeber_name":   "",
  "vertragsart":        "vollzeit",
  "wochenstunden":      "40",
  "urlaubstage":        "28",
  "abrechnungen": {
    "2025-01": {
      "abrechnungs_brutto": "9582.19",
      "lohnsteuer":         "2498.25",
      "solz":               "99.45",
      "kv_beitrag":         "498.88",
      "rv_beitrag":         "748.65",
      "av_beitrag":         "104.65",
      "pv_beitrag":         "132.31",
      "abrechnungs_netto":  "5500.00"
    }
  }
}

Kumuliert fields are NEVER stored explicitly — they are always calculated
on-the-fly by summing all months before the current one.
"""

import json
import os
import re
import sys
from pathlib import Path

from pdf_editor.core.number_utils import parse_de, fmt_de, monat_key

# ── Store directory (mirrors payroll_fields._ROOT logic) ─────────────────────
_HERE = os.path.dirname(os.path.abspath(__file__))
if getattr(sys, 'frozen', False):
    # Frozen: store data next to the .exe so it persists on USB
    _ROOT = os.path.dirname(sys.executable)
else:
    _ROOT = os.path.dirname(os.path.dirname(_HERE))

DEFAULT_STORE_DIR = os.path.join(_ROOT, "mitarbeiter")

# Keys stored per month (the "history" record)
MONAT_KEYS = [
    "abrechnungs_brutto",
    "lohnsteuer",
    "solz",
    "kv_beitrag",
    "rv_beitrag",
    "av_beitrag",
    "pv_beitrag",
    "abrechnungs_netto",
    # AG contributions (for SV-AG-Anteil kum.)
    "kv_beitrag_ag",
    "rv_beitrag_ag",
    "av_beitrag_ag",
    "pv_beitrag_ag",
]


# ── Internal helpers ──────────────────────────────────────────────────────────

def _ensure_dir(store_dir: str) -> Path:
    d = Path(store_dir)
    d.mkdir(parents=True, exist_ok=True)
    return d


def _sanitize(name: str) -> str:
    """Last word of name, lowercased, ASCII-only, for use in filename."""
    last = (name.split()[-1] if name.split() else "unbekannt").lower()
    return re.sub(r'[^a-z0-9]', '', last) or "unbekannt"


def _filename(pers_nr: str, name: str) -> str:
    return f"{pers_nr}_{_sanitize(name)}.json"


def _find_file(store_dir: str, pers_nr: str) -> Path | None:
    """Locate an existing JSON file for the given Pers-Nr."""
    d = Path(store_dir)
    for f in d.glob(f"{pers_nr}_*.json"):
        return f
    return None


# ── Public API ────────────────────────────────────────────────────────────────

def list_employees(store_dir: str = DEFAULT_STORE_DIR) -> list[dict]:
    """Return all employee records, sorted by Pers-Nr."""
    d = Path(store_dir)
    if not d.exists():
        return []
    employees = []
    for f in sorted(d.glob("*.json")):
        try:
            with open(f, encoding='utf-8') as fh:
                employees.append(json.load(fh))
        except Exception:
            pass
    return sorted(employees, key=lambda e: e.get("pers_nr", ""))


def load_employee(pers_nr: str,
                  store_dir: str = DEFAULT_STORE_DIR) -> dict | None:
    """Load a single employee by Pers-Nr. Returns None if not found."""
    f = _find_file(store_dir, pers_nr)
    if f is None:
        return None
    try:
        with open(f, encoding='utf-8') as fh:
            return json.load(fh)
    except Exception:
        return None


def save_employee(data: dict,
                  store_dir: str = DEFAULT_STORE_DIR) -> None:
    """
    Save (create or update) an employee record.
    If the Pers-Nr already exists under a different filename, the old file
    is removed first.
    """
    d = _ensure_dir(store_dir)
    pers_nr = data.get("pers_nr", "00000")
    name    = data.get("vorname_nachname", "")
    new_fn  = _filename(pers_nr, name)

    # Remove any old file for this Pers-Nr with a different name
    for old in d.glob(f"{pers_nr}_*.json"):
        if old.name != new_fn:
            old.unlink()

    # Ensure the 'abrechnungen' key exists
    data.setdefault("abrechnungen", {})

    with open(d / new_fn, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def delete_employee(pers_nr: str,
                    store_dir: str = DEFAULT_STORE_DIR) -> bool:
    """Delete an employee record. Returns True if a file was removed."""
    f = _find_file(store_dir, pers_nr)
    if f:
        f.unlink()
        return True
    return False


# ── Monthly history helpers ───────────────────────────────────────────────────

def save_monat(pers_nr: str, year: int, month: int,
               monat_values: dict[str, float],
               store_dir: str = DEFAULT_STORE_DIR) -> None:
    """
    Persist the computed monthly values for a given Abrechnung month.
    ``monat_values`` keys must be from MONAT_KEYS, values are floats.
    """
    emp = load_employee(pers_nr, store_dir)
    if emp is None:
        return
    key = monat_key(year, month)
    emp.setdefault("abrechnungen", {})[key] = {
        k: monat_values.get(k, 0.0) for k in MONAT_KEYS
    }
    save_employee(emp, store_dir)


def get_kum_vormonat(pers_nr: str, year: int, month: int,
                     store_dir: str = DEFAULT_STORE_DIR) -> dict[str, float]:
    """
    Return cumulative totals for all months BEFORE (year, month),
    within the SAME year only (kumuliert resets each January).

    The result dict has the same keys as MONAT_KEYS, each value being the
    sum of all stored months in the given year that are strictly earlier
    than the given month.
    """
    emp = load_employee(pers_nr, store_dir)
    totals = {k: 0.0 for k in MONAT_KEYS}
    if emp is None:
        return totals

    year_prefix = f"{year:04d}-"
    current_key = monat_key(year, month)
    for mk, vals in emp.get("abrechnungen", {}).items():
        # Only sum months from the SAME year, strictly before current month
        if mk.startswith(year_prefix) and mk < current_key:
            for k in MONAT_KEYS:
                try:
                    totals[k] += float(vals.get(k, 0.0))
                except (TypeError, ValueError):
                    pass
    return totals


def employee_to_field_values(emp: dict) -> dict[str, str]:
    """
    Map an employee record's Stammdaten to the FIELD_SPEC field IDs
    used by the PDF editor form.
    """
    mapping = {
        "pers_nr":            "pers_nr",
        "steuer_id":          "steuer_id",
        "geburtsdatum":       "geburtsdatum",
        "eintritt":           "eintritt",
        "austritt":           "austritt",
        "st_kl":              "st_kl_steuerklasse",
        "faktor":             "faktor",
        "kinder_fb":          "kinder_fb",
        "st_tg":              "st_tg_steuertage",
        "freibetrag_jaehrl":  "freibetrag_jaehrl",
        "freibetrag_mtl":     "freibetrag_mtl",
        "konfession":         "konfession",
        "versicherungs_nr":   "versicherungs_nr",
        "krankenkasse":       "krankenkassenname",
        "kk_pct":             "kk_pct",
        "z_pct":              "z_pct",
        "pv_kinder_kz":       "pv_kinder_kennzeichen",
        "p":  "p",  "g":  "g",  "s":  "s",  "um": "um",
        "mfb":"mfb","ueb":"ueb","b":  "b",
        "g_sv":"g_sv","r": "r", "s_sv":"s_sv","sv_tg":"sv_tg",
        "anrede":             "anrede",
        "vorname_nachname":   "vorname_nachname",
        "strasse_hausnummer": "strasse_hausnummer",
        "plz_ort":            "plz_ort",
        "iban":               "iban",
        "bic":                "bic",
        "bank_name":          "bank",
        "arbeitgeber_name":   "arbeitgeber_name",
    }
    result = {}
    for emp_key, field_id in mapping.items():
        val = emp.get(emp_key, "")
        if val:
            result[field_id] = str(val)
    # p_nr (Empfängeradresse) mirrors pers_nr but formatted: strip leading zeros + "*"
    # e.g. "00237" → "237*"
    if "pers_nr" in result:
        raw = result["pers_nr"].lstrip("0") or "0"
        result["p_nr"] = raw + "*"
    return result
