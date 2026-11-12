"""Кошничката: најевтината стока од еден вид во секој маркет, по маркети."""

from __future__ import annotations

from datetime import date
from decimal import Decimal as D
from pathlib import Path

import pytest

from stipakcii.citaci.base import RawPriceRow
from stipakcii.citanje import OK, IshodProdavnica, IshodSinjir
from stipakcii.izvestaj import html, markdown, soberi
from stipakcii.kosnicka import kolicina, sostavi, stavka_od_zapis, stavki_od
from stipakcii.postavki import Postavki, vcitaj
from stipakcii.skladiste import citaj_csv, zapisi_den

DEN = date(2026, 11, 12)

MLEKO = {
    "ime": "Млеко", "bara": ["млеко", "трајно|ухт"], "bez": ["чоко"],
    "pakuvanje": "1 л", "nedelno": "6 л",
}  # fmt: skip
JAJCA = {
    "ime": "Јајца", "bara": ["јајца"], "bez": ["боја"],
    "pakuvanje": "10-30 парчиња", "nedelno": "20 парчиња",
}  # fmt: skip
SOL = {"ime": "Сол", "bara": ["сол "], "pakuvanje": "1 кг", "nedelno": "0.25 кг"}


def red(naziv, cena, opis="", so_popust=None, vid="акција", do=None, edinecna=None, edinica=None):
    return RawPriceRow(
        name=naziv,
        description=opis,
        sale_price=D(so_popust) if so_popust else D(cena),
        regular_price=D(cena),
        discount_price=D(so_popust) if so_popust else None,
        promo_type_raw=vid if so_popust else None,
        valid_to=do,
        unit_price=D(edinecna) if edinecna else None,
        unit_price_label=edinica,
    )


def zapisi(koren: Path, **po_sinjir) -> list[dict[str, str]]:
    """Запишува ценовник за секој синџир: `kam=[редови]` или `kam={"Штип 1": [редови]}`."""
    iminja = {"kam": "КАМ", "zito": "Жито маркети", "ramstore": "Рамстор", "stokomak": "Стокомак"}
    ishodi = []
    for sinjir, sodrzina in po_sinjir.items():
        po_prodavnica = sodrzina if isinstance(sodrzina, dict) else {"Штип 1": sodrzina}
        ishodi.append(
            IshodSinjir(
                sinjir,
                iminja[sinjir],
                prodavnici=[
                    IshodProdavnica(sinjir, iminja[sinjir], str(n), ime, status=OK, redovi=redovi)
                    for n, (ime, redovi) in enumerate(po_prodavnica.items(), start=1)
                ],
            )
        )
    zapisi_den(koren, ishodi, DEN)
    return citaj_csv(koren / "prodavnici.csv")


def izbor(koren, prodavnici, *zapisi_stavki):
    k = sostavi(koren, prodavnici, [stavka_od_zapis(z) for z in zapisi_stavki])
    return {i.stavka.ime: i for i in k.izbori}, k.nenajdeni


# --------------------------------------------------------------------------
@pytest.mark.parametrize(
    ("naziv", "ocekuvano"),
    [
        ("МЛЕКО ТРАЈНО 1,5%ММ 1Л. ДЕЈЛИ МУ", (D(1000), "ml", None)),
        ("Р СОНЧОГЛЕДОВО МАСЛО 905МЛ", (D(905), "ml", None)),
        ("МАСЛО СОНЧОГЛЕДОВО ЛЕ БОН 1 ЛИТ", (D(1000), "ml", None)),
        ("ОРИЗ КОЧАНСКИ до 7%крш 1кгр.", (D(1000), "g", None)),  # „кгр", не „кг"
        ("БРАШНО ТИП 400 1 КГ КАМКО", (D(1000), "g", None)),  # „400" е тип, не количина
        ("ЛЕБ БЕЛ Т-500 0.420гр МАКПРОМЕТ", (D(420), "g", None)),  # 0,42 кг напишано како грами
        ("ОРИЗ ДОЛГОЗРНЕСТ ГУСТО 4*125ГР", (D(500), "g", None)),
        ("ТЕСТЕНИНИ ИНДОМИ 5х70гр ПИЛЕШКО", (D(350), "g", None)),
        ("КОМПИР МЛАД КГР", (D(1000), "g", None)),
        ("ЈАБОЛКА СОРТА: ГАЛА /кгр", (D(1000), "g", None)),
        ("ЈАЈЦАКАМКО Л-КЛАСА, 10/1", (None, "g", D(10))),
        ("ЕКОНОМИЧНО ПАКУВАЊЕ ЈАЈЦА Л 1/10", (None, "g", D(10))),
        ("ЈАЈЦА КЛАСА М табла 30ком. НАШЕ ЈАЈЦЕ", (None, "g", D(30))),
        ("ТОАЛЕТНА ХАРТИЈА 24/1 2СЛ КЛОУДИ СОФТ", (None, "g", D(24))),
        ("СВЕЖ КОМПИР А", (None, "g", None)),
    ],
)
def test_kolicina_od_naziv(naziv, ocekuvano):
    assert kolicina(naziv) == ocekuvano


