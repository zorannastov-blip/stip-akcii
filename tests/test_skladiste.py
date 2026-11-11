"""Историјата: што е нова акција, што е завршена, што е променета цена."""

from __future__ import annotations

from datetime import date
from decimal import Decimal as D

from stipakcii.citaci.base import RawPriceRow
from stipakcii.citanje import OK, PADNA, IshodProdavnica, IshodSinjir
from stipakcii.skladiste import citaj_csv, od_cenovnik, zapisi_den

D1, D2, D3 = date(2026, 11, 10), date(2026, 11, 11), date(2026, 11, 12)


def red(naziv, redovna, so_popust=None, od=None, do=None, vid="акција"):
    return RawPriceRow(
        name=naziv,
        description="опис",
        sale_price=D(so_popust) if so_popust else D(redovna),
        regular_price=D(redovna),
        discount_price=D(so_popust) if so_popust else None,
        promo_type_raw=vid if so_popust else None,
        valid_from=od,
        valid_to=do,
    )


def citanje(redovi, status=OK, pid="1"):
    p = IshodProdavnica("kam", "КАМ", pid, f"Штип - {pid}", status=status, redovi=redovi)
    return [IshodSinjir("kam", "КАМ", prodavnici=[p])]


def aktivni(koren):
    return {z["naziv"]: z for z in citaj_csv(koren / "akcii" / "aktivni.csv")}


def test_popust_sto_ne_ja_namaluva_cenata_ne_e_akcija():
    assert not od_cenovnik(red("А", "100", "100")).e_akcija
    assert not od_cenovnik(red("А", "100", "120")).e_akcija
    akcija = od_cenovnik(red("А", "200", "150"))
    assert akcija.e_akcija and akcija.popust_pct == D("25.0") and akcija.cena == D("150")


def test_prvo_citanje_ne_prijavuva_se_kako_novo(tmp_path):
    zbir = zapisi_den(tmp_path, citanje([red("Кафе", "200", "150", date(2026, 11, 3))]), D1)
    assert (zbir.akcii, zbir.novi_akcii) == (1, 0)
    # Почетокот го кажува изворот, не денот кога ние првпат сме погледнале.
    assert aktivni(tmp_path)["Кафе"]["prv_pat"] == "2026-11-03"


def test_nova_akcija_zavrsena_akcija_i_promena_na_cena(tmp_path):
    zapisi_den(
        tmp_path,
        citanje([red("Кафе", "200", "150"), red("Млеко", "60"), red("Леб", "40")]),
        D1,
    )
    zbir = zapisi_den(
        tmp_path,
        citanje([red("Кафе", "200"), red("Млеко", "66"), red("Леб", "40", "30")]),
        D2,
    )
    assert (zbir.novi_akcii, zbir.zavrseni_akcii, zbir.promeni_na_ceni) == (1, 1, 1)

    assert aktivni(tmp_path)["Леб"]["prv_pat"] == "2026-11-11"
    zavrseni = citaj_csv(tmp_path / "akcii" / "zavrseni-2026-11.csv")
    assert [(z["naziv"], z["posleden_pat"]) for z in zavrseni] == [("Кафе", "2026-11-10")]
    promeni = citaj_csv(tmp_path / "promeni" / "2026.csv")
    assert [(z["naziv"], z["stara"], z["nova"]) for z in promeni] == [("Млеко", "60", "66")]


def test_povtorno_pustanje_istiot_den_ne_menuva_nisto(tmp_path):
    zapisi_den(tmp_path, citanje([red("Леб", "40")]), D1)
    denes = citanje([red("Леб", "44", "30")])
    zapisi_den(tmp_path, denes, D2)
    zbir = zapisi_den(tmp_path, denes, D2)
    assert (zbir.novi_akcii, zbir.zavrseni_akcii, zbir.promeni_na_ceni) == (0, 0, 0)
    assert aktivni(tmp_path)["Леб"]["prv_pat"] == "2026-11-11"
    assert len(citaj_csv(tmp_path / "promeni" / "2026.csv")) == 1


