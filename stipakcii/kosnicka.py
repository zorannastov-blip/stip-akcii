"""Кошничка: каде се најевтини основните производи, групирано по маркет.

Споредбата во `sporedba.py` бара ИСТ производ во повеќе маркети. Кошничката
прашува нешто друго: „каде е најевтин литар трајно млеко, без оглед на
брендот?“ За секоја ставка од листата `[[kosnicka]]` во postavki.toml се бара
најевтината понуда во секој синџир, по килограм, литар или парче, и ставката
оди кај синџирот што е најевтин.

Изборот е по зборови во називот, па во кошничката влегува најевтината стока
од тој вид, а не одреден бренд. Затоа до секоја цена стои и називот.

    python -m stipakcii.kosnicka                 денешната кошничка
    python -m stipakcii.kosnicka --kandidati 8   по 8 кандидати за секоја
                                                 ставка и синџир (за дотерување)
"""

from __future__ import annotations

import argparse
import re
import sys
from collections import defaultdict
from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path
from typing import Any

from stipakcii.citaci.parsing import normalize_for_match
from stipakcii.skladiste import citaj_csv, ime_na_datoteka, s2d

# --------------------------------------------------------------------------
# Количина од називот
# --------------------------------------------------------------------------
_BROJ = r"(\d+(?:[.,]\d+)?)"
# Подолгите ознаки се први, за „кгр" да не се прочита како „кг" + „р".
_EDINICA = r"(кгр|кг|kg|гр|gr|г|g|мл|ml|литри|литра|литар|лит|л|l)"
_MERKA = re.compile(rf"(?<![\w.,]){_BROJ}\s*{_EDINICA}\.?(?!\w)", re.IGNORECASE)
_PAKET = re.compile(rf"(?<![\w.,])(\d+)\s*[xх*]\s*{_BROJ}\s*{_EDINICA}\.?(?!\w)", re.IGNORECASE)
# „КОМПИР МЛАД КГР", „ЈАБОЛКА ГАЛА /кгр": цената е за килограм.
_NA_KILO = re.compile(r"(?<![\w.,\d])/?\s*(кгр|кг|kg)\.?(?!\w)", re.IGNORECASE)
_PARCINJA = (
    re.compile(r"(?<![\d/])(\d+)\s*/\s*1(?![\d/.,])"),  # 10/1
    re.compile(r"(?<![\d/.,])1\s*/\s*(\d+)(?![\d/])"),  # 1/10
    re.compile(r"(?<![\w.,])(\d+)\s*(?:парчиња|парч|ком|бр|ролни|ролна|рол)\.?(?!\w)", re.IGNORECASE),
)

_VO_GRAMI = {
    "кгр": 1000, "кг": 1000, "kg": 1000, "гр": 1, "gr": 1, "г": 1, "g": 1,
    "литри": 1000, "литра": 1000, "литар": 1000, "лит": 1000, "л": 1000, "l": 1000,
    "мл": 1, "ml": 1,
}  # fmt: skip
_MASA = {"кгр", "кг", "kg", "гр", "gr", "г", "g"}


def _d(tekst: str) -> Decimal:
    return Decimal(tekst.replace(",", "."))


def kolicina(naziv: str) -> tuple[Decimal | None, str, Decimal | None]:
    """Количината прочитана од називот: (износ, „g" или „ml", парчиња).

    Износот е во грами или милилитри; None значи дека во називот го нема.
    """
    tekst = normalize_for_match(naziv)

    tezina: Decimal | None = None
    vid = "g"
    paket = _PAKET.search(tekst)
    if paket:  # „4*125гр" е пакување од 4 по 125 г
        tezina = Decimal(paket.group(1)) * _d(paket.group(2)) * _VO_GRAMI[paket.group(3)]
        vid = "g" if paket.group(3) in _MASA else "ml"
    else:
        merka = _MERKA.search(tekst)
        if merka:
            iznos, edinica = _d(merka.group(1)), merka.group(2)
            # „0.420гр" во ценовник е 0,42 кг: леб од 420 г, не од половина грам.
            if edinica in _MASA and _VO_GRAMI[edinica] == 1 and iznos < 1:
                iznos *= 1000
            tezina = iznos * _VO_GRAMI[edinica]
            vid = "g" if edinica in _MASA else "ml"
        elif _NA_KILO.search(tekst):
            tezina = Decimal(1000)

    parcinja: Decimal | None = None
    for obrazec in _PARCINJA:
        m = obrazec.search(tekst)
        if m and int(m.group(1)) > 0:
            parcinja = Decimal(m.group(1))
            break
    return tezina, vid, parcinja


