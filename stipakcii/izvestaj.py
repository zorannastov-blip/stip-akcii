"""Дневниот извештај: една страница за телефон и краток преглед во Markdown.

Извештајот се гради САМО од датотеките во `podatoci/`, не од читањето во
меморија. Така повторно пуштање истиот ден дава ист извештај, а извештајот
може да се изгради и без мрежа.
"""

from __future__ import annotations

import json
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path
from typing import Any

from stipakcii.citaci.parsing import normalize_for_match
from stipakcii.postavki import Postavki
from stipakcii.skladiste import citaj_csv, s2d, s2dat
from stipakcii.sporedba import sporedi

# Колку дена наназад се бара покачување на редовната цена пред акција.
DENOVI_ZA_POKACUVANJE = 45


@dataclass
class Podatoci:
    datum: date
    grad: str
    izraboteno: str
    prodavnici: list[dict[str, Any]] = field(default_factory=list)
    akcii: list[dict[str, Any]] = field(default_factory=list)
    promeni: list[dict[str, Any]] = field(default_factory=list)
    sporedbi: list[dict[str, Any]] = field(default_factory=list)
    sledi: list[str] = field(default_factory=list)


# --------------------------------------------------------------------------
# Собирање
# --------------------------------------------------------------------------
def _broj(vrednost: Decimal | None) -> float | None:
    return float(vrednost) if vrednost is not None else None


def _se_sledi(tekst: str, sledi: list[list[str]]) -> bool:
    return any(all(zbor in tekst for zbor in zapis) for zapis in sledi)


def _pokacuvanja(koren: Path, denes: date) -> dict[tuple[str, ...], dict[str, str]]:
    """Последното покачување на редовната цена по производ и продавница."""
    od = denes - timedelta(days=DENOVI_ZA_POKACUVANJE)
    najdeni: dict[tuple[str, ...], dict[str, str]] = {}
    for godina in sorted({od.year, denes.year}):
        for z in citaj_csv(koren / "promeni" / f"{godina}.csv"):
            datum = s2dat(z["datum"])
            stara, nova = s2d(z["stara"]), s2d(z["nova"])
            if datum is None or stara is None or nova is None:
                continue
            if not (od <= datum <= denes) or nova <= stara:
                continue
            kluc = (
                z["sinjir"],
                z["prodavnica_id"],
                normalize_for_match(z["naziv"]),
                normalize_for_match(z["opis"]),
            )
            najdeni[kluc] = z  # датотеката е хронолошка: последното останува
    return najdeni


