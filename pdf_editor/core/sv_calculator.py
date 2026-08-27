"""
sv_calculator.py
================
Full payroll calculation engine — BMF PAP 2026 + SV (§32a EStG, SGB IV/XI).

Constants (2026):
    BBG KV/PV:  5.812,50 €/month
    BBG RV/AV:  8.450,00 €/month (bundeseinheitlich)
    RV:  18,60 % (9,30 % AN)
    AV:   2,60 % (1,30 % AN)
    KV base: 14,60 %
    PV:   3,60 % außerhalb Sachsens (1,80 % AN), Sachsen AN: 2,30 %, AG: 1,30 %
    PV kinderlos: +0,60 % AN
    Grundfreibetrag: 12.348 €
    WKP: 1.230 €/Jahr
    KV-Durchschnitt PAP: 2,90 %
    SolZ-Freigrenze: 20.350 € Jahreslohnsteuer
    Kinderfreibetragseinheit: 4.878 €
    Minijob: bis 603,00 €; Midijob: 603,01–2.000,00 €
    Minijob AG: KV 13 %, RV 15 %, Pauschsteuer 2 %, U1 0,80 %, U2 0,22 %,
                Insolvenzgeldumlage 0,15 %
"""
from __future__ import annotations
from dataclasses import dataclass, field

# ── 2026 defaults ────────────────────────────────────────────────────────
BBG_KV_2026   = 5_812.50  # source: https://www.bundesregierung.de/breg-de/suche/beitragsgemessungsgrenzen-2386514
BBG_RV_2026   = 8_450.00  # source: https://www.bundesregierung.de/breg-de/suche/beitragsgemessungsgrenzen-2386514
KV_BASIS      = 14.60     # source: https://www.bundesgesundheitsministerium.de/beitraege/seite
PV_WEST       = 3.60      # source: https://www.bundesgesundheitsministerium.de/themen/pflege/online-ratgeber-pflege/die-pflegeversicherung/finanzierung
PV_SACHSEN_AN = 2.30      # source: https://www.bundesgesundheitsministerium.de/themen/pflege/online-ratgeber-pflege/die-pflegeversicherung/finanzierung
PV_SACHSEN_AG = 1.30      # source: https://www.bundesgesundheitsministerium.de/themen/pflege/online-ratgeber-pflege/die-pflegeversicherung/finanzierung
RV_SATZ       = 18.60     # source: https://www.deutsche-rentenversicherung.de/DRV/DE/Experten/Zahlen-und-Fakten/Werte-der-Rentenversicherung/werte-der-rentenversicherung
AV_SATZ       = 2.60      # source: https://www.deutsche-rentenversicherung.de/DRV/DE/Experten/Zahlen-und-Fakten/Werte-der-Rentenversicherung/werte-der-rentenversicherung
PV_KINDERLOS  = 0.60      # source: https://www.bundesgesundheitsministerium.de/themen/pflege/online-ratgeber-pflege/die-pflegeversicherung/finanzierung
PV_BASE_AN    = 1.80      # source: https://www.bundesgesundheitsministerium.de/themen/pflege/online-ratgeber-pflege/die-pflegeversicherung/finanzierung
GRUNDFREIBETRAG = 12_348  # source: https://www.gesetze-im-internet.de/estg/__32a.html
WKP              = 1_230  # source: https://www.gesetze-im-internet.de/estg/__9a.html
KV_AVG_PAP       = 2.90   # source: https://www.bundesgesundheitsministerium.de/beitraege/seite
SOLZ_FREIGRENZE  = 20_350  # source: https://www.gesetze-im-internet.de/solzg_1995/__3.html
SOLZ_MILDERUNGSZONE_ENDE = 37_838.28125  # source: https://www.gesetze-im-internet.de/solzg_1995/__4.html
KINDERFREIBETRAG_EINHEIT = 4_878  # source: https://www.bundesfinanzministerium.de/Content/DE/Downloads/Steuern/Steuerarten/Lohnsteuer/Programmablaufplan/2025-11-12-PAP-2026-anlage-1.pdf?__blob=publicationFile&v=2

