"""Целото дневно читање, со лажна мрежа што ги враќа зачуваните примероци."""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest
from conftest import bajti, tekst

import stipakcii.citaci.http as http_modul
from stipakcii.__main__ import main
from stipakcii.skladiste import citaj_csv

PRAZNA_STRANA = (
    "<table><tr><th>Назив на стока</th><th>Продажна цена</th><th>Единечна цена</th>"
    "<th>Редовна цена</th></tr><tr><td colspan='9'>Нема податоци</td></tr></table>"
)
STOKOMAK_PRODAVNICI = (
    "<select name='org'><option value=''>Избери</option>"
    "<option value='5'>ШТИП</option><option value='6'>КУМАНОВО 2</option>"
    "<option value='7'>ПРОБИШТИП</option></select>"
)


def _odgovor(baranje: httpx.Request) -> httpx.Response:
    domakin, pateka = baranje.url.host, baranje.url.path
    parametri = dict(baranje.url.params)

    if domakin == "kam.mk":
        if pateka.endswith("LoadShopList"):
            return httpx.Response(200, json=json.loads(tekst("kam_shops.json")))
        if pateka.endswith(".pdf"):
            return httpx.Response(200, content=bajti("kam_pricelist.pdf"))
    if domakin == "ramstore.com.mk":
        if pateka.rstrip("/") == "/marketi":
            return httpx.Response(200, text=tekst("ramstore_marketi.html"))
        return httpx.Response(200, text=tekst("ramstore_store.html"))
    if domakin.endswith("proverkanaceni.mk"):
        if "org" not in parametri:
            if domakin.startswith("stokomak"):
                return httpx.Response(200, text=STOKOMAK_PRODAVNICI)
            return httpx.Response(200, text=tekst("proverkanaceni_stores.html"))
        if parametri.get("page") == "1":
            return httpx.Response(200, text=tekst("proverkanaceni_page.html"))
        return httpx.Response(200, text=PRAZNA_STRANA)
    if domakin == "kipper.mk":
        if pateka.endswith("admin-ajax.php"):
            # Како на 02.10.2026: Кипер Штип објавува нула производи.
            return httpx.Response(
                200, json={"draw": 1, "recordsTotal": 0, "recordsFiltered": 0, "data": []}
            )
        if pateka.rstrip("/").endswith("marketet"):
            return httpx.Response(200, text=tekst("kipper_marketet.html"))
        return httpx.Response(200, text=tekst("kipper_store.html"))
    return httpx.Response(404, text=f"непозната адреса {baranje.url}")


@pytest.fixture
def lazna_mreza(monkeypatch):
    vistinski = httpx.AsyncClient

    def so_lazen_prevoz(**kw):
        return vistinski(transport=httpx.MockTransport(_odgovor), **kw)

    monkeypatch.setattr(http_modul.httpx, "AsyncClient", so_lazen_prevoz)


def _proekt(tmp_path: Path, sledi: str = "") -> Path:
    (tmp_path / "postavki.toml").write_text(
        f'grad = "Штип"\nsledi = [{sledi}]\n[mreza]\npauza_sekundi = 0\n', encoding="utf-8"
    )
    return tmp_path


def test_dnevno_citanje_od_pocetok_do_kraj(tmp_path, lazna_mreza):
    koren = _proekt(tmp_path, sledi='"паштета", "грчки јогурт"')
    # Датум во рокот на акциите од примероците (28.09 - 21.10.2026).
    assert main(["--koren", str(koren), "--datum", "2026-10-02"]) == 0

    prodavnici = {
        (z["sinjir"], z["prodavnica_id"]): z for z in citaj_csv(koren / "podatoci/prodavnici.csv")
    }
    assert sorted(k for k, z in prodavnici.items() if z["status"] == "ok") == [
        ("kam", "46"),
        ("ramstore", "ramstore-shtip"),
        ("ramstore", "ramstore-shtip-luna"),
        ("stokomak", "5"),
        ("zito", "24"),
        ("zito", "75"),
        ("zito", "76"),
        ("zito", "89"),
    ]
    assert prodavnici[("kipper", "kipper-167-shtip")]["status"] == "prazen"
    assert prodavnici[("kam", "46")]["redovi"] == "33"

    aktivni = citaj_csv(koren / "podatoci/akcii/aktivni.csv")
    assert {z["sinjir"] for z in aktivni} == {"kam", "ramstore", "stokomak", "zito"}
    assert (koren / "podatoci/sostojba/ramstore-ramstore-shtip-luna.csv").exists()

    stranica = (koren / "docs/index.html").read_text(encoding="utf-8")
    assert "/*PODATOCI*/null" not in stranica and "Акции во Штип, 02.10.2026" in stranica
    vgradeno = stranica.split("const D = ", 1)[1].split(";\n", 1)[0].replace("<\\/", "</")
    podatoci = json.loads(vgradeno)
    assert len(podatoci["prodavnici"]) == 9
    # Истата акција во четирите продавници на Жито е ЕДНА ставка.
    pasteta = [a for a in podatoci["akcii"] if a["n"].endswith("МАЧЕ 100гр ЛОСОС") and a["sk"] == "zito"]
    assert len(pasteta) == 1 and pasteta[0]["site"] and len(pasteta[0]["p"]) == 4
    assert pasteta[0]["sl"] and not pasteta[0]["nov"]
    lojalnost = next(a for a in podatoci["akcii"] if a["sk"] == "ramstore" and a["kart"])
    assert lojalnost["c"] == 185.0 and lojalnost["r"] == 209.0

    izvestaj = (koren / "IZVESTAJ.md").read_text(encoding="utf-8")
    assert "## Твои производи" in izvestaj and "ПАШТЕТА МИГЛИОР" in izvestaj
    assert "⚪ објавен празен ценовник" in izvestaj

    # Втор ден со исти ценовници: ништо ново, ништо завршено.
    assert main(["--koren", str(koren), "--datum", "2026-10-03"]) == 0
    assert all(z["prv_pat"] <= "2026-10-02" for z in citaj_csv(koren / "podatoci/akcii/aktivni.csv"))
    assert not (koren / "podatoci/promeni/2026.csv").exists()


def test_koga_nisto_ne_se_procita_podatocite_ostanuvaat(tmp_path, monkeypatch):
    vistinski = httpx.AsyncClient
    monkeypatch.setattr(
        http_modul.httpx,
        "AsyncClient",
        lambda **kw: vistinski(
            transport=httpx.MockTransport(lambda b: httpx.Response(403)), **kw
        ),
    )
    koren = _proekt(tmp_path)
    assert main(["--koren", str(koren), "--datum", "2026-10-02"]) == 1
    assert not (koren / "podatoci").exists() and not (koren / "docs").exists()