# Единечната цена од ценовникот служи само за едно: да се препознае стока што
# се продава на килограм, а во називот нема количина („ПИЛЕШКИ КОПАН ГОЛД").
_ED_100 = re.compile(r"^100\s*(гр|gr|g)$", re.IGNORECASE)
_ED_1000 = re.compile(r"^(1\s*(кгр|кг|kg)|1000\s*(гр|gr|g))$", re.IGNORECASE)


def _se_prodava_na_kilo(cena: Decimal, edinecna: Decimal | None, edinica: str) -> bool:
    """Точно кога единечната цена за килограм е истата како цената."""
    if not edinecna or edinecna <= 0:
        return False
    edinica = edinica.strip()
    if _ED_100.match(edinica):
        po_kilo = edinecna * 10
    elif _ED_1000.match(edinica):
        po_kilo = edinecna
    else:
        return False
    return abs(po_kilo - cena) <= cena * Decimal("0.011")


# --------------------------------------------------------------------------
# Ставки од поставките
# --------------------------------------------------------------------------
_OPSEG = re.compile(
    rf"^\s*{_BROJ}\s*(?:-\s*{_BROJ}\s*)?(кг|г|гр|л|мл|парчиња|парче|парч|ком)\.?\s*$", re.IGNORECASE
)
_VO_OSNOVNA = {"кг": ("g", 1000), "г": ("g", 1), "гр": ("g", 1), "л": ("ml", 1000), "мл": ("ml", 1),
               "парчиња": ("kom", 1), "парче": ("kom", 1), "парч": ("kom", 1), "ком": ("kom", 1)}  # fmt: skip
# До оваа големина на пакување цената се прикажува по 100 г/мл, не по кг/л.
MALO_PAKUVANJE = Decimal(250)


def _opseg(tekst: str) -> tuple[Decimal, Decimal, str]:
    """„1 л", „400-500 г", „8-24 парчиња" -> (од, до, „g", „ml" или „kom")."""
    m = _OPSEG.match(tekst)
    if not m:
        raise ValueError(f"не се чита количината „{tekst}“ (пример: „1 л“, „400-500 г“, „10 парчиња“)")
    edinica = m.group(3).lower()
    osnovna, mnozi = _VO_OSNOVNA[edinica]
    od = _d(m.group(1)) * mnozi
    do = _d(m.group(2)) * mnozi if m.group(2) else od
    if do < od:
        raise ValueError(f"опсегот „{tekst}“ е наопаку")
    return od, do, osnovna


@dataclass(frozen=True)
class Stavka:
    ime: str
    # Секој запис е една или повеќе можности одделени со „|"; називот или
    # описот мора да има збор што почнува со една од нив, за секој запис.
    # Можност со празно место на крајот („сол ") бара цел збор.
    bara: tuple[tuple[str, ...], ...]
    # Ниту еден од овие делови не смее да се најде во називот или описот.
    bez: tuple[str, ...]
    # Исто, но се гледа само називот (описот често е име на цела група).
    bez_naziv: tuple[str, ...]
    od: Decimal  # најмало пакување, во грами, милилитри или парчиња
    do: Decimal  # најголемо пакување
    osnovna: str  # „g" (тежина), „ml" (волумен) или „kom"
    nedelno: Decimal  # колку троши семејството неделно, во истата единица
    # Свежа стока без количина во називот се смета дека е на килограм.
    na_kilo: bool = False
    # Се споредуваат и пакувања на тежина и на волумен (јогурт: 1 кг и 1 л).
    kg_i_l: bool = False

    @property
    def tecno(self) -> bool:
        return self.osnovna == "ml"

    @property
    def merka(self) -> str:
        """Единицата во која се прикажува цената."""
        if self.osnovna == "kom":
            return "парче"
        if self.delitel == 100:
            return "100 мл" if self.tecno else "100 г"
        return "л" if self.tecno else "кг"

    @property
    def delitel(self) -> Decimal:
        """Колку основни единици има во мерката за прикажување."""
        if self.osnovna == "kom":
            return Decimal(1)
        # Ситни пакувања (паста за заби) се читаат полесно по 100 мл.
        return Decimal(100) if self.do <= MALO_PAKUVANJE else Decimal(1000)


