"""
lohnpro_mcp_server.py
=====================
MCP (Model Context Protocol) server for LohnPRO — exposes the payroll
calculation engine, employee store, PDF generation, and field spec to
AI coding agents (Codex, Claude, etc.) via JSON-RPC over stdio.

Usage:
    python lohnpro_mcp_server.py

Configure in your MCP client (e.g. .cursor/mcp.json or claude_desktop_config.json):
    {
      "mcpServers": {
        "lohnpro": {
          "command": "python",
          "args": ["c:/Users/firas/Documents/GitHub/pdf/lohnpro_mcp_server.py"]
        }
      }
    }
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import traceback

# ── Add project root to path so pdf_editor package is importable ──────────────
_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)


# ── MCP Protocol helpers ──────────────────────────────────────────────────────

def _send(obj: dict) -> None:
    """Write a JSON-RPC message to stdout (newline-delimited)."""
    line = json.dumps(obj, ensure_ascii=False)
    sys.stdout.write(line + "\n")
    sys.stdout.flush()


def _ok(id_, result) -> None:
    _send({"jsonrpc": "2.0", "id": id_, "result": result})


def _err(id_, code: int, message: str, data=None) -> None:
    error = {"code": code, "message": message}
    if data is not None:
        error["data"] = data
    _send({"jsonrpc": "2.0", "id": id_, "error": error})


# ── Tool implementations ──────────────────────────────────────────────────────

def _tool_calculate_payroll(args: dict) -> dict:
    """
    Run the full BMF PAP 2026 payroll calculation.

    Required: grundgehalt (float)
    Optional: stkl (1-6), kfb (float), kk_pct (float), z_pct (float),
              pv_kinderlos (bool), rv_pflicht (bool), av_pflicht (bool),
              bundesland ("west"|"sachsen"|"ost"),
              kist_satz (0.0|0.08|0.09),
              jfreib (float), jhinzu (float),
              ueberstunden (float), sachbezug (float),
              einmalzahlung (float), fahrgeld (float),
              vwl_ag (float), vorschuss (float), vwl_an (float),
              beschaeftigung ("vollzeit"|"minijob"|"midijob")
    """
    from pdf_editor.core.sv_calculator import calculate_full, BBG_KV_2026, BBG_RV_2026

    kwargs = {
        "grundgehalt":   float(args.get("grundgehalt", 0)),
        "stkl":          int(args.get("stkl", 1)),
        "kfb":           float(args.get("kfb", 0.0)),
        "kk_pct":        float(args.get("kk_pct", 14.60)),
        "z_pct":         float(args.get("z_pct", 2.20)),
        "pv_kinderlos":  bool(args.get("pv_kinderlos", False)),
        "rv_pflicht":    bool(args.get("rv_pflicht", True)),
        "av_pflicht":    bool(args.get("av_pflicht", True)),
        "bundesland":    str(args.get("bundesland", "west")),
        "kist_satz":     float(args.get("kist_satz", 0.0)),
        "jfreib":        float(args.get("jfreib", 0.0)),
        "jhinzu":        float(args.get("jhinzu", 0.0)),
        "ueberstunden":  float(args.get("ueberstunden", 0.0)),
        "sachbezug":     float(args.get("sachbezug", 0.0)),
        "einmalzahlung": float(args.get("einmalzahlung", 0.0)),
        "fahrgeld":      float(args.get("fahrgeld", 0.0)),
        "vwl_ag":        float(args.get("vwl_ag", 0.0)),
        "vorschuss":     float(args.get("vorschuss", 0.0)),
        "vwl_an":        float(args.get("vwl_an", 0.0)),
        "beschaeftigung": str(args.get("beschaeftigung", "vollzeit")),
    }

    r = calculate_full(**kwargs)
    return {
        "gesamtbrutto":   r.gesamtbrutto,
        "lfd_brutto":     r.lfd_brutto,
        "netto":          r.netto,
        "lohnsteuer":     r.pap.lst_monat,
        "solz":           r.solz_gesamt,
        "kirchensteuer":  r.kist_gesamt,
        "steuer_gesamt":  r.steuer_gesamt,
        "sv": {
            "kv_sv_brutto":  r.sv.kv_sv_brutto,
            "kv_an":         r.sv.kv_beitrag_an,
            "kv_ag":         r.sv.kv_beitrag_ag,
            "rv_sv_brutto":  r.sv.rv_sv_brutto,
            "rv_an":         r.sv.rv_beitrag_an,
            "rv_ag":         r.sv.rv_beitrag_ag,
            "av_sv_brutto":  r.sv.av_sv_brutto,
            "av_an":         r.sv.av_beitrag_an,
            "av_ag":         r.sv.av_beitrag_ag,
            "pv_sv_brutto":  r.sv.pv_sv_brutto,
            "pv_an":         r.sv.pv_beitrag_an,
            "pv_ag":         r.sv.pv_beitrag_ag,
            "sv_an_gesamt":  r.sv.sv_an_gesamt,
            "sv_ag_gesamt":  r.sv.sv_ag_gesamt,
        },
        "pap": {
            "zve":          r.pap.zve,
            "vps":          r.pap.vps,
            "lst_monat":    r.pap.lst_monat,
            "solz_monat":   r.pap.solz_monat,
            "lst_jahr":     r.pap.lst_jahr,
        },
        "einmalzahlung_sv_an": r.sv_einmal_an,
        "lst_einmal":      r.lst_einmal,
        "abzuege_gesamt":  r.abzuege_gesamt,
    }


def _tool_list_employees(args: dict) -> list:
    """
    List all saved employees.
    Optional: store_dir (str, defaults to <repo>/mitarbeiter)
    """
    from pdf_editor.core.employee_store import list_employees, DEFAULT_STORE_DIR
    store = args.get("store_dir", DEFAULT_STORE_DIR)
    return list_employees(store)


def _tool_get_employee(args: dict) -> dict | None:
    """
    Load a single employee by Personalnummer.
    Required: pers_nr (str)
    Optional: store_dir (str)
    """
    from pdf_editor.core.employee_store import load_employee, DEFAULT_STORE_DIR
    pers_nr = str(args["pers_nr"])
    store = args.get("store_dir", DEFAULT_STORE_DIR)
    return load_employee(pers_nr, store)


def _tool_save_employee(args: dict) -> dict:
    """
    Create or update an employee record.
    Required: data (dict matching employee JSON schema)
    Optional: store_dir (str)
    """
    from pdf_editor.core.employee_store import save_employee, DEFAULT_STORE_DIR
    data = args["data"]
    store = args.get("store_dir", DEFAULT_STORE_DIR)
    save_employee(data, store)
    return {"ok": True, "pers_nr": data.get("pers_nr")}


def _tool_delete_employee(args: dict) -> dict:
    """
    Delete an employee record.
    Required: pers_nr (str)
    Optional: store_dir (str)
    """
    from pdf_editor.core.employee_store import delete_employee, DEFAULT_STORE_DIR
    pers_nr = str(args["pers_nr"])
    store = args.get("store_dir", DEFAULT_STORE_DIR)
    removed = delete_employee(pers_nr, store)
    return {"ok": removed, "pers_nr": pers_nr}


def _tool_get_cumulative(args: dict) -> dict:
    """
    Get cumulative (Kumuliert) values for an employee up to but not including
    the given month, within the same year.
    Required: pers_nr (str), year (int), month (int, 1-12)
    Optional: store_dir (str)
    """
    from pdf_editor.core.employee_store import get_kum_vormonat, DEFAULT_STORE_DIR
    pers_nr = str(args["pers_nr"])
    year = int(args["year"])
    month = int(args["month"])
    store = args.get("store_dir", DEFAULT_STORE_DIR)
    return get_kum_vormonat(pers_nr, year, month, store)


def _tool_save_month(args: dict) -> dict:
    """
    Persist monthly payroll values for an employee.
    Required: pers_nr (str), year (int), month (int), monat_values (dict)
    Optional: store_dir (str)
    """
    from pdf_editor.core.employee_store import save_monat, DEFAULT_STORE_DIR, MONAT_KEYS
    pers_nr = str(args["pers_nr"])
    year = int(args["year"])
    month = int(args["month"])
    monat_values = {k: float(v) for k, v in args["monat_values"].items()
                    if k in MONAT_KEYS}
    store = args.get("store_dir", DEFAULT_STORE_DIR)
    save_monat(pers_nr, year, month, monat_values, store)
    return {"ok": True}


def _tool_generate_pdf(args: dict) -> dict:
    """
    Generate a filled Brutto-Netto-Abrechnung PDF.
    Required: field_values (dict of field_id -> value string)
    Optional: output_path (str) — if omitted, writes to a temp file
    Returns: {"output_path": str, "size_bytes": int}
    """
    from pdf_editor.core.overlay_editor import create_filled_pdf
    from pdf_editor.core.payroll_fields import FIELD_SPEC, TEMPLATE_BLANK_PDF

    field_values = {str(k): str(v) for k, v in args["field_values"].items()}
    output_path = args.get("output_path")

    if not output_path:
        tmp = tempfile.NamedTemporaryFile(
            suffix=".pdf", delete=False,
            prefix="lohnpro_", dir=tempfile.gettempdir()
        )
        tmp.close()
        output_path = tmp.name

    pdf_bytes = create_filled_pdf(
        template_path=TEMPLATE_BLANK_PDF,
        field_values=field_values,
        field_spec=FIELD_SPEC,
        output_path=output_path,
    )
    return {
        "output_path": output_path,
        "size_bytes": len(pdf_bytes),
    }


def _tool_extract_pdf(args: dict) -> dict:
    """
    Extract field values from an existing filled Brutto-Netto-Abrechnung PDF.
    Required: pdf_path (str)
    Returns: dict of field_id -> extracted text
    """
    from pdf_editor.core.pdf_importer import extract_fields_from_pdf
    pdf_path = str(args["pdf_path"])
    extracted = extract_fields_from_pdf(pdf_path)
    return extracted


def _tool_get_field_spec(args: dict) -> list:
    """
    Return the full FIELD_SPEC list with all field metadata.
    Optional: section (str) — filter to a specific section
    Optional: editable_only (bool) — if true, exclude editable=False and _ fields
    """
    from pdf_editor.core.payroll_fields import FIELD_SPEC
    section = args.get("section")
    editable_only = bool(args.get("editable_only", False))
    result = []
    for f in FIELD_SPEC:
        if section and f.get("section") != section:
            continue
        if editable_only:
            if f["id"].startswith("_"):
                continue
            if f.get("editable") is False:
                continue
        result.append(f)
    return result


def _tool_get_sv_constants(args: dict) -> dict:
    """
    Return all current SV and tax constants from sv_calculator.py.
    No arguments required.
    """
    from pdf_editor.core import sv_calculator as sv
    constants = {}
    for name in dir(sv):
        if name.startswith("_"):
            continue
        val = getattr(sv, name)
        if isinstance(val, (int, float, str)):
            constants[name] = val
    return constants


def _tool_netto_to_brutto(args: dict) -> dict:
    """
    Find the Grundgehalt that produces a given Netto via bisection.
    Required: target_netto (float)
    Optional: same SV/tax params as calculate_payroll
    Returns: {"brutto": float, "netto_achieved": float, "diff_cents": float}
    """
    from pdf_editor.core.sv_calculator import calculate_full

    target = float(args["target_netto"])
    params = {k: v for k, v in args.items() if k != "target_netto"}

    def run(g: float):
        return calculate_full(grundgehalt=g, **{
            "stkl":          int(params.get("stkl", 1)),
            "kfb":           float(params.get("kfb", 0.0)),
            "kk_pct":        float(params.get("kk_pct", 14.60)),
            "z_pct":         float(params.get("z_pct", 2.20)),
            "pv_kinderlos":  bool(params.get("pv_kinderlos", False)),
            "rv_pflicht":    bool(params.get("rv_pflicht", True)),
            "av_pflicht":    bool(params.get("av_pflicht", True)),
            "bundesland":    str(params.get("bundesland", "west")),
            "kist_satz":     float(params.get("kist_satz", 0.0)),
            "beschaeftigung": str(params.get("beschaeftigung", "vollzeit")),
        })

    lo, hi = 0.0, target * 3.5
    r_hi = run(hi)
    while r_hi.netto < target and hi < 500_000:
        hi *= 2
        r_hi = run(hi)

    for _ in range(120):
        mid = (lo + hi) / 2.0
        r = run(mid)
        diff = r.netto - target
        if abs(diff) < 0.005:
            break
        if diff < 0:
            lo = mid
        else:
            hi = mid

    # Cent-level refinement
    base = round((lo + hi) / 2.0, 2)
    best_brutto, best_diff = base, abs(run(base).netto - target)
    for offset in range(-10, 11):
        candidate = round(base + offset * 0.01, 2)
        if candidate < 0:
            continue
        d = abs(run(candidate).netto - target)
        if d < best_diff:
            best_diff, best_brutto = d, candidate

    final = run(best_brutto)
    return {
        "brutto": best_brutto,
        "netto_achieved": final.netto,
        "diff_cents": round((final.netto - target) * 100, 1),
    }


# ── Tool registry ─────────────────────────────────────────────────────────────

TOOLS = {
    "calculate_payroll": {
        "fn": _tool_calculate_payroll,
        "description": (
            "Run a full BMF PAP 2026 monthly payroll calculation. "
            "Returns LSt, SolZ, KiSt, all SV contributions (AN+AG), and net pay."
        ),
        "inputSchema": {
            "type": "object",
            "required": ["grundgehalt"],
            "properties": {
                "grundgehalt":   {"type": "number",  "description": "Gross monthly salary (€)"},
                "stkl":          {"type": "integer", "description": "Steuerklasse 1-6", "default": 1},
                "kfb":           {"type": "number",  "description": "Kinderfreibeträge (0,5 steps)", "default": 0.0},
                "kk_pct":        {"type": "number",  "description": "KV Gesamtbeitrag % (default 14.60)", "default": 14.60},
                "z_pct":         {"type": "number",  "description": "KV Zusatzbeitrag AN+AG gesamt %", "default": 2.20},
                "pv_kinderlos":  {"type": "boolean", "description": "True if employee is childless (PV +0.60%)", "default": False},
                "rv_pflicht":    {"type": "boolean", "description": "Subject to RV?", "default": True},
                "av_pflicht":    {"type": "boolean", "description": "Subject to AV?", "default": True},
                "bundesland":    {"type": "string",  "description": "west|sachsen|ost", "default": "west"},
                "kist_satz":     {"type": "number",  "description": "Church tax rate 0|0.08|0.09", "default": 0.0},
                "jfreib":        {"type": "number",  "description": "Annual ELStAM Freibetrag (€)", "default": 0.0},
                "ueberstunden":  {"type": "number",  "description": "Overtime pay (€)", "default": 0.0},
                "sachbezug":     {"type": "number",  "description": "Non-cash benefit (€)", "default": 0.0},
                "einmalzahlung": {"type": "number",  "description": "One-time payment / Weihnachtsgeld (€)", "default": 0.0},
                "fahrgeld":      {"type": "number",  "description": "Tax-free travel allowance (€)", "default": 0.0},
                "vwl_ag":        {"type": "number",  "description": "VWL employer share (€)", "default": 0.0},
                "vorschuss":     {"type": "number",  "description": "Advance / garnishment (€)", "default": 0.0},
                "vwl_an":        {"type": "number",  "description": "VWL employee share (€)", "default": 0.0},
                "beschaeftigung":{"type": "string",  "description": "vollzeit|minijob|midijob", "default": "vollzeit"},
            },
        },
    },
    "netto_to_brutto": {
        "fn": _tool_netto_to_brutto,
        "description": "Find the gross salary (Brutto) that results in a given net pay (Netto) via bisection search.",
        "inputSchema": {
            "type": "object",
            "required": ["target_netto"],
            "properties": {
                "target_netto": {"type": "number", "description": "Desired net monthly pay (€)"},
                "stkl":         {"type": "integer", "default": 1},
                "kk_pct":       {"type": "number",  "default": 14.60},
                "z_pct":        {"type": "number",  "default": 2.20},
                "bundesland":   {"type": "string",  "default": "west"},
                "beschaeftigung":{"type": "string", "default": "vollzeit"},
            },
        },
    },
    "list_employees": {
        "fn": _tool_list_employees,
        "description": "Return all saved employee records sorted by Personalnummer.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "store_dir": {"type": "string", "description": "Optional path to mitarbeiter/ directory"},
            },
        },
    },
    "get_employee": {
        "fn": _tool_get_employee,
        "description": "Load a single employee by Personalnummer.",
        "inputSchema": {
            "type": "object",
            "required": ["pers_nr"],
            "properties": {
                "pers_nr":   {"type": "string"},
                "store_dir": {"type": "string"},
            },
        },
    },
    "save_employee": {
        "fn": _tool_save_employee,
        "description": "Create or update an employee record (JSON schema: pers_nr, vorname_nachname, geburtsdatum, eintritt, st_kl, iban, krankenkasse, kk_pct, z_pct, ...).",
        "inputSchema": {
            "type": "object",
            "required": ["data"],
            "properties": {
                "data":      {"type": "object", "description": "Employee record dict"},
                "store_dir": {"type": "string"},
            },
        },
    },
    "delete_employee": {
        "fn": _tool_delete_employee,
        "description": "Delete an employee record by Personalnummer.",
        "inputSchema": {
            "type": "object",
            "required": ["pers_nr"],
            "properties": {
                "pers_nr":   {"type": "string"},
                "store_dir": {"type": "string"},
            },
        },
    },
    "get_cumulative": {
        "fn": _tool_get_cumulative,
        "description": "Get cumulative (Kumuliert) payroll totals for an employee for all months before the given month in the same year.",
        "inputSchema": {
            "type": "object",
            "required": ["pers_nr", "year", "month"],
            "properties": {
                "pers_nr":   {"type": "string"},
                "year":      {"type": "integer"},
                "month":     {"type": "integer", "description": "1-12"},
                "store_dir": {"type": "string"},
            },
        },
    },
    "save_month": {
        "fn": _tool_save_month,
        "description": "Persist monthly payroll values for an employee (brutto, lohnsteuer, solz, kv/rv/av/pv beitraege).",
        "inputSchema": {
            "type": "object",
            "required": ["pers_nr", "year", "month", "monat_values"],
            "properties": {
                "pers_nr":      {"type": "string"},
                "year":         {"type": "integer"},
                "month":        {"type": "integer"},
                "monat_values": {"type": "object"},
                "store_dir":    {"type": "string"},
            },
        },
    },
    "generate_pdf": {
        "fn": _tool_generate_pdf,
        "description": "Generate a filled Brutto-Netto-Abrechnung PDF from a dict of field values.",
        "inputSchema": {
            "type": "object",
            "required": ["field_values"],
            "properties": {
                "field_values": {"type": "object", "description": "Dict of field_id → string value"},
                "output_path":  {"type": "string", "description": "Optional output file path"},
            },
        },
    },
    "extract_pdf": {
        "fn": _tool_extract_pdf,
        "description": "Extract field values from an existing filled Brutto-Netto-Abrechnung PDF by bounding-box coordinate lookup.",
        "inputSchema": {
            "type": "object",
            "required": ["pdf_path"],
            "properties": {
                "pdf_path": {"type": "string", "description": "Path to the filled PDF"},
            },
        },
    },
    "get_field_spec": {
        "fn": _tool_get_field_spec,
        "description": "Return the FIELD_SPEC list describing every PDF field (id, label, section, coordinates, type, alignment).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "section":      {"type": "string",  "description": "Filter by section name"},
                "editable_only":{"type": "boolean", "description": "Exclude static/mask fields"},
            },
        },
    },
    "get_sv_constants": {
        "fn": _tool_get_sv_constants,
        "description": "Return all current payroll constants (BBG_KV/RV, Grundfreibetrag, WKP, MINIJOB_GRENZE, etc.) from sv_calculator.py.",
        "inputSchema": {"type": "object", "properties": {}},
    },
}


# ── MCP Protocol handlers ─────────────────────────────────────────────────────

def _handle_initialize(id_, params: dict) -> None:
    _ok(id_, {
        "protocolVersion": "2024-11-05",
        "serverInfo": {
            "name":    "lohnpro",
            "version": "1.0.0",
        },
        "capabilities": {
            "tools": {"listChanged": False},
        },
    })


def _handle_tools_list(id_, params: dict) -> None:
    tools_list = []
    for name, meta in TOOLS.items():
        tools_list.append({
            "name":        name,
            "description": meta["description"],
            "inputSchema": meta["inputSchema"],
        })
    _ok(id_, {"tools": tools_list})


def _handle_tools_call(id_, params: dict) -> None:
    name = params.get("name", "")
    args = params.get("arguments", {})

    if name not in TOOLS:
        _err(id_, -32601, f"Tool not found: {name}")
        return

    try:
        result = TOOLS[name]["fn"](args)
        _ok(id_, {
            "content": [
                {"type": "text", "text": json.dumps(result, ensure_ascii=False, indent=2)}
            ]
        })
    except Exception as exc:
        tb = traceback.format_exc()
        _err(id_, -32603, str(exc), tb)


def _handle_notifications_initialized(params: dict) -> None:
    # No response needed for notifications
    pass


# ── Main loop ─────────────────────────────────────────────────────────────────

def main() -> None:
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except json.JSONDecodeError as e:
            _err(None, -32700, f"Parse error: {e}")
            continue

        method = msg.get("method", "")
        id_    = msg.get("id")       # may be None for notifications
        params = msg.get("params", {}) or {}

        if method == "initialize":
            _handle_initialize(id_, params)
        elif method == "notifications/initialized":
            _handle_notifications_initialized(params)
        elif method == "tools/list":
            _handle_tools_list(id_, params)
        elif method == "tools/call":
            _handle_tools_call(id_, params)
        elif method == "ping":
            _ok(id_, {})
        elif id_ is not None:
            _err(id_, -32601, f"Method not found: {method}")
        # Unrecognised notifications are silently ignored


if __name__ == "__main__":
    main()