def test_najevtinata_stoka_od_vidot_vo_sekoj_market(tmp_path):
    prodavnici = zapisi(
        tmp_path,
        kam=[
            red("МЛЕКО 3,2% ТРАЈ.БЕЛАФАРМ 1Л", "52", "BELLA FARM МЛЕКО ТРАЈНО"),
            red("МЛЕКО ТР ИМБ 2.8% 1Л", "65", "BIMILK МЛЕКО УХТ 2,8%"),
            red("МЛЕКО ЧОКОЛ.МОЈА КРАВИЦА 1Л", "40", "ЧОКОЛАДНО МЛЕКО ТРАЈНО"),  # „bez"
            red("МЛЕКО ТРАЈНО 0.5Л", "20"),  # друго пакување: се прескокнува
            red("МЛЕКО СВЕЖО 3.2% 1Л ИМБ", "30"),  # не е трајно
        ],
        zito=[red("МЛЕКО МИЛКЛЕНД 1л 2,8% СО ЧЕП", "60", "Млеко ухт", so_popust="49", do=date(2026, 11, 24))],
    )
    izbori, nenajdeni = izbor(tmp_path, prodavnici, MLEKO, JAJCA)

    mleko = izbori["Млеко"]
    assert [(x.sinjir, x.naziv, x.cena) for x in mleko.ponudi] == [
        ("zito", "МЛЕКО МИЛКЛЕНД 1л 2,8% СО ЧЕП", D("49")),
        ("kam", "МЛЕКО 3,2% ТРАЈ.БЕЛАФАРМ 1Л", D("52")),
    ]
    assert mleko.najevtina.akcija and mleko.najevtina.do == "2026-11-24"
    assert not mleko.najevtina.kartichka
    assert nenajdeni == ["Јајца"]


def test_se_sporeduva_po_edinica_ne_po_cena_na_pakuvanjeto(tmp_path):
    prodavnici = zapisi(
        tmp_path,
        kam=[
            red("ЈАЈЦА КАМКО М-КЛАСА 30/1", "199"),
            red("ЈАЈЦА КАМКО Л-КЛАСА 10/1", "75"),
            red("БОЈА ЗА ЈАЈЦА 10/1", "8"),
        ],
        zito=[red("ЈАЈЦА СУПЕР ЈАЈЦЕ М 10/1", "80", so_popust="72", vid="ЛОЈАЛНОСТ")],
    )
    jajca = izbor(tmp_path, prodavnici, JAJCA)[0]["Јајца"]
    assert jajca.ponudi[1].kartichka and not jajca.ponudi[1].klub and not jajca.najevtina.kartichka
    # 199 за 30 е 6,63 по парче: поевтино од 72 за 10, иако пакувањето е поскапо.
    assert [(x.sinjir, x.golemina) for x in jajca.ponudi] == [("kam", D(30)), ("zito", D(10))]
    assert round(jajca.najevtina.edinecna, 2) == D("6.63")