def _moznost(tekst: str) -> str:
    """Збор од „bara": празно место на крајот се чува, значи „цел збор"."""
    cisto = normalize_for_match(tekst)
    return cisto + " " if tekst.endswith(" ") and cisto else cisto


def stavka_od_zapis(zapis: dict[str, Any]) -> Stavka:
    ime = str(zapis.get("ime", "")).strip()
    if not ime:
        raise ValueError("ставка во кошничката нема „ime“")
    bara = tuple(
        tuple(_moznost(m) for m in str(z).split("|") if m.strip()) for z in zapis.get("bara", ())
    )
    if not bara or not all(bara):
        raise ValueError(f"кошничка „{ime}“: „bara“ мора да има барем еден збор")
    if "pakuvanje" not in zapis:
        raise ValueError(f"кошничка „{ime}“: недостасува „pakuvanje“")
    try:
        od, do, osnovna = _opseg(str(zapis["pakuvanje"]))
        n_od, _, n_osnovna = _opseg(str(zapis.get("nedelno", zapis["pakuvanje"])))
    except ValueError as greska:
        raise ValueError(f"кошничка „{ime}“: {greska}") from None
    if n_osnovna != osnovna:
        raise ValueError(f"кошничка „{ime}“: „nedelno“ и „pakuvanje“ се во различни единици")
    return Stavka(
        ime=ime,
        bara=bara,
        bez=tuple(normalize_for_match(str(z)) for z in zapis.get("bez", ()) if str(z).strip()),
        bez_naziv=tuple(
            normalize_for_match(str(z)) for z in zapis.get("bez_naziv", ()) if str(z).strip()
        ),
        od=od,
        do=do,
        osnovna=osnovna,
        nedelno=n_od,
        na_kilo=bool(zapis.get("na_kilo", False)),
        kg_i_l=bool(zapis.get("kg_i_l", False)),
    )


def stavki_od(zapisi: Any) -> tuple[list[Stavka], list[str]]:
    """Ставките од поставките. Запис што не се чита не го урива извештајот:
    се прескокнува, а причината се враќа за да се прикаже."""
    stavki: list[Stavka] = []
    greski: list[str] = []
    for zapis in zapisi or ():
        try:
            stavka = stavka_od_zapis(zapis)
        except (ValueError, TypeError, AttributeError) as greska:
            greski.append(str(greska))
            continue
        if any(s.ime == stavka.ime for s in stavki):
            greski.append(f"кошничка „{stavka.ime}“ е запишана двапати")
            continue
        stavki.append(stavka)
    return stavki, greski


# --------------------------------------------------------------------------
# Избор
# --------------------------------------------------------------------------
@dataclass
class Ponuda:
    sinjir: str
    naziv: str
    cena: Decimal  # цена на пакувањето
    golemina: Decimal  # грами/милилитри или парчиња во пакувањето
    vid: str  # „g", „ml" или „kom": во што е запишано пакувањето
    edinecna: Decimal  # цена за килограм, литар или парче
    akcija: bool
    kartichka: bool
    klub: bool
    do: str  # до кога важи акцијата, ISO датум или празно
    prodavnici: set[str] = field(default_factory=set)


@dataclass
class Izbor:
    stavka: Stavka
    ponudi: list[Ponuda]  # најевтината во секој синџир, од најевтина кон најскапа

    @property
    def najevtina(self) -> Ponuda:
        return self.ponudi[0]


