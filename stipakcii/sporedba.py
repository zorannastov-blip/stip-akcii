"""Споредба на ИСТ производ меѓу маркетите.

Маркетите го пишуваат истиот производ различно:

    КАМ:      КАФЕ ЕСПРЕСО МЕЛЕНО ЛАВАЦА ОРО 250ГР
    Рамстор:  ЛАВАЦА КАФЕ ОРО 250 ГР

Нема заедничка шифра, па спојувањето е по назив и мора да биде претпазливо:
подобро е производ да остане неспоен, отколку да се споредат две различни
стоки. Два производа се сметаат за исти само ако:

  1. имаат иста количина (250 г, 1 л, 16 парчиња ...),
  2. имаат исти броеви во називот (1.5% не е 2.8%),
  3. зборовите на едниот се содржат во зборовите на другиот, со најмалку
     два збора што значат нешто,
  4. во другиот маркет има ТОЧНО ЕДЕН таков кандидат.
"""

from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path

from stipakcii.citaci.parsing import normalize_for_match
from stipakcii.skladiste import citaj_csv, ime_na_datoteka, s2d

# Зборови што не разликуваат производ: вид на пакување и општи описи.
OPSTI = frozenset(
    """
    и со во за од на без the
    пакување пак кеса кесичка шише лименка конзерва кутија тетрапак стакло пет
    вакуум вакум рефус свежо свеж свежа ново нов нова акција промо
    """.split()
)
# Ако разликата е поголема од ова, веројатно не е ист производ.
NAJGOLEM_ODNOS = Decimal("2")
# Колку збора смее подолгиот назив да има повеќе од пократкиот.
NAJMNOGU_VISHOK = 2

_KOLICINA = re.compile(
    r"(?<![\w.,])(\d+(?:[.,]\d+)?)\s*(кг|kg|гр|г|gr|g|мл|ml|л|l|лит|парчиња|парч|пар|ком|капсули|бр)\.?(?![\w])",
    re.IGNORECASE,
)
_MNOZITEL = re.compile(r"(\d+)\s*[xх*]\s*(\d+(?:[.,]\d+)?)", re.IGNORECASE)
_BROJ = re.compile(r"\d+(?:[.,]\d+)?%?")
_ZBOR = re.compile(r"[a-zа-яѐ-џ]+", re.IGNORECASE)
_SLEPENO = re.compile(r"(\d)([a-zа-яѐ-џ])|([a-zа-яѐ-џ])(\d)", re.IGNORECASE)

_EDINICI = {
    "кг": ("g", 1000), "kg": ("g", 1000), "гр": ("g", 1), "г": ("g", 1), "gr": ("g", 1), "g": ("g", 1),
    "л": ("ml", 1000), "l": ("ml", 1000), "лит": ("ml", 1000), "мл": ("ml", 1), "ml": ("ml", 1),
    "парчиња": ("kom", 1), "парч": ("kom", 1), "пар": ("kom", 1), "ком": ("kom", 1),
    "капсули": ("kom", 1), "бр": ("kom", 1),
}  # fmt: skip

# Латинични називи на брендови се сведуваат на кирилица, за „LAVAZZA" и
# „ЛАВАЦА" барем делумно да се сретнат. Грубо е, но доследно.
_LAT = str.maketrans(
    {
        "a": "а", "b": "б", "c": "ц", "d": "д", "e": "е", "f": "ф", "g": "г", "h": "х",
        "i": "и", "j": "ј", "k": "к", "l": "л", "m": "м", "n": "н", "o": "о", "p": "п",
        "q": "к", "r": "р", "s": "с", "t": "т", "u": "у", "v": "в", "w": "в", "x": "кс",
        "y": "и", "z": "з",
    }
)  # fmt: skip


@dataclass(frozen=True)
class Potpis:
    """Она по што се препознава производот, независно од редот на зборовите."""

    kolicina: str  # „250g", „1000ml", „16kom"
    broevi: frozenset[str]  # сите други броеви од називот: „1.5%", „3"
    zborovi: frozenset[str]


