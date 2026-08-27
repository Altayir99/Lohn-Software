# Codex Auftrag: LohnPRO Payroll Engine — 2026 Law Update

**Repo root**: `c:\Users\firas\Documents\GitHub\pdf`

---

## Goal

`pdf_editor/core/sv_calculator.py` claims to implement "BMF PAP 2026" but its
constants are outdated. Your job is to:

1. **Research** the correct 2026 values from official German sources
2. **Update** the code with the verified values
3. **Write tests** that prove the calculations are correct

---

## Step 1 — Research (do this first)

Look up the correct 2026 values for each of the following from **official sources only**:

| What | Where to look |
|------|--------------|
| §32a EStG 2026 tariff (5 zones, all coefficients) | `gesetze-im-internet.de/estg/__32a.html` |
| BMF PAP 2026 full spec | `bundesfinanzministerium.de` — Schreiben November 2025, Anlage 1 |
| BBG KV/PV 2026 (monthly) | `tk.de` or `bundesregierung.de` |
| BBG RV/AV 2026 (monthly, check if East/West distinction still exists) | same |
| Grundfreibetrag 2026 | §32a EStG or BMF |
| SolZ Freigrenze 2026 | `§3 Abs.3 SolZG` |
| Minijob-Grenze 2026 (tied to Mindestlohn) | `minijob-zentrale.de` or §8 SGB IV |
| Midijob upper limit 2026 | same |
| KV-Durchschnittszusatzbeitrag 2026 (PAP figure for Vorsorgepauschale) | BMF PAP 2026 |
| WKP 2026 (Werbungskostenpauschbetrag) | §9a EStG |
| Kinderfreibetrag factor used in Vorsorgepauschale (`kfb_e = kfb * X`) | BMF PAP 2026 Anlage 1 |
| Minijob flat AG rates (KV, RV, Pauschsteuer, U1, U2, Insolvenz) | `minijob-zentrale.de` |

Add a `# source: <URL>` comment next to every constant you change.

---

## Step 2 — Files to Change

### `pdf_editor/core/sv_calculator.py`

#### Constants block (top of file)

- Rename `BBG_KV_2025` → `BBG_KV_2026`, update value
- Rename `BBG_RV_2025` → `BBG_RV_2026`, update value
- `BBG_RV_OST` — if BBG is now bundeseinheitlich in 2026, **delete** it
- `GRUNDFREIBETRAG` — update
- `WKP` — verify / update
- `MINIJOB_GRENZE` — update
- `MIDIJOB_GRENZE` — verify / update
- `KV_AVG_PAP` — verify / update
- All SV rates (`PV_WEST`, `PV_SACHSEN_AN/AG`, `RV_SATZ`, `AV_SATZ`, `KV_BASIS`,
  `PV_KINDERLOS`) — verify each; update if changed
- Minijob flat AG rates — verify / update

#### `_tarif_2026` function

Rewrite entirely with the correct 2026 §32a EStG zone boundaries and
formula coefficients. Keep the same function signature and `_floor()` pattern.

#### `_solz` function

Update the Freigrenze threshold and the Milderungszone crossover to 2026 values.

#### Remove Ost-BBG branch

If `BBG_RV_OST` is deleted, remove the `if bundesland == "ost": bbg_rv = BBG_RV_OST`
block from `calculate_full`. Leave the Sachsen PV path untouched.

#### Default parameters

```python
# calculate_full
bbg_kv: float = BBG_KV_2026,
bbg_rv: float = BBG_RV_2026,

# calculate_sv (legacy shim)
bbg_kv=BBG_KV_2026, bbg_rv=BBG_RV_2026,
```

#### Kinderfreibetrag factor in `_pap2026`

Find `kfb_e = kfb * 4_656` — verify the 2026 per-unit amount from BMF PAP 2026 and update.

#### Module docstring

Replace the constants table in the module docstring with the verified 2026 values.

---

### `pdf_editor/ui/pages/berechnung_page.py`

Find the Beschäftigungsart combo `items=` list (~line 211) and update the
threshold labels to match the new `MINIJOB_GRENZE` and `MIDIJOB_GRENZE`.

---

### `pdf_editor/ui/main_window.py`

Grep for `BBG_KV_2025` and `BBG_RV_2025` (~line 54, import + usages).
Rename all occurrences to `BBG_KV_2026` / `BBG_RV_2026`.

---

## Step 3 — Tests

Create `tests/test_sv_2026.py`. Cross-check expected values against the
official BMF Steuerrechner at `bmf-steuerrechner.de` (year 2026, Lohnsteuer).

Write at minimum these 6 tests using `calculate_full()`:

1. **BBG KV ceiling** — gross well above BBG KV → `sv.kv_sv_brutto == BBG_KV_2026`
2. **BBG RV ceiling** — gross well above BBG RV → `sv.rv_sv_brutto == BBG_RV_2026`
3. **Nullzone** — monthly gross at `GRUNDFREIBETRAG / 12` → `pap.lst_monat == 0`
4. **SolZ Freigrenze** — annual LSt just below new threshold → `solz_gesamt == 0`
5. **Minijob** — `grundgehalt=MINIJOB_GRENZE, beschaeftigung="minijob"` → AN-SV all zero, `netto == MINIJOB_GRENZE`
6. **Midijob boundary** — gross just above `MINIJOB_GRENZE`, `beschaeftigung="midijob"` → AN-SV reduced vs. Vollzeit

---

## Step 4 — Commit

```
fix(sv_calculator): update payroll engine to 2026 German law values

- BBG KV/PV and RV/AV updated to 2026 bundeseinheitlich values
- Grundfreibetrag updated to 2026 §32a EStG value
- _tarif_2026() rewritten with correct 2026 zone boundaries + coefficients
- _solz() Freigrenze updated to 2026 SolZG value
- MINIJOB_GRENZE updated to 2026 Mindestlohn-based value
- Renamed BBG_*_2025 → BBG_*_2026 throughout
- berechnung_page.py combo labels updated
- main_window.py imports updated
- tests/test_sv_2026.py added (6 BMF-verified test cases)
```

---

## Do NOT Change

- `overlay_editor.py`
- `payroll_fields.py`
- `employee_store.py`
- `pdf_importer.py`
- Any UI layout, theme, canvas, or form structure
- The midijob Faktor-F formula logic (only the `MINIJOB_GRENZE` constant feeds into it)