def test_pad_na_izvorot_ne_gi_zavrsuva_akciite(tmp_path):
    zapisi_den(tmp_path, citanje([red("Кафе", "200", "150", do=date(2026, 11, 20))]), D1)

    zbir = zapisi_den(tmp_path, citanje([], status=PADNA), D2)
    assert (zbir.akcii, zbir.zavrseni_akcii) == (1, 0)
    prodavnica = citaj_csv(tmp_path / "prodavnici.csv")[0]
    assert (prodavnica["status"], prodavnica["posledno_uspesno"]) == ("padna", "2026-11-10")

    # Кога изворот ќе се врати, истата акција не е „нова".
    zbir = zapisi_den(tmp_path, citanje([red("Кафе", "200", "150", do=date(2026, 11, 20))]), D3)
    assert (zbir.akcii, zbir.novi_akcii) == (1, 0)
    assert aktivni(tmp_path)["Кафе"]["prv_pat"] == "2026-11-10"


def test_istecena_akcija_na_padnat_izvor_se_zatvora(tmp_path):
    zapisi_den(tmp_path, citanje([red("Кафе", "200", "150", do=D1)]), D1)
    zbir = zapisi_den(tmp_path, citanje([], status=PADNA), D2)
    assert (zbir.akcii, zbir.zavrseni_akcii) == (0, 1)


def test_zastaren_red_so_pominat_rok_ne_e_akcija(tmp_path):
    zbir = zapisi_den(tmp_path, citanje([red("Кафе", "200", "150", do=date(2026, 11, 1))]), D1)
    assert zbir.akcii == 0


def test_ist_naziv_dvapati_ne_se_sporeduva(tmp_path):
    # Изворот не ги разликува варијантите: не се знае кој ред со кој оди.
    zapisi_den(tmp_path, citanje([red("Перница", "300"), red("Перница", "450")]), D1)
    zbir = zapisi_den(tmp_path, citanje([red("Перница", "320"), red("Перница", "450")]), D2)
    assert zbir.promeni_na_ceni == 0


def test_pad_na_cel_sinjir_se_gleda_vo_pregledot(tmp_path):
    ishodi = citanje([red("Леб", "40")])
    ishodi.append(IshodSinjir("zito", "Жито маркети", PADNA, "SourceUnavailable: 403"))
    zapisi_den(tmp_path, ishodi, D1)
    zito = [z for z in citaj_csv(tmp_path / "prodavnici.csv") if z["sinjir"] == "zito"]
    assert [(z["prodavnica"], z["status"], z["poraka"]) for z in zito] == [
        ("(целиот синџир)", "padna", "SourceUnavailable: 403")
    ]
    # Следниот ден синџирот се враќа: лажниот ред не останува.
    ishodi[1] = IshodSinjir(
        "zito", "Жито маркети", prodavnici=[IshodProdavnica("zito", "Жито маркети", "24", "24 Штип Сењак", status=OK, redovi=[red("Сол", "20")])]
    )
    zapisi_den(tmp_path, ishodi, D2)
    zito = [z for z in citaj_csv(tmp_path / "prodavnici.csv") if z["sinjir"] == "zito"]
    assert [(z["prodavnica_id"], z["status"]) for z in zito] == [("24", "ok")]


def test_akcii_na_izvor_sto_dolgo_ne_se_cita_se_zatvoraat(tmp_path):
    # Акција без краен датум: не смее вечно да стои „активна" на извор што
    # не одговара.
    zapisi_den(tmp_path, citanje([red("Кафе", "200", "150")]), D1)
    padnato = citanje([], status=PADNA)
    assert zapisi_den(tmp_path, padnato, date(2026, 11, 13)).akcii == 1
    zbir = zapisi_den(tmp_path, padnato, date(2026, 11, 14))
    assert (zbir.akcii, zbir.zavrseni_akcii) == (0, 1)
