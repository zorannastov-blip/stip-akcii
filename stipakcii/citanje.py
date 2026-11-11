"""Читање на ценовниците: најди ги продавниците во градот, па прочитај ги.

Секој синџир се чита независно од другите: ако еден извор падне, другите
продолжуваат, а падот се запишува со причината. Никогаш тивок празен резултат.
"""

from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass, field
from datetime import date

from stipakcii.citaci import CITACI
from stipakcii.citaci.base import (
    EmptyPricelist,
    PricelistReader,
    RawPriceRow,
    ReaderError,
    StoreRef,
)
from stipakcii.citaci.http import PoliteClient
from stipakcii.citaci.parsing import normalize_for_match
from stipakcii.dnevnik import get_logger
from stipakcii.grad import slugify
from stipakcii.postavki import Postavki

log = get_logger(__name__)

OK = "ok"
PRAZEN = "prazen"  # изворот одговорил, но објавил нула производи
PADNA = "padna"  # изворот не одговорил или сменил формат
NEMA = "nema"  # синџирот одговорил, но нема продавница во градот


@dataclass
class IshodProdavnica:
    sinjir: str
    sinjir_ime: str
    prodavnica_id: str
    prodavnica: str
    adresa: str = ""
    status: str = PADNA
    poraka: str = ""
    redovi: list[RawPriceRow] = field(default_factory=list)
    datum_cenovnik: date | None = None
    preskoknati: int = 0
    izvor: str = ""


@dataclass
class IshodSinjir:
    sinjir: str
    sinjir_ime: str
    status: str = OK
    poraka: str = ""
    prodavnici: list[IshodProdavnica] = field(default_factory=list)


# --------------------------------------------------------------------------
# Која продавница е во градот
# --------------------------------------------------------------------------
_BUKVA = "a-z0-9а-яѐ-џ"


def _zbor_vo(tekst: str | None, zbor: str) -> bool:
    """Дали `zbor` стои како цел збор во текстот.

    Цел збор, не дел: „Штип" не смее да се најде во „Пробиштип".
    """
    kluc = normalize_for_match(tekst)
    if not kluc or not zbor:
        return False
    return re.search(rf"(?<![{_BUKVA}]){re.escape(zbor)}(?![{_BUKVA}])", kluc) is not None


def vo_grad(prodavnica: StoreRef, grad: str) -> bool:
    """Дали продавницата е во бараниот град.

    Изворите го пишуваат градот на четири начини: во посебно поле (КАМ), на
    крајот од адресата (Рамстор), во името („76 Жито Штип Центар",
    „ШТИП 2") или латинично во патеката („kipper-167-shtip"). Името се
    гледа прво: полето за град кај Жито се вади од името и „Штип Центар"
    го чита како скопската општина Центар.
    """
    kirilica = normalize_for_match(grad)
    latinica = slugify(grad)

    if _zbor_vo(prodavnica.name, kirilica):
        return True
    if normalize_for_match(prodavnica.city) == kirilica:
        return True
    if _zbor_vo(prodavnica.address, kirilica):
        return True
    delovi = re.split(r"[^a-z0-9]+", prodavnica.external_id.lower())
    return bool(latinica) and latinica in delovi


# --------------------------------------------------------------------------
# Читање
# --------------------------------------------------------------------------
async def _procitaj_prodavnica(
    klasa: type[PricelistReader],
    prodavnica: StoreRef,
    postavki: Postavki,
    red: asyncio.Semaphore,
) -> IshodProdavnica:
    ishod = IshodProdavnica(
        sinjir=klasa.chain_code,
        sinjir_ime=klasa.chain_name,
        prodavnica_id=prodavnica.external_id,
        prodavnica=prodavnica.name,
        adresa=prodavnica.address or "",
        izvor=prodavnica.source_url or "",
    )
    async with red:
        try:
            # Секоја продавница има свој клиент, значи и своја пауза.
            async with PoliteClient(postavki.mreza) as klient:
                rezultat = await asyncio.wait_for(
                    klasa(klient).read_store(prodavnica),
                    timeout=postavki.minuti_po_prodavnica * 60,
                )
        except EmptyPricelist as greska:
            ishod.status, ishod.poraka = PRAZEN, str(greska)
            log.warning("%s %s: празен ценовник", klasa.chain_name, prodavnica.name)
            return ishod
        except ReaderError as greska:
            ishod.status, ishod.poraka = PADNA, f"{type(greska).__name__}: {greska}"
            log.error("%s %s: %s", klasa.chain_name, prodavnica.name, ishod.poraka)
            return ishod
        except TimeoutError:
            ishod.poraka = f"читањето траеше над {postavki.minuti_po_prodavnica} минути"
            log.error("%s %s: %s", klasa.chain_name, prodavnica.name, ishod.poraka)
            return ishod
        except Exception as greska:  # читач што пукнал не смее да ги урне другите
            ishod.poraka = f"неочекувана грешка {type(greska).__name__}: {greska}"
            log.exception("%s %s: неочекувана грешка", klasa.chain_name, prodavnica.name)
            return ishod

    ishod.status = OK
    ishod.redovi = rezultat.rows
    ishod.datum_cenovnik = rezultat.pricelist_date
    ishod.preskoknati = rezultat.rows_skipped
    ishod.izvor = rezultat.source_url
    if rezultat.warnings:
        ishod.poraka = "; ".join(rezultat.warnings[:3])
    log.info(
        "%s %s: %d реда, %d со цена со попуст",
        klasa.chain_name,
        prodavnica.name,
        len(rezultat.rows),
        len(rezultat.discount_rows),
    )
    return ishod


async def _procitaj_sinjir(kod: str, postavki: Postavki) -> IshodSinjir:
    klasa = CITACI.get(kod)
    if klasa is None:
        poznati = ", ".join(sorted(CITACI))
        return IshodSinjir(kod, kod, PADNA, f"нема читач за „{kod}“; познати: {poznati}")

    ishod = IshodSinjir(klasa.chain_code, klasa.chain_name)
    try:
        async with PoliteClient(postavki.mreza) as klient:
            site = await klasa(klient).discover_stores()
    except ReaderError as greska:
        ishod.status, ishod.poraka = PADNA, f"{type(greska).__name__}: {greska}"
        log.error("%s: листата продавници не се прочита: %s", klasa.chain_name, ishod.poraka)
        return ishod
    except Exception as greska:
        ishod.status = PADNA
        ishod.poraka = f"неочекувана грешка {type(greska).__name__}: {greska}"
        log.exception("%s: неочекувана грешка кај листата продавници", klasa.chain_name)
        return ishod

    lokalni = [p for p in site if vo_grad(p, postavki.grad)]
    if not lokalni:
        ishod.status = NEMA
        ishod.poraka = f"од {len(site)} продавници, ниедна не е во {postavki.grad}"
        log.warning("%s: %s", klasa.chain_name, ishod.poraka)
        return ishod

    log.info("%s: %d од %d продавници се во %s", klasa.chain_name, len(lokalni), len(site), postavki.grad)
    red = asyncio.Semaphore(max(1, klasa.store_concurrency))
    ishod.prodavnici = list(
        await asyncio.gather(
            *(_procitaj_prodavnica(klasa, p, postavki, red) for p in lokalni)
        )
    )
    return ishod


async def procitaj_se(postavki: Postavki, samo: tuple[str, ...] = ()) -> list[IshodSinjir]:
    """Ги чита сите синџири од поставките (или само наведените), напоредно."""
    kodovi = [k for k in postavki.sinjiri if not samo or k in samo]
    return list(await asyncio.gather(*(_procitaj_sinjir(k, postavki) for k in kodovi)))
