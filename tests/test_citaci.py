"""Читачите врз зачувани примероци од вистинските ценовници (02.10.2026).

Никогаш врз живи сајтови. Ако изворот смени формат, овие тестови паѓаат по
освежување на примерокот - пред да тргне дневното читање.
"""

from __future__ import annotations

import json
from datetime import date
from decimal import Decimal

from conftest import bajti, tekst

from stipakcii.citaci import kam, kipper, proverkanaceni, ramstore
from stipakcii.citanje import vo_grad

ZITO = "https://zito.proverkanaceni.mk/"


def _vo_stip(prodavnici):
    return sorted(p.external_id for p in prodavnici if vo_grad(p, "Штип"))


def test_kam_prodavnici_i_cenovnik():
    prodavnici = kam.parse_shop_list(json.loads(tekst("kam_shops.json")))
    assert len(prodavnici) == 8
    assert _vo_stip(prodavnici) == ["46"]
    stip = next(p for p in prodavnici if p.external_id == "46")
    assert stip.source_url == "https://kam.mk/2026/10/02/46.pdf"

    redovi, datum, preskoknati, _ = kam.parse_pdf(bajti("kam_pricelist.pdf"), source="тест")
    assert len(redovi) == 33 and preskoknati == 0
    assert datum == date(2026, 10, 2)
    akcija = next(r for r in redovi if r.is_discount)
    assert (akcija.regular_price, akcija.discount_price, akcija.discount_pct) == (
        Decimal("129"),
        Decimal("110"),
        Decimal("15"),
    )
    assert (akcija.valid_from, akcija.valid_to) == (date(2026, 9, 28), date(2026, 10, 4))


def test_ramstor_prodavnici_i_cenovnik():
    prodavnici = ramstore.parse_store_index(tekst("ramstore_marketi.html"))
    assert len(prodavnici) == 36
    assert _vo_stip(prodavnici) == ["ramstore-shtip", "ramstore-shtip-luna"]

    redovi, datum, preskoknati, _ = ramstore.parse_pricelist(
        tekst("ramstore_store.html"), source="тест"
    )
    assert len(redovi) == 40 and preskoknati == 0
    assert datum == date(2026, 10, 2)
    assert sum(r.is_discount for r in redovi) == 2


def test_zito_prodavnici_i_strana():
    prodavnici = proverkanaceni.parse_store_select(
        tekst("proverkanaceni_stores.html"), base_url=ZITO
    )
    assert len(prodavnici) == 94
    # „73 Жито ПробиШтип Автобуска" НЕ е во Штип, а „76 Жито Штип Центар" е,
    # иако полето за град го чита како скопската општина Центар.
    assert _vo_stip(prodavnici) == ["24", "75", "76", "89"]

    redovi, preskoknati, _, ima_zaglavie = proverkanaceni.parse_page(
        tekst("proverkanaceni_page.html"), source="тест"
    )
    assert ima_zaglavie and len(redovi) == 100 and preskoknati == 0
    assert sum(r.is_discount for r in redovi) == 18


def test_kiper_prodavnici_i_redovi():
    prodavnici = kipper.parse_store_index(tekst("kipper_marketet.html"))
    assert len(prodavnici) == 19
    assert _vo_stip(prodavnici) == ["kipper-167-shtip"]
    assert kipper.find_post_id(tekst("kipper_store.html")) == "23018"

    surovi = json.loads(tekst("kipper_products.json"))["data"]
    redovi, preskoknati, _ = kipper._parse_rows(surovi)
    assert len(redovi) == 40 and preskoknati == 0
    assert sum(r.is_discount for r in redovi) == 17