def soberi(koren: Path, postavki: Postavki, denes: date) -> Podatoci:
    prodavnici = citaj_csv(koren / "prodavnici.csv")
    ime_na = {(z["sinjir"], z["prodavnica_id"]): z["prodavnica"] for z in prodavnici}
    sinjir_ime = {z["sinjir"]: z["sinjir_ime"] for z in prodavnici}
    so_cenovnik: dict[str, set[str]] = defaultdict(set)
    for z in prodavnici:
        if z["posledno_uspesno"]:
            so_cenovnik[z["sinjir"]].add(z["prodavnica_id"])

    sledi = [normalize_for_match(z).split() for z in postavki.sledi if z.strip()]
    pokaceni = _pokacuvanja(koren, denes)
    utre = denes + timedelta(days=1)

    # Ист производ со иста акција во повеќе продавници на синџирот е една
    # ставка, со листа продавници.
    grupi: dict[tuple[str, ...], dict[str, Any]] = {}
    for z in citaj_csv(koren / "akcii" / "aktivni.csv"):
        naziv_k, opis_k = normalize_for_match(z["naziv"]), normalize_for_match(z["opis"])
        kluc = (z["sinjir"], naziv_k, opis_k, z["so_popust"], z["redovna"], z["od"], z["do"])
        stavka = grupi.get(kluc)
        if stavka is None:
            pocetok, kraj = s2dat(z["od"]), s2dat(z["do"])
            vid = normalize_for_match(z["vid"])
            edinecna = s2d(z["edinecna"])
            stavka = grupi[kluc] = {
                "n": z["naziv"],
                "o": z["opis"],
                "sk": z["sinjir"],
                "s": sinjir_ime.get(z["sinjir"], z["sinjir"]),
                "p": [],
                "_id": set(),
                "c": _broj(s2d(z["so_popust"])),
                "r": _broj(s2d(z["redovna"])),
                "pct": _broj(s2d(z["popust_pct"])),
                "e": _broj(edinecna) if edinecna else None,
                "ed": z["edinica"],
                "od": z["od"],
                "do": z["do"],
                "nov": False,
                "idna": pocetok is not None and pocetok > denes,
                "istek": kraj is not None and kraj <= utre,
                "kart": "лојал" in vid or "картич" in vid,
                "pred": "",
                "sl": _se_sledi(f"{naziv_k} {opis_k}", sledi),
                "viden": "",
            }
        stavka["viden"] = max(stavka["viden"], z.get("viden", ""))
        stavka["_id"].add(z["prodavnica_id"])
        stavka["p"].append(ime_na.get((z["sinjir"], z["prodavnica_id"]), z["prodavnica_id"]))
        if z["prv_pat"] == denes.isoformat():
            stavka["nov"] = True
        pokacena = pokaceni.get((z["sinjir"], z["prodavnica_id"], naziv_k, opis_k))
        if pokacena is not None and not stavka["pred"]:
            den = s2dat(pokacena["datum"])
            stavka["pred"] = (
                f"редовната цена е покачена на {den:%d.%m.} "
                f"(од {_cena(s2d(pokacena['stara']))} на {_cena(s2d(pokacena['nova']))})"
            )

    akcii = []
    for stavka in grupi.values():
        site = so_cenovnik.get(stavka["sk"], set())
        stavka["site"] = len(site) > 1 and stavka.pop("_id") >= site
        stavka.pop("_id", None)
        stavka["p"] = sorted(set(stavka["p"]))
        # Пополнето само кога ниедна продавница со оваа акција не се
        # прочитала денес: тогаш цената е од претходно читање.
        if stavka["viden"] == denes.isoformat():
            stavka["viden"] = ""
        akcii.append(stavka)
    akcii.sort(key=lambda a: (-(a["pct"] or 0), a["n"]))

    promeni_grupi: dict[tuple[str, ...], dict[str, Any]] = {}
    for z in citaj_csv(koren / "promeni" / f"{denes:%Y}.csv"):
        if z["datum"] != denes.isoformat():
            continue
        stara, nova = s2d(z["stara"]), s2d(z["nova"])
        if not stara or nova is None:
            continue
        kluc = (z["sinjir"], z["naziv"], z["opis"], z["stara"], z["nova"])
        stavka = promeni_grupi.setdefault(
            kluc,
            {
                "n": z["naziv"],
                "o": z["opis"],
                "sk": z["sinjir"],
                "s": sinjir_ime.get(z["sinjir"], z["sinjir"]),
                "p": [],
                "stara": float(stara),
                "nova": float(nova),
                "pct": float(
                    ((nova - stara) / stara * 100).quantize(
                        Decimal("0.1"), rounding=ROUND_HALF_UP
                    )
                ),
            },
        )
        stavka["p"].append(ime_na.get((z["sinjir"], z["prodavnica_id"]), z["prodavnica_id"]))
    promeni = sorted(promeni_grupi.values(), key=lambda p: (p["pct"], p["n"]))

    sporedbi = []
    for sp in sporedi(koren, prodavnici):
        kluc = " ".join(normalize_for_match(x.naziv) for x in sp.ponudi)
        sporedbi.append(
            {
                "n": sp.naziv,
                "pct": float(sp.razlika_pct),
                "raz": float(sp.najvisoka - sp.najniska),
                "sl": _se_sledi(kluc, sledi),
                "p": [
                    {
                        "s": sinjir_ime.get(x.sinjir, x.sinjir),
                        "n": x.naziv,
                        "c": float(x.cena),
                        "akc": x.akcija,
                    }
                    for x in sp.ponudi
                ],
            }
        )

    return Podatoci(
        datum=denes,
        grad=postavki.grad,
        izraboteno=datetime.now().astimezone().strftime("%d.%m.%Y %H:%M"),
        prodavnici=prodavnici,
        akcii=akcii,
        promeni=promeni,
        sporedbi=sporedbi,
        sledi=list(postavki.sledi),
    )