def test_cel_zbor_tezina_nasproti_volumen_i_stoka_na_kilo(tmp_path):
    prodavnici = zapisi(
        tmp_path,
        kam=[
            red("СОЛ МОРСКА ГУСТО 1КГ", "14"),
            red("СОЛНА КИСЕЛИНА 1КГ", "5"),  # „сол " бара цел збор
            red("СОЛЕТА ПИЛЕШКИ ПАРИЗЕР 1КГ", "9"),
            red("СОЛ ТЕЧНА 1Л", "3"),  # ставка во килограми не гледа литри
        ],
        ramstore=[
            # Без количина во називот, но единечната цена за кило е иста со цената.
            red("ТУЗЛАНСКА СОЛ РЕФУС", "36", edinecna="3.6", edinica="100 гр"),
            red("СОЛ ВО КЕСИЧКА", "2", edinecna="40", edinica="100 гр"),  # не се знае колку е
        ],
    )
    sol = izbor(tmp_path, prodavnici, SOL)[0]["Сол"]
    assert [(x.sinjir, x.naziv) for x in sol.ponudi] == [
        ("kam", "СОЛ МОРСКА ГУСТО 1КГ"),
        ("ramstore", "ТУЗЛАНСКА СОЛ РЕФУС"),
    ]


def test_bez_naziv_ne_go_gleda_opisot_a_kg_i_l_gi_spojuva(tmp_path):
    kopan = {"ime": "Копани", "bara": ["копан"], "bez_naziv": ["крилца"], "pakuvanje": "1 кг"}
    jogurt = {"ime": "Јогурт", "bara": ["јогурт"], "pakuvanje": "1 кг", "kg_i_l": True}
    prodavnici = zapisi(
        tmp_path,
        zito=[
            red("ПИЛЕШКИ КРАТОК КОПАН ГОЛД 1кг", "169", "Замрзнати копани и крилца"),
            red("ПИЛЕШКИ КРИЛЦА КОПАН ДЕЛИСИМО 1кг", "139", "Замрзнати копани и крилца"),
            red("ЈОГУРТ 5КА 1л 2.8%", "68"),
        ],
        kam=[red("ЈОГУРТ 2.8% 1КГ БЕЛА ФАРМ", "59")],
    )
    izbori, _ = izbor(tmp_path, prodavnici, kopan, jogurt)
    assert izbori["Копани"].najevtina.naziv == "ПИЛЕШКИ КРАТОК КОПАН ГОЛД 1кг"
    assert [(x.sinjir, x.vid) for x in izbori["Јогурт"].ponudi] == [("kam", "g"), ("zito", "ml")]


def test_izvestaj_gi_grupira_po_market_i_go_sobira_nedelnoto(tmp_path):
    zapisi(
        tmp_path,
        kam={
            "Штип 1": [red("МЛЕКО ТРАЈНО 1Л", "52"), red("ЈАЈЦА М 10/1", "70"), red("СОЛ 1КГ", "14")],
            "Штип 2": [red("МЛЕКО ТРАЈНО 1Л", "52"), red("ЈАЈЦА М 10/1", "75"), red("СОЛ 1КГ", "14")],
        },
        zito=[
            red("МЛЕКО УХТ 1л", "60", so_popust="49", vid="клуб цена", do=date(2026, 11, 16)),
            red("СОЛ ЕВРО 1кг", "14"),
        ],
    )
    p = soberi(tmp_path, Postavki(kosnicka=(MLEKO, JAJCA, SOL)), DEN)
    stavki = {x["ime"]: x for x in p.kosnicka["stavki"]}

    mleko = stavki["Млеко"]["p"][0]
    assert stavki["Млеко"]["kaj"] == "zito" and mleko["klub"] and not mleko["kart"]
    assert stavki["Јајца"]["kaj"] == "kam" and stavki["Јајца"]["p"][0]["kade"] == ["Штип 1"]
    # Солта чини исто во двата маркета, а секој веќе има по една ставка: оди кај првиот.
    assert stavki["Сол"]["kaj"] == "kam"

    zbirovi = {z["s"]: z for z in p.kosnicka["zbirovi"]}
    # најевтино: млеко 6 л × 49, јајца 20 × 7, сол 0,25 кг × 14 = 437,5, во цели денари
    assert zbirovi[""]["vkupno"] == 438
    assert (zbirovi["КАМ"]["ima"], zbirovi["КАМ"]["povekje"]) == (3, 6 * 3)
    # Жито нема јајца: се споредува само за млекото и солта, каде што е најевтин.
    assert (zbirovi["Жито маркети"]["ima"], zbirovi["Жито маркети"]["povekje"]) == (2, 0)

    tekst = markdown(p)
    assert "## Кошничка по маркети" in tekst
    assert tekst.index("## Кошничка по маркети") < tekst.index("## Најголеми попусти")
    ocekuvan = "| Млеко | ★ МЛЕКО УХТ 1л | **49 ден** за 1 л до 16.11. (клуб цена) | 49 ден/л | 52 ден КАМ |"
    assert ocekuvan in tekst
    assert "| Јајца | ЈАЈЦА М 10/1 (само Штип 1) | **70 ден** за 10 парчиња | 7 ден/парче | – |" in tekst
    assert '"kosnicka":{"stavki":[' in html(p)


