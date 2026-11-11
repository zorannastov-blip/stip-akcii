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