# --------------------------------------------------------------------------
# Markdown
# --------------------------------------------------------------------------
def _cena(vrednost: Decimal | float | None) -> str:
    if vrednost is None:
        return "–"
    tekst = f"{float(vrednost):.2f}".rstrip("0").rstrip(".")
    return tekst.replace(".", ",") + " ден"


def _procent(vrednost: float) -> str:
    return f"{vrednost:.1f}".rstrip("0").rstrip(".").replace(".", ",")


def _datum_kratko(iso: str) -> str:
    d = s2dat(iso)
    return f"{d:%d.%m.}" if d else ""


def _kade(a: dict[str, Any]) -> str:
    if a.get("site"):
        return f"{a['s']} (сите)"
    return f"{a['s']}: {', '.join(a['p'])}"


def _md(tekst: str) -> str:
    return tekst.replace("|", "\\|")


def _tabela_akcii(akcii: list[dict[str, Any]], najmnogu: int) -> list[str]:
    linii = ["| Производ | Цена | Редовна | Попуст | До | Каде |", "|---|--:|--:|--:|---|---|"]
    for a in akcii[:najmnogu]:
        pct = f"−{_procent(a['pct'])}%" if a["pct"] else ""
        znaci = ("💳 " if a["kart"] else "") + ("⚠ " if a["pred"] else "")
        linii.append(
            f"| {znaci}{_md(a['n'])} | **{_cena(a['c'])}** | {_cena(a['r'])} | {pct} "
            f"| {_datum_kratko(a['do'])} | {_md(_kade(a))} |"
        )
    if len(akcii) > najmnogu:
        linii.append(f"\n…и уште {len(akcii) - najmnogu}. Сите се на страницата.")
    return linii


def _tabela_sporedba(sporedbi: list[dict[str, Any]], najmnogu: int) -> list[str]:
    linii = ["| Производ | Најевтино | Другаде | Разлика |", "|---|---|---|--:|"]
    for x in sporedbi[:najmnogu]:
        prva, ostanati = x["p"][0], x["p"][1:]
        linii.append(
            f"| {_md(x['n'])} | **{_cena(prva['c'])}** {prva['s']}{' ★' if prva['akc'] else ''} "
            f"| {'; '.join(f'{_cena(o["c"])} {o["s"]}' for o in ostanati)} "
            f"| {_cena(x['raz'])} (−{_procent(x['pct'])}%) |"
        )
    if len(sporedbi) > najmnogu:
        linii.append(f"\n…и уште {len(sporedbi) - najmnogu}. Сите се на страницата.")
    return linii


STATUSI = {
    "ok": "✅ прочитан",
    "prazen": "⚪ објавен празен ценовник",
    "padna": "❌ не се прочита",
    "ja_nema": "❔ ја нема кај изворот",
    "nema": "❔ нема продавница во градот",
}