@dataclass
class Kosnicka:
    izbori: list[Izbor]  # само ставките што се најдени барем во еден синџир
    nenajdeni: list[str]


def so_kartichka(vid: str) -> bool:
    """Цена што важи само со картичка: исто правило како кај акциите во izvestaj.py."""
    vid = normalize_for_match(vid)
    return "лојал" in vid or "картич" in vid


def klub_cena(vid: str) -> bool:
    """„клуб цена" (Жито). Се прикажува како што пишува во ценовникот; дали за неа
    треба картичка, ценовникот не кажува, па не се означува со 💳."""
    return "клуб" in normalize_for_match(vid)


_BUKVA = "a-zа-яѐ-џ"


def _ima_zbor(tekst: str, moznost: str) -> bool:
    """Дали во текстот има збор што почнува со `moznost` (или е точно тој)."""
    if moznost.endswith(" "):
        return re.search(rf"(?<![{_BUKVA}]){re.escape(moznost[:-1])}(?![{_BUKVA}])", tekst) is not None
    return re.search(rf"(?<![{_BUKVA}]){re.escape(moznost)}", tekst) is not None


def _odgovara(stavka: Stavka, naziv: str, opis: str) -> bool:
    tekst = f"{naziv} | {opis}"
    if any(del_ in tekst for del_ in stavka.bez) or any(del_ in naziv for del_ in stavka.bez_naziv):
        return False
    return all(any(_ima_zbor(tekst, m) for m in moznosti) for moznosti in stavka.bara)


def _golemina(stavka: Stavka, z: dict[str, str], cena: Decimal) -> tuple[Decimal, str] | None:
    """Големината на пакувањето и во што е запишана; None ако не одговара."""
    tezina, vid, parcinja = kolicina(z["naziv"])
    if stavka.osnovna == "kom":
        return (parcinja, "kom") if parcinja is not None else None
    if tezina is None:
        if stavka.na_kilo or _se_prodava_na_kilo(cena, s2d(z.get("edinecna")), z.get("edinica", "")):
            tezina, vid = Decimal(1000), "g"
        else:
            return None
    if vid != stavka.osnovna and not stavka.kg_i_l:
        return None
    return tezina, vid


def kandidati(
    koren: Path, prodavnici: list[dict[str, str]], stavki: list[Stavka]
) -> dict[str, dict[str, list[Ponuda]]]:
    """Сите понуди што одговараат: ime на ставка -> синџир -> понуди, од најевтина."""
    najdeni: dict[str, dict[str, dict[str, Ponuda]]] = {s.ime: defaultdict(dict) for s in stavki}
    for p in prodavnici:
        if p["status"] != "ok" or not p["prodavnica_id"]:
            continue
        pateka = koren / "sostojba" / ime_na_datoteka(p["sinjir"], p["prodavnica_id"])
        for z in citaj_csv(pateka):
            cena = s2d(z["cena"])
            if not cena or cena <= 0:
                continue
            naziv, opis = normalize_for_match(z["naziv"]), normalize_for_match(z["opis"])
            for stavka in stavki:
                if not _odgovara(stavka, naziv, opis):
                    continue
                pakuvanje = _golemina(stavka, z, cena)
                if pakuvanje is None or not (stavka.od <= pakuvanje[0] <= stavka.do):
                    continue
                golemina, vid = pakuvanje
                postoi = najdeni[stavka.ime][p["sinjir"]].get(naziv)
                if postoi is None or cena < postoi.cena:
                    postoi = najdeni[stavka.ime][p["sinjir"]][naziv] = Ponuda(
                        sinjir=p["sinjir"],
                        naziv=z["naziv"],
                        cena=cena,
                        golemina=golemina,
                        vid=vid,
                        edinecna=cena / golemina * stavka.delitel,
                        akcija=bool(z["so_popust"]),
                        kartichka=bool(z["so_popust"]) and so_kartichka(z["vid"]),
                        klub=bool(z["so_popust"]) and klub_cena(z["vid"]),
                        do=z.get("do", "") if z["so_popust"] else "",
                    )
                if cena == postoi.cena:
                    postoi.prodavnici.add(p["prodavnica"])
    return {
        ime: {
            sinjir: sorted(ponudi.values(), key=lambda x: (x.edinecna, x.cena, x.naziv))
            for sinjir, ponudi in po_sinjir.items()
        }
        for ime, po_sinjir in najdeni.items()
    }