def _broj(tekst: str) -> Decimal:
    return Decimal(tekst.replace(",", "."))


def potpis(naziv: str) -> Potpis | None:
    """Потпис на производ, или None ако називот нема количина.

    Без количина не се споредува: „Нескафе класик" може да биде и 2 г и 200 г.
    """
    tekst = normalize_for_match(naziv)
    # „10x15.5г" е пакување од 10 по 15,5 г: се брои вкупното.
    mnozitel = _MNOZITEL.search(tekst)
    najdeni = list(_KOLICINA.finditer(tekst))
    if not najdeni:
        return None

    # Количината е последната во називот: „200Г+20 Г ЛИМЕНКА" останува
    # двосмислено и затоа се чуваат и сите броеви.
    m = najdeni[-1]
    edinica, mnozi = _EDINICI[m.group(2).lower()]
    iznos = _broj(m.group(1)) * mnozi
    if mnozitel and mnozitel.end() >= m.start() - 1 and mnozitel.start() < m.start():
        iznos = _broj(mnozitel.group(1)) * _broj(mnozitel.group(2)) * mnozi
    kolicina = f"{iznos.normalize():f}{edinica}"

    ostatok = tekst[: m.start()] + " " + tekst[m.end() :]
    broevi = frozenset(b.replace(",", ".").rstrip("0").rstrip(".") if "." in b or "," in b else b
                       for b in _BROJ.findall(ostatok))  # fmt: skip
    cisto = _SLEPENO.sub(lambda x: f"{x.group(1) or x.group(3)} {x.group(2) or x.group(4)}", ostatok)
    zborovi = frozenset(
        z for z in (zbor.translate(_LAT) for zbor in _ZBOR.findall(cisto))
        if len(z) >= 3 and z not in OPSTI
    )  # fmt: skip
    if len(zborovi) < 2:
        return None
    return Potpis(kolicina, broevi, zborovi)


def _ist_zbor(a: str, b: str) -> bool:
    """Ист збор, или еден е скратеница од другиот („инст" - „инстант")."""
    if a == b:
        return True
    kratok, dolg = (a, b) if len(a) <= len(b) else (b, a)
    return len(kratok) >= 4 and dolg.startswith(kratok)


def se_sovpagaat(a: Potpis, b: Potpis) -> bool:
    if a.kolicina != b.kolicina or a.broevi != b.broevi:
        return False
    mal, golem = (a.zborovi, b.zborovi) if len(a.zborovi) <= len(b.zborovi) else (b.zborovi, a.zborovi)
    vishok = len(golem) - len(mal)
    # Два збора се доволни само кога и другиот назив има точно два: „Нивеа
    # крема" не смее да се залепи за „Гел за туш Нивеа крем кер".
    if vishok > NAJMNOGU_VISHOK or (len(mal) < 3 and vishok > 0):
        return False
    return all(any(_ist_zbor(z, g) for g in golem) for z in mal)


# --------------------------------------------------------------------------
@dataclass
class Ponuda:
    sinjir: str
    naziv: str
    cena: Decimal
    redovna: Decimal | None
    akcija: bool
    prodavnici: int  # во колку продавници на синџирот е најдена оваа цена


@dataclass
class Sporedba:
    naziv: str
    kolicina: str
    ponudi: list[Ponuda] = field(default_factory=list)

    @property
    def najniska(self) -> Decimal:
        return min(p.cena for p in self.ponudi)

    @property
    def najvisoka(self) -> Decimal:
        return max(p.cena for p in self.ponudi)

    @property
    def razlika_pct(self) -> Decimal:
        return ((self.najvisoka - self.najniska) / self.najvisoka * 100).quantize(Decimal("0.1"))


