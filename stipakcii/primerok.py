"""Зачувува примерок од страница: `python -m stipakcii.primerok <адреса>`.

За нов маркет прво треба да се види како изгледа неговиот ценовник. Ова ја
презема страницата еднаш, учтиво, и ја запишува во `primeroci/` заедно со
основните податоци за одговорот. Читач се пишува врз примерокот, не напамет.
"""

from __future__ import annotations

import asyncio
import hashlib
import re
import sys
from pathlib import Path
from urllib.parse import urlsplit

import httpx

from stipakcii.postavki import Settings

NAJMNOGU_BAJTI = 1_500_000


async def snimi(adresa: str, papka: Path) -> Path:
    delovi = urlsplit(adresa)
    if delovi.scheme not in ("http", "https") or not delovi.hostname:
        raise SystemExit(f"не е веб-адреса: {adresa!r}")

    mreza = Settings()
    async with httpx.AsyncClient(
        headers={"User-Agent": mreza.scraper_user_agent, "Accept-Language": "mk,en;q=0.8"},
        timeout=mreza.scraper_timeout_seconds,
        follow_redirects=True,
    ) as klient:
        odgovor = await klient.get(adresa)

    telo = odgovor.content
    vid = odgovor.headers.get("content-type", "")
    nastavka = ".json" if "json" in vid else ".pdf" if telo.startswith(b"%PDF") else ".html"
    oznaka = hashlib.sha256(adresa.encode()).hexdigest()[:8]
    ime = re.sub(r"[^a-z0-9]+", "-", delovi.hostname.lower()).strip("-")
    papka.mkdir(parents=True, exist_ok=True)
    pateka = papka / f"{ime}-{oznaka}{nastavka}"
    pateka.write_bytes(telo[:NAJMNOGU_BAJTI])
    (papka / f"{ime}-{oznaka}.txt").write_text(
        f"adresa: {adresa}\nkrajna_adresa: {odgovor.url}\nstatus: {odgovor.status_code}\n"
        f"content-type: {vid}\ngolemina: {len(telo)} бајти"
        f"{' (скратено)' if len(telo) > NAJMNOGU_BAJTI else ''}\n",
        encoding="utf-8",
    )
    return pateka


async def _site(adresi: list[str]) -> None:
    for adresa in adresi:
        print(await snimi(adresa, Path("primeroci")))
        await asyncio.sleep(Settings().scraper_delay_seconds)


if __name__ == "__main__":
    # Една или повеќе адреси, одделени со празно место.
    adresi = " ".join(sys.argv[1:]).split()
    if not adresi:
        raise SystemExit("употреба: python -m stipakcii.primerok <адреса> [<адреса> ...]")
    asyncio.run(_site(adresi))