def sostavi(koren: Path, prodavnici: list[dict[str, str]], stavki: list[Stavka]) -> Kosnicka:
    """За секоја ставка: најевтината понуда во секој синџир."""
    site = kandidati(koren, prodavnici, stavki)
    izbori, nenajdeni = [], []
    for stavka in stavki:
        najdobri = [ponudi[0] for ponudi in site[stavka.ime].values() if ponudi]
        if not najdobri:
            nenajdeni.append(stavka.ime)
            continue
        najdobri.sort(key=lambda x: (x.edinecna, x.sinjir))
        izbori.append(Izbor(stavka, najdobri))
    return Kosnicka(izbori, nenajdeni)


# --------------------------------------------------------------------------
# За извештајот
# --------------------------------------------------------------------------
def _zaokruzi(vrednost: Decimal, mesta: str = "0.01") -> float:
    return float(vrednost.quantize(Decimal(mesta), rounding=ROUND_HALF_UP))


def _cel(vrednost: float) -> int:
    """Цели денари: збировите на кошничката не се прикажуваат со дени."""
    return int(Decimal(str(vrednost)).quantize(Decimal(1), rounding=ROUND_HALF_UP))


def golemina_tekst(golemina: Decimal, vid: str) -> str:
    """„1 л", „900 г", „10 парчиња"."""

    def broj(x: Decimal) -> str:
        return f"{x.normalize():f}".replace(".", ",")

    if vid == "kom":
        return f"{broj(golemina)} {'парче' if golemina == 1 else 'парчиња'}"
    golemo, malo = ("л", "мл") if vid == "ml" else ("кг", "г")
    return f"{broj(golemina / 1000)} {golemo}" if golemina >= 1000 else f"{broj(golemina)} {malo}"


def _raspredeli(izbori: list[Izbor]) -> dict[str, str]:
    """Кај кој синџир оди секоја ставка: кај најевтиниот. Кога повеќе синџири
    имаат иста најниска цена, ставката оди кај оној што веќе има најмногу
    ставки, за да се оди во што помалку маркети."""
    kaj: dict[str, str] = {}
    broj: dict[str, int] = defaultdict(int)
    izednaceni: list[tuple[Izbor, list[str]]] = []
    for izbor in izbori:
        najniska = _zaokruzi(izbor.najevtina.edinecna)
        isti = [x.sinjir for x in izbor.ponudi if _zaokruzi(x.edinecna) == najniska]
        if len(isti) == 1:
            kaj[izbor.stavka.ime] = isti[0]
            broj[isti[0]] += 1
        else:
            izednaceni.append((izbor, isti))
    for izbor, isti in izednaceni:
        izbran = max(isti, key=lambda sk: (broj[sk], -isti.index(sk)))
        kaj[izbor.stavka.ime] = izbran
        broj[izbran] += 1
    return kaj