def markdown(p: Podatoci) -> str:
    vazecki = [a for a in p.akcii if not a["idna"]]
    novi = [a for a in vazecki if a["nov"]]
    moi = [a for a in vazecki if a["sl"]]
    istekuvaat = [a for a in vazecki if a["istek"]]

    linii = [
        f"# Акции во {p.grad}, {p.datum:%d.%m.%Y}",
        "",
        f"**{len(vazecki)}** акции, од кои **{len(novi)}** нови денес и "
        f"**{len(istekuvaat)}** што истекуваат денес или утре.",
        "",
        "## Извори",
        "",
        "| Маркет | Продавница | Состојба | Редови | Акции | Последно прочитан |",
        "|---|---|---|--:|--:|---|",
    ]
    for z in p.prodavnici:
        linii.append(
            f"| {z['sinjir_ime']} | {_md(z['prodavnica'])} | {STATUSI.get(z['status'], z['status'])} "
            f"| {z['redovi']} | {z['akcii']} | {_datum_kratko(z['posledno_uspesno'])} |"
        )
    if not p.prodavnici:
        linii.append("| – | – | уште нема читање | | | |")

    if p.sledi:
        linii += ["", "## Твои производи", ""]
        linii += _tabela_akcii(moi, 60) if moi else ["Денес нема акција за ниеден од нив."]
    if novi:
        linii += ["", "## Нови денес", "", *_tabela_akcii(novi, 40)]
    if istekuvaat:
        linii += ["", "## Истекуваат денес или утре", "", *_tabela_akcii(istekuvaat, 30)]
    if vazecki:
        linii += ["", "## Најголеми попусти", "", *_tabela_akcii(vazecki, 40)]

    if p.sporedbi:
        so_razlika = [x for x in p.sporedbi if x["pct"] > 0]
        moi_sp = [x for x in so_razlika if x["sl"]]
        linii += [
            "",
            "## Ист производ, различна цена",
            "",
            f"Споени се **{len(p.sporedbi)}** производи што ги има во повеќе маркети; "
            f"кај **{len(so_razlika)}** цената се разликува. Спојувањето е по назив, "
            "па провери дали називите навистина се однесуваат на истата стока. "
            "★ значи дека најниската цена е акциска.",
        ]
        if moi_sp:
            linii += ["", "### Твои производи", "", *_tabela_sporedba(moi_sp, 50)]
        linii += ["", "### Најголеми разлики", "", *_tabela_sporedba(so_razlika, 30)]

    if p.promeni:
        poskapeni = [x for x in p.promeni if x["pct"] > 0][::-1][:15]
        poevtineti = [x for x in p.promeni if x["pct"] < 0][:15]
        linii += ["", "## Промени на редовни цени денес", ""]
        linii += ["| Производ | Од | На | Промена | Каде |", "|---|--:|--:|--:|---|"]
        for x in [*poskapeni, *poevtineti]:
            linii.append(
                f"| {_md(x['n'])} | {_cena(x['stara'])} | {_cena(x['nova'])} "
                f"| {'+' if x['pct'] > 0 else '−'}{_procent(abs(x['pct']))}% "
                f"| {x['s']}: {_md(', '.join(sorted(set(x['p']))))} |"
            )

    linii += [
        "",
        "---",
        "💳 цената важи само со картичка · ⚠ редовната цена е покачена "
        f"во последните {DENOVI_ZA_POKACUVANJE} дена",
        "",
        f"Изработено {p.izraboteno}. Цените се од ценовниците што маркетите јавно "
        "ги објавуваат; важи цената на каса.",
        "",
    ]
    return "\n".join(linii)


# --------------------------------------------------------------------------
# HTML
# --------------------------------------------------------------------------
def html(p: Podatoci) -> str:
    sodrzina = {
        "datum": p.datum.isoformat(),
        "grad": p.grad,
        "izraboteno": p.izraboteno,
        "denovi": DENOVI_ZA_POKACUVANJE,
        "prodavnici": p.prodavnici,
        "akcii": p.akcii,
        "promeni": p.promeni,
        "sporedbi": p.sporedbi,
        "sledi": p.sledi,
    }
    vgradeno = json.dumps(sodrzina, ensure_ascii=False, separators=(",", ":"))
    # „</" во податоците не смее да го затвори <script>.
    vgradeno = vgradeno.replace("</", "<\\/")
    sablon = (Path(__file__).parent / "stranica.html").read_text(encoding="utf-8")
    return sablon.replace("/*PODATOCI*/null", vgradeno).replace(
        "<!--NASLOV-->", f"Акции во {p.grad}, {p.datum:%d.%m.%Y}"
    )


def zapisi(koren_repo: Path, p: Podatoci) -> None:
    (koren_repo / "docs").mkdir(parents=True, exist_ok=True)
    (koren_repo / "docs" / "index.html").write_text(html(p), encoding="utf-8")
    (koren_repo / "IZVESTAJ.md").write_text(markdown(p), encoding="utf-8")