# ── Minijob / Midijob (Übergangsbereich) 2026 ────────────────────────────
MINIJOB_GRENZE     = 603.00    # source: https://www.minijob-zentrale.de/DE/die-minijobs/minijob-mit-verdienstgrenze
MIDIJOB_GRENZE     = 2_000.00  # source: https://www.minijob-zentrale.de/DE/die-minijobs/minijob-mit-verdienstgrenze
MINIJOB_KV_AG      = 13.0      # source: https://magazin.minijob-zentrale.de/minijob-beitraege-2026/
MINIJOB_RV_AG      = 15.0      # source: https://magazin.minijob-zentrale.de/minijob-beitraege-2026/
MINIJOB_PAUSCH_ST  = 2.0       # source: https://magazin.minijob-zentrale.de/minijob-beitraege-2026/
MINIJOB_U1         = 0.80      # source: https://magazin.minijob-zentrale.de/minijob-beitraege-2026/
MINIJOB_U2         = 0.22      # source: https://magazin.minijob-zentrale.de/minijob-beitraege-2026/
MINIJOB_INSOLVENZ  = 0.15      # source: https://magazin.minijob-zentrale.de/minijob-beitraege-2026/


@dataclass
class PAPResult:
    """Result of the BMF PAP 2026 Lohnsteuer calculation."""
    lst_monat:  float   # Lohnsteuer pro Monat
    solz_monat: float   # Solidaritätszuschlag pro Monat
    lst_jahr:   float
    solz_jahr:  float
    zve:        float   # zu versteuerndes Einkommen (Jahresbasis)
    vps:        float   # Vorsorgepauschale
    vps_rv:     float
    vps_kv:     float
    vps_pv:     float


@dataclass
class SVResult:
    """Social insurance AN contributions for one month."""
    kv_sv_brutto:  float
    kv_beitrag_an: float
    kv_beitrag_ag: float
    rv_sv_brutto:  float
    rv_beitrag_an: float
    rv_beitrag_ag: float
    av_sv_brutto:  float
    av_beitrag_an: float
    av_beitrag_ag: float
    pv_sv_brutto:  float
    pv_beitrag_an: float
    pv_beitrag_ag: float
    sv_an_gesamt:  float
    sv_ag_gesamt:  float


@dataclass
class LohnResult:
    """Complete monthly payroll result."""
    # Input echo
    grundgehalt:     float
    ueberstunden:    float
    sachbezug:       float
    einmalzahlung:   float
    fahrgeld:        float
    vwl_ag:          float
    vorschuss:       float
    vwl_an:          float
    gesamtbrutto:    float
    lfd_brutto:      float   # ohne Einmalzahlung

    # SV
    sv:              SVResult
    sv_einmal_an:    float   # SV auf Einmalzahlung (AN)
    sv_einmal_ag:    float

    # Steuer
    pap:             PAPResult
    lst_einmal:      float   # LSt Fünftelregelung auf Einmalzahlung
    solz_einmal:     float
    kist_lfd:        float
    kist_einmal:     float
    kist_satz:       float

    # Totals
    lst_gesamt:      float
    solz_gesamt:     float
    kist_gesamt:     float
    steuer_gesamt:   float
    abzuege_gesamt:  float
    netto:           float


# ── Internal helpers ──────────────────────────────────────────────────────────

def _r2(x: float) -> float:
    return round(x, 2)

def _floor(x: float) -> float:
    import math
    return math.floor(x)

# source: https://www.gesetze-im-internet.de/estg/__32a.html
def _tarif_2026(x: float, gf: float = GRUNDFREIBETRAG) -> float:
    """§32a EStG Einkommensteuertarif 2026."""
    if x <= gf:
        return 0.0
    if x <= 17_799:
        y = (x - gf) / 1e4
        return _floor((914.51 * y + 1_400) * y)
    if x <= 69_878:
        z = (x - 17_799) / 1e4
        return _floor((173.10 * z + 2_397) * z + 1_034.87)
    if x <= 277_825:
        return _floor(0.42 * x - 11_135.63)
    return _floor(0.45 * x - 19_470.38)