def za_izvestaj(
    k: Kosnicka, sinjir_ime: dict[str, str], prodavnici_po_sinjir: dict[str, set[str]]
) -> dict[str, Any]:
    """Кошничката во облик што го користат Markdown и страницата."""
    kaj = _raspredeli(k.izbori)
    stavki = []
    for izbor in k.izbori:
        s = izbor.stavka
        stavki.append(
            {
                "ime": s.ime,
                "kaj": kaj[s.ime],
                "merka": s.merka,
                "nedelno": golemina_tekst(s.nedelno, s.osnovna),
                "p": [
                    {
                        "sk": x.sinjir,
                        "s": sinjir_ime.get(x.sinjir, x.sinjir),
                        "n": x.naziv,
                        "c": _zaokruzi(x.cena),
                        "g": golemina_tekst(x.golemina, x.vid),
                        "e": _zaokruzi(x.edinecna),
                        "ned": _zaokruzi(x.edinecna * s.nedelno / s.delitel),
                        "akc": x.akcija,
                        "kart": x.kartichka,
                        "klub": x.klub,
                        "do": x.do,
                        # Празно кога цената важи во сите продавници на синџирот.
                        "kade": []
                        if x.prodavnici >= prodavnici_po_sinjir.get(x.sinjir, set())
                        else sorted(x.prodavnici),
                    }
                    for x in izbor.ponudi
                ],
            }
        )

    # Колку чини неделната кошничка: најевтино по производ, и сè во еден маркет.
    # Маркет што нема некоја ставка се споредува само за ставките што ги има.
    # Сè е во цели денари, за разликата да се сложува со прикажаните збирови.
    zbirovi = []
    if stavki:
        site = _cel(sum(x["p"][0]["ned"] for x in stavki))
        zbirovi.append({"s": "", "ima": len(stavki), "vkupno": site, "povekje": 0})
        po_market = []
        for sk in sorted({p["sk"] for x in stavki for p in x["p"]}):
            svoi = [(x, next(p for p in x["p"] if p["sk"] == sk)) for x in stavki
                    if any(p["sk"] == sk for p in x["p"])]  # fmt: skip
            vkupno = _cel(sum(p["ned"] for _, p in svoi))
            najevtino = _cel(sum(x["p"][0]["ned"] for x, _ in svoi))
            po_market.append(
                {
                    "s": sinjir_ime.get(sk, sk),
                    "ima": len(svoi),
                    "vkupno": vkupno,
                    "povekje": vkupno - najevtino,
                }
            )
        # Прво маркетите што ја имаат целата кошничка, од најевтин кон најскап.
        zbirovi += sorted(po_market, key=lambda z: (-z["ima"], z["vkupno"], z["s"]))
    return {"stavki": stavki, "zbirovi": zbirovi, "nenajdeni": list(k.nenajdeni)}


# --------------------------------------------------------------------------
# Од командна линија
# --------------------------------------------------------------------------
def main(argv: list[str] | None = None) -> int:
    from stipakcii.postavki import vcitaj

    p = argparse.ArgumentParser(prog="stipakcii.kosnicka", description=__doc__.splitlines()[0])
    p.add_argument("--koren", type=Path, default=Path.cwd(), help="папката на проектот")
    p.add_argument("--kandidati", type=int, default=0, metavar="N",
                   help="прикажи ги првите N кандидати за секоја ставка и синџир")  # fmt: skip
    p.add_argument("--samo", default="", help="само ставките што го содржат овој текст")
    arg = p.parse_args(argv)

    postavki = vcitaj(arg.koren / "postavki.toml")
    site_stavki, greski = stavki_od(postavki.kosnicka)
    for greska in greski:
        print(f"Не се чита: {greska}", file=sys.stderr)
    stavki = [s for s in site_stavki if arg.samo.lower() in s.ime.lower()]
    prodavnici = citaj_csv(arg.koren / "podatoci" / "prodavnici.csv")
    site = kandidati(arg.koren / "podatoci", prodavnici, stavki)
    for stavka in stavki:
        print(f"\n{stavka.ime}")
        po_sinjir = site[stavka.ime]
        if not po_sinjir:
            print("    (ништо не е најдено)")
        for sinjir in sorted(po_sinjir, key=lambda c: po_sinjir[c][0].edinecna):
            for x in po_sinjir[sinjir][: max(arg.kandidati, 1)]:
                znak = ("★" if x.akcija else " ") + ("💳" if x.kartichka else " ")
                print(
                    f"    {sinjir:9} {x.edinecna:9.2f}/{stavka.merka:5} {x.cena:8.2f} "
                    f"{golemina_tekst(x.golemina, x.vid):>12} {znak} {x.naziv}"
                )
    return 0


if __name__ == "__main__":
    sys.exit(main())
