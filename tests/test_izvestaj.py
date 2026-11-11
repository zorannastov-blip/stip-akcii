"""Извештајот: предупредување за покачена редовна цена пред акција."""

from __future__ import annotations

from datetime import date

from test_skladiste import D1, D2, citanje, red

from stipakcii.izvestaj import markdown, soberi
from stipakcii.postavki import Postavki
from stipakcii.skladiste import zapisi_den


def test_pokacena_redovna_cena_pred_akcija_se_oznacuva(tmp_path):
    zapisi_den(tmp_path, citanje([red("Леб", "40"), red("Сок", "80")]), D1)
    zapisi_den(
        tmp_path,
        citanje([red("Леб", "44", "30", do=date(2026, 11, 12)), red("Сок", "80", "60", vid="ЛОЈАЛНОСТ")]),
        D2,
    )
    p = soberi(tmp_path, Postavki(sledi=("сок",)), D2)
    leb = next(a for a in p.akcii if a["n"] == "Леб")
    sok = next(a for a in p.akcii if a["n"] == "Сок")

    assert leb["nov"] and leb["istek"]
    assert leb["pred"] == "редовната цена е покачена на 11.11. (од 40 ден на 44 ден)"
    assert not sok["pred"] and sok["kart"] and sok["sl"] and not leb["sl"]
    assert [(x["n"], x["pct"]) for x in p.promeni] == [("Леб", 10.0)]

    tekst = markdown(p)
    assert "## Нови денес" in tekst and "⚠ Леб" in tekst and "💳 Сок" in tekst


def test_sporedba_spojuva_ist_proizvod_megju_marketi():
    from stipakcii.sporedba import potpis, se_sovpagaat

    def isti(a, b):
        pa, pb = potpis(a), potpis(b)
        return bool(pa and pb and se_sovpagaat(pa, pb))

    assert isti("КАФЕ ЕСПРЕСО МЕЛЕНО ЛАВАЦА ОРО 250ГР", "ЛАВАЦА КАФЕ ОРО 250 ГР")
    assert isti("МЛЕКО БИТОЛСКО 1л 1.5%", "БИТОЛСКО МЛЕКО 1.5% ММ 1Л")
    assert isti("ЗЛАТЕН ДАБ ПИВО 0.33Л", "ПИВО ЗЛАТЕН ДАБ 330мл")
    # иста стока, друга количина или друг процент: НЕ е исто
    assert not isti("ЛАВАЦА КАФЕ ОРО 250 ГР", "ЛАВАЦА КАФЕ ОРО 500 ГР")
    assert not isti("МЛЕКО БИТОЛСКО 1л 1.5%", "БИТОЛСКО МЛЕКО 2.8% ММ 1Л")
    # друг вид од истиот бренд
    assert not isti("ЛАВАЦА КАФЕ ОРО 250 ГР", "ЛАВАЦА КАФЕ РОСА 250Г.")
    # кус назив не смее да се залепи за подолг
    assert not isti("НИВЕА КРЕМА 250 МЛ.", "ГЕЛ ЗА ТУШ НИВЕА 250мл КРЕМ КЕР")
    # без количина не се споредува
    assert potpis("НЕСКАФЕ КЛАСИК 3ВО1") is None