def _solz(lst_jahr: float) -> float:
    """SolZ — Freigrenze and Milderungszone for 2026."""
    if lst_jahr <= SOLZ_FREIGRENZE:
        return 0.0
    raw = min(lst_jahr * 0.055, (lst_jahr - SOLZ_FREIGRENZE) * 0.119)
    if lst_jahr >= SOLZ_MILDERUNGSZONE_ENDE:
        raw = lst_jahr * 0.055
    return _floor(raw)


def _pap2026(
    brutto_m:  float,
    stkl:      int,
    kfb:       float   = 0.0,
    jfreib:    float   = 0.0,
    jhinzu:    float   = 0.0,
    pvz:       bool    = False,   # kinderlos
    pvs:       bool    = False,   # Sachsen
    rv_an:     bool    = True,
    bbg_kv_j:  float   = BBG_KV_2026 * 12,
    bbg_rv_j:  float   = BBG_RV_2026 * 12,
    kv_avg:    float   = KV_AVG_PAP,
    gf:        float   = GRUNDFREIBETRAG,
    wkp:       float   = WKP,
) -> PAPResult:
    """BMF PAP 2026 Lohnsteuerberechnung (Jahresmethode)."""
    jre4 = brutto_m * 12

    # Vorsorgepauschale
    vps_rv = _floor(min(jre4, bbg_rv_j) * 0.093) if rv_an else 0.0
    kv_an_pap = 0.073 + kv_avg / 2 / 100
    vps_kv = _floor(min(jre4, bbg_kv_j) * kv_an_pap)
    if pvs:
        pv_pap = PV_SACHSEN_AN / 100
    else:
        pv_pap = PV_WEST / 100 / 2
    if pvz:
        pv_pap += PV_KINDERLOS / 100
    vps_pv = _floor(min(jre4, bbg_kv_j) * pv_pap)
    vps_real = vps_rv + vps_kv + vps_pv

    # Mindest-VPS §39b Abs.2 Satz 5 EStG (SK 1–4)
    mvsp = min(1_900, _floor(jre4 * 0.12)) if stkl in (1, 2, 3, 4) else 0
    vps = max(vps_real, mvsp)

    wkp_a = wkp if stkl in (1, 2, 3, 4) else 0
    sap   = 72 if stkl == 3 else (36 if stkl in (1, 2, 4) else 0)
    kfb_e = kfb * KINDERFREIBETRAG_EINHEIT

    zve = max(0, _floor(jre4 - wkp_a - sap - vps - kfb_e - jfreib + jhinzu))

    # Steuer nach SK
    if stkl == 3:
        st = _tarif_2026(zve / 2, gf) * 2
    elif stkl == 5:
        st = max(0, _tarif_2026(zve + gf + wkp_a + sap, gf)
                  - _tarif_2026(gf + wkp_a + sap, gf))
    elif stkl == 6:
        st = _tarif_2026(zve + gf, gf)
    else:
        st = _tarif_2026(zve, gf)

    solz_j = _solz(st)

    return PAPResult(
        lst_monat  = _floor(st / 12),
        solz_monat = _floor(solz_j / 12),
        lst_jahr   = st,
        solz_jahr  = solz_j,
        zve        = zve,
        vps        = vps,
        vps_rv     = vps_rv,
        vps_kv     = vps_kv,
        vps_pv     = vps_pv,
    )


def _fuenftel(
    zve_base: float, einmal: float, stkl: int,
    gf: float = GRUNDFREIBETRAG, wkp: float = WKP,
) -> tuple[float, float]:
    """§39b Abs.3 EStG — Fünftelregelung für Einmalzahlungen."""
    def _lst_sk(z: float) -> float:
        if stkl == 3:
            return _tarif_2026(z / 2, gf) * 2
        sap = 72 if stkl == 3 else (36 if stkl in (1, 2, 4) else 0)
        if stkl == 5:
            return max(0, _tarif_2026(z + gf + wkp + sap, gf)
                          - _tarif_2026(gf + wkp + sap, gf))
        if stkl == 6:
            return _tarif_2026(z + gf, gf)
        return _tarif_2026(z, gf)

    z5 = max(0, _floor(zve_base + einmal / 5))
    lst_sb = max(0, (_lst_sk(z5) - _lst_sk(zve_base)) * 5)
    solz_sb = _solz(lst_sb) if lst_sb > SOLZ_FREIGRENZE else 0.0
    return lst_sb, solz_sb