def test_ista_cena_odi_kaj_marketot_so_povekje_stavki(tmp_path):
    seker = {"ime": "Шеќер", "bara": ["шеќер"], "pakuvanje": "1 кг"}
    zapisi(
        tmp_path,
        kam=[red("МЛЕКО ТРАЈНО 1Л", "52"), red("ШЕЌЕР 1КГ", "50"), red("СОЛ 1КГ", "14")],
        zito=[red("МЛЕКО УХТ 1л", "49"), red("ШЕЌЕР 1кг", "45"), red("СОЛ ЕВРО 1кг", "14")],
    )
    p = soberi(tmp_path, Postavki(kosnicka=(SOL, MLEKO, seker)), DEN)
    # Жито е најевтин за млекото и шеќерот, па и солта со иста цена оди таму:
    # нема зошто да се оди во КАМ само по неа.
    kaj = {x["ime"]: x["kaj"] for x in p.kosnicka["stavki"]}
    assert kaj == {"Сол": "zito", "Млеко": "zito", "Шеќер": "zito"}
    assert "### КАМ" not in markdown(p)


def test_bez_kosnicka_vo_postavkite_nema_del_vo_izvestajot(tmp_path):
    zapisi(tmp_path, kam=[red("МЛЕКО ТРАЈНО 1Л", "52")])
    p = soberi(tmp_path, Postavki(), DEN)
    assert p.kosnicka == {} and "Кошничка" not in markdown(p)


def test_pogresen_zapis_se_preskoknuva_a_drugite_ostanuvaat(tmp_path):
    loso = {"ime": "Лошо", "bara": ["нешто"], "pakuvanje": "многу"}
    stavki, greski = stavki_od([MLEKO, loso, MLEKO, {"bara": ["х"]}])
    assert [s.ime for s in stavki] == ["Млеко"]
    assert len(greski) == 3 and "Лошо" in greski[0] and "двапати" in greski[1]

    zapisi(tmp_path, kam=[red("МЛЕКО ТРАЈНО 1Л", "52")])
    p = soberi(tmp_path, Postavki(kosnicka=(MLEKO, {**loso, "bara": []})), DEN)
    assert [x["ime"] for x in p.kosnicka["stavki"]] == ["Млеко"]
    assert "⚠ Грешка во кошничката: кошничка „Лошо“" in markdown(p)


def test_greska_vo_kosnickata_ne_go_urniva_izvestajot(tmp_path, monkeypatch):
    def padni(*_):
        raise RuntimeError("расипано")

    zapisi(tmp_path, kam=[red("МЛЕКО ТРАЈНО 1Л", "60", so_popust="52")])
    monkeypatch.setattr("stipakcii.kosnicka.sostavi", padni)
    p = soberi(tmp_path, Postavki(kosnicka=(MLEKO,)), DEN)
    tekst = markdown(p)
    assert "⚠ Грешка во кошничката: кошничката не се пресмета (RuntimeError: расипано)" in tekst
    assert "## Најголеми попусти" in tekst and "МЛЕКО ТРАЈНО 1Л" in tekst


def test_kosnickata_vo_postavki_toml_se_cita_cela():
    """Листата што оди со проектот мора да нема ниту еден запис со грешка."""
    postavki = vcitaj(Path(__file__).parent.parent / "postavki.toml")
    stavki, greski = stavki_od(postavki.kosnicka)
    assert greski == []
    assert len(stavki) >= 20 and len({s.ime for s in stavki}) == len(stavki)
