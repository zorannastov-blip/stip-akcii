"""Чување на податоците како обични CSV датотеки во `podatoci/`.

Три работи со различен раст:

    sostojba/<синџир>-<продавница>.csv   целиот ценовник; се пребришува
    promeni/<година>.csv                 ред САМО кога редовната цена се смени
    akcii/aktivni.csv                    акциите што важат денес; се пребришува
    akcii/zavrseni-<година>-<месец>.csv  завршени акции, со прв и последен ден

Состојбата е подредена и се пребришува, па git чува само разлики. Историјата
расте само со вистински промени: млекото што чини исто и вчера и денес не
зазема нов ред.
"""

from __future__ import annotations

import csv
import re
from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass, fields
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from pathlib import Path

from stipakcii.citaci.base import RawPriceRow
from stipakcii.citaci.parsing import normalize_for_match, normalize_space
from stipakcii.citanje import OK, IshodProdavnica, IshodSinjir


# --------------------------------------------------------------------------
# Запис на вредности
# --------------------------------------------------------------------------
def d2s(vrednost: Decimal | None) -> str:
    """Decimal во текст без вишок нули: 45.00 -> „45", 16.50 -> „16.5"."""
    if vrednost is None:
        return ""
    return format(vrednost.normalize(), "f")


def s2d(tekst: str | None) -> Decimal | None:
    if not tekst:
        return None
    try:
        return Decimal(tekst)
    except InvalidOperation:
        return None


def dat2s(vrednost: date | None) -> str:
    return vrednost.isoformat() if vrednost else ""


def s2dat(tekst: str | None) -> date | None:
    if not tekst:
        return None
    try:
        return date.fromisoformat(tekst)
    except ValueError:
        return None


# --------------------------------------------------------------------------
# Ред од ценовник, сведен
# --------------------------------------------------------------------------
@dataclass(frozen=True, slots=True)
class Red:
    naziv: str
    opis: str = ""
    cena: Decimal | None = None  # што се плаќа денес
    redovna: Decimal | None = None  # редовна цена
    so_popust: Decimal | None = None  # пополнето само кај вистинска акција
    popust_pct: Decimal | None = None
    edinecna: Decimal | None = None
    edinica: str = ""
    vid: str = ""
    od: date | None = None
    do: date | None = None

    @property
    def kluc(self) -> tuple[str, str]:
        return (normalize_for_match(self.naziv), normalize_for_match(self.opis))

    @property
    def e_akcija(self) -> bool:
        return self.so_popust is not None


def od_cenovnik(red: RawPriceRow) -> Red:
    """Го сведува редот од читачот.

    Акција е ред со пополнета цена со попуст што е навистина пониска од
    редовната. „Попуст" што не ја намалува цената не е понуда за купувачот,
    па тука се чува како обична цена.
    """
    redovna = red.regular_price
    so_popust = red.discount_price if red.is_discount else None

    if so_popust is not None and redovna is not None and so_popust >= redovna:
        so_popust = None
    if redovna is None and so_popust is None:
        redovna = red.sale_price

    cena = so_popust if so_popust is not None else (red.sale_price or redovna)

    pct = red.discount_pct if so_popust is not None else None
    if so_popust is not None and pct is None and redovna:
        pct = ((redovna - so_popust) / redovna * 100).quantize(
            Decimal("0.1"), rounding=ROUND_HALF_UP
        )

    akcija = so_popust is not None
    return Red(
        naziv=normalize_space(red.name),
        opis=normalize_space(red.description),
        cena=cena,
        redovna=redovna,
        so_popust=so_popust,
        popust_pct=pct,
        edinecna=red.unit_price,
        edinica=red.unit_price_label or "",
        vid=normalize_space(red.promo_type_raw) if akcija else "",
        od=red.valid_from if akcija else None,
        do=red.valid_to if akcija else None,
    )


KOLONI_SOSTOJBA = [f.name for f in fields(Red)]

# Колку дена акциите на продавница што не се чита остануваат „активни".
# Подолго од ова веќе не знаеме дали важат, па се затвораат.
DENOVI_BEZ_CITANJE = 3
# По колку дена исчезната продавница се брише од прегледот.
DENOVI_ZA_BRISENJE = 14