# ── Public API ────────────────────────────────────────────────────────────────

def calculate_full(
    grundgehalt:   float,
    stkl:          int   = 1,
    kfb:           float = 0.0,
    kk_pct:        float = KV_BASIS,
    z_pct:         float = 2.20,
    pv_kinderlos:  bool  = False,
    rv_pflicht:    bool  = True,
    av_pflicht:    bool  = True,
    bundesland:    str   = "west",        # "west" | "ost" | "sachsen"
    kist_satz:     float = 0.0,           # 0, 0.08, 0.09
    jfreib:        float = 0.0,
    jhinzu:        float = 0.0,
    ueberstunden:  float = 0.0,
    sachbezug:     float = 0.0,
    einmalzahlung: float = 0.0,
    fahrgeld:      float = 0.0,
    vwl_ag:        float = 0.0,
    vorschuss:     float = 0.0,
    vwl_an:        float = 0.0,
    bbg_kv:        float = BBG_KV_2026,
    bbg_rv:        float = BBG_RV_2026,
    kv_avg:        float = KV_AVG_PAP,
    gf:            float = GRUNDFREIBETRAG,
    wkp:           float = WKP,
    beschaeftigung: str  = "vollzeit",   # "vollzeit" | "minijob" | "midijob"
) -> LohnResult:
    """
    Full monthly payroll calculation: SV + PAP 2026 LSt + SolZ + KiSt.

    Returns a LohnResult with every relevant figure.
    """
    pvz = pv_kinderlos
    pvs = bundesland == "sachsen"

    lfd_b     = grundgehalt + ueberstunden + sachbezug
    gesamt_b  = lfd_b + einmalzahlung + fahrgeld + vwl_ag

    # ── Minijob: flat AG rates, zero AN contributions ─────────────────────
    if beschaeftigung == "minijob":
        kv_ag = _r2(lfd_b * MINIJOB_KV_AG / 100)
        rv_ag = _r2(lfd_b * MINIJOB_RV_AG / 100)
        pausch_st = _r2(lfd_b * MINIJOB_PAUSCH_ST / 100)
        u1 = _r2(lfd_b * MINIJOB_U1 / 100)
        u2 = _r2(lfd_b * MINIJOB_U2 / 100)
        insolvenz = _r2(lfd_b * MINIJOB_INSOLVENZ / 100)
        ag_total = _r2(kv_ag + rv_ag + pausch_st + u1 + u2 + insolvenz)

        sv_result = SVResult(
            kv_sv_brutto=lfd_b,  kv_beitrag_an=0.0,   kv_beitrag_ag=kv_ag,
            rv_sv_brutto=lfd_b,  rv_beitrag_an=0.0,   rv_beitrag_ag=rv_ag,
            av_sv_brutto=lfd_b,  av_beitrag_an=0.0,   av_beitrag_ag=0.0,
            pv_sv_brutto=lfd_b,  pv_beitrag_an=0.0,   pv_beitrag_ag=0.0,
            sv_an_gesamt=0.0,    sv_ag_gesamt=ag_total,
        )
        # Minijob: no income tax (AG pays 2% Pauschalsteuer already in ag_total)
        pap = PAPResult(lst_monat=0, solz_monat=0, lst_jahr=0, solz_jahr=0,
                        zve=0, vps=0, vps_rv=0, vps_kv=0, vps_pv=0)
        netto = _r2(gesamt_b - vorschuss - vwl_an)
        return LohnResult(
            grundgehalt=grundgehalt, ueberstunden=ueberstunden,
            sachbezug=sachbezug, einmalzahlung=einmalzahlung,
            fahrgeld=fahrgeld, vwl_ag=vwl_ag,
            vorschuss=vorschuss, vwl_an=vwl_an,
            gesamtbrutto=gesamt_b, lfd_brutto=lfd_b,
            sv=sv_result, sv_einmal_an=0.0, sv_einmal_ag=0.0,
            pap=pap, lst_einmal=0.0, solz_einmal=0.0,
            kist_lfd=0.0, kist_einmal=0.0, kist_satz=0.0,
            lst_gesamt=0.0, solz_gesamt=0.0, kist_gesamt=0.0,
            steuer_gesamt=0.0, abzuege_gesamt=_r2(vorschuss + vwl_an),
            netto=netto,
        )

    # ── Midijob (Übergangsbereich): reduced AN-SV, full AG-SV ─────────────
    if beschaeftigung == "midijob" and lfd_b <= MIDIJOB_GRENZE:
        # Gesamtbeitragssatz (alle SV-Zweige)
        kv_ges_pct  = (kk_pct + z_pct) / 100
        rv_ges_pct  = RV_SATZ / 100
        av_ges_pct  = AV_SATZ / 100
        pv_ges_pct  = PV_WEST / 100
        gesamt_sv_pct = kv_ges_pct + rv_ges_pct + av_ges_pct + pv_ges_pct

        # Faktor F = 28% / Gesamtbeitragssatz
        F = 0.28 / gesamt_sv_pct

        # Beitragspflichtige Einnahme (reduced basis for AN)
        T = MIDIJOB_GRENZE  # Obergrenze
        G = MINIJOB_GRENZE  # Untergrenze
        be = _r2(F * G + (T / (T - G)) * (lfd_b - G) * (1 - F) + G * (1 - F))
        # Clamp: can't exceed actual brutto
        be = min(be, lfd_b)

        # AG pays full SV on the actual brutto
        sv_bkv_ag = min(lfd_b, bbg_kv)
        sv_brv_ag = min(lfd_b, bbg_rv)
        kv_ag = _r2(sv_bkv_ag * kv_ges_pct / 2)
        rv_ag = _r2(sv_brv_ag * rv_ges_pct / 2)
        av_ag = _r2(sv_brv_ag * av_ges_pct / 2)
        pv_ag_s = PV_SACHSEN_AG / 100 if pvs else PV_WEST / 100 / 2
        pv_ag = _r2(sv_bkv_ag * pv_ag_s)

        # AN pays on reduced basis (Gesamtbeitrag minus AG-Anteil)
        sv_bkv_an = min(be, bbg_kv)
        sv_brv_an = min(be, bbg_rv)
        # Total SV on reduced basis, then subtract AG share
        kv_gesamt = _r2(sv_bkv_an * kv_ges_pct)
        kv_an = max(0.0, _r2(kv_gesamt - kv_ag))
        rv_gesamt = _r2(sv_brv_an * rv_ges_pct)
        rv_an = max(0.0, _r2(rv_gesamt - rv_ag))
        av_gesamt = _r2(sv_brv_an * av_ges_pct)
        av_an = max(0.0, _r2(av_gesamt - av_ag))
        pv_gesamt = _r2(sv_bkv_an * pv_ges_pct)
        pv_an = max(0.0, _r2(pv_gesamt - pv_ag))
        if pvz:
            pv_an = _r2(pv_an + sv_bkv_an * PV_KINDERLOS / 100)

        sv_an_tot = _r2(kv_an + rv_an + av_an + pv_an)
        sv_ag_tot = _r2(kv_ag + rv_ag + av_ag + pv_ag)

        sv_result = SVResult(
            kv_sv_brutto=sv_bkv_an, kv_beitrag_an=kv_an, kv_beitrag_ag=kv_ag,
            rv_sv_brutto=sv_brv_an, rv_beitrag_an=rv_an, rv_beitrag_ag=rv_ag,
            av_sv_brutto=sv_brv_an, av_beitrag_an=av_an, av_beitrag_ag=av_ag,
            pv_sv_brutto=sv_bkv_an, pv_beitrag_an=pv_an, pv_beitrag_ag=pv_ag,
            sv_an_gesamt=sv_an_tot,  sv_ag_gesamt=sv_ag_tot,
        )
        # Midijob: normal income tax calculation (LSt calculated on full brutto)
        # Fall through to LSt below using this sv_result
    else:
    # ── Vollzeit: standard SV calculation ─────────────────────────────────
        sv_bkv = min(lfd_b, bbg_kv)
        sv_brv = min(lfd_b, bbg_rv)

        kv_an_s = (kk_pct + z_pct) / 2 / 100
        kv_ag_s = kv_an_s
        kv_an = _r2(sv_bkv * kv_an_s)
        kv_ag = _r2(sv_bkv * kv_ag_s)

        if pvs:
            pv_an_s = PV_SACHSEN_AN / 100
            pv_ag_s = PV_SACHSEN_AG / 100
        else:
            pv_an_s = PV_WEST / 100 / 2
            pv_ag_s = PV_WEST / 100 / 2
        if pvz:
            pv_an_s += PV_KINDERLOS / 100

        pv_an = _r2(sv_bkv * pv_an_s)
        pv_ag = _r2(sv_bkv * pv_ag_s)

        rv_an = _r2(sv_brv * RV_SATZ / 2 / 100) if rv_pflicht else 0.0
        rv_ag = rv_an
        av_an = _r2(sv_brv * AV_SATZ / 2 / 100) if av_pflicht else 0.0
        av_ag = av_an

        # ── SV on Einmalzahlung (BBG-Restbetrag) ─────────────────────────────
        sb_kv = max(0.0, min(einmalzahlung, bbg_kv - sv_bkv))
        sb_rv = max(0.0, min(einmalzahlung, bbg_rv - sv_brv))
        sb_kv_an = _r2(sb_kv * kv_an_s);   sb_kv_ag = sb_kv_an
        sb_pv_an = _r2(sb_kv * pv_an_s);   sb_pv_ag = _r2(sb_kv * pv_ag_s)
        sb_rv_an = _r2(sb_rv * RV_SATZ/2/100) if rv_pflicht else 0.0; sb_rv_ag = sb_rv_an
        sb_av_an = _r2(sb_rv * AV_SATZ/2/100) if av_pflicht else 0.0; sb_av_ag = sb_av_an
        sv_einmal_an = _r2(sb_kv_an + sb_pv_an + sb_rv_an + sb_av_an)
        sv_einmal_ag = _r2(sb_kv_ag + sb_pv_ag + sb_rv_ag + sb_av_ag)

        sv_an_tot = _r2(kv_an + pv_an + rv_an + av_an + sv_einmal_an)
        sv_ag_tot = _r2(kv_ag + pv_ag + rv_ag + av_ag + sv_einmal_ag)

        sv_result = SVResult(
            kv_sv_brutto=sv_bkv,   kv_beitrag_an=kv_an,   kv_beitrag_ag=kv_ag,
            rv_sv_brutto=sv_brv,   rv_beitrag_an=rv_an,   rv_beitrag_ag=rv_ag,
            av_sv_brutto=sv_brv,   av_beitrag_an=av_an,   av_beitrag_ag=av_ag,
            pv_sv_brutto=sv_bkv,   pv_beitrag_an=pv_an,   pv_beitrag_ag=pv_ag,
            sv_an_gesamt=sv_an_tot, sv_ag_gesamt=sv_ag_tot,
        )

    # ── BMF PAP 2026 ──────────────────────────────────────────────────────
    pap = _pap2026(
        brutto_m=lfd_b, stkl=stkl, kfb=kfb,
        jfreib=jfreib, jhinzu=jhinzu,
        pvz=pvz, pvs=pvs, rv_an=rv_pflicht,
        bbg_kv_j=bbg_kv*12, bbg_rv_j=bbg_rv*12,
        kv_avg=kv_avg, gf=gf, wkp=wkp,
    )

    # ── Fünftelregelung ───────────────────────────────────────────────────
    lst_einmal, solz_einmal = (0.0, 0.0)
    if einmalzahlung > 0:
        lst_einmal, solz_einmal = _fuenftel(pap.zve, einmalzahlung, stkl, gf, wkp)

    # ── KiSt ──────────────────────────────────────────────────────────────
    kist_lfd   = _r2(pap.lst_monat * kist_satz)
    kist_einmal= _r2(lst_einmal    * kist_satz)
    kist_ges   = _r2(kist_lfd + kist_einmal)

    lst_ges   = _r2(pap.lst_monat + lst_einmal)
    solz_ges  = _r2(pap.solz_monat + solz_einmal)
    steuer_ges= _r2(lst_ges + solz_ges + kist_ges)
    sv_an_tot = sv_result.sv_an_gesamt
    # For Midijob, no Einmalzahlung SV split — keep simple
    sv_einmal_an_val = 0.0 if beschaeftigung == "midijob" else (sv_einmal_an if 'sv_einmal_an' in dir() else 0.0)
    sv_einmal_ag_val = 0.0 if beschaeftigung == "midijob" else (sv_einmal_ag if 'sv_einmal_ag' in dir() else 0.0)
    abzuege   = _r2(sv_an_tot + steuer_ges + vorschuss + vwl_an)
    netto     = _r2(gesamt_b - abzuege)

    return LohnResult(
        grundgehalt=grundgehalt, ueberstunden=ueberstunden,
        sachbezug=sachbezug, einmalzahlung=einmalzahlung,
        fahrgeld=fahrgeld, vwl_ag=vwl_ag,
        vorschuss=vorschuss, vwl_an=vwl_an,
        gesamtbrutto=gesamt_b, lfd_brutto=lfd_b,
        sv=sv_result, sv_einmal_an=sv_einmal_an_val, sv_einmal_ag=sv_einmal_ag_val,
        pap=pap, lst_einmal=lst_einmal, solz_einmal=solz_einmal,
        kist_lfd=kist_lfd, kist_einmal=kist_einmal, kist_satz=kist_satz,
        lst_gesamt=lst_ges, solz_gesamt=solz_ges, kist_gesamt=kist_ges,
        steuer_gesamt=steuer_ges, abzuege_gesamt=abzuege, netto=netto,
    )