def _ponudi_po_sinjir(koren: Path, prodavnici: list[dict[str, str]]) -> dict[str, dict[str, Ponuda]]:
    """За секој синџир: назив -> најниската денешна цена во неговите продавници."""
    po_sinjir: dict[str, dict[str, Ponuda]] = defaultdict(dict)
    for p in prodavnici:
        if p["status"] != "ok" or not p["prodavnica_id"]:
            continue
        pateka = koren / "sostojba" / ime_na_datoteka(p["sinjir"], p["prodavnica_id"])
        for z in citaj_csv(pateka):
            cena = s2d(z["cena"])
            if not cena or cena <= 0:
                continue
            kluc = normalize_for_match(z["naziv"])
            postoi = po_sinjir[p["sinjir"]].get(kluc)
            if postoi is None or cena < postoi.cena:
                po_sinjir[p["sinjir"]][kluc] = Ponuda(
                    p["sinjir"], z["naziv"], cena, s2d(z["redovna"]), bool(z["so_popust"]),
                    1 if postoi is None else postoi.prodavnici + 1,
                )  # fmt: skip
            elif cena == postoi.cena:
                postoi.prodavnici += 1
    return po_sinjir


def sporedi(koren: Path, prodavnici: list[dict[str, str]]) -> list[Sporedba]:
    """Производи што се наоѓаат во најмалку два синџира, со цената во секој."""
    po_sinjir = _ponudi_po_sinjir(koren, prodavnici)

    # Сите производи со потпис, групирани по количина: само тие меѓу себе
    # воопшто може да се исти.
    po_kolicina: dict[str, list[tuple[Potpis, Ponuda]]] = defaultdict(list)
    for ponudi in po_sinjir.values():
        for ponuda in ponudi.values():
            p = potpis(ponuda.naziv)
            if p is not None:
                po_kolicina[p.kolicina].append((p, ponuda))

    sporedbi: list[Sporedba] = []
    for kolicina, stavki in po_kolicina.items():
        if len({ponuda.sinjir for _, ponuda in stavki}) < 2:
            continue
        # sosedi[i] = за секој ДРУГ синџир, со кои производи се совпаѓа.
        sosedi: list[dict[str, list[int]]] = [defaultdict(list) for _ in stavki]
        for i, (pi, oi) in enumerate(stavki):
            for j in range(i + 1, len(stavki)):
                pj, oj = stavki[j]
                if oi.sinjir != oj.sinjir and se_sovpagaat(pi, pj):
                    sosedi[i][oj.sinjir].append(j)
                    sosedi[j][oi.sinjir].append(i)

        # Спојување само преку ЕДНОЗНАЧНИ парови: i има еден кандидат во
        # синџирот на j, и j има еден кандидат во синџирот на i.
        roditel = list(range(len(stavki)))

        def koren_na(x: int) -> int:
            while roditel[x] != x:
                roditel[x] = roditel[roditel[x]]
                x = roditel[x]
            return x

        for i, po_drug in enumerate(sosedi):
            for kandidati in po_drug.values():
                if len(kandidati) != 1:
                    continue
                j = kandidati[0]
                if sosedi[j][stavki[i][1].sinjir] == [i]:
                    roditel[koren_na(i)] = koren_na(j)

        grupi: dict[int, list[Ponuda]] = defaultdict(list)
        for i, (_, ponuda) in enumerate(stavki):
            grupi[koren_na(i)].append(ponuda)

        for ponudi in grupi.values():
            sinjiri = {p.sinjir for p in ponudi}
            # Двапати ист синџир во група значи дека спојувањето се излизгало.
            if len(sinjiri) < 2 or len(sinjiri) != len(ponudi):
                continue
            # Секој со секого: А=Б и Б=В не значи А=В кога Б има кус назив.
            potpisi = [potpis(p.naziv) for p in ponudi]
            if not all(
                se_sovpagaat(x, y)
                for n, x in enumerate(potpisi)
                for y in potpisi[n + 1 :]
                if x and y
            ):
                continue
            s = Sporedba(min((p.naziv for p in ponudi), key=len), kolicina, sorted(ponudi, key=lambda p: p.cena))
            if s.najvisoka > s.najniska * NAJGOLEM_ODNOS:
                continue
            sporedbi.append(s)

    sporedbi.sort(key=lambda s: (-s.razlika_pct, s.naziv))
    return sporedbi