def _red_vo_zapis(red: Red) -> dict[str, str]:
    return {
        "naziv": red.naziv,
        "opis": red.opis,
        "cena": d2s(red.cena),
        "redovna": d2s(red.redovna),
        "so_popust": d2s(red.so_popust),
        "popust_pct": d2s(red.popust_pct),
        "edinecna": d2s(red.edinecna),
        "edinica": red.edinica,
        "vid": red.vid,
        "od": dat2s(red.od),
        "do": dat2s(red.do),
    }


def _zapis_vo_red(zapis: dict[str, str]) -> Red:
    return Red(
        naziv=zapis.get("naziv", ""),
        opis=zapis.get("opis", ""),
        cena=s2d(zapis.get("cena")),
        redovna=s2d(zapis.get("redovna")),
        so_popust=s2d(zapis.get("so_popust")),
        popust_pct=s2d(zapis.get("popust_pct")),
        edinecna=s2d(zapis.get("edinecna")),
        edinica=zapis.get("edinica", ""),
        vid=zapis.get("vid", ""),
        od=s2dat(zapis.get("od")),
        do=s2dat(zapis.get("do")),
    )


# --------------------------------------------------------------------------
# CSV
# --------------------------------------------------------------------------
def citaj_csv(pateka: Path) -> list[dict[str, str]]:
    if not pateka.exists():
        return []
    with pateka.open(encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def pisi_csv(pateka: Path, koloni: list[str], zapisi: Iterable[dict[str, str]]) -> None:
    pateka.parent.mkdir(parents=True, exist_ok=True)
    privremena = pateka.with_suffix(pateka.suffix + ".tmp")
    with privremena.open("w", encoding="utf-8", newline="") as f:
        pisac = csv.DictWriter(f, fieldnames=koloni, lineterminator="\n")
        pisac.writeheader()
        pisac.writerows(zapisi)
    privremena.replace(pateka)


def dodaj_csv(pateka: Path, koloni: list[str], zapisi: list[dict[str, str]]) -> None:
    if not zapisi:
        return
    pateka.parent.mkdir(parents=True, exist_ok=True)
    nova = not pateka.exists()
    with pateka.open("a", encoding="utf-8", newline="") as f:
        pisac = csv.DictWriter(f, fieldnames=koloni, lineterminator="\n")
        if nova:
            pisac.writeheader()
        pisac.writerows(zapisi)


def ime_na_datoteka(sinjir: str, prodavnica_id: str) -> str:
    cisto = re.sub(r"[^a-z0-9]+", "-", prodavnica_id.lower()).strip("-") or "x"
    return f"{sinjir}-{cisto}.csv"


# --------------------------------------------------------------------------
# Акции
# --------------------------------------------------------------------------
KOLONI_AKCII = [
    "sinjir",
    "prodavnica_id",
    "naziv",
    "opis",
    "redovna",
    "so_popust",
    "popust_pct",
    "edinecna",
    "edinica",
    "vid",
    "od",
    "do",
    "prv_pat",
    "viden",
]
KOLONI_ZAVRSENI = [*KOLONI_AKCII[:-1], "posleden_pat"]
KOLONI_PROMENI = ["datum", "sinjir", "prodavnica_id", "naziv", "opis", "stara", "nova"]
KOLONI_PRODAVNICI = [
    "sinjir",
    "sinjir_ime",
    "prodavnica_id",
    "prodavnica",
    "adresa",
    "status",
    "poraka",
    "datum_cenovnik",
    "redovi",
    "akcii",
    "posledno_uspesno",
    "izvor",
]


def _kluc_akcija(z: dict[str, str]) -> tuple[str, ...]:
    return (
        z["sinjir"],
        z["prodavnica_id"],
        normalize_for_match(z["naziv"]),
        normalize_for_match(z["opis"]),
        z["so_popust"],
        z["od"],
        z["do"],
    )


def _akcija_od_red(sinjir: str, prodavnica_id: str, red: Red) -> dict[str, str]:
    zapis = _red_vo_zapis(red)
    del zapis["cena"]
    return {"sinjir": sinjir, "prodavnica_id": prodavnica_id, **zapis}


@dataclass
class Zbir:
    """Што се случи во едно дневно запишување."""

    prodavnici_ok: int = 0
    prodavnici_vkupno: int = 0
    redovi: int = 0
    akcii: int = 0
    novi_akcii: int = 0
    zavrseni_akcii: int = 0
    promeni_na_ceni: int = 0


def zapisi_den(koren: Path, ishodi: list[IshodSinjir], denes: date) -> Zbir:
    """Го запишува дневното читање и ја ажурира историјата.

    Продавница што денес не се прочитала НЕ се допира: нејзината состојба и
    нејзините активни акции остануваат како вчера. Инаку пад на изворот би
    ги „завршил" сите нејзини акции, а утре би ги пријавил како нови.
    """
    zbir = Zbir()
    stari_prodavnici = {
        (z["sinjir"], z["prodavnica_id"]): z for z in citaj_csv(koren / "prodavnici.csv")
    }
    stari_aktivni = citaj_csv(koren / "akcii" / "aktivni.csv")
    stari_po_kluc = {_kluc_akcija(z): z for z in stari_aktivni}

    novi_aktivni: list[dict[str, str]] = []
    zavrseni: list[dict[str, str]] = []
    promeni: list[dict[str, str]] = []
    prodavnici: list[dict[str, str]] = []
    procitani: set[tuple[str, str]] = set()
    videni: set[tuple[str, str]] = set()

    for sinjir in ishodi:
        for p in sinjir.prodavnici:
            zbir.prodavnici_vkupno += 1
            id_ = (p.sinjir, p.prodavnica_id)
            videni.add(id_)
            star = stari_prodavnici.get(id_, {})
            zapis = {
                "sinjir": p.sinjir,
                "sinjir_ime": p.sinjir_ime,
                "prodavnica_id": p.prodavnica_id,
                "prodavnica": p.prodavnica,
                "adresa": p.adresa,
                "status": p.status,
                "poraka": p.poraka,
                "datum_cenovnik": dat2s(p.datum_cenovnik),
                "redovi": star.get("redovi", ""),
                "akcii": star.get("akcii", ""),
                "posledno_uspesno": star.get("posledno_uspesno", ""),
                "izvor": p.izvor,
            }
            prodavnici.append(zapis)
            if p.status != OK:
                continue

            procitani.add(id_)
            zbir.prodavnici_ok += 1
            redovi = sorted(
                {od_cenovnik(r) for r in p.redovi},
                key=lambda r: (r.kluc, r.cena or Decimal(0)),
            )
            zbir.redovi += len(redovi)

            pateka = koren / "sostojba" / ime_na_datoteka(p.sinjir, p.prodavnica_id)
            prvo_citanje = not pateka.exists()
            if not prvo_citanje:
                stara = [_zapis_vo_red(z) for z in citaj_csv(pateka)]
                promeni.extend(_promeni_na_redovna(p, stara, redovi, denes))
            pisi_csv(pateka, KOLONI_SOSTOJBA, (_red_vo_zapis(r) for r in redovi))

            denesni: dict[tuple[str, ...], dict[str, str]] = {}
            for red in redovi:
                if not red.e_akcija or (red.do is not None and red.do < denes):
                    continue  # застарен ред што изворот уште го држи
                akcija = _akcija_od_red(p.sinjir, p.prodavnica_id, red)
                denesni.setdefault(_kluc_akcija(akcija), akcija)

            for kluc, akcija in denesni.items():
                prethodna = stari_po_kluc.get(kluc)
                if prethodna is not None:
                    akcija["prv_pat"] = prethodna["prv_pat"]
                elif prvo_citanje:
                    # Првпат ја читаме продавницата: акцијата не е нова денес,
                    # само ние ја гледаме првпат. Почетокот го кажува изворот.
                    pocetok = s2dat(akcija["od"])
                    akcija["prv_pat"] = dat2s(min(pocetok, denes) if pocetok else denes)
                else:
                    akcija["prv_pat"] = dat2s(denes)
                    zbir.novi_akcii += 1
                akcija["viden"] = dat2s(denes)
                novi_aktivni.append(akcija)

            zapis["redovi"] = str(len(redovi))
            zapis["akcii"] = str(len(denesni))
            zapis["posledno_uspesno"] = dat2s(denes)

    # Што било активно вчера: или е уште активно, или завршило, или е на
    # продавница што денес не се прочитала.
    denesni_klucevi = {_kluc_akcija(z) for z in novi_aktivni}
    for kluc, stara in stari_po_kluc.items():
        id_ = (stara["sinjir"], stara["prodavnica_id"])
        if id_ in procitani:
            if kluc not in denesni_klucevi:
                zavrseni.append(_vo_zavrsena(stara))
        else:
            kraj = s2dat(stara["do"])
            viden = s2dat(stara.get("viden"))
            istecena = kraj is not None and kraj < denes
            predolgo = viden is None or viden < denes - timedelta(days=DENOVI_BEZ_CITANJE)
            if istecena or predolgo:
                zavrseni.append(_vo_zavrsena(stara))
            else:
                novi_aktivni.append(stara)

    # Продавници што денес ги нема во листата на изворот остануваат во
    # прегледот, за да се види дека исчезнале, а не тивко да ги снема.
    for id_, star in stari_prodavnici.items():
        if id_ not in videni and id_[1]:
            posledno = s2dat(star.get("posledno_uspesno"))
            if posledno is None or posledno < denes - timedelta(days=DENOVI_ZA_BRISENJE):
                continue
            star = dict(star)
            sinjir_padna = any(s.sinjir == id_[0] and s.status != OK for s in ishodi)
            star["status"] = "padna" if sinjir_padna else "ja_nema"
            star["poraka"] = next(
                (s.poraka for s in ishodi if s.sinjir == id_[0] and s.status != OK),
                "денес ја нема во листата продавници на изворот",
            )
            prodavnici.append({k: star.get(k, "") for k in KOLONI_PRODAVNICI})

    # Синџир што паднал уште кај листата продавници, а од порано не знаеме
    # ниедна негова продавница, инаку воопшто не би се видел во прегледот.
    for s in ishodi:
        if s.status != OK and not any(z["sinjir"] == s.sinjir for z in prodavnici):
            prazen = dict.fromkeys(KOLONI_PRODAVNICI, "")
            prazen.update(
                sinjir=s.sinjir,
                sinjir_ime=s.sinjir_ime,
                prodavnica="(целиот синџир)",
                status=s.status,
                poraka=s.poraka,
            )
            prodavnici.append(prazen)

    novi_aktivni.sort(key=lambda z: (z["sinjir"], z["prodavnica_id"], z["naziv"], z["opis"]))
    pisi_csv(koren / "akcii" / "aktivni.csv", KOLONI_AKCII, novi_aktivni)
    dodaj_csv(
        koren / "akcii" / f"zavrseni-{denes:%Y-%m}.csv", KOLONI_ZAVRSENI, zavrseni
    )
    dodaj_csv(koren / "promeni" / f"{denes:%Y}.csv", KOLONI_PROMENI, promeni)
    prodavnici.sort(key=lambda z: (z["sinjir"], z["prodavnica"], z["prodavnica_id"]))
    pisi_csv(koren / "prodavnici.csv", KOLONI_PRODAVNICI, prodavnici)

    zbir.akcii = len(novi_aktivni)
    zbir.zavrseni_akcii = len(zavrseni)
    zbir.promeni_na_ceni = len(promeni)
    return zbir


def _vo_zavrsena(aktivna: dict[str, str]) -> dict[str, str]:
    zapis = {k: aktivna.get(k, "") for k in KOLONI_ZAVRSENI}
    zapis["posleden_pat"] = aktivna.get("viden", "")
    return zapis


def _promeni_na_redovna(
    p: IshodProdavnica, stari: list[Red], novi: list[Red], denes: date
) -> list[dict[str, str]]:
    """Редови каде РЕДОВНАТА цена е различна од вчера.

    Акциите не се бројат тука: тие се посебна приказна. Производ што се
    јавува повеќе пати со ист назив и опис (изворот не ги разликува
    варијантите) се прескокнува, зашто не се знае кој ред со кој се споредува.
    """
    broj_stari = Counter(r.kluc for r in stari)
    broj_novi = Counter(r.kluc for r in novi)
    stari_po_kluc = {r.kluc: r for r in stari if broj_stari[r.kluc] == 1}

    promeni: list[dict[str, str]] = []
    for nov in novi:
        if broj_novi[nov.kluc] != 1:
            continue
        star = stari_po_kluc.get(nov.kluc)
        if star is None or star.redovna is None or nov.redovna is None:
            continue
        if star.redovna == nov.redovna:
            continue
        promeni.append(
            {
                "datum": dat2s(denes),
                "sinjir": p.sinjir,
                "prodavnica_id": p.prodavnica_id,
                "naziv": nov.naziv,
                "opis": nov.opis,
                "stara": d2s(star.redovna),
                "nova": d2s(nov.redovna),
            }
        )
    return promeni