# ── Legacy helpers (kept for backward compat) ─────────────────────────────────

def calculate_sv(brutto, kk_pct, z_pct, pv_kinder_kz,
                 bbg_kv=BBG_KV_2026, bbg_rv=BBG_RV_2026):
    """Legacy: SV-only calculation (used by older calc panel path)."""
    r = calculate_full(
        grundgehalt=brutto, kk_pct=kk_pct, z_pct=z_pct,
        pv_kinderlos=(pv_kinder_kz == 0),
        bbg_kv=bbg_kv, bbg_rv=bbg_rv,
    )
    from dataclasses import make_dataclass
    # Return an object with the old field names for backward compat
    class _Compat:
        kv_sv_brutto = r.sv.kv_sv_brutto
        kv_beitrag_an = r.sv.kv_beitrag_an
        rv_sv_brutto = r.sv.rv_sv_brutto
        rv_beitrag_an = r.sv.rv_beitrag_an
        av_sv_brutto = r.sv.av_sv_brutto
        av_beitrag_an = r.sv.av_beitrag_an
        pv_sv_brutto = r.sv.pv_sv_brutto
        pv_beitrag_an = r.sv.pv_beitrag_an
        sv_abzuege_ges = r.sv.sv_an_gesamt
    return _Compat()


def sum_lohnarten_betraege(user_values: dict) -> float:
    from pdf_editor.core.number_utils import parse_de
    total = 0.0
    for fid in ("betrag_lohnart", "betrag_row2", "betrag_row3",
                 "betrag_row4", "betrag_row5"):
        val = user_values.get(fid, "").strip()
        if val:
            total += parse_de(val)
    return round(total, 2)
