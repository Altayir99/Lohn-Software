"""Regression tests for the verified German payroll values for 2026.

Official references:
- BMF PAP 2026 and check table:
  https://www.bundesfinanzministerium.de/Content/DE/Downloads/Steuern/Steuerarten/Lohnsteuer/Programmablaufplan/2025-11-12-PAP-2026-anlage-1.pdf?__blob=publicationFile&v=2
- BMF 2026 payroll tax calculator:
  https://www.bmf-steuerrechner.de/bl/bl2026/eingabeformbl2026.xhtml
"""

import unittest

from pdf_editor.core.sv_calculator import (
    BBG_KV_2026,
    BBG_RV_2026,
    GRUNDFREIBETRAG,
    KV_AVG_PAP,
    MIDIJOB_GRENZE,
    MINIJOB_GRENZE,
    SOLZ_FREIGRENZE,
    calculate_full,
)


class TestSV2026(unittest.TestCase):
    def test_kv_sv_brutto_is_capped_at_2026_bbg(self) -> None:
        result = calculate_full(grundgehalt=20_000, z_pct=KV_AVG_PAP)

        self.assertEqual(BBG_KV_2026, 5_812.50)
        self.assertEqual(result.sv.kv_sv_brutto, 5_812.50)

    def test_rv_sv_brutto_is_capped_at_2026_bbg(self) -> None:
        result = calculate_full(grundgehalt=20_000, z_pct=KV_AVG_PAP)

        self.assertEqual(BBG_RV_2026, 8_450.00)
        self.assertEqual(result.sv.rv_sv_brutto, 8_450.00)

    def test_monthly_gross_at_grundfreibetrag_is_in_nullzone(self) -> None:
        self.assertEqual(GRUNDFREIBETRAG, 12_348)
        result = calculate_full(
            grundgehalt=GRUNDFREIBETRAG / 12,
            z_pct=KV_AVG_PAP,
        )

        self.assertEqual(result.pap.lst_monat, 0)

    def test_solz_is_zero_just_below_2026_freigrenze(self) -> None:
        # This gross produces annual LSt of 20,349 EUR with the 2026 PAP inputs.
        self.assertEqual(SOLZ_FREIGRENZE, 20_350)
        result = calculate_full(grundgehalt=7_679.99, z_pct=KV_AVG_PAP)

        self.assertEqual(result.pap.lst_jahr, SOLZ_FREIGRENZE - 1)
        self.assertEqual(result.solz_gesamt, 0)

    def test_minijob_at_2026_limit_has_no_employee_sv_or_tax(self) -> None:
        self.assertEqual(MINIJOB_GRENZE, 603.00)
        result = calculate_full(
            grundgehalt=MINIJOB_GRENZE,
            beschaeftigung="minijob",
        )

        self.assertEqual(result.sv.kv_beitrag_an, 0)
        self.assertEqual(result.sv.rv_beitrag_an, 0)
        self.assertEqual(result.sv.av_beitrag_an, 0)
        self.assertEqual(result.sv.pv_beitrag_an, 0)
        self.assertEqual(result.sv.sv_an_gesamt, 0)
        self.assertEqual(result.sv.sv_ag_gesamt, 187.95)
        self.assertEqual(result.netto, MINIJOB_GRENZE)

    def test_midijob_just_above_minijob_limit_reduces_employee_sv(self) -> None:
        self.assertEqual(MIDIJOB_GRENZE, 2_000.00)
        self.assertEqual(KV_AVG_PAP, 2.90)
        gross = MINIJOB_GRENZE + 1.00
        midijob = calculate_full(
            grundgehalt=gross,
            beschaeftigung="midijob",
            z_pct=KV_AVG_PAP,
        )
        vollzeit = calculate_full(
            grundgehalt=gross,
            beschaeftigung="vollzeit",
            z_pct=KV_AVG_PAP,
        )

        self.assertLess(midijob.sv.sv_an_gesamt, vollzeit.sv.sv_an_gesamt)


if __name__ == "__main__":
    unittest.main()
